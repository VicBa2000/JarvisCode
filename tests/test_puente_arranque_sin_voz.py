"""Que el arranque diga POR QUE no hay voz, y no lo contrario.

>>> DE DONDE SALE (2026-09-10) <<<
Lo reporto el usuario probando: paso la voz de ingles a español en los
ajustes, reinicio, y Jarvis arranco sin escuchar. Lo repitio apagando y
encendiendo la maquina entera, y luego lanzandolo a mano con `--voz`.
Las tres veces igual.

La CAUSA era correcta y estaba bien contada: dejo `voz.perfil` en
`jarvis_en` con `voz.idioma` en `es`, y `voz/perfil.py` se niega a
arrancar con un perfil que no cuadra -- si arrancara, leeria español con
fonetica inglesa y eso solo se descubre al oirlo. El arranque lo explicaba
con todas las letras:

    NO SE PUDO ENCENDER LA VOZ: TTSError: El perfil activo 'jarvis_en'
    habla con una voz 'en' (en_US-lessac-medium) pero Jarvis esta puesto
    en 'es'.

**Y nadie lo leyo nunca**, porque la carcasa corre con `pythonw`: ahi
`sys.stdout` es None y `escritorio/salida.py` desvia los `print` a
`logs/escritorio/arranque_*.log`. La ventana no decia nada. Es el mismo
silencio que ya destapo `Consola.avisa` el 09-03, en el ultimo sitio
donde quedaba.

Debajo habia un segundo fallo, y es el que estos tests fijan: el resumen
del final imprimia

    Voz apagada (usa --voz para encenderla).

a alguien que acababa de arrancar con `--voz`. No solo no ayuda --
manda a mirar un flag que ya esta puesto --, es que CONTRADICE el aviso
de unas lineas mas arriba: quien lea solo el final se lleva que la voz
esta apagada porque no la pidio, y deja de buscar. Regla 5: "no hay voz"
admite dos respuestas distintas y el codigo tenia una sola rama.
"""

from __future__ import annotations

from puente.__main__ import aviso_de_voz_caida, resumen_sin_voz

# El fallo REAL, copiado de `logs/escritorio/arranque_20260910_153625.log`
# y no inventado (regla 8). Son tres renglones, y eso es justo lo que
# `aviso_de_voz_caida` tiene que recortar.
FALLO = (
    "TTSError: El perfil activo 'jarvis_en' habla con una voz 'en' "
    "(en_US-lessac-medium) pero Jarvis esta puesto en 'es'.\n"
    "  Una voz de otro idioma no da error: lee el texto con la fonetica "
    "que no es, y solo se nota al oirlo.\n"
    "  Elige un perfil del idioma en los ajustes, o cambia el idioma de "
    "la voz."
)


def test_sin_pedirla_se_invita_a_pedirla() -> None:
    """El caso de siempre: no hay `--voz` y no hay `voz.encendida`."""
    assert "--voz" in resumen_sin_voz(None)


def test_pedida_y_caida_NO_manda_usar_el_flag_que_ya_uso() -> None:
    """>>> ESTE ES EL FALLO QUE SE REPORTO <<<

    Con `--voz` puesto y la voz caida, "usa --voz para encenderla" es la
    pantalla contradiciendo al aviso de arriba.
    """
    dicho = resumen_sin_voz(FALLO)
    assert "usa --voz" not in dicho
    assert "PEDIDA" in dicho


def test_son_TRES_salidas_y_no_dos() -> None:
    """Que las dos ramas digan cosas DISTINTAS.

    Sin esto, alguien puede "arreglarlo" devolviendo el mismo texto en
    los dos casos y los otros dos tests seguirian en verde.
    """
    assert resumen_sin_voz(None) != resumen_sin_voz(FALLO)


def test_a_la_pantalla_va_SOLO_la_primera_linea() -> None:
    """El detalle entero se queda en el diario del arranque.

    La tarjeta de la consola es un renglon: meterle los tres del
    `TTSError` la convierte en un parrafo que nadie lee. La primera es la
    accionable -- dice el perfil, su idioma y el idioma puesto --.
    """
    aviso = aviso_de_voz_caida(FALLO)
    assert "El perfil activo 'jarvis_en'" in aviso
    assert "\n" not in aviso
    assert "solo se nota al oirlo" not in aviso
    assert "La consola sigue funcionando" in aviso


def test_un_fallo_de_una_sola_linea_no_se_rompe() -> None:
    """No todo lo que cae aqui es un `TTSError` de tres renglones."""
    assert "Algo" in aviso_de_voz_caida("RuntimeError: Algo")
