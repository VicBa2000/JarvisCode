"""Elegir dispositivo desde la UI, y la guarda que lo hace seguro.

>>> EL HALLAZGO QUE MOTIVA ESTE ARCHIVO (2026-08-26) <<<
`Nivel.sin_senal` existe para distinguir un microfono de un cable
virtual, que es LA trampa de esta maquina: 16 de sus 23 endpoints
entregan silencio digital perfecto sin dar error. Estaba puesto en
`1e-5` (-100 dBFS)... y los cables entregan `1.46e-05` (-96,7 dBFS).
**La guarda estaba por debajo de lo que venia a cazar, o sea que no se
disparaba nunca.** Lo destapo el boton de probar el microfono, que es
justo para lo que se hizo.

Se midieron los 13 endpoints de entrada, 0,4 s cada uno:

    10 cables virtuales / muertos   -96.7 dBFS   rms 1.46e-05  (identicos:
                                                  es el bit menos
                                                  significativo de 16)
     4 microfonos de verdad         -69.8 dBFS   rms 3.24e-04  (placa)
                                    -53.9        2.01e-03  (micro USB)
                                    -43.5        6.70e-03  (webcam)

26,9 dB de hueco entre las dos nubes. El umbral se pone en su mitad
geometrica, 7e-5 (-83 dBFS): ~13 dB de margen por cada lado, sin pegarse
a ningun dato.

ESTOS TESTS NO NECESITAN LA TARJETA DE SONIDO. Llevan los numeros
MEDIDOS dentro en vez de volver a medir: asi valen en cualquier maquina
y siguen protegiendo la frontera, que es lo unico que puede regresar.
"""

from __future__ import annotations

import pytest

from voz.audio import UMBRAL_SIN_SENAL, Nivel, _como_lista

# Los dos extremos de la medicion del 2026-08-26.
RMS_CABLE_VIRTUAL = 1.46e-05      # -96.7 dBFS, los 10 iguales
RMS_MICRO_MAS_FLOJO = 3.24e-04    # -69.8 dBFS, el micro de placa


def _nivel(rms: float) -> Nivel:
    return Nivel(rms=rms, pico=rms * 3, segundos=0.4)


def test_un_cable_virtual_se_reconoce_como_tal() -> None:
    """>>> LA REGRESION QUE ESTE ARCHIVO IMPIDE <<<

    Si el umbral vuelve a bajar de 1.46e-05, esta comprobacion deja de
    dispararse y el panel de ajustes empieza a decir "llega señal" sobre
    un cable de audio virtual -- que es exactamente lo que hacia hasta
    hoy, y en silencio.
    """
    assert _nivel(RMS_CABLE_VIRTUAL).sin_senal is True


def test_el_microfono_mas_flojo_de_la_casa_NO_es_un_cable() -> None:
    """La otra direccion, que es la que se paga con un falso positivo:
    declarar cable un microfono de verdad dejaria al usuario sin poder
    elegir el unico que tiene."""
    assert _nivel(RMS_MICRO_MAS_FLOJO).sin_senal is False


def test_el_umbral_cae_DENTRO_del_hueco_medido() -> None:
    """No pegado a ningun dato: en medio de los 26,9 dB."""
    assert RMS_CABLE_VIRTUAL < UMBRAL_SIN_SENAL < RMS_MICRO_MAS_FLOJO
    margen_abajo = UMBRAL_SIN_SENAL / RMS_CABLE_VIRTUAL
    margen_arriba = RMS_MICRO_MAS_FLOJO / UMBRAL_SIN_SENAL
    assert margen_abajo > 3, "muy pegado a los cables"
    assert margen_arriba > 3, "muy pegado al microfono mas flojo"


def test_silencio_absoluto_tambien_es_sin_senal() -> None:
    assert _nivel(0.0).sin_senal is True
    assert _nivel(0.0).dbfs == -999.0


# --- un dispositivo suelto vale, y NO es una comodidad ------------------


def test_un_nombre_suelto_no_se_deshace_en_letras() -> None:
    """>>> EL FALLO RIDICULO Y MUDO <<<

    El panel guarda UN dispositivo (un desplegable no puede expresar una
    cadena de respaldo), pero el archivo base los declara como lista. Sin
    normalizar, `list("sistema")` da ['s','i','s','t','e','m','a'] y
    Jarvis se pone a buscar un microfono llamado "s". No da error: elige
    mal. Encontrado el 2026-08-26 al cablear la superposicion.
    """
    assert _como_lista("sistema") == ["sistema"]
    assert _como_lista("micro USB") == ["micro USB"]


def test_una_lista_sigue_siendo_una_lista_ordenada() -> None:
    """La cadena de respaldo del archivo base no se pierde: es lo que
    hace que un micro USB se use solo el dia que se enchufe."""
    assert _como_lista(["micro USB", "Webcam"]) == ["micro USB", "Webcam"]


def test_nada_configurado_es_una_lista_vacia_y_no_un_error() -> None:
    """Vacio significa "no lo has dicho", y quien llama ya se niega a
    adivinar. Aqui no se decide eso."""
    assert _como_lista(None) == []


# --- las tres salidas de probar un dispositivo -------------------------


def test_probar_un_dispositivo_que_no_esta_no_finge_que_si() -> None:
    """Tercera salida: no se pudo, que no es ni bien ni mal."""
    from voz.prueba import Veredicto, probar_entrada

    r = probar_entrada("Microfono de la Luna que no existe")
    assert r.veredicto is Veredicto.NO_SE_PUDO
    assert not r.bien
    # Y dice cuales SI hay, que es lo que convierte el error en accionable.
    assert "disponibles" in r.mensaje.lower() or "presente" in r.mensaje.lower()


def test_el_resultado_viaja_como_texto_plano() -> None:
    """`Veredicto` es un Enum y la consola lo manda por JSON. `asdict`
    deja los Enum como Enum y `json.dumps` los rechaza: ya costo un
    fallo en vivo (ver `puente/consola.py`)."""
    from voz.prueba import Resultado, Veredicto

    j = Resultado(Veredicto.SIN_SENAL, "x", "y", nivel_dbfs=-96.66).a_json()
    assert j["veredicto"] == "sin_senal"
    assert isinstance(j["veredicto"], str)
    assert j["nivel_dbfs"] == -96.7


def test_grabar_sin_hablar_NO_es_un_microfono_roto() -> None:
    """Llega señal y no hay habla: eso es `ok`, no `sin_senal`.

    Colapsarlos diria que el microfono esta roto por haberte quedado
    callado -- la confusion entre "el aparato esta mal" y "el usuario no
    hablo" que este proyecto lleva veinte dias separando.
    """
    from voz.prueba import Resultado, Veredicto

    r = Resultado(Veredicto.OK, "micro", "llega señal", nivel_dbfs=-54.0,
                  hubo_habla=False)
    assert r.bien
    assert r.veredicto is not Veredicto.SIN_SENAL


@pytest.mark.parametrize("tipo", ["entrada", "salida"])
def test_el_centinela_del_sistema_esta_en_las_opciones(tipo: str) -> None:
    """La peticion del usuario: que el audio salga por donde diga
    Windows. Tiene que poder elegirse desde el panel."""
    from nucleo.ajustes import _opciones_de_audio
    from voz.audio import PREDETERMINADO

    valores = [o["valor"] for o in _opciones_de_audio(tipo)]
    assert PREDETERMINADO in valores


def test_el_alias_de_directsound_no_se_ofrece_dos_veces() -> None:
    """"Controlador primario de sonido" ES el predeterminado con otro
    nombre. Ofrecerlo suelto daria dos entradas que hacen lo mismo y una
    de ellas sin explicar."""
    from nucleo.ajustes import _opciones_de_audio

    etiquetas = [o["etiqueta"].lower() for o in _opciones_de_audio("salida")]
    sueltos = [e for e in etiquetas if e.startswith("controlador primario")]
    assert not sueltos
