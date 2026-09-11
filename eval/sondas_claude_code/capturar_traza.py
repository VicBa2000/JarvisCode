"""Captura una traza REAL de Claude Code en `stream-json`, cruda.

Existe por la regla de este proyecto: una sonda que construye su propia
entrada mide la sonda. El parser del puente se escribe contra ESTO, no
contra JSON inventado a mano.

Guarda las lineas TAL CUAL salen, sin tocar ni un byte, en un `.jsonl`.
Lo unico que decide es como contestar a las puertas que lleguen.

Uso:
    python capturar_traza.py <cwd> <salida.jsonl> <permitir|denegar> <prompt>

OJO: `permitir` ejecuta de verdad. Usar un directorio desechable.
"""
import json
import subprocess
import sys
import threading
import time

MODELO = "sonnet"


def capturar(cwd: str, destino: str, decision: str, prompt: str) -> int:
    orden = [
        "claude", "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--model", MODELO,
        "--permission-mode", "default",
        "--permission-prompt-tool", "stdio",
    ]
    proceso = subprocess.Popen(
        orden, cwd=cwd,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1,
    )
    t0 = time.time()
    errores: list[str] = []
    threading.Thread(
        target=lambda: errores.extend(l.rstrip() for l in proceso.stderr),
        daemon=True,
    ).start()

    def enviar(objeto: dict) -> None:
        proceso.stdin.write(json.dumps(objeto) + "\n")
        proceso.stdin.flush()

    enviar({"type": "user", "message": {"role": "user",
                                        "content": [{"type": "text", "text": prompt}]}})

    n_puertas = 0
    with open(destino, "w", encoding="utf-8", newline="\n") as salida:
        for linea in proceso.stdout:
            if not linea.strip():
                continue
            salida.write(linea if linea.endswith("\n") else linea + "\n")
            salida.flush()
            try:
                mensaje = json.loads(linea)
            except json.JSONDecodeError:
                print(f"  [no es JSON, se guarda igual] {linea[:80]!r}")
                continue
            tipo = mensaje.get("type")
            if tipo == "control_request":
                peticion = mensaje.get("request", {})
                n_puertas += 1
                print(f"  [{time.time()-t0:5.1f}s] puerta -> "
                      f"{peticion.get('tool_name')} ({decision})")
                respuesta = ({"behavior": "allow",
                              "updatedInput": peticion.get("input", {})}
                             if decision == "permitir" else
                             {"behavior": "deny",
                              "message": "El usuario dijo que no."})
                enviar({"type": "control_response",
                        "response": {"subtype": "success",
                                     "request_id": mensaje.get("request_id"),
                                     "response": respuesta}})
            elif tipo == "result":
                print(f"  [{time.time()-t0:5.1f}s] result: "
                      f"{mensaje.get('subtype')} / {mensaje.get('duration_ms')} ms")
                break

    proceso.stdin.close()
    try:
        proceso.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proceso.kill()
    if errores:
        print("  stderr:", " | ".join(errores[:3]))
    print(f"  guardado en {destino} ({n_puertas} puertas)")
    return proceso.returncode or 0


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(capturar(sys.argv[1], sys.argv[2], sys.argv[3],
                              " ".join(sys.argv[4:])))
