"""Sonda JC-0003: conduce una sesion de Claude Code por stream-json y
registra EN CRUDO los dos sentidos. No decide nada: solo mira.

Uso: python conductor.py <cwd> <prompt> [--permitir] [--modo MODO]
"""
import json, os, subprocess, sys, threading, time

cwd = sys.argv[1]
prompt = sys.argv[2]
permitir = "--permitir" in sys.argv
modo = "default"
if "--modo" in sys.argv:
    modo = sys.argv[sys.argv.index("--modo") + 1]

cmd = ["claude", "-p", "--input-format", "stream-json",
       "--output-format", "stream-json", "--verbose",
       "--model", "sonnet", "--permission-mode", modo]
if "--extra" in sys.argv:
    cmd += sys.argv[sys.argv.index("--extra") + 1:]

t0 = time.time()
p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, encoding="utf-8", bufsize=1)

def enviar(obj):
    linea = json.dumps(obj)
    print(f"[{time.time()-t0:6.2f}] >>> {linea[:400]}", flush=True)
    p.stdin.write(linea + "\n")
    p.stdin.flush()

def leer_stderr():
    for l in p.stderr:
        print(f"[{time.time()-t0:6.2f}] ERR {l.rstrip()}", flush=True)

threading.Thread(target=leer_stderr, daemon=True).start()

enviar({"type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}})

for linea in p.stdout:
    linea = linea.strip()
    if not linea:
        continue
    print(f"[{time.time()-t0:6.2f}] <<< {linea[:1500]}", flush=True)
    try:
        msg = json.loads(linea)
    except Exception:
        continue
    if msg.get("type") == "control_request":
        req = msg.get("request", {})
        print(f"[{time.time()-t0:6.2f}] *** PETICION DE CONTROL: "
              f"subtype={req.get('subtype')} ***", flush=True)
        if permitir:
            enviar({"type": "control_response",
                    "response": {"subtype": "success",
                                 "request_id": msg.get("request_id"),
                                 "response": {"behavior": "allow",
                                              "updatedInput": req.get("input", {})}}})
        else:
            enviar({"type": "control_response",
                    "response": {"subtype": "success",
                                 "request_id": msg.get("request_id"),
                                 "response": {"behavior": "deny",
                                              "message": "el usuario no ha contestado"}}})
    if msg.get("type") == "result":
        break

p.stdin.close()
try:
    p.wait(timeout=10)
except Exception:
    p.kill()
print(f"[{time.time()-t0:6.2f}] fin, exit={p.returncode}")
