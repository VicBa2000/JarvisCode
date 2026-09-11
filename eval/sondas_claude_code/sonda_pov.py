"""Sonda: un POV de Claude se sentiria VIDEO, o diapositivas?

    python -m eval.sondas_claude_code.sonda_pov

>>> LA PREGUNTA, DEL USUARIO (2026-09-02) <<<
Lo que pidio es ver el POV de Claude, como una pelicula en primera
persona para que se sienta vivo, al estilo del Jarvis de Iron Man: un
mini visor, un video en miniatura.

`sonda_en_vivo` ya contesto lo primero: **con `--include-partial-messages`
el contenido de un `Write` llega en 103 trozos repartidos en 7,1 s**, o
sea que ver escribirse un documento es real y no una animacion nuestra.
Lo que aquella NO contesto es lo que decide si esto merece la pena:

    ¿CUANTO RATO DEL TURNO HAY ALGO MOVIENDOSE?

Un visor que se mueve el 90 % del tiempo es una transmision. Uno que se
mueve a rafagas con huecos de cuatro segundos es una diapositiva con
animacion, y encima promete lo que no cumple -- que es peor que no
tenerlo, porque el usuario se queda mirando una pantalla congelada
creyendo que se colgo.

Asi que aqui se miden HUECOS, no trozos (magnitud continua):
  * el reparto de los intervalos entre linea y linea;
  * cuanto del reloj del turno esta "vivo", con un umbral explicito;
  * el hueco MAS LARGO, que es el que se ve;
  * y por bloque: cuanto dura escribirse cada documento.

Ademas se comprueba una cosa que cambia el diseño y que no se puede
suponer: **si la salida de un `Bash` llega en trozos o de golpe**. Si
llega de golpe, "ver la terminal escupiendo lineas" no existe y habria
que inventarlo.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import tempfile
import threading
import time
from pathlib import Path

MODELO = "sonnet"

# Un turno con las cuatro cosas que un POV tendria que enseñar: pensar,
# escribir un documento largo, correr una orden y leer un archivo. Largo
# a proposito: un turno de una sola herramienta no dice nada de los
# huecos, que es lo que se viene a medir.
ORDEN = (
    "Haz esto sin preguntarme nada: 1) escribe un archivo notas.md con "
    "un resumen de 15 lineas sobre por que un asistente de voz necesita "
    "una pantalla; 2) ejecuta `dir` para listar la carpeta; 3) lee "
    "notas.md y dime en una frase cuantas lineas tiene."
)

VIVO_MS = 300
"""Cuanto puede pasar sin que llegue nada y seguir sintiendose vivo.

No es un numero medido: es el umbral con el que se LEE la medicion, y
por eso va escrito y no escondido. 300 ms es aproximadamente el punto en
el que una pantalla quieta deja de parecer que esta trabajando. Los
huecos crudos se imprimen igual, para que se pueda releer con otro.
"""


def _correr(carpeta: Path, destino: Path) -> dict:
    orden = [
        "claude", "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--model", MODELO,
        "--permission-mode", "acceptEdits",
        "--permission-prompt-tool", "stdio",
        "--include-partial-messages",
    ]
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

    # Cada linea con SU instante. Es lo unico que hace falta para los
    # huecos, y es lo que le faltaba a `sonda_en_vivo`.
    lineas: list[dict] = []
    # >>> LA CLAVE LLEVA EL MENSAJE, Y NO SOLO EL INDICE <<<
    # `index` REINICIA en cada mensaje del asistente, y un turno con tres
    # herramientas trae tres mensajes. La primera version de esta sonda
    # indexaba solo por `index`, asi que el bloque del `Write` -- el que
    # se venia a medir -- lo machacaba el `Read` del mensaje siguiente y
    # la tabla salia con dos bloques diminutos. No dio ningun error: dio
    # una medicion tranquilizadora y falsa.
    bloques: dict[tuple, dict] = {}
    mensaje_n = 0
    herramientas: dict[str, str] = {}
    resultados: list[dict] = []
    bytes_totales = 0

    with destino.open("w", encoding="utf-8", newline="\n") as salida:
        for cruda in proceso.stdout:
            if not cruda.strip():
                continue
            ahora = time.time() - t0
            salida.write(cruda if cruda.endswith("\n") else cruda + "\n")
            bytes_totales += len(cruda.encode("utf-8"))
            try:
                m = json.loads(cruda)
            except json.JSONDecodeError:
                continue

            tipo = str(m.get("type"))
            apunte = {"t": round(ahora, 3), "tipo": tipo, "que": "", "car": 0}

            if tipo == "stream_event":
                ev = m.get("event") or {}
                clase = str(ev.get("type"))
                if clase == "message_start":
                    mensaje_n += 1
                indice = (mensaje_n, ev.get("index"))
                if clase == "content_block_start":
                    bloque = (ev.get("content_block") or {})
                    bloques[indice] = {
                        "clase": str(bloque.get("type")),
                        "nombre": str(bloque.get("name") or ""),
                        "desde": ahora, "hasta": ahora, "car": 0,
                        "trozos": 0, "tam": [],
                    }
                    apunte["que"] = f"start:{bloque.get('type')}"
                elif clase == "content_block_delta":
                    delta = ev.get("delta") or {}
                    trozo = (delta.get("text") or delta.get("partial_json")
                             or delta.get("thinking") or "")
                    apunte["que"] = str(delta.get("type"))
                    apunte["car"] = len(trozo)
                    b = bloques.get(indice)
                    if b is not None:
                        b["hasta"] = ahora
                        b["car"] += len(trozo)
                        b["trozos"] += 1
                        b["tam"].append(len(trozo))
                elif clase == "content_block_stop":
                    apunte["que"] = "stop"
                    if indice in bloques:
                        bloques[indice]["hasta"] = ahora
                else:
                    apunte["que"] = clase
            elif tipo == "assistant":
                for bloque in (m.get("message") or {}).get("content") or []:
                    if bloque.get("type") == "tool_use":
                        herramientas[str(bloque.get("id"))] = str(bloque.get("name"))
                        apunte["que"] = f"tool_use:{bloque.get('name')}"
            elif tipo == "user":
                for bloque in (m.get("message") or {}).get("content") or []:
                    if bloque.get("type") != "tool_result":
                        continue
                    cual = herramientas.get(str(bloque.get("tool_use_id")), "?")
                    contenido = bloque.get("content")
                    texto = (contenido if isinstance(contenido, str)
                             else json.dumps(contenido, ensure_ascii=False))
                    apunte["que"] = f"tool_result:{cual}"
                    apunte["car"] = len(texto)
                    resultados.append({"cual": cual, "t": round(ahora, 2),
                                       "car": len(texto)})
            elif tipo == "control_request":
                peticion = m.get("request", {})
                enviar({"type": "control_response",
                        "response": {"subtype": "success",
                                     "request_id": m.get("request_id"),
                                     "response": {
                                         "behavior": "allow",
                                         "updatedInput": peticion.get("input", {})}}})

            lineas.append(apunte)
            if tipo == "result":
                break

    proceso.terminate()
    try:
        proceso.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proceso.kill()

    # Los tiempos se guardan aparte: el `.jsonl` crudo no los lleva -- son
    # nuestros, no del binario -- y sin ellos releer esta medicion
    # obligaria a pagar otro turno.
    (destino.with_suffix(".tiempos.json")).write_text(
        json.dumps(lineas, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"lineas": lineas, "bloques": bloques, "resultados": resultados,
            "bytes": bytes_totales, "turno": lineas[-1]["t"] if lineas else 0.0}


def _informe(d: dict) -> None:
    lineas = d["lineas"]
    turno = d["turno"]
    huecos = [round(b["t"] - a["t"], 3)
              for a, b in zip(lineas, lineas[1:])]

    print(f"\n=== EL TURNO ===")
    print(f"  duracion .................... {turno:.2f} s")
    print(f"  lineas del flujo ............ {len(lineas)}")
    print(f"  peso del crudo .............. {d['bytes']/1024:.1f} KB")

    print(f"\n=== LOS HUECOS (lo que decide si es video o diapositivas) ===")
    if huecos:
        huecos_ord = sorted(huecos)
        n = len(huecos_ord)
        print(f"  entre linea y linea: mediana {huecos_ord[n//2]*1000:.0f} ms"
              f"   p90 {huecos_ord[int(n*0.9)]*1000:.0f} ms"
              f"   maximo {max(huecos)*1000:.0f} ms")
        # >>> EL NUMERO QUE DECIDE ES EL CONGELON MAS LARGO <<<
        # Un porcentaje de "tiempo vivo" suena a medida y no lo es: lo
        # que hace que una pantalla parezca colgada no es el promedio,
        # es el hueco mas largo que el ojo aguanta mirando. Si el mayor
        # es de medio segundo, no se nota ni uno; si hay uno de seis, ese
        # solo se carga la sensacion de transmision aunque el resto vaya
        # fino.
        largos = [h for h in huecos if h > VIVO_MS / 1000]
        print(f"  >>> el congelon MAS LARGO: {max(huecos)*1000:.0f} ms <<<")
        print(f"  huecos por encima de {VIVO_MS} ms: {len(largos)} de "
              f"{len(huecos)}   suman {sum(largos):.2f} s")
        if largos:
            print(f"     los cinco mayores: "
                  + ", ".join(f"{h:.2f} s" for h in sorted(largos, reverse=True)[:5]))
        print(f"  llegadas por segundo de turno: {len(lineas)/turno:.1f}")

    print(f"\n=== POR BLOQUE: que se puede ver, y cuanto dura ===")
    for indice, b in sorted(d["bloques"].items()):
        dura = b["hasta"] - b["desde"]
        etiqueta = b["clase"] + (f" ({b['nombre']})" if b["nombre"] else "")
        tam = sorted(b["tam"])
        mediano = tam[len(tam) // 2] if tam else 0
        print(f"  msg{indice[0]}/{indice[1]}  {etiqueta:<24} {b['trozos']:>4} trozos "
              f"{b['car']:>6} car  trozo~{mediano:>3} car  {dura:>6.2f} s"
              + ("   <- SE VE ESCRIBIRSE" if dura >= 1.0 else ""))

    print(f"\n=== LOS RESULTADOS DE HERRAMIENTA (llegan de golpe?) ===")
    for r in d["resultados"]:
        print(f"  {r['cual']:<12} a los {r['t']:>6.2f} s   "
              f"{r['car']:>6} car   en 1 trozo")
    print("  (si aqui pone siempre '1 trozo', la salida de una herramienta")
    print("   NO se puede ver aparecer: llega entera o no llega)")


def main(argv: list[str] | None = None) -> int:
    trozos = argparse.ArgumentParser(description=__doc__)
    trozos.add_argument("--salida", default="logs/sondas")
    args = trozos.parse_args(argv)
    destino = Path(args.salida)
    destino.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pov_") as tmp:
        crudo = destino / "pov.jsonl"
        print("corriendo un turno con cuatro cosas dentro...")
        d = _correr(Path(tmp), crudo)
        print(f"  crudo en {crudo}")
    _informe(d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
