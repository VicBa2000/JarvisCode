"""Deciding, per gate, whether the user has to be woken up.

This is JC-0001 turned into code. The decision the user made on
2026-08-21: **por defecto no se pregunta nada**, y se endurece solo una
lista corta de acciones irreversibles, empezando por el borrado.

WHY THE BRIDGE DOES THIS INSTEAD OF `--permission-mode auto`, and it was
measured, not assumed. With `auto`, `rm victima.txt` executed and the
gate never fired once -- the bridge is not fast, it is DEAF, and the
hardened list cannot exist because deletion is precisely what goes by
unannounced. So the session runs in `default` and the auto mode lives
here: this module answers `PERMITIR` instantly for almost everything,
and the user only ever hears about the short list.

WHAT THIS MODULE CANNOT DO, and it has to be said out loud. Measured:
`ls -la` executes without a gate in `default` AND in `manual`. Claude
Code decides on its own which shell commands are worth asking about, so
this policy is a VETO OVER WHAT CLAUDE CODE ASKS, not an independent
guard over everything that runs. For deletion that is enough -- `rm`
gated in every capture -- but nobody should read this file believing it
sees every action. What sees every action is the `UsoHerramienta`
stream, and that is where `auditoria` reads from.

THREE ANSWERS, THREE PATHS. "Is this
destructive?" admits si / no / NO LO SE, and in the original collapsing
the third into "no" failed open eight times. Here the third one exists as
its own veredicto: it acts like ENDURECER -- it asks -- but it is logged
as what it is, so that "el puente no supo leer la orden" never hides
inside "el puente decidio preguntar".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePath

from puente.protocolo import Puerta


class Veredicto(Enum):
    """What the bridge concluded about one gate.

    `DENEGAR` exists because the JC-0007 floor is FIXED, and asking about
    it would be a lie: a question the user is not allowed to answer "si"
    to is not a question. It was added when the settings layer turned out
    to be bypassable -- see `_toca_una_zona`.
    """

    PERMITIR = "permitir"
    ENDURECER = "endurecer"
    NO_SE_SABE = "no_se_sabe"
    DENEGAR = "denegar"

    @property
    def hay_que_preguntar(self) -> bool:
        """Only the two middle verdicts ask. They are logged apart on purpose."""
        return self in (Veredicto.ENDURECER, Veredicto.NO_SE_SABE)


# Heads of a command line that destroy something. Kept as bare command
# names because that is what survives quoting; the matching strips paths
# and extensions first.
#
# `mv` IS DELIBERATELY ABSENT and it is the closest call in this file: a
# move can be as destructive as a delete when it lands on top of
# something. It is also the single most common thing a user asks a voice
# assistant to do with files, and asking every time would be the "si"
# reflejo that D8 warns about. If it ever gets added, it gets added with
# a measurement of how often it fires, not because it sounded prudent.
ORDENES_DESTRUCTIVAS = frozenset({
    # POSIX / Git Bash
    "rm", "rmdir", "unlink", "shred", "truncate",
    # cmd.exe
    "del", "erase", "rd",
    # PowerShell, nombre y alias
    "remove-item", "ri", "rm-item", "clear-content", "clear-item",
})

# Whole command lines that are irreversible even though their head is
# harmless. Matched against the normalised segment, in order.
FORMAS_DESTRUCTIVAS: tuple[tuple[str, str], ...] = (
    (r"^git\s+push\b", "sube codigo a un remoto"),
    (r"^git\s+reset\s+--hard\b", "descarta cambios sin guardar"),
    (r"^git\s+clean\b", "borra archivos sin seguimiento"),
    (r"^git\s+branch\s+-D\b", "borra una rama"),
)

# The OTHER half of the JC-0007 floor, and it exists because the first
# half cannot cover it. Zones are paths; these commands break the machine
# WITHOUT WRITING TO ANY DENIED PATH:
#
#   * The registry is not a folder. `reg delete HKLM\SYSTEM\...` ruins a
#     boot and never touches `C:\Windows`.
#   * This machine is UEFI: there is no `C:\Boot`, no `bootmgr`, no
#     `C:\EFI` -- checked on disk. The loader lives on an unlettered EFI
#     partition, which no path rule can name. `mountvol` is how it is
#     reached, and `bcdedit` is how it is broken.
#   * `vssadmin delete shadows` destroys the restore points, which is the
#     one thing that would have undone the rest.
#
# THE LIST IS SHORT ON PURPOSE. Every entry here becomes a spoken
# question (JC-0002), and a floor that asks about everything trains the
# reflex "si" that D8 warns about. Read-only uses are left alone where
# they can be told apart: `dism /online /get-features` and a bare
# `icacls ruta` list things and are not gated.
#
# NOT MEASURED YET: nobody knows how often this fires in real
# use. If some entry turns out to interrupt constantly, it comes out with
# a number attached, not because it felt annoying.
FORMAS_QUE_ROMPEN_EL_SISTEMA: tuple[tuple[str, str], ...] = (
    (r"^reg(\.exe)?\s+delete\b", "borra una clave del registro de Windows"),
    (r"^reg(\.exe)?\s+(add|import)\b.*\bHK(LM|CR|U)\b",
     "escribe en el registro del sistema"),
    (r"^remove-item\b.*\bHK(LM|CR|U):", "borra una clave del registro"),
    (r"^bcdedit\b", "cambia como arranca Windows"),
    (r"^bootrec\b|^bootsect\b", "reescribe el arranque del disco"),
    (r"^mountvol\b.*(/d\b|/s\b|\{)", "toca la particion de arranque"),
    (r"^diskpart\b", "reparticiona discos"),
    (r"^format\b", "formatea una unidad"),
    (r"^(format-volume|clear-disk|remove-partition|set-partition)\b",
     "formatea o reparticiona un disco"),
    (r"^vssadmin\b.*\bdelete\b", "borra los puntos de restauracion"),
    (r"^sc(\.exe)?\s+delete\b|^remove-service\b",
     "borra un servicio de Windows"),
    (r"^schtasks\b.*/delete", "borra una tarea programada"),
    (r"^takeown\b", "se apropia de archivos del sistema"),
    (r"^icacls\b.*(/grant|/setowner|/reset|/remove|/deny)",
     "cambia quien puede tocar unos archivos"),
    (r"^dism(\.exe)?\b.*(/remove-|/disable-|/apply-|/cleanup-image)",
     "modifica la instalacion de Windows"),
    (r"^fsutil\b.*(delete|setflag|repair|volume)",
     "toca el sistema de archivos a bajo nivel"),
    (r"^robocopy\b.*(/mir\b|/purge\b)",
     "borra en el destino todo lo que no este en el origen"),
    (r"^cipher\b.*/w", "sobrescribe el espacio libre del disco"),
    (r"^net(\.exe)?\s+user\b.*(/delete|/add)",
     "crea o borra una cuenta de usuario"),
)

# The bridge cannot read these with any confidence, so it does not
# pretend to. These take a STRING and run it, so there is nothing to
# read: what the string turns out to be is decided at run time.
FORMAS_OPACAS: tuple[tuple[str, str], ...] = (
    (r"\beval\b", "la orden se evalua en tiempo de ejecucion"),
    (r"\biex\b|\binvoke-expression\b", "la orden se evalua en tiempo de ejecucion"),
    (r"\|\s*(ba)?sh\b", "la orden se canaliza a un interprete"),
)

# >>> EL ACENTO GRAVE NO SIGNIFICA LO MISMO EN LAS DOS SHELLS <<<
# En bash `cmd` es sustitucion de ordenes. En PowerShell es el caracter
# de ESCAPE -- `n, `t, `" --, o sea puntuacion corriente. Tenerlo en la
# lista comun volvia opaca cualquier linea de PowerShell con un escape
# dentro, y eso NO es una lectura prudente: es la regla mintiendo sobre
# lo que hace la orden, igual que `2>&1` el 2026-08-27.
FORMAS_OPACAS_BASH: tuple[tuple[str, str], ...] = (
    (r"`", "la orden construye parte de si misma"),
)

SEPARADORES = re.compile(r"&&|\|\||;|\||\n")

# Herramientas que escriben en un archivo concreto. Su `file_path` se
# compara contra el directorio de la sesion.
HERRAMIENTAS_DE_ESCRITURA = frozenset({"Write", "Edit", "NotebookEdit"})

NULOS = frozenset({"/dev/null", "nul", "$null"})


@dataclass(frozen=True)
class Decision:
    """The verdict plus everything the spoken sentence will need.

    `elementos` exists for JC-0002: la peticion hablada tiene que decir
    CUANTOS y CUALES elementos toca. Deriving it here, from the same
    `Puerta` the console renders, is what keeps the two forms from
    drifting apart.
    """

    veredicto: Veredicto
    motivo: str
    regla: str
    elementos: tuple[str, ...] = field(default_factory=tuple)

    @property
    def hay_que_preguntar(self) -> bool:
        return self.veredicto.hay_que_preguntar


def _toca_una_zona(puerta: Puerta, zonas: tuple) -> Decision | None:
    """Whether this gate lands inside a JC-0007 zone. Denies if it does.

    SEGUNDA LINEA, y la primera sigue siendo `permissions.deny`. Esta
    capa existe por lo que el ADR ya dejaba abierto: el LAVADO DE RUTA
    (`cp` de una zona privada a zona de trabajo) se cuela por arriba y SI
    llega a la puerta, asi que aqui se puede cazar. Ademas decide sobre la
    ruta NORMALIZADA (`os.path.normpath` unifica las barras en Windows),
    de modo que `C:/Windows/...`, `C:\\Windows\\...` y un `..` por medio
    dan todos el mismo veredicto.

    Se DENIEGA en vez de preguntar porque el suelo es fijo: una pregunta
    que no admite un "si" no es una pregunta, y ofrecerla ensenaria que el
    suelo se negocia.

    NO CONVIERTE ESTO EN UN GUARDIA: sigue viendo solo lo que Claude Code
    pregunta -- `politica.py` lo dice en su cabecera y sigue siendo
    verdad.
    """
    if not zonas:
        return None

    destino = puerta.entrada.get("file_path")
    if not isinstance(destino, str) or not destino.strip():
        destino = puerta.ruta_afectada
    if not isinstance(destino, str) or not destino.strip():
        return None

    # >>> UN MCP CUENTA COMO QUE ESCRIBE, PORQUE NO SE SABE (JC-0015) <<<
    # El eje 1 deja LEER el sistema a proposito -- "que version de driver
    # cuda tengo" es medio producto --, y para saber si una herramienta
    # lee o escribe esta capa mira su NOMBRE. Con `mcp__x__y` ese nombre
    # no dice nada: lo elige un tercero y puede hacer cualquier cosa.
    #
    # Asumir que no escribe seria colapsar "no lo se" contra "no", que es
    # el fallo por defecto de este proyecto y aqui fallaria
    # ABIERTO: se midio que un `mcp__archivos__escribir` apuntando a
    # `C:\Windows` salia PERMITIR incluso con el servidor autorizado, o
    # sea que `auto` era una forma de saltarse el suelo pidiendoselo a un
    # amigo.
    #
    # `Bash` NO entra aqui y no es un olvido: su linea de ordenes SI se
    # puede leer (`_decidir_shell`), asi que ahi no hay "no lo se" -- y
    # meterlo romperia leer el sistema desde la shell, que esta pedido.
    escribe = (puerta.herramienta in HERRAMIENTAS_DE_ESCRITURA
               or puerta.herramienta.startswith("mcp__"))
    for zona in zonas:
        if not _esta_dentro(destino, zona.ruta):
            continue
        privada = getattr(zona.eje, "value", zona.eje) == "privada"
        if not (escribe or privada):
            # Eje 1: leer el sistema es legitimo y es medio producto.
            continue
        return Decision(
            veredicto=Veredicto.DENEGAR,
            motivo=(f"{zona.ruta} es zona privada y no se toca"
                    if privada else
                    f"{zona.ruta} es zona de sistema y no se escribe"),
            regla="zona_privada" if privada else "zona_de_sistema",
            elementos=(destino,),
        )
    return None


def _decidir_mcp(puerta: Puerta, servidores: tuple | None) -> Decision | None:
    """Que hacer con una herramienta de un servidor MCP. None si no lo es.

    >>> `servidores=None` NO ES "NINGUNO", ES "NO SE ME HA DICHO" <<<
    Y por eso NO deniega: es la tercera salida. Un test que
    construya una `Puerta` a mano no esta declarando que el usuario no
    tenga servidores, solo no esta hablando de eso. Quien corre de
    verdad -- `puente/sesion.py` -- SIEMPRE pasa la tupla, aunque este
    vacia, y una tupla vacia si significa "ninguno declarado".

    Colapsar los dos casos en uno haria que la unica capa que entiende
    estos nombres dependiera de que nadie olvide un argumento.
    """
    from nucleo.mcp import Politica, es_de_mcp, politica_de, servidor_de

    if not es_de_mcp(puerta.herramienta):
        return None
    if servidores is None:
        return None

    quien = servidor_de(puerta.herramienta) or "(sin nombre)"
    politica = politica_de(puerta.herramienta, servidores)

    if politica is None:
        # NO DECLARADO -> NO PASA. Si esto preguntara, no seria una lista
        # blanca sino un aviso. El motivo NOMBRA al servidor para que
        # enterarse y anadirlo sea un paso y no una investigacion.
        return Decision(
            veredicto=Veredicto.DENEGAR,
            motivo=f"el servidor MCP '{quien}' no esta en la lista blanca",
            regla="mcp_no_declarado",
            elementos=(puerta.herramienta,),
        )
    if politica is Politica.PROHIBIDO:
        return Decision(
            veredicto=Veredicto.DENEGAR,
            motivo=f"el servidor MCP '{quien}' esta prohibido",
            regla="mcp_prohibido",
            elementos=(puerta.herramienta,),
        )
    if politica is Politica.CONFIRMAR:
        return Decision(
            veredicto=Veredicto.ENDURECER,
            motivo=f"lo pide el servidor MCP '{quien}'",
            regla="mcp_confirmar",
            elementos=(puerta.herramienta,),
        )
    return Decision(
        veredicto=Veredicto.PERMITIR,
        motivo=f"el servidor MCP '{quien}' esta autorizado",
        regla="mcp_auto",
        elementos=(puerta.herramienta,),
    )


def decidir(puerta: Puerta, directorio_sesion: str | None = None,
            zonas: tuple = (), servidores_mcp: tuple | None = None) -> Decision:
    """Whether this gate can be answered without waking anyone.

    `directorio_sesion` is the folder the session is bounded to. Passing
    None disables the "writes outside the project" rule; it does not
    silently allow them, it just leaves that question unasked, and the
    caller is expected to know why.

    `zonas` are the JC-0007 zones. Empty means the caller is not enforcing
    them here -- which is a real choice for a test, and a bad one for a
    live session, because the settings layer alone is bypassable.
    """
    # El suelo va PRIMERO. Si esto quedara detras de `ruta_fuera`, una
    # escritura en `C:\Windows` desde una sesion acotada a otra carpeta
    # se convertiria en una PREGUNTA en vez de una negativa, y el suelo
    # dejaria de ser fijo por un accidente de orden.
    del_suelo = _toca_una_zona(puerta, zonas)
    if del_suelo is not None:
        return del_suelo

    # >>> LA LISTA BLANCA DE MCP (JC-0015) <<<
    # VA AQUI, detras del suelo y DELANTE de todo lo demas, y el orden es
    # deliberado en los dos lados:
    #   - detras del suelo, porque si un servidor MCP llegase a nombrar
    #     una ruta de zona de sistema, eso se deniega por lo que toca y
    #     no por quien lo pide;
    #   - delante del resto, porque el resto **no sabe leer estos
    #     nombres**. Se midio el 2026-08-26: `mcp__archivos__borrar`
    #     salia `permitir / por_defecto`, o sea que atravesaba la puerta
    #     entera sin tocarla.
    de_mcp = _decidir_mcp(puerta, servidores_mcp)
    if de_mcp is not None:
        return de_mcp

    # `ruta_afectada` NO es un veto -- ver su docstring en protocolo.py.
    # Lo unico que se le pregunta es si cae fuera del proyecto.
    if (puerta.ruta_afectada and directorio_sesion
            and not _esta_dentro(puerta.ruta_afectada, directorio_sesion)):
        return Decision(
            veredicto=Veredicto.ENDURECER,
            motivo="toca un archivo fuera del directorio de la sesion",
            regla="ruta_fuera",
            elementos=(puerta.ruta_afectada,),
        )

    if puerta.herramienta in HERRAMIENTAS_DE_ESCRITURA:
        return _decidir_escritura(puerta, directorio_sesion)

    orden = puerta.orden_shell
    if orden is not None:
        # La shell no es un detalle de transporte: decide como se LEE la
        # linea. Ver `FORMAS_OPACAS_BASH`.
        shell = "powershell" if puerta.herramienta == "PowerShell" else "bash"
        return _decidir_shell(orden, puerta.ruta_afectada, shell=shell,
                              directorio_sesion=directorio_sesion,
                              zonas=zonas)

    return Decision(
        veredicto=Veredicto.PERMITIR,
        motivo="no esta en la lista endurecida",
        regla="por_defecto",
    )


def _decidir_escritura(puerta: Puerta, directorio_sesion: str | None) -> Decision:
    destino = puerta.entrada.get("file_path")
    if not isinstance(destino, str) or not destino.strip():
        # Una escritura sin ruta legible es justo el caso de "no lo se".
        return Decision(
            veredicto=Veredicto.NO_SE_SABE,
            motivo="no se ve sobre que archivo escribe",
            regla="escritura_sin_ruta",
        )
    if directorio_sesion and not _esta_dentro(destino, directorio_sesion):
        return Decision(
            veredicto=Veredicto.ENDURECER,
            motivo="escribe fuera del directorio de la sesion",
            regla="escritura_fuera",
            elementos=(destino,),
        )
    return Decision(
        veredicto=Veredicto.PERMITIR,
        motivo="escribe dentro del directorio de la sesion",
        regla="escritura_dentro",
        elementos=(destino,),
    )


def _borra_dentro(objetivos: tuple[str, ...],
                  directorio_sesion: str | None,
                  zonas: tuple = ()) -> bool | None:
    """Si TODO lo que borra cae dentro del proyecto. Tres respuestas.

    `None` = no se puede saber, y entonces manda quien llama. Sin
    directorio de sesion no hay nada contra lo que comparar, y sin
    objetivos legibles tampoco: las dos cosas siguen preguntando.

    >>> LA CARPETA DEL PROYECTO NO CUENTA COMO "DENTRO" <<<
    Y esto no estaba en la decision del usuario, esta puesto aqui: "un
    archivo dentro del proyecto" y "el proyecto entero" no son la misma
    frase, aunque `is_relative_to` diga que si para los dos. Un
    `rm -rf .` en la raiz de la sesion borra el trabajo del que se venia
    hablando, y eso sigue mereciendo una pregunta. Lo mismo cualquier
    ancestro.

    >>> Y BASTA CON QUE UNO SE SALGA <<<
    `rm temporal.txt ../importante.txt` no es medio permitido. Se mira
    todo o no se permite nada.

    >>> LAS ZONAS SE MIRAN AQUI TAMBIEN, Y LO CAZO SU PROPIO TEST <<<
    `_toca_una_zona` decide sobre una RUTA -- el `file_path` de un
    `Write`, o el `blocked_path` que nombre Claude Code --, y una linea
    de shell no trae ninguna de las dos. Asi que una sesion enraizada
    dentro de una zona de sistema hacia que `rm x.txt` saliera "dentro
    del proyecto" y PASARA SOLO: la regla nueva convertia en permiso lo
    que antes al menos preguntaba. Es el lavado de ruta del ADR por otra
    puerta.
    Se mira el eje entero, sistema y privada: borrar es escribir, y en
    las dos esta prohibido escribir.
    """
    if not directorio_sesion or not objetivos:
        return None
    for objetivo in objetivos:
        if not _esta_dentro(objetivo, directorio_sesion):
            return False
        # >>> SE RESUELVE ANTES DE LA SEGUNDA COMPROBACION <<<
        # Y lo destapo `rm -rf .`, que salia PERMITIR: comparar un `.`
        # crudo contra la ruta de la sesion no casa nunca, asi que "el
        # objetivo contiene a la sesion" daba siempre False y la forma
        # mas corta de borrar el proyecto entero pasaba sola. Un
        # relativo se lee DESDE la carpeta de la sesion, que es donde
        # corre la orden.
        try:
            absoluto = Path(objetivo)
            if not absoluto.is_absolute():
                absoluto = Path(directorio_sesion) / absoluto
        except (ValueError, OSError):
            return False
        if _esta_dentro(directorio_sesion, str(absoluto)):
            # El objetivo CONTIENE la sesion: es la carpeta misma o un
            # padre suyo. Dentro y encima, que no es dentro.
            return False
        for zona in zonas:
            if _esta_dentro(str(absoluto), zona.ruta):
                return False
    return True


def _esta_dentro(destino: str, directorio: str) -> bool:
    """Whether a path lands inside a folder, without touching the disk.

    Deliberately syntactic: `resolve()` would follow symlinks and hit the
    filesystem for a decision that has to be taken before anything runs.
    """
    try:
        ruta = Path(destino)
        raiz = Path(directorio)
        if not ruta.is_absolute():
            ruta = raiz / ruta
        return PurePath(_normaliza(ruta)).is_relative_to(PurePath(_normaliza(raiz)))
    except (ValueError, OSError):
        return False


def _normaliza(ruta: Path) -> str:
    import os

    return os.path.normcase(os.path.normpath(str(ruta)))


def _decidir_shell(orden: str, ruta_afectada: str | None = None,
                   shell: str = "bash",
                   directorio_sesion: str | None = None,
                   zonas: tuple = ()) -> Decision:
    """El veredicto de una linea de ordenes.

    `shell` decide como se LEE la linea, no cuanto se permite. Ver
    `FORMAS_OPACAS_BASH`: el acento grave es sustitucion en bash y el
    caracter de escape en PowerShell, asi que la misma linea significa
    dos cosas distintas y no puede juzgarse con una sola gramatica.
    """
    limpia = orden.strip()
    if not limpia:
        return Decision(
            veredicto=Veredicto.NO_SE_SABE,
            motivo="la orden llego vacia",
            regla="shell_vacia",
        )

    opacas = FORMAS_OPACAS + (FORMAS_OPACAS_BASH if shell == "bash" else ())
    for patron, motivo in opacas:
        if re.search(patron, limpia, flags=re.IGNORECASE):
            return Decision(
                veredicto=Veredicto.NO_SE_SABE,
                motivo=motivo,
                regla="shell_opaca",
                elementos=(limpia,),
            )

    # Lo que hay dentro de una sustitucion se juzga como un segmento mas,
    # y la linea se juzga sin el. Ver `_sin_sustituciones`.
    visible, sustituido = _sin_sustituciones(limpia, shell)
    if visible is None:
        return Decision(
            veredicto=Veredicto.NO_SE_SABE,
            motivo="la orden abre una sustitucion y no la cierra",
            regla="sustitucion_sin_cerrar",
            elementos=(limpia,),
        )
    segmentos = _segmentos(visible)
    for contenido in sustituido:
        segmentos.extend(_segmentos(contenido))

    for segmento in segmentos:
        for patron, motivo in FORMAS_DESTRUCTIVAS:
            if re.search(patron, segmento, flags=re.IGNORECASE):
                return Decision(
                    veredicto=Veredicto.ENDURECER,
                    motivo=motivo,
                    regla="forma_destructiva",
                    elementos=(segmento,),
                )
        # Se apunta con una regla PROPIA, no como una forma destructiva
        # mas: al leer la auditoria hay que poder contar por separado
        # "quiso borrar algo" y "quiso tocar el sistema", porque no se
        # miden juntas ni se responden igual por voz.
        for patron, motivo in FORMAS_QUE_ROMPEN_EL_SISTEMA:
            if re.search(patron, segmento, flags=re.IGNORECASE):
                return Decision(
                    veredicto=Veredicto.ENDURECER,
                    motivo=motivo,
                    regla="rompe_el_sistema",
                    elementos=(segmento,),
                )
        cabeza = _cabeza(segmento)
        if cabeza in ORDENES_DESTRUCTIVAS:
            # Claude Code ya resolvio la ruta cuando la nombra; su valor
            # es absoluto y no depende de como se hayan puesto comillas.
            objetivos = ((ruta_afectada,) if ruta_afectada
                         else _objetivos(segmento))
            dentro = _borra_dentro(objetivos, directorio_sesion, zonas)
            if dentro is True:
                # >>> DECISION DEL USUARIO (2026-08-29) <<<
                # Decidio que dentro del proyecto NO se pregunta. Su
                # sesion real paro en un `Remove-Item probe_umbral.py`,
                # un temporal que la propia sesion habia creado dos
                # minutos antes, dentro de la carpeta de trabajo.
                # Preguntar por eso es el "si" reflejo que D8 avisa: se
                # contesta que si sin leer, y entonces la puerta deja de
                # significar nada el dia que la respuesta importe.
                # `git push` y compania NO pasan por aqui: no son rutas,
                # asi que se siguen preguntando.
                return Decision(
                    veredicto=Veredicto.PERMITIR,
                    motivo="borra dentro del directorio de la sesion",
                    regla="borrado_dentro",
                    elementos=objetivos,
                )
            if not objetivos:
                # >>> BORRA, Y NO SE VE QUE. NO ES LO MISMO <<<
                # Es donde acaba `rm $(cat lista.txt)` desde que se lee
                # dentro de las sustituciones: la orden se entiende, el
                # OBJETIVO no. Pregunta igual que un borrado normal, pero
                # se registra aparte, porque la frase hablada de JC-0002
                # no puede decir cuantos ni cuales -- y decir "borra tres
                # archivos" sin saberlo seria inventar la peticion en la
                # que el usuario consiente.
                return Decision(
                    veredicto=Veredicto.NO_SE_SABE,
                    motivo="borra, y no se ve que archivos",
                    regla="borrado_sin_objetivo",
                    elementos=(segmento,),
                )
            return Decision(
                veredicto=Veredicto.ENDURECER,
                motivo="borra archivos",
                regla="orden_destructiva",
                elementos=objetivos,
            )
        if _trunca(segmento):
            return Decision(
                veredicto=Veredicto.NO_SE_SABE,
                motivo="reescribe un archivo entero y no se sabe si existia",
                regla="redirige_y_trunca",
                elementos=(segmento,),
            )

    return Decision(
        veredicto=Veredicto.PERMITIR,
        motivo="no esta en la lista endurecida",
        regla="shell_inofensiva",
    )


def _segmentos(orden: str) -> list[str]:
    return [t.strip() for t in SEPARADORES.split(orden) if t.strip()]


def _sin_sustituciones(orden: str, shell: str) -> tuple[str | None, list[str]]:
    """Saca lo que hay dentro de `$(...)` -- y de `` `...` `` en bash.

    Devuelve la linea con los huecos en blanco y la lista de contenidos,
    para que **se juzguen los dos**: el contenido como un segmento mas y
    la linea sin el.

    >>> POR QUE ESTO NO ES AFLOJAR LA PUERTA <<<
    Hasta el 2026-08-29, un `$(` volvia la linea entera ilegible y
    preguntaba SIEMPRE, sin mirar. Eso tumbo dos de las cinco puertas de
    una sesion real, y las dos eran interpolar un campo en una cadena:

        "OLLAMA OK $($r.StatusCode)"

    Leer dentro no puede anadir puertas -- antes preguntaba siempre --,
    solo puede quitarlas: `$(rm -rf /)` sigue cayendo, porque su
    contenido entra como segmento y `rm` sigue en la lista.
    Lo que si se conserva es la DUDA cuando la sustitucion decide sobre
    QUE actua una orden destructiva: ver `_decidir_shell`, donde un
    borrado sin objetivos legibles es NO_SE_SABE y no ENDURECER.

    El anidamiento se cuenta con un contador de parentesis, no con una
    expresion regular: `$(a $(b) c)` tiene que salir entero o el resto de
    la linea se leeria descuadrado.

    >>> DEVUELVE None SI NO SE PUEDE LEER, Y ESO ES LA TERCERA SALIDA <<<
    Un `$(` sin cerrar no es una linea sin sustituciones: es una linea
    que no se sabe donde empieza ni acaba. Lo destapo su propio test --
    `echo $(rm -rf /tmp` salia PERMITIR, porque la cabeza del segmento
    era `echo` y el `rm` iba de acompanante. Devolver la linea tal cual
    era colapsar "no lo se" contra "no", que es el fallo por defecto de
    este proyecto.
    """
    dentro: list[str] = []
    fuera: list[str] = []
    i, n = 0, len(orden)
    while i < n:
        if orden.startswith("$(", i):
            profundidad, j = 1, i + 2
            while j < n and profundidad:
                if orden[j] == "(":
                    profundidad += 1
                elif orden[j] == ")":
                    profundidad -= 1
                j += 1
            if profundidad:
                return None, []   # sin cerrar: no se puede leer
            dentro.append(orden[i + 2:j - 1])
            fuera.append(" ")
            i = j
            continue
        if shell == "bash" and orden[i] == "`":
            j = orden.find("`", i + 1)
            if j == -1:
                return None, []
            dentro.append(orden[i + 1:j])
            fuera.append(" ")
            i = j + 1
            continue
        fuera.append(orden[i])
        i += 1
    return "".join(fuera), dentro


def _cabeza(segmento: str) -> str:
    """The command name of a segment, stripped of path, quotes and .exe."""
    partes = segmento.split()
    for parte in partes:
        # Un prefijo `VAR=valor` no es la orden todavia.
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", parte):
            continue
        nombre = parte.strip("'\"")
        nombre = PurePath(nombre).name.lower()
        if nombre.endswith(".exe"):
            nombre = nombre[:-4]
        return nombre
    return ""


def _objetivos(segmento: str) -> tuple[str, ...]:
    """What a destructive command is pointed at, for the spoken sentence."""
    partes = segmento.split()[1:]
    return tuple(
        p.strip("'\"") for p in partes
        if not p.startswith("-") and "=" not in p
    )


def _trunca(segmento: str) -> bool:
    """Whether the segment redirects over a file, wiping what was there.

    `>>` appends and is left alone; `>` replaces. Writing to a null
    device destroys nothing and is extremely common, so it is excluded.

    >>> `2>&1` NO ESCRIBE NINGUN ARCHIVO, Y ESTO COSTO CUATRO PUERTAS <<<
    Lo destapo la primera sesion real contra un proyecto de verdad
    (2026-08-27, Delta): de las cuatro puertas que le llegaron al
    usuario a la consola, TRES eran `2>&1` -- `nvidia-smi ... 2>&1 |
    head`, `ls -la ... 2>&1 | head`, `curl ... 2>&1` --, y ninguna
    escribia nada. `>&` DUPLICA UN DESCRIPTOR: el destino es un numero de
    descriptor, no una ruta, asi que aqui se leia como "machaca un
    archivo llamado `&1`".

    No era un endurecimiento de mas: era la regla mintiendo sobre lo que
    hacia la orden, y encima en la frase que se locuta. `&>archivo` SI se
    queda dentro -- ahi el destino es una ruta y trunca de verdad.

    Y SE MIRAN TODAS LAS REDIRECCIONES DEL SEGMENTO, no solo la primera:
    con `re.search`, un `cmd 2>&1 > importante.txt` se salia por la
    primera y la de verdad no se veia.
    """
    for encontrado in re.finditer(r"(?<!>)>(?!>)\s*(\S+)", segmento):
        destino = encontrado.group(1).strip("'\"").lower()
        if destino.startswith("&"):
            continue          # `2>&1`, `1>&2`: un descriptor, no un archivo
        if destino in NULOS:
            continue          # a la nada: no destruye nada
        return True
    return False
