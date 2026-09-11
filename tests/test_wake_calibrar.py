"""Calibrar la escucha: el paso que ESCRIBE un ajuste, y sus tres salidas.

>>> DE DONDE SALE (2026-09-09) <<<
Idea del usuario: que cada quien grabe su propio banco y que **el
aplicativo use lo que salga**, en vez de dejar el numero en una tabla
que hay que trasladar a mano a un YAML. Vale sobre todo para el ingles,
donde no hay ni una medicion, y para cualquiera cuya voz o cuya sala no
se parezcan a las del autor -- el umbral esta medido a filo de navaja
(el intento bueno mas flojo dio 0,494 contra un umbral de 0,5).

>>> LO QUE ESTOS TESTS PROTEGEN <<<
Que NO se recomiende con media medicion. Es la unica funcion del arbol
que escribe un ajuste a partir de algo que midio una persona, y el
error facil es el caro: con solo las activaciones, el umbral que "mejor
sale" es siempre el mas bajo que quepa, o sea el que despierta a Jarvis
solo. Y aqui un falso positivo no es una molestia -- es una ventana que
se abre sola, transcribe la sala y manda lo que oiga a la nube como si
fuera una orden. JC-0012 al pie de la letra.

NO NECESITAN AUDIO. `decidir_umbral` se extrajo justamente para esto: la
decision vivia mezclada con los `print` y con leer wav del disco, asi
que solo se podia probar en la unica maquina que tiene corpus. En un
clon recien descargado, el paso que escribe un ajuste no tenia un test.
"""

from __future__ import annotations

import pytest

from eval.wake_bench import (
    UMBRAL_MAX,
    UMBRAL_MIN,
    Negativos,
    decidir_umbral,
)


def _negativos(maxima: float, hubo: bool = True) -> Negativos:
    return Negativos(activaciones=0, segundos=300.0, maxima=maxima,
                     por_archivo=[maxima], hubo_material=hubo)


# --- 1. la salida que no se puede colapsar ----------------------------


def test_sin_material_ajeno_NO_se_recomienda_nada():
    """>>> EL ERROR CARO, Y ES EL QUE PARECE INOFENSIVO <<<

    "Cero falsos positivos" y "no he mirado si hay falsos positivos" se
    escriben igual con un `int`, y el segundo es el caso de cualquiera
    que acabe de instalar esto. Recomendar ahi es recomendar el umbral
    mas bajo que quepa.
    """
    frontera = decidir_umbral([0.9] * 20, _negativos(0.0, hubo=False))

    assert frontera.veredicto == "sin_material"
    assert frontera.propuesto is None


def test_sin_activaciones_tampoco_se_recomienda():
    assert decidir_umbral([], _negativos(0.05)).propuesto is None


def test_sin_la_mitad_ajena_EN_ABSOLUTO_tampoco():
    assert decidir_umbral([0.9], None).veredicto == "sin_material"


# --- 2. las nubes que se pisan son un RESULTADO -----------------------


def test_si_las_nubes_se_pisan_no_se_inventa_un_punto_medio():
    """Que se solapen dice algo verdadero: con esa palabra y esa voz NO
    existe umbral que acierte las dos cosas. El punto medio de dos nubes
    que se pisan es una frontera dibujada donde no la hay.

    Es el caso REAL de `eval/audio_wake_natural`, que es el corpus de
    decir "hey jarvis" a la española: el intento bueno mas flojo dio
    0,018 y el audio ajeno llego a 0,066.
    """
    frontera = decidir_umbral([0.018, 0.4, 0.9], _negativos(0.066))

    assert frontera.veredicto == "se_pisan"
    assert frontera.propuesto is None
    assert frontera.separacion < 0


def test_tocarse_exactamente_tambien_cuenta_como_pisarse():
    """Un empate no es una separacion. Con `<` en vez de `<=` saldria un
    umbral que deja el peor intento bueno JUSTO en la frontera."""
    assert decidir_umbral([0.3], _negativos(0.3)).veredicto == "se_pisan"


# --- 3. cuando si se puede --------------------------------------------


def test_con_las_dos_mitades_separadas_propone_el_punto_medio():
    """El caso real de `audio_wake_ing20_silencio`: el intento bueno mas
    flojo 0,917 y el audio ajeno 0,100 -> 0,51. Que caiga casi encima
    del 0,5 elegido a mano en agosto es la comprobacion buena: dos
    caminos distintos y el mismo numero."""
    frontera = decidir_umbral([0.917, 0.95, 0.99], _negativos(0.100))

    assert frontera.veredicto == "separadas"
    assert frontera.propuesto == 0.51
    assert frontera.separacion == pytest.approx(0.817)


def test_la_propuesta_no_se_sale_del_rango_que_acepta_el_panel():
    """Un numero fuera de rango es uno que el panel rechaza, y entonces
    la calibracion habria "guardado" algo que no se puede leer."""
    altisimo = decidir_umbral([0.999], _negativos(0.998))
    bajisimo = decidir_umbral([0.05], _negativos(0.001))

    assert UMBRAL_MIN <= altisimo.propuesto <= UMBRAL_MAX
    assert UMBRAL_MIN <= bajisimo.propuesto <= UMBRAL_MAX


def test_el_peor_intento_manda_y_no_la_mediana():
    """La calibracion la decide el intento bueno MAS FLOJO, porque es el
    que se perderia. Con la mediana, un umbral "razonable" dejaria fuera
    justo las veces que hablaste mas bajo -- que son las que se notan."""
    frontera = decidir_umbral([0.30, 0.95, 0.96, 0.97], _negativos(0.10))

    assert frontera.mas_flojo == 0.30
    assert frontera.propuesto == 0.20


# --- 4. y el ajuste solo se escribe cuando se pide ---------------------


def test_aplicar_suelto_no_escribe_nada(tmp_path, capsys):
    """`--aplicar` sin `--calibrar` no tiene nada que guardar. Aceptarlo
    en silencio dejaria a alguien creyendo que ya toco el ajuste."""
    import sys

    from eval.wake_bench import main

    argv = sys.argv
    sys.argv = ["wake_bench", "--aplicar"]
    try:
        assert main() == 2
    finally:
        sys.argv = argv
    assert "--calibrar" in capsys.readouterr().out


def test_el_ajuste_que_se_escribe_es_el_que_lee_el_wake_word():
    """>>> LA CLAVE TIENE QUE SER LA MISMA O ESTO NO SIRVE DE NADA <<<

    Escribir un ajuste que nadie lee es exactamente el mando en el vacio
    del 2026-09-03: `voz.wake_word.umbral` se validaba, se guardaba y se
    superponia bien, y `voz/bucle.py` construia `Wake()` sin argumento.
    Ocho dias en verde con 1269 tests.
    """
    import inspect

    from voz import wake

    assert "voz.wake_word.umbral" in inspect.getsource(wake)
