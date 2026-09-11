"""Donde va lo que se dice cuando no hay nadie mirando una terminal.

>>> EL PROBLEMA, MEDIDO Y NO SUPUESTO (2026-08-26) <<<
Arrancando con `pythonw.exe` SIN consola — que es exactamente lo que
pasa en el arranque de Windows — `sys.stdout` vale **None**. Y `print()`
sobre None **no revienta: no hace nada**. Se comprobo lanzando el
interprete con DETACHED_PROCESS y escribiendo el resultado a un archivo:

    stdout=None
    stderr=None
    print ok
    print acentos ok

O sea que el modo de fallo no es un error visible sino el peor de los de
este proyecto: **el silencio**. Si el suelo de JC-0007 no esta en
condiciones, `-m puente` imprime por que y devuelve 3; arrancado desde la
carpeta Inicio, el usuario no ve nada de nada — ni el motivo, ni que haya
pasado algo. Un Jarvis que no arranco es indistinguible de uno que
arranco y no te esta oyendo.

LA SALIDA NO ES TOCAR LOS `print`. Son decenas, y ademas los hay en
`voz/`, en `canales/` y en `puente/`, y manana habra mas. Se redirige
`sys.stdout` y `sys.stderr` a un archivo ANTES de montar nada, y asi
queda recogido todo lo que ya se decia y todo lo que se diga en el
futuro, sin que nadie tenga que acordarse.

Y DE PASO SE ARREGLA LO DE LAS TILDES. Con consola, esa salida sale en
`cp1252` y este proyecto habla español; el archivo se abre en UTF-8, que
es lo que se viene pidiendo desde JC-0003 ("el TTS acabara
diciendo canci?n").

NO SUSTITUYE AL REGISTRO DE LA SESION. `logs/puente/sesion_*.jsonl` sigue
siendo la auditoria de lo que Claude Code hizo. Esto es el diario del
ARRANQUE: por que se pudo o no se pudo levantar.
"""

from __future__ import annotations

import sys
from collections import deque
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIR_LOGS = PROJECT_ROOT / "logs" / "escritorio"

# Cuantas lineas se guardan en memoria para poder enseñarlas sin abrir el
# archivo. Es lo que lee la bandeja cuando algo va mal: quien no tiene
# terminal tampoco tiene ganas de buscar un log.
COLA = 200


class Diario:
    """Un `sys.stdout` que escribe a disco y recuerda las ultimas lineas.

    Se queda ademas con lo que ya hubiera (si es que habia consola), asi
    que lanzarlo desde una terminal sigue enseñando todo por pantalla Y
    lo guarda. No se elige entre las dos cosas.
    """

    def __init__(self, archivo: Path, tambien_a=None) -> None:
        self.archivo = archivo
        self._otro = tambien_a
        self.ultimas: deque[str] = deque(maxlen=COLA)
        archivo.parent.mkdir(parents=True, exist_ok=True)
        # Sin buffer de linea no se veria nada hasta cerrar el proceso, y
        # este proceso esta pensado para no cerrarse nunca.
        self._f = open(archivo, "a", encoding="utf-8", buffering=1,
                       errors="replace")
        self._a_medias = ""

    def write(self, texto: str) -> int:
        if self._otro is not None:
            try:
                self._otro.write(texto)
            except Exception:  # noqa: BLE001 - una consola que se va no importa
                self._otro = None
        try:
            self._f.write(texto)
        except Exception:  # noqa: BLE001
            pass
        self._recordar(texto)
        return len(texto)

    def _recordar(self, texto: str) -> None:
        self._a_medias += texto
        while "\n" in self._a_medias:
            linea, self._a_medias = self._a_medias.split("\n", 1)
            if linea.strip():
                self.ultimas.append(linea.rstrip())

    def flush(self) -> None:
        if self._otro is not None:
            try:
                self._otro.flush()
            except Exception:  # noqa: BLE001
                pass
        try:
            self._f.flush()
        except Exception:  # noqa: BLE001
            pass

    def isatty(self) -> bool:
        return False

    def cerrar(self) -> None:
        try:
            self._f.close()
        except Exception:  # noqa: BLE001
            pass


def encender(nombre: str = "arranque") -> Diario:
    """Redirige la salida a `logs/escritorio/<nombre>_<fecha>.log`.

    Se llama LO PRIMERO, antes de importar nada pesado: si algo revienta
    montando la voz o el suelo, el traceback tiene que caer aqui dentro y
    no en el vacio.
    """
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    diario = Diario(DIR_LOGS / f"{nombre}_{marca}.log", tambien_a=sys.stdout)
    sys.stdout = diario
    sys.stderr = diario
    print(f"=== Jarvis, arranque de escritorio {datetime.now():%Y-%m-%d %H:%M:%S} ===")
    print(f"    interprete: {sys.executable}")
    return diario


def ultimo_log() -> Path | None:
    """El log mas reciente, para poder abrirlo desde la bandeja."""
    if not DIR_LOGS.is_dir():
        return None
    logs = sorted(DIR_LOGS.glob("*.log"), key=lambda r: r.stat().st_mtime)
    return logs[-1] if logs else None
