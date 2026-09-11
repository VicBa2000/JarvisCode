"""Que pregunta Claude Code EN PROSA al cerrar el turno, y que se puede
numerar de ello. Sacado de sesiones reales.

El extractor de opciones no se disena contra una idea de como
pregunta Claude Code, sino contra como pregunto. Aqui se saca de los
registros crudos que ya hay en disco.

PREGUNTA ABIERTA = el TEXTO del `result` termina preguntando, segun
`voz.resumen.pregunta_final` (la regla de la cola tras el ultimo signo
de cierre, ya medida el 2026-08-25). No es `AskUserQuestion`: esa llega
por el canal de control, ya se escala a Telegram desde JC-0016 y se
contesta con `Sesion.responder`. Esta CIERRA el turno, y contestarla es
un turno nuevo.

    python -m eval.mirar_preguntas [--todas]

Lo que hay que mirar de la tabla que imprime:

  disyuntiva / si_no   se pueden mandar numeradas al movil.
  dudosa               hay un `o` y NO se sabe si separa opciones. Se
                       trata como ninguna (direccion segura) pero se
                       cuenta aparte: si este numero crece, hay material
                       para afinar el extractor.
  ninguna              no hay nada que enumerar. Se avisa y se contesta
                       en la consola o hablando.
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

from voz.resumen import (FORMA_DISYUNTIVA, FORMA_DUDOSA, FORMA_NINGUNA,
                         FORMA_SI_NO, opciones_de_pregunta, pregunta_final)

ORDEN = (FORMA_DISYUNTIVA, FORMA_SI_NO, FORMA_DUDOSA, FORMA_NINGUNA)


def respuestas() -> list[str]:
    """El texto final de cada turno que cerro bien, de los logs crudos."""
    salida: list[str] = []
    fuentes = sorted(glob.glob("logs/puente/*.jsonl"))
    fuentes += sorted(glob.glob("eval/trazas_claude_code/*.jsonl"))
    for ruta in fuentes:
        for linea in Path(ruta).read_text(
                encoding="utf-8", errors="replace").splitlines():
            linea = linea.strip()
            if not linea:
                continue
            try:
                dato = json.loads(linea)
            except Exception:  # noqa: BLE001 - hay lineas truncadas
                continue
            if not isinstance(dato, dict):
                continue
            if dato.get("type") != "result" or dato.get("subtype") != "success":
                continue
            texto = (dato.get("result") or "").strip()
            if texto:
                salida.append(texto)
    return salida


def main() -> int:
    todas = "--todas" in sys.argv
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - da igual, es una sonda
        pass

    turnos = respuestas()
    if not turnos:
        print("No hay registros crudos en logs/puente/. Nada que mirar.")
        return 1

    vistas: dict[str, str] = {}
    for texto in turnos:
        pregunta = pregunta_final(texto)
        if pregunta:
            vistas.setdefault(pregunta, texto)

    print(f"TURNOS QUE CERRARON BIEN:      {len(turnos)}")
    porcentaje = len(vistas) / len(turnos) * 100
    print(f"TERMINAN PREGUNTANDO (unicas): {len(vistas)}  "
          f"({porcentaje:.0f} % de los turnos)\n")

    por_forma: dict[str, list[tuple[str, tuple[str, ...]]]] = {
        f: [] for f in ORDEN}
    for pregunta in vistas:
        opciones = opciones_de_pregunta(pregunta)
        por_forma[opciones.forma].append((pregunta, opciones.etiquetas))

    contestables = (len(por_forma[FORMA_DISYUNTIVA])
                    + len(por_forma[FORMA_SI_NO]))
    print("  forma        cuantas   se contesta desde el movil")
    for forma in ORDEN:
        marca = "SI" if forma in (FORMA_DISYUNTIVA, FORMA_SI_NO) else "no"
        print(f"  {forma:<12} {len(por_forma[forma]):>5}          {marca}")
    print(f"\n  CONTESTABLES: {contestables}/{len(vistas)} "
          f"({contestables / len(vistas) * 100:.0f} %)\n")

    for forma in ORDEN:
        if not por_forma[forma]:
            continue
        if forma in (FORMA_NINGUNA, FORMA_DUDOSA) and not todas:
            print(f"== {forma.upper()} ({len(por_forma[forma])}) "
                  f"-- con --todas se listan ==\n")
            continue
        print(f"== {forma.upper()} ({len(por_forma[forma])}) ==")
        for pregunta, etiquetas in por_forma[forma]:
            print(f"  P: {pregunta[:150]}")
            for i, etiqueta in enumerate(etiquetas, start=1):
                print(f"     {i}. {etiqueta}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
