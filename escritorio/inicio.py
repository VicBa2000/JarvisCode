"""Arrancar con Windows: un acceso directo en la carpeta Inicio.

>>> POR QUE UN ACCESO DIRECTO Y NO EL REGISTRO <<<
Decidido el 2026-08-24 y sigue siendo la razon: la carpeta Inicio es
REVERSIBLE (se borra un archivo), SE VE en el Administrador de tareas —
donde el usuario puede desactivarlo sin nosotros — y **no toca HKLM**,
que ademas esta en nuestra propia lista endurecida de JC-0001. Un
asistente que se instala escribiendo en el registro del sistema mientras
le prohibe eso mismo a su cerebro es incoherente, y la incoherencia en
una politica de seguridad es como se pierde la confianza en ella.

Y es la carpeta Inicio DEL USUARIO, no la de todos: no hace falta
administrador, y no se le mete nada a nadie mas de esta maquina.

>>> LO QUE FALLA EN SILENCIO AQUI, Y ES LA RAZON DE LA MITAD DEL CODIGO
El modo de fallo de un acceso directo no es que de un error: es que
APUNTE A ALGO QUE YA NO ESTA. El `.venv` de este proyecto se ha recreado
una vez (2026-08-21, para pasar a 3.11) y volvera a recrearse; el dia
que eso pase, un `.lnk` que apunte al python viejo arranca la nada y el
usuario se entera porque Jarvis "ya no arranca solo", sin nada que
mirar.

Por eso `estado()` tiene TRES respuestas y no dos:

    PUESTO        esta, y apunta a lo que deberia
    APUNTA_MAL    esta, pero a otro python u otra carpeta -> NO arranca
    NO_PUESTO     no esta

Colapsar `APUNTA_MAL` contra `PUESTO` es el error por defecto — la
casilla saldria marcada y el arranque no ocurriria — y colapsarlo contra
`NO_PUESTO` tampoco vale, porque entonces "ponerlo" no diria que lo que
habia estaba roto.

>>> EL `.lnk` SE CREA CON POWERSHELL, y es a proposito <<<
Un `.lnk` es un formato binario de Windows y quien lo escribe es
`WScript.Shell`, que es COM. La alternativa era `pywin32` — una
dependencia de 10 MB para escribir un archivo —, y la otra era dejar un
`.bat` en Inicio, que abre una consola negra en cada arranque: justo lo
que esta carcasa viene a quitar. PowerShell ya esta en la maquina.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# El nombre del acceso directo. Se busca por el, asi que cambiarlo deja
# huerfano el que hubiera puesto una version anterior.
NOMBRE = "Jarvis.lnk"


class EstadoInicio(str, Enum):
    """Tres respuestas, no dos. Ver el docstring del modulo."""

    PUESTO = "puesto"
    APUNTA_MAL = "apunta_mal"
    NO_PUESTO = "no_puesto"
    # Y una cuarta que no es un veredicto sino la ausencia de uno: no se
    # pudo mirar. Un "no lo se" NO se cuenta como "no puesto", porque
    # entonces la UI ofreceria ponerlo encima de algo que ya existe.
    NO_SE_SABE = "no_se_sabe"


@dataclass(frozen=True)
class Inicio:
    """Que hay ahora mismo en la carpeta Inicio, y si sirve."""

    estado: EstadoInicio
    ruta: Path | None = None
    destino: str = ""
    argumentos: str = ""
    motivo: str = ""
    """Por que APUNTA_MAL o NO_SE_SABE. Vacio en los otros dos."""

    @property
    def arranca(self) -> bool:
        """Si Jarvis arrancara de verdad con Windows tal y como esta."""
        return self.estado is EstadoInicio.PUESTO


def carpeta_de_inicio() -> Path:
    """La carpeta Inicio DEL USUARIO.

    Se pregunta a Windows en vez de construirla a mano: la ruta cambia
    con el idioma del sistema ("Inicio" / "Startup") y con las carpetas
    redirigidas, que en una maquina con OneDrive no son las de siempre.
    """
    return Path(
        os.path.expandvars(
            r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
        )
    )


def _pythonw() -> Path:
    """El interprete SIN consola del entorno que esta corriendo.

    `pythonw.exe` y no `python.exe`: con el segundo, cada arranque de
    Windows abre una ventana negra que se queda ahi todo el dia. Es la
    misma razon por la que se descarto el `.bat`.
    """
    return Path(sys.executable).with_name("pythonw.exe")


def argumentos_para(carpeta: Path, voz: bool = True) -> str:
    """Lo que se le pasa al interprete. Es tambien la HUELLA del acceso.

    `estado()` compara esto con lo que hay puesto, asi que si un dia se
    anaden mas opciones, el acceso viejo pasara a APUNTA_MAL y la UI lo
    dira -- que es mejor que arrancar con opciones distintas de las que
    el usuario cree tener.
    """
    partes = ["-m", "escritorio", f'"{carpeta}"']
    if voz:
        partes.append("--voz")
    # >>> `--oculto` SIEMPRE EN EL ARRANQUE DE WINDOWS <<<
    # Nadie quiere una ventana abriendosele en cada boot. Jarvis se va a
    # la bandeja y se abre cuando se le pide, que es como se comporta
    # cualquier cosa que arranca con el sistema.
    partes.append("--oculto")
    return " ".join(partes)


def _powershell(guion: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", guion],
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def estado(carpeta: Path | None = None, voz: bool = True) -> Inicio:
    """Que hay puesto, y si arrancaria.

    Si `carpeta` es None solo se comprueba que EXISTA y que su destino
    siga existiendo en disco; sin saber a que directorio deberia apuntar
    no se puede juzgar si apunta bien.
    """
    destino_lnk = carpeta_de_inicio() / NOMBRE
    if not destino_lnk.is_file():
        return Inicio(estado=EstadoInicio.NO_PUESTO)

    guion = (
        "$s = New-Object -ComObject WScript.Shell; "
        f"$a = $s.CreateShortcut('{destino_lnk}'); "
        "Write-Output $a.TargetPath; Write-Output $a.Arguments"
    )
    try:
        salida = _powershell(guion)
    except Exception as exc:  # noqa: BLE001
        return Inicio(
            estado=EstadoInicio.NO_SE_SABE,
            ruta=destino_lnk,
            motivo=f"no se pudo leer el acceso directo: {exc}",
        )
    if salida.returncode != 0:
        return Inicio(
            estado=EstadoInicio.NO_SE_SABE,
            ruta=destino_lnk,
            motivo=(salida.stderr or "").strip() or "PowerShell fallo",
        )

    lineas = [l.strip() for l in salida.stdout.splitlines()]
    apunta_a = lineas[0] if lineas else ""
    args = lineas[1] if len(lineas) > 1 else ""

    if not apunta_a or not Path(apunta_a).exists():
        return Inicio(
            estado=EstadoInicio.APUNTA_MAL,
            ruta=destino_lnk,
            destino=apunta_a,
            argumentos=args,
            motivo=(
                f"apunta a un interprete que ya no existe: {apunta_a or '(vacio)'}"
            ),
        )

    esperado = str(_pythonw())
    if Path(apunta_a) != Path(esperado):
        return Inicio(
            estado=EstadoInicio.APUNTA_MAL,
            ruta=destino_lnk,
            destino=apunta_a,
            argumentos=args,
            motivo=f"apunta a otro interprete; este entorno usa {esperado}",
        )

    if carpeta is not None:
        quiere = argumentos_para(carpeta, voz=voz)
        if args.strip() != quiere.strip():
            return Inicio(
                estado=EstadoInicio.APUNTA_MAL,
                ruta=destino_lnk,
                destino=apunta_a,
                argumentos=args,
                motivo=f"arrancaria con otras opciones: {args or '(ninguna)'}",
            )

    return Inicio(
        estado=EstadoInicio.PUESTO,
        ruta=destino_lnk,
        destino=apunta_a,
        argumentos=args,
    )


def poner(carpeta: Path, voz: bool = True) -> Inicio:
    """Crea (o rehace) el acceso directo, y COMPRUEBA que quedo bien.

    Se relee despues de escribir en vez de dar por hecho que funciono. Es
    la misma regla que el senuelo del suelo (JC-0007): una proteccion —
    o aqui una comodidad — que se da por instalada sin mirarlo es la que
    luego no esta.
    """
    inicio_dir = carpeta_de_inicio()
    if not inicio_dir.is_dir():
        return Inicio(
            estado=EstadoInicio.NO_SE_SABE,
            motivo=f"no existe la carpeta Inicio: {inicio_dir}",
        )

    destino_lnk = inicio_dir / NOMBRE
    fallo = _escribir_lnk(destino_lnk, argumentos_para(carpeta, voz=voz))
    if fallo is not None:
        return Inicio(estado=EstadoInicio.NO_SE_SABE, motivo=fallo)
    return estado(carpeta, voz=voz)


def _escribir_lnk(destino_lnk: Path, argumentos: str,
                  icono: Path | None = None) -> str | None:
    """Escribe UN acceso directo. Devuelve el motivo si no pudo, o None.

    >>> ESTO ERA EL CUERPO DE `poner` Y SE SACO EL 2026-09-09 <<<
    Al anadir el acceso del ESCRITORIO habia dos caminos posibles:
    copiar estas ocho lineas, o compartirlas. Copiarlas es como se
    separan dos cosas que tienen que decir lo mismo -- ya paso en este
    arbol con los tres normalizadores de `voz/` --, y aqui lo que
    comparten es delicado: el interprete SIN consola y el directorio de
    trabajo. Un acceso que apunte a `python.exe` abre una ventana negra
    para siempre; uno sin `WorkingDirectory` arranca en `System32` y no
    encuentra ni la config ni los modelos.
    """
    guion = (
        "$s = New-Object -ComObject WScript.Shell; "
        f"$a = $s.CreateShortcut('{destino_lnk}'); "
        f"$a.TargetPath = '{_pythonw()}'; "
        f"$a.Arguments = '{argumentos}'; "
        f"$a.WorkingDirectory = '{PROJECT_ROOT}'; "
        "$a.Description = 'Jarvis: asistente de voz con Claude Code'; "
        + (f"$a.IconLocation = '{icono}'; " if icono else "")
        + "$a.Save()"
    )
    try:
        salida = _powershell(guion)
    except Exception as exc:  # noqa: BLE001
        return f"no se pudo crear: {exc}"
    if salida.returncode != 0:
        return (salida.stderr or "").strip() or "PowerShell fallo"
    return None


def quitar() -> Inicio:
    """Lo borra. Que no estuviera NO es un error: el final es el mismo."""
    destino_lnk = carpeta_de_inicio() / NOMBRE
    try:
        destino_lnk.unlink(missing_ok=True)
    except OSError as exc:
        return Inicio(
            estado=EstadoInicio.NO_SE_SABE,
            ruta=destino_lnk,
            motivo=f"no se pudo borrar: {exc}",
        )
    return Inicio(estado=EstadoInicio.NO_PUESTO)


# --- el acceso del ESCRITORIO, que no es el del arranque --------------
# >>> Y NO SE UNIFICAN, PORQUE NO SIGNIFICAN LO MISMO <<<
# (2026-09-09, al preparar la publicacion.) Comparten como se escribe un
# `.lnk` -- eso es `_escribir_lnk` --, y nada mas:
#
#   arranque de Windows   va SIEMPRE con `--oculto`: nadie quiere una
#                         ventana abriendosele en cada boot. Se pone y
#                         se quita desde el menu de la bandeja, y tiene
#                         TRES estados porque nadie lo mira nunca.
#   escritorio            es lo contrario: lo pulsas TU para ver la
#                         ventana, asi que `--oculto` lo haria parecer
#                         roto -- doble clic y no pasa nada.
#
# Por eso este no reusa `argumentos_para`, que mete `--oculto` dentro.

NOMBRE_ESCRITORIO = "Jarvis.lnk"


def carpeta_del_escritorio() -> Path:
    """El Escritorio del usuario, preguntado a Windows.

    Igual que `carpeta_de_inicio`: a mano seria `%USERPROFILE%\\Desktop`,
    y eso es falso en cuanto hay OneDrive redirigiendo la carpeta o el
    sistema esta en otro idioma. Se pregunta al shell, y si no contesta
    se dice -- no se adivina una ruta y se escribe un archivo ahi.
    """
    salida = _powershell("[Environment]::GetFolderPath('Desktop')")
    ruta = (salida.stdout or "").strip()
    if salida.returncode == 0 and ruta:
        return Path(ruta)
    return Path(os.path.expandvars(r"%USERPROFILE%\Desktop"))


def _icono_en_disco() -> Path | None:
    """Un `.ico` para el acceso, generado una vez.

    `escritorio/icono.py` dibuja el icono EN MEMORIA a proposito, porque
    cambia de color con el estado y un archivo seria una copia que se
    queda vieja. Un acceso directo necesita una RUTA, asi que aqui se
    escribe uno fijo -- el del estado en reposo -- y se acepta que no
    parpadee: es un icono de lanzador, no un indicador.

    Si algo falla se devuelve None y el acceso se crea IGUAL, con el
    icono de `pythonw`. Feo, pero un lanzador feo lanza; uno que no se
    creo porque no habia icono, no.
    """
    try:
        from escritorio.icono import a_ico, dibujar

        destino = PROJECT_ROOT / "logs" / "jarvis.ico"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(a_ico(dibujar()))
        return destino
    except Exception:  # noqa: BLE001
        return None


def poner_en_el_escritorio(carpeta: Path | None = None,
                           voz: bool = True) -> Inicio:
    """Un acceso directo en el Escritorio. Se relee despues de escribir.

    `carpeta` puede ser None: `escritorio` la acepta opcional y cae a la
    que haya en AJUSTES. Es lo correcto para un lanzador -- si la carpeta
    fuera al `.lnk`, cambiarla en el panel dejaria el acceso apuntando a
    la vieja, sin error y sin sintoma, que es el fallo que esta carcasa
    ya se comio una vez.
    """
    escritorio_dir = carpeta_del_escritorio()
    if not escritorio_dir.is_dir():
        return Inicio(estado=EstadoInicio.NO_SE_SABE,
                      motivo=f"no existe el Escritorio: {escritorio_dir}")

    partes = ["-m", "escritorio"]
    if carpeta is not None:
        partes.append(f'"{carpeta}"')
    if voz:
        partes.append("--voz")

    destino_lnk = escritorio_dir / NOMBRE_ESCRITORIO
    fallo = _escribir_lnk(destino_lnk, " ".join(partes), _icono_en_disco())
    if fallo is not None:
        return Inicio(estado=EstadoInicio.NO_SE_SABE, ruta=destino_lnk,
                      motivo=fallo)
    if not destino_lnk.is_file():
        # Se relee en vez de fiarse del codigo de salida, igual que el
        # senuelo del suelo: PowerShell puede volver con 0 y no haber
        # dejado nada si el COM fallo por dentro.
        return Inicio(estado=EstadoInicio.NO_SE_SABE, ruta=destino_lnk,
                      motivo="PowerShell dijo que si y no hay archivo")
    return Inicio(estado=EstadoInicio.PUESTO, ruta=destino_lnk,
                  destino=str(_pythonw()), argumentos=" ".join(partes))


def describe(inicio: Inicio) -> str:
    """Una linea para la consola y para el menu de la bandeja."""
    if inicio.estado is EstadoInicio.PUESTO:
        return "Arranca con Windows."
    if inicio.estado is EstadoInicio.APUNTA_MAL:
        return f"Puesto, pero NO arrancaria: {inicio.motivo}"
    if inicio.estado is EstadoInicio.NO_SE_SABE:
        return f"No se ha podido comprobar: {inicio.motivo}"
    return "No arranca con Windows."


if __name__ == "__main__":  # pragma: no cover - utilidad de mano
    import argparse

    p = argparse.ArgumentParser(description="Arrancar Jarvis con Windows")
    p.add_argument("accion", choices=["ver", "poner", "quitar", "escritorio"])
    p.add_argument("carpeta", nargs="?", help="la carpeta de trabajo")
    p.add_argument("--sin-voz", action="store_true")
    a = p.parse_args()

    destino = Path(a.carpeta).expanduser() if a.carpeta else None
    if a.accion == "escritorio":
        # La carpeta es OPCIONAL aqui, al reves que en `poner`: el
        # acceso del escritorio deja que la elija AJUSTES, y meterla
        # dentro del `.lnk` la congelaria.
        actual = poner_en_el_escritorio(destino, voz=not a.sin_voz)
        if actual.estado is EstadoInicio.PUESTO:
            print(f"Acceso directo creado en {actual.ruta}")
        else:
            print(f"No se pudo crear: {actual.motivo}")
            raise SystemExit(1)
        raise SystemExit(0)

    if a.accion == "ver":
        actual = estado(destino, voz=not a.sin_voz)
    elif a.accion == "poner":
        if destino is None:
            raise SystemExit("`poner` necesita la carpeta de trabajo")
        actual = poner(destino, voz=not a.sin_voz)
    else:
        actual = quitar()

    print(describe(actual))
    print(f"  carpeta Inicio: {carpeta_de_inicio()}")
    if actual.ruta:
        print(f"  acceso:         {actual.ruta}")
        print(f"  destino:        {actual.destino}")
        print(f"  argumentos:     {actual.argumentos}")
