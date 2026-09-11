"""El acceso directo que hace que Jarvis arranque con Windows.

SE PRUEBA CONTRA UN `.lnk` DE VERDAD, no contra un doble: se redirige la
carpeta Inicio a un temporal y se deja que PowerShell escriba y lea el
archivo binario real. Un doble de `WScript.Shell` habria probado que
sabemos llamar a nuestro propio doble, y lo que puede fallar
aqui esta justamente en el formato del `.lnk` y en el escapado de las
rutas.

LO QUE MAS SE PRUEBA es el estado APUNTA_MAL, porque es el unico que
falla EN SILENCIO: un acceso que apunta a un python que ya no existe no
da ningun error, simplemente no arranca nada, y el usuario se entera de
que "Jarvis ya no arranca solo" sin tener donde mirar. El `.venv` de
este proyecto ya se recreo una vez (2026-08-21, al pasar a 3.11).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from escritorio import inicio as mod
from escritorio.inicio import EstadoInicio

falta_powershell = pytest.mark.skipif(
    shutil.which("powershell") is None,
    reason="no hay powershell: el .lnk lo escribe WScript.Shell",
)

CARPETA = Path(r"C:\proyectos\carpetadepruebas")


@pytest.fixture
def inicio_falso(tmp_path, monkeypatch) -> Path:
    """La carpeta Inicio, redirigida. NO se toca la del usuario."""
    falsa = tmp_path / "Startup"
    falsa.mkdir()
    monkeypatch.setattr(mod, "carpeta_de_inicio", lambda: falsa)
    return falsa


@falta_powershell
def test_sin_acceso_directo_no_arranca(inicio_falso) -> None:
    actual = mod.estado(CARPETA)
    assert actual.estado is EstadoInicio.NO_PUESTO
    assert not actual.arranca


@falta_powershell
def test_ponerlo_lo_deja_arrancando_y_se_relee_de_disco(inicio_falso) -> None:
    """`poner` no se cree a si mismo: vuelve a leer el archivo.

    Es la regla del senuelo de JC-0007 aplicada aqui -- una comodidad que
    se da por instalada sin comprobarlo es la que luego no esta.
    """
    actual = mod.poner(CARPETA)
    assert actual.estado is EstadoInicio.PUESTO, actual.motivo
    assert actual.arranca
    assert (inicio_falso / mod.NOMBRE).is_file()
    # Y lo dice quien lo lee de nuevo, no solo quien lo escribio.
    assert mod.estado(CARPETA).estado is EstadoInicio.PUESTO


@falta_powershell
def test_apunta_al_pythonw_del_entorno_que_corre(inicio_falso) -> None:
    """>>> `pythonw.exe`, NO `python.exe` <<<

    Con el segundo, cada arranque de Windows abre una ventana de consola
    negra que se queda ahi todo el dia -- que es justo lo que esta
    carcasa viene a quitar, y la razon por la que tampoco se dejo un
    `.bat` en Inicio.
    """
    actual = mod.poner(CARPETA)
    assert Path(actual.destino).name.lower() == "pythonw.exe"
    assert Path(actual.destino) == Path(sys.executable).with_name("pythonw.exe")


@falta_powershell
def test_la_carpeta_de_trabajo_viaja_en_los_argumentos(inicio_falso) -> None:
    """Sin esto arrancaria acotado a otro sitio, que en un proyecto cuyo
    suelo se define por rutas no es un detalle cosmetico."""
    actual = mod.poner(CARPETA)
    assert str(CARPETA) in actual.argumentos
    assert "--voz" in actual.argumentos

    sin_voz = mod.poner(CARPETA, voz=False)
    assert "--voz" not in sin_voz.argumentos


@falta_powershell
def test_un_acceso_que_apunta_a_otro_python_NO_dice_que_arranca(
    inicio_falso, monkeypatch, tmp_path
) -> None:
    """>>> EL FALLO QUE NO DA ERROR <<<

    Se recrea el `.venv` (o se mueve el proyecto) y el acceso sigue ahi,
    apuntando a un interprete que ya no existe. No falla: no arranca. Si
    esto se contase como PUESTO, la casilla de la UI saldria marcada y el
    arranque no ocurriria -- que es la peor combinacion posible.
    """
    mod.poner(CARPETA)
    assert mod.estado(CARPETA).arranca

    otro = tmp_path / "venv_nuevo" / "Scripts" / "pythonw.exe"
    otro.parent.mkdir(parents=True)
    otro.write_bytes(b"")
    monkeypatch.setattr(mod, "_pythonw", lambda: otro)

    actual = mod.estado(CARPETA)
    assert actual.estado is EstadoInicio.APUNTA_MAL
    assert not actual.arranca
    assert actual.motivo


@falta_powershell
def test_apunta_mal_tampoco_es_lo_mismo_que_no_estar(inicio_falso,
                                                     monkeypatch,
                                                     tmp_path) -> None:
    """La otra mitad de la tercera salida: si APUNTA_MAL se contase como
    NO_PUESTO, "ponerlo" no diria nunca que lo que habia estaba roto."""
    mod.poner(CARPETA)
    otro = tmp_path / "otro" / "pythonw.exe"
    otro.parent.mkdir(parents=True)
    otro.write_bytes(b"")
    monkeypatch.setattr(mod, "_pythonw", lambda: otro)

    actual = mod.estado(CARPETA)
    assert actual.estado is not EstadoInicio.NO_PUESTO
    assert actual.ruta is not None and actual.ruta.is_file()


@falta_powershell
def test_arrancar_con_otras_opciones_tambien_es_apuntar_mal(
    inicio_falso,
) -> None:
    """Puesto con voz y consultado sin ella: no es lo que el usuario
    cree tener, asi que no se dice que este bien."""
    mod.poner(CARPETA, voz=True)
    actual = mod.estado(CARPETA, voz=False)
    assert actual.estado is EstadoInicio.APUNTA_MAL


@falta_powershell
def test_quitarlo_dos_veces_no_es_un_error(inicio_falso) -> None:
    """Que no estuviera no es un fallo: el final es el mismo."""
    mod.poner(CARPETA)
    assert mod.quitar().estado is EstadoInicio.NO_PUESTO
    assert not (inicio_falso / mod.NOMBRE).exists()
    assert mod.quitar().estado is EstadoInicio.NO_PUESTO


def test_la_carpeta_de_inicio_se_le_pregunta_a_windows() -> None:
    """No se construye a mano: cambia con el idioma del sistema y con las
    carpetas redirigidas, que con OneDrive no son las de siempre."""
    ruta = mod.carpeta_de_inicio()
    assert "%APPDATA%" not in str(ruta), "no se expandio la variable"
    assert ruta.name.lower() in ("startup", "inicio")


def test_describe_no_dice_que_arranca_cuando_no_arranca() -> None:
    """La UI lee esta frase. Un 'Arranca con Windows' sobre un acceso roto
    es exactamente la mentira que el estado APUNTA_MAL existe para
    evitar."""
    roto = mod.Inicio(estado=EstadoInicio.APUNTA_MAL, motivo="el venv se fue")
    frase = mod.describe(roto)
    assert "NO arrancaria" in frase
    assert "el venv se fue" in frase
