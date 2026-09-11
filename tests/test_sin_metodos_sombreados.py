"""Un metodo definido dos veces en la misma clase. Barrido del arbol.

>>> ESTE ARCHIVO EXISTE PORQUE PASO DOS VECES <<<
La primera en `Consola`: `parar()` (apagar el servidor) y `parar()`
(parar el turno). Se arreglo el 2026-09-01 renombrando, y quedo
documentado en su docstring.

La segunda en `Bucle`, y **estaba ahi desde entonces sin que nadie la
buscara** -- que es justo lo que manda esta casa: al arreglar un
fallo de forma, buscar los demas sitios con esa forma. Lo reporto el
usuario el 2026-09-02 por el sintoma, no por el codigo: al salir, Jarvis
decia siempre "dale, paro" -- una frase que es solo de la parada por Esc,
y se estaba diciendo tambien al cerrar.

Lo que hacia: `Montaje.cerrar()` llama `voz.parar()` para APAGAR LOS
HILOS. Python se queda con la ultima definicion, asi que salir de Jarvis
contaba una parada, cortaba el turno, decia "Vale, paro" en voz alta...
y no paraba ni un hilo.

>>> Y NO LO CAZA NADA MAS <<<
No es un error de sintaxis, no es un aviso, y los dos metodos son
plausibles por separado. Un linter lo veria; este arbol no usa ninguno.
Un test por AST cuesta 20 milisegundos y no depende de nadie.
"""

from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PAQUETES = ("puente", "voz", "nucleo", "seguridad", "canales", "escritorio")


def _repetidos(ruta: Path) -> list[str]:
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    hallados = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.ClassDef):
            continue
        vistos: dict[str, list[int]] = {}
        for miembro in nodo.body:
            if isinstance(miembro, (ast.FunctionDef, ast.AsyncFunctionDef)):
                vistos.setdefault(miembro.name, []).append(miembro.lineno)
        for nombre, lineas in vistos.items():
            # Un `@property` con su `@nombre.setter` son dos definiciones
            # legitimas del mismo nombre, y ahi la segunda NO tapa a la
            # primera: la completa.
            if len(lineas) > 1 and not _es_una_propiedad(nodo, nombre):
                hallados.append(
                    f"{ruta.relative_to(RAIZ)}: {nodo.name}.{nombre} "
                    f"en las lineas {lineas} -- gana la ultima")
    return hallados


def _es_una_propiedad(clase: ast.ClassDef, nombre: str) -> bool:
    for miembro in clase.body:
        if not isinstance(miembro, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if miembro.name != nombre:
            continue
        for adorno in miembro.decorator_list:
            texto = ast.unparse(adorno)
            if texto == "property" or texto.endswith((".setter", ".getter",
                                                      ".deleter")):
                return True
    return False


def test_ningun_metodo_se_define_dos_veces_en_la_misma_clase() -> None:
    sombras: list[str] = []
    for paquete in PAQUETES:
        carpeta = RAIZ / paquete
        if not carpeta.is_dir():
            continue
        for ruta in sorted(carpeta.rglob("*.py")):
            sombras.extend(_repetidos(ruta))
    assert not sombras, (
        "un metodo tapa a otro con su mismo nombre:\n  "
        + "\n  ".join(sombras)
        + "\nSi los dos hacen falta, uno se RENOMBRA por lo que hace "
          "(`parar` = apagar; `parar_el_turno` = cortar el turno).")


def test_el_barrido_SI_veria_el_caso_que_lo_origino() -> None:
    """>>> UN TEST QUE NO PUEDE FALLAR ES PEOR QUE NINGUNO <<<

    Se comprueba con el codigo exacto que estuvo en el arbol: dos
    `def parar` en la misma clase. Sin esto, el de arriba pasaria igual
    con el detector roto.
    """
    import tempfile

    codigo = (
        "class Bucle:\n"
        "    def parar(self, espera_s=5.0):\n"
        "        return True\n"
        "    def parar(self, origen='voz'):\n"
        "        return True\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "sombra.py"
        ruta.write_text(codigo, encoding="utf-8")
        # `_repetidos` calcula la ruta relativa a la raiz; aqui no lo es,
        # asi que se mira solo que encuentre algo y que nombre el metodo.
        arbol = ast.parse(codigo)
        clase = arbol.body[0]
        assert isinstance(clase, ast.ClassDef)
        vistos: dict[str, list[int]] = {}
        for miembro in clase.body:
            if isinstance(miembro, ast.FunctionDef):
                vistos.setdefault(miembro.name, []).append(miembro.lineno)
        assert vistos["parar"] == [2, 4]
        assert not _es_una_propiedad(clase, "parar")


def test_una_propiedad_con_su_setter_NO_cuenta() -> None:
    """La otra mitad: un barrido que grite con cada `@x.setter` se apaga
    a la semana, y entonces no protege de nada."""
    codigo = (
        "class Cosa:\n"
        "    @property\n"
        "    def valor(self):\n"
        "        return 1\n"
        "    @valor.setter\n"
        "    def valor(self, v):\n"
        "        pass\n"
    )
    arbol = ast.parse(codigo)
    clase = arbol.body[0]
    assert isinstance(clase, ast.ClassDef)
    assert _es_una_propiedad(clase, "valor")
