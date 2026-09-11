"""El canal de idioma del STT: dos canales, y el español intacto.

>>> QUE SE ROMPIO Y COMO (2026-09-08) <<<
`transcribir` llevaba `idioma: str = "es"` clavado por defecto y
`escuchar()` lo llamaba sin pasarle nada, asi que el canal ingles de
JC-0018 -- el que se elige con `voz.idioma` desde AJUSTES -- decodificaba
en español. `STT._idioma()`, que si lee la config, solo se usaba para
rellenar el campo de los dos caminos que NO transcriben, o sea que
`Transcripcion.idioma` decia "en" en los casos VACIOS y "es" en los que
traian texto: el unico sitio donde se podia notar mentia al reves.

>>> LO QUE ESTOS TESTS PROTEGEN, Y SON DOS COSAS DISTINTAS <<<
Que el canal ingles exista, y que el español NO SE HAYA MOVIDO. La
segunda es la que pidio el usuario con todas las letras -- que no se
rompa ningun canal que ya funcione -- y es la que un test de
la funcionalidad nueva no cubre: si manana alguien resuelve el idioma de
otra manera y el español pasa a llegar como `None`, faster-whisper lo
AUTODETECTA en vez de dar error, y en ordenes cortas se equivoca. Eso no
se veria en ningun rojo: se oiria semanas despues.

NO CARGAN EL MODELO. La resolucion es un `staticmethod` y el paso a
faster-whisper se comprueba con un doble que apunta lo que le piden, asi
que esto corre en milisegundos y sin `modelos/` en disco -- que es
ademas como llega un clon recien descargado.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml

from voz.stt import STT, UMBRAL_SIN_HABLA, Transcripcion


def _config(tmp_path: Path, **voz) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "jarvis.yaml").write_text(
        yaml.safe_dump({"voz": voz}), encoding="utf-8")
    return tmp_path


# --- 1. de donde sale el idioma ---------------------------------------


@pytest.mark.idioma_real  # prueba la RESOLUCION del idioma:
# necesita el `hablado` de verdad, no el que fija `conftest`.
def test_el_idioma_sale_de_voz_idioma(tmp_path):
    assert STT._idioma(_config(tmp_path / "en", idioma="en")) == "en"
    assert STT._idioma(_config(tmp_path / "es", idioma="es")) == "es"


def test_sin_ajuste_el_canal_es_el_español(tmp_path):
    """Ausente no es un hueco: es el idioma con el que se midio todo."""
    assert STT._idioma(_config(tmp_path, stt={"modelo": "small"})) == "es"


def test_una_config_ilegible_cae_al_español_en_vez_de_levantar(tmp_path):
    """>>> LA TERCERA SALIDA ESTABA ESCRITA Y NO EXISTIA <<<

    Habia DOS `except Exception` colgando del mismo `try`, y un handler
    no captura lo que lanza su hermano: si el primero reventaba leyendo
    la config, `_idioma` levantaba en vez de devolver "es". El comentario
    de al lado prometia el apaño y el codigo no lo hacia.
    """
    (tmp_path / "jarvis.yaml").write_text("voz: [sin cerrar\n", encoding="utf-8")

    assert STT._idioma(tmp_path) == "es"


def test_un_idioma_que_no_conocemos_no_se_reenvia_a_whisper(tmp_path):
    """Ni se traduce ni se adivina: se cae al canal medido."""
    assert STT._idioma(_config(tmp_path, idioma="fr")) == "es"


# --- 2. que el canal llegue de verdad a faster-whisper ----------------


class _ModeloQueApunta:
    """Un doble que no transcribe: solo guarda con que le llamaron.

    No hereda de nada de faster-whisper a proposito. Lo unico que esta
    en juego es QUE se le pide, y un doble que ademas devolviera texto
    invitaria a escribir aqui tests de calidad que no lo son.
    """

    def __init__(self) -> None:
        self.pedido: dict = {}

    def transcribe(self, audio, **kwargs):
        self.pedido = kwargs
        return iter(()), object()


def _stt_de_mentira(idioma: str, ancla: str = "") -> tuple[STT, _ModeloQueApunta]:
    stt = object.__new__(STT)
    stt.modelo = "small"
    stt.compute_type = "int8"
    stt.idioma = idioma
    stt.ancla = ancla
    stt.carga_s = 0.0
    doble = _ModeloQueApunta()
    stt._modelo = doble
    return stt, doble


def test_el_idioma_del_canal_llega_a_whisper():
    stt, doble = _stt_de_mentira("en")

    stt.transcribir(np.zeros(16000, dtype="float32"))

    assert doble.pedido["language"] == "en", (
        "el canal ingles decodificaria en español, que es el fallo que "
        "esto viene a arreglar")


def test_el_canal_español_no_se_movio():
    """>>> EL QUE PIDIO EL USUARIO, Y ES EL QUE MAS VALE <<<

    Lo de arriba es funcionalidad nueva; esto es que lo que ya andaba
    siga andando exactamente igual. La llamada a faster-whisper para
    español tiene que ser la MISMA de antes del cambio.
    """
    stt, doble = _stt_de_mentira("es")

    stt.transcribir(np.zeros(16000, dtype="float32"))

    assert doble.pedido["language"] == "es"


def test_transcribir_NUNCA_pide_autodeteccion():
    """`None` a faster-whisper significa "adivinalo", y eso esta descartado.

    Por medicion, y esta en la cabecera del modulo: la autodeteccion
    cuesta una pasada sobre la primera ventana y se equivoca en ordenes
    cortas, que es todo lo que se le dice a Jarvis. El riesgo es real
    porque el defecto del argumento paso de `"es"` a `None`: si alguien
    quita la linea que lo resuelve, esto NO daria error -- daria
    transcripciones peores de vez en cuando.
    """
    for idioma in ("es", "en"):
        stt, doble = _stt_de_mentira(idioma)
        stt.transcribir(np.zeros(16000, dtype="float32"))
        assert doble.pedido["language"] is not None


def test_un_idioma_explicito_manda_sobre_el_canal():
    """Es como los bancos piden un idioma que no es el configurado."""
    stt, doble = _stt_de_mentira("es")

    stt.transcribir(np.zeros(16000, dtype="float32"), idioma="en")

    assert doble.pedido["language"] == "en"


# --- 3. el canal no puede quedarse a medias ---------------------------


@pytest.mark.idioma_real  # prueba la RESOLUCION del idioma:
# necesita el `hablado` de verdad, no el que fija `conftest`.
def test_el_ancla_y_el_idioma_salen_DEL_MISMO_SITIO(tmp_path):
    """>>> LA COMBINACION QUE NO SIGNIFICA NADA <<<

    Ancla inglesa decodificando en español, o al reves. No da error: da
    una transcripcion peor sin decir por que. Los dos salen de
    `voz.idioma` y se resuelven en el mismo momento, al construir.
    """
    from voz.idioma import ANCLA

    config = _config(tmp_path, idioma="en", stt={"modelo": "small"})

    assert STT._idioma(config) == "en"
    assert STT._ancla_configurada(config) == ANCLA["en"]


def test_el_canal_es_UNA_decision_y_no_una_por_camino(tmp_path):
    """Los caminos que no transcriben decian el idioma configurado y los
    que si transcribian decian "es". Ahora los tres leen `self.idioma`,
    que es la unica resolucion que hay."""
    import inspect

    fuente = inspect.getsource(STT)

    assert "self._idioma()" not in fuente, (
        "alguien volvio a resolver el idioma por camino: eso es como "
        "divergieron el campo y la llamada")
    assert fuente.count("idioma=self.idioma") == 3


# --- 4. lo que el campo de la transcripcion cuenta --------------------


def test_la_transcripcion_dice_en_que_idioma_se_pidio():
    stt, _ = _stt_de_mentira("en")

    t = stt.transcribir(np.zeros(16000, dtype="float32"))

    assert isinstance(t, Transcripcion)
    assert t.idioma == "en"
    assert t.umbral_sin_habla == UMBRAL_SIN_HABLA
