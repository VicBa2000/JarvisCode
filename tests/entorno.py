"""Que le falta a ESTA instalacion, para no dar por roto lo que solo falta.

>>> POR QUE EXISTE (2026-09-08, preparando el release) <<<
Se probo la suite en un clon recien descargado -- el arbol exacto que se
publica, sin `modelos/` y sin la config del autor -- y salieron **19 en
rojo**. Ninguno era un fallo del codigo: eran cosas que un clon todavia
no tiene, y cada una lo decia perfectamente ("el perfil 'jarvis' usa
es_ES-davefx-medium, que no esta descargada"). Pero un recien llegado que
corre la suite y ve 19 rojos no lee 19 mensajes: cierra la carpeta.

>>> LA DISTINCION, Y ES LA DE LAS TRES SALIDAS <<<
Un test tiene TRES respuestas y no dos: pasa / falla / **no se puede
saber todavia**. Un modelo sin bajar y un microfono sin elegir son la
tercera, y colapsarla contra "falla" es el mismo error que colapsar "no
lo se" contra "si", solo que en la direccion que asusta en vez de en la
que tranquiliza. Un `skip` CON SU MOTIVO es una ausencia honesta: se ve, dice
que falta y dice como se arregla.

>>> LO QUE ESTO NO PUEDE HACER, Y POR ESO SE MIDE EN VEZ DE SUPONERSE <<<
Una guarda mal escrita se traga un fallo de verdad: si `HAY_VOCES` diera
False por un error nuestro, media capa de voz pasaria a "saltado" y la
suite se pondria verde MINTIENDO. Por eso cada predicado mira el disco y
nada mas -- ni versiones, ni contenido, ni sistema operativo --, y en la
maquina donde esto se desarrolla los tres dan True, o sea que alli no
salta ni uno. **Comprobado el 2026-09-08, y esa es la mitad que importa**:
en el arbol real la suite sigue dando **1467 pasan / 1 saltado**, el
mismo numero exacto que antes de existir este archivo. Si alguna de estas
guardas se disparase por error alla, ese numero bajaria.
En el clon virgen: **1442 pasan / 26 saltados / 0 rojos**, y cada saltado
dice que le falta y con que orden se arregla.
"""

from __future__ import annotations

from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

# --- 1. los modelos de voz: 745 MB que no viajan en git ----------------
# Son datos descargables y estan en `.gitignore` desde el primer commit.
# Ver el README para las dos ordenes que los bajan.
DIR_PIPER = RAIZ / "modelos" / "piper"
DIR_WHISPER = RAIZ / "modelos" / "whisper"

HAY_VOCES = DIR_PIPER.is_dir() and any(DIR_PIPER.glob("*.onnx"))
HAY_WHISPER = DIR_WHISPER.is_dir() and any(DIR_WHISPER.iterdir())

necesita_voces = pytest.mark.skipif(
    not HAY_VOCES,
    reason=(f"no hay voces de Piper en {DIR_PIPER}. Se bajan con "
            f"`python -m piper.download_voices es_ES-davefx-medium "
            f"--download-dir modelos/piper` (ver README)."),
)

necesita_whisper = pytest.mark.skipif(
    not HAY_WHISPER,
    reason=(f"no hay modelo de Whisper en {DIR_WHISPER}. `faster-whisper` "
            f"se lo baja solo la primera vez que se transcribe algo."),
)


# >>> Y HAY UN TERCER ESTADO QUE NADIE HABIA VISTO: **UNA SOLA VOZ** <<<
# (2026-09-09, al construir `instalar.bat`.) Hasta hoy solo existian dos
# entornos: el del autor, con las cinco voces bajadas desde agosto, y un
# clon virgen, con cero. `HAY_VOCES` es `any(*.onnx)`, o sea que "hay
# alguna" contaba como "estan todas" -- y con esos dos entornos nunca se
# noto, porque en uno no hay ninguna y en el otro estan todas.
#
# El instalador crea el estado de en medio: baja UNA, la de fabrica, que
# es lo correcto -- las cinco son 300 MB y nadie necesita cinco voces
# para empezar. Y ahi la suite daba **8 EN ROJO** en un doble clic
# recien hecho.
#
# LA REGLA, y son tres salidas otra vez: ninguna voz es un clon sin
# bajar; SOLO la de fabrica es una instalacion recien hecha; y "algunas
# pero no todas" si es un entorno incompleto y tiene que doler. Las dos
# primeras saltan, la tercera falla.
VOZ_DE_FABRICA = "es_ES-davefx-medium"
"""La unica que baja `scripts/bajar_modelos.py`. Si cambia alli, cambia
aqui: hay un test que lo comprueba."""

_DESCARGADAS = ({p.stem for p in DIR_PIPER.glob("*.onnx")}
                if DIR_PIPER.is_dir() else set())
INSTALACION_RECIEN_HECHA = _DESCARGADAS <= {VOZ_DE_FABRICA}

necesita_todas_las_voces = pytest.mark.skipif(
    INSTALACION_RECIEN_HECHA,
    reason=("esta instalacion solo tiene la voz de fabrica, que es lo que "
            f"baja el instalador. Lo que hay: {sorted(_DESCARGADAS) or 'nada'}. "
            "Este test comprueba que NINGUN perfil ni idioma declarado se "
            "quede sin su modelo, y eso solo significa algo en un entorno "
            "que las tiene todas. Se bajan con "
            "`python -m piper.download_voices <nombre> "
            "--download-dir modelos/piper`."),
)


# --- 2. el microfono: VACIO ES LA RESPUESTA CORRECTA de fabrica --------
# `config/base/jarvis.yaml` nace con `voz.audio.entrada: []` a proposito,
# y hay un test que lo exige (`test_config_base`): no se puede adivinar
# que aparatos tiene otra maquina, y 16 de los 23 endpoints medidos
# entregan silencio digital SIN dar error. O sea que hasta que alguien
# elige el suyo en Ajustes, los tests que necesitan un aparato de verdad
# no estan fallando: estan esperando a que se elija.
def _hay_dispositivo_elegido() -> bool:
    try:
        from nucleo.configuracion import load_general_config

        audio = load_general_config().get("voz", {}).get("audio", {})
    except Exception:
        # Sin config legible no se sabe, y "no se sabe" no es "si".
        return False
    return bool(audio.get("entrada")) and bool(audio.get("salida"))


HAY_DISPOSITIVO = _hay_dispositivo_elegido()

necesita_dispositivo = pytest.mark.skipif(
    not HAY_DISPOSITIVO,
    reason=("todavia no hay microfono elegido en config/jarvis.yaml "
            "(`voz.audio.entrada` esta vacio, que es como nace). Se elige "
            "en AJUSTES > Oir y hablar, y hay un boton de PROBARLO al "
            "lado: elegir a ciegas reparte un fallo mudo."),
)


# --- 3. los modelos de openWakeWord: NO viven en `modelos/` ------------
# >>> ESTE FALTABA, Y LA VALIDACION DEL RELEASE NO PODIA VERLO <<<
# (2026-09-09.) La del 09-08 corrio el clon virgen con el `.venv` DEL
# AUTOR, que lleva estos archivos bajados desde agosto. Con su propio
# `.venv`, recien hecho y siguiendo el README al pie de la letra, el
# mismo arbol da **17 EN ROJO**: 13 fallos de wake word y 4 errores de
# VAD, todos de aqui.
#
# LA TRAMPA ESTA EN DONDE VIVEN: los de Piper y Whisper van a `modelos/`,
# que es una carpeta del proyecto y se ve vacia. Estos los baja
# `openwakeword.utils.download_models()` DENTRO de site-packages, o sea
# dentro del entorno virtual, asi que cambiar de `.venv` los pierde y
# ninguna guarda que mire el arbol se entera. Es la misma forma que el
# `2>&1` o el acento grave: no falta una regla, falta que la regla mire
# donde esta el dato.
#
# Y EL VAD ENTRA AQUI AUNQUE NO LO PAREZCA: `silero_vad.onnx` llega en
# esta misma descarga -- por eso `requirements.txt` no trae el paquete
# `silero-vad` de PyPI, que arrastraria torch para hacer lo mismo --, asi
# que un clon sin la orden se queda sin wake word Y sin VAD, que es la
# capa de voz entera.
def _dir_openwakeword():
    try:
        import openwakeword

        return Path(openwakeword.__file__).parent / "resources" / "models"
    except Exception:
        # Sin el paquete no se sabe, y los tests que lo necesitan ya
        # revientan al importarlo: no es esta guarda quien lo dice.
        return None


_MODELOS_WAKE = _dir_openwakeword()
HAY_MODELOS_WAKE = bool(
    _MODELOS_WAKE
    and (_MODELOS_WAKE / "hey_jarvis_v0.1.onnx").is_file()
    and (_MODELOS_WAKE / "melspectrogram.onnx").is_file()
    and (_MODELOS_WAKE / "embedding_model.onnx").is_file()
    and (_MODELOS_WAKE / "silero_vad.onnx").is_file())

RAZON_MODELOS_WAKE = (
    "faltan los modelos de openWakeWord (wake word y VAD). Se bajan una "
    "vez, DENTRO de este .venv, con:\n"
    "  .venv\\Scripts\\python.exe -c \"import openwakeword.utils as u; "
    "u.download_models()\"\n"
    "(ver README). Van a site-packages, no a `modelos/`, asi que hay que "
    "repetirlo si se rehace el entorno.")

necesita_modelos_wake = pytest.mark.skipif(
    not HAY_MODELOS_WAKE, reason=RAZON_MODELOS_WAKE)


def saltar_si_faltan_modelos_wake() -> None:
    """Lo mismo, para dentro de una FIXTURE.

    Una marca `skipif` puesta sobre una fixture no la mira nadie -- pytest
    la ignora sin dar error --, y la fixture `vad` es el punto por donde
    pasan los siete tests de VAD que se caian. Aqui se salta desde
    dentro, que es lo unico que funciona.
    """
    if not HAY_MODELOS_WAKE:
        pytest.skip(RAZON_MODELOS_WAKE)
