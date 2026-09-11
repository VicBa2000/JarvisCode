"""Cuanto tarda la PRIMERA orden escrita en verse en pantalla.

>>> LO REPORTO EL USUARIO, Y CON EL SINTOMA EXACTO (2026-09-03) <<<
Escribio una orden en la consola nada mas arrancar, sin sesion previa,
le dio al enter y el texto desaparecio; tardo minutos en verse reflejado
y en empezar. Lo que penso, y es lo que importa, fue que se habia
trabado o estaba roto.

QUE MIDE, y son cuatro instantes distintos que hoy se confunden en uno:

    t0  se aprieta Enter            (la caja se vacia AQUI)
    t1  vuelve el POST /turno       (hasta aqui la pagina no sabe nada)
    t2  llega `TurnoDelUsuario`     (aqui se ve por fin lo que dijiste)
    t3  llega el primer `Inicio`    (la sesion se anuncia)
    t4  llega `Fin`                 (contesto)

El hueco que duele es **t0 -> t2**: es el rato en el que la pantalla no
enseña ni lo que acabas de escribir. `puente/consola.py` llama a
`anuncia_turno` DESPUES de `asegurar_sesion()` y de `mandar()`, asi que
todo lo que tarde abrir la sesion es tiempo con la pantalla en blanco y
el texto ya borrado.

POR QUE UNA SONDA Y NO UNA LECTURA DEL CODIGO: leyendo, `abrir()` es un
`Popen` y `mandar()` es un `write`, o sea que t0->t2 "tendria" que ser
instantaneo. El usuario midio minutos con un reloj de pared. Cuando el
codigo y el usuario discrepan, gana el usuario y hay algo que el codigo
no cuenta -- aqui, todo lo que `claude` hace ANTES de aceptar el turno,
que incluye arrancar los servidores MCP de `config/mcp.yaml`.

GASTA UN TURNO DE VERDAD (red y dinero). Es la unica forma: un doble no
arranca un binario de 337 MB ni levanta un servidor MCP.

    .venv\\Scripts\\python.exe -m eval.mirar_el_primer_turno [carpeta]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PUERTO = 8799
LIMITE_ARRANQUE_S = 90.0
LIMITE_TURNO_S = 240.0

ORDEN = "Contesta unicamente la palabra: listo. No uses ninguna herramienta."


def _pide(url: str, ficha: str | None = None, cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    peticion = urllib.request.Request(url, data=datos)
    if ficha:
        peticion.add_header("X-Jarvis-Ficha", ficha)
    if datos is not None:
        peticion.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(peticion, timeout=LIMITE_TURNO_S)


def _esperar_pagina(base: str) -> str:
    """Devuelve la ficha en cuanto la consola sirve la pagina."""
    fin = time.time() + LIMITE_ARRANQUE_S
    while time.time() < fin:
        try:
            texto = _pide(base + "/").read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
            continue
        marca = re.search(r'FICHA\s*=\s*"([^"]+)"', texto)
        if marca:
            return marca.group(1)
        time.sleep(0.2)
    raise SystemExit("la consola no sirvio la pagina a tiempo")


def _escuchar(base: str, ficha: str, reloj, llegadas: list, parar) -> None:
    """Lee el SSE y apunta CUANDO llega cada clase de evento."""
    try:
        flujo = _pide(f"{base}/eventos?ficha={ficha}")
    except Exception as exc:  # noqa: BLE001
        llegadas.append((reloj(), "ERROR-SSE", str(exc)))
        return
    for cruda in flujo:
        if parar.is_set():
            return
        linea = cruda.decode("utf-8", "replace").strip()
        if not linea.startswith("data:"):
            continue
        try:
            evento = json.loads(linea[5:].strip())
        except json.JSONDecodeError:
            continue
        llegadas.append((reloj(), evento.get("clase", "?"), ""))
        if evento.get("clase") == "Fin":
            parar.set()
            return


def _segundo_turno(base: str, ficha: str) -> float:
    """Lo mismo con la sesion YA abierta. Aisla el coste de la PRIMERA.

    Sin esto no se puede decir que parte del hueco es abrir la sesion y
    que parte es el POST siendo sincrono: las dos se ven igual desde el
    navegador.
    """
    t0 = time.perf_counter()
    _pide(base + "/turno", ficha, {"texto": ORDEN}).read()
    return time.perf_counter() - t0


def main() -> int:
    carpeta = sys.argv[1] if len(sys.argv) > 1 else str(RAIZ / "logs")
    base = f"http://127.0.0.1:{PUERTO}"
    python = RAIZ / ".venv" / "Scripts" / "python.exe"

    print(f"Carpeta de la sesion: {carpeta}")
    print("Levantando el puente (sin navegador)...")
    arranque = time.perf_counter()
    puente = subprocess.Popen(
        [str(python), "-m", "puente", carpeta,
         "--sin-navegador", "--puerto", str(PUERTO)],
        cwd=str(RAIZ), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    salida: list[str] = []
    threading.Thread(
        target=lambda: [salida.append(l.rstrip()) for l in puente.stdout],
        daemon=True).start()

    try:
        ficha = _esperar_pagina(base)
        listo = time.perf_counter() - arranque
        print(f"  consola en pie en {listo:.2f} s\n")

        llegadas: list[tuple[float, str, str]] = []
        parar = threading.Event()
        t0 = time.perf_counter()
        reloj = lambda: time.perf_counter() - t0  # noqa: E731
        threading.Thread(target=_escuchar,
                         args=(base, ficha, reloj, llegadas, parar),
                         daemon=True).start()
        time.sleep(0.5)  # que el SSE este suscrito antes de mandar

        print(f"t0  Enter. La caja se vacia AQUI. Orden: {ORDEN!r}")
        t0 = time.perf_counter()
        respuesta = _pide(base + "/turno", ficha, {"texto": ORDEN})
        t1 = time.perf_counter() - t0
        print(f"t1  vuelve POST /turno .......... {t1:8.2f} s  "
              f"{respuesta.read().decode('utf-8', 'replace')}")

        fin = time.time() + LIMITE_TURNO_S
        while not parar.is_set() and time.time() < fin:
            time.sleep(0.2)

        print()
        segunda = _segundo_turno(base, ficha)
        primera = {}
        for cuando, clase, extra in llegadas:
            primera.setdefault(clase, cuando)
            if extra:
                print(f"    !! {clase}: {extra}")

        print("  LA LINEA DE TIEMPO, desde que apretaste Enter:")
        for clase in ("Aviso", "TurnoDelUsuario", "Inicio", "UsoHerramienta",
                      "Texto", "Fin"):
            if clase in primera:
                print(f"    {clase:<18} {primera[clase]:8.2f} s")

        ciego = primera.get("TurnoDelUsuario")
        print()
        print(f"  EL SEGUNDO TURNO, con la sesion YA viva:")
        print(f"    vuelve POST /turno ......... {segunda:8.2f} s")
        print(f"    o sea que la PRIMERA vez cuesta {t1 - segunda:.2f} s de mas")
        print()
        # >>> LO QUE SE MIDE DESDE EL ARREGLO (2026-09-03) <<<
        # Ya no es "cuanto tarda en verse la linea": el texto se queda en
        # la caja y el boton dice MANDANDO, asi que esperar no se
        # confunde con estar roto. Lo que importa ahora es si llega
        # ALGUNA señal antes que la linea, y cuanto antes.
        aviso = primera.get("Aviso")
        if ciego is None:
            print("  >>> `TurnoDelUsuario` NO LLEGO. La pantalla no enseño "
                  "nunca lo que se escribio.")
        else:
            print(f"  >>> LA LINEA DE LO QUE DIJISTE tarda {ciego:.2f} s "
                  f"({t1:.2f} s de POST bloqueado).")
        if aviso is None:
            print("  >>> Y NO LLEGO NINGUN `Aviso`: durante esa espera la "
                  "pantalla no dice que esta abriendo la sesion.")
        else:
            print(f"  >>> EL ARRANQUE LO DICE A LOS {aviso:.2f} s, o sea "
                  f"{(ciego or 0) - aviso:.2f} s ANTES de la linea.")
            print("      Ese es el hueco que antes estaba mudo.")
        return 0
    finally:
        parar_todo = getattr(puente, "terminate", None)
        if parar_todo:
            puente.terminate()
            try:
                puente.wait(timeout=15)
            except subprocess.TimeoutExpired:
                puente.kill()
        print("\n  --- lo que dijo el puente por consola ---")
        for linea in salida:
            if linea.strip():
                # La consola de Windows es cp1252 y lo que sale del puente
                # es UTF-8: sin esto la sonda muere imprimiendo su propio
                # resultado, que es la forma mas tonta de perder una
                # medicion que ya estaba hecha.
                print("   ", linea.encode("ascii", "replace").decode("ascii"))


if __name__ == "__main__":
    raise SystemExit(main())
