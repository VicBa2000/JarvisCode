"""Cuanto vivia la bandera de callar, y cada cuanto la miraba quien
reproduce el audio.

>>> POR QUE EXISTE ESTA SONDA <<<
El usuario reporto el 2026-08-29 que al decir "para" la voz a veces se
quedaba recitando aunque el trabajo ya se hubiera detenido. La version
anterior de `Bucle._parar_el_turno` era:

    self._callar.set()
    self.sesion.interrumpir()
    self._callar.clear()

y la pregunta era si esa ventana daba tiempo a que alguien la viera.
No se estima: se MIDE `Sesion.interrumpir()` de verdad, escribiendo en
una tuberia de verdad, que es lo unico que habia entre el `set()` y el
`clear()`. Y se pregunta al sistema cada cuanto corre el callback de
salida, que es quien mira esa bandera mientras suena el audio
(`voz/tts.py::hablar`, funcion `alimentar`).

    python -m eval.sonda_parar_la_voz

Resultado en esta maquina (2026-08-29):

    la bandera vivia    0,0082 ms  (mediana de 200; maxima 0,028)
    el callback mira    cada ~90 ms
    la veia el          ~0,009 % de las veces

O sea que NO fallaba a veces: no funcionaba nunca. Lo que se percibia
como "a veces si para" era el turno cerrandose solo -- `Fin.parado`
impide locutar la respuesta --, no la voz cortandose.

La magnitud continua es lo que dice el mecanismo. Un "a veces
no para" no habria distinguido "la ventana es corta" de "la bandera no
se mira", y son arreglos distintos.
"""

from __future__ import annotations

import os
import statistics
import threading
import time

from puente.sesion import Sesion

VUELTAS = 200


class ProcesoPostizo:
    """Un proceso cuyo stdin es una tuberia DE VERDAD.

    Con un doble que no escribe nada, lo que se mide es el doble. Aqui el
    `write` + `flush` son los reales.
    """

    def __init__(self) -> None:
        lectura, escritura = os.pipe()
        self._lectura = lectura
        self.stdin = os.fdopen(escritura, "w", encoding="utf-8")
        self.stdout = None
        # El buffer de una tuberia es de unos pocos KB: sin nadie leyendo
        # al otro lado, la vuelta 45 se bloquea y entonces lo que se mide
        # es eso. El proceso de verdad tambien lee.
        threading.Thread(target=self._drenar, daemon=True).start()

    def _drenar(self) -> None:
        while True:
            if not os.read(self._lectura, 65536):
                return

    def poll(self):
        return None


def main() -> int:
    sesion = Sesion(os.getcwd())
    sesion._proceso = ProcesoPostizo()

    for _ in range(3):          # unas cuantas en frio
        sesion.interrumpir()

    muestras = []
    for _ in range(VUELTAS):
        inicio = time.perf_counter()
        sesion.interrumpir()
        muestras.append((time.perf_counter() - inicio) * 1000.0)
    muestras.sort()

    mediana = statistics.median(muestras)
    print(f"VENTANA EN QUE LA BANDERA ESTABA PUESTA (ms), {VUELTAS} vueltas")
    print(f"  minima    {muestras[0]:.4f}")
    print(f"  mediana   {mediana:.4f}")
    print(f"  p95       {muestras[int(0.95 * len(muestras))]:.4f}")
    print(f"  maxima    {muestras[-1]:.4f}")

    try:
        import sounddevice as sd

        info = sd.query_devices(kind="output")
        periodo_ms = float(info.get("default_low_output_latency", 0.0)) * 1000
    except Exception as exc:  # noqa: BLE001
        print(f"\n(sin sounddevice: no se pudo leer el periodo -- {exc})")
        return 0

    print(f"\nSALIDA POR DEFECTO: {info['name']}")
    print(f"  el callback mira la bandera cada ~{periodo_ms:.1f} ms")
    if periodo_ms > 0:
        print(f"\n  la bandera vivia {mediana:.4f} ms de cada "
              f"{periodo_ms:.1f} ms")
        print(f"  probabilidad de que el callback la viera: "
              f"~{min(1.0, mediana / periodo_ms) * 100:.3f} %")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
