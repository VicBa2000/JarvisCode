"""Ancla de vocabulario en el STT: ¿arregla algo, y a costa de que?

LA PREGUNTA. El banco de 30 deja `small` en 24/30, y de las 6 fallas solo
TRES son del modelo: 'bloc' -> 'blog', tres veces. No las arregla un
modelo mayor (large-v3 tambien las falla: "abre el blog de notas" es
español plausible y el modelo esta SEGURO de lo que oye). Lo que si
podria atacarlas es decirle de antemano que palabras existen en este
dominio -- `initial_prompt` y `hotwords` de faster-whisper --, y eso
quedo SIN MEDIR en el proyecto original.

POR QUE ESTA SONDA NO PUEDE RESPONDER "CUANTO MEJORA", y conviene leerlo
antes que la tabla: el suceso que se quiere arreglar ocurre **3 veces en
30**. La regla de este proyecto es explicita -- con 0, 1 o 2
apariciones la tanda no responde nada, y 3 esta justo en el borde. Asi
que esto NO estima una tasa.
estima una tasa.

LO QUE SI RESPONDE, que es lo que hace falta para decidir:
  1) si el mecanismo DISPARA (comprobado antes de escribirla, en una
     traza suelta: las tres pasaron de 'blog' a 'bloc');
  2) **si rompe alguna de las otras 27**, que es el riesgo real. Anclar
     vocabulario sesga al modelo hacia esas palabras, y un sesgo que
     arregla tres cosas y estropea cinco es peor que no hacer nada.

Por eso la salida no es un WER medio: son las ordenes que MEJORAN y las
que EMPEORAN, una a una, contra el control de la misma tanda.

    .venv\\Scripts\\python.exe -m eval.sonda_anclaje
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from eval.stt_bench import ORDENES, wer

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIR_AUDIO = PROJECT_ROOT / "eval" / "audio_ordenes"
DIR_MODELOS = PROJECT_ROOT / "modelos" / "whisper"

# El vocabulario del dominio, no una lista de deseos. Sale de las cosas
# que el usuario nombra al dar ordenes: carpetas de Windows en español,
# aplicaciones, y las dos ordenes de shell que aparecen en el banco.
# NO se meten aqui las frases del banco: eso seria darle las respuestas
# al examen y la sonda mediria la sonda.
VOCABULARIO = (
    "bloc de notas, Descargas, Documentos, Imagenes, Escritorio, "
    "papelera, captura, informe, factura, carpeta, archivo, "
    "navegador, calculadora, explorador, git status, pip list, PDF"
)


@dataclass
class Resultado:
    indice: int
    orden: str
    texto: str
    wer: float
    latencia_s: float


def transcribir_todo(modelo, extra: dict, hasta: int | None) -> list[Resultado]:
    resultados = []
    for indice, orden in enumerate(ORDENES[:hasta], start=1):
        ruta = DIR_AUDIO / f"{indice:02d}.wav"
        if not ruta.exists():
            continue
        audio, _ = sf.read(ruta, dtype="float32")
        arranque = time.perf_counter()
        segmentos, _ = modelo.transcribe(
            np.asarray(audio, dtype="float32").reshape(-1),
            language="es", beam_size=5, condition_on_previous_text=False,
            **extra,
        )
        texto = "".join(s.text for s in segmentos).strip()
        resultados.append(Resultado(
            indice=indice, orden=orden, texto=texto,
            wer=wer(orden, texto),
            latencia_s=time.perf_counter() - arranque,
        ))
    return resultados


def resume(nombre: str, resultados: list[Resultado]) -> None:
    medio = sum(r.wer for r in resultados) / len(resultados)
    perfectas = sum(1 for r in resultados if r.wer == 0)
    latencias = sorted(r.latencia_s for r in resultados)
    print(f"  {nombre:10} WER {medio:5.1%}   perfectas {perfectas:2}/"
          f"{len(resultados)}   lat med {latencias[len(latencias)//2]:.2f}s")


def compara(control: list[Resultado], brazo: list[Resultado],
            nombre: str) -> tuple[int, int]:
    mejoran, empeoran = [], []
    for c, b in zip(control, brazo):
        if b.wer < c.wer - 1e-9:
            mejoran.append((c, b))
        elif b.wer > c.wer + 1e-9:
            empeoran.append((c, b))
    print(f"\n--- {nombre} contra el control ---")
    print(f"  MEJORAN: {len(mejoran)}   EMPEORAN: {len(empeoran)}")
    for c, b in mejoran:
        print(f"    + {c.indice:02d} {c.orden}")
        print(f"        antes: {c.texto}")
        print(f"        ahora: {b.texto}")
    for c, b in empeoran:
        print(f"    - {c.indice:02d} {c.orden}")
        print(f"        antes: {c.texto}")
        print(f"        ahora: {b.texto}")
    if not empeoran:
        print("    (ninguna orden empeoro)")
    return len(mejoran), len(empeoran)


def main() -> int:
    trozos = argparse.ArgumentParser(description=__doc__)
    trozos.add_argument("--modelo", default="small")
    trozos.add_argument("--hasta", type=int, default=None)
    args = trozos.parse_args()

    from faster_whisper import WhisperModel

    print(f"Ancla de vocabulario sobre {args.modelo}, "
          f"{len(ORDENES[:args.hasta])} ordenes reales.")
    print("OJO: el suceso que se quiere arreglar ocurre 3 veces en 30.")
    print("Esto NO estima una tasa; dice si dispara y si rompe algo.\n")

    modelo = WhisperModel(args.modelo, device="cpu", compute_type="int8",
                          download_root=str(DIR_MODELOS))

    brazos = {
        "control": {},
        "prompt": {"initial_prompt": VOCABULARIO},
        "hotwords": {"hotwords": VOCABULARIO},
    }
    salidas: dict[str, list[Resultado]] = {}
    for nombre, extra in brazos.items():
        arranque = time.perf_counter()
        salidas[nombre] = transcribir_todo(modelo, extra, args.hasta)
        print(f"  {nombre} medido en {time.perf_counter()-arranque:.0f} s")

    print("\nRESUMEN")
    for nombre, resultados in salidas.items():
        resume(nombre, resultados)

    for nombre in ("prompt", "hotwords"):
        compara(salidas["control"], salidas[nombre], nombre)

    print("\nCOMO SE LEE: si un brazo mejora las tres de 'bloc' y no")
    print("empeora ninguna, el mecanismo sirve y el coste es cero. Si")
    print("empeora alguna, hay que mirar CUAL: no es lo mismo estropear")
    print("un nombre de carpeta que una palabra de parada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
