"""Banco de la palabra de activacion. Su prueba de aceptacion.

    .venv\\Scripts\\python.exe -m eval.wake_bench --activaciones 20
    .venv\\Scripts\\python.exe -m eval.wake_bench --falsos 10
    .venv\\Scripts\\python.exe -m eval.wake_bench --umbrales
    .venv\\Scripts\\python.exe -m eval.wake_bench --falsos-grabados
    .venv\\Scripts\\python.exe -m eval.wake_bench --calibrar [--aplicar]

LO QUE MIDE, y son dos preguntas distintas que no se contestan juntas:

  --activaciones   cuantas veces de N se despierta cuando SI lo llamas.
  --falsos         cuantas veces se despierta solo mientras vives tu vida.
  --falsos-grabados  lo mismo, pero sobre el audio que YA hay en disco y
                   que no es la palabra. No hace falta hablar ni esperar,
                   y contesta la mitad barata de la pregunta.
  --calibrar       junta las dos y propone un umbral; con --aplicar lo
                   GUARDA en config/ajustes.yaml, que es lo que lee
                   Jarvis al arrancar.

Las dos hacen falta. Un umbral bajisimo da 20/20 activaciones y despierta
al asistente cada vez que toses; uno altisimo no tiene un solo falso
positivo y no se despierta nunca. Un banco que midiera una sola de las
dos elegiria siempre el extremo equivocado.

>>> Y POR ESO `--calibrar` SE NIEGA CON UNA SOLA (2026-09-09) <<<
Nace de una idea del usuario: que cada quien grabe su banco y que **el
aplicativo use lo que salga**, en vez de dejar el numero en una tabla
que hay que trasladar a mano a un YAML. La idea es buena y el peligro es
concreto: con solo las activaciones, el umbral que "mejor sale" es
siempre el mas bajo que quepa, o sea el que despierta a Jarvis solo. Y
un falso positivo aqui no es una molestia -- es una ventana que se abre
sola, transcribe la sala y manda lo que oiga a la nube como si fuera una
orden. Asi que no se recomienda con media medicion: se para y se dice
que falta.

POR QUE ADEMAS SE GUARDA LA PUNTUACION DE CADA INTENTO: una
bandera "se activo si/no" esconde a la vez el intento que quedo en 0,49 y
el que quedo en 0,02, y no son lo mismo. Con el margen a la vista se
puede mover el umbral con criterio; con el recuento, solo a ojo. Por eso
existe `--umbrales`, que reproduce la MISMA grabacion contra varios
umbrales sin volver a hacerte hablar.

>>> ESTO NO SE PUEDE SUSTITUIR POR UNA VOZ SINTETICA <<<
Se probo, y sirvio para lo suyo: sintetizando con nuestro propio TTS se
confirmo que el mecanismo PUEDE dispararse, y que "Hey Jarvis" leido a la
española practicamente nunca lo hace (0/5, ver `voz/wake.py`). Pero una
voz de TTS no es la del usuario, y ademas piper es estocastico -- la
misma frase da 0,02 o 0,85 segun la sintesis --, asi que de ahi no sale
ningun numero que valga para decidir un umbral. Eso solo lo da hablar.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from voz.audio import SAMPLE_RATE_VOZ, ConfigAudio, grabar
from voz.wake import TRAMA, Wake

CARPETA = Path(__file__).resolve().parent / "audio_wake"

# >>> EL AUDIO QUE **NO** ES LA PALABRA, POR IDIOMA <<<
# Cualquier activacion aqui dentro es un falso positivo, y es la mitad
# barata de la pregunta: este audio ya existe porque lo grabo el banco
# de STT. Estaba clavado en español hasta el 2026-09-09, o sea que un
# usuario ingles medía sobre cero archivos y se llevaba un "0 falsos
# positivos" que no habia mirado nada.
# Las carpetas de avisos y silencio pueden no existir en un idioma y no
# pasa nada: lo que no puede pasar es que NINGUNA exista y el resultado
# se parezca a un aprobado.
CORPUS_NEGATIVO = {
    "es": (
        ("ordenes dictadas", "audio_ordenes"),
        ("avisos hablados", "audio_avisos"),
        ("silencio de la sala", "audio_silencio"),
    ),
    "en": (
        ("dictated orders", "audio_ordenes_en"),
        ("spoken prompts", "audio_avisos_en"),
        ("room silence", "audio_silencio_en"),
    ),
}

# El rango que acepta el ajuste `voz.wake_word.umbral`. No se inventa
# aqui: es el que declara `nucleo/ajustes.py`, y una recomendacion fuera
# de rango seria un numero que el panel rechaza.
UMBRAL_MIN, UMBRAL_MAX = 0.2, 0.9


@dataclass
class Negativos:
    """Lo que dio el audio que no es la palabra, y SI hubo algo que mirar.

    `hubo_material` es la razon de ser de esta clase. Antes esto devolvia
    un `int` con el recuento de falsos positivos, y un 0 tenia DOS
    significados que no se distinguian: "no se disparo ni una vez en 5,3
    minutos" y "no habia ni un archivo". El segundo es el que aparece en
    la maquina de cualquiera que no sea el autor.
    """

    activaciones: int
    segundos: float
    maxima: float
    por_archivo: list[float]
    hubo_material: bool


@dataclass
class Intento:
    """Un intento, CUANTO le falto, y si de verdad hubo alguien hablando.

    >>> `hubo_habla` NO ES UN ADORNO: SIN EL, EL BANCO MIENTE <<<
    "No activo" tiene DOS causas y puntuan igual, ~0,00: que no hablaras
    (te pillo el aviso a contrapie, o llegaste tarde) y que hablaras y el
    modelo no te reconociera. Son problemas distintos -- una se arregla
    repitiendo, la otra cambiando de palabra o de modelo -- y contarlas
    juntas da un "12/20" que no dice nada.
    Se descubrio en la calibracion del 2026-08-25: dos intentos a 0,000 y
    0,014 que casi con seguridad eran del usuario colocandose, no del
    modelo fallando. La tercera salida, en el propio banco.
    """

    numero: int
    mejor: float
    activo: bool
    hubo_habla: bool = True
    audio: np.ndarray = field(repr=False, default_factory=lambda: np.zeros(0))

    @property
    def veredicto(self) -> str:
        if self.activo:
            return "SI"
        return "no" if self.hubo_habla else "SIN HABLA"


def _mejor_puntuacion(audio: np.ndarray, umbral: float,
                      modelo: str | None = None) -> tuple[float, bool]:
    """Recorre un buffer con un Wake NUEVO y devuelve el maximo.

    Nuevo a proposito: reutilizar uno arrastraria el periodo refractario
    del intento anterior y el siguiente saldria "fallido" por un motivo
    que no tiene nada que ver con como lo dijiste.
    """
    w = Wake(umbral=umbral, modelo=modelo)
    activaciones = w.recorrer(audio)
    return w.escucha.mejor_puntuacion, bool(activaciones)


class Aviso:
    """Avisa por el altavoz, porque QUIEN DICTA NO VE LA TERMINAL.

    Si el banco lo lanza el agente, el usuario no tiene delante el "AHORA"
    impreso: esta mirando a otro lado, esperando. Un aviso escrito en una
    terminal que nadie mira es lo mismo que ningun aviso.

    >>> LA SEÑAL DE CADA INTENTO ES UN PITIDO, NO UNA PALABRA <<<
    La primera version decia "ahora" con el TTS. Medido con el usuario el
    2026-08-25: **salia tan rapido que no se entendia**, y por eso solo
    acerto a hablar en el ultimo de tres intentos. Los dos ceros de
    aquella tanda no median el wake word, median MI AVISO -- la sonda
    midiendose otra vez, ahora en el instrumento en vez de en los datos.

    Un pitido no puede ser ininteligible. La voz se reserva para la
    explicacion del principio, que se oye una vez y sin prisa; la señal
    por intento es un tono, que se reconoce sin escucharlo entero.

    Y ninguno de los dos contiene la palabra de activacion, claro: si la
    dijera, el banco se despertaria a si mismo.
    """

    def __init__(self, encendido: bool) -> None:
        self.encendido = encendido
        self._tts = None
        self._senales = None
        self._altavoz = None
        if not encendido:
            return
        from voz.senales import Senales
        from voz.tts import TTS
        self._tts = TTS()
        self._altavoz = ConfigAudio.desde_config().altavoz()
        # Los dos sonidos vienen de `voz/senales.py` desde el 2026-08-25
        # y no se generan aqui: dos pitidos en dos archivos
        # divergen, y el aviso es parte del instrumento de medida.
        self._senales = Senales(self._altavoz)

    def di(self, texto: str) -> None:
        """Habla. Solo para lo que se oye una vez y da tiempo a procesar."""
        if not self.encendido:
            return
        from voz.audio import reproducir
        audio = np.concatenate(list(self._tts.sintetizar(texto)))
        reproducir(audio, self._tts.sample_rate, self._altavoz)

    def pita(self) -> None:
        """La señal de "habla ya"."""
        if self._senales is not None:
            self._senales.pitido()


def medir_activaciones(cuantas: int, umbral: float, segundos: float,
                       guardar: bool, con_voz: bool = False,
                       modelo: str | None = None) -> list[Intento]:
    """Las N veces que lo llamas, contando cuantas te oye.

    >>> AQUI HUBO UNA TANDA `--campana` Y SE RETIRO (2026-08-25) <<<
    Media la idea original de JC-0011: avisar unos segundos ANTES para
    dar tiempo a bajar la musica. Esa idea se cayo el mismo dia usandola
    -- ver `voz/ciclo.py::avisar_de_que_escucha` --, y con ella se cayo
    la tanda, por un motivo que conviene dejar escrito: **el aviso previo
    no podia ayudar nunca al wake word**, porque la palabra de activacion
    ocurre ANTES de que suene nada. No se puede avisar a alguien de que
    va a hablar antes de que decida hablar.
    Una opcion de banco que mide una idea retirada es prosa que envejece
    con forma de codigo, asi que se fue.
    """
    micro = ConfigAudio.desde_config().microfono()
    print(f"Microfono: {micro}")
    print(f"Vas a decir la palabra {cuantas} veces, una por aviso.")
    print("Dila como la dirias de verdad, no la actues: lo que se mide es")
    print("si te despierta a TI, no si el modelo puede despertarse.\n")
    if guardar:
        CARPETA.mkdir(parents=True, exist_ok=True)

    from voz.vad import VAD
    vad = VAD()
    aviso = Aviso(con_voz)
    aviso.di("Escucha. Cada vez que oigas un pitido, di la palabra. "
             "Empezamos en tres segundos.")
    if con_voz:
        time.sleep(3.0)

    intentos: list[Intento] = []
    for numero in range(1, cuantas + 1):
        print(f"  [{numero:2}/{cuantas}] preparado...", end="", flush=True)
        aviso.pita()
        # Un respiro entre la señal y la grabacion: si se solapan, la cola
        # del pitido entra en el audio y ensucia la medicion.
        time.sleep(0.25 if con_voz else 1.2)
        print(" AHORA", flush=True)
        audio = grabar(micro, segundos)
        mejor, activo = _mejor_puntuacion(audio, umbral, modelo)
        hubo_habla = vad.recortar(audio).hay_habla
        intentos.append(Intento(numero, mejor, activo, hubo_habla, audio))
        print(f"            {intentos[-1].veredicto:9} ({mejor:.3f})")
        # Un respiro entre intentos: encadenarlos sin pausa es lo que hace
        # que el usuario vaya siempre medio segundo por detras.
        if con_voz:
            time.sleep(0.6)
        if guardar:
            _guardar(CARPETA / f"activacion_{numero:02d}.wav", audio)
    return intentos


def medir_falsos(minutos: float, umbral: float) -> tuple[int, float]:
    """Escucha sin que nadie llame al asistente, y cuenta lo que salta.

    Se pide expresamente que la sala este VIVA -- musica, television,
    conversacion --, porque un falso positivo en una habitacion en
    silencio no dice nada del uso real.
    """
    micro = ConfigAudio.desde_config().microfono()
    print(f"Microfono: {micro}")
    print(f"Escuchando {minutos:.0f} min SIN que llames al asistente.")
    print("Haz vida normal: habla, pon musica o television. Una sala en")
    print("silencio no mide falsos positivos, mide una sala en silencio.\n")

    w = Wake(umbral=umbral)
    falsos = 0
    inicio = time.monotonic()
    for activacion in w.escuchar(micro, limite_s=minutos * 60):
        falsos += 1
        print(f"  FALSO POSITIVO {falsos}: {activacion}")
    horas = (time.monotonic() - inicio) / 3600
    if w.escucha.sordo:
        print("\n!! LA ESCUCHA SE QUEDO SORDA: el microfono entregaba silencio")
        print("!! digital. Esta tanda NO mide nada; revisa el dispositivo.")

    # >>> UN 0 EN UNA HABITACION VACIA NO ES UN 0 <<<
    # Este banco AVISABA por escrito de que hiciera falta ruido y no lo
    # COMPROBABA -- la misma distancia que hay entre un docstring y el
    # codigo. La primera tanda real dio "0 falsos positivos" sin
    # que nadie supiera si habia sonado algo. Ahora el numero viene con su
    # condicion al lado.
    viva = w.escucha.fraccion_con_sonido
    print(f"\n  la sala sono el {viva:.0%} del tiempo")
    if viva < 0.05:
        print("  !! CASI NO SONO NADA. Esta tanda mide una sala en silencio,")
        print("  !! no falsos positivos. Repitela con musica, television o")
        print("  !! conversacion, que es donde el asistente va a vivir.")
    return falsos, horas


def falsos_en_lo_grabado(idioma: str = "es") -> "Negativos":
    """Cuenta activaciones sobre audio REAL que NO es la palabra.

    >>> ESTO NO SUSTITUYE A `--falsos`, PERO ES GRATIS Y YA EXISTE <<<
    `--falsos` ya se corrio (0 en 10 min de sala viva, 2026-08-25) y esto
    no lo reemplaza: lo complementa por el lado barato. Aquella tanda
    cuesta diez minutos de tu vida y esta no cuesta nada, porque el
    corpus ya esta en disco:
    30 ordenes dictadas, 30 avisos hablados y 12 tomas del silencio de
    esta habitacion. Nada de eso es "hey jarvis", asi que **cualquier
    activacion ahi es un falso positivo**.

    Se lee con el MARGEN, no con el recuento: un 0/0 no dice si
    estuvo a punto. Medido el 2026-08-25, con umbral de disparo 0,5:

        ordenes    3,0 min   0 activaciones   maxima ~0,01
        avisos     1,7 min   0 activaciones   maxima ~0,00
        silencio   0,6 min   0 activaciones   maxima ~0,08
        TOTAL      5,3 min   0

    O sea que hablando normal NI SE ACERCA: dos ordenes de magnitud por
    debajo del umbral. Las maximas van con "~" a proposito -- entre dos
    pasadas dieron 0,010 y 0,004 sobre el MISMO audio, que es la rareza
    que documenta `voz/wake.py`: el modelo ceba su buffer con ruido
    aleatorio. Comparar centesimas aqui no significa nada; comparar
    ordenes de magnitud, si.

    (El silencio puntua MAS que el habla, y por lo mismo: con nada que
    oir, lo que domina es ese cebado.)

    >>> LO QUE ESTO **NO** DICE <<<
    Que sean 0 sobre 5,3 minutos no da una tasa: el suceso ocurrio CERO
    veces y con eso no se estima nada. Lo que si da es el
    margen, que es continuo y ese si vale. Y no cubre lo que mas
    importaria: television, musica y OTRAS VOCES, que es lo unico que
    prueba `--falsos` con la sala viva.
    """
    import wave

    corpus = CORPUS_NEGATIVO[idioma]
    raiz = Path(__file__).resolve().parent
    print("Activaciones sobre audio real que NO es la palabra.\n")
    print(f"  {'corpus':22} {'archivos':>8} {'minutos':>8} "
          f"{'activan':>8} {'maxima':>8}")
    total_segundos = 0.0
    total_activaciones = 0
    puntuaciones: list[float] = []
    for nombre, carpeta in corpus:
        wavs = sorted((raiz / carpeta).glob("*.wav"))
        if not wavs:
            print(f"  {nombre:22} (no hay grabaciones en {carpeta})")
            continue
        segundos = 0.0
        activaciones = 0
        mejor = 0.0
        for ruta in wavs:
            with wave.open(str(ruta), "rb") as w:
                audio = np.frombuffer(w.readframes(w.getnframes()),
                                      dtype=np.int16)
            segundos += len(audio) / SAMPLE_RATE_VOZ
            # Un Wake NUEVO por archivo: reutilizarlo arrastraria el
            # periodo refractario de uno al siguiente.
            wake = Wake()
            activaciones += len(wake.recorrer(audio))
            # La mejor de CADA archivo, no solo la del corpus: `calibrar`
            # necesita la nube entera para saber donde separar.
            puntuaciones.append(wake.escucha.mejor_puntuacion)
            mejor = max(mejor, wake.escucha.mejor_puntuacion)
        total_segundos += segundos
        total_activaciones += activaciones
        print(f"  {nombre:22} {len(wavs):8} {segundos/60:8.1f} "
              f"{activaciones:8} {mejor:8.3f}")

    # >>> CERO SOBRE CERO NO ES CERO FALSOS POSITIVOS <<<
    # (2026-09-09.) Estas tres carpetas estaban CLAVADAS en español,
    # asi que en una instalacion sin ese corpus -- la de cualquiera
    # que no sea el autor, y la de TODO usuario ingles -- la funcion
    # recorria cero archivos y terminaba imprimiendo "0 falsos
    # positivos en 0.0 min", que se lee como un aprobado. Es el fallo
    # de la cuota otra vez: un 0 perfectamente creible justo donde
    # falta el dato. Y aqui cuesta mas caro, porque de este numero
    # cuelga la mitad "no se despierta solo" de la calibracion.
    if not puntuaciones:
        print("\n  NO HAY NADA QUE MEDIR: ninguna de esas carpetas tiene")
        print("  grabaciones, asi que esto NO es '0 falsos positivos'.")
        print("  Es que no se ha mirado. El corpus se graba con:")
        print(f"    -m eval.stt_bench --grabar"
              f"{'' if idioma == 'es' else ' --idioma ' + idioma}")
        return Negativos(0, 0.0, 0.0, [], False)

    print(f"\n  {total_activaciones} falsos positivos en "
          f"{total_segundos/60:.1f} min de audio real.")
    print("  El umbral de disparo es 0,5: lo que dice si estuvo cerca es la")
    print("  columna 'maxima', no el recuento.")
    print("\n  OJO CON LO QUE ESTO NO CUBRE: television, musica y otras")
    print("  voces. Eso solo lo mide `--falsos` con la sala viva.")
    return Negativos(total_activaciones, total_segundos,
                     max(puntuaciones), puntuaciones, True)


def repasar_umbrales(umbrales: list[float]) -> None:
    """Reproduce las grabaciones guardadas contra varios umbrales.

    No vuelve a hacerte hablar: es el mismo audio, y por eso los umbrales
    se pueden COMPARAR. Volver a grabar para cada umbral mezclaria el
    efecto del umbral con el de haberlo dicho distinto.
    """
    wavs = sorted(CARPETA.glob("activacion_*.wav"))
    if not wavs:
        print(f"No hay grabaciones en {CARPETA}. Corre primero:")
        print("  -m eval.wake_bench --activaciones 20 --guardar")
        return

    print(f"{len(wavs)} grabaciones en {CARPETA}\n")
    print(f"  {'umbral':>7}  {'activan':>9}  {'margen mediano':>15}")
    audios = [_leer(w) for w in wavs]
    mejores = [_mejor_puntuacion(a, 1.1)[0] for a in audios]
    for umbral in umbrales:
        activan = sum(1 for m in mejores if m >= umbral)
        margen = statistics.median(m - umbral for m in mejores)
        print(f"  {umbral:7.2f}  {activan:4}/{len(wavs):<4}  {margen:15.3f}")
    print("\nEl margen mediano importa tanto como el recuento: dos umbrales")
    print("con 20/20 no son iguales si uno deja 0,45 de margen y otro 0,02.")


@dataclass
class Frontera:
    """Donde separar las dos nubes, o por que no se puede.

    >>> ESTO ES UNA FUNCION PURA A PROPOSITO <<<
    Vivia dentro de `calibrar`, mezclada con los `print` y con leer wav
    del disco, y asi solo se podia probar en la maquina del autor -- que
    es la unica con corpus. En un clon recien descargado la decision que
    ESCRIBE UN AJUSTE no tenia ni un test. Separada, se prueba con seis
    numeros y sin un solo archivo de audio.
    """

    veredicto: str          # "separadas" | "se_pisan" | "sin_material"
    propuesto: float | None
    mas_flojo: float | None = None
    mas_alto_ajeno: float | None = None

    @property
    def separacion(self) -> float | None:
        if self.mas_flojo is None or self.mas_alto_ajeno is None:
            return None
        return self.mas_flojo - self.mas_alto_ajeno


def decidir_umbral(positivos: list[float],
                   negativos: "Negativos | None") -> Frontera:
    """De las dos nubes a un umbral. TRES salidas, y ninguna se colapsa.

    `sin_material` NO es "no hay falsos positivos": es que no se ha
    mirado, y devolver un umbral ahi seria recomendar con media
    medicion. Con solo la nube de arriba, el mejor umbral es siempre el
    mas bajo que quepa -- o sea el que despierta a Jarvis solo.

    `se_pisan` tampoco es un fallo del banco: dice que con esa palabra y
    esa voz NO existe umbral que acierte las dos cosas. Inventar el punto
    medio de dos nubes que se solapan seria dibujar una frontera donde
    no la hay.
    """
    if not positivos or negativos is None or not negativos.hubo_material:
        return Frontera("sin_material", None)
    mas_flojo = min(positivos)
    mas_alto = negativos.maxima
    if mas_flojo <= mas_alto:
        return Frontera("se_pisan", None, mas_flojo, mas_alto)
    medio = (mas_flojo + mas_alto) / 2
    return Frontera("separadas",
                    round(min(max(medio, UMBRAL_MIN), UMBRAL_MAX), 2),
                    mas_flojo, mas_alto)


def calibrar(idioma: str = "es", aplicar: bool = False) -> int:
    """De las DOS mitades a un umbral, y del umbral al ajuste que se usa.

    >>> POR QUE NO SE PUEDE CON UNA SOLA MITAD, Y AQUI SE IMPIDE <<<
    Lo dice la cabecera de este archivo desde que se escribio: un umbral
    bajisimo da 20/20 y despierta al asistente cada vez que toses; uno
    altisimo no tiene un falso positivo y no se despierta nunca. Quien
    grabe 20 activaciones y baje el umbral hasta que salgan todas esta
    mirando media pregunta, y la mitad que ignora es la CARA: un falso
    positivo aqui no es una molestia, es una ventana que se abre sola,
    transcribe la sala y manda lo que oiga a la nube como si fuera una
    orden tuya. Eso es JC-0012 al pie de la letra.
    Por eso esto se NIEGA a recomendar sin las dos, en vez de recomendar
    con un asterisco: un aviso al pie no lo lee quien ya vio un numero.

    >>> Y TIENE TRES SALIDAS, NO DOS <<<
    Las dos nubes se separan (hay umbral limpio) / se solapan (NO existe
    ningun umbral que acierte las dos cosas, y eso es un resultado, no un
    fallo) / falta una mitad (no se sabe). La de en medio es la que no se
    puede colapsar: devolver el punto medio de dos nubes que se pisan
    seria inventarse una frontera que no existe.
    """
    from nucleo.ajustes import valor_de

    print(f"CALIBRAR LA ESCUCHA  ({idioma})\n")

    # --- mitad 1: te oye cuando le llamas -----------------------------
    wavs = sorted(CARPETA.glob("activacion_*.wav"))
    if not wavs:
        print(f"Falta la mitad de 'te oye': no hay grabaciones en {CARPETA}.")
        print("  -m eval.wake_bench --activaciones 20 --con-voz --guardar")
        return 1
    positivos = sorted(_mejor_puntuacion(_leer(w), 1.1)[0] for w in wavs)
    print(f"  te oye        {len(positivos)} intentos grabados")
    print(f"                el mas flojo {positivos[0]:.3f}, "
          f"mediana {statistics.median(positivos):.3f}")

    # --- mitad 2: no se despierta solo --------------------------------
    print()
    negativos = falsos_en_lo_grabado(idioma)
    if not negativos.hubo_material:
        print("\nSIN ESA MITAD NO SE RECOMIENDA NADA, y no es prudencia:")
        print("con solo la primera, el umbral que 'mejor sale' es siempre el")
        print("mas bajo posible, que es el que despierta a Jarvis solo.")
        return 1

    # --- la frontera ---------------------------------------------------
    frontera = decidir_umbral(positivos, negativos)
    print()
    print(f"  el intento bueno mas flojo      {frontera.mas_flojo:.3f}")
    print(f"  lo mas alto del audio ajeno     {frontera.mas_alto_ajeno:.3f}")

    if frontera.veredicto == "se_pisan":
        print("\n  >>> LAS DOS NUBES SE PISAN <<<")
        print("  NO existe un umbral que acierte las dos cosas: cualquiera")
        print("  que te oiga siempre se despertara tambien con ese audio.")
        print("  Eso es un RESULTADO, no un fallo del banco, y no se tapa")
        print("  con un punto medio inventado. Con la palabra actual, o se")
        print("  pierde alguna llamada o se acepta algun despertar solo:")
        repasar_umbrales([0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
        return 2

    propuesto = frontera.propuesto
    actual = valor_de("voz.wake_word.umbral", 0.5)
    print(f"  separacion                      {frontera.separacion:.3f}")
    print(f"\n  umbral propuesto  {propuesto:.2f}   (ahora tienes {actual})")
    print("  Es el punto medio entre las dos nubes, recortado al rango que")
    print("  acepta el panel. Bajarlo te oye con menos esfuerzo Y se")
    print("  despierta solo mas a menudo: las dos cosas a la vez, siempre.")

    if not aplicar:
        print("\n  No se ha guardado nada. Para que Jarvis lo use:")
        print(f"    -m eval.wake_bench --calibrar --aplicar"
              f"{'' if idioma == 'es' else ' --idioma ' + idioma}")
        return 0

    from nucleo.ajustes import guardar

    guardar({"voz.wake_word.umbral": propuesto})
    print(f"\n  GUARDADO en config/ajustes.yaml: {propuesto:.2f}")
    print("  Lo lee `voz.wake.Wake` al arrancar, asi que REINICIA Jarvis.")
    print("  Se cambia tambien desde AJUSTES > Avanzado, y se vuelve atras")
    print("  poniendo el que tenias.")
    return 0


def _guardar(ruta: Path, audio: np.ndarray) -> None:
    import wave
    datos = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE_VOZ)
        w.writeframes(datos.tobytes())


def _leer(ruta: Path) -> np.ndarray:
    import wave
    with wave.open(str(ruta), "rb") as w:
        crudo = w.readframes(w.getnframes())
    return np.frombuffer(crudo, dtype=np.int16)


def _ruta_modelo(nombre: str | None):
    """Un nombre suelto se resuelve a la carpeta de openWakeWord."""
    if not nombre:
        return None
    from voz.wake import ruta_del_modelo
    return ruta_del_modelo(nombre)


def main() -> int:
    trozos = argparse.ArgumentParser(description="Banco de la palabra de activacion")
    trozos.add_argument("--activaciones", type=int, default=0,
                        help="cuantas veces vas a decirla (la aceptacion pide 20)")
    trozos.add_argument("--falsos", type=float, default=0.0,
                        help="minutos escuchando sin llamarlo (sala viva)")
    trozos.add_argument("--calibrar", action="store_true",
                        help="de las dos mitades a un umbral, y con "
                             "--aplicar lo guarda para que Jarvis lo use")
    trozos.add_argument("--aplicar", action="store_true",
                        help="escribe el umbral propuesto en "
                             "config/ajustes.yaml (solo con --calibrar)")
    trozos.add_argument("--idioma", choices=("es", "en"), default="es",
                        help="que corpus se usa como audio ajeno")
    trozos.add_argument("--falsos-grabados", action="store_true",
                        help="cuenta activaciones sobre el audio YA GRABADO "
                             "que no es la palabra (ordenes, avisos, "
                             "silencio). Gratis y sin hablar")
    trozos.add_argument("--umbrales", action="store_true",
                        help="repasa las grabaciones guardadas con varios umbrales")
    trozos.add_argument("--umbral", type=float, default=0.5)
    trozos.add_argument("--segundos", type=float, default=3.0,
                        help="cuanto se graba por intento")
    trozos.add_argument("--guardar", action="store_true",
                        help="guarda los wav para poder repasar umbrales despues")
    trozos.add_argument("--modelo", default=None,
                        help="otro modelo, p.ej. alexa_v0.1.onnx")
    trozos.add_argument("--con-voz", action="store_true",
                        help="avisa en voz alta (quien dicta no ve la terminal)")
    trozos.add_argument("--carpeta", default=None,
                        help="donde guardar los wav (por defecto eval/audio_wake). "
                             "Dos tandas distintas NO deben mezclarse en la "
                             "misma carpeta: --umbrales las leeria juntas")
    args = trozos.parse_args()

    if args.carpeta:
        global CARPETA
        CARPETA = Path(args.carpeta)

    if args.aplicar and not args.calibrar:
        # `--aplicar` solo escribe lo que calcula `--calibrar`. Suelto no
        # tiene nada que guardar, y aceptarlo en silencio dejaria a
        # alguien creyendo que ya toco el ajuste.
        print("`--aplicar` va con `--calibrar`: es lo que guarda su")
        print("resultado. Suelto no hay nada que escribir.")
        return 2

    if args.calibrar:
        return calibrar(args.idioma, args.aplicar)

    if args.falsos_grabados:
        falsos_en_lo_grabado(args.idioma)
        return 0

    if args.umbrales:
        repasar_umbrales([0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
        return 0

    if args.activaciones:
        intentos = medir_activaciones(args.activaciones, args.umbral,
                                      args.segundos, args.guardar,
                                      con_voz=args.con_voz,
                                      modelo=_ruta_modelo(args.modelo))
        validos = [i for i in intentos if i.hubo_habla]
        mudos = [i for i in intentos if not i.hubo_habla]
        aciertos = sum(1 for i in validos if i.activo)

        if mudos:
            # NO entran en el denominador: en esos no hablo nadie, asi que
            # no dicen nada del wake word. Contarlos como fallos seria
            # culpar al modelo de un aviso que no se oyo a tiempo.
            print(f"\n  {len(mudos)} intento(s) SIN HABLA, fuera de la cuenta: "
                  + ", ".join(f"#{i.numero}" for i in mudos))
        if not validos:
            print("\n  NINGUN intento tuvo habla. Esta tanda no mide nada.")
            return 0

        puntos = sorted(i.mejor for i in validos)
        print(f"\n  activaciones   {aciertos}/{len(validos)} con umbral "
              f"{args.umbral}")
        print("                 (solo los intentos en que SI hablaste)")
        print(f"  puntuacion     min {puntos[0]:.3f} | mediana "
              f"{statistics.median(puntos):.3f} | max {puntos[-1]:.3f}")
        fallidos = [i for i in validos if not i.activo]
        if fallidos:
            print(f"  los {len(fallidos)} que no entraron: "
                  + ", ".join(f"#{i.numero} ({i.mejor:.3f})" for i in fallidos))
            print("  Si varios rondan el umbral, es cuestion de umbral. Si estan")
            print("  cerca de cero, es que el modelo no reconoce como lo dices.")
        if args.guardar:
            print(f"\n  wav en {CARPETA} -- ahora `--umbrales` compara sin")
            print("  que tengas que volver a hablar.")
        return 0

    if args.falsos:
        falsos, horas = medir_falsos(args.falsos, args.umbral)
        print(f"\n  falsos positivos  {falsos} en {horas*60:.0f} min")
        if horas > 0:
            print(f"  ritmo             {falsos/horas:.1f} por hora")
        if falsos <= 2:
            print("\n  OJO: con 0, 1 o 2 sucesos esta tanda no ha respondido")
            print("  nada sobre la TASA. Solo dice que no se dispara a todas")
            print("  horas; para un ritmo hace falta escuchar mucho mas.")
        return 0

    trozos.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
