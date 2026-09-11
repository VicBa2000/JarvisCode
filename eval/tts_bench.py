"""Measure Piper voices to close ADR-0003, which says the voice is
chosen BY MEASURED LATENCY and that the accent is indifferent.

    .venv\\Scripts\\python.exe -m eval.tts_bench
    .venv\\Scripts\\python.exe -m eval.tts_bench --repeticiones 7 --oir

WHAT IT MEASURES, and why it is the first-chunk number that decides:
The target is "first audio under 0.5 s", not the whole reply under
0.5 s. Only the first is felt by someone waiting, and it is what makes
the documented mitigation work -- speaking an acknowledgement while
the planner is still writing the plan.

THE PHRASES ARE NOT INVENTED. The rule learned on 2026-08-11 the
expensive way: a probe fed hand-written text measures the wording of
whoever wrote the probe. So the approval question here is rendered by
the REAL `PeticionAprobacion.render()`, with arguments of the shape the
executor actually produces. It matters beyond tidiness: that question is
the one Fase 5 will read out loud before touching anything, it is the
longest thing Jarvis says, and it is full of file paths and tool names
with dots -- which is exactly the text a TTS handles worst.

THE FIRST RUN OF EACH VOICE IS DISCARDED, out loud rather than
silently: onnxruntime warms up on the first call and that run measures
the warm-up, not the voice. `--incluir-calentamiento` keeps it visible
for whoever wants to see the size of that penalty.
"""

from __future__ import annotations

import argparse
import statistics
from dataclasses import dataclass

from seguridad.aprobacion import PeticionAprobacion
from voz.tts import TTS, DIR_VOCES, Habla, TTSError, voces_disponibles


def _frases() -> list[tuple[str, str]]:
    """(etiqueta, texto) for each thing Jarvis really says."""
    aprobacion = PeticionAprobacion(
        herramienta="fs.move_many",
        args={
            "origen": "C:\\Users\\Usuario\\Downloads",
            "patron": "*.jpg",
            "destino": "C:\\Users\\Usuario\\Downloads\\imagenes",
        },
        motivo="mueve archivos en bloque",
        paso=3,
        descripcion="mover las imagenes a su carpeta",
    ).render()

    return [
        # The documented mitigation: said BEFORE the plan is ready, so its
        # latency is the one the user perceives as Jarvis's reaction time.
        ("acuse", "Vale, voy."),
        # The most common real reply: a task that closed well.
        ("resultado", "Listo. He movido 36 archivos a sus carpetas por tipo."),
        # The honest one, which exists because a doubt is its own answer.
        (
            "sin_confirmar",
            "He hecho parte del trabajo, pero no me consta que la orden quedara "
            "cumplida del todo. Quedan doce archivos sin mover.",
        ),
        # The gate. Long, and full of paths and dotted tool names.
        ("aprobacion", aprobacion),
    ]


@dataclass
class Resultado:
    voz: str
    carga_s: float
    medidas: dict[str, list[Habla]]

    def mediana(self, etiqueta: str, campo: str) -> float:
        return statistics.median(
            getattr(h, campo) for h in self.medidas[etiqueta]
        )

    def peor_primer_audio(self) -> float:
        return max(
            max(h.primer_audio_s for h in hablas) for hablas in self.medidas.values()
        )


def _medir_voz(
    nombre: str, repeticiones: int, incluir_calentamiento: bool, oir: bool
) -> Resultado:
    tts = TTS(voz=nombre)
    medidas: dict[str, list[Habla]] = {}

    for etiqueta, texto in _frases():
        hablas: list[Habla] = []
        # +1 because the first is the warm-up and is dropped below.
        for indice in range(repeticiones + 1):
            habla = tts.medir(texto)
            if indice == 0 and not incluir_calentamiento:
                continue
            hablas.append(habla)
        medidas[etiqueta] = hablas

    if oir:
        tts.hablar(
            f"Hola, soy la voz {nombre.replace('_', ' ')}. "
            "Listo. He movido treinta y seis archivos a sus carpetas por tipo."
        )

    return Resultado(voz=nombre, carga_s=tts.carga_s, medidas=medidas)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "voces",
        nargs="*",
        help="Voces a medir. Por defecto, todas las de modelos/piper.",
    )
    parser.add_argument("--repeticiones", type=int, default=5)
    parser.add_argument(
        "--incluir-calentamiento",
        action="store_true",
        help="No descartar la primera pasada de cada voz (mide el warm-up "
        "de onnxruntime, no la voz).",
    )
    parser.add_argument(
        "--oir",
        action="store_true",
        help="Ademas de medir, decir una frase con cada voz por el altavoz "
        "configurado. ADR-0003 pide enseñarle el resultado al usuario.",
    )
    args = parser.parse_args()

    nombres = args.voces or voces_disponibles()
    if not nombres:
        print(f"No hay ninguna voz en {DIR_VOCES}.")
        print("Se bajan con: python -m piper.download_voices NOMBRE "
              "--download-dir modelos/piper")
        return 1

    etiquetas = [etiqueta for etiqueta, _ in _frases()]
    resultados: list[Resultado] = []

    print(f"Midiendo {len(nombres)} voces, {args.repeticiones} repeticiones.")
    print(f"Meta: primer audio < 0.5 s.\n")

    for nombre in nombres:
        try:
            resultados.append(
                _medir_voz(nombre, args.repeticiones, args.incluir_calentamiento, args.oir)
            )
            print(f"  medida {nombre}")
        except TTSError as exc:
            print(f"  FALLO {nombre}: {exc}")

    if not resultados:
        return 1

    print("\nPRIMER AUDIO (mediana en segundos), por frase")
    cabecera = f"{'voz':24s} {'carga':>6s} " + " ".join(f"{e:>14s}" for e in etiquetas)
    print(cabecera)
    print("-" * len(cabecera))
    for r in sorted(resultados, key=lambda r: r.peor_primer_audio()):
        celdas = " ".join(
            f"{r.mediana(e, 'primer_audio_s'):14.3f}" for e in etiquetas
        )
        print(f"{r.voz:24s} {r.carga_s:6.2f} {celdas}")

    print("\nFACTOR DE TIEMPO REAL (mediana; >1 = mas rapido que hablar)")
    for r in sorted(resultados, key=lambda r: -r.mediana("aprobacion", "factor_tiempo_real")):
        celdas = " ".join(
            f"{r.mediana(e, 'factor_tiempo_real'):14.1f}" for e in etiquetas
        )
        print(f"{r.voz:24s} {'':6s} {celdas}")

    print("\nDISPERSION del peor caso (frase 'aprobacion'), en segundos")
    print("Sin esto no se puede leer la tabla de arriba: una mediana buena")
    print("con un maximo malo es una voz que a veces se hace esperar.")
    for r in resultados:
        valores = [h.primer_audio_s for h in r.medidas["aprobacion"]]
        print(
            f"  {r.voz:24s} min {min(valores):.3f}  mediana "
            f"{statistics.median(valores):.3f}  max {max(valores):.3f}"
        )

    cumplen = [r for r in resultados if r.peor_primer_audio() < 0.5]
    print(f"\nCUMPLEN LA META EN TODAS LAS FRASES: {len(cumplen)} de {len(resultados)}")
    for r in sorted(cumplen, key=lambda r: r.peor_primer_audio()):
        print(f"  {r.voz:24s} peor primer audio {r.peor_primer_audio():.3f} s")
    if not cumplen:
        print("  ninguna. La meta se renegocia para el TTS, como ya se hizo")
        print("  con el planner, y se documenta el numero real.")

    print("\nLA LATENCIA NO DECIDE SOLA: ADR-0003 dice que el acento es")
    print("indiferente, no que el timbre lo sea. Correr con --oir y")
    print("enseñarle las candidatas al usuario antes de escribir")
    print("voz.tts.voz en config/jarvis.yaml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
