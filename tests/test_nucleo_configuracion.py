"""Lo que sobrevive de `test_configuracion.py` tras el fork.

El original probaba sobre todo la resolucion de ROLES a modelos locales
de Ollama (`get_role_config`, `to_ollama_options`, techos de contexto,
`razonamiento_interno`). Aqui no hay roles ni modelos locales, asi que
esos tests se fueron con el codigo que probaban.

Queda esto: que el YAML general se lee, y que un archivo que falta se
nota en vez de colar un diccionario vacio.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nucleo.configuracion import (
    CONFIG_DIR,
    PROJECT_ROOT,
    ConfigError,
    load_general_config,
    load_yaml,
)


def test_la_config_general_se_carga_de_verdad():
    datos = load_general_config()
    assert isinstance(datos, dict) and datos
    # El bloque de voz es el que sigue vivo y el que fija dispositivos
    # por nombre, medidos, no adivinados.
    assert "voz" in datos


def test_un_archivo_que_falta_no_se_convierte_en_un_diccionario_vacio(
    tmp_path: Path,
):
    """Silencio y ausencia no son lo mismo.

    Devolver `{}` haria que todo cogiera valores por defecto sin que
    nadie se entere, que es la forma callada de fallar.
    """
    with pytest.raises(ConfigError):
        load_general_config(config_dir=tmp_path)


def test_un_yaml_roto_se_queja_en_vez_de_tragarselo(tmp_path: Path):
    roto = tmp_path / "jarvis.yaml"
    roto.write_text("voz: [sin cerrar\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_yaml(roto)


def test_las_rutas_apuntan_a_donde_creemos():
    assert (PROJECT_ROOT / "config").resolve() == CONFIG_DIR.resolve()
    assert (CONFIG_DIR / "jarvis.yaml").exists()
