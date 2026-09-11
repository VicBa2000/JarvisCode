"""Lo que Jarvis deja detras de un turno, para que se pueda VER.

>>> EL AGUJERO QUE TAPA, DICHO POR EL USUARIO <<<
Lo dicho por el usuario: si le pide crear un documento que resuma el
proyecto, lo hace y sale perfecto, pero si no le pide EXPLICITAMENTE que
lo abra, no lo ve nunca. Eso no es una funcion que falte: es una salida a
medias. Jarvis produce cosas y no las ensena.
produce cosas y no las ensena.

>>> Y NO ES "VISION", AUNQUE LO PAREZCA <<<
El usuario lo planteo asi y le puso un toggle delante porque gasta
tokens. Con razon -- pero son DOS cosas:

    que TU veas lo que hizo      esto. UI nuestra leyendo eventos que ya
                                 tenemos y disco local. CERO tokens, y no
                                 sale nada de la maquina.
    que CLAUDE vea               meterle imagenes a la sesion. Eso si
                                 cuesta, y el contenido VIAJA: eje 2 de
                                 JC-0007.

Aqui solo esta lo primero, y por eso NO lleva interruptor: esconder
detras de un toggle lo unico que es gratis seria cobrarle al usuario por
donde no cuesta. Lo segundo lo decidio el usuario en su forma mas
acotada -- solo lo que ya devuelve una herramienta, su pantalla no se
captura NUNCA -- asi que esta tanda no abre una sola superficie nueva
hacia la nube.

>>> UN `Write` DENEGADO NO ES UNA PIEZA, Y ESTO NO SE PUEDE COLAR <<<
`UsoHerramienta` llega ANTES de ejecutar y puede acabar en la puerta y
en un `no`. Apuntar ahi seria listar como "producido" un archivo que no
existe, y el usuario lo descubriria pinchandolo. Se apunta la INTENCION
al ver el uso y solo se convierte en pieza con su `ResultadoHerramienta`
sin error. Es la misma regla que el resto del arbol: los mensajes dicen
lo que se pidio, el disco dice lo que paso.

>>> SE SIRVE POR ID, JAMAS POR RUTA <<<
La pagina pide `/pieza/<id>`. Una ruta que sirviera el archivo que
nombre el navegador seria una forma elegante de que cualquier cosa que
corra en esta PC se lea el disco entero por `127.0.0.1` -- y el suelo de
JC-0007 no la taparia, porque el suelo gobierna a Claude Code, no a
nuestro servidor. El id no es adivinable y solo existe para lo que la
sesion produjo de verdad.

>>> LAS IMAGENES NO VIAJAN EN EL JSON DE LOS EVENTOS <<<
Una captura son cientos de KB en base64 y `consola.a_json` hace `asdict`
de cada evento hacia CADA cliente conectado. Se guardan aqui, con tope, y
la pagina las pide por id. En el registro crudo ya estaban (`Sesion._leer`
escribe la linea entera antes de interpretarla), asi que esto no engorda
nada que no estuviera engordado.

Y una propiedad heredada gratis: `UsoHerramienta` llega TAMBIEN en auto
mode -- sordos no es ciegos, medido el 2026-08-27 contra los cinco
modos --, asi que esto funciona igual con JC-0017 puesto.
"""

from __future__ import annotations

import base64
import mimetypes
import secrets
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from puente.protocolo import Evento, Fin, ResultadoHerramienta, UsoHerramienta

CLASE_ARCHIVO = "archivo"
CLASE_IMAGEN = "imagen"
CLASE_HUECO = "hueco"
"""Una pieza que ESTUVO y ya no esta: se solto para hacer sitio.

>>> UN HUECO SILENCIOSO ES MENTIR SOBRE LO QUE PASO <<<
En la v2 esto era una lista, y una lista a la que le falta una entrada
no se distingue de una lista a la que nunca le entro. En la v3 es una
SECUENCIA -- lo nuevo entra por la derecha y empuja lo anterior --, y en
una secuencia un salto silencioso dice que ese trabajo no ocurrio. La
lapida conserva el sitio, el nombre y el turno; lo unico que pierde son
los bytes, que es exactamente lo que se solto.
"""

# Las que dejan un archivo con su ruta en la entrada. `Bash` y
# `PowerShell` NO estan, y no es un olvido: una orden de shell puede
# crear archivos y no hay forma honesta de saber cuales sin adivinar la
# linea de ordenes, que es exactamente lo que ya costo dos tandas de
# puertas equivocadas (el `2>&1` del 27 y el acento grave del 29).
HERRAMIENTAS_CON_ARCHIVO = {
    "Write": "file_path",
    "Edit": "file_path",
    "NotebookEdit": "notebook_path",
}

# Lo que la consola intenta pintar en linea. Lo que no este aqui se
# ofrece para abrir fuera y punto: pintar 40 MB de `.blend` en un
# navegador no ensena nada y tarda.
TEXTO_PINTABLE = {
    ".md", ".txt", ".py", ".json", ".yaml", ".yml", ".html", ".css", ".js",
    ".csv", ".xml", ".ini", ".toml", ".cfg", ".log", ".sh", ".ps1", ".sql",
}

# Topes. No son de gusto: esto vive en un proceso que corre todo el dia.
TOPE_PIEZAS = 60
TOPE_IMAGENES_BYTES = 24 * 1024 * 1024
TOPE_VISTA_BYTES = 512 * 1024
"""Lo maximo que se lee de un archivo para pintarlo. Por encima se dice
el tamano y se ofrece abrirlo fuera, que es mas honesto que un recorte
sin avisar."""


@dataclass(frozen=True)
class Pieza:
    """Algo que existe porque Jarvis lo hizo, y que se puede mirar."""

    id: str
    clase: str
    nombre: str
    tipo: str
    """Media type, para que el navegador sepa que hacer con ello."""
    herramienta: str
    turno: int
    momento: float = field(default_factory=time.time)
    ruta: Path | None = None
    datos: bytes | None = None
    """Solo las imagenes. Un archivo se lee del disco cuando se pide, y
    eso es a proposito: si el turno lo edito tres veces, lo que interesa
    ver es como quedo, no la primera version."""

    @property
    def se_pinta_en_linea(self) -> bool:
        # La lapida se dice explicita en vez de caer por el `ruta is
        # None` de abajo: quien lea esto tiene que ver que un hueco NO
        # se pinta porque ya no hay nada que pintar, no por accidente.
        if self.clase == CLASE_HUECO:
            return False
        if self.clase == CLASE_IMAGEN:
            return True
        return bool(self.ruta) and self.ruta.suffix.lower() in TEXTO_PINTABLE

    def a_json(self) -> dict:
        return {
            "id": self.id, "clase": self.clase, "nombre": self.nombre,
            "tipo": self.tipo, "herramienta": self.herramienta,
            "turno": self.turno, "momento": self.momento,
            "en_linea": self.se_pinta_en_linea,
            "ruta": str(self.ruta) if self.ruta else "",
            "existe": bool(self.ruta and self.ruta.is_file()),
            "bytes": self._bytes(),
        }

    def _bytes(self) -> int:
        if self.datos is not None:
            return len(self.datos)
        try:
            return self.ruta.stat().st_size if self.ruta else 0
        except OSError:
            return 0


class Producido:
    """Lo que ha dejado la sesion, en orden y con tope.

    NO se vacia en cada turno. La queja era "nunca lo veo", y vaciar al
    empezar el siguiente turno significaria que el documento desaparece
    de la pantalla justo cuando el usuario va a mirarlo.
    """

    def __init__(self, tope: int = TOPE_PIEZAS,
                 tope_imagenes: int = TOPE_IMAGENES_BYTES) -> None:
        self.tope = tope
        self.tope_imagenes = tope_imagenes
        self.turno = 0
        self.olvidadas = 0
        """Cuantas piezas se cayeron enteras por `tope`.

        Las imagenes que se sueltan por peso dejan LAPIDA, porque el
        hueco esta en medio de la secuencia. Estas se caen por el
        extremo viejo, donde una lapida por cada una llenaria la tira de
        losas; ahi basta un "+N antes", que es lo mismo que dice el
        borde de cualquier scroll.
        """
        self._piezas: list[Pieza] = []
        self._intenciones: dict[str, tuple[str, Path]] = {}
        self._cerrojo = threading.Lock()

    # --- lo que entra ---------------------------------------------------

    def ve(self, evento: Evento) -> Pieza | None:
        """Mira un evento. Devuelve la pieza nueva, si la hubo."""
        if isinstance(evento, Fin):
            with self._cerrojo:
                self.turno += 1
                self._intenciones.clear()
            return None

        if isinstance(evento, UsoHerramienta):
            clave = HERRAMIENTAS_CON_ARCHIVO.get(evento.herramienta)
            if not clave:
                return None
            destino = evento.entrada.get(clave)
            if not isinstance(destino, str) or not destino.strip():
                return None
            with self._cerrojo:
                # Solo la INTENCION. Todavia puede acabar en la puerta y
                # en un `no`, y un archivo denegado no es una pieza.
                self._intenciones[evento.id_uso] = (
                    evento.herramienta, Path(destino))
            return None

        if not isinstance(evento, ResultadoHerramienta):
            return None
        if evento.es_error:
            with self._cerrojo:
                self._intenciones.pop(evento.id_uso, None)
            return None

        with self._cerrojo:
            intencion = self._intenciones.pop(evento.id_uso, None)
        nueva = None
        if intencion is not None:
            herramienta, ruta = intencion
            nueva = self._guardar(Pieza(
                id=secrets.token_urlsafe(12), clase=CLASE_ARCHIVO,
                nombre=ruta.name, tipo=_tipo_de(ruta),
                herramienta=herramienta, turno=self.turno, ruta=ruta))
        for imagen in evento.imagenes:
            try:
                datos = base64.b64decode(imagen.datos, validate=True)
            except (ValueError, TypeError):
                continue
            nueva = self._guardar(Pieza(
                id=secrets.token_urlsafe(12), clase=CLASE_IMAGEN,
                nombre=_nombre_de_imagen(imagen.tipo, self.turno),
                tipo=imagen.tipo, herramienta="", turno=self.turno,
                datos=datos))
        return nueva

    def _guardar(self, pieza: Pieza) -> Pieza:
        with self._cerrojo:
            # Una misma ruta escrita tres veces en un turno es UNA pieza,
            # no tres: lo que interesa ver es el archivo, no cuantas
            # pasadas hizo el modelo por el.
            if pieza.clase == CLASE_ARCHIVO:
                self._piezas = [p for p in self._piezas
                                if not (p.clase == CLASE_ARCHIVO
                                        and p.ruta == pieza.ruta)]
            self._piezas.append(pieza)
            sobran = len(self._piezas) - self.tope
            if sobran > 0:
                self.olvidadas += sobran
                del self._piezas[:sobran]
            self._podar_imagenes()
        return pieza

    def _podar_imagenes(self) -> None:
        """Suelta los bytes de las imagenes mas viejas hasta caber.

        >>> Y DEJA LAPIDA, QUE ES EL CAMBIO DE LA v3 <<<
        Antes la pieza desaparecia de la lista. En una lista eso no se
        notaba; en una TIRA que cuenta una secuencia, un salto sin avisar
        dice que ese trabajo nunca ocurrio. La pieza se queda en su
        sitio, con su nombre y su turno, y sin bytes -- que es justo lo
        que se solto.

        Los archivos no ocupan nada aqui: de ellos solo se guarda la
        ruta, y se leen del disco cuando se piden.
        """
        total = sum(len(p.datos) for p in self._piezas if p.datos)
        if total <= self.tope_imagenes:
            return
        for i, pieza in enumerate(self._piezas):
            if pieza.datos is None:
                continue
            total -= len(pieza.datos)
            self._piezas[i] = replace(pieza, clase=CLASE_HUECO, datos=None)
            if total <= self.tope_imagenes:
                break

    # --- lo que sale ----------------------------------------------------

    @property
    def piezas(self) -> tuple[Pieza, ...]:
        with self._cerrojo:
            return tuple(reversed(self._piezas))

    def piezas_del_turno(self, turno: int) -> tuple[Pieza, ...]:
        """Lo producido en UN turno. Lo usa la voz al cerrar.

        OJO CON EL NUMERO: `ve(Fin)` incrementa `turno`, y la consola
        alimenta esto ANTES de avisar a la voz. Asi que cuando la voz va
        a hablar, el turno que acaba de cerrar es `turno - 1`. Se pasa
        explicito en vez de tener un "el ultimo": un `-1` mal puesto se
        ve al leerlo, y "el ultimo" segun quien lo mire son dos cosas.
        """
        with self._cerrojo:
            return tuple(p for p in self._piezas if p.turno == turno)

    def por_id(self, id_pieza: str) -> Pieza | None:
        with self._cerrojo:
            for pieza in self._piezas:
                if pieza.id == id_pieza:
                    return pieza
        return None

    def contenido_de(self, id_pieza: str,
                     tope: int | None = None) -> tuple[bytes, str] | None:
        """Los bytes de una pieza y su media type. `None` si no la hay.

        >>> LA UNICA PUERTA AL DISCO, Y SOLO POR ID <<<
        No existe una version de esto que acepte una ruta. Si la hubiera,
        cualquiera que alcance `127.0.0.1` leeria el disco entero, y el
        suelo de JC-0007 no lo taparia: aquel gobierna a Claude Code, no
        a nuestro servidor.

        `tope` es para el VISTAZO de la tira: cada ficha de documento
        ensena sus primeras lineas, y traerse 512 KB por cada una para
        pintar cuatro renglones es tonteria. Nunca puede AMPLIAR el tope
        de siempre -- se toma el menor de los dos --, o seria una forma
        elegante de pedir un archivo entero por la query.
        """
        pieza = self.por_id(id_pieza)
        if pieza is None:
            return None
        cuanto = min(tope, TOPE_VISTA_BYTES) if tope else TOPE_VISTA_BYTES
        if pieza.datos is not None:
            # Una imagen NO se recorta: media imagen no es una miniatura,
            # son bytes rotos que el navegador pinta a medias o no pinta.
            # La tira encoge las imagenes con CSS, que es gratis.
            return pieza.datos, pieza.tipo
        if pieza.ruta is None or not pieza.ruta.is_file():
            return None
        try:
            with pieza.ruta.open("rb") as f:
                return f.read(cuanto), pieza.tipo
        except OSError:
            return None

    def a_json(self) -> dict:
        return {"piezas": [p.a_json() for p in self.piezas],
                "turno": self.turno,
                "olvidadas": self.olvidadas}


def _tipo_de(ruta: Path) -> str:
    tipo, _ = mimetypes.guess_type(ruta.name)
    if tipo:
        return tipo
    # El defecto es texto plano y no `octet-stream` a proposito: casi
    # todo lo que escribe un agente de codigo es texto, y un `.py` sin
    # tipo registrado se lee perfectamente como texto.
    return "text/plain" if ruta.suffix.lower() in TEXTO_PINTABLE else \
        "application/octet-stream"


def _nombre_de_imagen(tipo: str, turno: int) -> str:
    extension = mimetypes.guess_extension(tipo) or ".png"
    return f"vista_{turno}{extension}"
