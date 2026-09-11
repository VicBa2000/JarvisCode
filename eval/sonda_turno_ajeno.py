"""Cuanto tarda en sonar un turno que NO abrio la voz, y si suena.

    .venv\\Scripts\\python.exe -m eval.sonda_turno_ajeno

>>> DE DONDE SALE <<<
El usuario, el 2026-08-29, probando JC-0016: el mecanismo nuevo de
respuesta desde Telegram funcionaba, pero la respuesta no se locutaba --
no se oyo hasta que volvio a hablarle.

Mide las DOS mitades del fallo por separado, porque son dos y se sumaban:

  1. SI SE DICE. Se pasa un `Fin` REAL de cada traza de disco por el
     bucle con el ciclo DORMIDO -- que es como llega un turno del movil
     o de la consola -- y se mira si el TTS recibio algo. Antes del
     arreglo: 6 de 8 en silencio, porque `preparar_respuesta()` exige
     TRABAJANDO y el `CicloError` se lo tragaba `_atender_buzon`.

  2. CUANTO TARDA. El hilo de la voz drena el buzon y despues se mete
     VUELTA_WAKE_S = 30 s en la ronda del wake word, donde nadie drena.
     Se cronometra la misma ronda con y sin la bandera `_hay_correo`,
     que es lo unico que cambia -- o sea un A/B sobre el MISMO montaje y
     no contra un recuerdo.

>>> NO ES UN BANCO Y NO ESTIMA NADA <<<
El wake word es postizo a proposito: aqui no se mide acustica, se mide
el reparto del hilo. Lo unico que aporta el postizo es que la ronda DURE
-- un doble que vuelve al instante no tiene nunca una ronda en vuelo, que
es justo lo que hay que atravesar (la leccion de `TTSQuePolea`).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from puente.protocolo import Fin, interpretar
from voz.bucle import VUELTA_WAKE_S, Bucle
from voz.ciclo import Ciclo, Estado
from voz.senales import Senales

RAIZ = Path(__file__).resolve().parent.parent
TRAZAS = RAIZ / "eval" / "trazas_claude_code"

# Lo que dura la ronda del doble. No son los 30 s de verdad porque la
# sonda no puede tardar medio minuto por medida; lo que se lee es la
# RESTA entre las dos columnas, y esa no depende de la duracion.
RONDA_S = 2.0


class TTSQueApunta:
    def __init__(self) -> None:
        self.dicho: list[str] = []

    def hablar(self, texto, dispositivo=None, cancelar=None) -> None:
        self.dicho.append(texto)


class STTMudo:
    def escuchar(self, segundos=4.0, dispositivo=None, cancelar=None, **_):
        return _nada()

    def escuchar_turno(self, dispositivo=None, espera_inicio_ms=None, **_):
        return _nada()


class SesionQuieta:
    directorio = str(RAIZ)
    pendientes: tuple = ()

    def mandar(self, texto): pass
    def interrumpir(self): return True
    def responder(self, *a, **k): return True


class WakeQueDura:
    """Como el de verdad: mira `cancelar` en la misma vuelta que el limite."""

    def __init__(self, ronda_s: float = RONDA_S) -> None:
        self.ronda_s = ronda_s
        self.soltadas = 0

    def escuchar(self, dispositivo, limite_s=None, cancelar=None):
        fin = time.monotonic() + self.ronda_s
        while time.monotonic() < fin:
            if cancelar is not None and cancelar.is_set():
                self.soltadas += 1
                return
            time.sleep(0.005)
        return
        yield  # pragma: no cover - nunca se activa


def _nada():
    from voz.stt import Transcripcion

    return Transcripcion(texto="", latencia_s=0.0, duracion_audio_s=0.3,
                         prob_sin_habla=1.0, idioma="es", modelo="small",
                         hay_habla_vad=False)


def _bucle() -> Bucle:
    b = Bucle(sesion=SesionQuieta(), ciclo=Ciclo(senales=Senales()),
              tts=TTSQueApunta(), stt=STTMudo(), micro=object(),
              altavoz=None)
    b.ciclo.respiro_s = 0.0
    b.seguimiento = False
    b.narrar = False
    return b


def _fines() -> list[tuple[str, Fin]]:
    salida = []
    for ruta in sorted(TRAZAS.glob("*.jsonl")):
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            for evento in interpretar(linea):
                if isinstance(evento, Fin):
                    salida.append((ruta.stem, evento))
                    break
            else:
                continue
            break
    return salida


def mide_si_se_dice() -> None:
    print("\n1) ¿SE DICE LA RESPUESTA DE UN TURNO QUE NO ABRIO LA VOZ?")
    print("   (el ciclo entra DORMIDO, que es como llega de Telegram)\n")
    print(f"   {'traza':24s} {'caracteres':>10s}  {'tirados':>7s}  veredicto")
    dichas = 0
    for nombre, fin in _fines():
        b = _bucle()
        assert b.ciclo.estado is Estado.DORMIDO
        b.recibir(fin)
        b._atender_buzon()
        largo = sum(len(t) for t in b.tts.dicho)
        # Un turno PARADO y uno SIN RED no dicen la respuesta a proposito.
        esperado = "silencio correcto" if fin.parado else "se dice"
        if b.tts.dicho:
            dichas += 1
        print(f"   {nombre:24s} {largo:10d}  "
              f"{b.cuenta.eventos_tirados:7d}  {esperado}")
    total = len(_fines())
    mudas = total - dichas
    print(f"\n   HABLARON {dichas} de {total}; callaron {mudas}, y esa es la "
          "traza del turno PARADO,\n   cuyo silencio es correcto: ya se dijo "
          '"vale, paro" al pararlo.')
    print("   ANTES DEL ARREGLO HABLABA 1 DE 8, y era la de sin red: la unica"
          "\n   que vuelve ANTES de pedirle el estado al ciclo. Las otras 6 se"
          "\n   perdian en silencio, contadas en cero, con la suite en verde.")


def mide_cuanto_tarda() -> None:
    print("\n2) ¿CUANTO ESPERA EN LA RONDA DEL WAKE WORD?")
    print(f"   (ronda del doble: {RONDA_S:.1f} s; "
          f"la de verdad, VUELTA_WAKE_S = {VUELTA_WAKE_S:.0f} s)\n")
    _, fin = _fines()[0]

    for etiqueta, avisa in (("sin la bandera (como estaba)", False),
                            ("con la bandera (ahora)", True)):
        b = _bucle()
        b.wake = WakeQueDura()
        b.recibir(fin)
        if not avisa:
            b._hay_correo.clear()   # justo lo que faltaba antes
        empezo = time.monotonic()
        b._esperar_la_palabra()
        tardo = time.monotonic() - empezo
        print(f"   {etiqueta:32s} {tardo:6.3f} s   "
              f"rondas soltadas: {b.wake.soltadas}")

    print(f"\n   La resta es lo que se lee. Con la ronda de verdad son hasta\n"
          f"   {VUELTA_WAKE_S:.0f} s de espera antes de que la respuesta "
          "llegue al altavoz, y ese\n   rato es donde el usuario la oyo "
          "FUERA DE ORDEN: llegaba cuando el ya\n   estaba hablando de "
          "otra cosa.")


def main() -> int:
    if not TRAZAS.is_dir():
        print(f"no hay trazas en {TRAZAS}")
        return 1
    mide_si_se_dice()
    mide_cuanto_tarda()
    return 0


if __name__ == "__main__":
    sys.exit(main())
