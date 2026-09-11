"""Sonda JC-0003 (2): dos turnos en el MISMO proceso, y una denegacion.
Mide si la sesion sigue viva tras el primer `result` y si el contexto
persiste sin --resume.
"""
import json, subprocess, sys, threading, time

cwd = sys.argv[1]
turnos = ["Crea un archivo llamado segundo.txt con el texto: turno uno",
          "Sin usar ninguna herramienta, dime en una frase que archivo acabas de crear."]

cmd = ["claude", "-p", "--input-format", "stream-json",
       "--output-format", "stream-json", "--verbose", "--model", "sonnet",
       "--permission-prompt-tool", "stdio"]

t0 = time.time()
p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)

def log(m): print(f"[{time.time()-t0:6.2f}] {m}", flush=True)
def enviar(o):
    p.stdin.write(json.dumps(o) + "\n"); p.stdin.flush()
def usuario(t):
    log(f">>> USUARIO: {t}")
    enviar({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": t}]}})

threading.Thread(target=lambda: [log("ERR " + l.rstrip()) for l in p.stderr], daemon=True).start()

i = 0
usuario(turnos[0])
for linea in p.stdout:
    linea = linea.strip()
    if not linea: continue
    try: msg = json.loads(linea)
    except Exception: continue
    t = msg.get("type")
    if t == "control_request" and msg["request"].get("subtype") == "can_use_tool":
        r = msg["request"]
        log(f"*** PUERTA: {r['tool_name']} | desc={r.get('description')!r}")
        # PRIMER turno: se DENIEGA a proposito, para ver que hace.
        enviar({"type": "control_response", "response": {
            "subtype": "success", "request_id": msg["request_id"],
            "response": {"behavior": "deny",
                         "message": "El usuario dijo que no."}}})
        log("--- respondido DENY")
    elif t == "assistant":
        for b in msg["message"]["content"]:
            if b["type"] == "text" and b["text"].strip():
                log(f"<<< TEXTO: {b['text'][:300]}")
            elif b["type"] == "tool_use":
                log(f"<<< HERRAMIENTA: {b['name']}")
    elif t == "result":
        log(f"=== RESULT turno {i}: subtype={msg.get('subtype')} "
            f"is_error={msg.get('is_error')} num_turns={msg.get('num_turns')} "
            f"session={msg.get('session_id')}")
        log(f"    result={msg.get('result','')[:300]!r}")
        i += 1
        if i < len(turnos):
            log("    (el proceso SIGUE VIVO, mando el segundo turno)")
            usuario(turnos[i])
        else:
            break

p.stdin.close()
try: p.wait(timeout=10)
except Exception: p.kill()
log(f"fin, exit={p.returncode}")
