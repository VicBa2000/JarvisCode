"""Shared test fixtures and path setup.

Las fixtures de Ollama (`llm_client`, `ollama_running`, `requires_ollama`)
se fueron el 2026-08-21 junto con `cognicion/`: aqui no hay modelo local
que levantar, y no quedaba un solo test que las pidiera. Una fixture que
nadie usa y que apunta a un modulo borrado es una trampa esperando.

El marcador `lento` cambio de significado con el fork. Antes queria decir
"llama al modelo local, tarda segundos". Ahora quiere decir **"llama a
Claude Code de verdad: es red y es dinero"**, que es una razon mas seria
para no correrlo en cada guardado. Lo que NO cambia es la regla: un
test que no necesita esa llamada no se marca, porque el marcador no se
paga en segundos, se paga en las veces que no se corre.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(autouse=True)
def _canal_de_voz_fijo(request, monkeypatch):
    """La suite mide el CODIGO, no el ajuste que tenga puesto quien la corre.

    >>> 114 ROJOS EL 2026-09-09, Y NO HABIA NADA ROTO <<<
    El usuario puso `voz.idioma: en` en el panel para probar el ingles y
    la suite se desfondo: `voz/ventana.py`, `voz/parada.py` y
    `voz/proyecto.py` resuelven sus formas con `voz.idioma.hablado()`,
    que lee `config/ajustes.yaml`. O sea que "abrete" deja de ser una
    orden -- correctamente, en ingles se dice "show yourself" -- y con
    ella se caen las 114 pruebas escritas contra el español.

    >>> LO QUE ESO SIGNIFICA, QUE ES PEOR QUE LOS 114 <<<
    La suite llevaba verde desde agosto **porque el YAML del autor decia
    `es`**. No estaba comprobando el codigo: estaba comprobando el codigo
    CON SU CONFIGURACION. Cualquiera que clone esto y prefiera el ingles
    -- que es justo a quien va dirigida la seccion inglesa del README --
    veria 114 rojos y pensaria que el proyecto esta roto. Es la regla
    en su version mas cara: una suite verde caduca en cuanto se toca
    produccion, y aqui bastaba con tocar un desplegable.

    Se fija en español porque es el idioma en que estan ESCRITAS las
    aserciones. Lo que quiera probar otro idioma lo pide explicito
    -- `interpretar(t, idioma="en")` --, que ya manda sobre esto, o se
    marca con `idioma_real` si lo que prueba es la RESOLUCION misma.
    """
    if request.node.get_closest_marker("idioma_real"):
        return
    import voz.idioma

    monkeypatch.setattr(voz.idioma, "hablado", lambda *a, **k: "es")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "lento: test de integracion contra Claude Code real (red y dinero).",
    )
    config.addinivalue_line(
        "markers",
        "necesita_modelos: necesita `modelos/` descargado (745 MB, fuera de git).",
    )
    config.addinivalue_line(
        "markers",
        "idioma_real: no fijar el canal de voz -- este test prueba la "
        "RESOLUCION del idioma, asi que necesita el `hablado` de verdad.",
    )
    # >>> LA SIEMBRA, Y AQUI PORQUE SI NO EL ORDEN DECIDE <<<
    # (2026-09-08, preparando el release.) `config/jarvis.yaml` dejo de
    # viajar en el repositorio: es la configuracion DE CADA UNO, y en un
    # clon recien descargado no existe hasta que alguien arranca Jarvis
    # una vez -- que es exactamente lo que hacen `-m puente` y
    # `-m escritorio` al abrir. Sin esto, los tests que leen la config
    # real fallaban en un clon virgen, y ademas SEGUN EL ORDEN: uno de
    # ellos siembra como efecto de lo que comprueba, asi que los que
    # corrian antes reventaban y los de despues pasaban. Un fallo
    # determinista con pinta de intermitente es peor que uno rojo.
    # NO PISA NADA: `sembrar_base` solo copia si no hay archivo, y tiene
    # sus tres salidas. Se hace aqui, en `pytest_configure`, para que
    # ocurra ANTES de coleccionar: hay guardas a nivel de modulo que
    # deciden si saltarse un archivo entero mirando la config.
    from nucleo.configuracion import sembrar_base

    sembrar_base()
