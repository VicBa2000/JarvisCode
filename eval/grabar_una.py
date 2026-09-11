"""Record ONE dictated order, play its prompt, and check it right away.

    .venv\\Scripts\\python.exe -m eval.grabar_una 7

WHY THIS EXISTS instead of `stt_bench --grabar --desde N --hasta N`,
which does the same thing on paper: that path loads Piper (2.7 s) and
then Whisper (2.0 s) on every single invocation, and `TTS.hablar` waits
up to `duracion + 5 s` for the output buffer to drain. Dictating one
order cost 12-15 s of waiting that produced nothing, and from the other
side of the microphone that is indistinguishable from a hang.

So the prompts are pre-rendered once into `eval/audio_avisos/` and this
plays a WAV. No TTS model is loaded at all, and the only model left is
the Whisper used to check what was heard -- which is the point of
dictating one at a time.

WHAT "CHECKING" MEANS HERE, because it is not the benchmark: the WER
printed is against `small`, just to confirm the recording captured the
right sentence before moving on. ADR-0006 is decided later by
`eval/stt_bench.py` over every model and every recording.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from eval.stt_bench import DIR_AUDIO, ORDENES, wer
from voz.audio import SAMPLE_RATE_VOZ, ConfigAudio, grabar, reproducir

DIR_AVISOS = Path(__file__).resolve().parent / "audio_avisos"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("indice", type=int, help="Numero de orden (1-30).")
    # 6 s y no 4: medido el 2026-08-20, con 4 s la ventana se
    # cerraba antes del final de la frase ("organiza mi carpeta de
    # descargas por" - falta 'tipo'), porque el tiempo de reaccion de
    # quien dicta cuenta dentro de la ventana. El silencio sobrante no
    # cuesta WER, y el VAD de 5.3 lo recortara para la latencia.
    parser.add_argument("--segundos", type=float, default=6.0)
    parser.add_argument(
        "--sin-aviso",
        action="store_true",
        help="No reproducir el aviso hablado (util si ya sabes la frase).",
    )
    args = parser.parse_args()

    if not 1 <= args.indice <= len(ORDENES):
        print(f"El indice va de 1 a {len(ORDENES)}.")
        return 1

    import soundfile as sf

    orden = ORDENES[args.indice - 1]
    micro = ConfigAudio.desde_config().microfono()
    DIR_AUDIO.mkdir(parents=True, exist_ok=True)

    print(f"[{args.indice}/{len(ORDENES)}]  «{orden}»", flush=True)

    if not args.sin_aviso:
        aviso = DIR_AVISOS / f"{args.indice:02d}.wav"
        if aviso.is_file():
            audio_aviso, sr = sf.read(aviso, dtype="float32")
            # Via `voz.audio.reproducir` y NO `sd.play`: las funciones de
            # conveniencia de sounddevice comparten un stream global con
            # `sd.rec` y se bloquean entre si. Aguanto seis frases y
            # colgo en la septima, que es como se comporta una carrera.
            reproducir(audio_aviso, sr, ConfigAudio.desde_config().altavoz())
        else:
            print(f"  (sin aviso pregrabado en {aviso})")

    print("  GRABANDO...", flush=True)
    inicio = time.perf_counter()
    audio = grabar(micro, args.segundos)
    destino = DIR_AUDIO / f"{args.indice:02d}.wav"
    sf.write(destino, audio, SAMPLE_RATE_VOZ)

    nivel = 20 * np.log10(float(np.sqrt(np.mean(audio**2))) + 1e-12)
    print(f"  guardado {destino.name}  ({nivel:.1f} dBFS)", flush=True)

    # La comprobacion en caliente: sin esto, un fallo de dictado no se
    # descubre hasta el final, cuando ya no se sabe cual salio mal.
    from voz.stt import STT

    t = STT(modelo="small").transcribir(audio)
    error = wer(orden, t.texto)
    veredicto = "OK" if error == 0 else f"REVISAR (WER {error:.0%})"
    print(f"  oido: {t.texto.strip()!r}")
    print(f"  {veredicto}   [{time.perf_counter() - inicio:.1f} s]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
