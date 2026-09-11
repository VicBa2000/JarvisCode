"""Que exige de verdad una instalacion LIMPIA, medido y no supuesto.

    python -m eval.mirar_la_instalacion

>>> POR QUE EXISTE (2026-09-05) <<<
Lo pregunto el usuario preparando el codigo abierto: por que seguia sin
estar listo para el release, si quien lo instale no deberia configurar a
mano ningun YAML ni nada para empezar.

Y esa pregunta no se contesta leyendo: se contesta apuntando el proyecto
a una carpeta de configuracion RECIEN COPIADA de `config/base/` y viendo
que aguanta y que revienta. La primera pasada ya dio un dato que nadie
sabia: `config/jarvis.yaml` es OBLIGATORIO -- sin el,
`load_general_config` levanta --, mientras que los otros cinco nacen
ausentes y eso significa "nada declarado". O sea que la lista de "hay que
crear a mano" tiene exactamente un archivo, y es el que se publica.

>>> LO QUE MIDE, Y POR QUE ASI <<<
Se prueba contra TRES carpetas, y las tres hacen falta:
  * VACIA, sin sembrar -- el instante antes de arrancar. Es la unica que
    ROMPE, y verlo romper es lo que dice cual es el archivo obligatorio.
  * VACIA, ya sembrada -- lo que pasa de verdad en el primer arranque,
    desde que `sembrar_base` existe (2026-09-05).
  * SOLO LA BASE -- lo que se descarga.
Sin la primera no se sabria que falta; sin la segunda la sonda seguiria
diciendo ROMPE de algo que hoy se arregla solo, que es una sonda
mintiendo; y sin la tercera, un archivo que sobra y uno que falta se
verian igual.

NO arranca Claude Code ni abre el microfono: eso cuesta dinero y
hardware, y lo que se pregunta aqui es si la CONFIGURACION basta. Lo que
si se construye de verdad es el catalogo de ajustes, que es la pantalla
desde la que un usuario nuevo lo configura todo -- si esa se cae, no hay
por donde empezar.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BASE = RAIZ / "config" / "base"

# Lo del autor, que no puede aparecer en nada de lo que se publica.
# La lista sale de `config/privado.txt` (ver `tests/privado.py`), que
# esta en `.gitignore`: escribirla aqui seria publicar justo lo que
# esta sonda existe para no publicar. Sin ese archivo, no busca nada.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.privado import terminos as _terminos

DEL_AUTOR = _terminos()


def _con(config_dir: Path) -> list[tuple[str, bool, str]]:
    """Las cuatro cosas que tienen que funcionar sin tocar un YAML."""
    import nucleo.ajustes as aj
    import nucleo.configuracion as cfg
    import nucleo.mcp as mcp
    import nucleo.proyectos as pr

    fuera = []

    def probar(nombre, f):
        try:
            fuera.append((nombre, True, str(f())[:52]))
        except Exception as exc:  # noqa: BLE001
            fuera.append((nombre, False, f"{type(exc).__name__}: {exc}"[:52]))

    probar("leer jarvis.yaml", lambda: "ok"
           if cfg.load_general_config(config_dir) else "vacio")
    probar("catalogo de ajustes", lambda: f"{len(aj.catalogo(config_dir))} ajustes")
    probar("registro de proyectos", lambda: f"{len(pr.leer(config_dir))} proyectos")
    probar("lista blanca de MCP", lambda: f"{len(mcp.leer(config_dir))} servidores")
    return fuera


def main() -> int:
    print(__doc__.splitlines()[0])
    print()

    if not BASE.is_dir():
        # El generador no viaja en el repositorio publicado, asi que
        # aqui no se puede mandar correrlo: en un clon esa orden falla.
        print(f"NO HAY BASE en {BASE}, que es la linea base de "
              f"`config/jarvis.yaml` y viaja con el repositorio. Si "
              f"falta, el clon esta incompleto.")
        return 2

    publicados = sorted(p.name for p in BASE.iterdir() if p.is_file())
    print(f"LO QUE SE PUBLICA ({len(publicados)}): {', '.join(publicados)}")

    # >>> Y SE MIRA QUE NO LLEVE NADA DEL AUTOR <<<
    # Es lo que reporto el usuario en el glosario, aplicado al archivo
    # que de verdad se descarga: un aparato o una ruta suya aqui se
    # instala en la maquina de otro.
    sucios = []
    for archivo in BASE.iterdir():
        if not archivo.is_file():
            continue
        texto = archivo.read_text(encoding="utf-8")
        for marca in DEL_AUTOR:
            if marca.lower() in texto.lower():
                sucios.append(f"{archivo.name}: {marca}")
    print(f"  datos del autor dentro: "
          f"{', '.join(sucios) if sucios else 'ninguno'}")
    print()

    with tempfile.TemporaryDirectory(prefix="instalacion_") as tmp:
        vacia = Path(tmp) / "vacia"
        vacia.mkdir()
        con_base = Path(tmp) / "con_base"
        shutil.copytree(BASE, con_base)

        # >>> Y EL CASO QUE DE VERDAD PASA: VACIA + ARRANQUE <<<
        # Desde el 2026-09-05 el arranque SIEMBRA la base si no hay
        # `jarvis.yaml`, asi que "carpeta vacia" ya no es el estado en el
        # que se queda nadie: es el estado un instante antes. Se miden
        # los tres para que la diferencia se vea -- sin el de en medio,
        # la sonda seguiria diciendo ROMPE de algo que se arregla solo.
        from nucleo.configuracion import sembrar_base

        sembrada = Path(tmp) / "sembrada"
        print(f"CARPETA VACIA + ARRANQUE  ->  sembrar_base() devolvio "
              f"'{sembrar_base(sembrada)}'")
        print()

        for titulo, carpeta in (
                ("CARPETA VACIA, SIN SEMBRAR (el instante antes)", vacia),
                ("CARPETA VACIA, YA SEMBRADA (el primer arranque)", sembrada),
                ("SOLO LA BASE (lo que descargas)", con_base)):
            print(titulo)
            for nombre, bien, detalle in _con(carpeta):
                print(f"  {'OK   ' if bien else 'ROMPE'} {nombre:24} {detalle}")
            print()

    # Y lo que un usuario nuevo SI tiene que elegir, que no es lo mismo
    # que editar: sale en la pantalla, con su boton de probar.
    import nucleo.ajustes as aj

    with tempfile.TemporaryDirectory(prefix="pendiente_") as tmp:
        con_base = Path(tmp) / "c"
        shutil.copytree(BASE, con_base)
        sin_elegir = [a.clave for a in aj.catalogo(con_base)
                      if a.valor in ("", [], None)]
    print("LO QUE QUEDA POR ELEGIR EN LA PANTALLA (no por editar):")
    for clave in sin_elegir:
        print(f"  - {clave}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
