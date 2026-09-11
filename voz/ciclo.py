"""El turno de palabra: cuando Jarvis escucha, cuando no, y que acepta.

Esto es JC-0011 puesto en codigo. No decide nada de acustica -- eso ya se
midio y no se pudo arreglar --: **coordina**. Convierte un problema de
microfono que no sabemos resolver en uno de aviso, que si.

>>> DE DONDE SALE, EN TRES NUMEROS <<<
Aceptacion del wake word con la voz del usuario (2026-08-25, mismo micro,
misma pronunciacion, umbral 0,5):

    en silencio   20/20
    con musica    14/20
    TECLEANDO      9/20

Y dos cosas que dan forma a todo lo de abajo: el fallo NO es gradual
(tumba intentos enteros, asi que no hay umbral que lo salve) y el
mecanismo NO se identifico (cuatro hipotesis probadas y descartadas). Con
eso sobre la mesa, lo que queda es cambiar la SITUACION: pedir el ruido
mas bajo, y pedirlo CON TIEMPO.

>>> LOS SEIS ESTADOS, Y QUE SE ACEPTA EN CADA UNO <<<

    DORMIDO      solo la palabra de activacion
    AVISANDO     esta sonando el aviso; el usuario todavia no habla
    ESCUCHANDO   se acabo el aviso; el usuario dicta una orden
    TRABAJANDO   la orden ya viaja;  SOLO se aceptan paradas
    HABLANDO     Jarvis locuta;      SOLO se aceptan paradas
    PREGUNTANDO  Jarvis pregunto;    se acepta la RESPUESTA, sin palabra

>>> A TRABAJANDO SE LLEGA POR DOS SITIOS, NO POR UNO <<<
Por la voz (`oido()` devolviendo ORDEN) y por `trabajo_ajeno()`, que es
un turno lanzado desde Telegram o desde la consola. Hasta el 2026-08-29
solo existia el primero, y por eso las respuestas de los turnos que no
abrio la voz no se locutaban: ver `trabajo_ajeno`.

>>> "APAGADA" SIGNIFICA APAGADA PARA ORDENES NUEVAS <<<
Del `wake` a la orden hay escucha; desde que la orden sale hasta que hay
algo que decir, no. Eso quita de un plumazo la ventana mas larga de
falsos positivos -- justo el rato en que el usuario vuelve a teclear y a
poner musica -- y ademas quita el rato en que el propio Jarvis va a
HABLAR, que es un bucle esperando a pasar.

Pero apagada del todo seria una escucha que no oye "para" mientras el
cerebro de la nube borra algo. Por eso en TRABAJANDO y en HABLANDO el
micro sigue abierto y la tuberia sigue corriendo: lo unico que cambia es
que `oido()` no devuelve nunca ORDEN, solo PARAR o IGNORAR. El filtro
vive en `voz/parada.py`.

>>> LA DUDA SE RESUELVE PARANDO, Y ES ASIMETRICO A PROPOSITO <<<
`voz/parada.py` tiene tres veredictos y aqui se colapsan a dos acciones,
que es donde hay que elegir. Se elige PARAR:

    parar sin que se lo pidieran   el trabajo se detiene, Jarvis lo dice,
                                   el usuario lo repite. Visible y barato.
    NO parar cuando se lo pidieron  el agente sigue actuando sobre la PC
                                    mientras el usuario repite "para".

No son comparables, y la regla pide que la tercera salida exista, no
que se reparta a medias. OJO con la direccion CONTRARIA: una orden nueva
dudosa NO se manda (ver `oido`), porque ahi lo caro es lo otro -- mandar
a un agente capaz una orden que nadie dio.

>>> UN SOLO AVISO, Y CUANDO ACABA SE HABLA <<<
JC-0011 decidio dos sonidos con dos segundos en medio. Al USARLO, el
usuario dijo que el segundo sobraba: con el primero ya se entiende que
Jarvis te oyo y que escuchara cuando termine de sonar. Ver
`avisar_de_que_escucha`, donde esta escrito que se pierde y por que se
puede perder.

>>> Y CUANDO PREGUNTA EL, LA ESCUCHA SE ABRE SOLA <<<
La otra cosa que enseño usarlo: si Jarvis te pregunta algo y para
contestarle hay que decir "hey jarvis" otra vez, eso no es una
conversacion, es un formulario. En PREGUNTANDO se acepta habla sin
palabra de activacion -- y solo ahi.

>>> LO QUE FALTA POR MEDIR, Y NO SE PUEDE MEDIR SIN HABLAR <<<
Cuanto se gana de verdad. Hay contra que compararlo, que es lo que hace
la tanda facil: 20 activaciones con musica sonando, avisando 2 s antes,
contra las 14/20 de hoy sin aviso.

    .venv\\Scripts\\python.exe -m eval.wake_bench --activaciones 20 --campana

Si no sube, la idea era buena y el mundo no coopero, y hay que saberlo
(son 20 intentos, asi que se lee el MARGEN, no el recuento).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from voz.parada import Juicio, Veredicto, mirar
from voz.senales import Senales
from voz.stt import Transcripcion

# >>> EL RESPIRO ENTRE EL PITIDO Y LA GRABACION <<<
# `eval/wake_bench.py` ya lo tenia escrito -- "si se solapan, la cola del
# pitido entra en el audio y ensucia la medicion" -- y al montar el ciclo
# no se copio. Es la regla cobrandose una: al arreglar algo, buscar la
# misma forma en los demas sitios.
#
# Y ademas hace falta MAS aqui que en el banco, porque esta medido que el
# altavoz mete ~380 ms de latencia: cuando `reproducir` vuelve, el pitido
# TODAVIA SE ESTA OYENDO. Sin respiro, la grabacion empieza encima del
# aviso y Whisper recibe un tono pegado a la primera silaba.
RESPIRO_S = 0.35

# Lo que se dice, y se dice UNA vez. Es la decision 1 de JC-0011: un
# aviso honesto en vez de una promesa. Las cifras son las medidas -- 70 %
# con musica, 45 % tecleando --, redondeadas a algo que quepa en un oido
# sin mentir en la direccion comoda.
# El texto vive en `voz/idioma.py` desde JC-0018. Esta constante se
# conserva porque la importan el bucle y sus tests, y sigue siendo la
# frase en español: el idioma se resuelve al decirla, no al importarla
# -- si no, arrancar en español y cambiar a ingles dejaria este aviso
# congelado hasta el siguiente reinicio del proceso.
def aviso_ruido(idioma: str | None = None) -> str:
    from voz.idioma import frase

    return frase("consejo_ruido", idioma=idioma)


AVISO_RUIDO = (
    "Cuando me llames, baja el ruido lo que puedas. "
    "Con musica suelo oirte; tecleando, menos de la mitad de las veces."
)


class Estado(Enum):
    """Donde esta el turno de palabra ahora mismo."""

    DORMIDO = "dormido"
    AVISANDO = "avisando"
    ESCUCHANDO = "escuchando"
    TRABAJANDO = "trabajando"
    HABLANDO = "hablando"
    PREGUNTANDO = "preguntando"
    """Jarvis pregunto algo y espera respuesta. Escucha SIN palabra.

    Es el unico estado en que se acepta habla sin que nadie haya dicho
    "hey jarvis", y se puede porque no abre nada: la sesion ya estaba
    trabajando en una orden que dio el usuario hace segundos, y lo unico
    que se acepta es la respuesta a lo que se acaba de preguntar.
    """


class Reaccion(Enum):
    """Que hacer con lo que se acaba de oir. Lo decide el estado."""

    ORDEN = "orden"
    """Va al puente como turno nuevo. SOLO puede salir de ESCUCHANDO."""

    RESPUESTA = "respuesta"
    """Contesta a lo que Jarvis pregunto. SOLO desde PREGUNTANDO.

    Separada de ORDEN a proposito: no viaja igual -- una contesta la
    peticion de control, la otra abre un turno nuevo -- y sobre todo no
    VALE igual. Una orden manda; una respuesta rellena un hueco que
    abrio Jarvis.
    """

    PARAR = "parar"
    IGNORAR = "ignorar"


class CicloError(RuntimeError):
    """Se pidio una transicion que no existe desde el estado actual."""


@dataclass
class Cuenta:
    """Lo que ha pasado, en magnitudes continuas y no en banderas.

    Existe para poder contar y para poder medir: cuando alguien lea "el
    ciclo va
    bien", esto es lo que le deja preguntar cuantas veces ocurrio de
    verdad cada suceso. `dudosas` va aparte de `paradas` a proposito --
    son las que se pararon SIN estar seguras, y si ese numero crece es
    que el filtro esta mal calibrado, no que el usuario pare mucho.
    """

    ordenes: int = 0
    paradas: int = 0
    dudosas: int = 0
    ignorados: int = 0
    ciclos: int = 0
    preguntas: int = 0
    respuestas: int = 0
    ajenos: int = 0
    """Turnos que el ciclo adopto sin haberlos abierto la voz.

    Son los que entran por Telegram o por la consola. Van aparte de
    `ciclos` a proposito: `ciclos` cuenta las veces que sono la palabra
    de activacion, y estos no la tienen -- si se sumaran ahi, la tasa de
    aciertos del wake word saldria diluida por turnos que nadie dijo.
    """
    sin_responder: int = 0
    """Preguntas en las que no se entendio la respuesta.

    Aparte de `ignorados` porque duele distinto: un "no te he oido"
    cuando hablas TU se repite y ya esta; uno cuando pregunta JARVIS
    deja un turno colgado esperando a alguien.
    """


@dataclass
class Ciclo:
    """La maquina de estados. Sin hardware salvo los avisos.

    Todo lo que DECIDE vive aqui y se puede probar con transcripciones de
    disco; lo unico que toca el mundo son los dos sonidos, y `Senales`
    sin dispositivo no suena, asi que los tests lo construyen igual.
    """

    senales: Senales = field(default_factory=Senales)
    respiro_s: float = RESPIRO_S
    estado: Estado = Estado.DORMIDO
    cuenta: Cuenta = field(default_factory=Cuenta)
    ultimo_juicio: Juicio | None = field(default=None, repr=False)

    # --- que esta encendido ahora mismo ----------------------------------

    @property
    def escucha_la_palabra(self) -> bool:
        """El wake word solo cuenta cuando no hay nada en marcha."""
        return self.estado is Estado.DORMIDO

    @property
    def acepta_ordenes(self) -> bool:
        return self.estado is Estado.ESCUCHANDO

    @property
    def escucha_paradas(self) -> bool:
        """El micro sigue abierto mientras trabaja y mientras habla.

        PREGUNTANDO NO esta en la lista, y no es un olvido: ahi ya hay
        alguien grabando -- el hilo de la voz, esperando la respuesta --
        y dos grabadores sobre el mismo microfono no son una escucha mas
        atenta, son audio partido en dos. La parada se sigue oyendo por
        el otro camino: `oido()` la mira ANTES que nada, tambien ahi.
        """
        return self.estado in (Estado.TRABAJANDO, Estado.HABLANDO)

    @property
    def espera_respuesta(self) -> bool:
        return self.estado is Estado.PREGUNTANDO

    # --- el enrutador, que es el corazon de JC-0011 -----------------------

    def oido(self, transcripcion: Transcripcion | str) -> Reaccion:
        """Que hacer con lo que se acaba de transcribir, segun el estado.

        Es el unico sitio donde se decide si algo llega al puente, y por
        eso el orden de las comprobaciones importa:

        1. **La parada se mira ANTES que la orden**, incluso mientras el
           usuario dicta. Al reves, un "cancela" dicho a media orden se
           enviaria a Claude Code COMO orden, que es lo contrario de lo
           que se pidio.
        2. **Una orden nueva sin habla fiable NO sale.** Falla cerrado:
           `small` se inventa texto ante el silencio 12 de 12 veces
           (medido), y lo que se invente viajaria a un agente que actua.
        """
        juicio = mirar(transcripcion)
        self.ultimo_juicio = juicio

        if juicio.veredicto is not Veredicto.SIGUE:
            # Una parada dicha estando DORMIDO no para nada: no hay nada
            # que parar, y tratarla como tal solo confundiria la cuenta.
            if self.estado in (Estado.ESCUCHANDO, Estado.TRABAJANDO,
                               Estado.HABLANDO, Estado.PREGUNTANDO):
                if juicio.veredicto is Veredicto.DUDOSA:
                    self.cuenta.dudosas += 1
                self.cuenta.paradas += 1
                self.estado = Estado.DORMIDO
                return Reaccion.PARAR
            self.cuenta.ignorados += 1
            return Reaccion.IGNORAR

        if self.estado not in (Estado.ESCUCHANDO, Estado.PREGUNTANDO):
            # Aqui es donde la escucha esta "apagada": el audio entro, se
            # transcribio, y se tira porque no era una parada.
            self.cuenta.ignorados += 1
            return Reaccion.IGNORAR

        sin_habla = getattr(transcripcion, "sin_habla", False)
        vacio = not str(getattr(transcripcion, "texto",
                                transcripcion)).strip()
        if sin_habla or vacio:
            # Falla cerrado en los dos casos, pero se CUENTAN aparte: una
            # orden que no se entendio la repite el usuario; una
            # respuesta que no se entendio deja un turno colgado.
            if self.estado is Estado.PREGUNTANDO:
                self.cuenta.sin_responder += 1
            else:
                self.cuenta.ignorados += 1
            return Reaccion.IGNORAR

        if self.estado is Estado.PREGUNTANDO:
            self.cuenta.respuestas += 1
            return Reaccion.RESPUESTA

        self.cuenta.ordenes += 1
        self.estado = Estado.TRABAJANDO
        return Reaccion.ORDEN

    # --- las transiciones -------------------------------------------------

    def desperto(self) -> None:
        """Sono la palabra de activacion.

        Solo cuenta estando DORMIDO. Durante el resto del ciclo el wake
        word ni siquiera deberia estar mirando, y si llega algo es un
        falso positivo: se ignora en silencio en vez de reiniciar un
        ciclo que estaba a mitad.
        """
        if self.estado is not Estado.DORMIDO:
            return
        self.estado = Estado.AVISANDO
        self.cuenta.ciclos += 1

    def trabajo_ajeno(self) -> bool:
        """Hay un turno en marcha que NO abrio la voz. Devuelve si se adopta.

        >>> SIN ESTO, UN TURNO QUE NO ABRIO LA VOZ NO SE LOCUTA <<<
        Lo vio el usuario el 2026-08-29 probando JC-0016: contesto una
        pregunta desde el movil, Claude Code respondio, y no sono nada --
        sono despues, cuando el ya estaba hablando de otra cosa. La causa
        estaba aqui: al ciclo solo se llegaba a TRABAJANDO por el camino
        de la voz (`oido()` devolviendo ORDEN), asi que un turno lanzado
        desde Telegram o desde la consola dejaba el ciclo en DORMIDO, y
        `preparar_respuesta()` -- que EXIGE TRABAJANDO -- moria con un
        `CicloError` que el bucle se tragaba sin contar.
        Medido contra las ocho trazas de `eval/trazas_claude_code/`:
        **6 de 8 respuestas no se decian**. Las dos que si son las que
        vuelven ANTES de pedir el estado (turno parado y sin conexion).

        >>> Y NO ES UN `if` SUELTO: MUEVE EL MICROFONO <<<
        Pasar a TRABAJANDO enciende `escucha_paradas` y apaga
        `escucha_la_palabra`, que es exactamente lo que se quiere -- un
        turno del movil actua sobre la misma PC, asi que "para" tiene que
        oirse igual --, pero conviene decirlo: mientras dure ese turno la
        palabra de activacion no abre nada, igual que si lo hubieras
        pedido hablando.

        TRES SITUACIONES Y DOS RESPUESTAS, que es lo que hay que elegir:

            DORMIDO                   se adopta -> True
            TRABAJANDO / HABLANDO /   ya era nuestro, no se toca -> True
            PREGUNTANDO
            AVISANDO / ESCUCHANDO     el usuario esta dictando -> False

        El False es una GUARDA, no un camino: el hilo de la voz es uno
        solo y esos dos estados solo existen dentro de el, asi que no
        deberia verse nunca. Se cuenta en el bucle en vez de darlo por
        imposible, porque "no deberia pasar" es como se pierden los
        eventos en silencio -- que es el fallo que esto viene a cerrar.
        """
        if self.estado is Estado.DORMIDO:
            self.estado = Estado.TRABAJANDO
            self.cuenta.ajenos += 1
            return True
        return self.estado in (Estado.TRABAJANDO, Estado.HABLANDO,
                               Estado.PREGUNTANDO)

    def avisar_de_que_escucha(self, dormir=time.sleep) -> None:
        """UN sonido, y cuando acaba se habla. Nada mas.

        >>> ERAN DOS SONIDOS HASTA EL 2026-08-25, Y LO CAMBIO EL USO <<<
        JC-0011 decidio campana ("baja el ruido") + 2 s + pitido ("habla
        ya"). Al usarlo, el veredicto del usuario fue que **el segundo
        sobra**: con el primero ya se entiende que Jarvis te oyo y que va
        a escuchar cuando termine de sonar -- que es como se comporta
        cualquier asistente que la gente ya sabe usar.

        QUE SE PIERDE, dicho claro: la ventana de dos segundos para bajar
        la musica. Y QUE COSTABA ESO DE VERDAD, que es lo que hace que se
        pueda soltar sin drama: lo que se midio mal (9/20 tecleando) fue
        la PALABRA DE ACTIVACION, y esa ocurre ANTES de que suene nada.
        Ninguna campana podia arreglar aquello. Lo que si protegia esta
        ventana es el DICTADO, y el dictado va bien -- WER 2,4 % medido, y
        "me entiende bien" usandolo.

        Queda el respiro, que no es cosmetico: con ~380 ms de latencia
        medidos en el altavoz, cuando `reproducir` vuelve el sonido
        TODAVIA se esta oyendo, y sin esperar se grabaria encima.

        El pitido NO se borra: sigue en `voz/senales.py` y lo usa
        `eval/wake_bench.py`, donde si hace falta un "habla ya" por
        intento.
        """
        self.senales.campana()
        dormir(self.respiro_s)

    def preparar_escucha(self, dormir=time.sleep) -> None:
        """El aviso, y a partir de ahi se acepta una orden."""
        if self.estado is not Estado.AVISANDO:
            raise CicloError(
                f"preparar_escucha() desde {self.estado.value}: la campana "
                f"solo suena despues de la palabra de activacion")
        self.avisar_de_que_escucha(dormir)
        self.estado = Estado.ESCUCHANDO

    def pregunto(self) -> None:
        """Jarvis ha preguntado algo y espera respuesta HABLADA.

        >>> AQUI NO HACE FALTA LA PALABRA DE ACTIVACION, Y ES EL PUNTO <<<
        Lo dijo el usuario despues de probarlo: si Jarvis te pregunta y
        para contestarle tienes que decir "hey jarvis" otra vez, no es
        una conversacion, es un formulario. Cuando ES EL quien pide la
        informacion, la escucha se abre sola.

        Y no abre una puerta nueva a nada: la sesion ya estaba trabajando
        en una orden que dio el usuario hace segundos, y lo unico que se
        acepta aqui es la RESPUESTA a lo que se acaba de preguntar.
        """
        if self.estado not in (Estado.TRABAJANDO, Estado.HABLANDO):
            raise CicloError(
                f"pregunto() desde {self.estado.value}: solo se pregunta "
                f"mientras hay un turno en marcha")
        self.estado = Estado.PREGUNTANDO
        self.cuenta.preguntas += 1

    def volver_al_trabajo(self) -> None:
        """Contestada la pregunta, el turno sigue donde estaba."""
        if self.estado is Estado.PREGUNTANDO:
            self.estado = Estado.TRABAJANDO

    def preparar_respuesta(self, dormir=time.sleep) -> None:
        """Se pasa a HABLANDO. SIN sonido, y eso se decidio el 2026-08-25.

        Antes sonaba la campana antes de contestar, para dar tiempo a
        bajar la musica. Con un solo aviso eso deja de poder hacerse: la
        campana ahora significa "habla tu", y sonarla justo antes de que
        hable Jarvis invitaria al usuario a hablar encima -- que es
        exactamente el error que JC-0011 queria evitar cuando exigia dos
        sonidos distintos. La voz de Jarvis es su propio aviso.
        """
        if self.estado is not Estado.TRABAJANDO:
            raise CicloError(
                f"preparar_respuesta() desde {self.estado.value}: solo se "
                f"responde a algo que se estaba trabajando")
        self.estado = Estado.HABLANDO

    def termino(self) -> None:
        """Se acabo el turno: vuelta a escuchar solo la palabra."""
        self.estado = Estado.DORMIDO
