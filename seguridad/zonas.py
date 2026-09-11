"""Detecting the restricted zones of THIS machine (JC-0007).

The floor is not a list somebody typed. It is what a scan of the actual
disks proposes, and the reason is sitting on this very machine: the user
has a SECOND Windows install on `E:`, left over from a disk migration.
A hand-written list would have protected `C:\\Windows` and left the other
one exposed, and nobody would have noticed until something broke.

TWO AXES, and they are not the same question (see the ADR):

    zona de SISTEMA    se puede LEER, no escribir ni borrar. Leer
                       `C:\\Windows` es inofensivo y hace falta -- "que
                       version de driver cuda tengo" escanea archivos de
                       sistema. Lo que rompe la PC es ESCRIBIR.
    zona PRIVADA       ni leer ni escribir. Aqui el riesgo no es romper
                       nada: el contenido VIAJA a la nube.

Este modulo detecta el eje de SISTEMA. Las zonas privadas las pone el
usuario, porque cuales son sus cosas privadas no lo dice ningun disco.

>>> LA LETRA DE UNIDAD ES EL `device index` DE ESTE PROBLEMA. <<<
Este proyecto ya pago esa leccion en otro sitio: `voz/audio.py` se niega
a elegir microfono por indice y los declara por NOMBRE, porque 16 de los
23 endpoints de audio de esta maquina son cables virtuales que entregan
silencio perfecto SIN dar error. Aqui pasa igual: `E:` hoy puede ser
`F:` manana -- se conecta un disco, se reordena, y las reglas siguen
nombrando una letra que ahora apunta a otra cosa. Y como una regla que no
casa FALLA ABIERTA Y EN SILENCIO (medido, ver el ADR), el suelo se
evaporaria sin un solo mensaje.

Por eso cada zona viaja con el GUID del volumen del que salio, y por eso
existe `comprobar_vigencia`: la deteccion NO es de una vez al instalar,
se revalida en cada arranque.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# `GetDriveTypeW`. Solo interesan los fijos: un USB o un disco de red no
# alojan el sistema, y montarlos como suelo obligatorio significaria que
# el suelo cambia cada vez que se enchufa un pendrive.
DRIVE_FIXED = 3

# El unico marcador honesto de "aqui vive un Windows". Se eligio sobre
# "existe la carpeta Windows" porque una carpeta llamada `Windows` la
# crea cualquiera; el kernel, no.
MARCADOR_DE_WINDOWS = Path("Windows") / "System32" / "ntoskrnl.exe"

# Carpetas de arranque, actualizacion y recuperacion. Se buscan POR
# NOMBRE en la raiz de cada volumen porque no todas existen en todas las
# maquinas: en esta hay `$WinREAgent` y `ESD`, y no hay `Boot` ni `EFI`.
RAICES_DE_SISTEMA = (
    ("Windows", "el sistema operativo"),
    ("Program Files", "los programas instalados"),
    ("Program Files (x86)", "los programas de 32 bits"),
    ("WindowsApps", "las aplicaciones de la Store"),
    ("Recovery", "la particion de recuperacion montada"),
    ("$WinREAgent", "el entorno de recuperacion de Windows"),
    ("$WINDOWS.~BT", "una actualizacion de Windows a medio aplicar"),
    ("$Windows.~WS", "una actualizacion de Windows descargada"),
    ("ESD", "las imagenes de instalacion de Windows"),
    ("System Volume Information", "los puntos de restauracion y las "
                                  "instantaneas VSS"),
    ("Config.Msi", "un instalador en curso"),
)

# Archivos sueltos en la raiz que son de la maquina, no del usuario.
ARCHIVOS_DE_MAQUINA = (
    ("pagefile.sys", "el archivo de paginacion"),
    ("hiberfil.sys", "el archivo de hibernacion"),
    ("swapfile.sys", "el archivo de intercambio"),
    ("DumpStack.log", "el volcado de fallos del sistema"),
    ("DumpStack.log.tmp", "el volcado de fallos del sistema"),
)


class Eje(Enum):
    """Which of the two axes a zone belongs to. They are NOT the same rule.

    Getting this wrong is not a detail: a private zone written as a
    system zone blocks writing and lets reading through, so the content
    still travels to the cloud while the UI says it is protected. That is
    a promise the rules do not keep, and it was exactly what the first
    version of `_opcionales_del_perfil` did.
    """

    SISTEMA = "sistema"
    PRIVADA = "privada"


class Vigencia(Enum):
    """Whether a saved set of zones still describes this machine.

    THREE ANSWERS, not two. "Sigue valiendo?"
    admite si / no / NO LO SE, y colapsar el tercero contra "si" es
    exactamente como se pierde un suelo sin enterarse.
    """

    VIGENTE = "vigente"
    CAMBIADA = "cambiada"
    NO_SE_SABE = "no_se_sabe"


@dataclass(frozen=True)
class Zona:
    """One folder or file the assistant may not write to.

    `coste` is what the user LOSES by blocking it, in their own language,
    and it is not decoration: a zone offered without its cost is a
    checkbox the user ticks without understanding, which is the same
    reflex "si" that D8 warns about, only in a settings screen.
    """

    ruta: str
    motivo: str
    obligatoria: bool
    coste: str = ""
    volumen: str | None = None
    directorio: bool = True
    eje: Eje = Eje.SISTEMA
    """System by default: the floor is all system, and defaulting to
    PRIVADA would silently block reads that "que version de driver cuda
    tengo" needs."""
    """Whether the zone is a folder. Taken FROM DISK at detection time.

    It is not inferred from the name, and that is not fussiness: the
    first version of this file guessed with `Path.suffix`, and on this
    very machine `C:\\Config.Msi`, `C:\\$WINDOWS.~BT` and
    `C:\\$Windows.~WS` are FOLDERS whose names carry a dot. They were
    classified as files, so the rule named the folder and left everything
    inside it writable -- a hole that produces no error whatsoever,
    because a `deny` that does not match is silent (see the ADR).
    """

    @property
    def patron_escritura(self) -> str:
        """The `permissions.deny` pattern, in the syntax MEASURED to bite.

        Native Windows form. Measured 2026-08-24 against `claude 2.1.241`:
        `C:\\...\\**` bites, and so do `C:/.../**` and `//c/.../**`, but
        `/c/...` and `//C:/...` DO NOT -- and they fail open in silence.
        Nothing here may switch to another form without re-measuring it
        with `eval/sondas_claude_code/sonda_zonas.py`.
        """
        if not self.directorio:
            return self.ruta
        return str(Path(self.ruta) / "**")


# --------------------------------------------------------------------
# Los volumenes de la maquina
# --------------------------------------------------------------------

@dataclass(frozen=True)
class Volumen:
    letra: str
    guid: str | None
    tiene_windows: bool


def _volumenes_fijos() -> list[Volumen]:
    """Fixed drives, with the stable id of each one.

    `guid` is None when Windows would not hand it over. That is NOT
    treated as "no pasa nada": it is what makes `comprobar_vigencia`
    answer NO_SE_SABE instead of pretending the mapping is unchanged.
    """
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetLogicalDriveStringsW.restype = wintypes.DWORD
    k32.GetDriveTypeW.restype = wintypes.UINT

    tamano = k32.GetLogicalDriveStringsW(0, None)
    if not tamano:
        return []
    buffer = ctypes.create_unicode_buffer(tamano)
    k32.GetLogicalDriveStringsW(tamano, buffer)

    volumenes: list[Volumen] = []
    for raiz in buffer[:tamano].split("\0"):
        if not raiz:
            continue
        if k32.GetDriveTypeW(raiz) != DRIVE_FIXED:
            continue

        nombre = ctypes.create_unicode_buffer(50)
        guid = None
        if k32.GetVolumeNameForVolumeMountPointW(raiz, nombre, 50):
            guid = nombre.value or None

        volumenes.append(Volumen(
            letra=raiz.rstrip("\\"),
            guid=guid,
            tiene_windows=(Path(raiz) / MARCADOR_DE_WINDOWS).exists(),
        ))
    return volumenes


# --------------------------------------------------------------------
# La deteccion
# --------------------------------------------------------------------

def detectar(inicio: Path | None = None) -> tuple[list[Zona], list[Zona]]:
    """Scan the machine and propose zones.

    Returns:
        (obligatorias, opcionales). The mandatory ones are the floor and
        the UI may not uncheck them. The optional ones are OFFERED, each
        with what it costs, and the user decides.
    """
    obligatorias: list[Zona] = []
    opcionales: list[Zona] = []
    sistema_vivo = os.environ.get("SystemDrive", "C:").rstrip("\\")

    for volumen in _volumenes_fijos():
        raiz = Path(volumen.letra + "\\")

        for nombre, motivo in RAICES_DE_SISTEMA:
            destino = raiz / nombre
            if not destino.exists():
                continue
            # Sin Windows en el volumen, `Program Files` es una carpeta
            # de programas portables cualquiera y bloquearla solo estorba.
            if not volumen.tiene_windows and nombre != "System Volume Information":
                continue
            ajeno = (volumen.tiene_windows and volumen.letra != sistema_vivo)
            obligatorias.append(Zona(
                ruta=str(destino),
                motivo=(f"{motivo}, en un Windows que NO es el que arranca"
                        if ajeno else motivo),
                obligatoria=True,
                volumen=volumen.guid,
                directorio=destino.is_dir(),
            ))

        for nombre, motivo in ARCHIVOS_DE_MAQUINA:
            destino = raiz / nombre
            if volumen.tiene_windows and destino.exists():
                obligatorias.append(Zona(
                    ruta=str(destino), motivo=motivo, obligatoria=True,
                    volumen=volumen.guid, directorio=destino.is_dir()))

        if volumen.tiene_windows:
            datos = raiz / "ProgramData"
            if datos.exists():
                opcionales.append(Zona(
                    ruta=str(datos),
                    motivo="datos de aplicaciones instaladas para todo el equipo",
                    obligatoria=False,
                    coste="Jarvis no podra instalar ni actualizar programas "
                          "que guarden ahi (chocolatey, Docker, controladores).",
                    volumen=volumen.guid, directorio=datos.is_dir()))

    obligatorias.extend(_zonas_del_propio_asistente(inicio))
    opcionales.extend(_opcionales_del_perfil(inicio))
    return obligatorias, opcionales


def _zonas_del_propio_asistente(inicio: Path | None = None) -> list[Zona]:
    """The files that define the assistant's own limits.

    THIS IS THE ONE ENTRY THAT DOES NOT PROTECT THE PC. It protects the
    protection: an agent that can rewrite the settings which bound it is
    not bounded. It is mandatory for the same reason the floor is fixed.
    """
    casa = Path(inicio) if inicio else Path.home()
    zonas: list[Zona] = []

    for destino, motivo in (
        (casa / ".claude", "la configuracion de Claude Code, que es donde "
                           "viven las reglas que limitan a Jarvis"),
        (casa / ".claude.json", "la configuracion de Claude Code"),
        (casa / ".local" / "bin", "el binario de Claude Code"),
    ):
        if destino.exists():
            zonas.append(Zona(str(destino), motivo, obligatoria=True,
                              directorio=destino.is_dir()))
    return zonas


def _opcionales_del_perfil(inicio: Path | None = None) -> list[Zona]:
    """Offered, never imposed: these are the user's own life.

    `AppData` entero NO se ofrece a proposito. Ahi viven npm, cargo, uv y
    media cadena de desarrollo; bloquearlo convierte al asistente en un
    adorno, y un suelo que estorba tanto acaba desactivado entero, que es
    peor que no tenerlo.
    """
    casa = Path(inicio) if inicio else Path.home()
    ofertas = (
        ("Documents", "tus documentos",
         "Jarvis no podra leer ni escribir nada ahi: ni buscar un PDF ni "
         "guardarte un resumen."),
        ("Desktop", "tu escritorio",
         "Jarvis no podra dejarte archivos a la vista ni leer lo que sueltes ahi."),
        ("Pictures", "tus fotos",
         "Jarvis no podra mirar ni organizar imagenes."),
        (".ssh", "tus claves SSH",
         "Ninguno: Jarvis no necesita leer claves privadas para nada."),
    )
    return [
        Zona(str(casa / nombre), motivo, obligatoria=False, coste=coste,
             directorio=(casa / nombre).is_dir(), eje=Eje.PRIVADA)
        for nombre, motivo, coste in ofertas
        if (casa / nombre).exists()
    ]


# --------------------------------------------------------------------
# La revalidacion, que es lo que impide que el suelo se evapore
# --------------------------------------------------------------------

def comprobar_vigencia(zonas: list[Zona]) -> tuple[Vigencia, str]:
    """Whether saved zones still point where they pointed.

    Answers in three, never two. A drive letter that now belongs to a
    different volume is not a small drift: the rule keeps naming `E:\\`,
    the pattern still parses, nothing errors, and the floor is simply
    gone.
    """
    try:
        actuales = {v.letra: v.guid for v in _volumenes_fijos()}
    except OSError as fallo:
        return Vigencia.NO_SE_SABE, f"no se pudieron leer los volumenes: {fallo}"

    for zona in zonas:
        if zona.volumen is None:
            continue
        letra = str(Path(zona.ruta).drive)
        if letra not in actuales:
            return (Vigencia.CAMBIADA,
                    f"la unidad {letra} ya no esta, y {zona.ruta} la nombra")
        if actuales[letra] is None:
            return (Vigencia.NO_SE_SABE,
                    f"Windows no dice que volumen es {letra} ahora mismo")
        if actuales[letra] != zona.volumen:
            return (Vigencia.CAMBIADA,
                    f"la unidad {letra} es otro disco distinto del que se "
                    f"detecto; {zona.ruta} ya no protege lo que protegia")
    return Vigencia.VIGENTE, "las unidades siguen siendo las mismas"


def validar_patrones(zonas: list[Zona]) -> tuple[bool, str]:
    """Whether every generated pattern has the shape MEASURED to bite.

    Free, local, and it runs before anything is launched. It cannot prove
    a rule matches its target -- only a live decoy does that -- but it
    catches the exact class of failure that has no symptom: a pattern in
    a form that never matches anything and never says so.

    Measured 2026-08-24 against `claude 2.1.241` with
    `sonda_zonas.py --sintaxis`: `C:\\...` bites, `/c/...` and `//C:/...`
    do NOT. Anything that is not the native Windows form is refused here
    rather than shipped and hoped for.
    """
    if not zonas:
        return False, ("no se detecto ni una zona obligatoria, y esta maquina "
                       "tiene Windows: la deteccion fallo")

    for zona in zonas:
        patron = zona.patron_escritura
        if patron.startswith("/"):
            return False, (f"el patron de {zona.ruta} empieza por barra "
                           f"({patron!r}), y esa forma NO muerde")
        if len(patron) < 3 or patron[1] != ":" or patron[2] != "\\":
            return False, (f"el patron de {zona.ruta} no es una ruta nativa "
                           f"de Windows: {patron!r}")
        if zona.directorio and not patron.endswith("\\**"):
            return False, (f"{zona.ruta} es una carpeta y su patron no cubre "
                           f"el contenido: {patron!r}")
    return True, f"{len(zonas)} patrones con la forma que se midio que muerde"


ARCHIVO_ELECCION = "zonas.yaml"


def leer_eleccion(config_dir: Path | None = None) -> set[str]:
    """Which optional zones the user has accepted, by path.

    A missing file means "ninguna aceptada", NOT "todas": the optional
    zones cost the user something and nobody chose them yet. Reading an
    absent config as consent is how a checkbox nobody ticked ends up
    blocking their Documents folder.

    A malformed file is NOT ignored either -- it raises, because the
    alternative is starting with a floor different from the one the user
    configured while telling them nothing.
    """
    from nucleo.configuracion import CONFIG_DIR, load_yaml

    destino = (config_dir or CONFIG_DIR) / ARCHIVO_ELECCION
    if not destino.exists():
        return set()
    datos = load_yaml(destino) or {}
    aceptadas = datos.get("opcionales_aceptadas") or []
    if not isinstance(aceptadas, list):
        from nucleo.configuracion import ConfigError
        raise ConfigError(
            f"{destino}: `opcionales_aceptadas` tiene que ser una lista, "
            f"y es {type(aceptadas).__name__}")
    return {os.path.normcase(os.path.normpath(str(r))) for r in aceptadas}


def guardar_eleccion(rutas: list[str], config_dir: Path | None = None) -> Path:
    """Persist the choice, in the same YAML shape the rest of config uses.

    Written whole, never appended: the file IS the choice, so a zone the
    user unticked has to disappear from it. Merging would make unticking
    impossible and nobody would notice until they looked.
    """
    from nucleo.configuracion import CONFIG_DIR

    destino = (config_dir or CONFIG_DIR) / ARCHIVO_ELECCION
    destino.parent.mkdir(parents=True, exist_ok=True)
    lineas = [
        "# Zonas opcionales que el usuario ha aceptado bloquear (JC-0007).",
        "#",
        "# EL SUELO NO ESTA AQUI. Las zonas obligatorias se DETECTAN en cada",
        "# arranque (`seguridad/zonas.py`) y no se pueden editar: quitar una",
        "# de este archivo no las desprotege, porque no salen de aqui.",
        "#",
        "# Lo edita la consola. A mano tambien vale, pero el cambio no llega",
        "# a una sesion ya abierta: el archivo de reglas se lee UNA VEZ al",
        "# arrancar (medido el 2026-08-24).",
        "opcionales_aceptadas:",
    ]
    lineas += [f"  - {ruta}" for ruta in rutas] or ["  []"]
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return destino


def validar_reglas(zonas: list[Zona], reglas: list[str]) -> tuple[bool, str]:
    """Whether the generated rules can actually do anything.

    Checks the one thing that has no symptom when it is wrong: every zone
    needs an `Edit(...)` rule, because that is the one that governs
    writing. A rule set that only says `Write(...)` parses fine, loads
    fine, reports nothing, and protects nothing -- measured, see
    `reglas_deny`. A private zone additionally needs its `Read(...)`, or
    it is offered as "ni leer ni escribir" while the reading goes on.
    """
    for zona in zonas:
        patron = zona.patron_escritura
        if f"Edit({patron})" not in reglas:
            return False, (f"{zona.ruta} no tiene regla Edit(...), que es la "
                           "que gobierna la escritura: la zona no protegeria "
                           "nada y no habria ningun error que lo delatara")
        if zona.eje is Eje.PRIVADA and f"Read({patron})" not in reglas:
            return False, (f"{zona.ruta} es zona privada y no tiene regla "
                           "Read(...): se ofreceria como 'ni leer ni "
                           "escribir' permitiendo la lectura")
    return True, f"{len(reglas)} reglas, y cada zona tiene la suya efectiva"


def huella(reglas: list[str], version_binario: str) -> str:
    """A fingerprint of what was verified, so a stale stamp cannot pass.

    Both halves matter and neither is enough alone. If the ZONES change,
    the new ones were never proven to bite. If the BINARY changes, the
    mechanism itself may have moved -- JC-0003 already expired once that
    way. Either one invalidates the decoy check and forces it again.
    """
    material = "\n".join(sorted(reglas)) + "\n" + version_binario
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def reglas_deny(zonas: list[Zona]) -> list[str]:
    """The `permissions.deny` entries, and the axis decides which.

    SISTEMA gets `Write` and `Edit` only: reading is what makes "que
    version de driver cuda tengo" work, and reading a system file breaks
    nothing.

    PRIVADA gets `Read` as well, and that is the whole difference. The
    risk there is not a broken machine, it is that the CONTENT TRAVELS --
    principle 1 fell in this fork. A private zone with only write rules
    would be offered as "ni leer ni escribir" and quietly allow the read,
    which is worse than not offering it: the user would believe it.

    >>> `Edit(...)` NO ES OPCIONAL, Y ESTA MEDIDO EL 2026-08-24 <<<
    Es la regla que gobierna las escrituras. `Write(...)` POR SI SOLA ES
    INERTE. A/B contra `claude 2.1.241`, mismo destino, misma sesion,
    cambiando solo el conjunto de reglas:

        solo Write(...)          la puerta salta y EL ARCHIVO SE ESCRIBE
        solo Edit(...)           BLOQUEADO, sin puerta
        Write(...) + Edit(...)   BLOQUEADO, sin puerta

    Un suelo escrito a mano con `Write(...)` a secas es un guardia
    decorativo perfecto: no da error, no avisa, y no hace nada. Costo
    media sesion de sondas creer que el suelo estaba roto cuando lo roto
    eran las sondas. Por eso `validar_reglas` lo comprueba en cada
    arranque en vez de confiar en que nadie lo toque.
    """
    reglas: list[str] = []
    for zona in zonas:
        patron = zona.patron_escritura
        if zona.eje is Eje.PRIVADA:
            reglas.append(f"Read({patron})")
        reglas.append(f"Write({patron})")
        reglas.append(f"Edit({patron})")
    return reglas
