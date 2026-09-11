"""Tests for `voz/tts.py`, against real Piper voices on disk.

No doubles: the voices are downloaded and Piper runs on CPU, so there is
nothing here that the real thing cannot produce. These are NOT
marked `lento` on purpose -- they need neither the GPU nor Ollama, and
the rule learned on 2026-08-19 is that the marker is not paid in seconds
but in the number of times a test is never run.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.entorno import (INSTALACION_RECIEN_HECHA,
                           necesita_dispositivo,
                           necesita_voces)
import yaml

from voz.tts import DIR_VOCES, TTS, Habla, TTSError, ruta_de_voz, voces_disponibles

# The smallest downloaded voice (28 MB), so the suite stays quick. Which
# voice SHIPS is a different question, decided by `eval/tts_bench.py`.
VOZ_DE_PRUEBA = "es_ES-carlfm-x_low"


@pytest.fixture(scope="module")
def tts() -> TTS:
    """>>> TRES SALIDAS, Y ANTES ERAN DOS (2026-09-08) <<<

    "No hay NINGUNA voz" y "estan las voces pero falta justo esta" no son
    lo mismo, y hasta hoy las dos daban `pytest.fail`. Lo primero es un
    clon recien descargado -- `modelos/` son 745 MB fuera de git -- y no
    es un fallo de nadie: es que todavia no se ha bajado. Lo segundo si
    es un entorno roto, porque las demas voces si llegaron.
    Se midio en un clon virgen antes de tocar esto: los 6 tests que
    dependen de esta fixture salian en ERROR con el mensaje correcto
    debajo, y un recien llegado no lee seis mensajes, cierra la carpeta.
    """
    disponibles = voces_disponibles()
    if not disponibles:
        pytest.skip(
            f"no hay ninguna voz de Piper en {DIR_VOCES}: se bajan con "
            f"`python -m piper.download_voices {VOZ_DE_PRUEBA} "
            f"--download-dir modelos/piper` (ver README)."
        )
    # >>> Y HABIA UN CUARTO ESTADO, DESCUBIERTO EL 2026-09-09 <<<
    # El docstring de arriba reparte el mundo en dos entornos: cero voces
    # (clon virgen) o todas (la maquina del autor). `instalar.bat` crea
    # el de en medio -- **solo la de fabrica** --, y ahi la rama de abajo
    # falla diciendo "y las demas SI estan", que es literalmente falso:
    # no hay ninguna otra.
    # Lo que estos seis tests prueban es el MOTOR, no esta voz: la
    # eleccion de `es_ES-carlfm-x_low` es por tamano (28 MB, la suite
    # rapida), no un requisito. Asi que con una instalacion recien hecha
    # se usa la que hay y se prueba lo mismo.
    if VOZ_DE_PRUEBA not in disponibles and INSTALACION_RECIEN_HECHA:
        return TTS(voz=disponibles[0])
    if VOZ_DE_PRUEBA not in disponibles:
        pytest.fail(
            f"Falta la voz {VOZ_DE_PRUEBA} en {DIR_VOCES}, y las demas SI "
            f"estan ({', '.join(disponibles)}). Es parte del entorno de la "
            f"Fase 5, no un opcional: se baja con "
            f"`python -m piper.download_voices {VOZ_DE_PRUEBA} "
            f"--download-dir modelos/piper`."
        )
    return TTS(voz=VOZ_DE_PRUEBA)


# --- que no sustituya una voz por otra en silencio ------------------------


def test_una_voz_que_no_esta_es_un_error_que_dice_cuales_hay():
    """Misma forma que `voz.audio.seleccionar`: nada de sustituir callando.

    Hablar con una voz que nadie pidio es un fallo que no se nota en
    semanas, asi que el error enumera lo que SI hay (un argumento
    malo detectable dice como se escribe bien).
    """
    with pytest.raises(TTSError) as excinfo:
        ruta_de_voz("es_ES-nadie-medium")

    mensaje = str(excinfo.value)
    assert "es_ES-nadie-medium" in mensaje
    assert "download_voices" in mensaje
    for voz in voces_disponibles():
        assert voz in mensaje


@necesita_voces
def test_las_voces_descargadas_se_ven():
    disponibles = voces_disponibles()
    assert disponibles, f"no hay voces en {DIR_VOCES}"
    assert all(not v.endswith(".onnx") for v in disponibles)
    for voz in disponibles:
        assert ruta_de_voz(voz).is_file()


def test_sin_perfil_activo_no_se_elige_una_voz_por_su_cuenta(tmp_path):
    """Una decision pendiente no puede volverse una decision tomada.

    Sin perfil activo el modulo NO escoge la primera voz que encuentre:
    eso haria que el sistema hablase con una voz que nadie eligio, que es
    de la familia de fallos que no se nota en semanas.
    """
    (tmp_path / "jarvis.yaml").write_text(
        yaml.safe_dump(
            {
                "voz": {
                    "perfiles": {
                        "jarvis": {
                            "nombre": "Jarvis",
                            "tts_voz": VOZ_DE_PRUEBA,
                            "wake_words": ["hey_jarvis"],
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(TTSError) as excinfo:
        TTS(config_dir=tmp_path)

    assert "voz.perfil" in str(excinfo.value)


# --- sintesis real --------------------------------------------------------


def test_sintetizar_produce_audio_de_verdad(tts: TTS):
    trozos = list(tts.sintetizar("Listo. He movido treinta y seis archivos."))

    assert trozos, "la voz no produjo ni un trozo de audio"
    audio = np.concatenate(trozos)
    assert audio.dtype == np.float32
    assert np.max(np.abs(audio)) > 0.01, "produjo audio, pero es silencio"
    # Una frase de ese largo no puede durar decimas ni un minuto.
    assert 1.0 < len(audio) / tts.sample_rate < 15.0


def test_texto_vacio_no_produce_audio_ni_revienta(tts: TTS):
    assert list(tts.sintetizar("")) == []
    assert list(tts.sintetizar("   \n  ")) == []


def test_sintetizar_es_un_generador_no_un_buffer(tts: TTS):
    """Lo que compra el streaming: el primer trozo llega ANTES del ultimo.

    Es la diferencia entre cumplirla y no cumplirla, porque la meta
    es cuando EMPIEZA a sonar, no cuando termina de generarse.
    """
    import time

    largo = (
        "Paso uno. Paso dos. Paso tres. Paso cuatro. Paso cinco. "
        "Paso seis. Paso siete. Paso ocho. Paso nueve. Paso diez."
    )
    inicio = time.perf_counter()
    generador = tts.sintetizar(largo)
    primero = next(generador)
    t_primero = time.perf_counter() - inicio
    resto = list(generador)
    t_total = time.perf_counter() - inicio

    assert primero.size > 0
    assert resto, "esta frase deberia partirse en varios trozos"
    assert t_primero < t_total


def test_medir_separa_el_primer_audio_del_total(tts: TTS):
    habla = tts.medir("Vale, voy.")

    assert isinstance(habla, Habla)
    assert 0 < habla.primer_audio_s <= habla.total_s
    assert habla.segundos_de_audio > 0
    assert habla.sample_rate == tts.sample_rate
    # Contra la voz que USA la fixture, no contra la constante: con una
    # instalacion recien hecha cae a la unica que hay, y comparar con
    # `VOZ_DE_PRUEBA` haria fallar el motor por el nombre del modelo.
    assert habla.voz == tts.nombre


def test_la_meta_del_555_se_evalua_sobre_el_primer_audio():
    """El umbral mide el primer audio, no el total.

    Se comprueba sobre valores construidos porque lo que se afirma es la
    REGLA, no el rendimiento de esta maquina: una voz que empieza en
    0.3 s cumple aunque tarde 4 s en decirlo todo.
    """
    rapida_pero_larga = Habla(
        texto="", voz="x", primer_audio_s=0.3, total_s=4.0,
        segundos_de_audio=10.0, sample_rate=16000, audio=np.zeros(1, dtype=np.float32),
    )
    lenta_pero_corta = Habla(
        texto="", voz="x", primer_audio_s=0.8, total_s=0.9,
        segundos_de_audio=1.0, sample_rate=16000, audio=np.zeros(1, dtype=np.float32),
    )

    assert rapida_pero_larga.cumple_meta is True
    assert lenta_pero_corta.cumple_meta is False
    assert rapida_pero_larga.factor_tiempo_real > 1.0


# >>> ESTOS DOS SUENAN DE VERDAD, Y LES FALTABA LA GUARDA <<<
# (2026-09-09.) Abren el ALTAVOZ, y `voz/audio.py` se niega a elegir
# dispositivo si no esta declarado por nombre -- que es como nace una
# instalacion, a proposito: 16 de los 23 endpoints de esta maquina son
# cables virtuales que entregan silencio digital sin dar error.
# No se veia porque hacian falta las DOS cosas a la vez: una voz
# descargada y ningun aparato elegido. Un clon virgen no tiene voz y
# la maquina del autor tiene aparato; el estado de en medio lo crea
# `instalar.bat`.
@necesita_dispositivo
def test_hablar_no_vuelve_antes_de_que_el_audio_haya_sonado(tts: TTS):
    """La regresion del 2026-08-20, y suena de verdad por el altavoz.

    `hablar` usaba `flujo.write()`, y la escritura BLOQUEANTE de
    PortAudio no la soporta DirectSound en esta maquina: acepta las
    muestras y las tira, sin error. Piper genera ~30 veces mas rapido de
    lo que se habla, asi que la funcion volvia enseguida y no se oia
    nada -- 5.51 s de voz devueltos en 0.30 s.

    Es la leccion del propio subsistema aplicada al reves: escribir en un
    dispositivo que no va a ningun sitio DEVUELVE EXITO, igual que grabar
    de un cable virtual devuelve silencio. La entrada estaba vigilada
    desde la primera linea y la salida no, porque "la llamada volvio" se
    tomo como prueba de que habia sonado.

    Por eso este test hace ruido de verdad en vez de comprobar que no
    revienta: es la unica forma de distinguir los dos casos.
    """
    import time

    inicio = time.perf_counter()
    habla = tts.hablar("Vale, voy.")
    transcurrido = time.perf_counter() - inicio

    assert habla.segundos_de_audio > 0.3, "la frase deberia durar algo"
    assert transcurrido >= habla.segundos_de_audio * 0.9, (
        f"hablar() volvio en {transcurrido:.2f} s para {habla.segundos_de_audio:.2f} s "
        f"de audio: se esta descartando lo que faltaba por sonar"
    )
    # Y la sintesis se sigue midiendo aparte de la reproduccion, o una
    # frase larga pareceria una voz lenta.
    assert habla.total_s < habla.segundos_de_audio


@necesita_dispositivo
def test_mandarle_callar_le_calla_a_MITAD_de_frase(tts: TTS):
    """El "para" de JC-0011 aplicado a la voz, y suena de verdad.

    Quien dice "para" mientras Jarvis le habla encima quiere silencio
    AHORA, no cuando acabe el parrafo. Sin esto, el "para" pararia a
    Claude Code y dejaria a Jarvis recitando la respuesta de algo que ya
    no se esta haciendo, que es la peor forma de decir que has
    obedecido.

    Se comprueba con el reloj, no con una bandera: lo unico que
    distingue "se callo" de "dijo que se callaba" es que la llamada
    vuelva ANTES de que el audio hubiera terminado de sonar.
    """
    import threading
    import time

    frase = ("Voy a explicarte con calma como esta organizado el proyecto, "
             "porque son varias piezas y conviene no mezclarlas. "
             "Primero la capa de voz, despues el puente, y al final la consola.")
    callar = threading.Event()
    threading.Timer(0.6, callar.set).start()

    inicio = time.perf_counter()
    habla = tts.hablar(frase, cancelar=callar)
    transcurrido = time.perf_counter() - inicio

    assert habla.cortado is True
    assert transcurrido < 3.0, (
        f"tardo {transcurrido:.2f} s en callarse: no se esta cortando")


def test_el_banco_mide_frases_que_el_sistema_dice_de_verdad():
    """La regla del 2026-08-11: una sonda con texto inventado mide la
    redaccion de quien la escribio.

    La pregunta de aprobacion del banco tiene que salir del renderizador
    REAL, porque es la frase que la Fase 5 leera en voz alta antes de
    tocar nada y es la mas dificil de decir (rutas, comodines y nombres
    de herramienta con puntos).
    """
    from eval.tts_bench import _frases

    etiquetas = dict(_frases())
    assert "Jarvis quiere ejecutar" in etiquetas["aprobacion"]
    assert "fs.move_many" in etiquetas["aprobacion"]
