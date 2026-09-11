"""Calibrate the "nobody spoke" guard, per model, with real audio.

    python -m eval.sonda_sin_habla --grabar-silencio 12   (calla 40 s)
    python -m eval.sonda_sin_habla                        (analiza)

POR QUE EXISTE. `voz/stt.py` compara `no_speech_prob` contra UN SOLO
numero (`UMBRAL_SIN_HABLA = 0.6`) para todos los modelos. Medido el
2026-08-21 sobre las 30 grabaciones del banco -- treinta que SI
contienen habla y que el propio modelo transcribe bien:
    small 20/30    tiny 24/30    large-v3 2/30    base 0/30    medium 0/30
`sin_habla` falla CERRADO, asi que con `small` Jarvis ignoraria dos de
cada tres ordenes bien oidas. Un umbral global sobre una señal que cada
modelo calibra a su manera no es un umbral.

LAS DOS DISTRIBUCIONES O NADA. Un umbral no se puede elegir mirando
solo el habla: bajaria a cero y dejaria pasar cualquier alucinacion
sobre silencio, que es el fallo PELIGROSO. Hace falta tambien silencio
real de esta sala por este microfono. Las 37 tomas del 2026-08-20 se
midieron en vivo y se tiraron; por eso se vuelven a grabar y esta vez
SE GUARDAN EN DISCO, que es lo que las convierte en un banco repetible.

LO QUE ESTA SONDA PUEDE RESPONDER "NO". Si las dos nubes se solapan, no
existe ningun umbral bueno y el informe lo dice en esas palabras, en vez
de devolver el menos malo con cara de resultado. Ya paso una vez: el 20
`no_speech_prob` bajo a 0.351 en alucinaciones, y se concluyo que NO HAY
VALOR que las separe. Esa es una respuesta legitima y es la que manda
apoyarse en la energia y en el VAD de 5.3.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIR_SILENCIO = PROJECT_ROOT / "eval" / "audio_silencio"


def grabar_silencio(tomas: int, segundos: float) -> int:
    """Record room silence, saved as a reusable fixture."""
    import soundfile as sf

    # Via `voz.audio.grabar` y no `sd.rec`: ver el porque en `voz/audio.py`.
    # Aqui importa el doble, porque esto graba muchas veces seguidas.
    from voz.audio import SAMPLE_RATE_VOZ, ConfigAudio, grabar

    DIR_SILENCIO.mkdir(parents=True, exist_ok=True)
    micro = ConfigAudio.desde_config().microfono()
    print(f"Microfono: {micro}")
    print(f"{tomas} tomas de {segundos:.0f} s. NO HABLES.\n", flush=True)

    for i in range(1, tomas + 1):
        audio = grabar(micro, segundos)
        destino = DIR_SILENCIO / f"sil{i:02d}.wav"
        sf.write(destino, audio, SAMPLE_RATE_VOZ)
        import numpy as np

        dbfs = 20 * np.log10(float(np.sqrt(np.mean(audio**2))) + 1e-12)
        print(f"  [{i:2d}/{tomas}] {destino.name}  {dbfs:6.1f} dBFS", flush=True)
    return tomas


def _probs(modelo: str, rutas: list[Path]) -> list[tuple[str, float, str]]:
    """(nombre, no_speech_prob, texto) for each clip, with one model."""
    import soundfile as sf

    from voz.stt import STT

    stt = STT(modelo=modelo)
    fuera = []
    for ruta in rutas:
        audio, _ = sf.read(ruta, dtype="float32")
        # Sin `suelo`: se mide la señal DEL MODELO aislada. El veto de
        # energia es la otra mitad de la guarda y no depende del modelo,
        # asi que mezclarlos aqui esconderia cual de los dos decide.
        t = stt.transcribir(audio)
        fuera.append((ruta.name, t.prob_sin_habla, t.texto.strip()))
    return fuera


def _resumen(vals: list[float]) -> str:
    if not vals:
        return "sin datos"
    return (
        f"min {min(vals):.3f}  p50 {statistics.median(vals):.3f}  "
        f"max {max(vals):.3f}"
    )


def analizar(modelos: list[str]) -> int:
    from eval.stt_bench import DIR_AUDIO

    habla = sorted(DIR_AUDIO.glob("[0-9][0-9].wav"))
    silencio = sorted(DIR_SILENCIO.glob("*.wav"))
    if not habla:
        print(f"No hay grabaciones de habla en {DIR_AUDIO}.")
        return 1
    if not silencio:
        print(f"No hay silencio en {DIR_SILENCIO}.")
        print("Primero: python -m eval.sonda_sin_habla --grabar-silencio 12")
        return 1

    print(f"{len(habla)} con habla, {len(silencio)} de silencio.")
    print(f"Umbral actual en voz/stt.py: 0.6, IGUAL PARA TODOS.\n")

    for modelo in modelos:
        print(f"===== {modelo} =====")
        ph = _probs(modelo, habla)
        ps = _probs(modelo, silencio)
        vh = [p for _, p, _ in ph]
        vs = [p for _, p, _ in ps]
        print(f"  habla    {_resumen(vh)}")
        print(f"  silencio {_resumen(vs)}")

        # Cuantas alucinaciones hay de verdad: un silencio que sale con
        # texto es el caso PELIGROSO, y es el que el umbral debe cazar.
        inventadas = [(n, p, t) for n, p, t in ps if t]
        print(f"  silencios que produjeron TEXTO: {len(inventadas)}/{len(ps)}")

        # ¿Existe umbral perfecto? Se marca sin_habla si prob >= umbral,
        # asi que hace falta que TODO silencio quede por encima de TODA
        # habla. Si no, las nubes se solapan y no hay numero bueno.
        if vs and vh and min(vs) > max(vh):
            u = (min(vs) + max(vh)) / 2
            print(f"  SEPARABLE. Cualquier umbral en ({max(vh):.3f}, "
                  f"{min(vs):.3f}) acierta el 100 %. Sugerido: {u:.3f}")
        else:
            print("  >>> NO SEPARABLE: las nubes se solapan. <<<")
            print("      No existe umbral que acierte los dos lados.")
            # El menos malo, y se dice que es un COMPROMISO, no una
            # solucion: cazar todo silencio a costa de tirar habla.
            if vs:
                cierra = max(vs)
                perdidas = sum(1 for v in vh if v >= min(vs))
                print(f"      Para cazar TODO silencio haria falta "
                      f"umbral <= {min(vs):.3f},")
                print(f"      y eso tiraria {perdidas}/{len(vh)} ordenes "
                      f"BIEN OIDAS.")
                del cierra
            # Y al reves: no tirar ni una orden buena.
            if vh:
                seguro = max(vh)
                escapan = sum(1 for v in vs if v < seguro)
                print(f"      Para no tirar NINGUNA orden buena haria falta "
                      f"umbral > {seguro:.3f},")
                print(f"      y por ahi se colarian {escapan}/{len(vs)} "
                      f"silencios.")
        print(f"  con el 0.6 de hoy: habla marcada "
              f"{sum(1 for v in vh if v >= 0.6)}/{len(vh)}, "
              f"silencio cazado {sum(1 for v in vs if v >= 0.6)}/{len(vs)}")
        print()

    print("RECORDATORIO DE DIRECCION: `sin_habla` falla CERRADO.")
    print("Tirar una orden buena MOLESTA; dejar pasar una alucinacion hace")
    print("ACTUAR sobre una orden que nadie dio. No son intercambiables.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grabar-silencio", type=int, default=0)
    parser.add_argument("--segundos", type=float, default=3.0)
    parser.add_argument("--modelos", nargs="*", default=["base", "small"])
    args = parser.parse_args()

    if args.grabar_silencio:
        n = grabar_silencio(args.grabar_silencio, args.segundos)
        print(f"\n{n} tomas en {DIR_SILENCIO}")
        return 0
    return analizar(args.modelos)


if __name__ == "__main__":
    sys.exit(main())
