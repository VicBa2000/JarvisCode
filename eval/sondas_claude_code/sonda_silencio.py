"""Sonda JC-0003 (3): la tercera salida. Llega la puerta y NO se contesta.
Pregunta: ¿la sesion espera indefinidamente, o se rinde sola (y con que)?
"""
import json, subprocess, sys, threading, time

cwd = sys.argv[1]
espera = int(sys.argv[2])

p = subprocess.Popen(["claude", "-p", "--input-format", "stream-json",
                      "--output-format", "stream-json", "--verbose",
                      "--model", "haiku", "--permission-prompt-tool", "stdio"],
                     cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}] {m}", flush=True)
threading.Thread(target=lambda: [log("ERR " + l.rstrip()) for l in p.stderr], daemon=True).start()

p.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
    {"type": "text", "text": "Crea un archivo tercero.txt con el texto: hola"}]}}) + "\n")
p.stdin.flush()

puerta_en = None
def leer():
    global puerta_en
    for l in p.stdout:
        l = l.strip()
        if not l: continue
        try: m = json.loads(l)
        except Exception: continue
        t = m.get("type")
        if t == "control_request":
            puerta_en = time.time()
            log(f"*** PUERTA ABIERTA, y NO voy a contestar: {m['request'].get('tool_name')}")
        elif t == "result":
            log(f"=== RESULT: subtype={m.get('subtype')} is_error={m.get('is_error')}")
        elif t == "system":
            log(f"    system/{m.get('subtype')}")

hilo = threading.Thread(target=leer, daemon=True)
hilo.start()
hilo.join(timeout=espera)
log(f"--- {espera}s despues: proceso vivo={p.poll() is None}, "
    f"puerta abierta hace={None if not puerta_en else round(time.time()-puerta_en,1)}s")
p.kill()
