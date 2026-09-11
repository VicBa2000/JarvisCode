"""Text to speech with Piper, local and on CPU.

ADR-0001 decides the CPU part: `PiperVoice.load` takes `use_cuda` and it
is left at False on purpose. The 6 GB of this GPU belong to the planner,
and speaking is cheap enough that the 5700G's idle cores can do it while
the GPU is busy planning.

WHAT THE TARGET ACTUALLY ASKS FOR, because it changes the design: it
is "first audio under 0.5 s", not "the whole reply synthesised under
0.5 s". Those are different numbers and only the first one is felt by a
person waiting. `sintetizar` is therefore a GENERATOR that yields chunks
as Piper produces them, and `primer_audio_s` measures the wait until the
first one. It is also what makes the documented mitigation
possible -- speaking an acknowledgement before the plan is finished --
because the sentence can start playing while the rest is still coming.

ADR-0003 says the accent is indifferent and the voice is chosen BY
MEASURED LATENCY. This module therefore names no voice: it takes the one
belonging to the active persona in `config/jarvis.yaml` (see
`voz/perfil.py`), and `eval/tts_bench.py` is what produces the numbers
to choose it with. It goes through the persona rather than through a
setting of its own so that the voice cannot drift apart from the name
the system answers to.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np

from voz.audio import AudioError, ConfigAudio, Dispositivo

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Where `python -m piper.download_voices --download-dir` puts them. Data,
# not code: kept out of the venv so that reinstalling dependencies does
# not throw away 300 MB of models.
DIR_VOCES = PROJECT_ROOT / "modelos" / "piper"


class TTSError(RuntimeError):
    """The voice model is missing, unreadable, or cannot be spoken."""


@dataclass
class Habla:
    """One synthesis, measured.

    `primer_audio_s` is the number that counts. `total_s` is kept beside it
    because reporting only the total would hide exactly the behaviour
    that streaming buys, and reporting only the first chunk would hide a
    voice that starts fast and then crawls.
    """

    texto: str
    voz: str
    primer_audio_s: float
    total_s: float
    segundos_de_audio: float
    sample_rate: int
    audio: np.ndarray = field(repr=False)
    cortado: bool = False
    """Si se dejo de hablar a mitad porque alguien lo pidio (JC-0011).

    No es un error y por eso no se levanta uno: callarse cuando te dicen
    "para" es obedecer. Pero tiene que poder DISTINGUIRSE de haber dicho
    la frase entera, o las medidas se llenarian de frases a
    medias sin que nadie lo supiera.
    """

    @property
    def cumple_meta(self) -> bool:
        """The target for TTS: first audio under 0.5 s."""
        return self.primer_audio_s < 0.5

    @property
    def factor_tiempo_real(self) -> float:
        """Seconds of audio produced per second of work. Above 1 is faster
        than real time, which is what lets a long reply stream without
        the voice ever catching up with the synthesiser."""
        return self.segundos_de_audio / self.total_s if self.total_s else 0.0

    def describe(self) -> str:
        marca = "OK " if self.cumple_meta else "TARDE"
        return (
            f"{marca} {self.voz:24s} primer audio {self.primer_audio_s:5.2f} s "
            f"| total {self.total_s:5.2f} s para {self.segundos_de_audio:4.1f} s "
            f"de habla (x{self.factor_tiempo_real:.1f} tiempo real)"
        )


def voces_disponibles(directorio: Path | None = None) -> list[str]:
    """The voice names present on disk, without their file extension."""
    carpeta = directorio or DIR_VOCES
    if not carpeta.is_dir():
        return []
    return sorted(p.stem for p in carpeta.glob("*.onnx"))


def ruta_de_voz(nombre: str, directorio: Path | None = None) -> Path:
    """Resolve a voice name to its model file, or say what IS available.

    Same shape as `voz.audio.seleccionar`: a name that is not there is an
    error that enumerates the alternatives, never a silent substitution.
    Speaking with a voice nobody asked for is the kind of failure that
    goes unnoticed for weeks.
    """
    carpeta = directorio or DIR_VOCES
    ruta = carpeta / f"{nombre}.onnx"
    if ruta.is_file():
        return ruta
    disponibles = voces_disponibles(carpeta)
    inventario = "\n".join(f"    {v}" for v in disponibles) or "    (ninguna)"
    raise TTSError(
        f"La voz '{nombre}' no esta en {carpeta}.\n"
        f"  descargadas:\n{inventario}\n"
        f"  Se bajan con: python -m piper.download_voices NOMBRE "
        f"--download-dir modelos/piper"
    )


class TTS:
    """A loaded Piper voice, ready to speak.

    Loading is the expensive part (a medium voice is ~63 MB of ONNX), so
    the instance is meant to be kept alive for the session rather than
    rebuilt per sentence.
    """

    def __init__(
        self,
        voz: str | None = None,
        directorio: Path | None = None,
        config_dir: Path | None = None,
    ) -> None:
        self.nombre = voz or self._voz_configurada(config_dir)
        self.ruta = ruta_de_voz(self.nombre, directorio)
        inicio = time.perf_counter()
        try:
            from piper import PiperVoice

            # use_cuda=False is the default and stays that way: ADR-0001.
            self._voz = PiperVoice.load(self.ruta)
        except Exception as exc:  # noqa: BLE001 - onnxruntime raises broadly
            raise TTSError(f"No se pudo cargar la voz {self.nombre}: {exc}") from exc
        self.carga_s = time.perf_counter() - inicio

    @staticmethod
    def _voz_configurada(config_dir: Path | None = None) -> str:
        """The voice of the active persona, never a loose setting.

        Goes through `voz.perfil` so that the voice cannot drift apart
        from the name and the wake word: they are one decision.
        """
        from voz.perfil import PerfilError, perfil_activo

        try:
            return perfil_activo(config_dir).tts_voz
        except PerfilError as exc:
            raise TTSError(str(exc)) from exc

    def sintetizar(self, texto: str) -> Iterator[np.ndarray]:
        """Yield audio chunks as Piper produces them.

        A generator and not a buffer, because the target is about
        when sound STARTS. Piper emits roughly a chunk per sentence, so
        a long reply begins playing while its tail is still being made.
        """
        if not texto.strip():
            return
        try:
            for chunk in self._voz.synthesize(texto):
                yield chunk.audio_float_array
        except Exception as exc:  # noqa: BLE001
            raise TTSError(f"Fallo sintetizando con {self.nombre}: {exc}") from exc

    @property
    def sample_rate(self) -> int:
        return int(self._voz.config.sample_rate)

    def medir(self, texto: str) -> Habla:
        """Synthesise everything, timing the first chunk apart from the rest."""
        inicio = time.perf_counter()
        primer_audio: float | None = None
        trozos: list[np.ndarray] = []
        for trozo in self.sintetizar(texto):
            if primer_audio is None:
                primer_audio = time.perf_counter() - inicio
            trozos.append(trozo)
        total = time.perf_counter() - inicio
        if not trozos:
            raise TTSError(f"La voz {self.nombre} no produjo audio para: {texto!r}")
        audio = np.concatenate(trozos)
        return Habla(
            texto=texto,
            voz=self.nombre,
            primer_audio_s=primer_audio or total,
            total_s=total,
            segundos_de_audio=len(audio) / self.sample_rate,
            sample_rate=self.sample_rate,
            audio=audio,
        )

    # NOTA: `medir` no acepta `cancelar` a proposito. Mide sintesis, no
    # reproduccion, y una medida a medias no es una medida.

    def hablar(self, texto: str, dispositivo: Dispositivo | None = None,
               cancelar: threading.Event | None = None) -> Habla:
        """Say it out loud through the configured speaker.

        >>> `cancelar` ES EL "PARA" DE JC-0011, Y SE CORTA DE VERDAD <<<
        Con ese evento puesto, esto deja de hablar A MITAD DE FRASE: se
        para de sintetizar y el callback deja de entregar muestras. Es la
        forma mas visible de obedecer que tiene un asistente por voz --
        alguien que dice "para" mientras le hablas encima quiere silencio
        AHORA, no cuando acabe el parrafo --, y sin esto el "para" solo
        detendria a Claude Code y dejaria a Jarvis recitando la respuesta
        de algo que ya no se esta haciendo.

        Lo que sale entonces lleva `cortado=True`. No es un error.

        Feeds a callback stream, so the first sentence is already audible
        while the rest is still being synthesised.

        WHY A CALLBACK AND NOT `flujo.write(...)`, which is the obvious
        way and was the first version: PortAudio's BLOCKING write is not
        supported by the DirectSound host API on this machine. It does
        not fail -- it accepts the samples and drops them. Measured on
        2026-08-20, and the numbers are worth keeping because the symptom
        was "the speakers are broken" and the cause was here:

            audio a reproducir 5.51 s  ->  hablar() volvia en 0.30 s

        Same probe across host APIs, 2 s of audio into the same speakers:

            MME          write+close 2.25 s   suena
            DirectSound  write+close 0.05 s   SE PIERDE
            WASAPI       ni abre a 22050 Hz (solo acepta su nativa)

        It is this module's own lesson turned against itself: writing
        into a device that goes nowhere RETURNS SUCCESS, exactly like
        recording from a virtual cable returns silence. The input side
        was guarded from the first line and the output side was not,
        because "the call returned" was taken as evidence that sound came
        out. The callback path is the one `sd.play` uses and it works on
        DirectSound, so the host API stays the same for input and output,
        keeping its full names and its resampling.
        """
        import queue
        import threading

        import sounddevice as sd

        salida = dispositivo or ConfigAudio.desde_config().altavoz()
        cola: queue.Queue[np.ndarray] = queue.Queue()
        sintesis_terminada = threading.Event()
        reproduccion_terminada = threading.Event()
        pendiente = np.empty(0, dtype="float32")

        def alimentar(buffer, frames, _tiempo, _estado):  # noqa: ANN001
            nonlocal pendiente
            if cancelar is not None and cancelar.is_set():
                # Silencio y fuera. Vaciar la cola aqui no hace falta: el
                # stream se cierra y con el se va todo lo pendiente.
                buffer[:, 0] = 0.0
                reproduccion_terminada.set()
                raise sd.CallbackStop
            escrito = 0
            while escrito < frames:
                if pendiente.size == 0:
                    try:
                        pendiente = cola.get_nowait()
                    except queue.Empty:
                        # Silencio para lo que quede del bloque. Si ya no
                        # va a llegar mas audio, ademas se para.
                        buffer[escrito:, 0] = 0.0
                        if sintesis_terminada.is_set():
                            reproduccion_terminada.set()
                            raise sd.CallbackStop
                        return
                toma = min(frames - escrito, pendiente.size)
                buffer[escrito : escrito + toma, 0] = pendiente[:toma]
                pendiente = pendiente[toma:]
                escrito += toma

        inicio = time.perf_counter()
        primer_audio: float | None = None
        trozos: list[np.ndarray] = []
        try:
            flujo = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                device=salida.indice,
                dtype="float32",
                callback=alimentar,
            )
        except Exception as exc:  # noqa: BLE001
            raise AudioError(f"No se pudo abrir la salida {salida}: {exc}") from exc

        cortado = False
        with flujo:
            for trozo in self.sintetizar(texto):
                if cancelar is not None and cancelar.is_set():
                    cortado = True
                    break
                if primer_audio is None:
                    primer_audio = time.perf_counter() - inicio
                trozo = np.ascontiguousarray(trozo, dtype="float32")
                cola.put(trozo)
                trozos.append(trozo)
            # Medido ANTES de esperar a que suene: `total_s` es el coste
            # de SINTETIZAR. Mezclarlo con la duracion del audio haria que
            # una frase larga pareciera una voz lenta.
            total = time.perf_counter() - inicio
            sintesis_terminada.set()
            if trozos:
                duracion = sum(t.size for t in trozos) / self.sample_rate
                # El margen cubre la latencia del dispositivo. El timeout
                # esta para no dejar a Jarvis mudo para siempre si el
                # callback nunca llega a vaciar la cola.
                reproduccion_terminada.wait(timeout=duracion + 5.0)
        cortado = cortado or (cancelar is not None and cancelar.is_set())
        if not trozos:
            if cortado:
                # Le mandaron callar antes de que saliera la primera
                # muestra. No hay audio y NO es un fallo: reventar aqui
                # convertiria obedecer en una excepcion.
                return Habla(
                    texto=texto, voz=self.nombre, primer_audio_s=0.0,
                    total_s=total, segundos_de_audio=0.0,
                    sample_rate=self.sample_rate,
                    audio=np.zeros(0, dtype="float32"), cortado=True,
                )
            raise TTSError(f"La voz {self.nombre} no produjo audio para: {texto!r}")
        audio = np.concatenate(trozos)
        return Habla(
            texto=texto,
            voz=self.nombre,
            primer_audio_s=primer_audio or total,
            total_s=total,
            segundos_de_audio=len(audio) / self.sample_rate,
            sample_rate=self.sample_rate,
            audio=audio,
            cortado=cortado,
        )
