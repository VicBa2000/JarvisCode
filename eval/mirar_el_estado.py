"""Cuantos turnos pasan enteros diciendo DORMIDO (2026-09-04).

>>> DE DONDE SALE <<<
Lo reporto el usuario: dando la instruccion escrita, el estado seguia
diciendo DORMIDO con Jarvis ya trabajando. La causa estaba
en la lista de eventos que adoptan un turno ajeno (`voz/bucle.py`): hasta
ese dia el primero que despertaba el ciclo era `UsoHerramienta`, o sea LA
PRIMERA HERRAMIENTA. Y hay turnos que no gastan ninguna.

>>> QUE MIDE, Y POR QUE ASI <<<
Cuenta turnos reales de `logs/puente/*.jsonl`, no turnos inventados: un turno
es todo lo que llega hasta un `result`. De cada uno
mira dos cosas -- si trae algun `tool_use` y si trae algun bloque de
texto no vacio -- porque esas dos son exactamente las dos versiones de la
lista de adopcion que hay que comparar.

No es una bandera: da tambien cuanto se ADELANTA el texto a la
herramienta en los turnos que traen las dos. Un porcentaje
solo diria que el arreglo llega; el adelanto dice cuanto antes.

    .venv\\Scripts\\python.exe -m eval.mirar_el_estado

OJO AL LEERLO: la cifra habla de los registros que haya en
disco HOY, no del codigo. Si cambia la lista de `_reaccionar`, esto
sigue midiendo lo mismo -- el material -- y hay que volver a mirarlo.
"""

from __future__ import annotations

import glob
import json
import statistics
from datetime import datetime
from pathlib import Path

CARPETA = Path(__file__).resolve().parent.parent / "logs" / "puente"


def _sello(linea: dict) -> datetime | None:
    """El `timestamp` del evento, o None si no lo trae.

    Tres salidas y no dos: un `assistant` sin sello no es un
    adelanto de cero, es un adelanto que no se sabe, y se queda fuera del
    reparto en vez de tirar la mediana hacia abajo.
    """
    crudo = linea.get("timestamp")
    if not crudo:
        return None
    try:
        return datetime.fromisoformat(str(crudo).replace("Z", "+00:00"))
    except ValueError:
        return None


def _bloques(linea: dict) -> list:
    mensaje = linea.get("message") or {}
    contenido = mensaje.get("content")
    return contenido if isinstance(contenido, list) else []


def mirar(carpeta: Path = CARPETA) -> dict:
    """Recorre las sesiones de disco y devuelve el recuento."""
    turnos = sin_uso = sin_nada = sin_texto = 0
    adelantos: list[float] = []

    for ruta in sorted(glob.glob(str(carpeta / "*.jsonl"))):
        t_texto = t_uso = None
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    dato = json.loads(linea)
                except json.JSONDecodeError:
                    # Una linea ilegible no invalida la sesion entera.
                    continue

                if dato.get("type") == "assistant":
                    cuando = _sello(dato)
                    for bloque in _bloques(dato):
                        if not isinstance(bloque, dict):
                            continue
                        clase = bloque.get("type")
                        if (clase == "text"
                                and str(bloque.get("text", "")).strip()
                                and t_texto is None):
                            t_texto = cuando
                        elif clase == "tool_use" and t_uso is None:
                            t_uso = cuando

                if dato.get("type") == "result":
                    turnos += 1
                    if t_uso is None:
                        sin_uso += 1
                        if t_texto is None:
                            sin_nada += 1
                    if t_texto is None:
                        sin_texto += 1
                    if t_texto and t_uso:
                        adelantos.append((t_uso - t_texto).total_seconds())
                    t_texto = t_uso = None

    return {"turnos": turnos, "sin_uso": sin_uso, "sin_nada": sin_nada,
            "sin_texto": sin_texto, "adelantos": sorted(adelantos)}


def _porciento(parte: int, total: int) -> str:
    return f"{100 * parte / total:.0f} %" if total else "?"


def main() -> None:
    r = mirar()
    total = r["turnos"]
    if not total:
        print(f"No hay ni un turno cerrado en {CARPETA}.")
        print("Sin material no se responde nada.")
        return

    print(f"Sesiones en {CARPETA}")
    print(f"turnos con `result` .......................... {total:4d}")
    print()
    print("SI SE ADOPTA CON LA PRIMERA HERRAMIENTA (hasta el 09-04):")
    print(f"  turnos sin una sola herramienta ............ {r['sin_uso']:4d}"
          f"   ({_porciento(r['sin_uso'], total)})")
    print("  ^ estos pasaban ENTEROS diciendo DORMIDO")
    print()
    print("SI SE ADOPTA CON EL PRIMER TEXTO (hoy):")
    print(f"  turnos sin texto NI herramienta ............ {r['sin_nada']:4d}"
          f"   ({_porciento(r['sin_nada'], total)})")
    print("  ^ no dicen nada en absoluto: los adopta el `Fin`")
    print(f"  turnos sin ningun texto .................... {r['sin_texto']:4d}")

    ad = r["adelantos"]
    if ad:
        p90 = ad[int(len(ad) * 0.9)]
        print()
        print(f"En los {len(ad)} turnos con texto Y herramienta, el texto")
        print(f"  llega ANTES:  mediana {statistics.median(ad):.2f} s"
              f" | p90 {p90:.2f} s | maximo {ad[-1]:.2f} s")

    print()
    print("LO QUE ESTO **NO** MIDE, y hay que decirlo: el hueco entre el")
    print("Enter y el primer evento. Ahi no hay nada en el registro -- el")
    print("registro empieza cuando Claude Code habla --, y son 0,62 s en")
    print("caliente y 6,65 s en frio (`-m eval.mirar_el_primer_turno`).")
    print("Ese hueco lo cubre el CABEZAL, que arranca en `anuncia_turno`.")


if __name__ == "__main__":
    main()
