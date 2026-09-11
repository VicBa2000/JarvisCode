"""Sonda: COMO se le entrega a Claude Code la respuesta a una pregunta?

    .venv\\Scripts\\python.exe -m eval.sondas_claude_code.sonda_pregunta <carpeta>

>>> POR QUE HACE FALTA MEDIR ESTO <<<
JC-0003 midio que `AskUserQuestion` LLEGA por el canal de control. Lo que
NO midio es como se contesta, y hoy el puente contesta con un `allow` a
secas y `updatedInput: {}` -- o sea que permite la herramienta y **no le
dice al modelo que se eligio**. Desde fuera parece que funciona: el turno
sigue y el modelo contesta algo. Es exactamente la clase de fallo que
este proyecto persigue.

La hipotesis a comprobar es que la eleccion viaja en `updatedInput`, en
un campo `answers` que empareja el ENUNCIADO con la ETIQUETA de la opcion
elegida. Puede ser que si, puede ser que el nombre sea otro, y puede ser
que el modelo lo ignore. Las tres se distinguen mirando si el modelo
REPITE la eleccion despues.

TRES SALIDAS, NO DOS:
    la sabe        el modelo nombra la opcion elegida
    no la sabe     sigue adelante sin ella, o se la inventa
    no se sabe     no vuelve a mencionarla y no se puede afirmar nada

Se prueban DOS formas en la misma sesion, para poder compararlas:
  1. `allow` + `updatedInput.answers`
  2. `deny` + `message` con la respuesta escrita en prosa
La segunda es la de reserva: JC-0003 ya midio que el `message` de un
`deny` llega al modelo y lo tiene en cuenta.

CUESTA DINERO: son llamadas de verdad.
"""

import json
import subprocess
import sys
import threading
import time

carpeta = sys.argv[1] if len(sys.argv) > 1 else "."
ELECCION = "Minusculas"

PROMPT = (
    "Necesito que me preguntes una cosa antes de seguir. Usa la herramienta "
    "AskUserQuestion para preguntarme si prefiero que los archivos se "
    "renombren en Mayusculas o en Minusculas (dos opciones, exactamente esas "
    "etiquetas). Cuando tengas mi respuesta, NO renombres nada: dime en una "
    "sola frase que opcion elegi."
)

cmd = ["claude", "-p", "--input-format", "stream-json",
       "--output-format", "stream-json", "--verbose", "--model", "sonnet",
       "--permission-mode", "default", "--permission-prompt-tool", "stdio"]

t0 = time.time()
proceso = subprocess.Popen(cmd, cwd=carpeta, stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, encoding="utf-8", errors="replace",
                           bufsize=1)


def log(mensaje: str) -> None:
    print(f"[{time.time() - t0:6.2f}] {mensaje}", flush=True)


def enviar(objeto: dict) -> None:
    proceso.stdin.write(json.dumps(objeto) + "\n")
    proceso.stdin.flush()


threading.Thread(
    target=lambda: [log("ERR " + l.rstrip()) for l in proceso.stderr],
    daemon=True).start()

log(">>> TURNO 1: se contesta con allow + updatedInput.answers")
enviar({"type": "user", "message": {"role": "user",
                                    "content": [{"type": "text", "text": PROMPT}]}})

forma = "answers"
respuestas = {}
turnos = 0

for linea in proceso.stdout:
    linea = linea.strip()
    if not linea:
        continue
    try:
        mensaje = json.loads(linea)
    except Exception:
        continue
    tipo = mensaje.get("type")

    if tipo == "control_request":
        peticion = mensaje.get("request") or {}
        entrada = dict(peticion.get("input") or {})
        if not peticion.get("requires_user_interaction"):
            log(f"*** PUERTA normal: {peticion.get('tool_name')} -> deny")
            enviar({"type": "control_response", "response": {
                "subtype": "success", "request_id": mensaje["request_id"],
                "response": {"behavior": "deny",
                             "message": "la sonda no ejecuta nada"}}})
            continue

        enunciados = [q.get("question") for q in entrada.get("questions", [])]
        etiquetas = [[o.get("label") for o in q.get("options", [])]
                     for q in entrada.get("questions", [])]
        log(f"*** PREGUNTA: {enunciados} opciones={etiquetas}")

        if forma == "answers":
            # La hipotesis: la eleccion va emparejada con el ENUNCIADO.
            contestacion = {q.get("question"): ELECCION
                            for q in entrada.get("questions", [])}
            nueva_entrada = dict(entrada)
            nueva_entrada["answers"] = contestacion
            log(f"    contesto allow + answers={contestacion}")
            enviar({"type": "control_response", "response": {
                "subtype": "success", "request_id": mensaje["request_id"],
                "response": {"behavior": "allow",
                             "updatedInput": nueva_entrada}}})
        else:
            log(f"    contesto deny + message con la eleccion en prosa")
            enviar({"type": "control_response", "response": {
                "subtype": "success", "request_id": mensaje["request_id"],
                "response": {"behavior": "deny",
                             "message": f"El usuario responde: {ELECCION}"}}})

    elif tipo == "user":
        # El resultado de la herramienta, que es donde se veria si la
        # respuesta entro.
        contenido = (mensaje.get("message") or {}).get("content")
        log(f"    tool_result: {json.dumps(contenido, ensure_ascii=False)[:300]}")

    elif tipo == "assistant":
        for bloque in mensaje["message"]["content"]:
            if bloque.get("type") == "text" and bloque.get("text", "").strip():
                log(f"<<< TEXTO: {bloque['text'][:250]}")
            elif bloque.get("type") == "tool_use":
                log(f"<<< HERRAMIENTA {bloque.get('name')}")

    elif tipo == "result":
        turnos += 1
        texto = str(mensaje.get("result") or "")
        respuestas[forma] = texto
        log(f"=== RESULT ({forma}): is_error={mensaje.get('is_error')} "
            f"terminal={mensaje.get('terminal_reason')!r}")
        log(f"    {texto[:250]!r}")
        if forma == "answers":
            forma = "deny_message"
            log("\n>>> TURNO 2: la misma pregunta, contestada con deny+message")
            enviar({"type": "user", "message": {"role": "user", "content": [
                {"type": "text", "text": PROMPT}]}})
        else:
            break

proceso.terminate()

print("\n" + "=" * 62)
print("QUE SABE EL MODELO DESPUES DE CADA FORMA")
print("=" * 62)
for forma, texto in respuestas.items():
    sabe = ELECCION.lower()[:5] in texto.lower()
    print(f"  {forma:14} nombra la eleccion: {'SI' if sabe else 'NO'}")
    print(f"                 {texto[:200]!r}")
print("\nSi ninguna la nombra, la respuesta NO esta llegando y el puente")
print("estaria permitiendo una pregunta sin contestarla -- que por fuera")
print("se ve igual que contestarla.")
