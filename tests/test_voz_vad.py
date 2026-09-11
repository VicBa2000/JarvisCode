"""Tests for `voz/vad.py`, against the real recordings on disk.

NO DOUBLES, y aqui no hacia falta ni plantearselo: el banco de la Fase
5.2 dejo 30 grabaciones reales de ordenes y 12 de silencio de la misma
sala y el mismo microfono. Un VAD probado con senoides sinteticas
mediria lo que silero opina de una senoide.

POR QUE ESTOS FICHEROS SON EL BANCO CORRECTO Y NO UNO CUALQUIERA: el
silencio se grabo de la MISMA sala, con el MISMO microfono y a la MISMA
hora que el habla. Un silencio bajado de internet, o generado con
ceros, no contiene el ruido de fondo de este cuarto -- que es
exactamente la senal que un VAD tiene que aprender a ignorar. El caso
de ceros se prueba aparte, y como lo que es: un caso limite, no la
prueba principal.

LA PREGUNTA QUE ESTOS TESTS RESPONDEN, medida el 2026-08-21: el veto de
energia de `voz/stt.py` no puede funcionar sobre el clip entero -- habla
y silencio se tocan (min habla -29.9 dBFS, max silencio -30.0). El VAD
si separa, 30/30 y 12/12. Estos tests son lo que permite apoyar la
guarda de "nadie hablo" en el, y por eso el fichero es rapido a
proposito: la parte que necesita Whisper vive en `test_voz_vad_stt.py`,
separada para que ESTA se corra siempre (leccion del 2026-08-19: un
marcador `lento` no se paga en segundos, se paga en veces que no se
corre).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from tests.entorno import saltar_si_faltan_modelos_wake

from voz.vad import BLOQUE, SAMPLE_RATE_VOZ, VAD, Habla

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIR_HABLA = PROJECT_ROOT / "eval" / "audio_ordenes"
DIR_SILENCIO = PROJECT_ROOT / "eval" / "audio_silencio"


def _wavs(directorio: Path, patron: str) -> list[Path]:
    return sorted(directorio.glob(patron))


def _leer(ruta: Path) -> np.ndarray:
    audio, sr = sf.read(ruta, dtype="float32")
    assert sr == SAMPLE_RATE_VOZ, f"{ruta.name} esta a {sr} Hz"
    return np.asarray(audio, dtype="float32").reshape(-1)


ORDENES = _wavs(DIR_HABLA, "[0-9][0-9].wav")
SILENCIOS = _wavs(DIR_SILENCIO, "*.wav")

falta_banco = pytest.mark.skipif(
    not ORDENES or not SILENCIOS,
    reason="faltan las grabaciones de eval/audio_ordenes y eval/audio_silencio",
)


@pytest.fixture(scope="module")
def vad() -> VAD:
    # Sin los .onnx de openWakeWord esto no es un fallo: es un
    # entorno recien hecho. `silero_vad.onnx` llega en la misma
    # descarga que el wake word (por eso no entra `silero-vad` de
    # PyPI, que arrastraria torch).
    saltar_si_faltan_modelos_wake()
    return VAD()


# --- las dos direcciones, que no son intercambiables ---------------------
#
# Un falso "no hablaste" MOLESTA; un falso "hablaste" hace que Whisper
# transcriba silencio y se INVENTE una orden. Los dos tests existen, pero
# el segundo es el que protege de lo grave.


@falta_banco
def test_encuentra_habla_en_todas_las_ordenes_reales(vad: VAD) -> None:
    mudas = [r.name for r in ORDENES if not vad.recortar(_leer(r)).hay_habla]
    assert not mudas, f"el VAD no oyo habla en ordenes que SI la tienen: {mudas}"


@falta_banco
def test_no_encuentra_habla_en_el_silencio_de_la_sala(vad: VAD) -> None:
    habladores = [r.name for r in SILENCIOS if vad.recortar(_leer(r)).hay_habla]
    assert not habladores, (
        f"el VAD oyo habla en silencio real: {habladores}. "
        "Esto es lo que hace que Whisper alucine una orden."
    )


@falta_banco
def test_recorta_de_verdad_y_nunca_alarga(vad: VAD) -> None:
    """Trimming that does not trim is a no-op dressed as a feature."""
    for ruta in ORDENES:
        h = vad.recortar(_leer(ruta))
        assert 0.0 < h.duracion_s <= h.duracion_original_s, ruta.name
        assert 0.0 <= h.recorte < 1.0, ruta.name


# --- determinismo: el fallo que no se ve mirando una sola llamada --------


@falta_banco
def test_dos_llamadas_seguidas_dan_lo_mismo(vad: VAD) -> None:
    """The LSTM state must not survive between calls.

    `probabilidades` reinicia h y c en cada llamada. Si algun dia deja de
    hacerlo, el resultado de una orden dependera de la anterior y el
    sintoma sera "a veces falla", que es el mas caro de diagnosticar. Se
    prueba sobre el MISMO objeto VAD a proposito: uno nuevo por llamada
    ocultaria justo el bug que se busca.
    """
    audio = _leer(ORDENES[0])
    primera = vad.probabilidades(audio)
    segunda = vad.probabilidades(audio)
    assert np.array_equal(primera, segunda)


@falta_banco
def test_el_orden_de_las_llamadas_no_cambia_el_veredicto(vad: VAD) -> None:
    """Same buffers, different order, same answers."""
    rutas = ORDENES[:4] + SILENCIOS[:4]
    directo = [vad.recortar(_leer(r)).hay_habla for r in rutas]
    inverso = [vad.recortar(_leer(r)).hay_habla for r in reversed(rutas)]
    assert directo == list(reversed(inverso))


# --- casos limite --------------------------------------------------------


def test_silencio_digital_no_es_habla(vad: VAD) -> None:
    """All zeros: the case a virtual audio cable produces.

    `config/jarvis.yaml` ya avisa de que esta maquina tiene 16 cables
    virtuales de un enrutador de audio virtual y que grabar de uno NO da error, da silencio
    perfecto. Si eso pasara por habla, Whisper lo rellenaria.
    """
    h = vad.recortar(np.zeros(SAMPLE_RATE_VOZ * 2, dtype="float32"))
    assert not h.hay_habla
    assert h.duracion_s == 0.0


def test_audio_vacio_no_revienta(vad: VAD) -> None:
    h = vad.recortar(np.zeros(0, dtype="float32"))
    assert not h.hay_habla
    assert h.recorte == 0.0, "sin audio original no hay fraccion que recortar"


def test_audio_mas_corto_que_un_bloque(vad: VAD) -> None:
    """Shorter than 512 samples: no whole block, so nothing to score."""
    h = vad.recortar(np.zeros(BLOQUE - 1, dtype="float32"))
    assert not h.hay_habla


@falta_banco
def test_ruido_fuerte_no_es_habla(vad: VAD) -> None:
    """Loud noise must not pass as speech.

    Es la diferencia entre un VAD y el veto de energia que este modulo
    viene a sustituir: subir el volumen no convierte ruido en voz. El
    ruido se genera y no se graba porque lo que se prueba aqui es una
    propiedad del MODELO, no de esta sala.
    """
    rng = np.random.default_rng(0)
    ruido = rng.normal(0, 0.1, SAMPLE_RATE_VOZ * 2).astype("float32")
    assert not vad.recortar(ruido).hay_habla


# --- la aritmetica de Habla, que no es un doble de nada ------------------


def test_recorte_es_la_fraccion_eliminada() -> None:
    h = Habla(
        audio=np.zeros(SAMPLE_RATE_VOZ, dtype="float32"),
        segmentos=((0, SAMPLE_RATE_VOZ),),
        duracion_original_s=4.0,
    )
    assert h.duracion_s == pytest.approx(1.0)
    assert h.recorte == pytest.approx(0.75)
