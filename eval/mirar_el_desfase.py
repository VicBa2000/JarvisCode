"""Cuanto se queda quieto el cabezal mientras Claude SI trabaja.

La queja del usuario: a veces lo que la pantalla dice que Jarvis hace y
lo que esta haciendo no coinciden. Antes de tocar nada, contar el suceso y
contra las trazas de disco, no contra una entrada inventada.

Se mide UNA cosa: cuantas herramientas se ejecutan sin que la frase del
cabezal cambie. Si la respuesta es "casi siempre una", la queja seria
otra cosa; si son rachas largas, la causa esta identificada.
"""
from collections import Counter
from pathlib import Path

from puente.protocolo import SeguidorDeTarea, UsoHerramienta, Fin, interpretar

rachas = []
por_sesion = 0
sesiones = 0
for ruta in sorted(Path("logs/puente").glob("*.jsonl")):
    seguidor = SeguidorDeTarea()
    racha = 0
    visto = False
    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            eventos = interpretar(linea)
        except Exception:
            continue
        for e in eventos:
            antes = seguidor.tarea
            seguidor.ve(e)
            if isinstance(e, UsoHerramienta):
                visto = True
                if seguidor.tarea != antes:
                    if racha:
                        rachas.append(racha)
                    racha = 1
                else:
                    racha += 1
            if isinstance(e, Fin):
                if racha:
                    rachas.append(racha)
                racha = 0
    if racha:
        rachas.append(racha)
    if visto:
        sesiones += 1

if not rachas:
    print("cero herramientas en las trazas: la sonda no ha medido nada")
    raise SystemExit(1)

rachas.sort()
n = len(rachas)
print(f"sesiones con herramientas: {sesiones}")
print(f"rachas (herramientas seguidas con la MISMA frase): {n}")
print(f"  mediana {rachas[n // 2]}   p90 {rachas[int(n * 0.9)]}   maximo {max(rachas)}")
print(f"  herramientas totales: {sum(rachas)}")
c = Counter(rachas)
print("  reparto:", ", ".join(f"{k}->{v}" for k, v in sorted(c.items())[:12]))
largas = sum(v for k, v in c.items() if k >= 3)
print(f"  rachas de 3 o mas: {largas} de {n} ({100*largas/n:.0f} %)")
print(f"  herramientas dentro de una racha de 3+: "
      f"{sum(k*v for k, v in c.items() if k >= 3)} de {sum(rachas)}")
