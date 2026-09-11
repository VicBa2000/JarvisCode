"""¿El VAD recorta SIN COMERSE PALABRAS? Necesita Whisper: va `lento`.

VIVE APARTE DE `test_voz_vad.py` A PROPOSITO. Aquel corre en 5 s y sin
modelos, y si compartieran fichero heredaria el marcador de modulo y
dejaria de correrse a diario. Es la leccion del 2026-08-19: un marcador
`lento` no se paga en segundos, se paga en veces que no se corre.

LA PRUEBA CORRECTA NO ES "¿RECORTA?" -- eso ya lo mide el fichero rapido
y ademas un VAD agresivo lo aprobaria luciendo bien. Es "¿recorta sin
perder lo dicho?". Un VAD que se coma la ultima palabra de cada orden
baja la latencia, sale precioso en una tabla, y rompe justo la palabra
que suele elegir la herramienta.

QUE NO SE AFIRMA AQUI, Y POR QUE. El registro decia el 2026-08-20
"transcripcion IDENTICA 6/6". Medido el 21 sobre las 30: **16/30
identicas**. Las otras 14 difieren en puntuacion y mayusculas, que
`wer()` normaliza -- o sea que la frase es la misma y la cadena no. La
afirmacion vieja era cierta para aquellas 6 y no generaliza; con 30 hay
que medir la propiedad que importa (que no se pierda contenido) y no la
que se veia en una muestra pequeña (que no cambie ni un caracter).

EL CASO QUE OBLIGA A TOLERANCIA, y conviene tenerlo delante:
    17  crudo      'Ejecuta PIP List en la carpeta del proyecto.'   WER  0%
        recortado  'de ejecuta pip list en la carpeta del proyecto.' WER 12%
El recorte metio un 'de' que nadie dijo: el relleno de 150 ms no llego a
cubrir el arranque y Whisper relleno el hueco. Es la MISMA tendencia a
inventar que motiva todo el modulo, ahora provocada por el recorte. Por
eso el test mide el AGREGADO y no orden por orden: exigir 0 regresiones
individuales seria fijar en piedra que este caso concreto nunca mejore.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

pytestmark = pytest.mark.lento

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIR_HABLA = PROJECT_ROOT / "eval" / "audio_ordenes"

ORDENES_WAV = sorted(DIR_HABLA.glob("[0-9][0-9].wav"))

falta_banco = pytest.mark.skipif(
    not ORDENES_WAV, reason="faltan las grabaciones de eval/audio_ordenes"
)

# Margen sobre el WER agregado. No es un numero elegido para que pase:
# medido el 2026-08-21 con `small`, crudo y recortado dan 4.2 % los dos
# (una orden mejora 22->11 %, otra empeora 0->12 %, el resto no se mueve).
# Dos puntos de holgura cubren que Whisper no es determinista entre
# versiones sin dejar pasar una perdida de palabras, que costaria mucho mas.
TOLERANCIA_WER = 0.02


@falta_banco
def test_recortar_no_empeora_lo_que_se_entiende() -> None:
    from eval.stt_bench import ORDENES, wer
    from voz.stt import STT
    from voz.vad import VAD

    vad = VAD()
    stt = STT(modelo="small")

    crudos, recortados, mudas = [], [], []
    for ruta in ORDENES_WAV:
        audio, _ = sf.read(ruta, dtype="float32")
        audio = np.asarray(audio, dtype="float32").reshape(-1)
        referencia = ORDENES[int(ruta.stem) - 1]

        habla = vad.recortar(audio)
        if not habla.hay_habla:
            mudas.append(ruta.name)
            continue

        crudos.append(wer(referencia, stt.transcribir(audio).texto))
        recortados.append(wer(referencia, stt.transcribir(habla.audio).texto))

    assert not mudas, f"el VAD dejo mudas ordenes que tienen habla: {mudas}"

    medio_crudo = sum(crudos) / len(crudos)
    medio_recortado = sum(recortados) / len(recortados)
    assert medio_recortado <= medio_crudo + TOLERANCIA_WER, (
        f"recortar empeoro lo entendido: {medio_crudo:.1%} -> "
        f"{medio_recortado:.1%}. Sospechar del relleno de `voz/vad.py` "
        f"(RELLENO_MS) antes que de Whisper: un recorte que muerde el "
        f"arranque hace que el modelo invente una palabra para llenarlo."
    )
