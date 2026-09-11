"""Baja los modelos que Jarvis necesita y que no vienen en el repositorio.

Son DOS descargas, viven en sitios distintos y se pierden en momentos
distintos, asi que se cuentan por separado:

    voz de Piper          -> `modelos/piper/`, carpeta del PROYECTO.
                             Sobrevive a rehacer el entorno virtual.
    openWakeWord          -> dentro de `site-packages`, o sea DENTRO del
                             `.venv`. Rehacer el entorno se los lleva.

>>> LA SEGUNDA NO ESTABA ESCRITA EN NINGUNA PARTE HASTA EL 2026-09-09 <<<
Ni en el README ni en la guia de publicacion. Se descubrio montando un
`.venv` nuevo para validar el release: el mismo arbol daba **17 tests en
rojo** -- 13 de wake word y 4 de VAD -- y `--voz` no arrancaba. Y no lo
cazaba ninguna guarda porque todas miraban el ARBOL, y estos archivos no
viven ahi. En esa misma descarga viene `silero_vad.onnx`, que es el VAD
entero: por eso `requirements.txt` no instala el paquete `silero-vad` de
PyPI, que arrastraria torch para hacer lo mismo.

>>> Y POR QUE ESTO EXISTE EN VEZ DE DOS LINEAS EN EL `.bat` <<<
Por el certificado. En la maquina del autor -- y en cualquiera con un
antivirus que intercepte HTTPS, o detras de un proxy de empresa -- las
dos descargas mueren con `CERTIFICATE_VERIFY_FAILED`, porque `requests`
verifica contra `certifi` y ahi no esta la CA que el antivirus se
inventa. Medido el 2026-09-09.

LA SALIDA NO ES `verify=False` NI `--trusted-host`, y no se negocia:
apagar la verificacion en un programa cuya premisa es la seguridad es
peor que no instalarlo. Lo que se hace es `truststore`, que le dice a
Python que verifique contra el ALMACEN DE WINDOWS -- donde esa CA ya
esta y donde el sistema ya la considera fiable, porque la puso el propio
antivirus al instalarse. Se verifica igual; cambia contra que lista.
Un `.bat` no puede hacer eso antes de un `-m`, y un `-c` de tres lineas
con `runpy` dentro es justo el tipo de cosa que se rompe callando.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# La voz por defecto de `config/base/jarvis.yaml`. Si algun dia cambia
# alli, este numero deja de valer -- y hay un test que lo comprueba.
VOZ_POR_DEFECTO = "es_ES-davefx-medium"
DIR_PIPER = PROJECT_ROOT / "modelos" / "piper"


def _con_el_almacen_del_sistema() -> str:
    """Verificar contra el almacen de Windows. Devuelve que paso.

    TRES respuestas y no dos: se inyecto / no hacia falta
    porque no esta el paquete / reviento. La tercera NO se traga: si
    `truststore` esta instalado y falla al inyectarse, eso hay que
    decirlo, porque la descarga que venga detras fallara por una razon
    que ya no sera esta.
    """
    try:
        import truststore
    except ImportError:
        return "sin truststore (se usa el almacen de Python)"
    try:
        truststore.inject_into_ssl()
    except Exception as exc:  # noqa: BLE001
        return f"truststore esta pero no se pudo usar: {exc}"
    return "verificando contra el almacen de Windows"


def _dir_openwakeword() -> Path | None:
    try:
        import openwakeword
    except ImportError:
        return None
    return Path(openwakeword.__file__).parent / "resources" / "models"


def hay_voz() -> bool:
    return (DIR_PIPER / f"{VOZ_POR_DEFECTO}.onnx").is_file()


def hay_escucha() -> bool:
    """Los CUATRO que se usan de verdad, no la carpeta a secas.

    Una carpeta que existe con la mitad dentro es el peor estado: parece
    hecho y revienta al arrancar la voz.
    """
    carpeta = _dir_openwakeword()
    if carpeta is None:
        return False
    return all((carpeta / n).is_file() for n in (
        "hey_jarvis_v0.1.onnx", "melspectrogram.onnx",
        "embedding_model.onnx", "silero_vad.onnx"))


def bajar_voz() -> tuple[bool, str]:
    if hay_voz():
        return True, f"la voz {VOZ_POR_DEFECTO} ya esta"
    DIR_PIPER.mkdir(parents=True, exist_ok=True)
    import runpy

    argv = sys.argv
    sys.argv = ["piper.download_voices", VOZ_POR_DEFECTO,
                "--download-dir", str(DIR_PIPER)]
    try:
        runpy.run_module("piper.download_voices", run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (0, None):
            return False, f"piper salio con codigo {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        sys.argv = argv
    # Se mira el DISCO, no lo que dijo el programa.
    if hay_voz():
        return True, "descargada"
    return False, "el programa termino y el archivo no esta"


def bajar_escucha() -> tuple[bool, str]:
    if hay_escucha():
        return True, "los modelos de escucha ya estan"
    try:
        import openwakeword.utils as utils

        utils.download_models()
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    if hay_escucha():
        return True, "descargados"
    return False, "el programa termino y los archivos no estan"


def main() -> int:
    print(f"  [...]   {_con_el_almacen_del_sistema()}")

    fallos = 0
    for etiqueta, faltante, funcion in (
        ("voz", "Jarvis arranca igual, pero NO hablara.", bajar_voz),
        ("escucha", "NO funcionaran ni la palabra de activacion ni el "
                    "detector de voz, o sea que `--voz` no arranca.",
         bajar_escucha),
    ):
        bien, detalle = funcion()
        if bien:
            print(f"  [OK]    {etiqueta}: {detalle}")
        else:
            fallos += 1
            print(f"  [FALLO] {etiqueta}: {detalle}")
            print(f"          {faltante}")
    return 1 if fallos else 0


if __name__ == "__main__":  # pragma: no cover - utilidad de mano
    raise SystemExit(main())
