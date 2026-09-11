"""Reading `config/*.yaml`. Nothing else, on purpose.

WHY THIS MODULE EXISTS SEPARATELY (JarvisCode, 2026-08-21). It used to
live in `cognicion/configuracion.py`, and the fork's map marked
`cognicion/` as dead wholesale -- the planner, the prompts, the memory,
all of it belongs to a brain this fork no longer has.

That map was wrong about this file, and only reading the imports showed
it: `voz/audio.py`, `voz/perfil.py`, `voz/stt.py` and
`seguridad/auditoria.py` all pull `load_general_config` from there. The
voice layer, which is the most alive thing in the tree, was hanging off
a package listed for demolition.

So the file was split rather than deleted. What stayed here is the half
that only reads YAML and knows where `config/` is. What was left behind
-- `RoleConfig`, `RuntimeConfig`, `get_role_config`, `to_ollama_options`
-- was entirely about resolving a ROLE to a local Ollama model, which is
the one job this fork does not have any more.

La leccion, que es la de siempre cobrandose otra pieza: el mapa de lo vivo
y lo muerto es PROSA, y la prosa envejece. Antes de borrar un modulo se
mira quien lo importa, no lo que dice el documento.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class ConfigError(RuntimeError):
    """The configuration is missing or malformed."""


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"No se encontro el archivo de configuracion: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML invalido en {path}: {exc}") from exc
    return data or {}


ARCHIVO_AJUSTES = "ajustes.yaml"


def _expandir(destino: dict[str, Any], clave: str, valor: Any) -> None:
    """Mete "voz.audio.salida" en su sitio dentro del arbol."""
    partes = clave.split(".")
    nodo = destino
    for parte in partes[:-1]:
        siguiente = nodo.get(parte)
        if not isinstance(siguiente, dict):
            siguiente = {}
            nodo[parte] = siguiente
        nodo = siguiente
    nodo[partes[-1]] = valor


BASE_DIR = PROJECT_ROOT / "config" / "base"


def sembrar_base(config_dir: Path | None = None) -> str:
    """Copia la linea base a `config/` si no hay `jarvis.yaml`. TRES salidas.

    >>> POR QUE ESTO EXISTE (2026-09-05) <<<
    Lo pidio el usuario preparando el codigo abierto: quien lo instale no
    debe configurar a mano ningun YAML para empezar. Y estaba
    medido que `jarvis.yaml` es el UNICO archivo obligatorio -- sin el,
    `load_general_config` levanta --, o sea que sin esto la primera cosa
    que tendria que hacer alguien recien descargado el proyecto es copiar
    un archivo a mano. Copiar a mano es editar a mano con otro nombre.

    >>> SOLO SI NO ESTA, Y ESO NO SE NEGOCIA <<<
    Nunca pisa uno que exista. Ese archivo es la linea base MEDIDA y
    alguien puede haberlo tocado: machacarlo al arrancar seria perder
    ajustes sin decir nada, y encima en el sitio donde viven los umbrales
    de la voz. Aqui "ya hay uno" es una respuesta completa, no un caso
    raro que despachar.

    Devuelve QUE PASO y no un bool, porque son tres cosas distintas y las
    tres hay que poder contarlas: `ya_estaba` (lo normal), `sembrada` (la
    primera vez, y conviene decirlo) y `sin_base` (alguien borro
    `config/base/`, que es un arbol roto y no un arranque limpio).
    """
    import shutil

    destino = (config_dir or CONFIG_DIR) / "jarvis.yaml"
    if destino.is_file():
        return "ya_estaba"
    origen = BASE_DIR / "jarvis.yaml"
    if not origen.is_file():
        return "sin_base"
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origen, destino)
    return "sembrada"


def load_general_config(config_dir: Path | None = None) -> dict[str, Any]:
    """`jarvis.yaml` con lo que el usuario haya cambiado encima.

    >>> POR QUE LA SUPERPOSICION VIVE AQUI Y NO EN CADA LECTOR <<<
    `config/ajustes.yaml` lo escribe la consola y contiene SOLO lo
    cambiado; `jarvis.yaml` se queda intacto como la linea base medida,
    con sus 420 lineas de comentarios explicando por que cada numero es
    el que es. Reescribir ese archivo desde la UI los borraria en
    silencio, y no estan en ningun otro sitio.

    Poniendo la mezcla en esta funcion, TODO el que ya leia la config
    -- `voz/audio.py`, `voz/stt.py`, `voz/wake.py`, `voz/perfil.py` --
    recoge el cambio sin tocar una linea. La alternativa era ir uno por
    uno, y entonces el panel diria "hace falta reiniciar" sobre ajustes
    que al reiniciar seguirian sin aplicarse: la pantalla mintiendo, que
    es justo lo que este panel no puede permitirse.

    Las claves de `ajustes.yaml` son PLANAS y con puntos
    ("voz.audio.salida"), porque asi es como las nombra la UI; aqui se
    expanden al arbol que espera todo lo demas.

    UN ARCHIVO DE AJUSTES ROTO **NO SE IGNORA**: levanta. Arrancar con
    unos ajustes distintos de los que el usuario configuro, y callarselo,
    es peor que no arrancar. Es la misma regla que `zonas.yaml`.
    """
    directory = config_dir or CONFIG_DIR
    base = load_yaml(directory / "jarvis.yaml")

    encima = directory / ARCHIVO_AJUSTES
    if not encima.is_file():
        # Ausente significa "no has cambiado nada", nunca "todo por
        # defecto de otra cosa".
        return base
    propios = load_yaml(encima)
    for clave, valor in propios.items():
        if isinstance(clave, str) and "." in clave:
            _expandir(base, clave, valor)
        else:
            base[clave] = valor
    return base
