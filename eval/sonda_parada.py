"""Mide `voz/parada.py` contra las 30 ordenes REALES ya grabadas.

    .venv\\Scripts\\python.exe -m eval.sonda_parada            (usa la traza)
    .venv\\Scripts\\python.exe -m eval.sonda_parada --transcribir

>>> POR QUE ESTA SONDA NO SE INVENTA SUS FRASES <<<
La regla: una sonda que construye su propia entrada mide la sonda. Es
facil escribir `mirar("para")` y ver que sale PARA -- y eso no dice nada,
porque el STT no entrega "para", entrega 'para.' con punto, 'Cancela' con
mayuscula y 'No, ese no.' con una coma en medio. Las tres formas rompen
una comparacion ingenua, y las tres estan en disco desde el 2026-08-21.

Asi que la entrada sale de `eval/audio_ordenes/`, que son 30 ordenes
dictadas por el usuario y etiquetadas a oido, pasadas por el STT DE
PRODUCCION (`small` con ancla de vocabulario). El resultado se guarda en
`eval/trazas_voz/ordenes_small_ancla.json` para que los tests puedan
correr contra el texto real sin cargar Whisper: transcribir las 30 cuesta
~63 s, y un test que cuesta un minuto es un test que no se corre.

>>> LO QUE ESTA TANDA NO PUEDE CONTESTAR <<<
**Ninguna de las 30 grabaciones contiene "para" como preposicion.** O
sea que el corpus prueba que las paradas se cazan y que 27 ordenes
normales no disparan, pero NO prueba la regla dificil, la de la palabra
ambigua enterrada en una frase larga. Eso solo lo contesta hablar cerca
del microfono mientras Jarvis trabaja y contar cuantas veces se para sin
que nadie se lo pidiera. Hasta entonces esa regla esta razonada, no
medida, y asi esta escrito en `voz/parada.py`.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from voz.parada import Veredicto, mirar

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIR_AUDIO = PROJECT_ROOT / "eval" / "audio_ordenes"
TRAZA = PROJECT_ROOT / "eval" / "trazas_voz" / "ordenes_small_ancla.json"

# Que indices del corpus SON una parada. Va aqui y no se deduce del texto
# para que la referencia sea la etiqueta puesta a oido, no lo que el
# reconocedor opine: si un dia cambia `voz/parada.py`, esto no se mueve.
#   26 'cancela'   27 'para'   29 'no, ese no'
PARADAS_DEL_CORPUS = frozenset({26, 27, 29})


def transcribir() -> list[dict]:
    """Pasa los 30 wav por el STT de produccion y devuelve lo que dijo."""
    import soundfile as sf

    from voz.stt import STT
    from voz.vad import VAD

    etiquetas = json.loads(
        (DIR_AUDIO / "ordenes.json").read_text(encoding="utf-8"))
    stt, vad = STT(), VAD()
    filas = []
    inicio = time.perf_counter()
    for indice, etiqueta in enumerate(etiquetas, start=1):
        ruta = DIR_AUDIO / f"{indice:02d}.wav"
        audio, _sr = sf.read(ruta, dtype="float32")
        habla = vad.recortar(audio)
        t = stt.transcribir(audio, hay_habla_vad=habla.hay_habla)
        filas.append({
            "indice": indice,
            "dicho": etiqueta,
            "texto": t.texto.strip(),
            "sin_habla": t.sin_habla,
            "prob_sin_habla": round(t.prob_sin_habla, 4),
            "hay_habla_vad": habla.hay_habla,
            "modelo": t.modelo,
            "con_ancla": bool(t.ancla),
        })
        print(f"  {indice:02d} {t.texto.strip()!r}")
    print(f"\n  {time.perf_counter() - inicio:.1f} s las 30")
    return filas


def guardar(filas: list[dict]) -> None:
    TRAZA.parent.mkdir(parents=True, exist_ok=True)
    TRAZA.write_text(json.dumps(filas, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    print(f"  -> {TRAZA.relative_to(PROJECT_ROOT)}")


def evaluar(filas: list[dict]) -> int:
    """Cuenta aciertos y errores, y ensena los dos tipos por separado.

    Se separan a proposito: una parada perdida y una parada falsa no
    cuestan lo mismo ni se arreglan igual, y sumarlas en un "28/30"
    esconde cual de las dos esta pasando.
    """
    perdidas, falsas, dudosas = [], [], []
    for fila in filas:
        juicio = mirar(fila["texto"])
        es_parada = fila["indice"] in PARADAS_DEL_CORPUS
        if juicio.veredicto is Veredicto.DUDOSA:
            dudosas.append((fila, juicio))
        if es_parada and juicio.veredicto is not Veredicto.PARA:
            perdidas.append((fila, juicio))
        if not es_parada and juicio.veredicto is Veredicto.PARA:
            falsas.append((fila, juicio))

    print(f"\n  paradas del corpus      {len(PARADAS_DEL_CORPUS)}")
    print(f"  paradas PERDIDAS        {len(perdidas)}"
          "   (el agente sigue actuando: es la cara)")
    print(f"  paradas FALSAS          {len(falsas)}"
          f"   sobre {len(filas) - len(PARADAS_DEL_CORPUS)} ordenes normales")
    print(f"  dudosas                 {len(dudosas)}"
          "   (sono a parada y la tuberia dijo que nadie hablo)")

    for titulo, casos in (("PERDIDAS", perdidas), ("FALSAS", falsas),
                          ("DUDOSAS", dudosas)):
        for fila, juicio in casos:
            print(f"    {titulo:8} {fila['indice']:02d} "
                  f"dicho {fila['dicho']!r} -> {juicio.describe()}")

    for fila in filas:
        if fila["indice"] in PARADAS_DEL_CORPUS:
            print(f"    parada   {fila['indice']:02d} "
                  f"{mirar(fila['texto']).describe()}")

    return 1 if (perdidas or falsas) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transcribir", action="store_true",
        help="Vuelve a pasar los 30 wav por el STT y regenera la traza "
             "(~63 s). Sin esto se lee la traza de disco.")
    args = parser.parse_args()

    if args.transcribir:
        print("Transcribiendo las 30 ordenes con el STT de produccion:")
        filas = transcribir()
        guardar(filas)
    else:
        if not TRAZA.is_file():
            print(f"No hay traza en {TRAZA}. Corre con --transcribir.")
            return 2
        filas = json.loads(TRAZA.read_text(encoding="utf-8"))
        print(f"Traza: {TRAZA.relative_to(PROJECT_ROOT)} "
              f"({len(filas)} ordenes, modelo {filas[0]['modelo']})")

    return evaluar(filas)


if __name__ == "__main__":
    raise SystemExit(main())
