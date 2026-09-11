"""El oido suelta el microfono en cuanto otro lo necesita.

DE DONDE SALE. 2026-08-26, usandolo: el usuario contestaba una puerta por
DE DONDE SALE. 2026-08-26, usandolo: el usuario contestaba una puerta por
voz y no se le oia. Conto que un "si" tuvo que decirlo dos veces para que
entrara, y que del "no" no supo si no le entendio o si lo dijo demasiado
pronto. Lo dijo pronto, y no era culpa suya: entre que Jarvis callaba y el
microfono se
abria pasaban hasta ~4,7 s -- la vuelta en vuelo del hilo del oido (3,0 s
de grabacion) mas lo que tardaba Whisper en transcribirla (1,7-1,9 s,
medido). Lo que dijera ahi no existia.

>>> Y NO ERA INTERMITENTE: ERA SEGURO PARA UNA PUERTA <<<
El oido graba MIENTRAS Jarvis habla, asi que justo detras de una peticion
de permiso su ventana viene llena de la voz del propio Jarvis. Con la
sala callada el VAD la despacha en 0,02 s y el hueco no se nota; detras
de una puerta siempre hay habla dentro y siempre se pagan los dos
segundos de Whisper.

LO QUE SE PROTEGE AQUI son las dos mitades del arreglo:
  1. que la vuelta se pueda soltar a medias, y
  2. que lo que se llevara grabado NO se enrute -- nadie ha mirado si
     habia habla ahi dentro, asi que tratarlo como "no dijo nada" seria
     inventarse la respuesta.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from tests.entorno import necesita_modelos_wake
from voz.audio import SAMPLE_RATE_VOZ, Dispositivo
from voz.stt import STT, Transcripcion
from voz.vad import Cierre

MICRO = Dispositivo(
    indice=0, nombre="postizo", host_api="WASAPI", canales=1,
    sample_rate_nativo=SAMPLE_RATE_VOZ,
)


class _StreamPostizo:
    def __init__(self, trozos, callback, al_entregar) -> None:
        self._trozos = trozos
        self._cb = callback
        self._al_entregar = al_entregar

    def __enter__(self):
        for n, trozo in enumerate(self._trozos, start=1):
            self._cb(trozo, len(trozo), None, None)
            if self._al_entregar is not None:
                self._al_entregar(n)
        return self

    def __exit__(self, *_):
        return False


class _SdPostizo:
    """Un PortAudio que entrega N trozos y avisa de cada uno."""

    def __init__(self, trozos, al_entregar=None) -> None:
        self._trozos = trozos
        self._al_entregar = al_entregar

    def InputStream(self, *, callback, **_):  # noqa: N802 - es la API de sd
        return _StreamPostizo(self._trozos, callback, self._al_entregar)


class STTPostizo:
    """El `escuchar` DE VERDAD sobre un modelo que no existe.

    Se toman los metodos reales de `STT` y se deja fuera lo unico que
    costaria gigabytes: cargar Whisper. Asi lo que se prueba es el codigo
    que corre en produccion y no una reimplementacion suya.
    """

    modelo = "postizo"
    _vad_cache = None
    # >>> ERA UN METODO `_idioma()` HASTA EL 2026-09-08 <<<
    # Ese dia el idioma paso a resolverse UNA vez al construir el `STT`
    # -- pegado al ancla, porque los dos salen de `voz.idioma` -- y los
    # caminos que no transcriben leen `self.idioma`. El doble lo cazo en
    # el acto con un `AttributeError`, que es exactamente para lo que
    # esta escrito asi: toma los metodos REALES de `STT`, de modo que
    # cuando produccion cambia de forma, esto se entera.
    idioma = "es"

    def __init__(self) -> None:
        self.transcripciones = 0

    def transcribir(self, audio, **_) -> Transcripcion:
        self.transcripciones += 1
        return Transcripcion(
            texto="lo que sea", latencia_s=0.1,
            duracion_audio_s=len(np.asarray(audio).reshape(-1)) / SAMPLE_RATE_VOZ,
            prob_sin_habla=0.01, idioma="es", modelo=self.modelo,
            hay_habla_vad=True,
        )

    escuchar = STT.escuchar
    _ventana_abortada = STT._ventana_abortada
    _el_vad = STT._el_vad


def _trozo() -> np.ndarray:
    return np.zeros((1024, 1), dtype="float32")


def test_si_ya_le_han_pedido_soltar_ni_abre_el_microfono(monkeypatch) -> None:
    """La bandera puesta antes de empezar no cuesta ni una grabacion."""
    from voz import audio as mod

    abrio = []

    class _SdQueSeQueja:
        def InputStream(self, **_):  # noqa: N802
            abrio.append(1)
            raise AssertionError("no debia abrir el microfono")

    monkeypatch.setattr(mod, "_sd", lambda: _SdQueSeQueja())
    aviso = threading.Event()
    aviso.set()

    stt = STTPostizo()
    t = stt.escuchar(segundos=3.0, dispositivo=MICRO, cancelar=aviso)

    assert not abrio
    assert t.cierre == Cierre.ABORTADO.value
    assert stt.transcripciones == 0


def test_la_vuelta_se_suelta_a_media_grabacion(monkeypatch) -> None:
    """Y se suelta CUANDO se pide, no al terminar la ventana."""
    from voz import audio as mod

    aviso = threading.Event()
    # 3 s de ventana son ~94 trozos; se pide soltar en el quinto.
    monkeypatch.setattr(
        mod, "_sd",
        lambda: _SdPostizo(
            [_trozo()] * 94,
            al_entregar=lambda n: aviso.set() if n == 5 else None,
        ),
    )

    stt = STTPostizo()
    t = stt.escuchar(segundos=3.0, dispositivo=MICRO, cancelar=aviso)

    assert t.cierre == Cierre.ABORTADO.value
    # Se solto casi al momento: muy lejos de los 3,0 s de la ventana.
    assert t.duracion_audio_s < 1.0, (
        f"se llevo {t.duracion_audio_s:.2f} s: no solto cuando se le pidio"
    )


def test_lo_que_se_solto_NO_se_transcribe(monkeypatch) -> None:
    """Transcribir es justo el segundo y pico que se venia a quitar."""
    from voz import audio as mod

    aviso = threading.Event()
    monkeypatch.setattr(
        mod, "_sd",
        lambda: _SdPostizo(
            [_trozo()] * 94,
            al_entregar=lambda n: aviso.set() if n == 5 else None,
        ),
    )

    stt = STTPostizo()
    stt.escuchar(segundos=3.0, dispositivo=MICRO, cancelar=aviso)

    assert stt.transcripciones == 0


def test_una_vuelta_soltada_NO_dice_que_no_hubo_habla(monkeypatch) -> None:
    """>>> LA PARTE QUE FALLA ABIERTO SI SE HACE MAL <<<

    `hay_habla_vad` tiene que quedarse en None, que es "no se ha mirado",
    y no en False, que es "no hablo". Son la tercera y la segunda salida
    de la costura, y colapsarlas es el error por defecto de aqui: quien
    lea False creera que el usuario callo cuando en realidad nadie
    escucho, y una parada dicha en ese hueco se daria por no dicha.
    """
    from voz import audio as mod

    aviso = threading.Event()
    monkeypatch.setattr(
        mod, "_sd",
        lambda: _SdPostizo(
            [_trozo()] * 94,
            al_entregar=lambda n: aviso.set() if n == 5 else None,
        ),
    )

    t = STTPostizo().escuchar(segundos=3.0, dispositivo=MICRO, cancelar=aviso)

    assert t.hay_habla_vad is None
    assert t.verdicto_fiable is False


# El unico de este archivo que llega al VAD de verdad: comprueba que
# el silencio digital se para ANTES de Whisper, y para eso hace falta
# `silero_vad.onnx`.
@necesita_modelos_wake
def test_sin_aviso_la_ventana_va_entera_y_se_transcribe(monkeypatch) -> None:
    """El camino normal del oido no cambia: sondea su vuelta completa."""
    from voz import audio as mod

    monkeypatch.setattr(mod, "_sd", lambda: _SdPostizo([_trozo()] * 94))

    aviso = threading.Event()  # nunca se pone
    stt = STTPostizo()
    t = stt.escuchar(segundos=3.0, dispositivo=MICRO, cancelar=aviso)

    assert t.cierre != Cierre.ABORTADO.value
    # Silencio digital: el VAD lo para antes de Whisper, que es lo de
    # siempre y lo que hace barata la vuelta cuando la sala esta callada.
    assert t.hay_habla_vad is False
    assert stt.transcripciones == 0


def test_el_cierre_abortado_no_es_ninguna_de_las_otras_tres() -> None:
    """Cuatro respuestas a "por que se cerro la ventana", no tres.

    `abortado` NO es un veredicto del VAD: dice que otro necesitaba el
    microfono, y no dice nada sobre si hablaste.
    """
    valores = {c.value for c in Cierre}
    assert valores == {"silencio", "tope", "sin_habla", "abortado"}


@pytest.mark.parametrize("cierre", [c for c in Cierre])
def test_todos_los_cierres_son_texto_plano(cierre: Cierre) -> None:
    """`Transcripcion.cierre` viaja a la consola por JSON.

    `asdict()` deja los Enum como Enum y `json.dumps` los rechaza -- ya
    costo un fallo en vivo (ver `puente/consola.py`). Por eso lo que se
    guarda es `.value`, no el miembro.
    """
    assert isinstance(cierre.value, str)
