"""Que se queda en español, comparando las DOS paginas servidas.

No usa una lista de palabras españolas: sirve cada pagina en `es` y en
`en` y busca lo que NO cambio. Una cadena visible identica en los dos
idiomas o esta traducida a si misma (nombres propios, siglas, numeros) o
es deuda.
"""
import re
import sys
from pathlib import Path

# La raiz sale de donde esta ESTE archivo, no de una ruta escrita a
# mano: clavarla dejaba la sonda funcionando solo en un disco.
PROYECTO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROYECTO))

from nucleo.textos import traducir_pagina, traducir_tema  # noqa: E402

RAIZ = str(PROYECTO / "puente")

# Lo que legitimamente se escribe igual en los dos idiomas.
IGUALES = re.compile(
    r"^(?:[\W\d\s]*|jarvis|claude|claude code|mcp|telegram|python|"
    r"git|json|yaml|ok|id|url|pdf|api|usd|esc|cpu|gpu|windows|"
    r"anthropic|opus|sonnet|haiku|piper|whisper|no|error|total|"
    r"normal|natural|control|final|debug|info|test|version|"
    r"minimal|terminal|serial|central|social|especial)$", re.I)


def visibles(html: str) -> list[str]:
    """Nodos de texto, atributos que se ven, y literales de JS."""
    fuera = []
    sin_estilo = re.sub(r"<style>.*?</style>|<!--.*?-->", "", html,
                        flags=re.DOTALL)
    # 1. nodos de texto del HTML (sin el JS)
    cuerpo = re.sub(r"<script>.*?</script>", "", sin_estilo, flags=re.DOTALL)
    for t in re.findall(r">([^<>]{2,})<", cuerpo):
        fuera.append(" ".join(t.split()))
    # 2. atributos que se leen
    for t in re.findall(r'(?:title|placeholder|aria-label|alt)="([^"]{2,})"',
                        cuerpo):
        fuera.append(" ".join(t.split()))
    # 3. literales de JS -- lo que el test de cobertura NO mira
    for bloque in re.findall(r"<script>(.*?)</script>", sin_estilo,
                             flags=re.DOTALL):
        sin_comentarios = re.sub(r"//[^\n]*", "", bloque)
        for t in re.findall(r'"([^"\\\n]{2,})"', sin_comentarios):
            fuera.append(" ".join(t.split()))
        for t in re.findall(r"'([^'\\\n]{2,})'", sin_comentarios):
            fuera.append(" ".join(t.split()))
    return fuera


def main() -> int:
    total_deuda = 0
    for nombre in ("consola.html", "ajustes.html"):
        crudo = open(f"{RAIZ}\\{nombre}", encoding="utf-8").read()
        es = traducir_tema(crudo, "jarvis")
        en = traducir_pagina(traducir_tema(crudo, "jarvis"), "en")
        v_es, v_en = visibles(es), visibles(en)
        # Lo que sigue EXACTAMENTE igual tras traducir.
        # Solo lo que de verdad PARECE TEXTO: con espacio, o en
        # mayusculas de rotulo. Un identificador suelto (`tgToken`,
        # `var(--mono)`, `span`) no se traduce y llenaba la lista de
        # ruido -- 397 entradas de las que casi ninguna se ve.
        def es_texto(a):
            if re.match(r"^var\(|^[#.]|/|^--", a):
                return False
            return " " in a.strip() or (a.isupper() and len(a) > 2)
        quedan = sorted({a for a in set(v_es) & set(v_en)
                         if not IGUALES.match(a) and es_texto(a)})
        print(f"\n{'='*66}\n{nombre}: {len(quedan)} cadenas sin traducir "
              f"(de {len(set(v_es))} visibles)\n{'='*66}")
        for q in quedan:
            print(f"  {q[:88]!r}")
        total_deuda += len(quedan)
    print(f"\nTOTAL: {total_deuda}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
