"""Nada de lo que se VE puede llevar datos de quien escribio el codigo.

>>> LO PILLO EL USUARIO MIRANDO EL GLOSARIO (2026-09-05) <<<
El glosario de ordenes llevaba escrito el nombre de un proyecto concreto,
puesto a mano entre las palabras del programa, y lo vio leyendolo. Esto
se publica: los ajustes, los menus y todo lo que se lee tienen que hablar
del proyecto de quien lo instale, no del de quien lo escribio.

Y el ejemplo lo dice todo: en una lista donde "apagate" y "para" SI son
palabras del programa, el nombre de un proyecto ajeno se lee como una
tercera. Quien instale esto de cero no lo tiene y se queda buscando el
comando.

>>> LO QUE ESTE ARCHIVO VIGILA, Y LO QUE NO <<<
Vigila lo que el usuario LEE: la pagina de ajustes, la consola y los
textos del catalogo. NO vigila los comentarios ni los docstrings, y es
deliberado: ahi hay que contar el caso real que produjo cada regla ("una
ruta dicha abria una carpeta y escrita otra"), que es justamente lo que
hay que conservar. Lo que se quita de un comentario es el
nombre propio, no la medicion: un caso contado es una medicion; un
nombre real en un desplegable es un bug.

Tampoco vigila `config/*.yaml`: eso son DATOS del usuario, no codigo, y
lo que hay que decidir ahi es otra cosa (que se publica y que no).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

# Los proyectos del autor, tal como estan en su `config/proyectos.yaml`.
# >>> LA LISTA YA NO SE ESCRIBE AQUI <<<
# (2026-09-09.) Estaba puesta a mano y enumeraba, por su nombre, los
# proyectos, los aparatos y el apellido de quien desarrolla esto -- o
# sea que el test escrito para impedir que sus datos viajaran era el
# que los publicaba. Ahora salen de `config/privado.txt`, que esta en
# `.gitignore`, y esto SALTA donde no exista. Ver `tests/privado.py`.
from tests.privado import cuela, necesita_la_lista


def _lo_que_se_ve(html: str) -> str:
    """El HTML sin comentarios, ni los de marcado ni los de JavaScript.

    Los dos se sirven al navegador pero ninguno se PINTA, y ahi los
    nombres reales son el registro de lo que paso -- misma regla que los
    docstrings. Aun asi conviene no dejarlos: la primera pasada de este
    test cazo uno mio en el JS, que contaba como se pintaba la fila de
    un proyecto y lo nombraba, y se reescribio: un comentario de un
    archivo que se publica lo lee cualquiera.
    """
    sin_marcado = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    return re.sub(r"^\s*//.*$", " ", sin_marcado, flags=re.M)


@pytest.mark.parametrize("pagina", ["ajustes.html", "consola.html"])
@necesita_la_lista
def test_ninguna_pagina_nombra_un_proyecto_del_autor(pagina) -> None:
    """El caso que reporto el usuario, y sus vecinos: el ejemplo de la
    seccion, el `placeholder` de la carpeta y el "¿por que?"."""
    visible = _lo_que_se_ve(
        (RAIZ / "puente" / pagina).read_text(encoding="utf-8")).lower()
    colados = cuela(visible)
    assert not colados, (
        f"{pagina} enseña nombres de proyectos del autor: {colados}. Un "
        f"ejemplo tiene que salir del registro DEL USUARIO o ser un hueco "
        f"que se lea como hueco.")


def test_el_glosario_saca_el_ejemplo_del_registro_del_usuario(
        tmp_path) -> None:
    """>>> ES EL CASO EXACTO QUE REPORTO <<<

    Con proyectos registrados, el ejemplo es UNO SUYO -- util, y suyo.
    Sin ninguno, que es como sale Jarvis recien instalado, va un hueco
    que se LEE como hueco: un nombre de mentira que parezca real seria la
    misma trampa con otra cara.
    """
    from nucleo.proyectos import Proyecto, guardar
    from voz.glosario import glosario

    vacio = glosario(tmp_path, "es")[3].frase
    assert not cuela(vacio)
    assert "el-que-tu-registres" in vacio

    guardar((Proyecto("mi-web", str(tmp_path)),), config_dir=tmp_path)
    assert "mi-web" in glosario(tmp_path, "es")[3].frase
    assert "mi-web" in glosario(tmp_path, "en")[3].frase


@necesita_la_lista
def test_los_textos_del_catalogo_no_llevan_nombres_reales() -> None:
    """Las etiquetas, ayudas y avisos de cada ajuste, en los dos idiomas.

    Se mira el catalogo YA CONSTRUIDO y no el archivo, porque es lo que
    de verdad llega a la pantalla -- y porque asi entran tambien los
    textos que se arman en tiempo de ejecucion.
    """
    from nucleo.ajustes import catalogo
    from nucleo.textos import AJUSTES_EN

    # >>> LAS `opciones` SE QUEDAN FUERA, Y SE DICE POR QUE <<<
    # Ahi viven los dispositivos de audio, y los construye
    # `_opciones_de_audio` mirando los que HAY ENCHUFADOS. En la maquina
    # del autor sale "micro USB" porque tiene uno, no porque este escrito
    # -- y en otra maquina saldra otra cosa. Mirarlas daria un test que
    # falla o pasa segun quien lo corra, que es peor que no tenerlo.
    # Lo que si hay que vigilar es el TEXTO, que si lo escribimos.
    dicho = " ".join(f"{a.etiqueta} {a.ayuda} {a.aviso}"
                     for a in catalogo()).lower()
    dicho += " " + " ".join(str(v) for v in AJUSTES_EN.values()).lower()

    colados = cuela(dicho)
    assert not colados, f"el catalogo nombra proyectos del autor: {colados}"

    de_su_pc = cuela(dicho)
    assert not de_su_pc, (
        f"un texto del catalogo nombra la maquina del autor: {de_su_pc}")


def test_ningun_ajuste_nace_con_una_ruta_dentro() -> None:
    """Un `por_defecto` con una carpeta de alguien dentro es lo mismo que
    un nombre de proyecto, pero peor: se guarda solo al primer GUARDAR."""
    from nucleo.ajustes import catalogo

    con_ruta = [a.clave for a in catalogo()
                if isinstance(a.por_defecto, str)
                and re.search(r"[A-Za-z]:\\|/home/|/Users/", a.por_defecto)]
    assert not con_ruta, f"nacen con una ruta dentro: {con_ruta}"
