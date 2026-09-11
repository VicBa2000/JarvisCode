"""Tests for `voz/perfil.py`, the voice personas.

Real config files on disk (tmp_path) and the project's real one. Nothing
here needs a double: a YAML file is exactly the thing being tested.
"""

from __future__ import annotations

import pytest

from tests.entorno import necesita_todas_las_voces
from tests.entorno import necesita_voces
import yaml

from nucleo.configuracion import CONFIG_DIR
from voz.perfil import (
    WAKE_WORDS_SIN_ENTRENAR,
    Perfil,
    PerfilError,
    perfil_activo,
    perfiles_declarados,
)


def _escribe(tmp_path, datos: dict) -> None:
    (tmp_path / "jarvis.yaml").write_text(yaml.safe_dump(datos), encoding="utf-8")


PERFIL_COMPLETO = {
    "nombre": "Jarvis",
    "tts_voz": "es_ES-davefx-medium",
    "wake_words": ["hey_jarvis"],
}


# --- las tres cosas van juntas o no van ----------------------------------


def test_un_perfil_a_medias_es_un_error(tmp_path):
    """Cambiar la voz y olvidar el nombre deja al sistema descosido.

    Es la razon de que exista el perfil: tres ajustes sueltos se cambian
    de uno en uno, y el que se olvida es siempre el que nadie mira.
    """
    _escribe(tmp_path, {"voz": {"perfil": "ella", "perfiles": {"ella": {
        "tts_voz": "es_MX-claude-high"}}}})

    with pytest.raises(PerfilError) as excinfo:
        perfiles_declarados(config_dir=tmp_path)

    mensaje = str(excinfo.value)
    assert "nombre" in mensaje and "wake_words" in mensaje


def test_sin_perfil_activo_no_se_escoge_el_primero(tmp_path):
    """Misma forma que en audio y en tts: nada de elegir por su cuenta."""
    _escribe(tmp_path, {"voz": {"perfiles": {"jarvis": PERFIL_COMPLETO}}})

    with pytest.raises(PerfilError) as excinfo:
        perfil_activo(config_dir=tmp_path)

    assert "voz.perfil" in str(excinfo.value)
    assert "jarvis" in str(excinfo.value)


def test_un_perfil_activo_inexistente_dice_cuales_hay(tmp_path):
    _escribe(
        tmp_path,
        {"voz": {"perfil": "nadie", "perfiles": {"jarvis": PERFIL_COMPLETO}}},
    )

    with pytest.raises(PerfilError) as excinfo:
        perfil_activo(config_dir=tmp_path)

    assert "nadie" in str(excinfo.value)
    assert "jarvis" in str(excinfo.value)


def test_el_toggle_cambia_las_tres_cosas_de_una_vez(tmp_path):
    """Lo que compra el perfil: un solo cambio, no tres."""
    perfiles = {
        "jarvis": PERFIL_COMPLETO,
        "ella": {
            "nombre": "Viernes",
            "tts_voz": "es_MX-claude-high",
            "wake_words": ["hey_mycroft"],
        },
    }
    _escribe(tmp_path, {"voz": {"perfil": "jarvis", "perfiles": perfiles}})
    uno = perfil_activo(config_dir=tmp_path)

    _escribe(tmp_path, {"voz": {"perfil": "ella", "perfiles": perfiles}})
    otro = perfil_activo(config_dir=tmp_path)

    assert (uno.nombre, uno.tts_voz, uno.wake_words) != (
        otro.nombre,
        otro.tts_voz,
        otro.wake_words,
    )
    assert otro.nombre == "Viernes"


# --- el limite que ADR-0002 impone y que no se puede olvidar -------------


def test_una_frase_de_activacion_inventada_queda_MARCADA_no_prohibida():
    """ADR-0002 eligio 'hey_jarvis' porque es CERO entrenamiento.

    openWakeWord solo trae cuatro frases preentrenadas. Otra cualquiera
    es una decision legitima con un coste (entrenar un modelo), y el
    coste tiene que verse AQUI y no descubrirse en la Fase 5.4.
    """
    inventada = Perfil(
        clave="ella", nombre="Viernes", tts_voz="x", wake_words=("hey_viernes",)
    )
    preentrenada = Perfil(
        clave="jarvis", nombre="Jarvis", tts_voz="x", wake_words=("hey_jarvis",)
    )

    assert inventada.wake_words_a_entrenar == ("hey_viernes",)
    assert "ENTRENAR" in inventada.describe()
    assert preentrenada.wake_words_a_entrenar == ()
    assert "ENTRENAR" not in preentrenada.describe()


def test_las_frases_sin_entrenar_son_las_que_openwakeword_trae_de_verdad():
    """Contra la libreria real, no contra una lista copiada a mano.

    Una constante copiada envejece en silencio: si openWakeWord añade o
    quita un modelo preentrenado, esto se entera.
    """
    import openwakeword

    disponibles = set(openwakeword.MODELS)
    for frase in WAKE_WORDS_SIN_ENTRENAR:
        assert frase in disponibles, (
            f"'{frase}' ya no esta entre los modelos preentrenados de "
            f"openWakeWord: {sorted(disponibles)}"
        )


def test_un_perfil_puede_declarar_frases_por_entrenar_sin_perder_las_que_valen():
    """El caso de 'hey_epsilon' (pedido el 2026-08-20, por Pluto).

    Una persona puede responder a varias frases porque openWakeWord
    carga varios modelos a la vez. Que una este por entrenar no invalida
    las otras: se marca la que falta y se sigue pudiendo despertar.
    """
    mixto = Perfil(
        clave="jarvis",
        nombre="Jarvis",
        tts_voz="x",
        wake_words=("hey_jarvis", "hey_epsilon"),
    )

    assert mixto.wake_words_listas == ("hey_jarvis",)
    assert mixto.wake_words_a_entrenar == ("hey_epsilon",)
    assert mixto.puede_despertarse_hoy is True
    assert "hey_epsilon" in mixto.describe()


def test_un_perfil_activo_que_no_puede_despertarse_es_un_error(tmp_path):
    """Declararlo vale; activarlo no.

    Un perfil con todas las frases por entrenar es un PLAN legitimo. Lo
    que no puede es estar activo: Jarvis se quedaria escuchando sin poder
    despertarse jamas, y eso NO daria ningun error en marcha — el proceso
    arranca, el micro abre, y no pasa nada nunca. Falla abierto.
    """
    _escribe(
        tmp_path,
        {
            "voz": {
                "perfil": "futura",
                "perfiles": {
                    "futura": {
                        "nombre": "Epsilon",
                        "tts_voz": "es_ES-davefx-medium",
                        "wake_words": ["hey_epsilon"],
                    }
                },
            }
        },
    )

    with pytest.raises(PerfilError) as excinfo:
        perfil_activo(config_dir=tmp_path)

    assert "hey_epsilon" in str(excinfo.value)
    assert "hey_jarvis" in str(excinfo.value)


def test_una_frase_suelta_no_se_lee_como_una_lista_de_letras(tmp_path):
    """Tolerar el adorno al ENTRAR, que es la estrategia aprobada.

    Sin esto, `wake_words: hey_jarvis` (una cadena, no una lista) se
    iteraria caracter a caracter y produciria diez frases de una letra,
    ninguna de las cuales existe. El YAML seria valido y el fallo
    aparecerio en la 5.4.
    """
    _escribe(
        tmp_path,
        {
            "voz": {
                "perfil": "jarvis",
                "perfiles": {
                    "jarvis": {
                        "nombre": "Jarvis",
                        "tts_voz": "es_ES-davefx-medium",
                        "wake_words": "hey_jarvis",
                    }
                },
            }
        },
    )

    assert perfil_activo(config_dir=tmp_path).wake_words == ("hey_jarvis",)


# --- el config real del proyecto -----------------------------------------


@pytest.mark.idioma_real  # prueba la RESOLUCION del idioma:
# necesita el `hablado` de verdad, no el que fija `conftest`.
def test_el_perfil_activo_del_proyecto_es_coherente():
    activo = perfil_activo()

    assert activo.nombre
    assert activo.tts_voz
    # El perfil que se usa a diario no puede exigir entrenar nada: eso
    # dejaria a Jarvis sin forma de despertarse (ADR-0002).
    assert activo.puede_despertarse_hoy, activo.describe()


@necesita_voces
@necesita_todas_las_voces
def test_la_voz_de_TODOS_los_perfiles_declarados_esta_descargada():
    """No solo la del activo: un toggle tiene que poder accionarse.

    Comprobar unicamente el perfil activo dejaria pasar un segundo perfil
    con una voz que no esta en disco, y el fallo aparecerio justo al
    cambiar de persona — que es el unico momento en que nadie lo espera.
    """
    from voz.tts import voces_disponibles

    disponibles = voces_disponibles()
    for clave, perfil in perfiles_declarados().items():
        assert perfil.tts_voz in disponibles, (
            f"el perfil '{clave}' usa {perfil.tts_voz}, que no esta descargada"
        )


def test_el_config_del_proyecto_declara_perfiles():
    datos = yaml.safe_load((CONFIG_DIR / "jarvis.yaml").read_text(encoding="utf-8"))

    assert datos["voz"]["perfil"]
    assert datos["voz"]["perfiles"]
