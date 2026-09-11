"""`voz.idioma` y `voz.perfil` van JUNTOS. Decision del usuario, 2026-09-10.

>>> DE DONDE SALE, Y QUE REVIERTE <<<
Hasta hoy eran dos ajustes independientes, y lo que impedia el desastre
era `voz/perfil.py`, que se NIEGA a arrancar la voz si el perfil no habla
el idioma configurado. Esa negativa es correcta y no se toca: Piper
sintetiza por fonemas del idioma con el que se entreno la voz, asi que
una voz española leyendo ingles **no da error**, solo suena mal -- y eso
solo se descubre oyendolo.

Lo que estaba mal era poder LLEGAR a ese estado. El usuario se lo comio
tres arranques seguidos y en las dos direcciones:

    perfil 'jarvis_en' + idioma 'es'   -> Jarvis arranca sin voz
    perfil 'jarvis'    + idioma 'en'   -> Jarvis arranca sin voz

y cada intento costaba un reinicio para enterarse, porque el aviso salia
DESPUES de arrancar. Sus palabras: *"son dos ajustes que deben ir juntos,
o ambos en español, o ambos en ingles"*.

Antes de esto, el `aviso` del panel decia "CAMBIA TAMBIEN la voz de aqui
abajo" -- o sea que el trabajo de mantener la pareja coherente era del
usuario, y la pantalla se limitaba a recordarselo. Ahora lo hace
`_emparejar_la_voz` al guardar, que es antes de reiniciar.

>>> POR QUE EN `guardar` Y NO EN LA PAGINA <<<
`guardar` es la unica puerta por la que se escribe `config/ajustes.yaml`,
y la cabecera de ese archivo invita a editarlo a mano. Con esto en el JS,
la pareja quedaria coherente solo para quien pase por el panel -- que es
exactamente el reparto que ya fallo con `guardar_mcp` (borraba el
lanzador) y con `guardar_proyectos` (reponia `auto` a true).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from nucleo.ajustes import AjustesError, catalogo, guardar

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture()
def config(tmp_path: Path) -> Path:
    """Una configuracion RECIEN SEMBRADA, como la de un clon.

    Se copia `config/base/jarvis.yaml`, que es lo que se publica, en vez
    de apuntar a la del autor: asi el test dice lo mismo en su maquina y
    en la de cualquiera, y de paso no puede escribir en la suya.
    """
    shutil.copy(RAIZ / "config" / "base" / "jarvis.yaml",
                tmp_path / "jarvis.yaml")
    return tmp_path


def par(config: Path) -> tuple[str, str]:
    """El (idioma, perfil) que quedaria puesto, leido del catalogo."""
    v = {a.clave: a.valor for a in catalogo(config)}
    return str(v["voz.idioma"]), str(v["voz.perfil"])


def test_de_fabrica_ya_cuadran(config: Path) -> None:
    assert par(config) == ("es", "jarvis")


def test_cambiar_el_idioma_arrastra_la_voz(config: Path) -> None:
    """El caso que reporto el usuario, en su primera direccion."""
    escritos = guardar({"voz.idioma": "en"}, config)
    assert escritos["voz.perfil"] == "jarvis_en"
    assert par(config) == ("en", "jarvis_en")


def test_cambiar_la_voz_arrastra_el_idioma(config: Path) -> None:
    """Y en la otra, que es la que se le rompio la segunda vez."""
    escritos = guardar({"voz.perfil": "jarvis_en"}, config)
    assert escritos["voz.idioma"] == "en"
    assert par(config) == ("en", "jarvis_en")


def test_y_se_puede_volver(config: Path) -> None:
    """Ir no vale de nada si no se puede volver por el mismo sitio."""
    guardar({"voz.idioma": "en"}, config)
    guardar({"voz.idioma": "es"}, config)
    assert par(config) == ("es", "jarvis")


def test_lo_arrastrado_VIAJA_al_panel(config: Path) -> None:
    """>>> Y ESTO NO ES COSMETICA <<<

    `Consola.guardar_ajustes` construye su lista de "hace falta
    reiniciar" a partir de lo que devuelve `guardar`. Si el ajuste
    arrastrado no viniera aqui dentro, la voz cambiaria sin que la
    pantalla lo dijera -- que es la pantalla mintiendo, y de eso este
    proyecto ya lleva varios.
    """
    escritos = guardar({"voz.idioma": "en"}, config)
    assert set(escritos) == {"voz.idioma", "voz.perfil"}


def test_otro_perfil_del_MISMO_idioma_no_mueve_nada(config: Path) -> None:
    """Elegir entre dos voces españolas es una eleccion, no un conflicto."""
    escritos = guardar({"voz.perfil": "kana"}, config)
    assert "voz.idioma" not in escritos
    assert par(config) == ("es", "kana")


def test_un_ajuste_ajeno_no_toca_la_voz(config: Path) -> None:
    escritos = guardar({"ui.tema": "hacker"}, config)
    assert "voz.perfil" not in escritos and "voz.idioma" not in escritos
    assert par(config) == ("es", "jarvis")


def test_los_dos_a_la_vez_y_coherentes_pasan(config: Path) -> None:
    """Elegir el par a mano sigue siendo legitimo, y es lo que hace la UI
    de quien quiere una voz concreta de otro idioma."""
    guardar({"voz.idioma": "en", "voz.perfil": "jarvis_en"}, config)
    assert par(config) == ("en", "jarvis_en")


def test_los_dos_a_la_vez_y_EN_CONFLICTO_levantan(config: Path) -> None:
    """>>> LA TERCERA SALIDA: AQUI NO SE ADIVINA <<<

    Si alguien manda idioma ingles Y voz española en el mismo guardado,
    los dos son deliberados y no hay forma de saber cual queria. Elegir
    uno le dejaria puesto algo que no eligio; se levanta y se le dice.
    """
    with pytest.raises(AjustesError) as exc:
        guardar({"voz.idioma": "en", "voz.perfil": "jarvis"}, config)
    dicho = str(exc.value)
    assert "juntos" in dicho


def test_un_conflicto_NO_escribe_nada(config: Path) -> None:
    """`guardar` es todo o nada, y esto no puede ser la excepcion.

    Se levanta DESPUES de validar y ANTES de mezclar, asi que un lote con
    tres ajustes buenos y este conflicto no deja los tres puestos.
    """
    with pytest.raises(AjustesError):
        guardar({"ui.tema": "hacker",
                 "voz.idioma": "en", "voz.perfil": "jarvis"}, config)
    assert par(config) == ("es", "jarvis")
    assert {a.clave: a.valor for a in catalogo(config)}["ui.tema"] == "jarvis"
