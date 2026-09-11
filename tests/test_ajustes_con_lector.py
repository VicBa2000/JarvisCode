"""Cada ajuste del panel tiene que tener a ALGUIEN que lo lea.

>>> ESTE ARCHIVO EXISTE PORQUE UN MANDO GIRABA EN EL VACIO <<<
Auditando el panel el 2026-09-03 aparecio `voz.wake_word.umbral`: estaba
en el catalogo desde el 2026-08-26, se validaba, se guardaba, se
superponia bien sobre `jarvis.yaml`... y no lo leia nadie. `voz/bucle.py`
construye `Wake()` sin argumento y el umbral salia de la constante del
modulo. El panel prometia ademas `aplica: reiniciar`, o sea que reiniciar
tampoco lo aplicaba.

>>> Y LA SUITE LLEVABA VERDE DESDE ENTONCES, CON 1269 TESTS <<<
No por descuido: `tests/test_nucleo_ajustes.py` usaba PRECISAMENTE ese
ajuste como cobaya de la superposicion, y con un motivo escrito. Los
tests demostraban que el valor llega al arbol mezclado, que es verdad.
Lo que no miraba nadie es si aguas abajo alguien lo recoge. El punto 2
del docstring de aquel archivo dice que la superposicion tiene que
llegar "A TODOS los que leen la config"; el hueco era el ajuste que no
tenia ninguno.

>>> POR QUE UN REGISTRO A MANO Y NO UN `grep` <<<
Se probo el `grep` primero y NO SIRVE, en las dos direcciones:

  * FALSO NEGATIVO: la mitad de los lectores no nombran la clave con
    puntos. `voz/stt.py` lee el ancla como
    `(bloque.get("stt") or {}).get("ancla_vocabulario")`, o sea que
    "voz.stt.ancla_vocabulario" no aparece en ninguna linea de codigo.
  * FALSO POSITIVO, que es el peligroso: la cadena SI aparece en
    docstrings y comentarios. `voz.wake_word.umbral` -- el ajuste muerto
    -- salia en tres sitios de `nucleo/textos.py`, y `voz/stt.py`
    menciona el ancla en su docstring tres lineas antes de leerla de
    verdad. Un test por texto habria dado el muerto por vivo.

Asi que el registro es EXPLICITO y dice, por cada ajuste, el archivo y
la expresion que hace la lectura. Cuesta una linea al añadir un ajuste, y
esa linea es justo la pregunta que nadie se hizo en agosto: **¿quien lo
lee?** Si no hay respuesta, el ajuste no deberia existir.

LO QUE ESTE TEST NO PRUEBA, y conviene no leerlo de mas: que la lectura
se ejecute, ni que el valor cambie el comportamiento. Prueba que hay un
lector nombrado y que sigue en su sitio. La otra mitad la cubren los
tests de cada modulo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nucleo.ajustes import catalogo

RAIZ = Path(__file__).resolve().parent.parent

# clave del panel -> (archivo que la lee, expresion que hace la lectura)
#
# La expresion se copia LITERAL del codigo. Si alguien reescribe esa
# linea, este test falla y hay que venir a decir donde se lee ahora --
# que es molesto exactamente una vez y evita que un ajuste se quede
# huerfano sin que nadie se entere.
LECTORES: dict[str, tuple[str, str]] = {
    # --- los que preguntan por la clave con puntos ---------------------
    "sesion.carpeta": ("escritorio/__main__.py", '_ajuste("sesion.carpeta"'),
    "ui.idioma": ("nucleo/textos.py", 'valor_de("ui.idioma"'),
    "ui.tema": ("puente/consola.py", 'valor_de("ui.tema"'),
    "voz.encendida": ("puente/__main__.py", 'valor_de("voz.encendida"'),
    "voz.idioma": ("voz/idioma.py", 'valor_de("voz.idioma"'),
    "voz.seguimiento": ("puente/__main__.py", 'valor_de("voz.seguimiento"'),
    "voz.narrar": ("puente/__main__.py", 'valor_de("voz.narrar"'),
    "voz.resumir": ("puente/__main__.py", 'valor_de("voz.resumir"'),
    "voz.wake_word.umbral": ("voz/wake.py", 'valor_de("voz.wake_word.umbral"'),
    "sesion.esfuerzo": ("puente/__main__.py", 'valor_de("sesion.esfuerzo"'),
    "sesion.modelo": ("puente/__main__.py", 'valor_de("sesion.modelo"'),
    "sesion.auto_por_defecto": ("nucleo/proyectos.py",
                                'valor_de("sesion.auto_por_defecto"'),
    "mcp.estricto": ("puente/__main__.py", 'valor_de("mcp.estricto"'),
    "proyectos.raiz": ("puente/consola.py", 'valor_de("proyectos.raiz"'),
    # >>> LO LEE `voz/proyecto.py` Y NO EL PANEL, Y ESO ES EL PUNTO <<<
    # `nucleo/ajustes.py` tambien lo ensena, pero preguntandoselo a este:
    # un panel que leyera su propia clave pintaria el valor guardado sin
    # que nadie aguas abajo lo recogiera, que es exactamente la forma del
    # umbral del wake word. Quien construye el turno es quien lo lee.
    "proyectos.ritual": ("voz/proyecto.py", 'valor_de("proyectos.ritual"'),
    "tiempos.telegram_minutos": ("puente/__main__.py",
                                 'valor_de("tiempos.telegram_minutos"'),
    "tiempos.ausente_minutos": ("puente/__main__.py",
                                'valor_de("tiempos.ausente_minutos"'),
    "tiempos.seguimiento_s": ("puente/__main__.py",
                              'valor_de("tiempos.seguimiento_s"'),
    # --- los que la leen ANIDADA, y por eso el grep no vale ------------
    # Estos entran por `load_general_config`, que es donde vive la
    # superposicion, asi que recogen lo del panel sin nombrar la clave.
    "voz.audio.entrada": ("voz/audio.py", 'audio.get("entrada")'),
    "voz.audio.salida": ("voz/audio.py", 'audio.get("salida")'),
    "voz.perfil": ("voz/perfil.py", 'bloque.get("perfil")'),
    "voz.stt.modelo": ("voz/stt.py", '.get("modelo")'),
    "voz.stt.ancla_vocabulario": ("voz/stt.py", '.get("ancla_vocabulario"'),
}


def test_el_registro_cubre_el_catalogo_entero() -> None:
    """Un ajuste nuevo sin lector declarado para la suite aqui.

    Es el unico sitio del arbol donde se obliga a contestar "¿quien lo
    lee?" antes de que el mando llegue a la pantalla.
    """
    del_panel = {a.clave for a in catalogo()}
    sin_declarar = sorted(del_panel - set(LECTORES))
    assert not sin_declarar, (
        f"estos ajustes salen en el panel y nadie ha dicho quien los lee: "
        f"{', '.join(sin_declarar)}. Si no hay lector, el mando gira en el "
        f"vacio (paso con voz.wake_word.umbral); si lo hay, apuntalo en "
        f"LECTORES.")

    sobran = sorted(set(LECTORES) - del_panel)
    assert not sobran, (
        f"LECTORES nombra ajustes que ya no estan en el catalogo: "
        f"{', '.join(sobran)}")


@pytest.mark.parametrize("clave", sorted(LECTORES))
def test_el_lector_declarado_sigue_ahi(clave: str) -> None:
    """El archivo existe y la expresion de lectura sigue escrita en el."""
    nombre, expresion = LECTORES[clave]
    ruta = RAIZ / nombre
    assert ruta.is_file(), f"{clave}: {nombre} ya no existe"
    texto = ruta.read_text(encoding="utf-8")
    assert expresion in texto, (
        f"{clave}: {nombre} ya no contiene `{expresion}`. O se movio la "
        f"lectura -- y hay que actualizar LECTORES -- o el ajuste se quedo "
        f"sin quien lo lea.")


def test_el_umbral_del_wake_word_lo_lee_quien_lo_usa() -> None:
    """El caso que origino el archivo, fijado aparte.

    >>> Y SE MIRA LA FIRMA, QUE ES DONDE ESTABA LA TRAMPA <<<
    El arreglo obvio era copiar el patron de `tiempos.seguimiento_s`, que
    `puente/__main__.py` aplica pisando la constante del modulo. Aqui eso
    habria sido INERTE Y MUDO: con `def __init__(self, umbral=UMBRAL)` el
    defecto se evalua al definir la funcion y se congela en
    `__defaults__`, asi que pisar `voz.wake.UMBRAL` despues del import no
    cambia nada y no da error. Por eso el defecto tiene que ser `None`.
    """
    import inspect

    from voz.wake import UMBRAL, Wake

    firma = inspect.signature(Wake.__init__)
    assert firma.parameters["umbral"].default is None, (
        "el defecto tiene que ser None para que se lea el ajuste: un "
        "numero aqui se congela al importar y el ajuste vuelve a ser mudo")
    # La constante se queda, pero como SUELO y no como el valor.
    assert UMBRAL == 0.5
