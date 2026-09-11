"""Measure Whisper sizes to close ADR-0006 (small / medium / large-v3).

    .venv\\Scripts\\python.exe -m eval.stt_bench --grabar     (dictas 30)
    .venv\\Scripts\\python.exe -m eval.stt_bench              (evalua)

SE GRABA UNA VEZ Y SE EVALUAN TODOS LOS MODELOS SOBRE EL MISMO AUDIO.
Es lo que hace la pregunta contestable: con tres tamaños, grabar por
modelo serian 90 dictados, y ademas cada tanda mediria una voz distinta
(mas cansada, mas rapida) en vez de medir el modelo. Un WAV en disco es
una entrada fija; una voz repetida no lo es.

WER SOBRE VOZ REAL, NO SINTETICA. Se podria generar el audio con Piper y
ahorrarse el dictado, y estaria midiendo lo bien que Whisper entiende a
Piper -- que no es la pregunta y ademas sale demasiado bien, porque un
TTS vocaliza perfecto y no tiene sala, ni distancia al microfono, ni
prisa. Es la regla del 2026-08-11: una sonda alimentada con entrada
fabricada mide la fabricacion.

QUE HACE DIFICIL UNA ORDEN AQUI, y por eso las frases son las que son:
no la longitud, sino el vocabulario que un modelo entrenado en español
no espera -- 'PDF', 'git status', 'informe.pdf', nombres de carpeta en
mayuscula.

LAS 8 PRIMERAS VENIAN IMPORTADAS DE `eval/planner_bench.py`, el set de
aceptacion del planner local. Ese archivo se borro con la limpieza del
2026-08-21 (aqui no hay planner) y las frases se copiaron aqui LITERALES.
No es una lista de ejemplo que se pueda retocar: **son las frases que se
grabaron**, y `eval/audio_ordenes/orden_NN.wav` va por indice contra esta
lista. Cambiar una palabra desalinea el banco entero y el WER pasaria a
medir otra cosa. Si hay que tocarlas, se regraba (y ver la regla del
audio: se regraba si el AUDIO no contiene la frase, no si el
modelo fallo).
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from voz.audio import SAMPLE_RATE_VOZ, ConfigAudio, calibrar_suelo
from voz.stt import STT, STTError, modelos_descargados

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIR_AUDIO = PROJECT_ROOT / "eval" / "audio_ordenes"

# Las 8 que eran el set de aceptacion del planner (copiadas literales de
# `planner_bench.ORDERS` antes de borrarlo), mas 22 que estiran el mismo
# vocabulario real. No son variaciones bonitas: cada una mete algo que se
# sabe que un STT español maltrata (siglas, extensiones, rutas, numeros,
# ingles). EL ORDEN ES PARTE DEL DATO: casa con los .wav por indice.
ORDENES_ACEPTACION = [
    "organiza mi carpeta de Descargas por tipo",
    "dime que archivos PDF tengo en Documentos",
    "abre el bloc de notas",
    "crea una carpeta llamada Facturas en Documentos",
    "elimina el archivo informe.pdf de Descargas",
    "mueve el archivo informe.pdf de Descargas a Documentos",
    "haz una captura de pantalla",
    "ejecuta git status en la carpeta del proyecto",
]

ORDENES = list(ORDENES_ACEPTACION) + [
    "abre el bloc de notas y escribe informe listo",
    "cierra la ventana del navegador",
    "que hora es",
    "busca los archivos jpg de la carpeta Imagenes",
    "copia el informe de ventas a la carpeta Documentos",
    "renombra el archivo captura punto png",
    "cuantos archivos hay en Descargas",
    "abre la calculadora",
    "ejecuta pip list en la carpeta del proyecto",
    "mueve los pdf de Descargas a Documentos",
    "crea una carpeta que se llame Facturas dos mil veintiseis",
    "borra los archivos temporales de Descargas",
    "dime el tamaño de la carpeta Documentos",
    "abre el explorador de archivos",
    "escribe hola mundo en el bloc de notas",
    "lista las carpetas de mi escritorio",
    "haz una captura y guardala en Imagenes",
    "cancela",
    "para",
    "repite eso",
    "no, ese no",
    "gracias",
]

# >>> EL CORPUS INGLES (JC-0018), Y NO ES UNA TRADUCCION <<<
# Las 8 de aceptacion si son las mismas ordenes -- para poder comparar
# banco contra banco --, pero las ultimas ocho no existen en español y
# son la razon de ser de este corpus.
#
# EN INGLES EL PELIGRO SE INVIERTE, que es el hallazgo de JC-0018: el
# ingles no distingue el imperativo, asi que "stop", "cancel" y "abort"
# son a la vez paradas y principios de ordenes normales. Queda UNA sola
# inequivoca -- `nevermind`, la unica que no es un verbo -- y todo lo
# demas pasa por una ventana de 2 palabras que esta RAZONADA Y NO
# MEDIDA (`voz.idioma.LexicoDeParada.medido` es False en ingles).
# Por eso 23-25 son ORDENES DE TRABAJO que empiezan por una palabra de
# parada: son las que dicen si esa ventana de 2 esta bien puesta, y son
# exactamente el caso que en español no se puede grabar.
# 30 es cortesia: no para, y se parece a las que si paran.
ORDENES_ACEPTACION_EN = [
    "organize my Downloads folder by type",
    "tell me what PDF files I have in Documents",
    "open notepad",
    "create a folder called Invoices in Documents",
    "delete the file report.pdf from Downloads",
    "move the file report.pdf from Downloads to Documents",
    "take a screenshot",
    "run git status in the project folder",
]

ORDENES_EN = list(ORDENES_ACEPTACION_EN) + [
    "open notepad and write report ready",
    "close the browser window",
    "what time is it",
    "find the jpg files in the Pictures folder",
    "copy the sales report to the Documents folder",
    "rename the file screenshot dot png",
    "how many files are in Downloads",
    "open the calculator",
    "run pip list in the project folder",
    "move the PDFs from Downloads to Documents",
    "create a folder called Invoices twenty twenty six",
    "delete the temporary files from Downloads",
    "open the file explorer",
    "take a screenshot and save it in Pictures",
    # 23-25: ordenes de trabajo que EMPIEZAN por palabra de parada.
    "stop the server and restart it",
    "cancel the deployment",
    "abort the migration",
    # 26-29: las paradas de verdad.
    "stop",
    "stop it",
    "nevermind",
    "forget it",
    # 30: cortesia, que no para.
    "thanks",
]

# Los indices (1-based) que SI son una parada. El español tiene el
# mismo dato escrito DOS veces -- `tests/test_voz_parada.PARADAS` y
# `eval/sonda_parada.PARADAS_DEL_CORPUS`, las dos {26, 27, 29} --, que
# es la forma de que un dia dejen de coincidir. Este vive en UN sitio,
# al lado de las frases que numera, y quien lo necesite lo importa.
PARADAS_EN = frozenset({26, 27, 28, 29})

# Y las tres que NO deben parar aunque lo parezcan. Se nombran aparte
# porque no son "las demas": son la medicion que cierra `palabras_max`.
ORDENES_QUE_EMPIEZAN_COMO_PARADA_EN = frozenset({23, 24, 25})

# El corpus de cada canal: las frases y DONDE viven sus wav. La carpeta
# es distinta a proposito -- grabar en ingles sobre `audio_ordenes/`
# machacaria el corpus español, que es irrepetible.
CORPUS = {
    "es": (ORDENES, PROJECT_ROOT / "eval" / "audio_ordenes"),
    "en": (ORDENES_EN, PROJECT_ROOT / "eval" / "audio_ordenes_en"),
}

# >>> Y UNA CARPETA APARTE PARA EL AUDIO FABRICADO <<<
# Un corpus sintetizado con una voz nativa NO es un banco, y la carpeta
# separada es la primera linea de defensa contra que alguien lo cite
# como si lo fuera. Lo que mide es al SINTETIZADOR: medido en esta casa
# el 2026-09-08, Piper ya daba WER 0,0 % y 0,994-0,998 en el wake word
# contra un umbral de 0,5, o sea pegado al techo -- y una voz mas
# natural sale igual de facil o mas, porque lo que le falta no son
# fonemas, es sala, distancia, microfono, titubeo y el acento de quien
# va a usar esto.
# PARA LO QUE SI VALE, y por eso existe: REGRESION. No dice si el ingles
# funciona bien; dice si un dia DEJA de funcionar, y eso es barato de
# tener porque se regenera solo.
CORPUS_SINTETICO = {
    "en": (ORDENES_EN, PROJECT_ROOT / "eval" / "audio_ordenes_en_tts"),
}

AVISO_SINTETICO = """
##################################################################
#  ESTO NO ES UN BANCO. El audio es FABRICADO, asi que lo que    #
#  mide es al sintetizador. Piper ya daba WER 0,0 % y  #
#  0,99 en el wake word: el techo esta aqui, no en lo nativa que #
#  sea la voz. Sirve como REGRESION -- si esto empeora, algo se  #
#  rompio -- y JAMAS como cifra comparable con el 2,4 % del      #
#  español, que es voz real, en una sala real, con un microfono. #
##################################################################"""


def corpus_de(idioma: str, sintetico: bool = False) -> tuple[list[str], Path]:
    """Las frases y DONDE viven sus wav. Tres combinaciones, no cuatro.

    El español sintetico no existe y no se inventa: alli hay 30
    grabaciones reales desde agosto, asi que fabricar una copia peor
    solo serviria para que alguien citara la cifra equivocada.
    """
    if not sintetico:
        return CORPUS[idioma]
    if idioma not in CORPUS_SINTETICO:
        raise STTError(
            f"No hay corpus sintetico de '{idioma}'. El español ya tiene "
            f"30 grabaciones REALES en {CORPUS['es'][1].name}, que es "
            f"mejor dato que cualquier voz fabricada.")
    return CORPUS_SINTETICO[idioma]


def normalizar(texto: str) -> list[str]:
    """Words, lowercased, without punctuation or accents.

    Accents come off because a WER that counts 'organiza' against
    'organizá' as an error would measure the transcriber's punctuation
    habits, not whether the order was understood. What matters here is
    whether the planner would receive the same instruction.
    """
    sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(c) != "Mn"
    )
    limpio = "".join(c if c.isalnum() or c.isspace() else " " for c in sin_tildes)
    return limpio.split()


def wer(referencia: str, hipotesis: str) -> float:
    """Word error rate by Levenshtein distance over words."""
    ref, hip = normalizar(referencia), normalizar(hipotesis)
    if not ref:
        return 0.0 if not hip else 1.0
    previa = list(range(len(hip) + 1))
    for i, palabra_ref in enumerate(ref, start=1):
        actual = [i]
        for j, palabra_hip in enumerate(hip, start=1):
            coste = 0 if palabra_ref == palabra_hip else 1
            actual.append(
                min(previa[j] + 1, actual[j - 1] + 1, previa[j - 1] + coste)
            )
        previa = actual
    return previa[-1] / len(ref)


@dataclass
class Medida:
    orden: str
    transcrito: str
    wer: float
    latencia_s: float
    duracion_audio_s: float
    sin_habla: bool

    @property
    def perfecta(self) -> bool:
        return self.wer == 0.0


def grabar(segundos: float, decir: bool, desde: int = 1, hasta: int | None = None,
           idioma: str = "es") -> int:
    """Dictate the 30 orders once, saving one WAV each.

    No stdin: this runs under a harness that has none, so the rhythm is
    fixed and announced. Run it from your own terminal so you can see
    which order is next.

    `idioma` elige el CORPUS y la CARPETA, y por defecto es el español
    para que todo lo que ya llamaba a esto siga grabando donde grababa.
    """
    import soundfile as sf

    from voz.audio import grabar as grabar_audio

    ordenes, carpeta = corpus_de(idioma)
    carpeta.mkdir(parents=True, exist_ok=True)
    micro = ConfigAudio.desde_config().microfono()
    voz = None
    if decir:
        from voz.tts import TTS

        # >>> LA VOZ QUE DICTA TIENE QUE SER LA DEL IDIOMA <<<
        # Con la española leyendo ingles, lo que oye quien dicta es una
        # pronunciacion equivocada -- y la repite. El corpus saldria
        # midiendo el acento de Piper y no el suyo.
        from voz.idioma import voces_del_idioma
        from voz.tts import voces_disponibles

        hay = voces_disponibles()
        eleccion = next((v for v in voces_del_idioma(idioma) if v in hay), None)
        if eleccion is None:
            raise STTError(
                f"No hay ninguna voz de Piper de '{idioma}' en disco "
                f"({', '.join(voces_del_idioma(idioma))}). Sin ella el "
                f"dictado se leeria con el acento del otro idioma, asi "
                f"que se para en vez de grabar un corpus torcido.")
        voz = TTS(voz=eleccion)

    ultimo = hasta or len(ordenes)
    tramo = [(i, o) for i, o in enumerate(ordenes, start=1) if desde <= i <= ultimo]

    print(f"Microfono: {micro}")
    print(f"Idioma: {idioma}   ->  {carpeta}")
    print(
        f"{len(tramo)} ordenes (de la {desde} a la {ultimo}), "
        f"{segundos:.0f} s cada una."
    )
    print("Habla cuando oigas el aviso. Se puede cortar y continuar")
    print("despues con --desde N: lo ya grabado se conserva.\n")

    if voz is not None:
        # El aviso va HABLADO porque quien dicta esta mirando al
        # microfono, no a la terminal -- y porque esto se lanza desde un
        # arnes cuya salida de texto el usuario ve DESPUES, cuando ya no
        # sirve de nada. El audio es la unica via que llega a tiempo.
        voz.hablar(
            f"Prueba de dictado. Te voy a decir {len(tramo)} ordenes. "
            "Repite cada una en voz alta justo despues de oirla. Empezamos."
        )

    grabadas = 0
    for indice, orden in tramo:
        destino = carpeta / f"{indice:02d}.wav"
        print(f"[{indice:2d}/{len(ordenes)}]  «{orden}»")
        if voz is not None:
            voz.hablar(f"Di: {orden}")
        else:
            time.sleep(1.0)
        print("            GRABANDO...", flush=True)
        # Via `voz.audio.grabar` y NO `sd.rec`: las funciones de
        # conveniencia de sounddevice comparten un stream de modulo con
        # `sd.play`, y este bucle REPRODUCE el aviso justo antes de
        # grabar. Es la receta exacta del cuelgue medido el 2026-08-20
        # (aguanto seis frases y murio en la septima). Se arreglo en
        # `voz/audio.py`, luego en `eval/grabar_una.py`, y este se quedo
        # sin arreglar hasta el 21: arreglar el modulo no arregla a quien
        # no lo usa.
        audio = grabar_audio(micro, segundos)
        sf.write(destino, audio, SAMPLE_RATE_VOZ)
        nivel = 20 * np.log10(float(np.sqrt(np.mean(audio**2))) + 1e-12)
        print(f"            guardado {destino.name}  ({nivel:.1f} dBFS)\n")
        grabadas += 1

    (carpeta / "ordenes.json").write_text(
        json.dumps(ordenes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return grabadas


def _grabaciones(idioma: str = "es",
                 sintetico: bool = False) -> list[tuple[str, Path]]:
    ordenes, carpeta = corpus_de(idioma, sintetico)
    if not carpeta.is_dir():
        return []
    pares = []
    for indice, orden in enumerate(ordenes, start=1):
        ruta = carpeta / f"{indice:02d}.wav"
        if ruta.is_file():
            pares.append((orden, ruta))
    return pares


def evaluar(nombre_modelo: str, pares: list[tuple[str, Path]],
            idioma: str = "es") -> list[Medida]:
    import soundfile as sf

    # El suelo se saca del microfono en vivo cuando se puede, pero un
    # banco sobre FICHEROS no puede depender de que haya hardware sano:
    # el 2026-08-20 la tanda entera murio porque el micro estaba
    # atascado, y las grabaciones estaban intactas en disco. Sin suelo,
    # el veto de energia no se aplica y `Transcripcion.verdicto_fiable`
    # lo dice; el WER, que es lo que decide ADR-0006, no lo usa.
    suelo = None
    try:
        suelo = calibrar_suelo(
            ConfigAudio.desde_config().microfono(), tomas=2, segundos=0.5
        )
    except Exception as exc:  # noqa: BLE001
        print(f"    (sin veto de energia: {type(exc).__name__})")
    # >>> EL IDIOMA Y EL ANCLA VAN JUNTOS O NO VAN <<<
    # Se pasan LOS DOS explicitos en vez de dejarlos salir de la config,
    # porque el banco corre con la config del usuario: medir el corpus
    # ingles con el ancla española es la combinacion que no significa
    # nada, y no da error -- da un WER peor sin decir por que.
    from voz.idioma import ANCLA

    stt = STT(modelo=nombre_modelo, idioma=idioma, ancla=ANCLA[idioma])
    medidas = []
    for orden, ruta in pares:
        audio, sr = sf.read(ruta, dtype="float32")
        if sr != SAMPLE_RATE_VOZ:
            raise STTError(f"{ruta.name} esta a {sr} Hz y se esperaba {SAMPLE_RATE_VOZ}")
        t = stt.transcribir(audio, suelo=suelo, idioma=idioma)
        medidas.append(
            Medida(
                orden=orden,
                transcrito=t.texto.strip(),
                wer=wer(orden, t.texto),
                latencia_s=t.latencia_s,
                duracion_audio_s=t.duracion_audio_s,
                sin_habla=t.sin_habla,
            )
        )
    return medidas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grabar", action="store_true", help="Dictar las 30 ordenes.")
    parser.add_argument("--segundos", type=float, default=4.0)
    parser.add_argument(
        "--decir",
        action="store_true",
        help="Que Jarvis lea cada orden en voz alta antes de grabarla.",
    )
    parser.add_argument("--modelos", nargs="*", default=None)
    parser.add_argument(
        "--desde", type=int, default=1, help="Primera orden a grabar (1-30)."
    )
    parser.add_argument("--hasta", type=int, default=None, help="Ultima orden.")
    parser.add_argument(
        "--idioma", choices=sorted(CORPUS), default="es",
        help="Que canal se mide. Cada uno tiene SU corpus y SU carpeta.",
    )
    parser.add_argument(
        "--sintetico", action="store_true",
        help="Medir la carpeta de audio FABRICADO. No es un banco: es "
             "una red de regresion, y la salida lo dice en grande.",
    )
    args = parser.parse_args()

    if args.grabar and args.sintetico:
        print("`--grabar` dicta con una voz humana y `--sintetico` mide")
        print("audio fabricado. Juntos no significan nada, asi que no se")
        print("elige uno por ti.")
        return 2

    try:
        _, carpeta = corpus_de(args.idioma, args.sintetico)
    except STTError as exc:
        print(exc)
        return 2

    if args.grabar:
        n = grabar(args.segundos, args.decir, args.desde, args.hasta,
                   args.idioma)
        print(f"{n} ordenes grabadas en {carpeta}")
        return 0

    pares = _grabaciones(args.idioma, args.sintetico)
    if not pares:
        print(f"No hay grabaciones en {carpeta}.")
        if args.sintetico:
            print("Se llena soltando los audios ahi y corriendo:")
            print("  -m eval.preparar_audio <carpeta-donde-los-dejaste>")
            return 1
        sufijo = "" if args.idioma == "es" else f" --idioma {args.idioma}"
        print(r"Primero: .venv\Scripts\python.exe -m eval.stt_bench --grabar"
              + sufijo)
        print("\nY conviene lanzarlo desde TU terminal (con `!` delante en")
        print("Claude Code), para ver que orden toca en cada momento.")
        return 1

    nombres = args.modelos or modelos_descargados()
    if not nombres:
        print("No hay ningun modelo Whisper descargado en modelos/whisper.")
        return 1

    if args.sintetico:
        print(AVISO_SINTETICO)
    print(f"{len(pares)} grabaciones en {args.idioma}, {len(nombres)} modelos.")
    print("Meta: latencia STT < 1.0 s.\n")

    resultados: dict[str, list[Medida]] = {}
    for nombre in nombres:
        inicio = time.perf_counter()
        try:
            resultados[nombre] = evaluar(nombre, pares, args.idioma)
            print(f"  medido {nombre} en {time.perf_counter() - inicio:.0f} s")
        except STTError as exc:
            print(f"  FALLO {nombre}: {exc}")

    if not resultados:
        return 1

    print("\nRESUMEN")
    cab = f"{'modelo':12s} {'WER':>7s} {'perfectas':>10s} {'lat med':>8s} {'lat p90':>8s} {'sin habla':>10s}"
    print(cab)
    print("-" * len(cab))
    for nombre, medidas in sorted(resultados.items(), key=lambda kv: _wer_medio(kv[1])):
        lat = sorted(m.latencia_s for m in medidas)
        print(
            f"{nombre:12s} {_wer_medio(medidas):6.1%} "
            f"{sum(m.perfecta for m in medidas):4d}/{len(medidas):<5d} "
            f"{statistics.median(lat):7.2f}s {lat[int(len(lat) * 0.9)]:7.2f}s "
            f"{sum(m.sin_habla for m in medidas):5d}/{len(medidas):<4d}"
        )

    print("\nLA MEDIANA NO BASTA: la meta se siente en el PEOR caso, no en")
    print("el tipico, asi que p90 esta ahi al lado a proposito.")
    print("\nDONDE FALLA CADA UNO (ordenes con WER > 0)")
    for nombre, medidas in resultados.items():
        malas = [m for m in medidas if not m.perfecta]
        print(f"\n  {nombre}: {len(malas)} de {len(medidas)}")
        for m in sorted(malas, key=lambda m: -m.wer)[:8]:
            print(f"    WER {m.wer:5.1%}  «{m.orden}»")
            print(f"                 -> {m.transcrito!r}")

    if args.sintetico:
        print(AVISO_SINTETICO)
    print("\nADR-0006 se cierra con la tabla de arriba, no con la impresion:")
    print("el modelo elegido va en voz.stt.modelo de config/jarvis.yaml.")
    return 0


def _wer_medio(medidas: list[Medida]) -> float:
    return statistics.mean(m.wer for m in medidas) if medidas else 1.0


if __name__ == "__main__":
    raise SystemExit(main())
