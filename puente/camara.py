"""El POV: ver a Claude trabajar, no leer lo que hizo.

>>> LO QUE PIDIO EL USUARIO (2026-09-02) <<<
Lo que pidio es ver el POV de Claude, como una pelicula en primera
persona para que se sienta vivo, al estilo del Jarvis de Iron Man: verle
el trabajo en vivo, no solo lo que acaba saliendo por la consola.

>>> Y ESTO SOLO PUEDE ENSEÑAR LO QUE DE VERDAD SE MUEVE <<<
Se midio antes de escribir una linea (`-m eval.sondas_claude_code.
sonda_pov`, contra `claude` real), porque la mitad de lo que uno
imaginaria aqui seria una animacion inventada -- o sea un mock en
produccion, y del peor tipo: parece informacion.

    lo que SI se mueve        el CONTENIDO de un `Write`, que el modelo
                              redacta token a token. Medido: 17 trozos de
                              ~97 caracteres, 1468 en total, repartidos
                              en 6,88 s. Se ve escribirse de verdad.
                              Y su prosa y su pensamiento, igual.

    lo que NO se mueve        la SALIDA de una herramienta. Un `Read` de
                              1400 caracteres llega en UN trozo, y la
                              herramienta tarda 0,02 s. "Verle leer
                              palabra por palabra" no existe en el
                              transporte: habria que inventarlo, y aqui
                              no se inventa. Se enseña que archivo, y
                              cuando el contenido ATERRIZA, aterriza.

Y el numero que decidio que esto merecia la pena: **el mayor rato sin
que llegue nada en todo un turno es 1,05 s**. Un visor colgado de esto no
parece congelado, que era el riesgo -- un visor que se queda quieto seis
segundos es peor que no tenerlo, porque el usuario cree que se colgo.

>>> NO ES LA TIRA, Y NO PUEDE VIVIR EN ELLA <<<
`puente/producido.py` cuenta el PASADO: una secuencia de lo que quedo, y
una pieza solo entra ahi con su resultado sin error. Esto es el
PRESENTE: un solo plano, y enseña cosas que **pueden no llegar a
existir** -- el contenido viaja ANTES de la puerta, asi que un `Write`
que el usuario deniegue se habra visto escribirse entero. Mezclarlos
seria romper la regla de la tira ("un Write denegado NO es una pieza")
sin tocarla. Por eso son dos superficies: esta es la camara y aquella la
pelicula que sale de ella. Cuando algo se deniega, el plano LO DICE.

>>> Y NO CUESTA UN TOKEN <<<
Es el mismo contenido que ya viajaba, entregado a plazos. Lo unico que
crece es el numero de lineas por el cable local (12 -> 65 en la
medicion), y los trozos no se guardan en el registro crudo: no aportan
un dato que el mensaje completo no traiga, solo el momento en que se
supo. Ver `Sesion._leer`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from puente.protocolo import (
    AbreBloque,
    AbreMensaje,
    CierraBloque,
    Evento,
    Fin,
    ResultadoHerramienta,
    Trozo,
    UsoHerramienta,
)

# Que esta haciendo, dicho en una palabra que se entienda de un vistazo.
# La clave es el nombre de la herramienta; lo que no este aqui cae en
# "usando", que es honesto: no sabemos que hace esa herramienta.
QUE_HACE = {
    "Write": "escribiendo",
    "Edit": "escribiendo",
    "NotebookEdit": "escribiendo",
    "Read": "leyendo",
    "Bash": "ejecutando",
    "PowerShell": "ejecutando",
    "Grep": "buscando",
    "Glob": "buscando",
    "WebFetch": "mirando",
    "WebSearch": "buscando",
    "Task": "delegando",
    "TodoWrite": "planeando",
}

# De que campo de la entrada sale lo que se VE crecer. Ojo: no es "el
# campo mas largo", es el que el usuario querria mirar. De un `Edit`
# interesa como queda, no como estaba.
CUERPO = {
    "Write": "content",
    "Edit": "new_string",
    "NotebookEdit": "new_source",
    "Bash": "command",
    "PowerShell": "command",
    "Grep": "pattern",
    "Glob": "pattern",
    "WebFetch": "prompt",
    "Task": "prompt",
}

# Y de cual sale el ASUNTO, el nombre que va en el rotulo.
SOBRE = ("file_path", "notebook_path", "path", "url")

# Las que producen algo: ahi el plano es lo que ESCRIBIO, y su resultado
# es un acuse ("File created successfully at..."). En las demas el plano
# es lo que SALIO, y por eso al aterrizar sustituye a la entrada.
ESCRIBEN = frozenset({"Write", "Edit", "NotebookEdit"})

TOPE_GUARDADO = 20_000
"""Lo maximo que se guarda de un plano. Esto corre todo el dia."""

TOPE_ENVIADO = 4_000
"""Lo maximo que va en un plano entero (al abrir una pestaña).

Los trozos van sueltos y son pequeños, asi que este tope solo lo toca
quien llega tarde. Un documento entero no cabe en un visor de 360 px y
ademas acaba en la tira, que es donde se lee.
"""

ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f",
           '"': '"', "\\": "\\", "/": "/"}


def valor_parcial(crudo: str, clave: str) -> tuple[str, bool]:
    """El valor de `clave` dentro de un JSON QUE TODAVIA NO ESTA ENTERO.

    >>> ESTA ES LA PIEZA QUE HACE POSIBLE VER ESCRIBIR <<<
    Lo que llega no es el texto del documento: es el JSON de la entrada
    de la herramienta, construyendose. O sea que a mitad de camino hay
    cosas como `{"file_path": "a.md", "content": "El mar respi` y hay que
    sacar de ahi lo que se puede leer, sin esperar a que cierre.

    Devuelve `(valor, completo)`. Tres salidas y no dos: la clave todavia
    no ha llegado, ha llegado a medias, o esta entera. Un `False` en
    `completo` no significa "vacio", significa "sigue escribiendose".

    Lo que se corta a proposito: una barra invertida suelta al final o un
    `\\uXXXX` a medias. Pintar `\\u00e` mientras llega el resto seria
    enseñar basura durante 200 ms, y eso en un visor se nota.
    """
    aguja = f'"{clave}"'
    i = crudo.find(aguja)
    if i < 0:
        return "", False
    resto = crudo[i + len(aguja):]
    k = 0
    n = len(resto)
    while k < n and resto[k] in " \t\r\n":
        k += 1
    if k >= n or resto[k] != ":":
        return "", False
    k += 1
    while k < n and resto[k] in " \t\r\n":
        k += 1
    if k >= n:
        return "", False          # la clave llego, el valor todavia no
    if resto[k] != '"':
        return "", False          # no es una cadena: aqui no hay nada que ver
    k += 1

    salida: list[str] = []
    while k < n:
        c = resto[k]
        if c == "\\":
            if k + 1 >= n:
                break             # escape a medias: se corta aqui
            siguiente = resto[k + 1]
            if siguiente == "u":
                if k + 6 > n:
                    break         # \uXXXX incompleto
                try:
                    salida.append(chr(int(resto[k + 2:k + 6], 16)))
                except ValueError:
                    pass
                k += 6
                continue
            salida.append(ESCAPES.get(siguiente, siguiente))
            k += 2
            continue
        if c == '"':
            return "".join(salida), True
        salida.append(c)
        k += 1
    return "".join(salida), False


@dataclass
class Plano:
    """Un fotograma: una sola cosa, la que pasa ahora."""

    id: int
    que: str
    """`escribiendo`, `leyendo`, `pensando`, `diciendo`, `ejecutando`..."""
    sobre: str = ""
    herramienta: str = ""
    texto: str = ""
    parcial: bool = True
    """Sigue creciendo. `False` es "esto ya esta entero"."""
    aterrizo: bool = False
    """El texto no crecio: llego de golpe. Se distingue a proposito --
    el visor no puede fingir que algo se escribio si aterrizo."""
    negado: bool = False
    hay_imagen: bool = False
    id_uso: str = ""
    """A que herramienta pertenece. Es lo unico que permite saber
    despues si ESTE plano fue el que se denego."""
    vivo: bool = True
    """Hay turno. Al cerrarse, el ultimo plano se queda como una pausa en
    vez de irse a negro: quedarse en negro borra lo ultimo que hizo justo
    cuando lo vas a mirar."""
    momento: float = field(default_factory=time.time)

    def a_json(self) -> dict[str, Any]:
        texto = self.texto
        if len(texto) > TOPE_ENVIADO:
            # Creciendo interesa el FINAL, que es donde esta el cursor;
            # aterrizado interesa el principio, que es por donde se lee.
            texto = (texto[-TOPE_ENVIADO:] if self.parcial
                     else texto[:TOPE_ENVIADO])
        return {"id": self.id, "que": self.que, "sobre": self.sobre,
                "herramienta": self.herramienta, "texto": texto,
                "parcial": self.parcial, "aterrizo": self.aterrizo,
                "negado": self.negado, "hay_imagen": self.hay_imagen,
                "vivo": self.vivo, "momento": self.momento}


@dataclass
class _Bloque:
    clase: str
    herramienta: str = ""
    id_uso: str = ""
    crudo: str = ""
    visible: str = ""


class Camara:
    """Sigue el flujo y sabe que se esta viendo AHORA.

    Come los mismos eventos que todo lo demas y devuelve, como mucho, una
    cosa por evento: el plano entero cuando cambia, o el pedacito nuevo
    cuando solo crece. Los dos con el id del plano, porque una pestaña
    puede engancharse a mitad y tiene que saber a que pertenece lo que
    llega.
    """

    def __init__(self) -> None:
        self.plano: Plano | None = None
        self._bloques: dict[tuple[int, int], _Bloque] = {}
        self._mensaje = 0
        self._actual: tuple[int, int] | None = None
        self._por_uso: dict[str, Plano] = {}
        """Los planos de este turno, por la herramienta a la que van.

        >>> HACE FALTA PORQUE LA CAMARA TIENE QUE PODER VOLVER <<<
        Un mensaje puede pedir dos herramientas de golpe, y entonces los
        dos planos se crean seguidos ANTES de que vuelva ninguna de las
        dos. Sin esto, la salida de la primera no se enseña nunca --
        medido contra la traza real: el `dir` se quedo con su linea de
        ordenes y sus 370 caracteres de salida no aparecieron. Los
        resultados llegan en orden, asi que la camara puede hacer un
        barrido: enseña lo que acaba de aterrizar, que es lo que un POV
        haria.
        """
        self._siguiente_id = 1
        self._cerrojo = threading.Lock()

    # --- lo que entra ---------------------------------------------------

    def ve(self, evento: Evento) -> dict[str, Any] | None:
        """Un evento. Devuelve lo que hay que mandar a la pagina, o nada."""
        with self._cerrojo:
            return self._ve(evento)

    def _ve(self, evento: Evento) -> dict[str, Any] | None:
        if isinstance(evento, AbreMensaje):
            # >>> EL INDICE REINICIA AQUI, Y ESO YA COSTO UNA MEDICION <<<
            # Un turno con tres herramientas trae tres mensajes y tres
            # bloques con indice 0. Contando solo el indice, el `Write`
            # que se venia a mirar lo machacaba el `Read` siguiente.
            self._mensaje += 1
            return None

        if isinstance(evento, AbreBloque):
            clave = (self._mensaje, evento.indice)
            self._bloques[clave] = _Bloque(
                clase=evento.clase, herramienta=evento.herramienta,
                id_uso=evento.id_uso)
            self._actual = clave
            return self._nuevo_plano(self._bloques[clave])

        if isinstance(evento, Trozo):
            clave = (self._mensaje, evento.indice)
            bloque = self._bloques.get(clave)
            if bloque is None or not evento.texto:
                return None
            bloque.crudo += evento.texto
            return self._crecer(clave, bloque)

        if isinstance(evento, CierraBloque):
            clave = (self._mensaje, evento.indice)
            if self.plano is not None and clave == self._actual:
                self.plano.parcial = False
                return self._entero()
            return None

        if isinstance(evento, UsoHerramienta):
            # Aqui llega la entrada COMPLETA. Sirve para dos cosas: poner
            # el asunto exacto (el nombre del archivo pudo llegar
            # troceado) y atar el plano a su `id_uso`, que es lo unico que
            # permite saber despues si ESTO se denego.
            return self._con_la_entrada(evento)

        if isinstance(evento, ResultadoHerramienta):
            return self._con_el_resultado(evento)

        if isinstance(evento, Fin):
            self._bloques.clear()
            self._por_uso.clear()
            self._actual = None
            if self.plano is None:
                return None
            self.plano.parcial = False
            self.plano.vivo = False
            return self._entero()

        return None

    # --- como se arma un plano ------------------------------------------

    def _nuevo_plano(self, bloque: _Bloque) -> dict[str, Any]:
        if bloque.clase == "thinking":
            que, sobre = "pensando", ""
        elif bloque.clase == "text":
            que, sobre = "diciendo", ""
        else:
            que = QUE_HACE.get(bloque.herramienta, "usando")
            sobre = ""
        self.plano = Plano(id=self._siguiente_id, que=que, sobre=sobre,
                           herramienta=bloque.herramienta)
        self._siguiente_id += 1
        return self._entero()

    def _crecer(self, clave: tuple[int, int],
                bloque: _Bloque) -> dict[str, Any] | None:
        if self.plano is None or clave != self._actual:
            return None
        antes = bloque.visible
        if bloque.clase == "tool_use":
            campo = CUERPO.get(bloque.herramienta, "")
            bloque.visible = (valor_parcial(bloque.crudo, campo)[0]
                              if campo else "")
            # El asunto tambien va llegando a trozos: se refresca mientras
            # no este el `UsoHerramienta`, que es el que manda.
            nuevo_sobre = self._asunto_parcial(bloque.crudo)
            if nuevo_sobre and nuevo_sobre != self.plano.sobre:
                self.plano.sobre = nuevo_sobre
                self.plano.texto = bloque.visible
                return self._entero()
        else:
            bloque.visible = bloque.crudo

        if bloque.visible == antes:
            return None
        # Lo normal: el visible crece por el final y solo viaja lo nuevo.
        if bloque.visible.startswith(antes):
            mas = bloque.visible[len(antes):]
            self.plano.texto = _recortado(self.plano.texto + mas)
            return {"clase": "Cuadro", "id": self.plano.id, "mas": mas}
        # Y si no crecio por el final -- un escape que se completa y
        # cambia lo de atras --, se manda el plano entero. Pasa poco y
        # arreglarlo con un parche seria peor que mandar 4 KB.
        self.plano.texto = _recortado(bloque.visible)
        return self._entero()

    def _asunto_parcial(self, crudo: str) -> str:
        """El nombre del archivo, SOLO cuando la ruta ha llegado entera.

        >>> Y ESTO NO ES UN DETALLE: LO DESTAPO UN TURNO DE VERDAD <<<
        La ruta tambien viaja a trozos, asi que a mitad de camino vale
        `C:/Users/.../pov_e2e_toi3muo2/` -- y quedarse con el ultimo
        pedazo de ESO da el nombre de la CARPETA. Medido: el rotulo
        enseño "escribiendo pov_e2e_toi3muo2" antes de enseñar
        "escribiendo saludo.md". No es feo, es falso: durante ese rato
        dice que esta escribiendo una cosa que no existe.
        Es la regla de las tres salidas otra vez -- "todavia esta
        llegando" no es "esto es el nombre" --, y por eso se mira el
        `completo` que `valor_parcial` ya devolvia y nadie usaba.
        """
        for clave in SOBRE:
            valor, completo = valor_parcial(crudo, clave)
            if valor and completo:
                return _solo_el_nombre(valor)
        return ""

    def _con_la_entrada(self, evento: UsoHerramienta) -> dict[str, Any] | None:
        if self.plano is None:
            return None
        cambio = False
        for clave in SOBRE:
            valor = evento.entrada.get(clave)
            if isinstance(valor, str) and valor.strip():
                nuevo = _solo_el_nombre(valor)
                if nuevo != self.plano.sobre:
                    self.plano.sobre = nuevo
                    cambio = True
                break
        if self.plano.herramienta != evento.herramienta:
            self.plano.herramienta = evento.herramienta
            self.plano.que = QUE_HACE.get(evento.herramienta, "usando")
            cambio = True
        self.plano.id_uso = evento.id_uso
        self._por_uso[evento.id_uso] = self.plano
        return self._entero() if cambio else None

    def _con_el_resultado(self,
                          evento: ResultadoHerramienta) -> dict[str, Any] | None:
        suyo = self._por_uso.get(evento.id_uso)
        if suyo is None:
            return None
        # La camara vuelve sobre el: es lo que acaba de pasar.
        self.plano = suyo
        self.plano.parcial = False
        if evento.es_error:
            # >>> LO QUE SE VIO ESCRIBIR PUEDE NO HABER PASADO <<<
            # El contenido viaja antes de la puerta. Si el usuario dice
            # que no, el visor ya enseño el documento entero -- y callarse
            # dejaria en pantalla algo que no existe. Lo dice.
            self.plano.negado = True
            return self._entero()
        if evento.imagenes:
            self.plano.hay_imagen = True
        if self.plano.herramienta not in ESCRIBEN:
            # Aqui el asunto es lo que SALIO, no lo que se pidio. Y se
            # marca `aterrizo`: no se escribio delante de nadie, aparecio
            # de golpe, y el visor no puede fingir lo contrario.
            self.plano.texto = _recortado(evento.contenido or "")
            self.plano.aterrizo = True
        return self._entero()

    def _entero(self) -> dict[str, Any]:
        assert self.plano is not None
        return {"clase": "Plano", **self.plano.a_json()}

    # --- lo que sale ----------------------------------------------------

    def a_json(self) -> dict[str, Any] | None:
        """El plano de ahora, para una pestaña que acaba de llegar."""
        with self._cerrojo:
            if self.plano is None:
                return None
            return self._entero()


def _recortado(texto: str) -> str:
    return texto[-TOPE_GUARDADO:] if len(texto) > TOPE_GUARDADO else texto


def _solo_el_nombre(ruta: str) -> str:
    limpio = ruta.strip().replace("\\", "/").rstrip("/")
    return limpio.rsplit("/", 1)[-1] or ruta
