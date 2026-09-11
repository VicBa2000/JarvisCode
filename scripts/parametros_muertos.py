"""Busca parametros declarados y NUNCA LEIDOS en el cuerpo de su funcion.

Uso:
    .venv\\Scripts\\python.exe scripts\\parametros_muertos.py

POR QUE EXISTE ESTE SCRIPT, que es lo unico que justifica conservarlo:
el 2026-08-19 `cognicion/planner.py::_build_user_prompt` acepto un
parametro `un_paso` y no lo leyo en ninguna rama. El flag viajaba entero
desde `config/jarvis.yaml` -> `Bucle` -> `Planner.plan()` -> hasta aqui,
y moria en la ultima capa. Consecuencia: el modo "un paso a la vez" se
midio DOS VECES con A/B de 4 rondas cada uno, y los dos brazos enviaban
al modelo exactamente el mismo prompt. Se llegaron a escribir cifras
explicando el comportamiento de una instruccion que no existia.

Nadie avisa de esta forma de fallo. El interprete no, porque la firma es
valida. Los tests del llamante tampoco, porque el llamante pasa el
argumento correctamente. Una revision humana menos aun, porque la firma
se lee bien y el docstring puede describir con todo detalle un
comportamiento que el cuerpo no implementa.

Este barrido tarda segundos. Correrlo despues de añadir un parametro que
atraviese varias capas cuesta menos que una sola tanda de GPU.

COMO LEER LA SALIDA: la mayoria de hallazgos son deliberados y llevan
prefijo `_` (los despachadores de `accion/verificador.py` comparten
firma, las puertas `AprobacionDenegada`/`AprobacionAutomatica` ignoran la
peticion por diseño). **Un parametro SIN prefijo `_` que no se lee es el
sospechoso**; en el barrido del 19 hubo 24 hallazgos, 23 justificados y
uno real.
"""

from __future__ import annotations

import ast
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PAQUETES = ["cognicion", "accion", "seguridad", "voz", "diagnostico", "eval"]
IGNORADOS = {"self", "cls"}


def parametros_muertos(arbol: ast.AST) -> list[tuple[int, str, str]]:
    """Devuelve (linea, funcion, parametro) por cada parametro no leido."""
    hallazgos = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = nodo.args
        declarados = [
            a.arg
            for a in (args.posonlyargs + args.args + args.kwonlyargs)
            if a.arg not in IGNORADOS
        ]
        if not declarados:
            continue
        leidos = {
            n.id
            for hijo in nodo.body
            for n in ast.walk(hijo)
            if isinstance(n, ast.Name)
        }
        for nombre in declarados:
            if nombre not in leidos:
                hallazgos.append((nodo.lineno, nodo.name, nombre))
    return hallazgos


def main() -> int:
    sospechosos = 0
    total = 0
    for paquete in PAQUETES:
        for py in sorted((RAIZ / paquete).rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            arbol = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for linea, funcion, param in parametros_muertos(arbol):
                total += 1
                # El prefijo `_` es la forma de decir "lo se, es a proposito".
                marca = "     " if param.startswith("_") else "  <-- "
                if not param.startswith("_"):
                    sospechosos += 1
                ruta = py.relative_to(RAIZ)
                print(f"{ruta}:{linea}  {funcion}(...)  {param}{marca}")

    print(f"\n{total} parametros no leidos, {sospechosos} SIN prefijo `_`.")
    if sospechosos:
        print(
            "Los marcados con <-- no declaran que sean intencionales. "
            "Comprobar si el cuerpo deberia usarlos."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
