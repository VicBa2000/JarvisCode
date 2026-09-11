"""Audio device selection and level checks for the voice subsystem.

WHY THIS MODULE EXISTS (it is not in the original layout; see ADR-0030).
`wake.py`, `vad.py` and `stt.py` all need the same microphone and
`tts.py` needs the same speaker. Without a shared place, each of them
would repeat the device choice, and on THIS machine that choice is not
trivial: there are 23 active audio endpoints and 16 of them are virtual
virtual audio cables. Recording from a virtual cable does not fail --
it returns perfect digital silence.

THE FAILURE THIS MODULE IS BUILT AGAINST (the lesson of
2026-08-21): silence has two opposite meanings -- "the user said
nothing" and "we are listening to the wrong device" -- and if both leave
through the same door, the wrong-device case is invisible. So
`medir_nivel` answers with THREE states, never two.

MEASURED ON THIS MACHINE (2026-08-20), which is why DirectSound is the
default host API:

    host API      remuestrea a 16 kHz   nombre del dispositivo
    MME                   si            cortado a 31 chars
    DirectSound           si            completo (46 chars)
    WASAPI                NO            completo

WASAPI shared mode accepts exactly ONE sample rate per device, its
native one: a USB webcam is usually natively 16 kHz (what openWakeWord, silero-vad
and faster-whisper all want) but the board's microphone is 44.1 kHz and
a USB microphone is typically 48 kHz. Choosing DirectSound means the
host API resamples and Jarvis does not carry a resampler of its own --
one less piece in the latency budget, and one less place to put
a bug.
"""

from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from nucleo.configuracion import load_general_config

# What openWakeWord, silero-vad and faster-whisper all consume. Not a
# preference: all three are trained at this rate.
SAMPLE_RATE_VOZ = 16000

# See the table in the module docstring.
HOST_API_POR_DEFECTO = "Windows DirectSound"

# Below this RMS the device is handing us digital silence: not a quiet
# room, but bytes that carry no signal. A real microphone always has a
# noise floor, so this is the signature of a dead or virtual endpoint.
#
# >>> 7e-5 Y NO 1e-5, Y EL VIEJO ERA CODIGO MUERTO (2026-08-26) <<<
# Estaba en 1e-5, o sea -100 dBFS. Se midieron los 13 endpoints de
# entrada de esta maquina, 0,4 s cada uno, y las dos poblaciones salen
# separadisimas -- pero el umbral estaba POR DEBAJO de la mala:
#
#     10 cables virtuales / muertos   -96.7 dBFS   rms 1.46e-05  (todos
#         (9 cables virtuales + 1 camara)             el MISMO valor: es
#                                                   el bit menos
#                                                   significativo de 16)
#      4 microfonos de verdad         -69.8 dBFS   rms 3.24e-04  (placa)
#                                     -53.9        2.01e-03  (micro USB)
#                                     -43.5        6.70e-03  (webcam)
#
# Con 1e-5 la guarda NUNCA se disparaba: 1.46e-05 > 1e-05, asi que el
# cable virtual pasaba por microfono bueno y `Nivel.sin_senal` era una
# comprobacion que no comprobaba nada. Lo destapo el boton de probar el
# microfono de la UI (`voz/prueba.py`), que es justo para lo que se hizo.
#
# 7e-5 (-83 dBFS) es la mitad GEOMETRICA del hueco de 26,9 dB que hay
# entre las dos nubes: ~13 dB de margen por cada lado. No se elige
# pegado a ningun dato.
UMBRAL_SIN_SENAL = 7e-5

# How far above the MEASURED noise floor a level has to sit before it is
# worth calling "something is happening". Relative on purpose: see
# `calibrar_suelo`.
MARGEN_SOBRE_SUELO_DB = 8.0

Tipo = Literal["entrada", "salida"]

# >>> "EL QUE TENGA WINDOWS PUESTO" (2026-08-26, peticion del usuario) <<<
# Puesto en `voz.audio.entrada` o `voz.audio.salida` de la config, se
# resuelve al dispositivo predeterminado del SISTEMA en vez de a un
# nombre fijo. Es lo que uno espera de una aplicacion de escritorio: si
# enchufas unos cascos, Jarvis habla por los cascos.
#
# BAJO DirectSound ESO ES GRATIS Y ADEMAS ES EN VIVO. PortAudio expone
# ahi un dispositivo virtual -- "Controlador primario de sonido" -- que
# NO es un aparato concreto sino un alias del predeterminado de Windows,
# y sigue los cambios sin reiniciar nada. Comprobado el 2026-08-26:
#     Windows dice      Altavoces (tu tarjeta de sonido)
#     DirectSound da    [40] Controlador primario de sonido
#     WASAPI da         [62] Altavoces (tu tarjeta de sonido)
#
# >>> Y LA ASIMETRIA ENTRE ENTRADA Y SALIDA ES DELIBERADA <<<
# Para la SALIDA seguir al sistema es lo correcto y ademas es seguro: si
# el audio se va al sitio equivocado, no lo oyes, y no oir a Jarvis se
# nota al segundo. Para la ENTRADA es peligroso, y es la trampa medida
# que abre el docstring de este modulo: 16 de los 23 endpoints de esta
# maquina son cables de audio virtuales que entregan silencio
# digital perfecto SIN dar error. Un microfono equivocado no se nota --
# escucharias para siempre sin oir nada --, asi que ahi el centinela se
# permite pero NO es el valor por defecto, y quien lo ponga se lo tiene
# que probar con el boton de la UI.
PREDETERMINADO = "sistema"


class AudioError(RuntimeError):
    """No usable audio device, or the configured one is not present."""


@dataclass(frozen=True)
class Dispositivo:
    """One audio endpoint, already resolved to a PortAudio index."""

    indice: int
    nombre: str
    host_api: str
    canales: int
    sample_rate_nativo: int

    def __str__(self) -> str:
        return f"[{self.indice}] {self.nombre} ({self.host_api})"


@dataclass(frozen=True)
class Suelo:
    """A microphone's measured idle noise floor, in dBFS."""

    dbfs: float
    minimo: float
    maximo: float
    tomas: int

    @property
    def estable(self) -> bool:
        """A floor that swings more than this was measured in a noisy room."""
        return (self.maximo - self.minimo) <= 6.0

    def describe(self) -> str:
        estado = "estable" if self.estable else "INESTABLE (¿habia ruido al calibrar?)"
        return (
            f"suelo {self.dbfs:.1f} dBFS "
            f"[{self.minimo:.1f} .. {self.maximo:.1f}] "
            f"en {self.tomas} tomas, {estado}"
        )


@dataclass(frozen=True)
class Nivel:
    """The result of listening to a device for a moment.

    THREE states, deliberately. `sin_senal` and `silencio` are
    not the same answer and must never be collapsed: the first says the
    device is wrong, the second says the user is quiet.
    """

    rms: float
    pico: float
    segundos: float

    @property
    def dbfs(self) -> float:
        return 20 * math.log10(self.rms) if self.rms > 0 else -999.0

    @property
    def sin_senal(self) -> bool:
        """The endpoint delivers digital silence: it is not a microphone.

        Absolute and device-independent on purpose. Every real capture
        path has a noise floor, so bytes that are essentially zero mean
        the endpoint is dead or virtual, whatever microphone is wired.
        """
        return self.rms < UMBRAL_SIN_SENAL

    def supera(self, suelo: Suelo, margen_db: float = MARGEN_SOBRE_SUELO_DB) -> bool:
        """Whether this level sits clearly above a MEASURED noise floor.

        Takes the floor as an argument instead of comparing against a
        constant because the floor belongs to the microphone, not to the
        system: the webcam mic on this machine idles at -31 dBFS (measured, 6 takes,
        1.6 dB of spread) while a condenser USB microphone idles far
        lower. A fixed threshold would be right for one of them and
        wrong for the other.

        This is a hint for startup checks, NEVER a VAD. Deciding where
        speech starts and ends is silero's job in 5.3.
        """
        return not self.sin_senal and self.dbfs > suelo.dbfs + margen_db

    def describe(self) -> str:
        if self.sin_senal:
            return (
                f"SIN SENAL: el dispositivo entrega silencio digital "
                f"(RMS {self.rms:.2e}). No es un microfono real o esta mudo."
            )
        return f"{self.dbfs:.1f} dBFS (pico {self.pico:.3f})"


def _sd() -> Any:
    """Import sounddevice late so importing this module never opens PortAudio."""
    try:
        import sounddevice
    except ImportError as exc:  # pragma: no cover - depends on the venv
        raise AudioError(
            "sounddevice no esta instalado; es una dependencia de la Fase 5"
        ) from exc
    return sounddevice


def listar(
    tipo: Tipo = "entrada", host_api: str = HOST_API_POR_DEFECTO
) -> list[Dispositivo]:
    """Every endpoint of one kind under one host API, in PortAudio order."""
    sd = _sd()
    clave = "max_input_channels" if tipo == "entrada" else "max_output_channels"
    apis = sd.query_hostapis()
    encontrados = []
    for indice, datos in enumerate(sd.query_devices()):
        if datos[clave] <= 0:
            continue
        nombre_api = apis[datos["hostapi"]]["name"]
        if nombre_api != host_api:
            continue
        encontrados.append(
            Dispositivo(
                indice=indice,
                nombre=datos["name"],
                host_api=nombre_api,
                canales=datos[clave],
                sample_rate_nativo=int(datos["default_samplerate"]),
            )
        )
    return encontrados


def _generacion(nombre: str) -> int:
    """The re-enumeration number Windows puts in front of a device name.

    'Microfono (3- Webcam USB)' -> 3. Devices that never got
    unplugged carry no number, which is generation 0 and loses only
    against a device that HAS one -- i.e. against a later plug of itself.
    """
    import re

    encontrado = re.search(r"\((\d+)-\s", nombre)
    return int(encontrado.group(1)) if encontrado else 0


def predeterminado(tipo: Tipo = "entrada",
                   host_api: str = HOST_API_POR_DEFECTO) -> Dispositivo | None:
    """El dispositivo que Windows tiene puesto por defecto, o None.

    Devuelve None y NO levanta si el host API no declara ninguno: "no lo
    se" es una respuesta distinta de "no hay", y quien llama decide.
    """
    sd = _sd()
    try:
        apis = sd.query_hostapis()
    except Exception as exc:  # noqa: BLE001
        raise AudioError(f"No se pudo consultar PortAudio: {exc}") from exc

    clave = "default_input_device" if tipo == "entrada" else "default_output_device"
    for api in apis:
        if api.get("name") != host_api:
            continue
        indice = api.get(clave)
        if indice is None or indice < 0:
            return None
        for d in listar(tipo, host_api):
            if d.indice == indice:
                return d
        return None
    return None


def nombre_del_predeterminado(tipo: Tipo = "entrada") -> str:
    """Como se llama de verdad el predeterminado de Windows.

    POR QUE NO SALE DE `predeterminado()`: bajo DirectSound ese aparato
    es un ALIAS ("Controlador primario de sonido"), asi que decir su
    nombre no le dice al usuario por donde va a salir el audio. WASAPI si
    resuelve su defecto al aparato concreto -- comprobado contra la
    propia API de Windows el 2026-08-26, coincide en entrada y salida --,
    asi que se USA el alias de DirectSound y se ENSEÑA el nombre de
    WASAPI. Son la misma cosa vista de dos maneras.

    Cadena vacia si no se sabe. NUNCA se inventa un nombre: en un panel
    de ajustes, un nombre inventado es peor que un hueco.
    """
    try:
        d = predeterminado(tipo, host_api="Windows WASAPI")
    except AudioError:
        return ""
    return d.nombre if d is not None else ""


def seleccionar(
    candidatos: list[str],
    tipo: Tipo = "entrada",
    host_api: str = HOST_API_POR_DEFECTO,
) -> Dispositivo:
    """Resolve the first name in `candidatos` that is present, in order.

    `candidatos` is an ORDERED preference list, which is what makes a
    microphone that is not always plugged in (a USB one) work without
    editing the config: name it first, and it is used when present.

    NEVER falls back to the system default. On this machine the default
    can be a virtual audio cable, and a silent fallback is precisely the
    failure the module docstring describes: the pipeline would keep
    running and hear nothing forever. A device that was asked for and is
    missing is an error that says so, and lists what IS there.
    """
    disponibles = listar(tipo, host_api)
    if not disponibles:
        raise AudioError(
            f"No hay ningun dispositivo de {tipo} bajo el host API '{host_api}'."
        )
    for buscado in candidatos:
        aguja = buscado.strip().lower()
        if not aguja:
            continue
        if aguja == PREDETERMINADO:
            # No se cuela por el emparejamiento de nombres: es un alias,
            # no un aparato, y buscar "sistema" entre los nombres no
            # casaria con nada. Si el host API no declara defecto, se
            # sigue con el resto de la lista en vez de fallar: la lista
            # ES una lista de preferencias.
            elegido = predeterminado(tipo, host_api)
            if elegido is not None:
                return elegido
            continue
        casan = [d for d in disponibles if aguja in d.nombre.lower()]
        if casan:
            # EL MAS NUEVO GANA, y esto costo una tarde el 2026-08-20.
            # Al desconectar y volver a conectar un USB, Windows lo
            # reenumera con el prefijo incrementado -- "(2- Webcam
            # USB)" pasa a "(3- Webcam USB)" -- y DEJA EL VIEJO
            # EN LA LISTA, con estado OK y todo. El fantasma no da error
            # al abrirlo: se queda esperando para siempre, que es el modo
            # de fallo mas caro de este subsistema.
            # Un nombre parcial casa con los dos, asi que hay que
            # desempatar, y el criterio no puede ser el orden de la lista
            # (el fantasma va primero, por indice mas bajo).
            return max(casan, key=lambda d: (_generacion(d.nombre), d.indice))
    inventario = "\n".join(f"    {d}" for d in disponibles)
    raise AudioError(
        f"Ninguno de los dispositivos de {tipo} configurados esta presente.\n"
        f"  buscados (en orden): {candidatos}\n"
        f"  disponibles bajo '{host_api}':\n{inventario}\n"
        f"  Se corrige en config/jarvis.yaml (voz.audio)."
    )


def _procesos_vivos() -> set[str]:
    """Executable names currently running, lowercased. Empty if unknown."""
    import subprocess

    try:
        salida = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout
    except Exception:  # noqa: BLE001 - diagnostico, nunca una via de fallo
        return set()
    nombres = set()
    for linea in salida.splitlines():
        if linea.startswith('"'):
            nombres.add(linea.split('","')[0].strip('"').lower())
    return nombres


def quien_usa_el_microfono() -> list[str]:
    """Applications holding the microphone right now, per Windows itself.

    Windows records microphone use under CapabilityAccessManager, and a
    key whose `LastUsedTimeStop` is 0 has it open at this moment. Reading
    it costs milliseconds and turns the worst failure in this subsystem
    -- a capture that hangs with no error -- into a sentence naming the
    program to close.

    Returns an empty list when nothing holds it, and also when the
    registry cannot be read: this is a diagnostic aid, and it must never
    become a second way for recording to fail.
    """
    try:
        import winreg
    except ImportError:  # pragma: no cover - not Windows
        return []

    rutas = [
        (
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion"
            r"\CapabilityAccessManager\ConsentStore\microphone",
        ),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion"
            r"\CapabilityAccessManager\ConsentStore\microphone",
        ),
    ]
    en_uso: list[str] = []

    vivos = _procesos_vivos()

    def _revisar(clave, nombre: str) -> None:
        try:
            valor, _ = winreg.QueryValueEx(clave, "LastUsedTimeStop")
        except OSError:
            return
        if valor != 0:
            return
        # Las subclaves guardan la ruta con '#' en vez de '\'.
        legible = nombre.replace("#", "\\").split("\\")[-1] or nombre
        # LA BANDERA SOLA MIENTE. Medido el 2026-08-20: Discord aparecia
        # con LastUsedTimeStop=0 llevando horas cerrado, porque un
        # programa que muere sin cerrar limpiamente nunca escribe la hora
        # de fin y deja la marca puesta para siempre. Acusar a un proceso
        # muerto manda a quien lee el error a cerrar algo que no existe,
        # que es peor que no decir nada.
        if legible.lower() not in vivos:
            return
        # NO ACUSARSE A UNO MISMO. Jarvis es Python y el proceso que
        # graba tiene el microfono abierto por definicion, asi que
        # 'python.exe' sale SIEMPRE en esta lista y mandaria a cerrar
        # justo el programa que esta preguntando. El registro no guarda
        # PIDs, asi que no hay forma de distinguir otro Python del
        # nuestro: se descarta el nombre entero y se pierde el caso raro
        # de dos Jarvis a la vez, que es mucho mejor que dar un consejo
        # absurdo en todos los demas.
        if legible.lower() == Path(sys.executable).name.lower():
            return
        if legible not in en_uso:
            en_uso.append(legible)

    for raiz, ruta in rutas:
        try:
            with winreg.OpenKey(raiz, ruta) as base:
                indice = 0
                while True:
                    try:
                        nombre = winreg.EnumKey(base, indice)
                    except OSError:
                        break
                    indice += 1
                    try:
                        with winreg.OpenKey(base, nombre) as sub:
                            _revisar(sub, nombre)
                            # Las apps empaquetadas cuelgan un nivel mas.
                            hijo = 0
                            while True:
                                try:
                                    nieto = winreg.EnumKey(sub, hijo)
                                except OSError:
                                    break
                                hijo += 1
                                with winreg.OpenKey(sub, nieto) as sub2:
                                    # `nieto`, no `nombre`: bajo
                                    # 'NonPackaged' cuelga una clave por
                                    # aplicacion, y es la hija la que
                                    # lleva la ruta del ejecutable. Pasar
                                    # el padre daba 'NonPackaged' como
                                    # culpable, que no es nadie.
                                    _revisar(sub2, nieto)
                    except OSError:
                        continue
        except OSError:
            continue
    return en_uso


def grabar(
    dispositivo: Dispositivo, segundos: float, margen_s: float = 5.0
) -> "np.ndarray":
    """Record from one device with an EXPLICIT stream, never `sd.rec`.

    WHY NOT `sd.rec`, which is one line and was the first version:
    sounddevice's convenience functions (`play`, `rec`, `wait`) share one
    module-level stream. Play a prompt and then record in the same
    process and `sd.rec` blocks forever -- measured on 2026-08-20, the
    dictation harness hung at "GRABANDO..." until the process was killed.
    Nothing raises; it simply never returns, which from the other side of
    the microphone looks exactly like a broken program.

    It is the output-side lesson repeating on the input side: the audio
    call that misbehaves does not fail, it waits. So there is also a HARD
    CAP -- a recording that cannot finish raises instead of hanging,
    because a voice assistant that stops answering is worse than one that
    says it broke.

    IF IT TIMES OUT, SUSPECT ANOTHER APPLICATION FIRST. Measured on
    2026-08-20: after 40 good recordings the microphone started hanging
    with no code change, and the holder was Discord sitting in a voice
    channel. A device that another program has open does not return an
    error here -- it blocks. Windows names the culprit in the registry,
    which is faster than guessing:

        HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\
            CapabilityAccessManager\\ConsentStore\\microphone\\...

    A subkey whose `LastUsedTimeStop` is 0 is using the microphone RIGHT
    NOW. Second suspect: a process killed mid-recording, which is the
    other way this device gets stuck -- and the reason the cap above
    exists at all, since a program that fails cleanly never needs to be
    killed.
    """
    import queue

    import numpy as np

    sd = _sd()
    total = int(segundos * SAMPLE_RATE_VOZ)
    cola: queue.Queue = queue.Queue()

    def entrando(datos, _frames, _tiempo, _estado):  # noqa: ANN001
        cola.put(datos.copy())

    trozos: list[np.ndarray] = []
    recogido = 0
    limite = time.monotonic() + segundos + margen_s
    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE_VOZ,
            channels=1,
            device=dispositivo.indice,
            dtype="float32",
            callback=entrando,
        ):
            while recogido < total:
                restante = limite - time.monotonic()
                if restante <= 0:
                    ocupantes = quien_usa_el_microfono()
                    culpable = (
                        f"\n  LO TIENE TOMADO: {', '.join(ocupantes)}. "
                        f"Ciérralo o cambiale el dispositivo de entrada."
                        if ocupantes
                        else "\n  Nadie figura usandolo; revisa si un proceso "
                        "murio a media grabacion (eso deja el micro bloqueado "
                        "hasta desconectarlo)."
                    )
                    raise AudioError(
                        f"La grabacion de {segundos:.1f} s en {dispositivo} no "
                        f"termino en {segundos + margen_s:.1f} s. Llegaron "
                        f"{recogido / SAMPLE_RATE_VOZ:.1f} s de audio.{culpable}"
                    )
                try:
                    trozo = cola.get(timeout=min(restante, 0.5))
                except queue.Empty:
                    continue
                trozos.append(trozo)
                recogido += len(trozo)
    except AudioError:
        raise
    except Exception as exc:  # noqa: BLE001 - PortAudio raises many types
        raise AudioError(f"No se pudo grabar de {dispositivo}: {exc}") from exc

    return np.concatenate(trozos)[:total].reshape(-1)


def grabar_hasta(
    dispositivo: Dispositivo,
    cerrar,
    tope_s: float,
    margen_s: float = 5.0,
) -> "tuple[np.ndarray, bool]":
    """Record for as long as it takes, and let `cerrar` decide when to stop.

    EL HERMANO DE `grabar` PARA CUANDO NO SE SABE LA DURACION (JC-0013).
    `grabar` pide N segundos porque quien llama los sabe -- un banco, una
    sonda. Un turno de palabra no: lo largo que sea depende de lo que el
    usuario quiera decir, y fijarlo de antemano es lo que le cortaba a
    mitad de frase.

    `cerrar(trozo)` recibe cada bloque segun entra y devuelve algo con
    valor de verdad cuando ya se puede parar. Esta funcion NO sabe que es
    el habla: la decision de fin de turno vive en `voz/vad.py`, y aqui
    solo esta el microfono.

    DOS RELOJES, Y NO SON EL MISMO (tres salidas):

      * `tope_s` -- el MAXIMO ABSOLUTO de audio que se acepta. Cierra
        normal y se avisa devolviendo True. Es la red por si el detector
        no cierra nunca, y por eso no puede faltar: sin el, un VAD que se
        equivoca es una grabacion infinita.
      * `margen_s` -- cuanto se aguanta SIN QUE LLEGUE NADA. Se reinicia
        con cada trozo, asi que no limita lo que dure el turno: limita el
        silencio del DRIVER. Esto SI es un fallo y levanta `AudioError`,
        que es la leccion cara de `grabar`: la llamada de audio que se
        porta mal no falla, espera. Un cuelgue asi costo un reinicio del
        PC el 2026-08-20.

    Devuelve `(audio, llego_al_tope)`.
    """
    import queue

    import numpy as np

    sd = _sd()
    tope_muestras = int(tope_s * SAMPLE_RATE_VOZ)
    cola: queue.Queue = queue.Queue()

    def entrando(datos, _frames, _tiempo, _estado):  # noqa: ANN001
        cola.put(datos.copy())

    trozos: list[np.ndarray] = []
    recogido = 0
    llego_al_tope = False
    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE_VOZ,
            channels=1,
            device=dispositivo.indice,
            dtype="float32",
            callback=entrando,
        ):
            limite_entrega = time.monotonic() + margen_s
            while True:
                restante = limite_entrega - time.monotonic()
                if restante <= 0:
                    ocupantes = quien_usa_el_microfono()
                    culpable = (
                        f"\n  LO TIENE TOMADO: {', '.join(ocupantes)}. "
                        f"Ciérralo o cambiale el dispositivo de entrada."
                        if ocupantes
                        else "\n  Nadie figura usandolo; revisa si un proceso "
                        "murio a media grabacion (eso deja el micro bloqueado "
                        "hasta desconectarlo)."
                    )
                    raise AudioError(
                        f"El microfono {dispositivo} dejo de entregar audio "
                        f"durante {margen_s:.1f} s. Llegaron "
                        f"{recogido / SAMPLE_RATE_VOZ:.1f} s.{culpable}"
                    )
                try:
                    trozo = cola.get(timeout=min(restante, 0.5))
                except queue.Empty:
                    continue

                limite_entrega = time.monotonic() + margen_s
                trozos.append(trozo)
                recogido += len(trozo)

                if recogido >= tope_muestras:
                    llego_al_tope = True
                    break
                if cerrar(trozo):
                    break
    except AudioError:
        raise
    except Exception as exc:  # noqa: BLE001 - PortAudio raises many types
        raise AudioError(f"No se pudo grabar de {dispositivo}: {exc}") from exc

    if not trozos:
        return np.zeros(0, dtype="float32"), llego_al_tope
    return np.concatenate(trozos)[:tope_muestras].reshape(-1), llego_al_tope


def reproducir(
    audio: "np.ndarray",
    sample_rate: int,
    dispositivo: Dispositivo,
    margen_s: float = 5.0,
) -> None:
    """Play a buffer through one device, waiting until it has been heard.

    Explicit callback stream for the same two reasons as `grabar`: the
    module-level `sd.play` shares state with `sd.rec` and deadlocks when
    both are used, and PortAudio's blocking write silently discards audio
    under DirectSound (see `voz.tts.TTS.hablar`).
    """
    import queue

    import numpy as np

    sd = _sd()
    plano = np.ascontiguousarray(np.asarray(audio, dtype="float32").reshape(-1))
    posicion = 0
    terminado = queue.Queue(maxsize=1)

    def saliendo(buffer, frames, _tiempo, _estado):  # noqa: ANN001
        nonlocal posicion
        trozo = plano[posicion : posicion + frames]
        buffer[: len(trozo), 0] = trozo
        if len(trozo) < frames:
            buffer[len(trozo) :, 0] = 0.0
            posicion = len(plano)
            terminado.put(True)
            raise sd.CallbackStop
        posicion += frames

    duracion = len(plano) / sample_rate
    try:
        with sd.OutputStream(
            samplerate=sample_rate,
            channels=1,
            device=dispositivo.indice,
            dtype="float32",
            callback=saliendo,
        ):
            try:
                terminado.get(timeout=duracion + margen_s)
            except queue.Empty as exc:
                raise AudioError(
                    f"La reproduccion de {duracion:.1f} s en {dispositivo} no "
                    f"termino a tiempo."
                ) from exc
    except AudioError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AudioError(f"No se pudo reproducir en {dispositivo}: {exc}") from exc


def medir_nivel(dispositivo: Dispositivo, segundos: float = 1.0) -> Nivel:
    """Record for a moment and report how much energy arrived.

    This is the check that tells a real microphone from a virtual cable,
    and it is meant to run at startup: hearing nothing for a whole
    session because the wrong endpoint was chosen is a failure that
    otherwise nobody notices.
    """
    import numpy as np

    # Via `grabar` y no `sd.rec`: ver ahi por que la funcion de
    # conveniencia se cuelga en cuanto algo ha sonado antes.
    plano = np.asarray(grabar(dispositivo, segundos), dtype="float32").reshape(-1)
    return Nivel(
        rms=float(np.sqrt(np.mean(plano**2))) if plano.size else 0.0,
        pico=float(np.max(np.abs(plano))) if plano.size else 0.0,
        segundos=segundos,
    )


def calibrar_suelo(
    dispositivo: Dispositivo, tomas: int = 5, segundos: float = 1.0
) -> Suelo:
    """Measure a microphone's idle noise floor, several takes.

    Exists so that no threshold in the voice subsystem is a guess. The
    first version of this module compared against a hardcoded -50 dBFS
    and it was simply wrong for the microphone actually plugged in: the
    that webcam mic idles at -31 dBFS, so "quiet room" would have read as "signal"
    every single time, and the check would have passed while meaning
    nothing.

    Returns the spread as well as the floor, because a floor that moves
    a lot between takes is not a floor -- it means the room was not
    quiet while calibrating, and the caller deserves to know rather than
    to receive one confident number.
    """
    if tomas < 1:
        raise AudioError("calibrar_suelo necesita al menos una toma")
    lecturas = [medir_nivel(dispositivo, segundos).dbfs for _ in range(tomas)]
    return Suelo(
        dbfs=sum(lecturas) / len(lecturas),
        minimo=min(lecturas),
        maximo=max(lecturas),
        tomas=tomas,
    )


def _como_lista(valor: Any) -> list[str]:
    """Un nombre suelto tambien vale, y esto NO es una comodidad.

    `config/jarvis.yaml` declara los dispositivos como LISTA ordenada,
    pero el panel de ajustes guarda UNO solo -- un desplegable no puede
    expresar una cadena de respaldo. Sin esto, `list("sistema")` da
    ['s','i','s','t','e','m','a'] y se buscaria un microfono llamado "s":
    un fallo silencioso y ridiculo, encontrado el 2026-08-26 al cablear
    la superposicion de ajustes.
    """
    if valor is None:
        return []
    if isinstance(valor, str):
        return [valor]
    return [str(x) for x in valor]


@dataclass(frozen=True)
class ConfigAudio:
    """The `voz.audio` block of `config/jarvis.yaml`."""

    entrada: list[str]
    salida: list[str]
    host_api: str = HOST_API_POR_DEFECTO

    @classmethod
    def desde_config(cls, config_dir: Path | None = None) -> ConfigAudio:
        try:
            bloque = (load_general_config(config_dir) or {}).get("voz") or {}
            audio = bloque.get("audio") or {}
        except Exception as exc:  # noqa: BLE001
            raise AudioError(f"No se pudo leer config/jarvis.yaml: {exc}") from exc
        entrada = _como_lista(audio.get("entrada"))
        salida = _como_lista(audio.get("salida"))
        if not entrada or not salida:
            # An empty list would mean "any device", and "any device"
            # here means "possibly a virtual cable". Better to stop.
            raise AudioError(
                "config/jarvis.yaml no declara voz.audio.entrada y voz.audio.salida. "
                "Sin nombres explicitos no se elige dispositivo: el de por defecto "
                "de Windows puede ser un cable virtual."
            )
        return cls(
            entrada=entrada,
            salida=salida,
            host_api=str(audio.get("host_api") or HOST_API_POR_DEFECTO),
        )

    def microfono(self) -> Dispositivo:
        return seleccionar(self.entrada, "entrada", self.host_api)

    def altavoz(self) -> Dispositivo:
        return seleccionar(self.salida, "salida", self.host_api)
