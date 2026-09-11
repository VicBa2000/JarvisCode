"""El ancla de vocabulario, y la guarda que casi rompe.

Lo medido el 2026-08-21 sobre el corpus real de esta sala (30 ordenes,
12 silencios), `small`, todo en la misma tanda:

    brazo       WER     perfectas   mejoran  empeoran
    control     4.2%      24/30        -         -
    hotwords    2.4%      27/30        3         0

Las 3 que arregla son las 3 de 'bloc' -> 'blog', que era la UNICA falla
real del banco (las otras 3 del control son artefactos del WER: el modelo
normalizo bien 'dos mil veintiseis' -> '2026' y la metrica se lo cobro).

Y lo que casi se cuela por debajo:

                HABLA (30)         SILENCIO (12)
    sin ancla   max 0.219    <     min 0.686
    con ancla   max 0.031    <     min 0.490

Anclar NO rompe la separacion, pero corre la frontera entera hacia abajo.
Con el umbral viejo de 0.6 puesto, CUATRO de los doce silencios pasarian
como ordenes reales -- y con `initial_prompt` el texto inventado eran
palabras del propio vocabulario ('Escritorio,', 'Imagenes,'), que parecen
una orden de verdad. De ahi los dos umbrales y de ahi `hotwords`.

Los que tocan los 12 wav van marcados `lento`: cargan Whisper y tardan.
Los de logica, no.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from voz.stt import (
    ANCLA_POR_DEFECTO,
    UMBRAL_SIN_HABLA,
    UMBRAL_SIN_HABLA_CON_ANCLA,
    STT,
    Transcripcion,
)

DIR_SILENCIO = Path(__file__).resolve().parent.parent / "eval" / "audio_silencio"
DIR_ORDENES = Path(__file__).resolve().parent.parent / "eval" / "audio_ordenes"


def transcripcion(prob: float, umbral: float) -> Transcripcion:
    return Transcripcion(
        texto="abre el bloc de notas", latencia_s=1.0, duracion_audio_s=3.0,
        prob_sin_habla=prob, idioma="es", modelo="small",
        umbral_sin_habla=umbral,
    )


# --- la logica del umbral, sin cargar nada --------------------------------


def test_el_umbral_viaja_con_la_transcripcion_no_es_global():
    """La leccion del 2026-08-04, aplicada a otra opcion.

    Nada que dependa de COMO se hizo la llamada puede fijarse fuera de
    ella. El umbral depende de si se anclo vocabulario, asi que es un
    campo de la transcripcion y no una constante que alguien lee suelta.
    """
    assert UMBRAL_SIN_HABLA_CON_ANCLA < UMBRAL_SIN_HABLA
    # Una p que es habla con ancla y seria silencio sin ella.
    assert transcripcion(0.4, UMBRAL_SIN_HABLA).sin_habla is False
    assert transcripcion(0.4, UMBRAL_SIN_HABLA_CON_ANCLA).sin_habla is True


def test_el_umbral_nuevo_deja_margen_a_los_dos_lados_de_lo_medido():
    """Puesto con margen, no pegado al dato: 12 silencios son pocos."""
    habla_max_medido, silencio_min_medido = 0.031, 0.490
    assert habla_max_medido < UMBRAL_SIN_HABLA_CON_ANCLA < silencio_min_medido
    # Y el viejo sigue valiendo para su propia medicion.
    assert 0.219 < UMBRAL_SIN_HABLA < 0.686


def test_el_ancla_no_contiene_las_frases_del_banco():
    """Una sonda que se da las respuestas mide la sonda.

    El ancla lleva vocabulario del dominio, no las ordenes grabadas. Si
    alguien mete aqui una frase del banco, el 27/30 deja de significar
    nada.
    """
    ancla = ANCLA_POR_DEFECTO.lower()
    for frase in ("abre el bloc de notas", "escribe hola mundo",
                  "organiza mi carpeta", "haz una captura de pantalla"):
        assert frase not in ancla


def test_apagar_el_ancla_a_proposito_no_es_lo_mismo_que_no_decir_nada(
    tmp_path: Path,
):
    """Tres estados otra vez: puesta / quitada / no configurada."""
    (tmp_path / "jarvis.yaml").write_text(
        "voz:\n  stt:\n    modelo: small\n    ancla_vocabulario: false\n",
        encoding="utf-8",
    )
    assert STT._ancla_configurada(config_dir=tmp_path) == ""
    (tmp_path / "jarvis.yaml").write_text(
        "voz:\n  stt:\n    modelo: small\n", encoding="utf-8")
    assert STT._ancla_configurada(config_dir=tmp_path) == ANCLA_POR_DEFECTO


def test_una_lista_en_el_yaml_tambien_vale(tmp_path: Path):
    (tmp_path / "jarvis.yaml").write_text(
        "voz:\n  stt:\n    ancla_vocabulario:\n      - bloc de notas\n"
        "      - Descargas\n",
        encoding="utf-8",
    )
    assert STT._ancla_configurada(config_dir=tmp_path) == "bloc de notas, Descargas"


# --- contra el audio real -------------------------------------------------


@pytest.mark.lento
def test_con_el_ancla_puesta_los_doce_silencios_siguen_descartandose():
    """LA REGRESION QUE IMPORTA.

    Es el agujero que abrio el ancla y que el umbral nuevo cierra. Si
    esto falla, Whisper le esta mandando ordenes inventadas a un agente
    que ACTUA, que es la peor forma de fallar que tiene este proyecto.
    """
    clips = sorted(DIR_SILENCIO.glob("*.wav"))
    assert len(clips) >= 12, "falta el corpus de silencio de la sala"
    stt = STT()
    assert stt.ancla, "este test no dice nada sin el ancla puesta"

    colados = []
    for clip in clips:
        audio, _ = sf.read(clip, dtype="float32")
        t = stt.transcribir(np.asarray(audio, dtype="float32").reshape(-1))
        if not t.sin_habla:
            colados.append((clip.name, t.texto.strip(), t.prob_sin_habla))
    assert not colados, f"pasaron como habla: {colados}"


@pytest.mark.lento
def test_con_el_ancla_puesta_las_tres_de_bloc_se_oyen_bien():
    """El otro lado: que la guarda no se haya comido lo que arreglaba."""
    stt = STT()
    for nombre in ("03", "09", "23"):
        audio, _ = sf.read(DIR_ORDENES / f"{nombre}.wav", dtype="float32")
        t = stt.transcribir(np.asarray(audio, dtype="float32").reshape(-1))
        assert not t.sin_habla, f"{nombre}.wav se descarto siendo habla"
        assert "bloc" in t.texto.lower(), f"{nombre}.wav -> {t.texto!r}"
        assert "blog" not in t.texto.lower()
