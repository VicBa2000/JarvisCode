"""Lo que NO puede colarse en lo que se publica -- leido de fuera del repo.

>>> POR QUE ESTA LISTA NO ESTA ESCRITA AQUI <<<
(2026-09-09.) Habia tres copias de ella -- `test_config_base.py`,
`test_nada_harcodeado.py` y `eval/mirar_la_instalacion.py` -- y las tres
enumeraban, por su nombre, los proyectos del autor, sus aparatos de audio
y su apellido. O sea que **los tests escritos para impedir que sus datos
viajaran eran los que los publicaban**. Funcionaban; el precio era el
dato que protegian.

Ahora los terminos viven en `config/privado.txt`, que esta en
`.gitignore` y por tanto se queda en el disco de quien desarrolla. El
formato es una linea por termino, `#` para comentarios.

>>> Y TIENE TRES SALIDAS, NO DOS <<<
    hay archivo y tiene terminos  -> se comprueba de verdad
    hay archivo y esta vacio      -> es una lista vacia, y se dice
    no hay archivo                -> AQUI NO SE PUEDE SABER, y se salta
La tercera es un clon: alli no hay nada del autor que buscar, porque el
resultado que estos tests protegen ya se cumplio. Colapsarla contra
"falla" pondria en rojo la instalacion de alguien que no ha hecho nada
mal; colapsarla contra "pasa" seria un guardia decorativo en la maquina
donde SI hace falta.
"""

from __future__ import annotations

from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
ARCHIVO = RAIZ / "config" / "privado.txt"


def terminos() -> tuple[str, ...]:
    """Los terminos a buscar, o vacio si el archivo no esta."""
    if not ARCHIVO.is_file():
        return ()
    fuera = []
    for linea in ARCHIVO.read_text(encoding="utf-8").splitlines():
        linea = linea.split("#", 1)[0].strip()
        if linea:
            fuera.append(linea)
    return tuple(fuera)


HAY_LISTA = bool(terminos())

necesita_la_lista = pytest.mark.skipif(
    not HAY_LISTA,
    reason=(f"no hay {ARCHIVO.relative_to(RAIZ)}, que es donde vive la lista "
            f"de terminos personales. Esta en `.gitignore` a proposito: solo "
            f"existe en la maquina de quien desarrolla, y en un clon no hay "
            f"nada suyo que buscar. Para activarlo, una linea por termino."),
)


def cuela(texto: str) -> list[str]:
    """Que terminos de la lista aparecen en `texto`. Sin distinguir caso."""
    bajo = texto.lower()
    return [t for t in terminos() if t.lower() in bajo]
