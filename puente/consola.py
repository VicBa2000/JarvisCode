"""La consola de JC-0008: ver la sesion en vivo y poder tomar el control.

Es el tercer canal, y el unico que no depende de que el usuario este
lejos. Sirve una pagina en `127.0.0.1` y nada mas: sin puerto expuesto,
sin telemetria, sin dependencias fuera de la biblioteca estandar.

LO QUE MUESTRA ES CONTENIDO OBSERVADO. Todo lo que sale de la sesion
puede venir de un archivo o de la web, asi que la pagina lo pinta con
`textContent` y jamas con `innerHTML`. Que la consola ejecutara algo que
Claude Code leyo por ahi seria la puerta fallando en el unico sitio donde
el usuario cree estar mirando la verdad.

LO QUE EL USUARIO ESCRIBE AQUI ES UNA ORDEN LEGITIMA, con la misma
autoridad que su voz. Es el, en su maquina. No se filtra ni se valida
contra allowlist: seria tratar al dueno como a un intruso.

LA CONSOLA NUNCA CONTESTA SOLA. Ni lo obvio, ni un "si". Solo reenvia lo
que una persona pulsa. En cuanto empiece a decidir, hay dos agentes.

LAS DOS FORMAS TIENEN QUE NOMBRAR LO MISMO. La frase corta que se
locutara y lo que se ve aqui salen de la misma `Puerta`, y la pagina
ensena SIEMPRE el `input` crudo debajo de la version legible. Si
divergieran, el usuario aprobaria una cosa y se ejecutaria otra.
"""

from __future__ import annotations

import json
import queue
import secrets
import threading
import time
import webbrowser
from dataclasses import asdict, is_dataclass
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from nucleo.carcasa import Gestos
from puente.protocolo import (
    AbreBloque,
    AbreMensaje,
    CierraBloque,
    Trozo,
    Fin,
    Inicio,
    Limite,
    LineaIlegible,
    Pensamiento,
    Pregunta,
    Puerta,
    Reintento,
    ResultadoHerramienta,
    SeguidorDeTarea,
    Texto,
    UsoHerramienta,
)
from puente.camara import Camara
from puente.producido import Producido
from puente.sesion import Caida, Resuelta, Sesion, SinPuerta

PAGINA = Path(__file__).resolve().parent / "consola.html"
PAGINA_AJUSTES = Path(__file__).with_name("ajustes.html")

ADIOS_S = 1.2
"""Cuanto se espera entre la despedida y cerrarse, escrito en la consola.

>>> NO ES UN NUMERO MEDIDO, Y SE DICE <<<
Es el tiempo de LEER una frase corta, no el de que llegue: el aviso viaja
por SSE a `127.0.0.1` y eso son milisegundos. Puesto por lo que tarda la
voz en decir "hasta luego", que es el flujo con el que el usuario pidio
que cuadrara. Mas corto y la despedida parpadea; mas largo y parece que
no le has dado.
"""
FUENTES = Path(__file__).resolve().parent / "fuentes"
TEMA = Path(__file__).resolve().parent / "tema.css"
FUENTES_CSS = Path(__file__).resolve().parent / "fuentes.css"
HOJAS_TEMA = Path(__file__).resolve().parent / "temas"
"""Las hojas de MAQUETA, una por tema (2026-08-29).

>>> POR QUE HAY UNA CARPETA APARTE Y NO MAS `tema.css` <<<
Hasta el rediseño de los temas, un tema eran SOLO variables de color, y
un test lo sostenia. Los tres temas nuevos necesitan mover cosas de
sitio -- barras de estado en `hacker`, una columna menos en `despacho`,
una barra lateral en `nexo` --, asi que la maqueta deja de estar
prohibida y pasa a tener su sitio. `tema.css` sigue siendo tokens y solo
tokens: es la hoja que lee TODO el mundo, y una regla de `display` ahi
dentro tocaria tambien al tema `jarvis`, que es el unico que ya estaba
aceptado en pantalla.

`jarvis` NO tiene hoja, y es deliberado: sin archivo no hay nada que
pueda romperlo por accidente.
"""

TEMAS = ("jarvis", "hacker", "despacho", "nexo")
"""Los temas que `tema.css` sabe pintar. El orden es el de la UI.

>>> ESTA TUPLA ES ADEMAS UNA LISTA BLANCA, Y ESO NO ES ADORNO <<<
El valor elegido se ESTAMPA DENTRO DEL HTML que servimos. Un valor que
llegase tal cual desde `config/ajustes.yaml` podria cerrar el atributo y
abrir una etiqueta -- o sea inyeccion en nuestra propia consola, que es
la pantalla desde la que se aprueba lo que Claude Code hace. Se comprueba
contra esta tupla y lo que no este en ella se ignora, que ademas es la
respuesta correcta para un archivo escrito a mano con una errata.

"jarvis" no estampa nada: es `:root`, o sea el tema de siempre. Asi una
pagina servida sin este codigo -- o abierta desde disco -- se sigue
pintando bien.
"""

# Cuanto silencio hace falta para decir "no se si sigue vivo". No es un
# limite de la herramienta: es cuando MERECE LA PENA contarselo a una
# persona. Medido: una sesion sin red puede callar ~180 s reintentando,
# asi que por debajo de eso el silencio no prueba nada.
SILENCIO_DUDOSO_S = 25.0


def _plano(valor: Any) -> Any:
    """Anything a dataclass can hold, turned into something JSON accepts.

    `asdict()` recurses into nested dataclasses but leaves Enums as Enum
    objects, and `json.dumps` refuses those. It cost a live bug: an
    auto-approved gate carries a `Veredicto`, so the moment the policy
    allowed something with a browser attached, that client's stream died
    -- and only that client's. Nothing in the fixtures produces a
    `Resuelta`, so the fast tests never saw it; the end-to-end one did.
    """
    if isinstance(valor, Enum):
        return valor.value
    if isinstance(valor, dict):
        return {k: _plano(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_plano(v) for v in valor]
    return valor


# Las claves cuyo VALOR es texto para una persona. Todo lo demas que
# viaja en estos JSON son identificadores, rutas y numeros, y traducir
# una ruta seria estropearla.
CLAVES_DE_TEXTO = frozenset({
    "motivo", "coste", "descripcion", "detalle", "aviso", "que_puede",
    # El veredicto de probar el micro o el altavoz. Es la frase que hace
    # SEGURO dejar elegir dispositivo -- "por ahi no entra nada, lo mas
    # probable es que este silenciado" --, o sea justo la que no puede
    # quedarse en otro idioma: quien la lee esta tratando de averiguar
    # por que no le oyen.
    "mensaje",
})


# Los eventos del troceo. NO se pintan en el flujo ni se le pasan a la
# voz: son el mismo hecho llegando a plazos, y el `assistant` que viene
# detras trae lo mismo entero. Alimentan la camara y nada mas. Pintarlos
# llenaria el registro de 30 renglones por turno que no dicen nada nuevo.
DEL_TROCEO = (AbreMensaje, AbreBloque, Trozo, CierraBloque)

CLASES_DE_ESTADO = frozenset({"Tarea", "Producido"})
"""Lo que viaja por el mismo cable que los eventos y NO es un evento.

Un evento cuenta algo que paso y se acumula; esto dice como estan las
cosas AHORA y solo importa el ultimo. Ver `Consola._ultimo_estado`.
"""

CLASES_TRANSITORIAS = frozenset({"Plano", "Cuadro"})
"""El POV. Ni se acumula ni se guarda: es lo que se esta viendo.

A diferencia de `CLASES_DE_ESTADO`, de esto no se guarda ni el ultimo:
una pestaña que llega tarde no quiere el ultimo `Cuadro` (una silaba
suelta) sino el plano ENTERO, y ese lo arma la camara al vuelo en
`_suscribir`. Guardar aqui seria tener el mismo dato en dos sitios.
"""


def traducir_salida(cuerpo: Any) -> Any:
    """Lo que el servidor manda a la pagina, en el idioma de la pantalla.

    >>> ESTO ES LA MITAD QUE FALTABA, Y ERA LA IMPORTANTE <<<
    Traducir `consola.html` deja fuera todo lo que la pagina PINTA a
    partir de lo que le manda el servidor. Y ahi vive el texto mas
    importante del programa: el MOTIVO de una peticion de permiso
    ("borra archivos", "escribe fuera del directorio de la sesion") lo
    fabrica `puente/politica.py`, y es lo que el usuario lee justo antes
    de autorizar. Con la pagina en ingles y el motivo en español, la
    pregunta se contesta a medias.

    >>> SE HACE EN LA SALIDA, NO EN CADA SITIO QUE CONSTRUYE UN JSON <<<
    Hay una veintena de `return {"ok": False, "motivo": ...}` repartidos
    por este archivo. Envolverlos uno a uno garantiza que el proximo se
    escriba sin envolver, y como una cadena sin traducir se sirve tal
    cual, ese olvido no daria ningun error: solo un mensaje en español
    en mitad de una pantalla en ingles. Aqui pasa TODO, incluido lo que
    todavia no existe.

    Y es seguro sobre lo que no es copia: la traduccion es una BUSQUEDA
    que devuelve la entrada intacta cuando no encuentra nada, asi que una
    ruta o un nombre de servidor que caiga en una de estas claves sale
    exactamente como entro.
    """
    from nucleo.textos import idioma, mensaje

    if idioma() != "en":
        return cuerpo
    return _traducir_hondo(cuerpo, mensaje)


def _traducir_hondo(dato: Any, traduce: Any) -> Any:
    if isinstance(dato, dict):
        return {k: (traduce(v) if k in CLAVES_DE_TEXTO and isinstance(v, str)
                    else _traducir_hondo(v, traduce))
                for k, v in dato.items()}
    if isinstance(dato, list):
        return [_traducir_hondo(v, traduce) for v in dato]
    return dato


def a_json(evento: Any) -> dict[str, Any]:
    """One event as something the page can render. Never loses the type."""
    cuerpo: dict[str, Any] = {"clase": type(evento).__name__}
    if is_dataclass(evento):
        for clave, valor in asdict(evento).items():
            cuerpo[clave] = _plano(valor)
    if isinstance(evento, ResultadoHerramienta):
        # >>> EL base64 NO SALE DE AQUI <<<
        # `asdict` se las lleva enteras, y esto va a CADA cliente
        # conectado por SSE. Una captura de viewport son cientos de KB;
        # dos pestanas abiertas y un turno de Blender es un problema de
        # memoria por una comodidad que nadie pidio. La pagina recibe
        # cuantas hubo y las pide por id a `/pieza/<id>`.
        cuerpo["imagenes"] = len(evento.imagenes)
    if isinstance(evento, Puerta):
        cuerpo["crudo"] = json.dumps(evento.entrada, ensure_ascii=False,
                                     indent=1)
        cuerpo["orden_shell"] = evento.orden_shell
    if isinstance(evento, Pregunta):
        cuerpo["enunciados"] = list(evento.enunciados)
    if isinstance(evento, Limite):
        cuerpo["porcentaje"] = evento.porcentaje
        cuerpo["agotado"] = evento.agotado
        cuerpo["es_semanal"] = evento.es_semanal
        # >>> LOS DOS RELOJES, Y `None` VIAJA COMO `null` <<<
        # `asdict` ya deja las dos ventanas puestas; lo que falta es el
        # porcentaje, que es una propiedad y no un campo. Se anaden solo
        # si la ventana vino: una ventana ausente tiene que llegar a la
        # pagina como `null` para que escriba "?" y no un cero.
        for nombre, ventana in (("sesion", evento.sesion),
                                ("semana", evento.semana)):
            if ventana is None:
                cuerpo[nombre] = None
                continue
            # >>> `caducada` VIAJA, Y NO ES UN ADORNO <<<
            # Se calcula AQUI y no al interpretar el evento porque
            # depende del reloj: `/estado` se pide cada 2 s, o sea que
            # esto se vuelve a evaluar sin que llegue nada nuevo. Es lo
            # unico que hace que una ventana ya reiniciada deje de
            # ensenar la cifra de antes sin tener que reiniciar Jarvis.
            cuerpo[nombre] = {"utilizacion": ventana.utilizacion,
                              "reinicia_en": ventana.reinicia_en,
                              "porcentaje": ventana.porcentaje,
                              "caducada": ventana.caducada()}
    if isinstance(evento, Reintento):
        cuerpo["es_el_ultimo"] = evento.es_el_ultimo
    return cuerpo


class Consola:
    """Fan-out from one session to however many browser tabs are open."""

    def __init__(self, sesion: Sesion, puerto: int = 8731,
                 suelo: Any = None) -> None:
        self.sesion = sesion
        self.puerto = puerto
        self.ficha = secrets.token_urlsafe(24)
        """Un secreto por sesion, incrustado en la pagina que servimos.

        DE QUE PROTEGE, Y DE QUE NO. Protege del navegador: una pagina
        web cualquiera puede hacer `POST http://127.0.0.1:8731/turno` --
        medido el 2026-08-24, el servidor lo aceptaba con `Origin` ajeno
        y `Content-Type: text/plain`, que no dispara preflight -- y aunque
        CORS le impida LEER la respuesta, no le hace falta: el turno se
        habria ejecutado con la autoridad entera del usuario. La ficha lo
        corta porque esa pagina no puede leerla.

        NO protege de otro proceso local, y no pretende: quien ya corre
        en esta maquina con tu cuenta puede lanzar `claude` el mismo. Ese
        no es un limite que este servidor pueda poner.
        """
        self.gestos = Gestos()
        """Los gestos de la carcasa, compartidos con la voz.

        Se crea VACIO aqui y lo rellena `escritorio/` si hay ventana. El
        objeto es el mismo que ve el `Bucle` (`puente/__main__.py` lo
        pasa a los dos), que es lo que impide que "apagate" haga cosas
        distintas dicho y escrito.
        """
        self.tarea = SeguidorDeTarea()
        self._tarea_vista: tuple[str, str] = ("", "")
        self._tarea_desde: float = time.time()
        self._cerrojo_latido = threading.Lock()
        """Lo ultimo que se mando en un latido, y cuando.

        `SeguidorDeTarea` sabe QUE se hace, no DESDE CUANDO -- y el reloj
        del cabezal es la mitad de lo que hace que se sienta en directo.
        Vive aqui y no alli porque es una propiedad de ESTA pantalla: la
        voz usa el mismo seguidor y no tiene reloj que pintar.
        """
        self.camara = Camara()
        """El POV: lo que se esta haciendo AHORA, para verlo.

        Se alimenta en `bombear` como los otros dos, y por la misma
        razon: hay que ver el flujo entero y en orden. Aqui ademas es
        literal -- un trozo solo significa algo detras del bloque que
        abrio, y el indice de bloque REINICIA en cada mensaje.
        """
        self.producido = Producido()
        """Lo que la sesion deja detras, para que se pueda VER.

        Se alimenta en `bombear` por la misma razon que `tarea`: hace
        falta ver el flujo ENTERO y en orden, porque una pieza solo
        existe cuando su `UsoHerramienta` se empareja con un
        `ResultadoHerramienta` sin error. La pagina ve los eventos
        sueltos y no podria emparejarlos.
        """
        """Que se esta haciendo AHORA, para la barra de arriba.

        Dos fuentes y en este orden: la ORDEN del usuario en cuanto la
        da -- literal, sin parafrasear, que es lo que le deja comprobar
        que se le entendio -- y luego lo que Claude Code vaya contando
        que hace. Al cerrar el turno se queda vacia: una barra que
        congela la ultima tarea para siempre dice que se esta trabajando
        cuando no.
        """

        self.al_primer_turno: Any = None
        """Callable que abre la sesion la primera vez que hace falta.

        EL PUENTE ARRANCA MUDO. Con la app puesta en el inicio de Windows,
        abrir Claude Code en cada boot cuesta un proceso de 337 MB vivo
        todo el dia y, cada vez que el binario se actualiza solo
        (`autoUpdatesChannel: latest`), un turno entero en el senuelo.
        Nada de eso hace falta hasta que hay una orden.

        Lo que SI esta encendido desde el arranque es la escucha, y es
        100 % local: wake word, VAD y STT corren en esta maquina. A la
        nube no sale nada hasta que se ha reconocido una orden -- o sea
        que de la maquina solo sale algo cuando el usuario habla, no
        por tener el asistente puesto.

        `None` significa que quien monto la consola ya trajo la sesion
        abierta, que es lo que hacen los tests.
        """
        self.suelo = suelo
        """The JC-0007 floor this session runs under, or None.

        It is shown on the page for one reason: a floor nobody can see is
        indistinguishable from no floor at all, and this project already
        decided that a decorative guard is worse than none. `None` is
        rendered as "sin suelo", never hidden.
        """
        self.escalado: Any = None
        self.buzon: Any = None
        """JC-0016: lo que recoge de Telegram, para poder ponerlo al dia
        cuando el usuario cambia el interruptor sin reiniciar."""
        """El escalado a Telegram (JC-0006), si el lanzador lo monto.

        `None` significa que no hay tercer canal, y eso NO es un fallo:
        es un canal que no se puso. La pagina lo enseña como tal.
        """
        self.voz: Any = None
        """El bucle de voz, si el lanzador lo encendio (`--voz`).

        >>> LA PANTALLA TIENE QUE PODER DECIR SI TE ESTA ESCUCHANDO <<<
        Hasta el 2026-08-26 la consola no sabia NADA de la voz: cero
        menciones en `consola.html`. O sea que la unica pantalla del
        asistente no podia contestar la pregunta mas basica que tiene un
        asistente de voz -- "¿me oye ahora mismo?" --, y el usuario solo
        podia saberlo hablandole a ver que pasaba.

        `None` significa que arranco sin voz, y eso se pinta como tal.
        """
        self.oyentes: list[Any] = []
        """Quien quiere los eventos TIPADOS, no el JSON de la pagina.

        Hoy es la voz (`voz/bucle.py`). Se registran aqui y no se
        suscriben a la sesion porque `Sesion.eventos()` tiene un solo
        consumidor -- ver `_avisar_oyentes`.
        """
        self.fallos_de_oyentes: list[str] = []
        """Lo que reventaron los oyentes, para que se pueda ver.

        Se guarda en vez de tragarse: un canal que deja de funcionar en
        silencio es lo mismo que un canal que no existe, y este proyecto
        ya decidio que eso es peor que no tenerlo.
        """
        self.al_reiniciar: Any = None
        """Quien sabe reiniciar Jarvis entero, si alguien sabe.

        >>> `None` NO ES UN FALLO: ES QUE NADIE PUEDE <<<
        Reiniciar significa matar este proceso y levantar otro con el
        MISMO argv, y eso solo lo puede hacer quien conoce ese argv: la
        carcasa de escritorio, que lo captura antes de que
        `escritorio/__main__.py` lo machaque con el del puente. Lanzado
        a mano desde una terminal (`-m puente`) no hay nadie ahi, y
        entonces el boton se pinta APAGADO y diciendo por que.

        Fingir que se puede -- reiniciar "a medias", recargar la pagina y
        llamarlo reinicio -- seria un mock en produccion, y
        ademas del tipo caro: el usuario creeria aplicado un ajuste que
        sigue sin aplicarse.
        """
        self.historia: list[dict[str, Any]] = []
        self._ultimo_estado: dict[str, dict[str, Any]] = {}
        """Lo ultimo de cada cosa que es ESTADO y no un renglon del log.

        >>> LA TIRA Y EL CABEZAL NO SON EVENTOS, AUNQUE VIAJEN COMO UNO <<<
        `historia` es lo que se le replica a una pestaña que llega tarde,
        y para eso un log esta bien: se repinta el turno entero. Pero de
        estos dos lo unico que se quiere es el ULTIMO -- replicar los
        cuarenta latidos de un turno seria pasarle a la pestaña nueva una
        pelicula del reloj, y replicar cada version de la tira la haria
        crecer y encogerse sola al abrirla. Se guarda uno de cada y se
        manda al final del replay, que es donde queda el estado de ahora.
        """
        self._clientes: list[queue.Queue[dict[str, Any] | None]] = []
        self._cerrojo = threading.Lock()
        self._servidor: ThreadingHTTPServer | None = None

    # --- el flujo ---------------------------------------------------------

    def bombear(self) -> None:
        """Drain the session into every open tab. Runs on its own thread."""
        for evento in self.sesion.eventos():
            # La barra de TAREA. Se alimenta AQUI y no en la pagina
            # porque la regla ("un `Texto` es narracion si detras viene
            # una herramienta") necesita ver el flujo entero en orden, y
            # el navegador solo ve lo que le llega suelto.
            # >>> LOS TROZOS NO SON UN EVENTO MAS <<<
            # Van solo a la camara: ni al registro, ni a la voz, ni al
            # flujo de la pagina. Son el mismo hecho llegando a plazos y
            # el `assistant` de detras lo trae entero, asi que pintarlos
            # seria repetir treinta veces por turno lo que ya se ve una.
            if isinstance(evento, DEL_TROCEO):
                cambio = self.camara.ve(evento)
                if cambio is not None:
                    self._difundir(cambio)
                continue
            self.tarea.ve(evento)
            nueva = self.producido.ve(evento)
            cambio = self.camara.ve(evento)
            self._avisar_oyentes(evento)
            self._difundir(a_json(evento))
            if cambio is not None:
                self._difundir(cambio)
            # EN ESTE ORDEN, y no da igual: el cabezal dice lo que se
            # esta haciendo AHORA, o sea despues de este evento. Mandarlo
            # antes pintaria la tarea anterior junto al evento nuevo.
            self._latir()
            if nueva is not None:
                self._difundir_producido()
        self._difundir({"clase": "FinDelFlujo"})

    # --- el cabezal en directo (v3, 2026-09-02) --------------------------
    #
    # >>> ESTO CUELGA DE LOS EVENTOS, NO DEL SONDEO DE `/estado` <<<
    # Es el punto 1 de los cuatro que dejo escritos la v2, y es el que
    # decide si la pantalla se siente viva: `/estado` se pide cada 2 s, y
    # un cabezal que va hasta dos segundos por detras de lo que pinta el
    # registro se siente MAS muerto que no tener ninguno -- el usuario ve
    # la linea nueva del flujo y el cabezal todavia contando lo anterior.
    #
    # Se manda solo CUANDO CAMBIA. Un latido por evento seria ruido: hay
    # turnos con cientos, y la pagina repintaria lo mismo.

    def _latir(self) -> None:
        """Manda la tarea si ha cambiado. Nada mas.

        >>> Y EL "SI HA CAMBIADO" VA BAJO CERROJO, QUE NO ES UN DETALLE <<<
        Aqui entran DOS hilos: el que bombea el flujo y el que anuncia un
        turno (la voz, la consola o Telegram). Sin cerrojo, los dos pueden
        leer el mismo `_tarea_vista` y uno de los dos apuntar su cambio
        sin mandarlo. Y el precio de perder UN latido no es perder un
        fotograma: es que `_tarea_vista` ya dice lo nuevo, asi que **el
        cabezal se queda con la frase vieja hasta el siguiente cambio**,
        que puede no llegar en todo el turno. Un cerrojo propio y no
        `_cerrojo`, que lo toma `_difundir` y no es reentrante.
        """
        with self._cerrojo_latido:
            ahora = (self.tarea.tarea, self.tarea.origen)
            if ahora == self._tarea_vista:
                return
            self._tarea_vista = ahora
            self._tarea_desde = time.time()
        self._difundir({
            "clase": "Tarea",
            "tarea": self.tarea.tarea,
            "tarea_origen": self.tarea.origen,
            # >>> ABSOLUTO, Y NO "HACE N SEGUNDOS" <<<
            # Una pestaña que se abre a mitad de turno replica la
            # historia entera de golpe: con un "hace N" el reloj
            # arrancaria de cero y diria que el turno acaba de empezar.
            # El navegador y esto son el MISMO reloj -- 127.0.0.1 --,
            # asi que la epoca vale y no hay que corregir nada.
            "desde": self._tarea_desde,
            "trabajando": bool(self.tarea.tarea),
        })

    def _difundir_producido(self) -> None:
        """La tira entera, no la pieza suelta.

        >>> POR QUE VA LA LISTA COMPLETA Y NO LO QUE ACABA DE ENTRAR <<<
        Porque la lista NO es la suma de lo que llego: el mismo archivo
        escrito tres veces es UNA pieza (se quita la anterior), y una
        imagen que se suelta por peso se convierte en lapida. Mandando la
        pieza suelta, la pagina tendria que repetir esas dos reglas para
        no pintar duplicados -- y dos copias de una regla es como
        divergieron los tres normalizadores de `voz/`. Aqui la regla vive
        en un sitio y la pagina pinta lo que le den.

        Cabe de sobra: son 60 entradas como mucho, sin un byte de base64
        (las imagenes se piden por `/pieza/<id>`), y solo se manda cuando
        aterriza algo.
        """
        self._difundir({"clase": "Producido", **self.producido.a_json()})

    def _avisar_oyentes(self, evento: Any) -> None:
        """Pasa el evento TIPADO a quien lo pidiera. Hoy, la voz.

        >>> POR QUE LA VOZ NO TIRA DE `sesion.eventos()` ELLA MISMA <<<
        Es UNA cola con UN consumidor: quien saca un evento se lo lleva.
        Con dos consumidores, cada evento caeria en uno de los dos al
        azar -- la consola pintaria la mitad de las respuestas y la voz
        locutaria la otra mitad --, y por fuera pareceria un problema de
        red. Asi que se bombea aqui, en un sitio, y se reparte.

        Y se reparte con red debajo: un oyente que reviente NO puede
        parar el bombeo. Si la voz se cae, la consola tiene que seguir
        pintando y las puertas tienen que seguir llegando; al reves, el
        usuario se quedaria sin los dos canales por un fallo de uno.
        """
        for oyente in list(self.oyentes):
            try:
                oyente(evento)
            except Exception as exc:  # noqa: BLE001
                self.fallos_de_oyentes.append(f"{type(exc).__name__}: {exc}")

    def anuncia_turno(self, texto: str, origen: str) -> None:
        """Enseña en pantalla lo que el usuario acaba de pedir.

        >>> POR QUE EXISTE (2026-08-27), Y FALTABA SOLO POR VOZ <<<
        Al dar una instruccion hablada hace falta VERLA escrita en la
        consola, para saber que se entendio bien lo que se dijo.
        El evento existia desde JC-0008, pero lo emitia el endpoint
        `/turno` -- o sea el canal que YA se ve, porque lo acabas de
        teclear. El de voz, que es el unico donde no sabes lo que
        entendio, mandaba sin anunciar.

        Vive aqui y no en los dos sitios que lo usan: si el de voz y el
        de texto pintasen cada uno lo suyo, acabarian enseñando cosas
        distintas para lo mismo.
        """
        # >>> SOLO UNA FRASE DEL USUARIO MUEVE LA FRANJA <<<
        # El ritual de ADR-0029 ("hola, en que nos quedamos?") lo manda
        # Jarvis solo al cambiar de proyecto. Es el flujo correcto y se
        # pinta en el flujo, pero la franja existe para que compruebes
        # que se te ENTENDIO, y una frase nuestra ahi no comprueba nada
        # -- ademas de tapar la tuya, que es la que querias ver.
        if origen != "ritual":
            self.tarea.orden(texto, origen=origen)
        self._difundir({"clase": "TurnoDelUsuario", "texto": texto,
                        "origen": origen})
        # El cabezal arranca AQUI y no al primer evento de la sesion: el
        # turno empieza cuando el usuario habla, y entre eso y el primer
        # `Texto` de Claude Code hay segundos de arranque en frio (~3,5 s
        # medidos en JC-0003). Un cabezal que se enciende al final de esa
        # espera deja muerta justamente la parte en la que uno se
        # pregunta si le ha oido.
        self._latir()

    def glosario(self) -> dict[str, Any]:
        """Las frases que Jarvis se queda antes de mandarlas al cerebro.

        Nace de una peticion del 2026-09-05: un glosario de las palabras
        clave que Jarvis se queda y reconoce.
        Sale de `voz.glosario`, que las genera de quien intercepta y
        tiene un test que pasa cada frase por el interprete real -- asi
        la lista no puede envejecer sin que salte algo.
        """
        from voz.glosario import glosario

        return {"entradas": [e.a_json() for e in glosario()]}

    def de_la_ventana(self, texto: str) -> bool:
        """"abrete" / "cierrate" / "apagate" escritos. Si se ocupo, True.

        >>> SE REPORTO EL 2026-09-05 <<<
        Las ordenes como "apagate" se interceptaban bien DICHAS -- Jarvis
        se apagaba, que es lo correcto -- y escritas en la consola se le
        pasaban directas a Claude.
        Y era exacto: gastaba un turno entero, Claude Code contestaba una
        despedida educada y Jarvis seguia vivo.

        El decisor es `voz.ventana.atender`, EL MISMO que llama la voz.
        Aqui se queda lo unico que no se comparte: PINTAR. Es la misma
        forma que `cambiar_de_proyecto`, y por la misma leccion del
        09-03.

        >>> "para" NO ENTRA AQUI, Y LO DECIDIO EL USUARIO <<<
        Escrita es una preposicion normal ("para el servidor", "para que
        veas") y comersela seria tragarse una orden buena. La consola ya
        tiene Esc, que corta lo mismo y esta rotulado.
        """
        from voz.ventana import Hecho, atender

        r = atender(texto, self.gestos,
                    interrumpir=(self.sesion.interrumpir
                                 if getattr(self.sesion, "viva", False)
                                 else None))
        if not r.se_ocupo:
            return False

        if r.hecho is Hecho.SIN_CARCASA:
            self.avisa("No tengo ventana que mover: Jarvis va sin carcasa. "
                       "Cierralo desde la terminal donde lo lanzaste."
                       if not r.es_el_final else
                       "No me puedo apagar solo: Jarvis va sin carcasa. "
                       "Cierralo desde la terminal donde lo lanzaste.")
        elif r.hecho is Hecho.ROTO:
            self.avisa(f"No he podido mover la ventana: {r.error}")
        elif r.hecho is Hecho.MOSTRADA:
            # >>> ESTA HAY QUE DECIRLA, Y POR VOZ NO <<<
            # Por voz "abrete" se contesta corto porque el resultado se
            # VE: la ventana aparece delante. Escribiendola, la ventana
            # YA estaba delante -- es donde estas tecleando --, asi que
            # no se mueve nada y sin esto se lee igual que si Jarvis
            # hubiera ignorado la orden. Es el mismo motivo por el que la
            # voz si contesta al apagarse: un resultado que no se ve
            # necesita palabras.
            self.avisa("Ya estoy delante: esta ventana es la que pediste.")
        elif r.hecho is Hecho.ESCONDIDA:
            # Esta SI se ve -- la ventana desaparece --, pero el aviso se
            # manda igual porque `avisa` tambien escribe en el diario del
            # arranque, y ahi queda por que se escondio.
            self.avisa("Me escondo en la bandeja. Sigo trabajando.")
        elif r.hecho is Hecho.APAGANDO:
            # >>> SE DESPIDE Y LUEGO SE VA, IGUAL QUE POR VOZ <<<
            # Se reporto el 2026-09-05: el "apagate" escrito cerraba de
            # golpe, y no deberia -- tiene que seguir el mismo flujo que
            # dicho, donde Jarvis se despide antes de cerrarse.
            #
            # Y lo peor es que estaba escrito aqui que daba igual. El
            # comentario decia que el aviso "puede no llegar a pintarse
            # -- y da igual: aqui el resultado SE VE". Es falso, y por
            # dos motivos: el aviso viaja por SSE y `apagar()` mata el
            # proceso en el mismo microsegundo, asi que no se veia NUNCA;
            # y una ventana que desaparece de golpe se lee igual que un
            # cuelgue, que es exactamente el argumento por el que la voz
            # SI se despide. El canal cambia, el motivo no.
            #
            # >>> POR ESO NO SE APAGA AQUI: SE PROGRAMA <<<
            # `apagar` no vuelve. Llamandolo en linea no sale ni el aviso
            # ni la respuesta HTTP del turno -- el navegador ve la
            # conexion cortarse, que es la peor forma de enterarse. Se
            # deja para dentro de un momento: el handler contesta, el SSE
            # llega, se lee la despedida, y entonces se cierra.
            self.avisa("Hasta luego. Cierro la sesion de Claude Code y me "
                       "apago.")
            threading.Timer(ADIOS_S, self._apagarse_de_verdad).start()
        return True

    def _apagarse_de_verdad(self) -> None:
        """Lo que corre cuando ya te has podido leer la despedida.

        Va en un hilo aparte, y eso ya estaba probado: la voz llama a
        este mismo gesto desde el hilo del `Bucle` desde el 2026-08-27.
        """
        try:
            self.gestos.apagar()
        except Exception as exc:  # noqa: BLE001
            # Si no se puede apagar hay que DECIRLO: el usuario acaba de
            # leer "hasta luego" y se quedaria mirando una ventana viva.
            self.avisa(f"No he podido apagarme: {exc}")

    def cambiar_de_proyecto(self, texto: str) -> tuple[str, str]:
        """ADR-0029 desde la CONSOLA. Devuelve (que mandar, de quien es).

        >>> LA MISMA FRASE DABA RESULTADOS DISTINTOS (2026-09-03) <<<
        Se reporto usandolo: la instruccion por consola y la instruccion
        por voz producian resultados diferentes. Y era exacto -- "continua
        con el proyecto X, checa que avance tiene..." abria la carpeta de
        ese proyecto dicha, y escrita dejaba
        la sesion en la carpeta base con Claude Code buscando
        `**/*faro*` ahi dentro. Sin un solo error: el cerebro es capaz,
        asi que hace algo plausible en el sitio que no es.

        La causa era que la interceptacion vivia SOLO en `voz/bucle.py`.
        Y no era una decision: el razonamiento de ADR-0029 habla de la
        NATURALEZA de la orden -- Claude Code no puede mudar su propia
        sesion --, y eso no depende de si la dices o la tecleas.

        DEVUELVE EL TEXTO QUE TIENE QUE VIAJAR Y DE QUIEN ES, y ("", "")
        si no hay que mandar nada. Asi el que llama no tiene que saber si
        hubo cola, ritual o una negativa: eso lo decide
        `voz.proyecto.atender`, que es el MISMO sitio que consulta la voz.

        >>> EL ORIGEN NO ES DECORADO <<< La cola ES una frase tuya y el
        ritual NO -- lo escribimos nosotros. La voz ya los separa asi
        (`"voz"` contra `"ritual"`), y pintar el ritual como tuyo fue un
        fallo que se corrigio mirandolo el 2026-08-27: el ritual esta
        bien, pero no lo dijo el usuario.
        """
        from voz.proyecto import Cambio, atender, primera_pregunta

        r = atender(texto, self.sesion)
        if not r.se_ocupo:
            return texto, "consola"

        if r.cambio is Cambio.SIN_NOMBRE:
            self.avisa("¿Que proyecto? No he entendido cual.")
        elif r.cambio is Cambio.DESCONOCIDO:
            self.avisa(f"No tengo ningun proyecto registrado que se llame "
                       f"'{r.nombre}'. Se añaden en Ajustes.")
        elif r.cambio is Cambio.VARIOS:
            self.avisa(f"Hay {len(r.candidatos)} que casan con '{r.nombre}': "
                       f"{', '.join(r.candidatos)}. Di cual.")
        elif r.cambio is Cambio.SIN_CARPETA:
            self.avisa(f"'{r.proyecto.alias}' esta registrado pero su "
                       f"carpeta ya no esta en el disco.")
        elif r.cambio is Cambio.ROTO:
            self.avisa(f"No he podido cambiar de proyecto: {r.error}")
        else:
            # LA CARPETA, no solo el alias: dos proyectos con nombres
            # parecidos es donde esto se equivoca caro. Es la condicion 1
            # de ADR-0029 y vale igual escrita que dicha.
            self.avisa(f"Abro {r.proyecto.alias}: {r.proyecto.carpeta}")
            # La cola SUSTITUYE al ritual, no va delante. Es la misma
            # regla que la voz, y sale del mismo sitio.
            if r.cola:
                return r.cola, "consola"
            # >>> EL RITUAL LO ESCRIBE EL USUARIO (2026-09-05) <<<
            # Se pasa el PROYECTO porque cada uno puede tener el suyo, y
            # la resolucion entera vive en `primera_pregunta`: repartirla
            # entre los dos canales es exactamente lo que se arreglo el
            # 09-03. Vacio significa "abre y no digas nada", y entonces
            # esto devuelve lo mismo que una negativa -- nada que mandar
            # --, con la diferencia de que aqui ya se ha dicho "Abro X".
            ritual = primera_pregunta(proyecto=r.proyecto)
            if ritual:
                return ritual, "ritual"
        return "", ""

    def avisa(self, motivo: str) -> None:
        """Algo del ARRANQUE que el usuario tiene que ver AHORA.

        >>> EXISTE PORQUE HABIA UN `print` HABLANDOLE A NADIE <<<
        Se reporto el 2026-09-03: al escribir la primera orden y darle a
        Enter, el texto desaparecia y no se veia reflejado hasta minutos
        despues, con toda la pinta de haberse trabado.

        La primera orden abre la sesion, y si el sello del suelo caduco
        gasta ademas UN TURNO ENTERO en una sesion aparte. Todo eso ya se
        contaba -- `abrir_de_verdad` tenia sus `print` --, pero la
        carcasa corre con `pythonw`, donde `sys.stdout` es None y
        `escritorio/salida.py` lo desvia a un archivo. O sea que el
        sistema estaba explicando lo que hacia A UN LOG QUE NADIE MIRA,
        mientras la pantalla no enseñaba nada y el texto ya se habia
        borrado de la caja.

        Se IMPRIME ADEMAS de difundir, y no en vez de: el archivo de
        `salida.py` es el diario del arranque y ahi tiene que seguir
        estando. Lo que faltaba era el otro extremo, no cambiar este.

        Va por `motivo` porque es una de las `CLAVES_DE_TEXTO`, o sea que
        se traduce sola en una pantalla en ingles. Un campo nuevo no lo
        haria, y el aviso saldria en español en mitad de una consola en
        ingles -- que es justo el fallo del que avisa `traducir_salida`.
        """
        print(f"  {motivo}")
        self._difundir({"clase": "Aviso", "motivo": motivo})

    def _difundir(self, cuerpo: dict[str, Any]) -> None:
        # El flujo en vivo lleva las tarjetas de PUERTA, o sea el motivo
        # que el usuario lee antes de autorizar. Va por otro canal (SSE)
        # que no pasa por `_responder_json`, asi que se traduce aqui
        # tambien -- y se guarda ya traducido, porque `historia` es lo
        # que se le replica a una pestaña que se abre despues.
        cuerpo = traducir_salida(cuerpo)
        with self._cerrojo:
            clase = str(cuerpo.get("clase", ""))
            if clase in CLASES_DE_ESTADO:
                self._ultimo_estado[clase] = cuerpo
            elif clase not in CLASES_TRANSITORIAS:
                self.historia.append(cuerpo)
            for cliente in list(self._clientes):
                cliente.put(cuerpo)

    def _suscribir(self) -> queue.Queue[dict[str, Any] | None]:
        cola: queue.Queue[dict[str, Any] | None] = queue.Queue()
        with self._cerrojo:
            for linea in self.historia:
                cola.put(linea)
            # Al FINAL: el estado de ahora tiene que ser lo ultimo que
            # lea la pestaña nueva, o el replay del log la dejaria
            # pintando lo de hace diez minutos.
            for estado in self._ultimo_estado.values():
                cola.put(estado)
            # El POV, armado al vuelo: lo que la camara este enseñando
            # ahora mismo, entero. Va DENTRO del cerrojo con el registro
            # de la pestaña, que es lo que garantiza que no se pierda ni
            # se duplique un `Cuadro` -- lo que llegue despues de esto
            # llega despues de que esta cola exista.
            plano = self.camara.a_json()
            if plano is not None:
                cola.put(traducir_salida(plano))
            self._clientes.append(cola)
        return cola

    def _desuscribir(self, cola: queue.Queue) -> None:
        with self._cerrojo:
            if cola in self._clientes:
                self._clientes.remove(cola)

    # --- lo que la pagina pregunta ---------------------------------------

    def estado(self) -> dict[str, Any]:
        sesion = self.sesion
        silencio = sesion.silencio_s
        pendientes = [
            {
                "id_peticion": p.evento.id_peticion,
                "es_pregunta": p.es_pregunta,
                "segundos": round(p.segundos_esperando),
                "veredicto": (p.decision.veredicto.value if p.decision else None),
                "motivo": (p.decision.motivo if p.decision else ""),
                "elementos": list(p.decision.elementos) if p.decision else [],
            }
            for p in sesion.pendientes
        ]
        return {
            "viva": sesion.viva,
            # Las piezas van TAMBIEN en el estado, y no solo en su
            # evento: una pestaña puede abrirse a mitad de turno, y lo
            # que ya se produjo tiene que estar ahi al llegar. El sondeo
            # ademas refresca lo que cambia sin evento -- un archivo que
            # alguien borra por fuera deja de `existe`.
            # Es la MISMA forma que manda `_difundir_producido`, a
            # proposito: la pagina tiene un solo dibujante.
            "producido": self.producido.a_json(),
            "tarea": self.tarea.tarea,
            "tarea_origen": self.tarea.origen,
            "session_id": sesion.session_id,
            "directorio": sesion.directorio,
            "modelo": sesion.modelo,
            "silencio_s": round(silencio, 1),
            # Tres respuestas, no dos: responde / no responde / no se sabe.
            "salud": self._salud(silencio),
            "reintento": (a_json(sesion.reintentando)
                          if sesion.reintentando else None),
            "limite": a_json(sesion.limite) if sesion.limite else None,
            "pendientes": pendientes,
            "suelo": self._suelo(),
            "puerta": self._puerta(),
            "voz": self._voz(),
            "canales": self._canales(),
            "mcp": self._mcp(),
            # Para que el boton de reiniciar se pinte apagado en vez de
            # fallar al pulsarlo. Ver `Consola.al_reiniciar`.
            "reiniciable": self.al_reiniciar is not None,
        }

    def _voz(self) -> dict[str, Any]:
        """Que esta haciendo la voz ahora mismo, para pintarlo.

        Lo importante es `estado`: son los seis del ciclo de JC-0011, y
        cada uno significa algo distinto para quien mira la pantalla --
        "dormido" es "di hey jarvis", "escuchando" es "habla ya",
        "trabajando" es "solo te oigo si dices para". Sin esto, los tres
        se ven igual: una pagina quieta.
        """
        voz = self.voz
        if voz is None:
            return {"encendida": False, "estado": None,
                    "motivo": "arranco sin --voz"}
        ciclo = getattr(voz, "ciclo", None)
        cuenta = getattr(voz, "cuenta", None)
        return {
            "encendida": True,
            "estado": ciclo.estado.value if ciclo else None,
            "escucha_la_palabra": bool(ciclo and ciclo.escucha_la_palabra),
            "escucha_paradas": bool(ciclo and ciclo.escucha_paradas),
            "espera_respuesta": bool(ciclo and ciclo.espera_respuesta),
            "micro": str(getattr(voz, "micro", "") or ""),
            "altavoz": str(getattr(voz, "altavoz", "") or ""),
            "locuta_entero": getattr(voz, "limite_hablado", None) is None,
            "seguimiento": bool(getattr(voz, "seguimiento", False)),
            # El fallo se enseña aunque este vacio: un asistente de voz
            # que falla en silencio es indistinguible de uno que no te
            # oye, y esta pantalla es donde se distinguen.
            "ultimo_fallo": getattr(voz, "ultimo_fallo", ""),
            "cuenta": _plano(asdict(cuenta)) if cuenta else {},
        }

    def _mcp(self) -> dict[str, Any]:
        """Los servidores MCP y si llegaron a levantarse.

        >>> TRES ESTADOS ARRIBA DEL TODO, Y EL TERCERO ES EL DE HOY <<<
        `sesion.inicio` es `None` hasta que arranca el PRIMER TURNO --
        medido: `system/init` no se emite al abrir el proceso, solo
        cuando hay turno en marcha--, asi que antes de eso la respuesta
        no es "no hay servidores", es **no se sabe**. Escribir una lista
        vacia ahi seria pintar "todo en orden" sobre algo que nadie ha
        mirado, que es exactamente el 0 % de cuota que duro seis dias.

        Por eso `sabido` es un campo aparte y no se deduce de la lista.
        """
        inicio = self.sesion.inicio
        if inicio is None:
            return {"sabido": False, "servidores": [], "caidos": []}
        return {
            "sabido": True,
            "servidores": [s.a_json() for s in inicio.servidores],
            # Se manda aparte y ya resuelto: quien pinta no tiene que
            # volver a decidir que cuenta como caido, y asi la regla vive
            # en un solo sitio. `needs-auth` NO esta aqui.
            "caidos": [s.nombre for s in inicio.mcp_caidos],
        }

    def _canales(self) -> dict[str, Any]:
        """Los tres canales de un vistazo: consola, voz y Telegram.

        La consola siempre esta -- la estas mirando. Los otros dos
        pueden no estar, y "no esta puesto" NO es un fallo: es una
        decision del usuario que la pantalla tiene que reflejar sin
        alarmar.
        """
        canal = getattr(self.escalado, "canal", None) if self.escalado else None
        return {
            "consola": True,
            "voz": self.voz is not None,
            "telegram": bool(getattr(canal, "disponible", False)),
            "escala_tras_minutos": (self.escalado.tras_minutos
                                    if self.escalado else None),
        }

    def asegurar_sesion(self) -> tuple[bool, str]:
        """Open the session if this is the first real instruction.

        Idempotente y con tres salidas, no dos: ya estaba viva /
        se ha abierto / no se pudo. La tercera NO se colapsa contra la
        segunda: si el suelo no muerde o la puerta no llega, hay que
        decirlo aqui y no mandar el turno igualmente.
        """
        if self.sesion.viva:
            return True, "ya estaba abierta"
        if self.al_primer_turno is None:
            return False, ("la sesion no esta abierta y nadie sabe abrirla; "
                           "quien monto la consola tenia que traerla viva")
        return self.al_primer_turno()

    def telegram(self) -> dict[str, Any]:
        """Que hay configurado y si funciona. NUNCA el token.

        Se enseñan sus cuatro ultimos caracteres, que es lo justo para
        que el usuario reconozca cual puso sin que el valor acabe en una
        captura de pantalla.
        """
        from canales import telegram as canal

        ajustes = canal.leer()
        estado, detalle = canal.Telegram(ajustes).comprobar() if ajustes.activo \
            else (canal.Estado.SIN_CONFIGURAR, "esta apagado")
        return {
            **ajustes.sin_secretos(),
            "estado": estado.value,
            "detalle": detalle,
            "tras_minutos": self.escalado.tras_minutos if self.escalado else None,
            # Que Telegram NO autoriza no es un detalle de esta pantalla:
            # es la decision de fondo del proyecto, y quien configure esto tiene
            # que verla aqui y no en un ADR.
            "solo_avisa": True,
        }

    def guardar_telegram(self, datos: dict) -> dict[str, Any]:
        """Guarda y COMPRUEBA en el mismo paso.

        Comprobar aqui, y no dejarlo para cuando haga falta, es lo que
        evita el fallo caro de un canal de avisos: descubrir que no
        funciona el dia que lo necesitas.
        """
        from canales import telegram as canal

        actuales = canal.leer()
        # Un token vacio NO borra el que ya habia: la UI no lo enseña, asi
        # que mandarlo vacio es lo normal cuando solo se cambia el chat.
        token = str(datos.get("token") or "").strip() or actuales.token
        ajustes = canal.Ajustes(
            activo=bool(datos.get("activo", False)),
            token=token,
            chat_id=str(datos.get("chat_id") or "").strip(),
            # JC-0016. Ausente = apagado: pasar de canal de salida a canal
            # de ENTRADA no puede ocurrir por omision.
            responde=bool(datos.get("responde", False)),
        )
        canal.guardar(ajustes)
        probado = ""
        if datos.get("probar") and ajustes.completo:
            # Manda un mensaje DE VERDAD. Es lo unico que valida el
            # `chat_id`: `getMe` solo valida el token, asi que un chat mal
            # puesto pasaria el guardado y fallaria el dia que hay algo
            # que avisar. Va detras de una peticion explicita porque
            # escribe en el Telegram del usuario.
            estado, probado = canal.Telegram(ajustes).probar()
            probado = f"{estado.value}: {probado}"
        if self.buzon is not None and self.buzon.entrada is not None:
            # En caliente, y con la misma razon que en los MCP: sin esto
            # el usuario encenderia el interruptor, veria "guardado", y
            # seguiria sin poder contestar hasta reiniciar.
            self.buzon.entrada.ajustes = ajustes
            if ajustes.activo and ajustes.responde:
                # Al ENCENDERLO se tira lo que hubiera pendiente: un
                # mensaje de antes no puede contestar la primera pregunta
                # que aparezca ahora.
                try:
                    self.buzon.entrada.ponerse_al_dia()
                except Exception as exc:  # noqa: BLE001
                    print(f"  (no se pudo poner al dia Telegram: {exc})")
        if self.escalado is not None:
            self.escalado.canal.ajustes = ajustes
            minutos = datos.get("tras_minutos")
            if isinstance(minutos, (int, float)) and minutos > 0:
                self.escalado.tras_minutos = float(minutos)
        return {**self.telegram(), "prueba": probado}

    def ajustes(self) -> dict[str, Any]:
        """Lo que el usuario puede tocar, agrupado y con su valor de ahora.

        Se recalcula en cada peticion y NO se cachea, a proposito: las
        opciones de audio son los dispositivos QUE HAY, y eso cambia al
        enchufar unos cascos. Un panel que enseñara una lista congelada
        te dejaria elegir un aparato que ya no esta.
        """
        from nucleo.ajustes import por_grupos

        directorio = getattr(self.sesion, "directorio", "") or ""
        grupos = por_grupos()
        # La carpeta de trabajo se puede dar por la linea de ordenes, y
        # entonces el ajuste esta vacio. Enseñar el hueco seria enseñar
        # algo distinto de lo que esta corriendo: se rellena con la de
        # verdad, que es lo que el usuario reconoce.
        for grupo in grupos:
            for aj in grupo["ajustes"]:
                if aj["clave"] == "sesion.carpeta" and not aj["valor"]:
                    aj["valor"] = directorio
        return {"grupos": grupos, "directorio": directorio}

    def tema_elegido(self) -> str:
        """Que tema hay puesto, ya validado contra `TEMAS`.

        >>> UN SOLO SITIO QUE LO DECIDA, Y ES ESTE <<<
        Lo usan DOS cosas al servir la pagina: el atributo `data-tema`
        del <html> (que elige la hoja de maqueta) y la copia del tema
        (`nucleo.textos.traducir_tema`). Resolviendolo cada uno por su
        cuenta, el dia que uno de los dos cambiara de criterio la
        pantalla saldria con la maqueta de un tema y las palabras de
        otro, y no habria nada roto que arreglar.

        Un `ajustes.yaml` malformado NO puede dejar la consola sin
        servir: es la pantalla desde la que se arregla.
        """
        from nucleo.ajustes import valor_de

        try:
            elegido = str(valor_de("ui.tema", "jarvis") or "jarvis")
        except Exception:  # noqa: BLE001 - ver el docstring
            return "jarvis"
        return elegido if elegido in TEMAS else "jarvis"

    def atributos_del_html(self) -> str:
        """Lo que el servidor decide del documento: idioma y tema.

        Se estampa al servir en vez de aplicarse con JS por una razon
        que se ve: si la pagina llegase con el tema de siempre y luego un
        script la repintase, cada apertura de la ventana empezaria con un
        fogonazo cian antes de ponerse clara. Servida ya con su atributo,
        el primer fotograma es el bueno.

        Un valor desconocido NO se estampa. Ver la nota de `TEMAS`.
        """
        from nucleo.textos import idioma

        # `lang` no es decoracion: de el dependen la particion de
        # palabras del navegador y como lee la pagina un lector de
        # pantalla. Una pagina en ingles etiquetada `lang="es"` se lee en
        # alto con acento español.
        trozos = [f' lang="{idioma()}"']
        elegido = self.tema_elegido()
        if elegido != "jarvis":
            trozos.append(f' data-tema="{elegido}"')
        return "".join(trozos)

    def _servir_pagina(self, pagina: Path) -> bytes:
        """La pagina lista para el navegador: idioma, tema y ficha.

        >>> EL ORDEN IMPORTA, Y AHORA EN DOS SITIOS <<<
        1. La copia del TEMA va antes que la del idioma. Las dos usan el
           mismo mecanismo de sustitucion, y yendo el tema primero al
           diccionario ingles solo le hacen falta las frases nuevas; al
           reves haria falta una tabla despacho-ingles entera. El porque
           largo esta en `nucleo/textos.traducir_tema`.
        2. Las dos van ANTES de meter la ficha. La ficha es un secreto
           aleatorio de 24 bytes en base64: si entrara primero, el
           traductor la veria como una cadena mas y podria -- con una
           probabilidad ridicula pero no nula -- tocarla. Traducir
           primero hace que eso no dependa de la suerte.
        """
        from nucleo.textos import idioma, traducir_pagina, traducir_tema

        texto = pagina.read_text(encoding="utf-8")
        texto = traducir_tema(texto, self.tema_elegido())
        texto = traducir_pagina(texto, idioma())
        texto = texto.replace("__FICHA__", self.ficha)
        texto = texto.replace("__ATRIBUTOS__", self.atributos_del_html())
        return texto.encode("utf-8")

    def reiniciar(self) -> dict[str, Any]:
        """Mata Jarvis y levanta otro con el mismo argv. No vuelve.

        >>> POR QUE ESTE BOTON EXISTE, Y NO ES POR LOS AJUSTES NUEVOS <<<
        **12 de los 16 ajustes que ya habia son `aplica: reiniciar`**, y
        la pagina lleva desde el 26 diciendo "hace falta reiniciar
        Jarvis" sin ofrecer ninguna forma de hacerlo: habia que ir a la
        bandeja, Salir, y relanzar a mano. Una pantalla que pide una
        accion que ella misma no ofrece manda al usuario a buscarla
        fuera, y por el camino se pierde el cambio recien guardado.

        >>> LO QUE CUESTA, Y POR ESO SE DICE ANTES <<<
        Se lleva por delante la sesion de Claude Code Y SU CONTEXTO: al
        volver, Jarvis no recuerda la conversacion. No mata lo que Claude
        Code arranco POR TI (docker, ollama), igual que "apagate": son
        tus procesos.

        >>> Y EL ORDEN NO ES NEGOCIABLE, POR JC-0010 <<<
        El cerrojo de "un solo Jarvis" ES EL PUERTO, y se midio que
        `allow_reuse_address` lo dejaba pasar en silencio, asi que hoy
        vale `False` y bindear un puerto ocupado revienta con WinError
        10048. O sea que **primero se muere y luego se nace**, nunca al
        reves: quien relance antes de que este proceso suelte el puerto
        se encuentra el cerrojo puesto por su propio cadaver. Por eso lo
        de arriba no relanza nada -- solo pide la muerte -- y el que nace
        lo lanza `escritorio/__main__.py` DESPUES de que el montaje se
        haya cerrado.
        """
        if self.al_reiniciar is None:
            return {"ok": False,
                    "motivo": "esta sesion no se puede reiniciar sola: "
                              "lanzala desde la aplicacion de escritorio"}
        # >>> SE CONTESTA ANTES DE MORIR <<<
        # Si se llamase aqui mismo, el proceso se cerraria con la
        # respuesta a medio escribir y el navegador veria una conexion
        # cortada: indistinguible de "el boton no hizo nada". Medio
        # segundo basta para que el 200 salga por el cable.
        threading.Timer(0.5, self._morir_para_renacer).start()
        return {"ok": True}

    def _morir_para_renacer(self) -> None:
        try:
            self.al_reiniciar()
        except Exception as exc:  # noqa: BLE001
            # No hay a quien contestarle ya: la pagina se fue con el 200.
            # Queda el log, que es donde mira quien vea que no reinicio.
            print(f"  (no se pudo reiniciar: {type(exc).__name__}: {exc})")

    def guardar_ajustes(self, cambios: dict[str, Any]) -> dict[str, Any]:
        """Valida y escribe. O entran todos, o no entra ninguno.

        Devuelve tambien QUE HACE FALTA para que se note, que es la mitad
        honesta de esto: un ajuste que parece aplicado y no lo esta es la
        pantalla mintiendo, y ya paso una vez con el panel de zonas.
        """
        from nucleo.ajustes import AjustesError, catalogo, guardar

        try:
            limpios = guardar(cambios)
        except AjustesError as exc:
            return {"ok": False, "motivo": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "motivo": f"{type(exc).__name__}: {exc}"}

        cual = {a.clave: a.aplica for a in catalogo()}
        aplica = {clave: cual.get(clave, "reiniciar") for clave in limpios}
        # Lo que SI se puede mover en caliente se mueve aqui mismo, para
        # no prometer un "reiniciar" que no hace falta.
        self._aplicar_en_caliente(limpios)
        return {"ok": True, "guardados": list(limpios), "aplica": aplica}

    def _aplicar_en_caliente(self, limpios: dict[str, Any]) -> None:
        """Los pocos que se pueden cambiar sin reabrir nada.

        Son los que viven en un objeto que ya esta montado y no en el
        arranque de un proceso. El resto se marca `reabrir` o
        `reiniciar` y se dice; fingir aqui seria peor que no hacerlo.
        """
        if "tiempos.telegram_minutos" in limpios and self.escalado is not None:
            try:
                self.escalado.tras_minutos = float(
                    limpios["tiempos.telegram_minutos"])
            except Exception as exc:  # noqa: BLE001
                print(f"  (no se pudo aplicar el aviso de Telegram: {exc})")
        if "tiempos.ausente_minutos" in limpios and self.escalado is not None:
            presencia = getattr(self.escalado, "presencia", None)
            if presencia is not None:
                try:
                    presencia.ausente_tras_s = float(
                        limpios["tiempos.ausente_minutos"]) * 60.0
                except Exception as exc:  # noqa: BLE001
                    print(f"  (no se pudo aplicar la ausencia: {exc})")

    def probar_audio(self, datos: dict[str, Any]) -> dict[str, Any]:
        """Toca un tono o graba un momento, y cuenta QUE paso de verdad.

        Es la contrapartida de dejar elegir dispositivo. Sin esto, elegir
        el equivocado no da un error: da un Jarvis sordo para siempre --
        16 de los 23 endpoints de esta maquina entregan silencio digital
        sin quejarse. Con esto, el fallo mudo se ve en dos segundos.
        """
        from voz.prueba import probar_entrada, probar_salida

        tipo = str(datos.get("tipo") or "")
        dispositivo = str(datos.get("dispositivo") or "")
        if tipo not in ("entrada", "salida"):
            return {"ok": False, "motivo": "se prueba 'entrada' o 'salida'"}
        try:
            r = (probar_entrada(dispositivo) if tipo == "entrada"
                 else probar_salida(dispositivo))
        except Exception as exc:  # noqa: BLE001
            # Probar el audio NO puede tumbar la consola: es un boton.
            return {"ok": False, "motivo": f"{type(exc).__name__}: {exc}"}
        return {"ok": True, **r.a_json()}

    def proyectos(self) -> dict[str, Any]:
        """Los proyectos que se pueden abrir por su nombre (ADR-0029).

        Ya no es "por voz": desde el 2026-09-03 la consola intercepta la
        misma frase, con el mismo interruptor y el mismo decisor.
        """
        from nucleo.ajustes import valor_de
        from nucleo.proyectos import (candidatas_bajo, intercepta, leer,
                                      manda_la_global)

        registrados = leer()
        raiz = str(valor_de("proyectos.raiz", "") or "")
        ya = {str(Path(p.carpeta)).lower() for p in registrados}
        # Se OFRECEN las carpetas de la raiz, no se registran. Descubrir
        # es barato; abrir una que nadie declaro es lo que no se hace.
        sueltas = [c for c in candidatas_bajo(raiz)
                   if str(Path(c)).lower() not in ya] if raiz else []
        # La global viaja con la lista para que cada fila pueda ensenar
        # QUE hereda. Un desplegable que dice "pregunta lo de siempre"
        # sin decir cual es lo de siempre obliga a subir a Avanzado para
        # entender la fila que tienes delante.
        from voz.proyecto import primera_pregunta

        return {
            "proyectos": [p.a_json() for p in registrados],
            "intercepta": intercepta(),
            "raiz": raiz,
            "candidatas": sueltas,
            "actual": getattr(self.sesion, "directorio", ""),
            "ritual_global": primera_pregunta(),
            # >>> VIAJA PARA QUE LAS FILAS PISADAS LO DIGAN <<<
            # Sin esto el override seria invisible donde muerde: verias
            # "mira el roadmap" en la fila de nebula y Jarvis mandaria
            # otra cosa. Es el fallo de la barra de la cuota otra vez --
            # ningun dato mal, y la pantalla mintiendo igual.
            "ritual_manda": manda_la_global(),
        }

    def guardar_proyectos(self, datos: dict) -> dict[str, Any]:
        """Reescribe el registro. EL PANEL SOLO CAMBIA LO QUE ENSENA.

        >>> Y HASTA EL 2026-09-05 BAJABA UN FRENO POR LA PUERTA DE ATRAS
            <<< Esto rehacia los `Proyecto` desde el formulario --
        `Proyecto(alias, carpeta)` -- y el formulario no conoce `auto`.
        Como `guardar` reescribe el archivo ENTERO y `auto` nace en True,
        un proyecto puesto a `auto: false` a mano volvia a `true` la
        primera vez que alguien anadiera o quitara otro. Sin un error,
        sin un aviso, y en el campo que decide si la puerta llega.
        Es EXACTAMENTE la forma del fallo de `guardar_mcp` con `lanzar`
        (2026-09-01), y aparecio al buscar donde meter el ritual (al arreglar
        un fallo de forma, mirar los demas sitios).

        LA REGLA QUE SALE DE LAS DOS VECES, y vale para el proximo campo:
        **lo que la pagina no ensena, la pagina no lo escribe.** `auto`
        sale del ARCHIVO, emparejado por carpeta; `ritual` SI sale de la
        pagina, porque ahi se edita. La misma regla que gobierna
        `/mcp/autorizar`: del cliente se acepta CUAL, no QUE.
        """
        from nucleo.proyectos import (Proyecto, ProyectosError, guardar,
                                      leer, manda_la_global)

        filas = datos.get("proyectos")
        if not isinstance(filas, list):
            return {"ok": False, "motivo": "falta la lista de proyectos"}

        try:
            previos = {self._clave_de_carpeta(p.carpeta): p for p in leer()}
        except ProyectosError as exc:
            # Sin poder leer lo que hay no se puede conservar lo que hay,
            # y escribir igual significaria devolver a `auto: true` todo
            # lo que el usuario hubiera frenado. Se dice y no se toca.
            return {"ok": False,
                    "motivo": f"no puedo guardar sin poder leer el registro "
                              f"que ya hay: {exc}"}

        nuevos = []
        for fila in filas:
            if not isinstance(fila, dict):
                return {"ok": False, "motivo": "hay una entrada mal formada"}
            alias = str(fila.get("alias") or "").strip()
            carpeta = str(fila.get("carpeta") or "").strip()
            if not alias or not carpeta:
                return {"ok": False,
                        "motivo": "cada proyecto necesita alias y carpeta"}
            anterior = previos.get(self._clave_de_carpeta(carpeta))
            # Uno que no estaba nace como nace en el YAML: `auto` en True
            # (JC-0017, estar en el registro ya es la decision) y sin
            # ritual propio, o sea heredando el global.
            auto = anterior.auto if anterior else True
            # TRES estados y la clave AUSENTE no es la vacia. Que la
            # pagina no mande la clave significa "no me toques esto" --
            # una version vieja de la pagina no puede borrar un ritual
            # por no conocerlo --; mandar `null` SI es heredar, y mandar
            # "" es la salida explicita de no mandar nada.
            if "ritual" in fila:
                crudo = fila.get("ritual")
                ritual = None if crudo is None else str(crudo).strip()
            else:
                ritual = anterior.ritual if anterior else None
            nuevos.append(Proyecto(alias, carpeta, auto=auto, ritual=ritual))
        # Misma regla que `auto`: si la pagina no manda la clave, se
        # conserva lo que hay en disco. Una pestana abierta desde antes
        # de este cambio no puede apagar un override que el usuario
        # encendio despues.
        if "ritual_manda" in datos:
            manda = bool(datos.get("ritual_manda"))
        else:
            manda = manda_la_global()
        try:
            guardar(tuple(nuevos),
                    activo=bool(datos.get("intercepta")),
                    ritual_manda=manda)
        except (ProyectosError, OSError) as exc:
            return {"ok": False, "motivo": str(exc)}
        return {"ok": True, **self.proyectos()}

    @staticmethod
    def _clave_de_carpeta(carpeta: str) -> str:
        """Como se emparejan las filas de la pagina con las del archivo.

        Por CARPETA y no por alias, porque el alias es justo lo que el
        usuario puede estar renombrando; y normalizada, porque la pagina
        devuelve la cadena que le mandamos pero un anadido a mano llega
        como lo escribio quien lo escribio.
        """
        import os

        return os.path.normcase(os.path.normpath(str(carpeta)))

    def mcp(self) -> dict[str, Any]:
        """La lista blanca de servidores MCP, mas los que se han visto.

        Los VISTOS son lo que hace que la lista sea abierta en vez de un
        muro: denegar sin decir que se denego obliga a leer el log para
        enterarse. Con esto el panel ofrece "he visto estos, ¿los
        autorizo?", que es enterarse en un paso.
        """
        from nucleo.mcp import POLITICA_AL_ANADIR, Politica, descubrir, leer

        declarados = leer()
        conocidos = {s.nombre for s in declarados}
        vistos = sorted(getattr(self.sesion, "mcp_vistos", set()) - conocidos)

        # >>> Y LO QUE YA TIENE TU CLAUDE CODE (2026-09-03) <<<
        # Los VISTOS solo aparecen DESPUES de que un servidor intente
        # actuar y se coma una negativa. Esto se entera antes, leyendo
        # donde mira el propio Claude Code. Lo pidio el usuario; la
        # decision fue DESCUBRIR y no confiar, asi que esto no autoriza
        # nada: pone el boton.
        #
        # La carpeta de la SESION va aparte porque puede no estar entre
        # los proyectos que `~/.claude.json` conoce -- es justo el caso
        # de una carpeta recien abierta, que es cuando mas falta hace.
        hallados = descubrir(carpetas_extra=(str(self.sesion.directorio),))
        return {
            "servidores": [s.a_json() for s in declarados],
            "vistos": vistos,
            "encontrados": [
                {**e.a_json(), "ya_declarado": e.nombre in conocidos}
                for e in hallados
            ],
            "politicas": [p.value for p in Politica],
            "al_anadir": POLITICA_AL_ANADIR.value,
        }

    def autorizar_mcp(self, datos: dict) -> dict[str, Any]:
        """Mete en la lista blanca uno de los que ya tiene tu Claude Code.

        >>> ENTRA EN `confirmar`, COMO CUALQUIER OTRO <<<
        Autorizar desde aqui es un clic, y un clic no puede valer mas que
        escribirlo a mano: `POLITICA_AL_ANADIR` es la misma para los dos
        caminos. Que el servidor ya estuviera en tu Claude Code dice que
        TU lo pusiste ahi, no que deba pasar sin preguntar -- y de hecho
        el propio Claude Code tampoco lo da por aprobado.

        >>> LO QUE SE COPIA Y LO QUE NO <<<
        Se copia la linea de ordenes o la url. **Los valores de entorno
        NO**: `config/mcp.yaml` se versiona, asi que un `env` literal de
        un `.mcp.json` ajeno meteria un token en git. Se traen los
        NOMBRES como `${NOMBRE}` -- que es lo que `_del_entorno` resuelve
        contra el entorno del proceso -- y se DICE en la nota, porque un
        servidor que no arranca por una variable que falta es de los que
        se depuran a ciegas.

        >>> Y SI YA ESTABA, SE PISA SU LANZAMIENTO A PROPOSITO <<<
        Es el caso de un mismo servidor declarado dos veces: aqui con un
        ejecutable suelto y en el proyecto con un lanzador de paquetes.
        Dos definiciones de la misma cosa acaban divergiendo, asi que
        importar sirve justo para quedarse con UNA.
        La POLITICA que ya tuviera NO se toca: bajarle el freno a un
        servidor por pulsar "importar" seria cambiar permisos por la
        puerta de atras.
        """
        from nucleo.mcp import (
            POLITICA_AL_ANADIR,
            McpError,
            Servidor,
            descubrir,
            guardar,
            leer,
        )

        nombre = str(datos.get("nombre") or "").strip()
        origen = str(datos.get("origen") or "").strip()
        if not nombre:
            return {"ok": False, "motivo": "falta el nombre del servidor"}

        # >>> SE VUELVE A DESCUBRIR, NO SE FIA DE LO QUE MANDA LA PAGINA
        # <<< La pagina podria mandar una linea de ordenes cualquiera, y
        # esto ESCRIBE algo que Jarvis va a EJECUTAR. Asi que del cliente
        # solo se acepta CUAL de los encontrados, y la definicion sale de
        # leer el archivo otra vez.
        hallados = descubrir(carpetas_extra=(str(self.sesion.directorio),))
        cual = next((e for e in hallados
                     if e.nombre == nombre
                     and (not origen or e.origen == origen)), None)
        if cual is None:
            return {"ok": False,
                    "motivo": f"ya no encuentro '{nombre}' en tu Claude Code"}
        if cual.lanzamiento is None:
            return {"ok": False,
                    "motivo": f"'{nombre}' no dice como se arranca"}

        nota = f"Importado de {cual.origen}."
        if cual.claves_de_entorno:
            nota += (" Necesita estas variables de entorno, que NO se copian "
                     "porque este archivo se versiona: "
                     + ", ".join(cual.claves_de_entorno) + ".")

        antes = leer()
        politica = next((s.politica for s in antes if s.nombre == nombre),
                        POLITICA_AL_ANADIR)
        nuevos = [s for s in antes if s.nombre != nombre]
        nuevos.append(Servidor(nombre, politica, nota, cual.lanzamiento))
        try:
            guardar(tuple(nuevos))
        except (McpError, OSError) as exc:
            return {"ok": False, "motivo": str(exc)}

        # En caliente, por lo mismo que `guardar_mcp`: sin esto el
        # usuario autoriza, ve "guardado", y la siguiente peticion sigue
        # denegada.
        self.sesion.servidores_mcp = leer()
        return {"ok": True, **self.mcp()}

    def guardar_mcp(self, datos: dict) -> dict[str, Any]:
        """Reescribe la lista ENTERA. Ver `nucleo/mcp.py::guardar`."""
        from nucleo.mcp import McpError, Politica, Servidor, guardar, leer

        filas = datos.get("servidores")
        if not isinstance(filas, list):
            return {"ok": False, "motivo": "falta la lista de servidores"}

        # >>> EL PANEL NO EDITA `lanzar`, ASI QUE NO PUEDE BORRARLO <<<
        # `guardar` reescribe el archivo ENTERO -- tiene que hacerlo, o no
        # se podria quitar un servidor --, y esta pantalla solo conoce el
        # nombre, la politica y la nota. Sin arrastrar el `lanzamiento`
        # que ya estaba, cambiar una politica de `confirmar` a `auto`
        # borraria la linea de ordenes del servidor y este dejaria de
        # arrancar: al reiniciar la herramienta simplemente no estaria,
        # sin un solo error y con la pantalla diciendo "guardado".
        antes = {s.nombre: s.lanzamiento for s in leer()}

        nuevos = []
        for fila in filas:
            if not isinstance(fila, dict) or not str(fila.get("nombre") or "").strip():
                return {"ok": False, "motivo": "hay una entrada sin nombre"}
            try:
                politica = Politica(str(fila.get("politica") or ""))
            except ValueError:
                return {"ok": False,
                        "motivo": f"'{fila.get('politica')}' no es una politica"}
            nombre = str(fila["nombre"]).strip()
            nuevos.append(Servidor(nombre, politica,
                                   str(fila.get("nota") or ""),
                                   antes.get(nombre)))
        try:
            guardar(tuple(nuevos))
        except (McpError, OSError) as exc:
            return {"ok": False, "motivo": str(exc)}

        # >>> EN CALIENTE, Y ESO IMPORTA MAS AQUI QUE EN OTROS SITIOS <<<
        # La sesion lleva su propia copia. Si no se pusiera al dia, el
        # usuario autorizaria un servidor, veria "guardado", y la
        # siguiente peticion seguiria denegada -- la pantalla mintiendo
        # sobre lo unico que no puede mentir.
        recien = leer()
        self.sesion.servidores_mcp = recien
        vistos = getattr(self.sesion, "mcp_vistos", None)
        if vistos is not None:
            vistos.difference_update({s.nombre for s in recien})
        return {"ok": True, **self.mcp()}

    def parar_el_turno(self) -> dict[str, Any]:
        """La tecla Esc. Corta el turno en marcha, como el "para" hablado.

        >>> SE LLAMA `parar_el_turno` Y NO `parar` POR UNA RAZON REAL <<<
        `Consola.parar()` ya existe y significa otra cosa: apagar el
        SERVIDOR. Lo llama el lanzador al salir. La primera version de
        esto se llamo `parar` y quedo sombreada por aquella -- Python se
        queda con la ultima definicion --, asi que Esc apagaba... nada, y
        el riesgo al reves era peor: cerrar Jarvis creyendo que parabas
        un turno. Lo cazaron los tests de aqui abajo.

        >>> NO LLAMA A `sesion.interrumpir` DIRECTAMENTE, Y ES EL PUNTO <<<
        Esa llamada corta el TURNO y nada mas. Parar de verdad son cuatro
        cosas -- callar lo que ya suena, no decir lo que venia detras,
        vaciar el buzon de narracion y cortar el turno --, y hacer solo la
        ultima deja a Jarvis recitando la respuesta de un trabajo que ya
        no existe. Fue el fallo del 2026-08-29 y costo tres fugas
        arreglarlo; repetirlo aqui seria tirarlas.

        Sin voz montada si se llama directo, porque entonces no hay nada
        que callar: solo hay turno.

        TRES RESPUESTAS, no dos: `parado` dice si habia algo vivo, y "no
        habia turno" NO es un fallo. Pintarlo como error ensenaria un
        aviso rojo cada vez que alguien roza Esc en una pantalla quieta.
        """
        voz = getattr(self, "voz", None)
        if voz is not None:
            return {"ok": True,
                    "parado": bool(voz.parar_el_turno(origen="consola")),
                    "con_voz": True}
        return {"ok": True, "parado": bool(self.sesion.interrumpir()),
                "con_voz": False}

    def abrir_pieza(self, id_pieza: str) -> dict[str, Any]:
        """Abre una pieza con el programa que Windows le tenga asociado.

        >>> ACEPTA UN ID Y NUNCA UNA RUTA <<<
        `os.startfile` EJECUTA: abre el archivo con su programa asociado.
        Con una ruta, cualquier cosa que alcance `127.0.0.1` podria
        arrancar lo que quisiera de esta PC, y el suelo de JC-0007 no lo
        taparia -- aquel gobierna a Claude Code, no a nuestro servidor.
        Lo unico abrible es lo que ESTA sesion produjo y sigue en disco.

        Y las imagenes NO se abren: viven en memoria, no tienen ruta, y
        escribirlas en un temporal para poder lanzarlas seria inventar un
        archivo que el usuario no pidio. Se miran en la pagina, que es
        donde ya se pintan.
        """
        pieza = self.producido.por_id(id_pieza)
        if pieza is None or pieza.ruta is None:
            return {"ok": False, "motivo": "eso no es una pieza de esta sesion"}
        if not pieza.ruta.is_file():
            # Tercera respuesta de verdad: la pieza existe y el archivo
            # no. Decirlo es mejor que un error del sistema, porque pasa
            # de verdad -- un temporal que la propia sesion borro despues.
            return {"ok": False,
                    "motivo": f"ya no esta en disco: {pieza.ruta}"}
        try:
            import os

            os.startfile(str(pieza.ruta))   # noqa: S606 - es el objetivo
        except OSError as exc:
            return {"ok": False, "motivo": f"Windows no pudo abrirlo: {exc}"}
        return {"ok": True, "nombre": pieza.nombre}

    def zonas(self) -> dict[str, Any]:
        """Everything the zones panel needs, obligatorias included.

        Las obligatorias se envian aunque no se puedan desmarcar, y a
        proposito: el usuario tiene derecho a VER de que se le esta
        protegiendo. Un suelo que no se puede inspeccionar se parece
        demasiado a uno que no existe.
        """
        if self.suelo is None:
            return {"hay_suelo": False, "obligatorias": [], "opcionales": []}

        def a_dict(zona, aceptada=None):
            fila = {"ruta": zona.ruta, "motivo": zona.motivo,
                    "eje": zona.eje.value, "coste": zona.coste}
            if aceptada is not None:
                fila["aceptada"] = aceptada
            return fila

        aceptadas = {z.ruta for z in self.suelo.zonas}
        return {
            "hay_suelo": True,
            "estado": self.suelo.estado.value,
            "obligatorias": [a_dict(z) for z in self.suelo.zonas
                             if z.obligatoria],
            "opcionales": [a_dict(z, z.ruta in aceptadas)
                           for z in self.suelo.opcionales],
        }

    def guardar_zonas(self, rutas: list[str], config_dir: Any = None,
                      version: str | None = None) -> dict[str, Any]:
        """Persist the choice and say HONESTLY what took effect.

        >>> LO QUE ESTA PANTALLA NO PUEDE PROMETER, Y ESTA MEDIDO <<<
        Un cambio NO queda aplicado del todo hasta reabrir la sesion, y
        eso vale para las DOS direcciones. Medido el 2026-08-24:

          * El archivo de `--settings` se lee al arrancar. Con la sesion
            viva, quitar una regla NO la suelta: se desmarco una zona por
            esta misma funcion y la lectura siguio denegada.
          * Nuestra segunda capa (`politica.py`) si cambia en caliente
            -- `sesion.zonas` se actualiza aqui mismo --, pero solo ve lo
            que Claude Code PREGUNTA, y `Read` no dispara la puerta. Asi
            que para una zona PRIVADA recien marcada no puede garantizar
            la lectura por si sola.

        Hubo una observacion suelta en la que una zona recien marcada SI
        quedo bloqueada en caliente. No se explico, y por lo tanto no se
        promete: se informa de lo que esta seguro y se pide reabrir. Decir
        "listo" y que no lo este seria mentir en la pantalla donde el
        usuario consiente, que es justo lo que avisa D8.
        """
        from puente.suelo import preparar
        from seguridad.zonas import guardar_eleccion

        antes = {z.ruta for z in self.suelo.zonas} if self.suelo else set()
        guardar_eleccion(rutas, config_dir=config_dir)

        nuevo_suelo = preparar(destino=self.suelo.archivo,
                               sello=self.suelo.sello, config_dir=config_dir,
                               version=version)
        ahora = {z.ruta for z in nuevo_suelo.zonas}

        # La sesion viva pasa a denegar lo nuevo en el acto.
        self.sesion.zonas = nuevo_suelo.zonas
        self.suelo = nuevo_suelo

        anadidas, soltadas = sorted(ahora - antes), sorted(antes - ahora)
        return {
            "ok": nuevo_suelo.estado.se_puede_arrancar,
            "estado": nuevo_suelo.estado.value,
            "motivo": nuevo_suelo.motivo,
            "zonas": len(nuevo_suelo.zonas),
            "anadidas": anadidas,
            "soltadas": soltadas,
            # Lo unico que se afirma sin reservas: la puerta ya las
            # deniega. No cubre las lecturas, que no pasan por ella.
            "ya_en_la_puerta": anadidas,
            "hace_falta_reabrir": bool(anadidas or soltadas),
        }

    def _puerta(self) -> dict[str, Any]:
        """Si esta sesion tiene freno, y se pinta SIEMPRE (JC-0017).

        >>> SORDOS NO ES CIEGOS, PERO TIENE QUE VERSE QUE ESTAMOS SORDOS <<<
        En auto mode la consola sigue ensenando cada `tool_use` -- eso
        esta medido --, o sea que se ve TODO lo que pasa. Lo que deja de
        verse es que ya no hay nada que lo pare, y esa ausencia no tiene
        sintoma: la pantalla de una sesion sin frenos y la de una sesion
        que simplemente no ha hecho nada peligroso son identicas.
        Por eso se dice, y con la misma regla que el suelo: se pinta
        aunque este bien, porque un aviso que solo aparece cuando algo va
        mal se confunde con que no hay aviso.
        """
        auto = self.sesion.modo_permisos != "default"
        return {
            "modo": self.sesion.modo_permisos,
            "auto": auto,
            "motivo": (
                "sin freno: no se preguntara por borrados, `git push` ni "
                "MCP sin autorizar. Las zonas selladas siguen bloqueadas."
                if auto else
                "la puerta esta puesta: lo irreversible se pregunta"),
        }

    def _suelo(self) -> dict[str, Any]:
        """What the page says about the floor. Absence is stated, not hidden."""
        if self.suelo is None:
            return {"estado": "sin_suelo", "zonas": 0,
                    "motivo": "esta sesion corre sin el suelo de JC-0007"}
        return {
            "estado": self.suelo.estado.value,
            "zonas": len(self.suelo.zonas),
            "reglas": len(self.suelo.reglas),
            "motivo": self.suelo.motivo,
        }

    def _salud(self, silencio: float) -> str:
        # >>> REPOSO VA ANTES QUE CAIDA, Y NO SON LO MISMO <<<
        # Una sesion que nunca se abrio -- o que se cerro a proposito --
        # no se ha caido de ningun sitio. Ver `Sesion.en_reposo`.
        if self.sesion.en_reposo:
            return "en_reposo"
        if not self.sesion.viva:
            return "caida"
        if self.sesion.reintentando is not None:
            return "sin_servidor"
        if self.sesion.pendientes:
            return "esperandote"
        if silencio > SILENCIO_DUDOSO_S:
            # NO es "esta rota". Es que no se sabe, y se dice asi.
            return "callada"
        return "bien"

    # --- servidor ---------------------------------------------------------

    def servir(self, abrir_navegador: bool = True) -> ThreadingHTTPServer:
        consola = self

        class Manejador(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_: Any) -> None:
                pass  # el registro de la sesion ya esta en otro sitio

            @property
            def _origen_propio(self) -> str:
                return f"http://127.0.0.1:{consola.puerto}"

            def _autorizado(self) -> bool:
                """Two independent checks, and both have to pass.

                `Origin` ajeno se rechaza siempre: nuestra propia pagina
                manda `Origin` con el origen correcto en los POST, asi que
                un valor distinto solo puede venir de otro sitio.

                Y la ficha, que es la que aguanta cuando no hay `Origin`
                que mirar. Va en cabecera propia a proposito: una cabecera
                que no es de las simples obliga al navegador a hacer
                preflight, y el preflight se cae porque no contestamos
                CORS. Son dos puertas, no una.
                """
                origen = self.headers.get("Origin")
                if origen is not None and origen != self._origen_propio:
                    return False
                ficha = self.headers.get("X-Jarvis-Ficha")
                if ficha is None:
                    partes = urlparse(self.path)
                    ficha = parse_qs(partes.query).get("ficha", [None])[0]
                return secrets.compare_digest(str(ficha or ""), consola.ficha)

            def _cabeceras(self, tipo: str, largo: int | None = None) -> None:
                self.send_response(200)
                # Nos identifica sin obligar a olfatear el HTML. Sirve para
                # distinguir "ya hay un Jarvis" de "ese puerto lo tiene otro
                # programa", que no se responden igual.
                self.send_header("X-Jarvis", "puente")
                self.send_header("Content-Type", tipo)
                # >>> NADA DE ESTO SE CACHEA, Y COSTO UNA SESION <<<
                # 2026-08-27: se añadio la barra de TAREA a `consola.html`
                # y el usuario no la vio ni matando y reabriendo Jarvis.
                # No estaba rota: el WebView2 tenia la pagina VIEJA en su
                # cache, que vive en el perfil de pywebview y sobrevive a
                # reiniciar el proceso. Sin esto, cada cambio de la UI se
                # prueba contra la version anterior y parece que no
                # funciona -- que es el peor sitio donde tener un fallo
                # silencioso, porque manda a buscar el problema al codigo
                # que si estaba bien.
                self.send_header("Cache-Control", "no-store, must-revalidate")
                if largo is not None:
                    self.send_header("Content-Length", str(largo))
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                ruta = urlparse(self.path).path
                if ruta == "/":
                    # La pagina se sirve SIN pedir ficha -- es de donde
                    # sale la ficha. Servirla no es peligroso: una pagina
                    # ajena no puede leer la respuesta, y un proceso local
                    # ya podria lanzar `claude` por su cuenta.
                    cuerpo = consola._servir_pagina(PAGINA)
                    self._cabeceras("text/html; charset=utf-8", len(cuerpo))
                    self.wfile.write(cuerpo)
                    return
                if ruta == "/ajustes":
                    # >>> SU PROPIA PAGINA, Y NO UN DESPLEGABLE <<<
                    # Lo pidio el usuario al verlo: configurar y vigilar son
                    # tareas distintas, y meterlas en la misma pantalla
                    # obliga a que una quepa donde no cabe. Se sirve sin
                    # pedir ficha por lo mismo que `/`: es de donde sale.
                    cuerpo = consola._servir_pagina(PAGINA_AJUSTES)
                    self._cabeceras("text/html; charset=utf-8", len(cuerpo))
                    self.wfile.write(cuerpo)
                    return
                if ruta.startswith("/pieza/"):
                    # >>> LA UNICA PUERTA AL DISCO, Y VA POR ID <<<
                    # No hay una version de esto que acepte una ruta. Si
                    # la hubiera, cualquier cosa que alcance 127.0.0.1
                    # leeria el disco entero -- y el suelo de JC-0007 no
                    # lo taparia, porque aquel gobierna a Claude Code y
                    # no a este servidor. Ficha SI: esto sirve contenido
                    # de la sesion, no una hoja de estilo.
                    # La ficha puede venir en la query, y hace falta:
                    # un `<img src="/pieza/...">` no manda cabeceras
                    # propias. `_autorizado` ya contempla las dos formas.
                    if not self._autorizado():
                        self.send_error(403)
                        return
                    # `vistazo` es el recorte de la MINIATURA de la
                    # tira: cuatro renglones de un documento. Nunca
                    # amplia nada -- `contenido_de` se queda con el menor
                    # de los dos topes --, y un valor absurdo o con letras
                    # cae en el tope de siempre en vez de reventar.
                    consulta = parse_qs(urlparse(self.path).query)
                    try:
                        vistazo = int(consulta.get("vistazo", ["0"])[0])
                    except ValueError:
                        vistazo = 0
                    hallado = consola.producido.contenido_de(
                        ruta[7:], tope=vistazo if vistazo > 0 else None)
                    if hallado is None:
                        self.send_error(404)
                        return
                    datos, tipo = hallado
                    self._cabeceras(tipo, len(datos))
                    self.wfile.write(datos)
                    return
                if ruta == "/tema.css":
                    # La paleta de los cuatro temas. Se sirve SIN ficha
                    # por lo mismo que las fuentes: es una hoja de
                    # estilo, no una puerta a la sesion, y la pide el
                    # `<link>` de una pagina que todavia no tiene JS.
                    datos = TEMA.read_bytes()
                    self._cabeceras("text/css; charset=utf-8", len(datos))
                    self.wfile.write(datos)
                    return
                if ruta == "/fuentes.css":
                    # Los `@font-face` de las seis familias, en un solo
                    # sitio porque los ajustes viven en un `iframe` y no
                    # heredan nada del padre. Sin ficha, como la paleta.
                    datos = FUENTES_CSS.read_bytes()
                    self._cabeceras("text/css; charset=utf-8", len(datos))
                    self.wfile.write(datos)
                    return
                if ruta.startswith("/temas/"):
                    # La MAQUETA del tema. El nombre NO se saca de la
                    # ruta y se abre: se comprueba contra `TEMAS`, que
                    # ya es la lista blanca del atributo `data-tema`.
                    # Asi `/temas/../config/telegram.yaml` no es una
                    # ruta que exista, es un nombre que no esta en la
                    # tupla -- y eso no hay `Path(...).name` que se
                    # despiste.
                    nombre = Path(ruta).name.removesuffix(".css")
                    archivo = HOJAS_TEMA / f"{nombre}.css"
                    if nombre not in TEMAS or not archivo.is_file():
                        self.send_error(404)
                        return
                    datos = archivo.read_bytes()
                    self._cabeceras("text/css; charset=utf-8", len(datos))
                    self.wfile.write(datos)
                    return
                if ruta.startswith("/fuentes/"):
                    # >>> LAS FUENTES SE SIRVEN DESDE AQUI, NO DESDE GOOGLE <<<
                    # Un `@font-face` apuntando a fonts.gstatic.com haria
                    # que esta pagina -- local, en 127.0.0.1 -- pidiera
                    # algo a un tercero en cada carga: una peticion
                    # externa en un proyecto cuya premisa es cero
                    # telemetria. Y dejaria la consola con las fuentes de
                    # respaldo justo cuando no hay red, que es cuando mas
                    # falta hace leerla bien.
                    #
                    # Van SIN ficha, como la pagina: son tipografia
                    # publica, no dicen nada de esta sesion. Y el nombre
                    # se limpia con `Path(...).name` para que un
                    # `/fuentes/../../config/telegram.yaml` no salga de
                    # la carpeta -- eso SI diria algo.
                    nombre = Path(ruta).name
                    archivo = FUENTES / nombre
                    if not nombre.endswith(".woff2") or not archivo.is_file():
                        self.send_error(404)
                        return
                    datos = archivo.read_bytes()
                    self._cabeceras("font/woff2", len(datos))
                    self.wfile.write(datos)
                    return
                if not self._autorizado():
                    self.send_error(403, "sin ficha")
                    return
                # >>> LOS SEIS POR LA MISMA PUERTA <<< Cada uno se
                # armaba su propio `json.dumps` -- seis copias de tres
                # lineas --, y el dia que la salida tuvo que hacer algo
                # mas (traducir), cinco de las seis se quedaron sin
                # hacerlo. No dio ningun error: solo motivos en español
                # en una pantalla en ingles, que es lo que vio el
                # usuario. Ahora hay un solo sitio por donde salen.
                if ruta == "/estado":
                    self._responder_json(consola.estado())
                elif ruta == "/zonas":
                    self._responder_json(consola.zonas())
                elif ruta == "/glosario":
                    self._responder_json(consola.glosario())
                elif ruta == "/ajustes.json":
                    self._responder_json(consola.ajustes())
                elif ruta == "/proyectos":
                    self._responder_json(consola.proyectos())
                elif ruta == "/mcp":
                    self._responder_json(consola.mcp())
                elif ruta == "/telegram":
                    self._responder_json(consola.telegram())
                elif ruta == "/eventos":
                    self._transmitir()
                else:
                    self.send_error(404)

            def _transmitir(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                cola = consola._suscribir()
                try:
                    while True:
                        try:
                            cuerpo = cola.get(timeout=15.0)
                        except queue.Empty:
                            self.wfile.write(b": latido\n\n")
                            self.wfile.flush()
                            continue
                        if cuerpo is None:
                            return
                        dato = json.dumps(cuerpo, ensure_ascii=False)
                        self.wfile.write(f"data: {dato}\n\n".encode("utf-8"))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
                finally:
                    consola._desuscribir(cola)

            def do_POST(self) -> None:  # noqa: N802
                largo = int(self.headers.get("Content-Length") or 0)
                if not self._autorizado():
                    # El cuerpo se lee y se tira ANTES de contestar. Sin
                    # esto la conexion se corta en seco con keep-alive y
                    # el que llama recibe un reset en vez de un 403: un
                    # rechazo que parece una averia se acaba investigando
                    # como una averia.
                    self.rfile.read(largo)
                    self.send_error(403, "sin ficha")
                    return
                try:
                    datos = json.loads(self.rfile.read(largo) or b"{}")
                except json.JSONDecodeError:
                    self.send_error(400)
                    return
                if self.path == "/turno":
                    texto = str(datos.get("texto", "")).strip()
                    if not texto:
                        self.send_error(400)
                        return
                    # >>> LO QUE ESCRIBISTE SE ANUNCIA SIEMPRE, Y LO
                    # PRIMERO <<< Aunque la frase acabe siendo un cambio
                    # de proyecto y lo que viaje sea otra cosa. Es la
                    # leccion del 2026-08-27 en la voz: se anuncia lo que
                    # DIJISTE, no lo que se manda, porque el anuncio
                    # existe para que compruebes que se te entendio.
                    consola.anuncia_turno(texto, "consola")
                    # >>> Y EL CAMBIO DE PROYECTO VA ANTES DE ABRIR <<<
                    # `cambiar_a` cierra la sesion y repunta el
                    # directorio; abrir primero levantaria el binario de
                    # 337 MB en la carpeta VIEJA para cerrarlo acto
                    # seguido. Es tambien el orden honesto: hasta que no
                    # se sabe donde, no hay que arrancar nada.
                    # >>> LAS ORDENES SOBRE JARVIS, LO PRIMERO <<<
                    # Antes que el cambio de proyecto y antes de abrir la
                    # sesion: "apagate" no puede levantar el binario de
                    # 337 MB para matarlo acto seguido. Es el mismo orden
                    # que la voz, que las mira "de la mas barata a la mas
                    # cara".
                    if consola.de_la_ventana(texto):
                        self._responder_json({"ok": True})
                        return
                    viaja, de_quien = consola.cambiar_de_proyecto(texto)
                    if not viaja:
                        # Se ocupo de la frase y no hay turno que mandar
                        # (no se entendio el nombre, no existe, hay
                        # varios). Ya se ha dicho por que.
                        self._responder_json({"ok": True})
                        return
                    listo, porque = consola.asegurar_sesion()
                    if not listo:
                        self._responder_json({"ok": False, "motivo": porque})
                        return
                    consola.sesion.mandar(viaja)
                    if viaja != texto:
                        # La cola, o el ritual: no es lo que escribiste
                        # entero, asi que se enseña aparte para que se
                        # vea QUE viajo tras el cambio de carpeta. Es lo
                        # mismo que hace la voz, y por eso salen dos
                        # renglones en el registro y no uno.
                        consola.anuncia_turno(viaja, de_quien)
                    self._responder_json({"ok": True})
                elif self.path == "/responder":
                    # `respuestas` es lo que contesta DE VERDAD una
                    # pregunta: sin ella, permitir un `AskUserQuestion`
                    # deja pasar la herramienta sin decir que se eligio,
                    # y por fuera se ve igual. Medido el 2026-08-25.
                    crudas = datos.get("respuestas")
                    respuestas = (
                        {str(k): str(v) for k, v in crudas.items()}
                        if isinstance(crudas, dict) else None
                    )
                    ok = consola.sesion.responder(
                        str(datos.get("id_peticion", "")),
                        permitir=bool(datos.get("permitir")),
                        motivo=str(datos.get("motivo", "")),
                        respuestas=respuestas,
                    )
                    consola._difundir({
                        "clase": "RespuestaDelUsuario",
                        "id_peticion": datos.get("id_peticion"),
                        "permitir": bool(datos.get("permitir")),
                        # False = otro canal llego antes. No es un error.
                        "aceptada": ok, "origen": "consola",
                    })
                    self._responder_json({"ok": ok})
                elif self.path == "/telegram":
                    self._responder_json(consola.guardar_telegram(datos))
                elif self.path == "/ajustes":
                    cambios = datos.get("cambios")
                    if not isinstance(cambios, dict):
                        self.send_error(400)
                        return
                    self._responder_json(consola.guardar_ajustes(cambios))
                elif self.path == "/ajustes/probar":
                    self._responder_json(consola.probar_audio(datos))
                elif self.path == "/reiniciar":
                    self._responder_json(consola.reiniciar())
                elif self.path == "/proyectos":
                    self._responder_json(consola.guardar_proyectos(datos))
                elif self.path == "/mcp":
                    self._responder_json(consola.guardar_mcp(datos))
                elif self.path == "/mcp/autorizar":
                    # Ruta aparte y no un campo mas de `/mcp`: aquella
                    # reescribe la lista ENTERA desde el formulario, y
                    # esta añade UNO leyendo el archivo del que salio.
                    # Mezclarlas dejaria que la pagina mandase una linea
                    # de ordenes, que es lo que Jarvis va a EJECUTAR.
                    self._responder_json(consola.autorizar_mcp(datos))
                elif self.path == "/parar":
                    self._responder_json(consola.parar_el_turno())
                elif self.path == "/abrir":
                    # >>> ESTO LANZA UN PROGRAMA, Y HAY QUE DECIRLO <<<
                    # `os.startfile` abre el archivo con lo que Windows
                    # tenga asociado, o sea que ejecuta algo. Por eso
                    # acepta un ID y no una ruta: lo unico que se puede
                    # abrir es lo que ESTA sesion produjo y sigue en
                    # disco. Con una ruta, cualquiera que alcance
                    # 127.0.0.1 arrancaria lo que quisiera de la PC.
                    self._responder_json(
                        consola.abrir_pieza(str(datos.get("id") or "")))
                elif self.path == "/zonas":
                    rutas = datos.get("rutas")
                    if not isinstance(rutas, list) or not all(
                            isinstance(r, str) for r in rutas):
                        self.send_error(400)
                        return
                    if consola.suelo is None:
                        # Sin suelo no hay zonas que elegir, y decirlo es
                        # mejor que aceptar la eleccion y perderla.
                        self._responder_json(
                            {"ok": False,
                             "motivo": "esta sesion corre sin suelo"})
                        return
                    self._responder_json(consola.guardar_zonas(rutas))
                else:
                    self.send_error(404)

            def _responder_json(self, cuerpo: dict[str, Any]) -> None:
                # `ensure_ascii=False` porque por aqui pasan ahora los
                # nombres de dispositivo y de carpeta, que llevan tildes
                # y enies. Escaparlos funcionaria igual, pero deja el
                # registro crudo ilegible al mirarlo a mano.
                datos = json.dumps(traducir_salida(cuerpo),
                                   ensure_ascii=False).encode("utf-8")
                self._cabeceras("application/json; charset=utf-8", len(datos))
                self.wfile.write(datos)

        # 127.0.0.1 explicito: no "" ni 0.0.0.0. Esto no sale de la maquina.
        class Servidor(ThreadingHTTPServer):
            """El bind ES el cerrojo, pero solo si se apaga `SO_REUSEADDR`.

            >>> MEDIDO EL 2026-08-25, Y LO CONTRARIO DE LO QUE PARECE <<<
            `HTTPServer` trae `allow_reuse_address = 1`, y en Windows eso
            deja que un SEGUNDO servidor bindee un puerto YA OCUPADO. Se
            comprobo: los dos arrancan sin error y las peticiones caen en
            uno u otro. O sea que dar por hecho que "el puerto ya sirve de
            cerrojo" -- que es lo que se dijo en esta misma sesion -- era
            falso: habria dos Jarvis, dos micros escuchando y dos politicas
            sobre la misma PC, en silencio.

            Con `False`, el segundo bind falla con WinError 10048 y se
            puede DECIR. Y no impide reiniciar: arrancar-usar-cerrar-
            reabrir mide 0,5 s, sin TIME_WAIT de por medio (tambien
            medido, porque un Jarvis que no se puede reiniciar en dos
            minutos seria peor que el problema).
            """

            allow_reuse_address = False

        servidor = Servidor(("127.0.0.1", self.puerto), Manejador)
        servidor.daemon_threads = True
        self._servidor = servidor
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        threading.Thread(target=self.bombear, daemon=True).start()
        if abrir_navegador:
            webbrowser.open(f"http://127.0.0.1:{self.puerto}/")
        return servidor

    def parar(self) -> None:
        if self._servidor is not None:
            self._servidor.shutdown()
            self._servidor.server_close()
            self._servidor = None
