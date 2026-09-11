"""Sonda: si `--effort` hace algo, y cuanto. Contra el binario.

    python -m eval.sondas_claude_code.sonda_esfuerzo [--repeticiones 2]

>>> POR QUE HAY QUE MEDIRLO Y NO BASTA CON PONERLO <<<
`--effort` no aparece por ningun lado en `system/init` -- se miraron los
21 campos de un init real y no esta --, asi que poner el flag y darlo por
bueno seria exactamente la deuda que dejo JC-0003 con
`--permission-prompt-tool`: un flag que se cree puesto y no hace nada.

Y hay una razon concreta para desconfiar, medida el 2026-09-01:

    claude -p --effort disparate "di solo OK"
    Warning: Unknown --effort value 'disparate' - ignoring it and using
    the default effort. Valid values: low, medium, high, xhigh, max.

**Un valor invalido NO da error: se ignora.** Y en nuestro montaje ese
aviso viaja por stderr, o sea que llega como `LineaIlegible` y lo que se
ve es nada. Una errata dejaria el esfuerzo en el defecto para siempre.
Por eso `voz/esfuerzo.py` valida la lista por su cuenta.

LA MAGNITUD CONTINUA es `system/thinking_tokens`, que llega
con `estimated_tokens` acumulado por turno. Una bandera de "hizo algo"
no distinguiria un flag que mueve poco de uno que no mueve nada. Se
miran ademas los segundos y el coste, porque son lo que paga el usuario.

>>> ESTO NO ES UNA CURVA Y NO SE PUEDE LEER COMO TAL <<<
Con dos repeticiones por nivel, lo unico que se puede responder es si el
flag MUEVE la aguja o no. Si dos niveles salen parecidos, esta sonda no
dice que sean iguales: dice que no los ha separado.
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
from pathlib import Path

from puente.protocolo import Fin
from puente.sesion import Sesion

# Un acertijo cerrado: la respuesta es la misma siempre, asi que lo que
# cambie no es QUE se contesta sino cuanto se piensa. Y no usa
# herramientas, o sea que no hay nada mas que pueda mover los numeros.
ORDEN = ("Tengo tres cajas: una con solo manzanas, otra con solo naranjas "
         "y otra mezclada. Las tres etiquetas estan mal. Sacando UNA sola "
         "fruta de UNA sola caja, como las etiqueto las tres? Contesta en "
         "dos frases.")

NIVELES = (None, "low", "high", "max")


def _una(carpeta: Path, nivel: str | None) -> dict:
    """Una sesion, un turno. Los tokens salen del REGISTRO CRUDO.

    >>> Y NO DE `Sesion.eventos()`, QUE NO LOS ENTREGA <<<
    `protocolo.py` tira todo `system/*` que no sea `init` ni `api_retry`
    como "ruido de progreso", y `thinking_tokens` es uno de ellos. Se
    lee del `.jsonl` en vez de tocar produccion para medir: es la misma
    fuente contra la que se escriben los tests del puente.
    """
    extra = ("--effort", nivel) if nivel else ()
    registro = carpeta / "crudo.jsonl"
    sesion = Sesion(carpeta, modelo="sonnet", extra=extra, registro=registro)
    sesion.abrir()
    fin = None
    try:
        sesion.mandar(ORDEN)
        for evento in sesion.eventos(timeout=300):
            if isinstance(evento, Fin):
                fin = evento
                break
    finally:
        sesion.cerrar()

    pensados = 0
    if registro.is_file():
        for linea in registro.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if d.get("subtype") == "thinking_tokens":
                pensados = max(pensados, int(d.get("estimated_tokens") or 0))
    return {
        "pensados": pensados,
        "segundos": (fin.duracion_ms / 1000) if fin else 0.0,
        "coste": getattr(fin, "coste_usd", 0.0) or 0.0,
        "largo": len(fin.texto) if fin else 0,
    }


def main(argv: list[str] | None = None) -> int:
    trozos = argparse.ArgumentParser(description=__doc__)
    trozos.add_argument("--repeticiones", type=int, default=2)
    trozos.add_argument("--niveles", default="",
                        help="coma-separados; vacio = todos. `defecto` es "
                             "el control sin flag")
    args = trozos.parse_args(argv)

    niveles = NIVELES
    if args.niveles:
        pedidos = [x.strip() for x in args.niveles.split(",") if x.strip()]
        niveles = tuple(None if x == "defecto" else x for x in pedidos)

    filas: list[tuple[str, list[dict]]] = []
    with tempfile.TemporaryDirectory(prefix="sonda_esfuerzo_") as tmp:
        for nivel in niveles:
            etiqueta = nivel or "(sin flag)"
            tomas = []
            for i in range(args.repeticiones):
                print(f"-- {etiqueta} {i + 1}/{args.repeticiones} ...", flush=True)
                carpeta = Path(tmp) / f"{etiqueta.strip('()')}_{i}"
                carpeta.mkdir()
                tomas.append(_una(carpeta, nivel))
            filas.append((etiqueta, tomas))

    print(f"\n  {args.repeticiones} tomas por nivel. NO es una curva: con "
          f"estos numeros solo se puede\n  decir si el flag mueve la aguja "
          f".\n")
    print("  nivel        tokens pensados      segundos     USD      caracteres")
    for etiqueta, tomas in filas:
        p = [t["pensados"] for t in tomas]
        s = [t["segundos"] for t in tomas]
        c = sum(t["coste"] for t in tomas) / len(tomas)
        largo = statistics.mean(t["largo"] for t in tomas)
        print(f"  {etiqueta:<12} {statistics.mean(p):>7.0f} "
              f"{'(' + ', '.join(str(x) for x in p) + ')':<14} "
              f"{statistics.mean(s):>7.1f}  {c:>7.4f}  {largo:>8.0f}")

    # >>> EL VEREDICTO CUENTA SUCESOS, NO MEDIAS <<<
    # La primera pasada de esta sonda concluyo "el flag mueve la aguja"
    # con UN solo turno que penso, escondido en una media de dos. Eso es
    # exactamente lo que la regla prohibe: antes de leer un A/B hay que
    # contar cuantas veces ocurrio EL SUCESO, no cuantas ejecuciones
    # hubo. Aqui el suceso es "este turno penso algo".
    print("\n  cuantos turnos PENSARON algo (el suceso, no la media):")
    minimo = 3
    bastantes = True
    for etiqueta, tomas in filas:
        cuantos = sum(1 for t in tomas if t["pensados"] > 0)
        print(f"    {etiqueta:<12} {cuantos}/{len(tomas)}")
        if 0 < cuantos < minimo:
            bastantes = False
    print()
    if not bastantes:
        print(f"  >>> NO SE PUEDE LEER: hay un nivel con menos de {minimo} "
              f"turnos pensando.\n      Con eso la tanda no ha respondido "
              f"nada. Sube --repeticiones.")
        return 2
    por_nivel = {e: [t["pensados"] for t in ts] for e, ts in filas}
    if "(sin flag)" in por_nivel and "max" in por_nivel:
        sin = sum(1 for x in por_nivel["(sin flag)"] if x)
        top = sum(1 for x in por_nivel["max"] if x)
        if top <= sin:
            print("  >>> `max` no penso mas veces que el defecto. O el flag "
                  "no llega en esta\n      forma de invocacion, o hace falta "
                  "un turno que se lo cobre.")
            return 1
        print(f"  >>> `max` pensó en {top} de {len(por_nivel['max'])} turnos "
              f"y el defecto en {sin}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
