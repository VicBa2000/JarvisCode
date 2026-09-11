"""Tests for `voz/stt.py` and the WER of `eval/stt_bench.py`.

The silence test runs the real model over the real microphone, because
the thing being asserted -- that Whisper invents sentences out of room
tone -- cannot be produced by a double without deciding in advance what
it invents, which is the trap of 2026-08-11.

Not marked `lento`: no GPU and no Ollama.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.entorno import necesita_whisper
import yaml

from eval.stt_bench import normalizar, wer
from voz.stt import UMBRAL_SIN_HABLA, STT, STTError, Transcripcion, modelos_descargados

MODELO_DE_PRUEBA = "small"


def _transcripcion(**kwargs) -> Transcripcion:
    base = dict(
        texto="organiza mi carpeta de descargas",
        latencia_s=0.5,
        duracion_audio_s=3.0,
        prob_sin_habla=0.05,
        idioma="es",
        modelo="small",
    )
    base.update(kwargs)
    return Transcripcion(**base)


# --- las tres respuestas, que es lo que este modulo existe para tener ----


def test_sin_habla_no_es_lo_mismo_que_texto_vacio():
    """Whisper alucinando devuelve español impecable, no una cadena vacia.

    Una comprobacion de `if not texto` no saltaria NUNCA con
    'Subtitulos realizados por la comunidad de Amara.org', y esa frase
    llegaria al planner como una ORDEN del usuario.
    """
    alucinacion = _transcripcion(
        texto="Subtitulos realizados por la comunidad de Amara.org",
        prob_sin_habla=0.78,
    )

    assert alucinacion.texto  # hay texto...
    assert alucinacion.sin_habla is True  # ...y aun asi no se dijo nada


def test_no_comprobar_el_vad_es_un_TERCER_estado_no_un_si():
    """El fallo por defecto: colapsar "no lo se" contra "si"."""
    sin_comprobar = _transcripcion(hay_habla_vad=None)
    comprobado = _transcripcion(hay_habla_vad=True)

    assert sin_comprobar.verdicto_fiable is False
    assert comprobado.verdicto_fiable is True
    # No comprobarlo no puede convertirse en "habia habla".
    assert "sin VAD" in _transcripcion(
        hay_habla_vad=None, prob_sin_habla=0.9
    ).describe()


def test_sin_habla_falla_CERRADO():
    """Cualquier señal que diga silencio basta para descartar.

    Un falso "no dijiste nada" hace que Jarvis te ignore, que es molesto.
    Un falso "el usuario dijo esto" hace que Jarvis ACTUE sobre una orden
    que nadie dio. Solo una de las dos es segura.
    """
    # El modelo cree que hubo habla (p baja) pero el VAD dice que no.
    solo_vad = _transcripcion(prob_sin_habla=0.35, hay_habla_vad=False)
    assert solo_vad.sin_habla is True

    # Y al reves: el VAD oyo habla, pero el modelo lo niega.
    solo_modelo = _transcripcion(prob_sin_habla=0.9, hay_habla_vad=True)
    assert solo_modelo.sin_habla is True

    # Solo pasa cuando las dos señales dicen que si.
    ambas = _transcripcion(prob_sin_habla=0.05, hay_habla_vad=True)
    assert ambas.sin_habla is False


def test_silencio_digital_se_descarta_aunque_todo_lo_demas_diga_que_si():
    """`sin_senal` no dice "nadie hablo" sino "esto no es un microfono".

    Es la unica parte del antiguo veto de energia que SI era fiable, y se
    conserva por eso: es un umbral ABSOLUTO (rms practicamente cero), no
    una comparacion contra un suelo que se mueve. Esta maquina tiene 16
    cables de audio virtuales y grabar de uno no da error, da
    silencio digital perfecto: sin esto, Whisper lo rellenaria con una
    orden inventada y las otras dos señales podrian no enterarse.
    """
    cable_virtual = _transcripcion(
        texto="Subtitulos realizados por la comunidad de Amara.org",
        prob_sin_habla=0.05,
        hay_habla_vad=True,
        sin_senal=True,
    )
    assert cable_virtual.sin_habla is True
    assert "sin_senal" in cable_virtual.describe()


def test_el_umbral_del_modelo_no_habria_cazado_lo_medido():
    """Documenta POR QUE hace falta una SEGUNDA señal, con el numero.

    Medido el 2026-08-20 sobre silencio real: alucinaciones con
    `no_speech_prob` de 0.351, o sea por debajo del umbral. Si algun dia
    alguien sube el umbral pensando que la señal del modelo basta, esto
    se lo recuerda.

    LA SEGUNDA SEÑAL CAMBIO EL 2026-08-21, y el motivo esta medido. Era
    el veto de energia, que comparaba el RMS del clip entero contra el
    suelo; sobre 30 ordenes reales y 12 silencios reales resulto que
    habla y silencio se TOCAN (-29.9 dBFS contra -30.0), asi que no hay
    margen que los separe, y ademas el suelo oscila 13 dB entre
    calibraciones seguidas. El VAD, sobre los mismos 42 clips, acierta
    30/30 y 12/12.
    """
    escape_real = _transcripcion(texto="¡Suscribete!", prob_sin_habla=0.351)

    assert escape_real.prob_sin_habla < UMBRAL_SIN_HABLA
    assert escape_real.sin_habla is False, "el modelo solo NO lo caza"
    con_vad = _transcripcion(
        texto="¡Suscribete!", prob_sin_habla=0.351, hay_habla_vad=False
    )
    assert con_vad.sin_habla is True, "el VAD si"


def test_la_energia_ya_no_vota():
    """El campo se conserva como diagnostico, pero no decide.

    Sin este test, alguien que lea `supera_suelo` en el dataclass puede
    asumir razonablemente que sigue gateando el veredicto y construir
    encima. Medido el 2026-08-21: dejarlo votar rechazaba las 30 ordenes
    del banco cuando la calibracion salia alta, o sea que fallaba cerrado
    de forma INTERMITENTE.
    """
    solo_energia = _transcripcion(
        prob_sin_habla=0.05, hay_habla_vad=True, supera_suelo=False
    )
    assert solo_energia.sin_habla is False


def test_la_meta_del_555_del_stt_es_un_segundo():
    assert _transcripcion(latencia_s=0.8).cumple_meta is True
    assert _transcripcion(latencia_s=1.4).cumple_meta is False


# --- configuracion --------------------------------------------------------


def test_sin_modelo_configurado_no_se_elige_uno_solo(tmp_path):
    (tmp_path / "jarvis.yaml").write_text(
        yaml.safe_dump({"voz": {"stt": {"modelo": None}}}), encoding="utf-8"
    )

    with pytest.raises(STTError) as excinfo:
        STT(config_dir=tmp_path)

    assert "ADR-0006" in str(excinfo.value)


@necesita_whisper
def test_el_modelo_configurado_esta_descargado():
    import yaml as _yaml

    from nucleo.configuracion import CONFIG_DIR

    datos = _yaml.safe_load((CONFIG_DIR / "jarvis.yaml").read_text(encoding="utf-8"))
    configurado = datos["voz"]["stt"]["modelo"]

    assert configurado in modelos_descargados(), (
        f"voz.stt.modelo es '{configurado}' y no esta en modelos/whisper: "
        f"{modelos_descargados()}"
    )


# --- WER ------------------------------------------------------------------


def test_wer_cuenta_palabras_no_caracteres():
    assert wer("abre el bloc de notas", "abre el bloc de notas") == 0.0
    assert wer("abre el bloc de notas", "abre el blog de notas") == pytest.approx(0.2)
    assert wer("abre el bloc de notas", "") == 1.0


def test_wer_ignora_tildes_y_puntuacion():
    """Un WER que cuenta 'cuantos' contra 'cuántos' mide la puntuacion
    del transcriptor, no si la orden se entendio."""
    assert wer("cuantos archivos hay", "¿Cuántos archivos hay?") == 0.0
    assert normalizar("¡Cancela!") == ["cancela"]


def test_wer_penaliza_inserciones_y_borrados():
    assert wer("abre el bloc", "abre el bloc de notas") == pytest.approx(2 / 3)
    assert wer("abre el bloc de notas", "abre el bloc") == pytest.approx(0.4)


# --- contra el modelo real ------------------------------------------------


@necesita_whisper
def test_whisper_no_devuelve_orden_alguna_ante_silencio_digital():
    """El caso mas facil y el que no puede fallar: ceros exactos.

    Con el microfono equivocado (un cable de audio virtual) esto es lo que
    llega, y lo que NO puede pasar es que salga una orden de ahi.
    """
    stt = STT(modelo=MODELO_DE_PRUEBA)
    t = stt.transcribir(np.zeros(2 * 16000, dtype="float32"))

    assert t.sin_habla is True, t.describe()
