"""Recoge audio generado fuera y lo deja como lo espera el banco.

    .venv\\Scripts\\python.exe -m eval.preparar_audio <carpeta> [--idioma en]
    .venv\\Scripts\\python.exe -m eval.preparar_audio <carpeta> --frases

>>> PARA QUE EXISTE <<<
Lo pidio el usuario: generar las frases inglesas con una herramienta de
voz casi nativa y dejarlas en una ruta. Esas herramientas escupen mp3 a
24 o 44,1 kHz con el nombre que les da la gana, y el banco quiere WAV
mono a 16 kHz llamados `01.wav`..`30.wav`. Esto hace la conversion, y
sobre todo hace el EMPAREJADO, que es donde esta el error caro.

>>> LO QUE NO HACE, Y NO ES UN DESCUIDO: ADIVINAR <<<
El indice manda porque el corpus va POR INDICE contra las frases: si el
14 acaba en el sitio del 15, el WER sale mal y no hay nada que lo
delate -- las dos transcripciones seran ingles perfectamente formado.
Es la misma trampa que ya se pago en `eval/stt_bench.py` cuando el banco
de STT importaba sus frases de otro archivo.
Asi que el nombre TIENE que empezar por el numero (`01`, `1`, `07-stop`,
`14_take_a_screenshot`). Lo que no case, se dice y se deja fuera; nunca
se coloca "por orden alfabetico", que es la version automatizada de
inventarse el dato.

>>> Y ESTO NO CONVIERTE UN AUDIO FABRICADO EN UN BANCO <<<
Va a `eval/audio_ordenes_en_tts/`, que es carpeta aparte, y el banco
imprime un aviso en grande al medirla. Medido el 2026-09-08: Piper daba
ya WER 0,0 % y 0,994-0,998 de wake word contra un umbral de 0,5, o sea
que el sintetico esta pegado al techo y una voz mas nativa sale igual de
facil o mas. Lo que le falta no son fonemas: es sala, distancia,
microfono, titubeo y el acento de quien va a usar esto.
Sirve como REGRESION -- si esto empeora, algo se rompio --, jamas como
la cifra que cierra JC-0018.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.stt_bench import corpus_de  # noqa: E402
from voz.audio import SAMPLE_RATE_VOZ  # noqa: E402

# Lo que libsndfile lee en este entorno (comprobado: 1.2.2).
EXTENSIONES = {".wav", ".mp3", ".flac", ".ogg", ".aiff", ".aif"}

# El numero al principio del nombre, con o sin cero delante. No se busca
# "un numero en cualquier parte" a proposito: `report_2026.mp3` tiene
# uno y no es un indice.
#
# >>> ERA `\b` Y RECHAZABA EL SEPARADOR MAS COMUN <<< Se vio probandolo
# con nombres de verdad: `14_take_a_screenshot.wav` no casaba, porque el
# guion bajo ES un caracter de palabra y entre "4" y "_" no hay
# frontera. O sea que la guarda escrita para no adivinar de mas tiraba
# justo el nombre que mas se parece a lo que escupe una herramienta de
# voz. Lo que hay que exigir no es una frontera: es que no siga OTRO
# digito, para que `140` no se lea como `14`.
INDICE = re.compile(r"^(\d{1,2})(?![0-9])")


def _a_16k_mono(audio: np.ndarray, sr: int) -> np.ndarray:
    """Mono y 16 kHz, que es lo unico que los tres modelos de voz comen.

    El remuestreo es lineal y basta: lo que entra ya viene limpio de un
    sintetizador, asi que no hay banda alta que preservar. Si algun dia
    entrara audio de microfono por aqui, esto habria que mirarlo -- y
    por eso lo dice en vez de callarselo.
    """
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = np.asarray(audio, dtype="float32").reshape(-1)
    if sr == SAMPLE_RATE_VOZ:
        return audio
    n = int(round(len(audio) * SAMPLE_RATE_VOZ / sr))
    return np.interp(np.linspace(0, len(audio) - 1, n),
                     np.arange(len(audio)), audio).astype("float32")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("carpeta", nargs="?",
                        help="Donde dejaste los audios generados.")
    parser.add_argument("--idioma", default="en")
    parser.add_argument("--frases", action="store_true",
                        help="Solo imprimir las frases numeradas, para "
                             "pegarlas en la herramienta que las genere.")
    args = parser.parse_args()

    ordenes, destino = corpus_de(args.idioma, sintetico=True)

    if args.frases:
        for i, frase in enumerate(ordenes, start=1):
            print(f"{i:02d}\t{frase}")
        return 0

    if not args.carpeta:
        parser.error("hace falta la carpeta (o --frases)")

    origen = Path(args.carpeta).expanduser()
    if not origen.is_dir():
        print(f"No existe la carpeta {origen}.")
        return 1

    import soundfile as sf

    # --- emparejar, y decir las tres cosas por separado ---------------
    por_indice: dict[int, list[Path]] = {}
    sin_indice: list[Path] = []
    for ruta in sorted(origen.iterdir()):
        if not ruta.is_file() or ruta.suffix.lower() not in EXTENSIONES:
            continue
        casa = INDICE.match(ruta.stem)
        if casa is None:
            sin_indice.append(ruta)
            continue
        por_indice.setdefault(int(casa.group(1)), []).append(ruta)

    fuera_de_rango = [i for i in por_indice if not 1 <= i <= len(ordenes)]
    repetidos = {i: v for i, v in por_indice.items() if len(v) > 1}

    print(f"Origen : {origen}")
    print(f"Destino: {destino}")
    print(f"Corpus : {args.idioma}, {len(ordenes)} frases\n")

    for ruta in sin_indice:
        print(f"  FUERA  {ruta.name}  (el nombre no empieza por un numero)")
    for indice in sorted(fuera_de_rango):
        print(f"  FUERA  indice {indice}: el corpus llega a {len(ordenes)}")
    for indice, rutas in sorted(repetidos.items()):
        print(f"  FUERA  indice {indice} lo reclaman {len(rutas)} archivos: "
              f"{', '.join(r.name for r in rutas)}")
    if sin_indice or fuera_de_rango or repetidos:
        print("\n  Nada de eso se coloca por orden alfabetico: el corpus va")
        print("  POR INDICE, y una frase en el sitio de otra da un WER malo")
        print("  que no delata nada -- las dos son ingles bien formado.\n")

    escribibles = {i: v[0] for i, v in por_indice.items()
                   if len(v) == 1 and 1 <= i <= len(ordenes)}
    if not escribibles:
        print("No hay ni un archivo que colocar.")
        print("Los nombres tienen que empezar por el numero de la frase:")
        print("  01.mp3   7-stop.wav   14_take_a_screenshot.mp3")
        print("Las frases numeradas salen con --frases.")
        return 1

    destino.mkdir(parents=True, exist_ok=True)
    for indice in sorted(escribibles):
        ruta = escribibles[indice]
        try:
            audio, sr = sf.read(ruta, dtype="float32", always_2d=False)
        except Exception as exc:  # noqa: BLE001
            print(f"  NO LEIDO {ruta.name}: {exc}")
            continue
        preparado = _a_16k_mono(audio, sr)
        salida = destino / f"{indice:02d}.wav"
        sf.write(salida, preparado, SAMPLE_RATE_VOZ)
        pico = float(np.max(np.abs(preparado))) if preparado.size else 0.0
        nivel = 20 * np.log10(pico + 1e-12)
        aviso = ""
        # Un sintetizador no entrega silencio, asi que un pico bajisimo
        # es un archivo vacio o un canal equivocado, no una voz floja.
        if pico < 1e-3:
            aviso = "   <-- CASI SILENCIO, mira ese archivo"
        print(f"  {indice:02d}  {ruta.name:38.38}  {sr:6d} Hz -> "
              f"{len(preparado)/SAMPLE_RATE_VOZ:5.2f} s  "
              f"{nivel:6.1f} dBFS{aviso}")
        print(f"      «{ordenes[indice - 1]}»")

    faltan = [i for i in range(1, len(ordenes) + 1) if i not in escribibles]
    print(f"\n{len(escribibles)} colocados en {destino}")
    if faltan:
        # Un corpus a medias NO es un error: el banco mide lo que hay y
        # lo dice. Pero se enumera, porque "faltan 4" y "faltan las 4
        # paradas" no son la misma noticia.
        print(f"Faltan {len(faltan)}: {', '.join(f'{i:02d}' for i in faltan)}")
    print("\nAhora:  .venv\\Scripts\\python.exe -m eval.stt_bench "
          f"--idioma {args.idioma} --sintetico")
    print("Y recuerda lo que ese aviso te va a decir: esto es REGRESION,")
    print("no el banco. El banco lo dictas tu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
