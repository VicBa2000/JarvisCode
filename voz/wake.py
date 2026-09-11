"""La palabra de activacion: lo unico que esta encendido siempre.

Es la puerta de entrada del asistente y la pieza mas barata del arbol --
2,56 ms de trabajo por cada 80 ms de audio, medido el 2026-08-25, o sea
un 3 % de un nucleo escuchando todo el dia. Y es la que sostiene la unica
propiedad local que le queda a este fork: **mientras nadie diga
la palabra, no ha salido nada de esta maquina.** Wake word, VAD y STT
corren aqui; a la nube solo viaja el texto de una orden ya reconocida.

>>> EL MODELO ES INGLES, Y ESO NO ES UN DETALLE <<<
`hey_jarvis_v0.1` se entreno con "hey JAR-vis" dicho en ingles. La J
española (/x/, como en "jamon") no se parece a la inglesa (/dʒ/, como en
"yema"), asi que quien diga "ey jarbis" a la española puede no activarlo
NUNCA -- y por fuera eso se ve como "no me oye", no como lo que es.

Medido el 2026-08-25 sintetizando cada frase 5 veces con nuestro propio
TTS (piper es estocastico: la misma frase suena distinta cada vez, y una
sola sintesis no dice nada):

    frase                    min   mediana   max    disparan
    "Hey Jarvis" a la esp.  0,001   0,001   0,010     0/5
    "Ey Yarvis"             0,240   0,436   0,854     2/5
    "Ei Llarvis"            0,143   0,379   0,475     0/5
    "buenos dias que tal"   0,000   0,000   0,000     0/5   <- control

LO QUE ESO SI DICE: el mecanismo PUEDE dispararse, el habla que no es la
palabra nunca lo hace, y "Hey Jarvis" leido a la española practicamente
tampoco. LO QUE NO DICE: cual grafia es mejor. El suceso ocurre 2, 1 y 0
veces, y con esos numeros la tanda no ha respondido.

Y sobre todo: **una voz de TTS no es la del usuario**. Eso responde a
"puede dispararse esto?"; a "se dispara con quien lo va a usar" solo
responde hablando.

>>> MEDIDO CON LA VOZ DEL USUARIO EL 2026-08-25, Y DECIDE EL PRODUCTO <<<
La misma frase, la misma persona, el mismo microfono, cambiando SOLO como
se pronuncia. Barrido de umbral sobre las MISMAS grabaciones:

    umbral   "hey jarvis" a la inglesa   a la española
             (6 intentos)                (20 intentos)
     0,30         6/6                       15/20
     0,50         6/6   margen +0,493        3/20   margen -0,073
     0,70         6/6   margen +0,293        2/20
     0,90         5/6                        2/20

    a la inglesa   min 0,881 | mediana 0,991 | max 0,998
    a la española  min 0,018 | mediana 0,444 | max 0,969

No es cuestion de afinar el umbral: dicho a la española LA MEDIANA CAE
POR DEBAJO del umbral, o sea que el intento tipico no llega. Dicho a la
inglesa sobra margen.

(De esta tanda se llego a proponer subir el umbral a 0,7. Se retiro el
mismo dia al medir a distancia real -- ver mas abajo. Queda escrito
porque era una conclusion sacada de una tanda de CERCA, y ese es
justamente el error que la de distancia corrigio.)

LA CLAVE ES LA J: la de "yema"/"llave" (/dʒ/), no la de "jamon" (/x/).
"jei YAR-vis".

CONFIRMADO CON EL BUEN MICROFONO Y A DISTANCIA DE USO REAL (un micro
USB, "medio lejos, como usualmente estaria"). Esa pareja es la
comparacion LIMPIA, porque comparte micro y distancia y solo cambia como
se dice:
                        activan (umbral 0,5)   mediana
    micro USB, español        1/20               0,266
    micro USB, ingles         5/6                0,954

UN MICRO MEJOR NO ARREGLA LA PRONUNCIACION. Y OJO al comparar la webcam con
el micro USB: entre esas tandas cambiaron DOS cosas, el micro y la distancia,
asi que de ahi no se puede concluir nada sobre el micro por separado.

LA DISTANCIA CUESTA MARGEN, y por eso el umbral se queda en 0,5:
    inglesa de cerca      min 0,881  -> a 0,70 sigue 6/6
    inglesa a distancia   min 0,494  -> a 0,70 baja a 5/6
Subirlo a 0,7 por el margen de la tanda de cerca habria sido optimizar
para el laboratorio.

OJO, para no leer esto de mas: los fallos ocurren 0 y 1 vez sobre 6,
y con eso no se estima ninguna tasa. La evidencia buena es el MARGEN,
que es magnitud continua y no recuento.

>>> LA OTRA MITAD DE LA ACEPTACION, POR DOS CAMINOS (2026-08-25) <<<
**En la sala viva:** 0 falsos positivos en 10 minutos con el usuario
haciendo vida normal, medido el 2026-08-25 con
`-m eval.wake_bench --falsos 10`. Con una pega que la tanda dejo
escrita: que la sala estuviera viva se sabe POR TESTIMONIO, no por
instrumento -- `fraccion_con_sonido` se anadio despues, por eso.

**Y sobre lo ya grabado**, que no cuesta ni hablar ni esperar: el corpus
estaba en disco. `-m eval.wake_bench --falsos-grabados` pasa el
modelo por las 30 ordenes dictadas, los 30 avisos hablados y las 12 tomas
del silencio de esta sala. Nada de eso es la palabra:

    ordenes    3,0 min   0 activaciones   maxima ~0,01
    avisos     1,7 min   0 activaciones   maxima ~0,00
    silencio   0,6 min   0 activaciones   maxima ~0,08
    TOTAL      5,3 min   0

Hablando normal NI SE ACERCA: dos ordenes de magnitud por debajo del 0,5.
Lo que vale de esto es el margen, no el cero -- un recuento a cero no
dice si estuvo a punto.

LO QUE SIGUE SIN CUBRIRSE, juntando las dos tandas: **otras voces**. La
de 10 minutos era la vida normal del usuario -- el hablando, su musica --
y el corpus grabado es una sola voz cerca del micro. Ninguna de las dos
mete a una SEGUNDA persona en la sala, que es el riesgo concreto de la
ventana de seguimiento de JC-0012.
Y ninguna estima una TASA: los dos sucesos ocurrieron cero veces. Lo que hay
es margen, y es amplio.

>>> LA MISMA GRABACION NO DA SIEMPRE LA MISMA PUNTUACION <<<
Medido el 2026-08-25, y conviene saberlo antes de comparar dos numeros de
este modulo. `AudioFeatures.__init__` de openWakeWord ceba su buffer de
caracteristicas con RUIDO ALEATORIO del RNG global de numpy
(`openwakeword/utils.py:169`). O sea que cada `Wake` nace con un arranque
distinto, y el mismo audio da:

    sin controlar el RNG   0,2011   0,2248   0,2032
    con `np.random.seed`   0,1949   0,1949   0,1949

No es estado compartido entre instancias: es que cada una empieza en un
sitio distinto. Se descubrio porque un test comparaba dos `Wake` sobre el
mismo buffer y pasaba SUELTO y fallaba dentro de la suite, segun lo que
hubiera tocado el RNG antes.

QUE SIGNIFICA PARA QUIEN MIDA AQUI: dos puntuaciones que difieren en
centesimas NO son una diferencia. Comparar umbrales sobre las MISMAS
grabaciones (lo que hace `wake_bench --umbrales`) sigue valiendo, porque
el ruido afecta a todos los umbrales por igual; comparar dos frases por
una decima, no.

TRES ESTADOS, NO DOS. "Ha habido palabra de activacion?" parece
un si/no y no lo es, porque existe el caso en el que **no llega audio**.
Este proyecto ya lo pago: 16 de los 23 endpoints de esta maquina son
cables virtuales que entregan SILENCIO DIGITAL PERFECTO sin dar ningun
error, y un microfono que murio a media grabacion se queda tomado igual.
Un wake word escuchando silencio digital se comporta EXACTAMENTE como uno
que espera: ninguno dispara. Por eso `Escucha` lleva `mudo_desde_s` y
`sordo`, y el bucle de arriba puede decir "no te oigo" en vez de esperar
callado para siempre.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np

from voz.audio import SAMPLE_RATE_VOZ, AudioError, Dispositivo

# openWakeWord trabaja en tramas de 1280 muestras = 80 ms a 16 kHz. No es
# configurable: el preprocesador las trocea a ese tamaño igualmente.
TRAMA = 1280
TRAMA_S = TRAMA / SAMPLE_RATE_VOZ

# Por encima de esto se considera activacion. 0.5 es el punto de partida
# de openWakeWord, NO un numero medido en esta sala: se ajusta con
# `eval/wake_bench.py` contando falsos positivos, que es lo que manda la
# aceptacion.
#
# >>> ES EL SUELO, NO EL VALOR: LO ELIGE `voz.wake_word.umbral` <<<
# (2026-09-03.) Hasta hoy este numero era lo UNICO que decidia. El panel
# de ajustes ofrecia `voz.wake_word.umbral` desde el 2026-08-26, lo
# validaba, lo guardaba y lo superponia bien sobre `jarvis.yaml` --
# y nadie lo leia jamas: `voz/bucle.py` construye `Wake()` sin
# argumento. O sea un mando que giraba en el vacio, con la pantalla
# prometiendo ademas que se aplicaba al reiniciar.
#
# Y LA FORMA OBVIA DE ARREGLARLO NO FUNCIONA, que es por lo que la
# lectura vive en `_umbral_configurado` y no en la firma. El patron del
# arbol para esto es el de `tiempos.seguimiento_s`, que `puente/
# __main__.py` aplica pisando la constante del modulo
# (`mod_bucle.ESPERA_SEGUIMIENTO_S = ...`). Aqui ese patron seria
# SILENCIOSAMENTE INERTE: con `def __init__(self, umbral=UMBRAL)` el
# valor por defecto se evalua al DEFINIR la funcion y se queda en
# `__defaults__`, asi que pisar `voz.wake.UMBRAL` despues del import no
# cambia nada y no da ningun error. Habria sido el mismo fallo otra vez,
# con un arreglo encima para disimularlo.
UMBRAL = 0.5

# Tras una activacion, se ignora el modelo un rato. Sin esto una sola
# "ey jarvis" dispara varias veces seguidas -- el modelo puntua alto
# durante varias tramas -- y el bucle abriria dos ordenes para una frase.
REFRACTARIO_S = 2.0

# Un microfono que entrega ceros exactos no esta en silencio: no esta
# entregando nada. El silencio de una sala real tiene suelo de ruido
# (medido en una: -31 dBFS con el micro de una webcam).
SILENCIO_DIGITAL = 1e-7

# Cuanto silencio digital seguido hace falta para declararse sordo. Cinco
# segundos son muchisimas tramas y ninguna sala real los da.
SORDO_S = 5.0

# Por encima de esto hay ALGO sonando, no solo suelo de ruido. Referencia
# medida en esta casa: la sala en reposo da pico ~0,04 con el microfono USB.
# No pretende detectar habla -- para eso esta el VAD -- sino distinguir
# "habia vida" de "silencio de tumba".
SONIDO = 0.06


class WakeError(RuntimeError):
    """The wake word model is missing or cannot be run."""


# El mismo rango que ofrece el panel (`nucleo/ajustes.py`). Se repite
# aqui a proposito: el panel valida lo que ENTRA por la pantalla, y esto
# valida lo que SALE del archivo, que se puede editar a mano.
UMBRAL_MINIMO = 0.2
UMBRAL_MAXIMO = 0.9


def _umbral_configurado(config_dir: Path | None = None) -> float:
    """`voz.wake_word.umbral`, y el numero medido ante cualquier duda.

    TRES SALIDAS Y NO DOS: un numero bueno / un numero que no
    vale / no se ha podido leer. Las dos ultimas NO se colapsan contra
    "usa el ajuste igual", y tampoco se recortan al rango en silencio.

    >>> POR QUE UN VALOR MALO NO SE RECORTA <<<
    Recortar 5.0 a 0.9 dejaria a Jarvis casi sordo -- 0.9 esta muy por
    encima del 0.494 que dio el intento bueno mas flojo -- y con la
    pantalla enseñando 5.0 tan tranquila. Y recortar 0.0 a 0.2 lo dejaria
    disparando solo. Los dos fallos son MUDOS: no hay error, hay un wake
    word que se comporta raro. Se dice en voz alta y se usa el medido,
    que es lo mismo que hace `puente/__main__.py` con `--effort`.
    """
    try:
        from nucleo.ajustes import valor_de

        crudo = valor_de("voz.wake_word.umbral", UMBRAL, config_dir)
        elegido = float(crudo)
    except Exception:  # noqa: BLE001 - sin ajustes, manda lo medido
        return UMBRAL
    if not UMBRAL_MINIMO <= elegido <= UMBRAL_MAXIMO:
        print(f"AVISO: voz.wake_word.umbral = {elegido:g} esta fuera de "
              f"{UMBRAL_MINIMO:g}-{UMBRAL_MAXIMO:g}. Se usa {UMBRAL:g}, "
              f"que es el medido.")
        return UMBRAL
    return elegido


def ruta_del_modelo(nombre: str = "hey_jarvis_v0.1.onnx") -> Path:
    """Locate the wake word model inside the openWakeWord install.

    Vive DENTRO del `.venv`, igual que `silero_vad.onnx`: recrear el
    entorno se los lleva por delante. Son 12 MB y una orden, pero hay que
    saberlo antes de pasar media hora buscando por que no arranca.
    """
    try:
        import openwakeword
    except ImportError as exc:  # pragma: no cover
        raise WakeError(
            "openwakeword no esta instalado; es de donde sale el modelo"
        ) from exc

    ruta = (Path(os.path.dirname(openwakeword.__file__))
            / "resources" / "models" / nombre)
    if not ruta.is_file():
        raise WakeError(
            f"Falta {ruta}. Se descarga una vez con:\n"
            f"  python -c \"import openwakeword.utils as u; u.download_models()\"\n"
            f"  (con REQUESTS_CA_BUNDLE apuntando a .certs/bundle.pem)"
        )
    return ruta


@dataclass(frozen=True)
class Activacion:
    """One time the wake word fired, with the number that caused it."""

    puntuacion: float
    segundo: float
    """Segundos de audio procesados cuando salto. Es la referencia que
    permite volver a encontrarlo en una grabacion."""

    def __str__(self) -> str:
        return f"activacion en {self.segundo:.2f} s (puntuacion {self.puntuacion:.3f})"


@dataclass
class Escucha:
    """What the listener knows about itself while it runs.

    Existe para que "no ha pasado nada" se pueda distinguir de "no estoy
    oyendo nada", que desde fuera son identicos.
    """

    tramas: int = 0
    activaciones: int = 0
    mejor_puntuacion: float = 0.0
    mudo_desde_s: float = 0.0
    """Segundos seguidos recibiendo silencio DIGITAL (ceros exactos)."""

    tramas_con_sonido: int = 0
    """Tramas en las que sonaba algo por encima del suelo de ruido.

    >>> ESTO ES LO QUE HACE QUE UN "0 FALSOS POSITIVOS" SIGNIFIQUE ALGO <<<
    Una tanda de falsos positivos en una habitacion vacia mide una
    habitacion vacia. El banco lo AVISABA por escrito y no lo COMPROBABA,
    que es la misma distancia que hay entre un docstring y el codigo. Con este
    contador, "no salto nada" se puede leer junto a
    "y habia ruido el 40 % del tiempo", que ya es una frase con
    contenido.
    """

    ultima: Activacion | None = field(default=None, repr=False)

    @property
    def segundos(self) -> float:
        return self.tramas * TRAMA_S

    @property
    def fraccion_con_sonido(self) -> float:
        """Que parte del rato hubo algo sonando. Magnitud continua, no
        bandera: "la sala estuvo viva" admite grados."""
        if not self.tramas:
            return 0.0
        return self.tramas_con_sonido / self.tramas

    @property
    def sordo(self) -> bool:
        """True cuando lleva tanto silencio digital que no es creible.

        No es lo mismo que "no ha habido activacion": es que probablemente
        no esta llegando audio, y quien esta arriba tiene que poder DECIRLO
        en vez de seguir esperando en silencio.
        """
        return self.mudo_desde_s >= SORDO_S


class Wake:
    """The model, loaded once and fed frames.

    Se separa a proposito en `procesar` (una trama, sin hardware) y
    `escuchar` (el microfono de verdad). Todo lo que decide -- umbral,
    refractario, sordera -- vive en la parte sin hardware, que es la que
    se puede probar contra los wav grabados sin que nadie hable.
    """

    def __init__(self, umbral: float | None = None,
                 refractario_s: float = REFRACTARIO_S,
                 modelo: str | Path | None = None,
                 config_dir: Path | None = None) -> None:
        from openwakeword.model import Model

        # `None` = "el que haya configurado el usuario"; un numero = "este
        # y no se discute", que es lo que necesita `eval/wake_bench.py`
        # para barrer umbrales sin que el ajuste le mueva la medicion.
        self.umbral = (_umbral_configurado(config_dir) if umbral is None
                       else float(umbral))
        self.refractario_s = refractario_s
        self.ruta = Path(modelo) if modelo else ruta_del_modelo()
        self.nombre = self.ruta.stem
        try:
            # `onnx` explicito: el valor por defecto de openWakeWord es
            # `tflite`, y aqui el runtime instalado es onnxruntime -- el
            # mismo que ya usa `voz/vad.py`.
            self._modelo = Model(wakeword_models=[str(self.ruta)],
                                 inference_framework="onnx")
        except Exception as exc:  # noqa: BLE001
            raise WakeError(f"No se pudo cargar {self.ruta}: {exc}") from exc

        self.escucha = Escucha()
        self._callado_hasta = 0.0

    # --- la parte sin hardware -------------------------------------------

    def procesar(self, trama: np.ndarray) -> float:
        """Score one 1280-sample frame and update what we know.

        Acepta `float32` en [-1, 1] o `int16`, porque las dos formas
        circulan por este arbol: `audio.grabar` entrega float32 y los wav
        del corpus se leen como int16. Convertir aqui evita que cada
        llamante lo haga a su manera, que es como acaban difiriendo.
        """
        plano = np.asarray(trama).reshape(-1)
        if plano.dtype != np.int16:
            plano = np.clip(plano.astype(np.float32), -1.0, 1.0)
            pico = float(np.max(np.abs(plano)))
            plano = (plano * 32767).astype(np.int16)
        else:
            pico = float(np.max(np.abs(plano))) / 32768.0

        self.escucha.tramas += 1
        if pico < SILENCIO_DIGITAL:
            self.escucha.mudo_desde_s += TRAMA_S
        else:
            self.escucha.mudo_desde_s = 0.0
        if pico >= SONIDO:
            self.escucha.tramas_con_sonido += 1

        puntuacion = float(self._modelo.predict(plano)[self.nombre])
        self.escucha.mejor_puntuacion = max(
            self.escucha.mejor_puntuacion, puntuacion)
        return puntuacion

    def mirar(self, trama: np.ndarray) -> Activacion | None:
        """`procesar` mas la decision: umbral y periodo refractario.

        El refractario NO es cosmetico: el modelo puntua por encima del
        umbral durante varias tramas seguidas de la misma palabra, asi que
        sin el, una sola "ey jarvis" abriria dos o tres ordenes.
        """
        puntuacion = self.procesar(trama)
        ahora = self.escucha.segundos
        if puntuacion < self.umbral or ahora < self._callado_hasta:
            return None

        self._callado_hasta = ahora + self.refractario_s
        activacion = Activacion(puntuacion=puntuacion, segundo=ahora)
        self.escucha.activaciones += 1
        self.escucha.ultima = activacion
        return activacion

    def recorrer(self, audio: np.ndarray) -> list[Activacion]:
        """Run over a whole buffer. Para los wav del corpus y los tests."""
        plano = np.asarray(audio).reshape(-1)
        encontradas = []
        for inicio in range(0, len(plano) - TRAMA + 1, TRAMA):
            activacion = self.mirar(plano[inicio:inicio + TRAMA])
            if activacion is not None:
                encontradas.append(activacion)
        return encontradas

    # --- el microfono de verdad ------------------------------------------

    def escuchar(self, dispositivo: Dispositivo,
                 limite_s: float | None = None,
                 cancelar: threading.Event | None = None,
                 ) -> Iterator[Activacion]:
        """Listen on the real microphone until the caller stops asking.

        NO se usa `audio.grabar`: aquello graba un trozo de duracion fija
        y esto tiene que estar abierto indefinidamente. Lo que si se
        hereda es la leccion de aquel modulo -- un `InputStream` explicito
        con callback, nunca las funciones de conveniencia de sounddevice,
        que comparten un stream global y se quedan colgadas al mezclar
        reproducir y grabar en el mismo proceso.

        >>> `cancelar` SUELTA LA RONDA SIN ESPERAR AL LIMITE <<<
        Es el mismo patron que `STT.escuchar` (JC-0014) y esta por la
        misma razon: la ronda dura `VUELTA_WAKE_S` = 30 s, y mientras
        tanto el hilo de la voz no hace NADA MAS -- no drena su buzon, o
        sea que una respuesta que llega de un turno del movil puede
        esperar medio minuto al altavoz. Bajar los 30 s no es el arreglo:
        ese numero lo fija que abrir y cerrar el `InputStream` cuesta
        44 ms medidos, y en ese hueco no se oye nada.
        Se mira en la MISMA condicion que el limite, o sea cada trozo
        (~0,5 s en el peor caso, que es el `timeout` de la cola).
        """
        import sounddevice as sd

        cola: queue.Queue[np.ndarray] = queue.Queue()

        def entrando(datos, _tramas, _tiempo, estado) -> None:
            if estado:
                # No se traga: un overflow silencioso es audio perdido, y
                # audio perdido es una palabra que no se oyo.
                self.escucha.mudo_desde_s = 0.0
            cola.put(datos.copy())

        limite = None if limite_s is None else time.monotonic() + limite_s
        resto = np.zeros(0, dtype=np.float32)
        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE_VOZ,
                channels=1,
                device=dispositivo.indice,
                dtype="float32",
                blocksize=TRAMA,
                callback=entrando,
            ):
                while limite is None or time.monotonic() < limite:
                    if cancelar is not None and cancelar.is_set():
                        return
                    try:
                        trozo = cola.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    resto = np.concatenate([resto, trozo.reshape(-1)])
                    while len(resto) >= TRAMA:
                        activacion = self.mirar(resto[:TRAMA])
                        resto = resto[TRAMA:]
                        if activacion is not None:
                            yield activacion
        except Exception as exc:  # noqa: BLE001 - PortAudio raises many types
            raise AudioError(
                f"No se pudo escuchar en {dispositivo}: {exc}") from exc
