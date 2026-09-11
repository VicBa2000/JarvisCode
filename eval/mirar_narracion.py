"""Que narra Claude Code MIENTRAS trabaja, sacado de sesiones reales.

El filtro de narracion no se disena contra una idea de lo que
Claude Code dice, sino contra lo que dijo. Aqui se saca de los registros
crudos que ya hay en disco.

NARRACION = un bloque de texto SEGUIDO de una herramienta en el mismo
turno. El texto que va justo antes de `Fin` es la respuesta, no
narracion, y ese ya se locuta desde el 2026-08-25.

    python -m eval.mirar_narracion [--todas]
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

from puente.protocolo import Fin, Texto, UsoHerramienta, interpretar


def narraciones() -> list[tuple[str, str]]:
    salida: list[tuple[str, str]] = []
    fuentes = sorted(glob.glob("logs/puente/*.jsonl"))
    fuentes += sorted(glob.glob("eval/trazas_claude_code/*.jsonl"))
    for ruta in fuentes:
        pendiente: str | None = None
        for linea in Path(ruta).read_text(
                encoding="utf-8", errors="replace").splitlines():
            for evento in interpretar(linea):
                if isinstance(evento, Texto):
                    pendiente = evento.texto
                elif isinstance(evento, UsoHerramienta) and pendiente is not None:
                    salida.append((Path(ruta).name, pendiente))
                    pendiente = None
                elif isinstance(evento, Fin):
                    pendiente = None
    return salida


def main() -> int:
    todas = "--todas" in sys.argv
    muestras = narraciones()
    print(f"NARRACIONES REALES ENCONTRADAS: {len(muestras)}\n")
    for archivo, texto in (muestras if todas else muestras[:30]):
        plano = " ".join(texto.split())
        print(f"[{archivo[:26]:26s}] {plano[:160]}")
    if not todas and len(muestras) > 30:
        print(f"\n... y {len(muestras) - 30} mas (--todas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
