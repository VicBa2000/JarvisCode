"""Cuanto se habla, y que se pierde por el camino. Turnos reales.

    python -m eval.mirar_respuestas [--peores N]

>>> PARA QUE SIRVE ESTO <<<
Es la linea base del preambulo (`voz/preambulo.py`): el cerebro escribe
para una PANTALLA porque nadie le ha dicho otra cosa, y desde que JC-0004
quedo revocado ("quiero que diga siempre todo el texto") esa prosa para
pantalla se locuta ENTERA. Antes de decirle nada al modelo hay que saber
cuanto dura hoy lo que dice, con los turnos que ya estan en disco y no
con una respuesta imaginada.

Se mide lo que sale de `voz.resumen.para_un_oido`, que es exactamente lo
que recibe el TTS. No el texto crudo: los bloques de codigo ya se van
enteros ahi, y contarlos seria inflar el problema.

>>> SE MIDEN LOS DOS MODOS, Y SE DICE CUAL ESTA VIVO <<<
JC-0004 se revoco de palabra ("quiero que diga siempre todo el texto"),
pero `voz.resumir` es un interruptor del PANEL y el usuario lo puede
tener puesto -- lo tenia el 2026-09-01. Medir solo `limite=None` seria
medir la prosa que describe el proyecto en vez del archivo en disco, que
es exactamente lo que no se puede hacer. Asi que se imprimen las dos
columnas y se marca la que corresponde a `config/ajustes.yaml`.

>>> LOS SEGUNDOS SON DERIVADOS, NO MEDIDOS. NO SE CITAN COMO BANCO <<<
`CARACTERES_POR_SEGUNDO` sale de UNA sola pareja documentada en
`voz/resumen.py`: 2035 caracteres = ~145 segundos hablando. Es un orden
de magnitud, no una curva, y con `piper-tts` sin instalar en el `.venv`
no se puede medir aqui. Lo que si es exacto es el recuento de
caracteres. Cuando haya banco de TTS, este numero se sustituye.

LAS DOS PATOLOGIAS QUE SE CUENTAN APARTE, porque no son "largo":

  tabla al oido    `sin_markdown` quita cercos, negritas y enlaces, pero
                   NO quita las tablas. Una tabla markdown se locuta con
                   sus barras y sus guiones, y eso no se entiende por un
                   altavoz. Se cuenta cuantas respuestas llevan una.
  solo codigo      la respuesta era codigo y nada mas. El usuario oye
                   "te lo deje en la consola" y ni una palabra de que
                   hizo. Es correcto y es poquisimo, pero si sube quiere
                   decir que el modelo esta contestando en bloques.
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys

from eval.mirar_preguntas import respuestas
from nucleo.ajustes import valor_de
from voz.resumen import LIMITE_HABLADO, para_un_oido

# Ver el aviso de arriba: derivado de 2035 caracteres = ~145 s.
CARACTERES_POR_SEGUNDO = 14.0

# Una fila de tabla markdown: empieza y acaba en barra, con barras dentro.
FILA_DE_TABLA = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


def segundos(caracteres: int) -> float:
    return caracteres / CARACTERES_POR_SEGUNDO


def _medir(textos: list[str], limite: int | None) -> dict:
    largos: list[int] = []
    con_tabla = solo_codigo = mudas = 0
    peores: list[tuple[int, str]] = []
    for texto in textos:
        resumen = para_un_oido(texto, limite=limite)
        hablado = resumen.hablado
        largos.append(len(hablado))
        if not hablado:
            mudas += 1
        if FILA_DE_TABLA.search(texto) and "|" in hablado:
            con_tabla += 1
        peores.append((len(hablado), texto))
    largos.sort()
    return {"largos": largos, "tabla": con_tabla, "mudas": mudas,
            "peores": sorted(peores, key=lambda p: -p[0])}


def _columna(datos: dict, n: int) -> list[str]:
    largos = datos["largos"]
    filas = []
    for etiqueta, valor in (
        ("mediana", statistics.median(largos)),
        ("p90", largos[min(n - 1, int(n * 0.9))]),
        ("maximo", largos[-1]),
    ):
        filas.append(f"{etiqueta:<9}{valor:>8.0f} car {segundos(valor):>6.0f} s")
    total = sum(largos)
    filas.append(f"{'TOTAL':<9}{total:>8} car {segundos(total) / 60:>6.0f} min")
    for tope in (30, 60, 120):
        cuantas = sum(1 for x in largos if segundos(x) > tope)
        filas.append(f"pasa de {tope:>3} s      {cuantas:>4}/{n}")
    filas.append(f"tabla al oido    {datos['tabla']:>4}/{n}")
    filas.append(f"mudas del todo   {datos['mudas']:>4}/{n}")
    return filas


def main(argv: list[str] | None = None) -> int:
    trozos = argparse.ArgumentParser(description=__doc__)
    trozos.add_argument("--peores", type=int, default=5,
                        help="cuantas de las mas largas se listan")
    args = trozos.parse_args(argv)

    textos = respuestas()
    if not textos:
        print("No hay ni una respuesta en logs/puente/ ni en las trazas.")
        return 1
    n = len(textos)

    resumiendo = bool(valor_de("voz.resumir", False))
    entero = _medir(textos, None)
    corto = _medir(textos, LIMITE_HABLADO)

    print(f"\n  {n} respuestas reales de logs/puente/ y "
          f"eval/trazas_claude_code/")
    print(f"  `voz.resumir` en config/ajustes.yaml: "
          f"{'ENCENDIDO' if resumiendo else 'apagado'}\n")
    vivo_a = "" if resumiendo else "   <-- VIVO"
    vivo_b = "   <-- VIVO" if resumiendo else ""
    print(f"    {'ENTERA (limite=None)' + vivo_a:<34}"
          f"{'RESUMIDA (limite=' + str(LIMITE_HABLADO) + ')' + vivo_b}")
    for izq, der in zip(_columna(entero, n), _columna(corto, n)):
        print(f"    {izq:<34}{der}")

    datos = corto if resumiendo else entero
    print(f"\n  LAS {args.peores} MAS LARGAS DEL MODO VIVO:")
    for largo, texto in datos["peores"][:args.peores]:
        cabeza = " ".join(texto.split())[:100]
        print(f"    {largo:>5} car / {segundos(largo):>4.0f} s  {cabeza}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
