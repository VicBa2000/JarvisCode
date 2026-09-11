"""Un servidor MCP de verdad, lo mas pequeno que se puede. Instrumento.

NO ES PRODUCCION Y NO ES UN MOCK. Es lo mismo que el senuelo
del suelo de JC-0007: una pieza real -- habla JSON-RPC 2.0 por stdio y
Claude Code se le conecta de verdad -- que existe solo para que se pueda
MEDIR lo que pasa. Un servidor MCP ajeno serviria igual, pero traeria
una descarga, una version y una red al medio de la medicion.

Expone una sola herramienta, `sumar`, y lo importante no es que sume:
es que ESCRIBE UN ARCHIVO. Asi el veredicto se lee del DISCO y no de lo
que cuente el modelo, que es la regla de todas las sondas de este arbol
-- los mensajes dicen lo que se pidio, el disco dice lo que paso.

    python -m eval.sondas_claude_code.servidor_mcp_minimo <archivo>
"""

import json
import sys
from pathlib import Path

HUELLA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("huella_mcp.txt")

# `2024-11-05` es la version de protocolo con la que se midio el
# 2026-09-01 contra `claude 2.1.252`: el `system/init` devolvio
# `status: connected`.
VERSION_DEL_PROTOCOLO = "2024-11-05"

HERRAMIENTAS = [{
    "name": "sumar",
    "description": "Suma dos numeros y deja constancia en disco.",
    "inputSchema": {
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        "required": ["a", "b"],
    },
}]


def responder(id_, resultado) -> None:
    sys.stdout.write(json.dumps(
        {"jsonrpc": "2.0", "id": id_, "result": resultado}) + "\n")
    sys.stdout.flush()


def main() -> None:
    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        try:
            mensaje = json.loads(linea)
        except json.JSONDecodeError:
            continue
        metodo = mensaje.get("method")
        id_ = mensaje.get("id")
        if metodo == "initialize":
            responder(id_, {
                "protocolVersion": VERSION_DEL_PROTOCOLO,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "sonda", "version": "0.1.0"},
            })
        elif metodo == "tools/list":
            responder(id_, {"tools": HERRAMIENTAS})
        elif metodo == "tools/call":
            args = (mensaje.get("params") or {}).get("arguments") or {}
            total = (args.get("a") or 0) + (args.get("b") or 0)
            HUELLA.parent.mkdir(parents=True, exist_ok=True)
            with HUELLA.open("a", encoding="utf-8") as f:
                f.write(f"sumar {args.get('a')} + {args.get('b')} = {total}\n")
            responder(id_, {"content": [
                {"type": "text", "text": f"El resultado es {total}."}]})
        elif id_ is not None:
            # Un `id` sin respuesta deja al cliente esperando para siempre.
            responder(id_, {})


if __name__ == "__main__":
    main()
