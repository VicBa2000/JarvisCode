"""Cuanto se pisan el REGISTRO y el VISOR del POV.

    python -m eval.mirar_el_solape

>>> LA PREGUNTA, DEL USUARIO (2026-09-02) <<<
La pregunta del usuario fue si el registro de transmision y esa ventana
no son "lo mismo" en cuanto a lo que se supone que hace cada una.

Es la pregunta correcta y no se contesta con una opinion. Los dos salen
del MISMO flujo, asi que se puede contar exactamente cuanto de lo que
pinta el registro es lo mismo que el visor enseña, y de que forma.

Se mide sobre las sesiones REALES de `logs/puente/`, no sobre
un turno inventado, y en tres ejes:

  1. **cuantos renglones** del registro son de herramienta, o sea los que
     el visor tambien enseña;
  2. **cuanta letra** de esos renglones es JSON crudo -- que es la parte
     que el visor enseña mejor: un documento como documento y no como
     `{"file_path":"C:\\\\...","content":"# Titulo\\n\\n..."}`;
  3. **que hay en el registro que el visor NO puede enseñar** -- puertas,
     decisiones, errores, lo que dijiste tu --, que es lo que decide si
     sobra uno de los dos o si cada uno hace algo distinto.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from puente.protocolo import (Fin, Inicio, Limite, Pensamiento, Puerta,
                              Pregunta, Reintento, ResultadoHerramienta, Texto,
                              UsoHerramienta, interpretar)

# Lo que el visor tambien enseña, cada uno a su manera.
LOS_DOS = (UsoHerramienta, ResultadoHerramienta, Texto, Pensamiento)

# Lo que SOLO puede estar en el registro. No es una lista de sobras: es
# la respuesta a la pregunta. Una puerta es donde se CONSIENTE y tiene
# que quedarse en pantalla hasta que alguien la conteste; un visor de un
# solo plano la borraria con lo siguiente que pasara.
SOLO_EL_REGISTRO = (Puerta, Pregunta, Inicio, Fin, Limite, Reintento)


def main() -> int:
    renglones = Counter()
    letra_de_herramienta = 0
    letra_json = 0
    sesiones = 0

    for ruta in sorted(Path("logs/puente").glob("*.jsonl")):
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        if not texto.strip():
            continue
        sesiones += 1
        for linea in texto.splitlines():
            try:
                eventos = interpretar(linea)
            except Exception:  # noqa: BLE001
                continue
            for e in eventos:
                renglones[type(e).__name__] += 1
                if isinstance(e, UsoHerramienta):
                    crudo = json.dumps(e.entrada, ensure_ascii=False)
                    # El registro pinta exactamente esto, recortado a 400.
                    letra_de_herramienta += min(len(crudo), 400)
                    letra_json += min(len(crudo), 400)
                if isinstance(e, ResultadoHerramienta):
                    letra_de_herramienta += min(len(e.contenido or ""), 600)

    total = sum(renglones.values())
    de_los_dos = sum(v for k, v in renglones.items()
                     if k in {c.__name__ for c in LOS_DOS})
    solo_registro = sum(v for k, v in renglones.items()
                        if k in {c.__name__ for c in SOLO_EL_REGISTRO})

    print(f"sesiones reales miradas: {sesiones}")
    print(f"renglones del registro: {total}\n")
    print("QUE PINTA EL REGISTRO, por clase:")
    for clase, cuantos in renglones.most_common():
        marca = ""
        if clase in {c.__name__ for c in LOS_DOS}:
            marca = "  <- el visor tambien lo enseña"
        elif clase in {c.__name__ for c in SOLO_EL_REGISTRO}:
            marca = "  <- SOLO puede estar aqui"
        print(f"  {clase:<22} {cuantos:>6}  {100*cuantos/total:>5.1f} %{marca}")

    print(f"\nSOLAPE: {de_los_dos} de {total} renglones "
          f"({100*de_los_dos/total:.0f} %) son de lo que el visor tambien "
          f"enseña.")
    print(f"LO QUE NO PUEDE SOLAPARSE: {solo_registro} renglones "
          f"({100*solo_registro/total:.0f} %) -- puertas, preguntas, "
          f"limites, fin de turno.")
    print(f"\nLETRA de herramienta que el registro pinta: "
          f"{letra_de_herramienta/1024:.0f} KB")
    print(f"  de la cual JSON crudo de la entrada: {letra_json/1024:.0f} KB "
          f"({100*letra_json/max(letra_de_herramienta,1):.0f} %)")
    print("\n>>> COMO SE LEE ESTO <<<")
    print("  El solape NO es 'sobra uno': es que el registro cuenta el")
    print("  PASADO entero y en orden (y ahi viven las puertas, que es")
    print("  donde se consiente), y el visor enseña UNA cosa, la de")
    print("  ahora, y en su forma -- un documento como documento.")
    print("  Lo que si sobra es la FORMA en que el registro pinta una")
    print("  herramienta: JSON crudo recortado a 400 caracteres, que no")
    print("  se lee ni dice nada que el visor no diga mejor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
