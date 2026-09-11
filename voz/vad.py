"""Voice activity detection with silero, on CPU via onnxruntime.

WHERE THE MODEL COMES FROM, and why no new dependency: openWakeWord
downloads `silero_vad.onnx` alongside its own models, so the VAD is
already on disk. The `silero-vad` package on PyPI would pull torch and
torchaudio (~250 MB) to run the same network. Measured 2026-08-20.

WHAT IT BUYS, in the two ways that matter here:

1. CORRECTNESS. Whisper invents sentences out of room tone -- 10 of 12
   takes of real silence produced fluent Spanish (see `voz/stt.py`).
   The fix is not a better threshold downstream; it is never handing
   Whisper audio that has no speech in it.

2. LATENCY. Whisper processes whatever window it is given, silence
   included. A 6 s recording of a 3 s command costs twice what it should,
   and the budget for STT is 1.0 s. Measured on this machine: a 6 s
   dictation carries ~3.2 s of speech.

THE RISK THIS MODULE CARRIES is cutting words off, and it is the only
thing worth testing: a VAD that trims aggressively looks great on a
latency table and quietly loses the last word of every order. So the
test is not "does it trim" but "does the transcription stay the same
while the audio gets shorter".

AND NO SPEECH IS ITS OWN ANSWER. `recortar` on audio where nobody
spoke does not return the audio unchanged, because that would hand
Whisper exactly the silence that makes it hallucinate. `Habla.hay_habla`
is the branch the caller must take.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np

from voz.audio import SAMPLE_RATE_VOZ

# Silero at 16 kHz consumes fixed-size blocks. 512 gives 32 ms of
# resolution, which is finer than the pauses between words.
BLOQUE = 512

# Above this the block counts as speech. Silero's own default.
UMBRAL = 0.5

# Shorter bursts than this are not words: a cough, a key, a chair.
MIN_HABLA_MS = 250

# Gaps shorter than this belong INSIDE one utterance. A person pauses
# between words, and cutting there would split one order into two.
MIN_SILENCIO_MS = 300

# Kept on each side of the speech. The model marks where energy rises,
# which is slightly after a soft consonant starts -- and the cost of
# being generous here is a few milliseconds of Whisper, while the cost
# of being tight is a lost first syllable.
RELLENO_MS = 150


class VADError(RuntimeError):
    """The silero model is missing or cannot be run."""


def ruta_del_modelo() -> Path:
    """Locate `silero_vad.onnx` inside the openWakeWord install."""
    try:
        import openwakeword
    except ImportError as exc:  # pragma: no cover
        raise VADError(
            "openwakeword no esta instalado; es de donde sale silero_vad.onnx"
        ) from exc
    ruta = (
        Path(os.path.dirname(openwakeword.__file__))
        / "resources"
        / "models"
        / "silero_vad.onnx"
    )
    if not ruta.is_file():
        raise VADError(
            f"Falta {ruta}. Se descarga una vez con:\n"
            f"  python -c \"import openwakeword.utils as u; u.download_models()\"\n"
            f"  (con REQUESTS_CA_BUNDLE apuntando a .certs/bundle.pem)"
        )
    return ruta


@dataclass(frozen=True)
class Habla:
    """Where speech was found in a buffer, and what is left after trimming."""

    audio: np.ndarray
    segmentos: tuple[tuple[int, int], ...]
    duracion_original_s: float
    sample_rate: int = SAMPLE_RATE_VOZ

    @property
    def hay_habla(self) -> bool:
        return bool(self.segmentos)

    @property
    def duracion_s(self) -> float:
        return len(self.audio) / self.sample_rate

    @property
    def recorte(self) -> float:
        """Fraction of the original buffer removed."""
        if not self.duracion_original_s:
            return 0.0
        return 1 - (self.duracion_s / self.duracion_original_s)

    def describe(self) -> str:
        if not self.hay_habla:
            return f"SIN HABLA en {self.duracion_original_s:.1f} s de audio"
        return (
            f"{len(self.segmentos)} segmento(s), "
            f"{self.duracion_original_s:.1f} s -> {self.duracion_s:.1f} s "
            f"({self.recorte:.0%} recortado)"
        )


class VAD:
    """Silero, loaded once and reused."""

    def __init__(self, umbral: float = UMBRAL) -> None:
        import onnxruntime as ort

        self.umbral = umbral
        try:
            # CPUExecutionProvider EXPLICITO. onnxruntime tambien ofrece
            # AzureExecutionProvider, que envia la inferencia a un
            # endpoint remoto: en un proyecto cuya premisa es "100 %
            # local, sin telemetria" el proveedor no se deja al
            # criterio de la libreria.
            self._sesion = ort.InferenceSession(
                str(ruta_del_modelo()), providers=["CPUExecutionProvider"]
            )
        except VADError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VADError(f"No se pudo cargar silero: {exc}") from exc

    def probabilidades(self, audio: np.ndarray) -> np.ndarray:
        """Speech probability per block of `BLOQUE` samples."""
        plano = np.asarray(audio, dtype="float32").reshape(-1)
        h = np.zeros((2, 1, 64), dtype="float32")
        c = np.zeros((2, 1, 64), dtype="float32")
        sr = np.array(SAMPLE_RATE_VOZ, dtype="int64")
        salidas = []
        for inicio in range(0, len(plano) - BLOQUE + 1, BLOQUE):
            trozo = plano[inicio : inicio + BLOQUE].reshape(1, -1)
            fuera, h, c = self._sesion.run(
                None, {"input": trozo, "sr": sr, "h": h, "c": c}
            )
            salidas.append(float(fuera[0][0]))
        return np.array(salidas, dtype="float32")

    def segmentos(self, audio: np.ndarray) -> list[tuple[int, int]]:
        """Speech spans as (start, end) sample offsets.

        Short gaps are bridged before short bursts are dropped, and the
        order matters: doing it the other way round would delete the
        halves of a word split by its own pause, and then find nothing
        left to bridge.
        """
        probs = self.probabilidades(audio)
        if not len(probs):
            return []

        activo = probs >= self.umbral
        bloques_silencio = max(1, int(MIN_SILENCIO_MS * SAMPLE_RATE_VOZ / 1000 / BLOQUE))
        bloques_habla = max(1, int(MIN_HABLA_MS * SAMPLE_RATE_VOZ / 1000 / BLOQUE))

        crudos: list[list[int]] = []
        for indice, hay in enumerate(activo):
            if hay:
                if crudos and indice - crudos[-1][1] <= bloques_silencio:
                    crudos[-1][1] = indice + 1
                else:
                    crudos.append([indice, indice + 1])

        relleno = int(RELLENO_MS * SAMPLE_RATE_VOZ / 1000)
        total = len(np.asarray(audio).reshape(-1))
        spans = []
        for inicio, fin in crudos:
            if fin - inicio < bloques_habla:
                continue
            spans.append(
                (
                    max(0, inicio * BLOQUE - relleno),
                    min(total, fin * BLOQUE + relleno),
                )
            )
        return spans

    def recortar(self, audio: np.ndarray) -> Habla:
        """Keep only what was spoken, from first word to last.

        Keeps the INTERIOR of the utterance untouched -- the pauses
        between words go to Whisper along with the words, because a
        transcriber uses them. What gets cut is the dead air before
        someone starts and after they stop, which is where the latency
        and the hallucinations live.
        """
        plano = np.asarray(audio, dtype="float32").reshape(-1)
        spans = self.segmentos(plano)
        original = len(plano) / SAMPLE_RATE_VOZ
        if not spans:
            return Habla(
                audio=np.zeros(0, dtype="float32"),
                segmentos=(),
                duracion_original_s=original,
            )
        return Habla(
            audio=plano[spans[0][0] : spans[-1][1]],
            segmentos=tuple(spans),
            duracion_original_s=original,
        )


# ======================================================================
#  JC-0013: FIN DE TURNO. Cuando el usuario ha dejado de hablar.
# ======================================================================
#
# Lo de arriba RECORTA un buffer que ya existe. Esto decide, EN VIVO,
# cuando ese buffer deja de crecer. Son dos preguntas distintas y por eso
# tienen numeros distintos.
#
# >>> `SILENCIO_FIN_TURNO_MS` NO ES `MIN_SILENCIO_MS`, Y CONFUNDIRLOS ES
# >>> EXACTAMENTE EL FALLO QUE ESTA SECCION VIENE A ARREGLAR. <<<
#
#   MIN_SILENCIO_MS (300)  un hueco mas corto que esto va DENTRO de una
#                          frase: uno pausa entre palabras. Cortar ahi
#                          parte una orden en dos.
#   SILENCIO_FIN_TURNO_MS  cuanto silencio significa "he terminado".
#
# El usuario lo dijo asi al decidirlo: "parar cuando dejo de hablar, no
# cuando le de su gana al VAD". La gana del VAD es cortar en la pausa en
# la que respiras o buscas la palabra. Por eso el numero de fin de turno
# es casi tres veces el otro, y por eso una racha de habla NO se rompe
# con un hueco de menos de MIN_SILENCIO_MS.

# Silencio seguido que cierra el turno. El ADR lo situa en 700-900 ms.
SILENCIO_FIN_TURNO_MS = 800

# Paciencia para que empiece a hablar. Si nadie habla en este rato, la
# ventana se cierra SIN HABLA en vez de quedarse esperando: es la tercera
# salida, y ademas es mas rapida que la ventana fija que sustituye.
ESPERA_INICIO_MS = 3000

# EL TOPE DURO, y no se quita nunca. `voz/audio.py` lo trae porque un
# cuelgue grabando costo un reinicio del PC el 2026-08-20, y en esta
# maquina hay 16 endpoints que entregan silencio digital perfecto sin dar
# error. Una ventana que cierra "cuando dejes de hablar" necesita su
# maximo absoluto por encima, o un fallo del VAD es una grabacion
# infinita.
TOPE_TURNO_S = 20.0


class Cierre(str, Enum):
    """Por que dejo de grabar. Tres salidas, no dos."""

    SILENCIO = "silencio"      # dejaste de hablar: el caso bueno
    TOPE = "tope"              # se acabo el maximo absoluto
    SIN_HABLA = "sin_habla"    # nunca empezaste
    # Y una cuarta que NO es un veredicto del VAD: alguien mas necesitaba
    # el microfono y esta ventana se solto sin terminar. No dice nada
    # sobre si hablaste -- por eso quien la recibe no puede leerla como un
    # "no habia habla" ni transcribir lo que se llevaba grabado.
    ABORTADO = "abortado"


@dataclass(frozen=True)
class Turno:
    """Lo que se grabo y COMO se cerro la ventana."""

    audio: np.ndarray
    cierre: Cierre
    duracion_s: float
    # Segundo en el que se le dio por empezado el habla. None si nunca.
    empezo_en_s: float | None = None

    @property
    def hay_habla(self) -> bool:
        return self.cierre is not Cierre.SIN_HABLA


class FinDeTurno:
    """Silero corriendo EN VIVO sobre el audio segun entra.

    QUE DECIDE Y QUE NO. Decide UNICAMENTE cuando parar de grabar. NO
    decide si alguien hablo: eso lo sigue contestando `VAD.recortar`
    sobre el buffer entero, que es lo que esta medido (30/30 ordenes y
    12/12 silencios de la misma sala, 2026-08-21). Si los dos
    discrepasen manda el de despues, porque ve el clip completo y con el
    modelo reiniciado; este va a ciegas hacia delante y no puede
    revisar lo que ya dijo.

    POR QUE ES OTRA PASADA Y NO REUSA `probabilidades`: aquella reinicia
    el estado recurrente (h, c) en cada llamada, que es lo correcto para
    un buffer suelto y lo incorrecto aqui -- reiniciarlo cada 32 ms le
    quita al modelo justo la memoria con la que distingue una pausa de
    un final.
    """

    def __init__(
        self,
        vad: "VAD",
        silencio_fin_ms: float = SILENCIO_FIN_TURNO_MS,
        espera_inicio_ms: float = ESPERA_INICIO_MS,
    ) -> None:
        self._vad = vad
        self._h = np.zeros((2, 1, 64), dtype="float32")
        self._c = np.zeros((2, 1, 64), dtype="float32")
        self._sr = np.array(SAMPLE_RATE_VOZ, dtype="int64")
        self._resto = np.zeros(0, dtype="float32")

        por_bloque_ms = BLOQUE * 1000 / SAMPLE_RATE_VOZ
        self._bloques_fin = max(1, round(silencio_fin_ms / por_bloque_ms))
        self._bloques_hueco = max(1, round(MIN_SILENCIO_MS / por_bloque_ms))
        self._bloques_habla = max(1, round(MIN_HABLA_MS / por_bloque_ms))
        self._espera_inicio_s = espera_inicio_ms / 1000

        self._bloques_vistos = 0
        self._habla_en_racha = 0
        self._silencio_seguido = 0
        self.empezo_en_s: float | None = None
        self.cierre: Cierre | None = None

    @property
    def segundos_vistos(self) -> float:
        return self._bloques_vistos * BLOQUE / SAMPLE_RATE_VOZ

    def empujar(self, trozo: np.ndarray) -> Cierre | None:
        """Consume audio nuevo. Devuelve el cierre cuando toca parar.

        Se puede llamar con trozos de cualquier tamaño: lo que no llega a
        un bloque entero se guarda para la siguiente. Que el ultimo
        cachito quede sin mirar no importa -- son menos de 32 ms.
        """
        if self.cierre is not None:
            return self.cierre

        plano = np.asarray(trozo, dtype="float32").reshape(-1)
        self._resto = np.concatenate([self._resto, plano])
        enteros = len(self._resto) // BLOQUE
        for i in range(enteros):
            bloque = self._resto[i * BLOQUE : (i + 1) * BLOQUE]
            self._un_bloque(bloque)
            if self.cierre is not None:
                break
        self._resto = self._resto[enteros * BLOQUE :]
        return self.cierre

    def _un_bloque(self, bloque: np.ndarray) -> None:
        fuera, self._h, self._c = self._vad._sesion.run(
            None,
            {"input": bloque.reshape(1, -1), "sr": self._sr,
             "h": self._h, "c": self._c},
        )
        self._bloques_vistos += 1
        hay_habla = float(fuera[0][0]) >= self._vad.umbral

        if hay_habla:
            self._silencio_seguido = 0
            self._habla_en_racha += 1
            if (self.empezo_en_s is None
                    and self._habla_en_racha >= self._bloques_habla):
                # Cuenta desde donde empezo la racha, no desde ahora: los
                # MIN_HABLA_MS que hicieron falta para creersela son
                # habla, no preambulo.
                self.empezo_en_s = max(
                    0.0,
                    self.segundos_vistos
                    - self._habla_en_racha * BLOQUE / SAMPLE_RATE_VOZ,
                )
            return

        self._silencio_seguido += 1

        if self.empezo_en_s is None:
            # Todavia no ha empezado. Un hueco largo mata la racha: lo que
            # habia era una tos, una tecla, una silla.
            if self._silencio_seguido >= self._bloques_hueco:
                self._habla_en_racha = 0
            if self.segundos_vistos >= self._espera_inicio_s:
                self.cierre = Cierre.SIN_HABLA
            return

        # Ya empezo. AQUI y solo aqui manda el numero de fin de turno.
        if self._silencio_seguido >= self._bloques_fin:
            self.cierre = Cierre.SILENCIO
