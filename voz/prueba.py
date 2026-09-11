"""Probar el micro y el altavoz desde la propia UI.

>>> POR QUE ESTO NO ES UN LUJO <<<
Es la contrapartida de dejar elegir dispositivo. La trampa que abre
`voz/audio.py` esta medida: **16 de los 23 endpoints de esta maquina son
cables de audio virtuales que entregan silencio digital perfecto
SIN dar error**. Elegir el equivocado no produce un fallo, produce un
Jarvis que escucha para siempre y no oye nada.

Un desplegable sin boton de probar seria repartir ese fallo. Con el, el
fallo mudo se convierte en uno que se ve en dos segundos:

    salida    suena un tono. Si no lo oyes, no es tu altavoz. Punto.
    entrada   se graba un momento y se enseña CUANTA energia llego y si
              el VAD encontro habla. Un cable virtual da -inf dBFS.

>>> TRES RESPUESTAS, NO DOS <<<
    OK              llego señal y habia habla
    SIN_SEÑAL       el dispositivo entrega silencio digital: es un cable
    NO_SE_PUDO      ni siquiera se pudo abrir

Y "grabo pero no hablaste" NO es un fallo del dispositivo: es
`OK` con `hubo_habla=False`. Colapsarlo contra SIN_SEÑAL diria que el
microfono esta roto por haberte quedado callado, que es justo el error
que este proyecto lleva veinte dias evitando.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Cuanto se graba al probar la entrada. Corto: es una prueba, no un
# dictado, y el usuario esta mirando la pantalla esperando.
SEGUNDOS_PRUEBA = 2.0


class Veredicto(str, Enum):
    OK = "ok"
    SIN_SENAL = "sin_senal"
    NO_SE_PUDO = "no_se_pudo"


@dataclass(frozen=True)
class Resultado:
    veredicto: Veredicto
    dispositivo: str
    mensaje: str
    nivel_dbfs: float | None = None
    hubo_habla: bool | None = None

    @property
    def bien(self) -> bool:
        return self.veredicto is Veredicto.OK

    def a_json(self) -> dict:
        return {
            "veredicto": self.veredicto.value,
            "dispositivo": self.dispositivo,
            "mensaje": self.mensaje,
            "nivel_dbfs": (round(self.nivel_dbfs, 1)
                           if self.nivel_dbfs is not None else None),
            "hubo_habla": self.hubo_habla,
        }


def _resolver(nombre: str, tipo: str):
    """El dispositivo que corresponde a lo elegido en el desplegable."""
    from voz.audio import PREDETERMINADO, seleccionar

    candidatos = [nombre] if nombre else [PREDETERMINADO]
    return seleccionar(candidatos, tipo)


def probar_salida(nombre: str = "") -> Resultado:
    """Toca un tono por ahi. Lo unico que lo verifica es tu oido.

    NO SE FINGE UNA COMPROBACION AUTOMATICA. Se podria mirar si la
    llamada devolvio sin error y decir "correcto", y seria mentira: un
    cable virtual acepta el audio encantado y no da un solo fallo. Lo que
    esta funcion garantiza es que el audio SALIO; si se oyo o no, lo dice
    el usuario. Por eso el mensaje pregunta en vez de afirmar.
    """
    from voz.audio import SAMPLE_RATE_VOZ, AudioError, reproducir
    from voz.senales import pitido

    try:
        dispositivo = _resolver(nombre, "salida")
    except AudioError as exc:
        return Resultado(Veredicto.NO_SE_PUDO, nombre, str(exc))

    try:
        reproducir(pitido(), SAMPLE_RATE_VOZ, dispositivo)
    except AudioError as exc:
        return Resultado(Veredicto.NO_SE_PUDO, str(dispositivo), str(exc))

    return Resultado(
        Veredicto.OK, str(dispositivo),
        "Ha sonado un tono. ¿Lo has oido? Si no, este no es tu altavoz: "
        "hay salidas que aceptan el audio sin quejarse y no lo sacan por "
        "ningun sitio.",
    )


def probar_entrada(nombre: str = "",
                   segundos: float = SEGUNDOS_PRUEBA) -> Resultado:
    """Graba un momento y dice CUANTO llego, no solo si fallo.

    La magnitud continua es el punto: un "correcto" binario
    esconde justo el caso que importa, que es el dispositivo que abre
    bien y entrega -inf dBFS.
    """
    from voz.audio import AudioError, grabar, medir_nivel

    try:
        dispositivo = _resolver(nombre, "entrada")
    except AudioError as exc:
        return Resultado(Veredicto.NO_SE_PUDO, nombre, str(exc))

    try:
        nivel = medir_nivel(dispositivo, segundos=segundos)
    except AudioError as exc:
        return Resultado(Veredicto.NO_SE_PUDO, str(dispositivo), str(exc))

    if nivel.sin_senal:
        # `sin_senal` es ABSOLUTO (rms practicamente cero) y por eso es
        # fiable: dice "por aqui no entra nada", no "nadie hablo".
        #
        # >>> Y NO DICE POR QUE, A PROPOSITO (2026-08-26) <<<
        # La primera version afirmaba "es un cable virtual, elige otro", y
        # el mismo dia se vio que eso es un consejo EQUIVOCADO la mitad de
        # las veces: el microfono USB aparecio a -91,8 dBFS -- 38 dB
        # por debajo de lo suyo -- simplemente porque estaba SILENCIADO
        # (tiene mute tactil en la placa de arriba). Mandarle a cambiar de
        # microfono cuando lo que hay que hacer es tocarlo es peor que no
        # decir nada, porque suena seguro.
        # Se dice lo que SI se sabe -- no entra señal -- y se nombran las
        # dos causas, la recuperable primero.
        return Resultado(
            Veredicto.SIN_SENAL, str(dispositivo),
            "Por ahi no entra nada. Lo mas probable es que este SILENCIADO "
            "(muchos micros tienen un boton o una placa tactil, y el "
            "micro USB se silencia tocandolo por arriba); mira tambien el "
            "volumen de entrada en Windows. Si esta bien y sigue asi, es "
            "que ese endpoint no es un microfono de verdad: elige otro.",
            nivel_dbfs=nivel.dbfs, hubo_habla=False,
        )

    hubo_habla = None
    try:
        from voz.vad import VAD

        audio = grabar(dispositivo, segundos)
        hubo_habla = VAD().recortar(audio).hay_habla
    except Exception:  # noqa: BLE001
        # Sin VAD se sigue: el nivel ya contesta lo principal, y decir
        # "no hubo habla" sin haber mirado seria inventarselo.
        hubo_habla = None

    if hubo_habla:
        mensaje = "Te oye. Ha llegado señal y ha encontrado habla."
    elif hubo_habla is False:
        mensaje = ("Llega señal, pero no ha encontrado habla. Si has hablado, "
                   "prueba otra vez mas cerca o mas alto.")
    else:
        mensaje = "Llega señal. No se ha podido comprobar si habia habla."
    return Resultado(Veredicto.OK, str(dispositivo), mensaje,
                     nivel_dbfs=nivel.dbfs, hubo_habla=hubo_habla)


if __name__ == "__main__":  # pragma: no cover - utilidad de mano
    import argparse

    p = argparse.ArgumentParser(description="Probar micro y altavoz")
    p.add_argument("que", choices=["entrada", "salida"])
    p.add_argument("--dispositivo", default="")
    a = p.parse_args()

    r = probar_salida(a.dispositivo) if a.que == "salida" else probar_entrada(
        a.dispositivo)
    print(f"[{r.veredicto.value}] {r.dispositivo}")
    if r.nivel_dbfs is not None:
        print(f"  nivel: {r.nivel_dbfs:.1f} dBFS")
    print(f"  {r.mensaje}")
