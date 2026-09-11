"""Sonda: se puede VER trabajar a Claude Code, o solo el resultado?

    python -m eval.sondas_claude_code.sonda_en_vivo

>>> LA PREGUNTA, TAL COMO LA HIZO EL USUARIO (2026-09-02) <<<
La pregunta fue si hay forma de VER a Jarvis leer un documento palabra
por palabra, verlo escribir uno mientras crece, y ver que archivos nuevos
genera: como si se estuviera viendo una transmision en primera persona.

Son TRES cosas distintas y no tienen la misma respuesta, asi que lo que
esta sonda hace es separarlas midiendo, en vez de contestarlas de memoria:

  1. LO QUE ESCRIBE  -- el contenido de un `Write` lo redacta el modelo,
     token a token. Si el transporte lo entrega en trozos, se puede ver
     crecer de verdad. Si llega entero de golpe, cualquier "crecimiento"
     que pintemos seria una animacion inventada, o sea un mock en
     produccion.
  2. LO QUE LEE      -- un `Read` no lo redacta nadie: es una lectura de
     disco que la herramienta hace de un tirón. Aqui se mide cuanto tarda
     y cuantos trozos trae, que es lo unico que decide si "verlo leer"
     existe o hay que inventarlo.
  3. LO QUE DEJA     -- eso ya se ve (`puente/producido.py`), pero al
     TERMINAR la herramienta. Aqui se mide cuanto tiempo pasa entre que
     se sabe que va a escribir y que el archivo existe: ese hueco es
     todo lo que un panel en vivo podria rellenar.

Y la variable es UNA: `--include-partial-messages`, que hoy NO se usa
(`puente/sesion.py` no lo pone). JC-0003 lo dejo anotado como "para que
el TTS empiece antes de que acabe el turno" y nunca se midio. Se corren
las dos, con y sin, sobre la MISMA orden.

MAGNITUD CONTINUA: no se mira una bandera de "llegan trozos",
se cuentan los trozos, sus bytes y los segundos que abarcan. Un flag que
entrega el texto en dos pedazos no sirve para lo que se pregunta, y una
bandera diria que si.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import threading
import time
from pathlib import Path

MODELO = "sonnet"

# Pide las tres cosas de una: escribir algo largo (para que haya trozos
# que contar), leerlo (para ver si leer se puede mirar) y contestar.
ORDEN = (
    "Escribe un archivo llamado poema.md con un poema de 12 versos sobre "
    "el mar, sin preguntarme nada. Luego leelo con Read y dime en una "
    "sola frase cuantos versos tiene."
)


def _correr(carpeta: Path, con_trozos: bool, destino: Path) -> dict:
    orden = [
        "claude", "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--model", MODELO,
        "--permission-mode", "acceptEdits",
        "--permission-prompt-tool", "stdio",
    ]
    if con_trozos:
        orden.append("--include-partial-messages")

    proceso = subprocess.Popen(
        orden, cwd=str(carpeta),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1,
    )
    threading.Thread(target=lambda: [None for _ in proceso.stderr],
                     daemon=True).start()

    def enviar(objeto: dict) -> None:
        proceso.stdin.write(json.dumps(objeto) + "\n")
        proceso.stdin.flush()

    t0 = time.time()
    enviar({"type": "user",
            "message": {"role": "user",
                        "content": [{"type": "text", "text": ORDEN}]}})

    # Lo que se cuenta. `_json` son los trozos del INPUT de una
    # herramienta, o sea el contenido del documento redactandose.
    cuenta: dict = {
        "lineas": 0, "tipos": {}, "eventos": {},
        "texto_trozos": 0, "texto_bytes": 0,
        "json_trozos": 0, "json_bytes": 0,
        "json_desde": None, "json_hasta": None,
        "uso_write_en": None, "resultado_write_en": None,
        "uso_read_en": None, "resultado_read_en": None,
        "read_bytes": 0, "read_trozos": 0,
        "fin_en": None, "archivo_en": None,
    }
    usos: dict[str, str] = {}
    archivo = carpeta / "poema.md"
    vigila = threading.Event()

    def mirar_el_disco() -> None:
        """Cuando APARECE el archivo en disco, medido aparte del flujo."""
        while not vigila.wait(0.02):
            if archivo.is_file():
                cuenta["archivo_en"] = round(time.time() - t0, 2)
                return

    hilo = threading.Thread(target=mirar_el_disco, daemon=True)
    hilo.start()

    with destino.open("w", encoding="utf-8", newline="\n") as salida:
        for linea in proceso.stdout:
            if not linea.strip():
                continue
            salida.write(linea if linea.endswith("\n") else linea + "\n")
            ahora = round(time.time() - t0, 2)
            cuenta["lineas"] += 1
            try:
                m = json.loads(linea)
            except json.JSONDecodeError:
                continue
            tipo = str(m.get("type"))
            cuenta["tipos"][tipo] = cuenta["tipos"].get(tipo, 0) + 1

            if tipo == "stream_event":
                ev = (m.get("event") or {})
                clase = str(ev.get("type"))
                cuenta["eventos"][clase] = cuenta["eventos"].get(clase, 0) + 1
                delta = (ev.get("delta") or {})
                if delta.get("type") == "text_delta":
                    cuenta["texto_trozos"] += 1
                    cuenta["texto_bytes"] += len(delta.get("text") or "")
                if delta.get("type") == "input_json_delta":
                    trozo = delta.get("partial_json") or ""
                    cuenta["json_trozos"] += 1
                    cuenta["json_bytes"] += len(trozo)
                    if cuenta["json_desde"] is None:
                        cuenta["json_desde"] = ahora
                    cuenta["json_hasta"] = ahora

            if tipo == "assistant":
                for bloque in (m.get("message") or {}).get("content") or []:
                    if bloque.get("type") != "tool_use":
                        continue
                    usos[str(bloque.get("id"))] = str(bloque.get("name"))
                    if bloque.get("name") == "Write":
                        cuenta["uso_write_en"] = ahora
                    if bloque.get("name") == "Read":
                        cuenta["uso_read_en"] = ahora

            if tipo == "user":
                for bloque in (m.get("message") or {}).get("content") or []:
                    if bloque.get("type") != "tool_result":
                        continue
                    cual = usos.get(str(bloque.get("tool_use_id")), "")
                    if cual == "Write":
                        cuenta["resultado_write_en"] = ahora
                    if cual == "Read":
                        cuenta["resultado_read_en"] = ahora
                        contenido = bloque.get("content")
                        texto = (contenido if isinstance(contenido, str)
                                 else json.dumps(contenido))
                        cuenta["read_bytes"] = len(texto)
                        cuenta["read_trozos"] = 1

            if tipo == "control_request":
                peticion = m.get("request", {})
                enviar({"type": "control_response",
                        "response": {"subtype": "success",
                                     "request_id": m.get("request_id"),
                                     "response": {
                                         "behavior": "allow",
                                         "updatedInput": peticion.get("input", {})}}})
            if tipo == "result":
                cuenta["fin_en"] = ahora
                break

    vigila.set()
    proceso.terminate()
    try:
        proceso.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proceso.kill()
    cuenta["existe"] = archivo.is_file()
    cuenta["tamano"] = archivo.stat().st_size if archivo.is_file() else 0
    return cuenta


def _tabla(nombre: str, c: dict) -> None:
    print(f"\n--- {nombre} " + "-" * (58 - len(nombre)))
    print(f"  lineas del flujo ............ {c['lineas']}")
    print(f"  tipos ....................... "
          + ", ".join(f"{k}:{v}" for k, v in sorted(c["tipos"].items())))
    if c["eventos"]:
        print(f"  stream_event ................ "
              + ", ".join(f"{k}:{v}" for k, v in sorted(c["eventos"].items())))
    print(f"  trozos de TEXTO ............. {c['texto_trozos']} "
          f"({c['texto_bytes']} car)")
    print(f"  trozos del INPUT de una herr. {c['json_trozos']} "
          f"({c['json_bytes']} car)")
    if c["json_trozos"]:
        print(f"     repartidos en ............ "
              f"{c['json_desde']}s -> {c['json_hasta']}s  "
              f"({round((c['json_hasta'] or 0) - (c['json_desde'] or 0), 2)} s)")
    print(f"  Write: se anuncia en ........ {c['uso_write_en']}s")
    print(f"         resultado en ......... {c['resultado_write_en']}s")
    print(f"         archivo EN DISCO en .. {c['archivo_en']}s  "
          f"({c['tamano']} bytes)")
    print(f"  Read:  se anuncia en ........ {c['uso_read_en']}s")
    print(f"         resultado en ......... {c['resultado_read_en']}s  "
          f"en {c['read_trozos']} trozo(s), {c['read_bytes']} car")
    print(f"  turno cerrado en ............ {c['fin_en']}s")


def main(argv: list[str] | None = None) -> int:
    trozos = argparse.ArgumentParser(description=__doc__)
    trozos.add_argument("--salida", default="logs/sondas")
    args = trozos.parse_args(argv)

    destino = Path(args.salida)
    destino.mkdir(parents=True, exist_ok=True)

    resultados = {}
    for con_trozos in (False, True):
        nombre = "CON --include-partial-messages" if con_trozos else "SIN el flag (lo de hoy)"
        with tempfile.TemporaryDirectory(prefix="en_vivo_") as tmp:
            print(f"\ncorriendo: {nombre} ...")
            crudo = destino / (f"en_vivo_{'con' if con_trozos else 'sin'}.jsonl")
            resultados[nombre] = _correr(Path(tmp), con_trozos, crudo)
            print(f"  crudo en {crudo}")

    for nombre, c in resultados.items():
        _tabla(nombre, c)

    print("\n>>> LO QUE HAY QUE LEER DE AQUI <<<")
    print("  * si `input_json_delta` trae MUCHOS trozos repartidos en")
    print("    segundos, el documento se puede ver crecer DE VERDAD;")
    print("  * el `Read` trae su contenido en UN trozo: 'verle leer' no")
    print("    existe en el transporte, habria que inventarlo;")
    print("  * el hueco entre que se anuncia el Write y el archivo esta")
    print("    en disco es todo lo que un panel en vivo puede rellenar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
