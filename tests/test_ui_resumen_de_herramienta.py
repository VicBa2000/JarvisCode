"""El renglon de una herramienta en el registro: corto y CIERTO.

>>> DE DONDE SALE (2026-09-02, pregunta del usuario) <<<
La pregunta del usuario fue si el registro de transmision y esa ventana
no son "lo mismo" en cuanto a lo que se supone que hace cada una.

Se midio en vez de opinar (`-m eval.mirar_el_solape`, 47 sesiones
reales): **56 % de solape**, pero el 39 % del registro -- 212 puertas
entre otras cosas -- no cabe en un visor de un solo plano, asi que no
sobra ninguno de los dos. Lo que SI sobraba era la FORMA: de los 187 KB
de letra de herramienta que pintaba el registro, **71 KB eran JSON
crudo** recortado a 400 caracteres. Ahora el renglon dice lo factual --
`notas.md · 1468 car` -- y el JSON queda a un clic.

>>> Y ESTO SE PRUEBA CON NODE, NO LEYENDO EL ARCHIVO <<<
La regla vive en el JS de la pagina. Un test que buscara cadenas en el
HTML comprobaria que el codigo esta escrito, no que hace lo que dice --
y lo que aqui se rompe es justo el QUE dice: la primera version resumia
un `Grep` con la CARPETA en vez del patron, porque recorria una lista de
campos en orden y la ruta iba antes. Eso no se ve leyendo, se ve
ejecutando.
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
CONSOLA = RAIZ / "puente" / "consola.html"

# Las formas REALES, sacadas de las trazas y de los `system/init` del
# binario. No son inventadas: `PowerShell` esta porque en Windows es la
# que elige el modelo, y `mcp__*` porque JC-0015 las dejo entrar.
CASOS = [
    ({"herramienta": "Write",
      "entrada": {"file_path": "C:\\proyectos\\p\\notas.md",
                  "content": "a" * 1468}},
     "notas.md · 1468 car"),
    ({"herramienta": "Edit",
      "entrada": {"file_path": "/x/voz/bucle.py", "old_string": "a",
                  "new_string": "b" * 240}},
     "bucle.py · 240 car"),
    ({"herramienta": "Read",
      "entrada": {"file_path": "C:\\proyectos\\faro\\notas_de_avance.md"}},
     "notas_de_avance.md"),
    ({"herramienta": "PowerShell",
      "entrada": {"command": "Remove-Item temporal.txt"}},
     "Remove-Item temporal.txt"),
    # >>> EL QUE LO ORIGINO <<< Lleva `pattern` Y `path`, y con una lista
    # recorrida en orden salia "voz" -- la carpeta -- en vez de lo que se
    # busca. Un resumen que nombra otra cosa es peor que el JSON.
    ({"herramienta": "Grep",
      "entrada": {"pattern": "SeguidorDeTarea", "path": "/x/voz"}},
     "SeguidorDeTarea"),
    ({"herramienta": "NotebookEdit",
      "entrada": {"notebook_path": "C:\\a\\analisis.ipynb",
                  "new_source": "x" * 80}},
     "analisis.ipynb · 80 car"),
    # Una herramienta que no conocemos pero cuya entrada SI se reconoce.
    ({"herramienta": "mcp__x__raro", "entrada": {"file_path": "/a/b/c.txt"}},
     "c.txt"),
    # >>> Y LAS DOS QUE DEVUELVEN VACIO A PROPOSITO <<<
    # Tres salidas y no dos: si no se reconoce nada, NO se inventa un
    # resumen. El renglon se queda como estaba, abierto y con su JSON.
    # Esconder el dato detras de un resumen vacio seria perder
    # informacion para que quede bonito.
    ({"herramienta": "TodoWrite", "entrada": {"todos": [1, 2, 3]}}, ""),
    ({"herramienta": "mcp__blender__get_scene_info", "entrada": {}}, ""),
]


def _js_de_la_pagina() -> str:
    texto = CONSOLA.read_text(encoding="utf-8")
    return "\n".join(re.findall(r"<script>(.*?)</script>", texto, re.DOTALL))


def test_el_resumen_dice_lo_que_distingue_a_cada_herramienta(tmp_path) -> None:
    if subprocess.run(["node", "--version"],
                      capture_output=True).returncode != 0:
        pytest.skip("no hay node para ejecutar el JS de la pagina")

    js = _js_de_la_pagina()
    # Los dos trozos que hacen falta, tal cual estan en la pagina. Si
    # alguien los mueve o los renombra, esto falla -- y esta bien que
    # falle: es la señal de que la regla cambio de sitio.
    for marca in ("const DONDE_TRABAJA", "function pintaCabezal",
                  "// >>> QUE CAMPO DESCRIBE", "function resumeEntrada"):
        assert marca in js, f"la pagina ya no tiene {marca!r}"
    trozo = (js[js.index("const DONDE_TRABAJA"):js.index("function pintaCabezal")]
             + "\n"
             + js[js.index("// >>> QUE CAMPO DESCRIBE"):js.index("function resumeEntrada")])

    guion = tmp_path / "probar.js"
    guion.write_text(
        trozo + "\n" + textwrap.dedent("""
        const casos = JSON.parse(process.argv[2]);
        console.log(JSON.stringify(casos.map(c => resumenDeUso(c))));
        """), encoding="utf-8")

    salida = subprocess.run(
        ["node", str(guion), json.dumps([c for c, _ in CASOS])],
        capture_output=True, text=True, encoding="utf-8")
    assert salida.returncode == 0, salida.stderr
    salieron = json.loads(salida.stdout)

    fallos = []
    for (caso, esperado), salio in zip(CASOS, salieron):
        if salio != esperado:
            fallos.append(f"{caso['herramienta']}: {salio!r} != {esperado!r}")
    assert not fallos, "el resumen no dice lo que debe:\n  " + "\n  ".join(fallos)


def test_el_JSON_no_se_pierde_solo_se_pliega() -> None:
    """>>> ES UN CAMBIO DE FORMA, NO UN BORRADO <<<

    El registro es el REGISTRO: lo que deja de estar aqui no esta en
    ningun otro sitio una vez el visor pasa al plano siguiente. Por eso
    la entrada cruda sigue viajando entera al `<details>` y lo unico que
    cambia es que nace cerrado cuando hay un resumen que leer.
    """
    js = _js_de_la_pagina()
    assert 'JSON.stringify(e.entrada).slice(0, 400), resumenDeUso(e)' in js, (
        "el cuerpo crudo ya no llega al renglon: eso no es plegarlo, es "
        "perderlo")
    assert 'det.open = !resumen &&' in js, (
        "sin resumen tiene que seguir naciendo abierto: un renglon sin "
        "nada que leer plegado no dice nada")
    assert '.linea .detalle.conResumen > summary { display: list-item;' in js \
        or '.detalle.conResumen > summary' in CONSOLA.read_text(encoding="utf-8"), (
        "el resumen se escribe y no se ve: el CSS esconde todos los "
        "summary del registro")
