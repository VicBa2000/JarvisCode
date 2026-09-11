"""JC-0013: se deja de grabar cuando el usuario deja de hablar.

QUE PROTEGE ESTE ARCHIVO, y no es "que el VAD funcione" -- eso ya lo
cubre `test_voz_vad.py`. Protege las DOS decisiones de JC-0013, que son
las que se pueden deshacer sin querer:

  1. Que la ventana de dictado ya no la cierra un reloj. La prueba se
     hace contra las 30 ordenes reales de disco, no contra audio
     generado: cinco de ellas se hablan mas alla de los 4,0 s
     que corrian en produccion, o sea que la queja del usuario -- "a
     veces la escucha se corta y no termina de escucharme" -- esta
     grabada en el corpus.

  2. Que el umbral de fin de turno NO es `MIN_SILENCIO_MS`. Es la trampa
     que el usuario nombro al decidirlo ("no cuando le de su gana al
     VAD") y la unica forma de que no vuelva es un test que falle si
     alguien los unifica: con 300 ms, `08.wav` -- "ejecuta git status en
     la carpeta del proyecto" -- se corta en la pausa de en medio.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from tests.entorno import saltar_si_faltan_modelos_wake

from voz.audio import SAMPLE_RATE_VOZ, AudioError, Dispositivo
from voz.vad import (
    MIN_SILENCIO_MS,
    SILENCIO_FIN_TURNO_MS,
    TOPE_TURNO_S,
    VAD,
    Cierre,
    FinDeTurno,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIR_ORDENES = PROJECT_ROOT / "eval" / "audio_ordenes"
DIR_SILENCIO = PROJECT_ROOT / "eval" / "audio_silencio"

# La ventana FIJA que corria en produccion antes de esta tanda.
VENTANA_VIEJA_S = 4.0

ORDENES = sorted(DIR_ORDENES.glob("[0-9][0-9].wav"))
SILENCIOS = sorted(DIR_SILENCIO.glob("*.wav"))

falta_banco = pytest.mark.skipif(
    not ORDENES or not SILENCIOS,
    reason="faltan las grabaciones de eval/audio_ordenes y eval/audio_silencio",
)


def _leer(ruta: Path) -> np.ndarray:
    audio, sr = sf.read(ruta, dtype="float32")
    assert sr == SAMPLE_RATE_VOZ, f"{ruta.name} esta a {sr} Hz"
    return np.asarray(audio, dtype="float32").reshape(-1)


@pytest.fixture(scope="module")
def vad() -> VAD:
    # Sin los .onnx de openWakeWord esto no es un fallo: es un
    # entorno recien hecho. `silero_vad.onnx` llega en la misma
    # descarga que el wake word (por eso no entra `silero-vad` de
    # PyPI, que arrastraria torch).
    saltar_si_faltan_modelos_wake()
    return VAD()


def _hasta_donde_cierra(
    vad: VAD, audio: np.ndarray, silencio_fin_ms: float = SILENCIO_FIN_TURNO_MS
) -> FinDeTurno:
    """Le da el audio al detector como se lo daria el microfono."""
    detector = FinDeTurno(vad, silencio_fin_ms=silencio_fin_ms)
    for inicio in range(0, len(audio), 1024):
        if detector.empujar(audio[inicio : inicio + 1024]) is not None:
            break
    return detector


def _fin_del_habla_s(vad: VAD, audio: np.ndarray) -> float | None:
    spans = vad.segmentos(audio)
    return spans[-1][1] / SAMPLE_RATE_VOZ if spans else None


# --- 1. LA QUEJA DEL USUARIO, QUE ESTA EN EL CORPUS ---------------------


@falta_banco
def test_hay_ordenes_reales_que_pasan_de_la_ventana_fija_vieja(vad: VAD) -> None:
    """Sin esto, el resto del archivo no prueba nada.

    Si ninguna orden se pasase de 4,0 s, el fallo que se viene a arreglar
    no estaria representado en los datos y los tests de abajo estarian
    midiendo el vacio (contar primero cuantas veces ocurre el
    suceso).
    """
    largas = [
        r.name
        for r in ORDENES
        if (_fin_del_habla_s(vad, _leer(r)) or 0) > VENTANA_VIEJA_S
    ]
    assert len(largas) >= 3, (
        f"solo {len(largas)} orden(es) se pasan de {VENTANA_VIEJA_S} s; "
        f"el corpus ya no representa el fallo de JC-0013"
    )


@falta_banco
def test_el_detector_nunca_corta_una_orden_real(vad: VAD) -> None:
    """La prueba de que el reloj ya no manda.

    Cortar = cerrar la ventana y que DESPUES siguiera habiendo habla. Con
    una ventana fija eso le pasaba a las ordenes largas siempre; aqui no
    le puede pasar a ninguna.
    """
    cortadas = []
    for ruta in ORDENES:
        audio = _leer(ruta)
        detector = _hasta_donde_cierra(vad, audio)
        fin = _fin_del_habla_s(vad, audio)
        if detector.cierre is None or fin is None:
            continue
        if detector.segundos_vistos < fin:
            cortadas.append(
                f"{ruta.name} (cerro en {detector.segundos_vistos:.2f} s, "
                f"se hablaba hasta {fin:.2f} s)"
            )
    assert not cortadas, "cortadas a mitad de frase: " + ", ".join(cortadas)


# --- 2. LA TRAMPA: LOS DOS NUMEROS NO SON EL MISMO ----------------------


def test_el_umbral_de_fin_de_turno_no_es_el_de_segmentar() -> None:
    """Los dos numeros existen a la vez y contestan preguntas distintas.

    `MIN_SILENCIO_MS` dice que hueco va DENTRO de una frase;
    `SILENCIO_FIN_TURNO_MS` dice cuanto silencio significa "he
    terminado". Unificarlos es el fallo que describe el usuario.
    """
    assert SILENCIO_FIN_TURNO_MS > MIN_SILENCIO_MS


@falta_banco
def test_con_el_umbral_de_segmentar_se_corta_una_orden_de_verdad(
    vad: VAD,
) -> None:
    """El mecanismo se dispara, y esta es la traza que lo enseña.

    UNA sola orden de 30, asi que esto NO estima ninguna tasa:
    lo que demuestra es que reusar `MIN_SILENCIO_MS` como umbral de fin
    de turno PUEDE partir una orden real por su pausa, que es
    exactamente lo que hay que impedir. Con el umbral elegido, la misma
    orden sobrevive entera.
    """
    audio = _leer(DIR_ORDENES / "08.wav")
    fin = _fin_del_habla_s(vad, audio)
    assert fin is not None

    corto = _hasta_donde_cierra(vad, audio, silencio_fin_ms=MIN_SILENCIO_MS)
    assert corto.cierre is Cierre.SILENCIO
    assert corto.segundos_vistos < fin, (
        "con MIN_SILENCIO_MS esta orden ya no se corta: o cambio el audio "
        "o cambio el detector, y en los dos casos hay que volver a elegir "
        "el umbral con `-m eval.fin_de_turno_bench --barrido`"
    )

    bueno = _hasta_donde_cierra(vad, audio)
    assert bueno.cierre is Cierre.SILENCIO
    assert bueno.segundos_vistos >= fin


# --- 3. LAS TRES SALIDAS --------------------------------------


@falta_banco
def test_el_ruido_de_la_sala_no_abre_un_turno(vad: VAD) -> None:
    """Si la sala abriera turno, la ventana esperaria a que "terminase"
    de hablar algo que nadie empezo, y solo la cerraria el tope duro."""
    abrieron = []
    for ruta in SILENCIOS:
        detector = FinDeTurno(vad, espera_inicio_ms=10_000)
        for inicio in range(0, len(_leer(ruta)), 1024):
            detector.empujar(_leer(ruta)[inicio : inicio + 1024])
        if detector.empezo_en_s is not None:
            abrieron.append(ruta.name)
    assert not abrieron, f"se dio por empezado sobre silencio: {abrieron}"


def test_si_nadie_habla_la_ventana_se_cierra_sin_habla(vad: VAD) -> None:
    """La tercera salida: no es "texto vacio", es que no empezaste."""
    mudo = np.zeros(int(2.5 * SAMPLE_RATE_VOZ), dtype="float32")
    detector = FinDeTurno(vad, espera_inicio_ms=1000)
    salida = None
    for inicio in range(0, len(mudo), 1024):
        salida = detector.empujar(mudo[inicio : inicio + 1024])
        if salida is not None:
            break
    assert salida is Cierre.SIN_HABLA
    assert detector.empezo_en_s is None


@falta_banco
def test_una_pausa_corta_no_cierra_el_turno(vad: VAD) -> None:
    """Respirar en medio de una orden no la termina.

    Se cose una orden real consigo misma con un hueco de MIN_SILENCIO_MS
    en medio -- una pausa de las de DENTRO de una frase -- y detras una
    cola de silencio larga, que es la unica forma de que "cerro donde
    debia" se pueda distinguir de "se acabo el fichero". El audio es real; lo
    fabricado es el hueco, que es la variable bajo prueba.
    """
    audio = _leer(DIR_ORDENES / "11.wav")  # una de las cortas
    habla = vad.recortar(audio)
    assert habla.hay_habla

    def _silencio(ms: float) -> np.ndarray:
        return np.zeros(int(ms / 1000 * SAMPLE_RATE_VOZ), dtype="float32")

    hueco = _silencio(MIN_SILENCIO_MS)
    cola = _silencio(SILENCIO_FIN_TURNO_MS * 2)
    cosida = np.concatenate([habla.audio, hueco, habla.audio, cola])

    # Donde acaba la pausa. Cerrar antes de aqui es partir la orden en dos.
    pasada_la_pausa_s = (len(habla.audio) + len(hueco)) / SAMPLE_RATE_VOZ

    detector = _hasta_donde_cierra(vad, cosida)
    assert detector.cierre is Cierre.SILENCIO, (
        "con una cola de silencio de sobra, el detector tiene que cerrar el"
        " turno el solo"
    )
    assert detector.segundos_vistos > pasada_la_pausa_s, (
        f"cerro en {detector.segundos_vistos:.2f} s, dentro de la pausa que"
        f" acaba en {pasada_la_pausa_s:.2f} s: se quedo con la primera mitad"
    )


# --- 4. EL TOPE DURO, QUE NO SE QUITA ------------------------------------


class _StreamPostizo:
    def __init__(self, trozos, callback) -> None:
        self._trozos = trozos
        self._cb = callback

    def __enter__(self):
        for trozo in self._trozos:
            self._cb(trozo, len(trozo), None, None)
        return self

    def __exit__(self, *_):
        return False


class _SdPostizo:
    """Un PortAudio que entrega lo que se le diga, y nada mas."""

    def __init__(self, trozos) -> None:
        self._trozos = trozos

    def InputStream(self, *, callback, **_):  # noqa: N802 - es la API de sd
        return _StreamPostizo(self._trozos, callback)


MICRO = Dispositivo(
    indice=0, nombre="postizo", host_api="WASAPI", canales=1,
    sample_rate_nativo=SAMPLE_RATE_VOZ,
)


def test_el_tope_duro_cierra_aunque_el_detector_no_lo_haga(monkeypatch) -> None:
    """Un detector que no cierra nunca no puede ser una grabacion infinita.

    Es la leccion que costo un reinicio del PC el 2026-08-20, y en esta
    maquina hay 16 endpoints que entregan silencio digital perfecto sin
    dar error: si el que cierra la ventana es el habla, hace falta un
    maximo absoluto por encima.
    """
    from voz import audio as mod

    trozo = np.zeros((1024, 1), dtype="float32")
    monkeypatch.setattr(mod, "_sd", lambda: _SdPostizo([trozo] * 200))

    grabado, llego_al_tope = mod.grabar_hasta(
        MICRO, cerrar=lambda _t: False, tope_s=1.0
    )
    assert llego_al_tope is True
    assert len(grabado) == int(1.0 * SAMPLE_RATE_VOZ)


def test_un_microfono_que_deja_de_entregar_falla_en_vez_de_esperar(
    monkeypatch,
) -> None:
    """La llamada de audio que se porta mal no falla: espera. Aqui no."""
    from voz import audio as mod

    monkeypatch.setattr(mod, "_sd", lambda: _SdPostizo([]))
    monkeypatch.setattr(mod, "quien_usa_el_microfono", lambda: [])

    with pytest.raises(AudioError, match="dejo de entregar audio"):
        mod.grabar_hasta(
            MICRO, cerrar=lambda _t: False, tope_s=30.0, margen_s=0.2
        )


def test_el_tope_por_defecto_deja_hablar_mas_que_la_ventana_vieja() -> None:
    """Si el tope fuese como la ventana fija, no se habria arreglado nada."""
    assert TOPE_TURNO_S > VENTANA_VIEJA_S * 2
