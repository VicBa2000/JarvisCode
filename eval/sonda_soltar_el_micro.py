"""Sonda: cuanto tarda el oido en soltar el microfono (hallazgo 2026-08-26).

QUE MIDE. El usuario contestaba una puerta por voz y no se le oia. La
causa no era el reconocedor -- esperando al aviso entiende "no" a la
primera -- sino el hueco entre que Jarvis calla y el microfono se abre:
el hilo del oido esta a mitad de su vuelta de paradas y quien quiere
preguntar espera a que termine.

    3,0 s de grabacion  +  1,7-1,9 s de Whisper  =  hasta ~4,7 s

Y NO ES INTERMITENTE, es seguro justo detras de una puerta: el oido graba
MIENTRAS Jarvis habla, asi que su ventana viene llena de la voz del
propio Jarvis. Con la sala callada el VAD la despacha en 0,02 s y no se
nota; detras de una peticion de permiso siempre hay habla dentro y
siempre se pagan los dos segundos de Whisper.

ESTA SONDA MIDE EL CAMINO DE VERDAD, no una simulacion:
microfono real, `STT` real, la misma llamada que hace `voz/bucle.py`. Lo
unico que hace de mas es cronometrar.

    .venv/Scripts/python.exe -m eval.sonda_soltar_el_micro

NO HACE FALTA HABLAR. Lo que se cronometra es cuanto tarda la llamada en
volver despues de pedirle que suelte, y eso no depende de lo que suene.
"""

from __future__ import annotations

import argparse
import statistics
import threading
import time

from voz.audio import ConfigAudio
from voz.stt import STT
from voz.vad import Cierre

# La vuelta del oido, tal cual esta en `voz/bucle.py`.
VENTANA_PARADA_S = 3.0

# Cuando se le pide que suelte, contando desde que empieza a grabar. A
# mitad de vuelta a proposito: es donde mas se nota, y es donde cae una
# puerta que llega mientras Jarvis habla.
SOLTAR_EN_S = 1.0


def una_toma(stt: STT, micro, con_cancelar: bool) -> tuple[float, str]:
    """Devuelve (segundos desde el aviso hasta que vuelve, cierre)."""
    aviso = threading.Event()
    resultado: dict = {}

    def escuchar() -> None:
        t0 = time.perf_counter()
        t = stt.escuchar(
            segundos=VENTANA_PARADA_S,
            dispositivo=micro,
            cancelar=aviso if con_cancelar else None,
        )
        resultado["t"] = t
        resultado["fin"] = time.perf_counter()
        resultado["inicio"] = t0

    hilo = threading.Thread(target=escuchar)
    hilo.start()
    time.sleep(SOLTAR_EN_S)
    pedido = time.perf_counter()
    aviso.set()
    hilo.join(timeout=30)

    espera = resultado["fin"] - pedido
    cierre = resultado["t"].cierre or "(ninguno)"
    return espera, cierre


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tomas", type=int, default=3)
    args = p.parse_args()

    micro = ConfigAudio.desde_config().microfono()
    print(f"microfono: {micro}")
    stt = STT()
    print(f"modelo {stt.modelo}, cargado en {stt.carga_s:.1f} s\n")

    print(f"Se pide soltar a los {SOLTAR_EN_S:.1f} s de una vuelta de "
          f"{VENTANA_PARADA_S:.1f} s.\n")
    print(f"  {'':>6} {'espera tras el aviso':>22}  cierre")

    for modo, con_cancelar in (("ANTES", False), ("AHORA", True)):
        esperas = []
        for i in range(args.tomas):
            espera, cierre = una_toma(stt, micro, con_cancelar)
            esperas.append(espera)
            print(f"  {modo if i == 0 else '':>6} {espera:>19.2f} s  {cierre}")
        print(f"  {'':>6} {'mediana':>19} {statistics.median(esperas):.2f} s\n")

    print("ANTES = como corria hasta hoy: la vuelta se termina entera y se")
    print("        transcribe. AHORA = con `cancelar`, se suelta y NO se")
    print(f"        transcribe (cierre `{Cierre.ABORTADO.value}`).")
    print("\nOJO CON LEERLO: el `ANTES` de una sala callada es el caso")
    print("BUENO, no el malo -- sin habla dentro, el VAD ahorra Whisper y")
    print("la espera es solo lo que quedaba de grabacion. El caso que")
    print("sufria el usuario lleva la voz de Jarvis dentro y suma otros")
    print("1,7-1,9 s por encima de lo que salga aqui.")


if __name__ == "__main__":
    main()
