"""Tests for `voz/audio.py`, against the real audio devices of this PC.

No doubles: PortAudio is reachable and the machine has microphones, so
the no-mocks rule applies in full. The one thing a double WOULD be needed
for -- a device that hands back digital silence -- is covered by
building the `Nivel` value directly, which is not a double of anything:
it is the arithmetic being asserted.
"""

from __future__ import annotations

import pytest
import yaml

from voz.audio import (
    HOST_API_POR_DEFECTO,
    SAMPLE_RATE_VOZ,
    AudioError,
    ConfigAudio,
    Nivel,
    Suelo,
    calibrar_suelo,
    listar,
    medir_nivel,
    seleccionar,
)
from nucleo.configuracion import CONFIG_DIR
from tests.entorno import necesita_dispositivo


# --- lo que el modulo existe para impedir --------------------------------


def test_silencio_digital_y_sala_en_silencio_no_son_el_mismo_estado():
    """La costura: dos significados opuestos, dos salidas.

    Un cable virtual entrega ceros y una sala en silencio entrega el
    suelo de ruido del microfono. Si los dos contestaran lo mismo, el
    caso "estoy escuchando el dispositivo equivocado" seria invisible y
    Jarvis escucharia para siempre sin oir nada.
    """
    cable_virtual = Nivel(rms=0.0, pico=0.0, segundos=1.0)
    sala_en_silencio = Nivel(rms=0.026, pico=0.08, segundos=1.0)  # -31 dBFS, la webcam20

    assert cable_virtual.sin_senal is True
    assert sala_en_silencio.sin_senal is False
    assert "SIN SENAL" in cable_virtual.describe()
    assert "SIN SENAL" not in sala_en_silencio.describe()


def test_seleccionar_no_cae_al_dispositivo_por_defecto():
    """Pedir algo que no esta es un ERROR, nunca un silencio.

    Es la mitad que impide que esto falle ABIERTO: en esta maquina el
    dispositivo por defecto puede ser un cable de audio virtual, asi que
    un fallback callado convertiria un error de configuracion en horas
    de escuchar la nada.
    """
    with pytest.raises(AudioError) as excinfo:
        seleccionar(["no-existe-este-dispositivo-42"], "entrada")

    mensaje = str(excinfo.value)
    assert "no-existe-este-dispositivo-42" in mensaje
    assert "jarvis.yaml" in mensaje
    # Y dice que SI hay, que es lo que convierte el callejon sin salida
    # en un paso reparable.
    assert any(d.nombre in mensaje for d in listar("entrada"))


def test_entre_dos_generaciones_del_mismo_aparato_gana_la_nueva():
    """El fantasma del replug, medido el 2026-08-20.

    Al reconectar un USB, Windows lo reenumera con el prefijo
    incrementado -- '(2- Webcam USB)' pasa a '(3- ...)' -- y DEJA
    EL VIEJO EN LA LISTA, con estado OK. Abrir el fantasma no da error:
    se queda esperando para siempre.

    Un nombre parcial casa con los dos, y el fantasma va PRIMERO porque
    tiene el indice mas bajo, asi que "el primero que case" elegia
    justo el que cuelga. Costo una tarde y tres diagnosticos falsos.
    """
    from voz.audio import _generacion

    assert _generacion("Microfono (3- Webcam USB)") == 3
    assert _generacion("Microfono (2- Webcam USB)") == 2
    # Un aparato que nunca se ha desconectado no lleva numero, y eso solo
    # pierde contra una generacion posterior de si mismo.
    assert _generacion("Altavoces (Realtek Audio)") == 0
    assert _generacion("Microfono (10- USB Mic)") == 10


def test_el_orden_de_los_candidatos_manda():
    """Un micro USB que no siempre esta enchufado se resuelve por orden.

    Es lo que hace que el microfono USB se use el dia que se conecte sin
    tocar el config, y que mientras tanto se caiga al de repuesto sin ruido.
    """
    disponibles = listar("entrada")
    assert disponibles, "esta maquina deberia tener algun microfono"
    presente = disponibles[0].nombre

    elegido = seleccionar(["no-esta-conectado-todavia", presente], "entrada")
    assert elegido.nombre == presente


# --- configuracion --------------------------------------------------------


@necesita_dispositivo
def test_config_real_resuelve_microfono_y_altavoz():
    cfg = ConfigAudio.desde_config()
    mic = cfg.microfono()
    alt = cfg.altavoz()

    assert mic.host_api == cfg.host_api
    assert alt.host_api == cfg.host_api
    assert mic.canales >= 1
    assert alt.canales >= 1


def test_una_lista_vacia_no_significa_cualquier_dispositivo(tmp_path):
    """Sin nombres explicitos se para, en vez de adivinar.

    El mismo criterio aplicado a una allowlist vacia: el
    silencio no puede leerse como "sin restriccion", porque aqui
    "cualquiera" incluye los 16 cables virtuales.
    """
    (tmp_path / "jarvis.yaml").write_text(
        yaml.safe_dump({"voz": {"audio": {"entrada": [], "salida": []}}}),
        encoding="utf-8",
    )

    with pytest.raises(AudioError) as excinfo:
        ConfigAudio.desde_config(config_dir=tmp_path)

    assert "cable virtual" in str(excinfo.value)


@necesita_dispositivo
def test_el_config_del_proyecto_declara_los_dispositivos():
    """Guarda contra vaciar el bloque sin darse cuenta."""
    datos = yaml.safe_load((CONFIG_DIR / "jarvis.yaml").read_text(encoding="utf-8"))
    audio = datos["voz"]["audio"]

    assert audio["entrada"], "voz.audio.entrada no puede quedar vacio"
    assert audio["salida"], "voz.audio.salida no puede quedar vacio"
    assert audio["host_api"] == HOST_API_POR_DEFECTO


# --- host API: la razon medida de elegir DirectSound ----------------------


def test_el_host_api_elegido_acepta_16_khz_en_todos_sus_microfonos():
    """Lo que compra DirectSound: no escribir un resampler.

    openWakeWord, silero-vad y faster-whisper estan entrenados los tres
    a 16 kHz. WASAPI compartido acepta solo la frecuencia nativa de cada
    dispositivo (44.1 kHz en el micro de placa, 48 kHz en un USB
    tipico), asi que bajo WASAPI este test fallaria -- y esa es
    exactamente la diferencia que justifica la eleccion.
    """
    import sounddevice as sd

    microfonos = listar("entrada", HOST_API_POR_DEFECTO)
    assert microfonos, "sin microfonos no hay nada que comprobar"

    for dispositivo in microfonos:
        sd.check_input_settings(
            device=dispositivo.indice,
            samplerate=SAMPLE_RATE_VOZ,
            channels=1,
            dtype="float32",
        )


def test_los_nombres_no_vienen_cortados():
    """El otro motivo de DirectSound: MME trunca a 31 caracteres.

    Un nombre cortado ('Microfono (2- Webcam USB') rompe el
    casado por nombre del config, que es como se elige el dispositivo.
    """
    nombres = [d.nombre for d in listar("entrada", HOST_API_POR_DEFECTO)]
    assert nombres
    assert max(len(n) for n in nombres) > 31


# --- medicion real --------------------------------------------------------


@necesita_dispositivo
def test_medir_nivel_de_un_microfono_real_no_da_silencio_digital():
    """Si esto falla, el micro configurado no esta entregando audio.

    >>> Y LA PRIMERA SOSPECHA ES QUE ESTE SILENCIADO <<<
    Fallo el 2026-08-26 y ese era el motivo: el microfono USB aparecio a
    -91,8 dBFS, 38 dB por debajo de lo suyo, mientras los otros dos
    microfonos de la maquina seguian donde siempre (-72,3 la placa,
    -44,6 el de una webcam). Se silencia tocandolo por arriba.

    >>> Y HAY UNA SEGUNDA CAUSA, MEDIDA EL 2026-09-09 <<<
    Fallo otra vez, y esta vez NO estaba silenciado: **lo tenia ocupado
    otro programa** (una llamada de WhatsApp). Se midio en el momento, y
    lo que importa es que **son indistinguibles**:

        micro USB, ocupado por otra app   1,46e-05   <- sin senal
        webcam, libre                      2,06e-02
        micro de placa, libre            3,21e-04

    Ese 1,46e-05 es EXACTAMENTE el nivel que entregan los cables
    virtuales de esta maquina, o sea el numero por el que
    `UMBRAL_SIN_SENAL` subio de 1e-5 a 7e-5. Y DirectSound no da ningun
    error: devuelve silencio digital perfecto y se queda tan ancho.
    CONSECUENCIA QUE NO ES DE ESTE TEST: si alguien coge una llamada,
    Jarvis se queda SORDO sin un solo aviso. La guarda existe y esta
    bien puesta; lo que no hay es quien la mire mientras se escucha.

    NO SE AFLOJA EL UMBRAL CUANDO ESTO FALLA. Es un test de HARDWARE y
    esta diciendo la verdad: por ese micro no entra nada, y Jarvis
    escucharia para siempre sin oir. Aflojarlo para que pase seria
    apagar el unico aviso que hay.
    """
    mic = ConfigAudio.desde_config().microfono()
    nivel = medir_nivel(mic, segundos=0.3)

    assert nivel.segundos == 0.3
    assert nivel.sin_senal is False, (
        f"{nivel.describe()}\n"
        f"  Micro: {mic}\n"
        f"  DOS causas, y las dos se ven IGUAL desde aqui -- silencio\n"
        f"  digital sin un solo error (medidas las dos en esta maquina):\n"
        f"    1) LO TIENE OCUPADO OTRO PROGRAMA. Una llamada de WhatsApp,\n"
        f"       Teams, Discord o el navegador. Cierrala y repite.\n"
        f"    2) ESTA SILENCIADO. El microfono USB se silencia tocandolo por\n"
        f"       arriba, y el LED lo dice.\n"
        f"  Mira tambien el volumen de entrada en Windows. Sospechar del\n"
        f"  codigo es lo ULTIMO: este test solo lee lo que entra."
    )


@necesita_dispositivo
def test_calibrar_suelo_es_relativo_al_microfono_no_a_una_constante():
    """La correccion del 2026-08-20: el umbral era una suposicion.

    La primera version comparaba contra -50 dBFS fijos y esa webcam esta en
    -31, asi que "sala en silencio" habria dado SENAL siempre y la
    comprobacion habria pasado sin significar nada.
    """
    mic = ConfigAudio.desde_config().microfono()
    suelo = calibrar_suelo(mic, tomas=2, segundos=0.3)

    assert suelo.minimo <= suelo.dbfs <= suelo.maximo
    assert suelo.tomas == 2

    # Una lectura tomada del mismo microfono en las mismas condiciones no
    # puede "superar" su propio suelo: eso es lo que hace la comparacion
    # relativa y no lo que hacia la constante.
    #
    # >>> SE TOMA LA MAS TRANQUILA DE TRES, Y NO ES AFLOJARLO <<<
    # Con una sola lectura esto fallaba en falso: mide una sala VIVA dos
    # veces seguidas, y una tecla, una silla o el propio Jarvis
    # escuchando con el micro abierto bastan para que la segunda supere a
    # la primera. Paso dos veces el 2026-08-26 y las dos veces paso sola
    # al repetir. Un test que avisa en falso enseña a ignorar los avisos,
    # que es peor que no tenerlo.
    # Lo que se prueba sigue intacto: que el suelo es RELATIVO a este
    # microfono y no una constante. Si lo fuera, ninguna de las tres
    # lecturas pasaria.
    lecturas = [medir_nivel(mic, segundos=0.3) for _ in range(3)]
    tranquilo = min(lecturas, key=lambda n: n.rms)
    assert tranquilo.supera(suelo) is False, (
        f"{tranquilo.describe()} contra {suelo.describe()}\n"
        f"  (la mas tranquila de 3; si falla, la sala no estaba en "
        f"silencio al calibrar o el micro cambio de nivel)"
    )


def test_un_suelo_que_baila_se_declara_inestable():
    ruidoso = Suelo(dbfs=-30.0, minimo=-40.0, maximo=-20.0, tomas=3)
    quieto = Suelo(dbfs=-31.0, minimo=-32.0, maximo=-30.0, tomas=3)

    assert ruidoso.estable is False
    assert "INESTABLE" in ruidoso.describe()
    assert quieto.estable is True


@necesita_dispositivo
def test_calibrar_sin_tomas_es_un_error():
    mic = ConfigAudio.desde_config().microfono()
    with pytest.raises(AudioError):
        calibrar_suelo(mic, tomas=0)
