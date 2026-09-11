"""Turning the detected zones into a floor the session actually runs with.

`seguridad/zonas.py` sabe QUE hay que proteger en esta maquina. Este
modulo lo convierte en el archivo de `--settings` con el que arranca la
sesion, y decide si se puede arrancar.

TRES ESTADOS, NO DOS, porque "el suelo esta bien?" admite si /
no / NO LO SE, y aqui el tercero es el caso normal, no el raro: unas
reglas recien generadas estan bien FORMADAS pero nadie ha comprobado
todavia que MUERDAN.

    LISTO           detectado, vigente, bien formado, y probado con un
                    senuelo contra ESTE binario y ESTAS reglas.
    SIN_VERIFICAR   sano, pero nunca se probo con esta huella. Se puede
                    arrancar, y lo primero que se hace es probarlo.
    INSEGURO        no se arranca. Las letras de unidad cambiaron, o un
                    patron tiene una forma que no muerde.

POR QUE EL SELLO LLEVA LA VERSION DEL BINARIO DENTRO. Verificar en cada
arranque cuesta un turno de verdad (~8 s y dinero, JC-0003), y hacerlo
siempre invita a quitarlo. Pero un sello eterno es peor que ninguno: JC-
0003 ya caduco una vez porque el binario paso de `2.1.239` a `2.1.241`
sin avisar. Asi que el sello vale mientras no cambien NI las reglas NI el
binario, y en cuanto cambia cualquiera de los dos vuelve a haber que
demostrarlo.

LO QUE ESTE MODULO NO PUEDE HACER, y va dicho para que nadie lo lea al
reves: comprobar la FORMA de un patron es gratis y local, pero no prueba
que la regla cubra su objetivo. Eso solo lo dice un senuelo real dentro
de una zona real, que es `verificar_con_senuelo`.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from seguridad.zonas import (
    Vigencia,
    leer_eleccion,
    Zona,
    comprobar_vigencia,
    detectar,
    huella,
    reglas_deny,
    validar_patrones,
    validar_reglas,
)


class QuienTieneElPuerto(Enum):
    """Who is holding the port, in three answers and not two.

    "Esta ocupado" no basta. No se le dice lo mismo al usuario si ya tiene
    un Jarvis abierto -- que es lo normal y solo hay que traerlo al frente
    -- que si el puerto se lo quedo otro programa, donde lo util es
    cambiar de puerto. Y "no lo se" existe porque una respuesta rara no es
    ninguna de las dos.
    """

    LIBRE = "libre"
    OTRO_JARVIS = "otro_jarvis"
    OTRO_PROGRAMA = "otro_programa"
    NO_SE_SABE = "no_se_sabe"


def quien_tiene_el_puerto(puerto: int) -> tuple[QuienTieneElPuerto, str]:
    """Probe the port before trying to bind, to be able to explain it.

    Se pregunta ANTES de arrancar porque despues solo queda un
    `WinError 10048`, que no distingue nada. Y se identifica por la
    cabecera `X-Jarvis`, no olfateando el HTML: una pagina cambia, una
    cabecera puesta a proposito no.
    """
    import socket
    import urllib.error
    import urllib.request

    with socket.socket() as prueba:
        prueba.settimeout(0.4)
        if prueba.connect_ex(("127.0.0.1", puerto)) != 0:
            return QuienTieneElPuerto.LIBRE, "el puerto esta libre"

    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{puerto}/", timeout=2) as respuesta:
            cabecera = respuesta.headers.get("X-Jarvis")
    except urllib.error.HTTPError as fallo:
        cabecera = fallo.headers.get("X-Jarvis")
    except OSError as fallo:
        return (QuienTieneElPuerto.NO_SE_SABE,
                f"hay algo en el puerto {puerto} pero no contesta HTTP: {fallo}")

    if cabecera == "puente":
        return (QuienTieneElPuerto.OTRO_JARVIS,
                f"ya hay un Jarvis escuchando en el puerto {puerto}")
    return (QuienTieneElPuerto.OTRO_PROGRAMA,
            f"el puerto {puerto} lo tiene otro programa, no un Jarvis")


def primer_puerto_libre(desde: int, intentos: int = 20) -> int | None:
    """A port actually free, for the message that suggests one.

    Sugerir `puerto + 1` a ciegas es como saco la primera version: en la
    prueba real apunto justo al puerto donde estaba el OTRO Jarvis. Un
    consejo que lleva al siguiente error es peor que no dar consejo.
    """
    for puerto in range(desde + 1, desde + 1 + intentos):
        quien, _ = quien_tiene_el_puerto(puerto)
        if quien is QuienTieneElPuerto.LIBRE:
            return puerto
    return None


NOMBRE_SENUELO = "jarvis_senuelo_de_arranque.txt"
TEXTO_SENUELO = "senuelo de JC-0007: si esto cambia, el suelo no muerde\n"


class EstadoSuelo(Enum):
    LISTO = "listo"
    SIN_VERIFICAR = "sin_verificar"
    INSEGURO = "inseguro"

    @property
    def se_puede_arrancar(self) -> bool:
        return self is not EstadoSuelo.INSEGURO


@dataclass(frozen=True)
class Suelo:
    """The floor a session will run under, and how much it is trusted."""

    estado: EstadoSuelo
    motivo: str
    archivo: Path | None = None
    zonas: tuple[Zona, ...] = ()
    opcionales: tuple[Zona, ...] = ()
    huella: str = ""
    reglas: tuple[str, ...] = field(default=(), repr=False)
    sello: Path | None = None
    """Donde vive el sello, para poder regenerar el suelo sin que quien
    lo regenere tenga que acordarse de la ruta."""

    @property
    def resumen(self) -> str:
        """One line for a human, for the console and for the log."""
        return (f"suelo {self.estado.value}: {len(self.zonas)} zonas, "
                f"{len(self.reglas)} reglas -- {self.motivo}")


def version_del_binario() -> str:
    """What `claude --version` says, or a marker that we could not ask.

    An unreadable version is NOT treated as "da igual": it goes into the
    fingerprint as its own value, so a stamp taken when the version was
    known never gets reused when it stopped being known.
    """
    try:
        salida = subprocess.run(["claude", "--version"], capture_output=True,
                                text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "desconocida"
    return salida.stdout.strip() or "desconocida"


def _normalizada(ruta: str) -> str:
    return os.path.normcase(os.path.normpath(ruta))


def preparar(destino: Path, sello: Path | None = None,
             inicio: Path | None = None, version: str | None = None,
             config_dir: Path | None = None) -> Suelo:
    """Detect, validate and write the settings file the session runs with.

    Disk and local checks only -- no session is launched -- so it is
    cheap enough to run on every start, which is the point:
    `comprobar_vigencia` only protects if it actually runs.

    `version` is injectable because asking the binary costs 1.1 s
    (measured), and the tests neither need it nor should pay it on every
    case. Left out, it asks for real.
    """
    detectadas, opcionales = detectar(inicio=inicio)

    # Lo que el usuario acepto se suma AL SUELO: a partir de aqui es una
    # zona mas, con sus reglas y su comprobacion. Lo que NO acepto se
    # queda fuera y no genera nada -- una zona ofrecida no es una zona.
    aceptadas = leer_eleccion(config_dir)
    elegidas = [z for z in opcionales
                if _normalizada(z.ruta) in aceptadas]
    obligatorias = detectadas + elegidas

    vigencia, porque = comprobar_vigencia(obligatorias)
    if vigencia is not Vigencia.VIGENTE:
        return Suelo(
            estado=EstadoSuelo.INSEGURO,
            motivo=(f"las unidades no son las que se detectaron ({porque}). "
                    "Las reglas nombrarian rutas que ya no son las mismas, y "
                    "una regla que no casa no da ningun error."),
            zonas=tuple(obligatorias), opcionales=tuple(opcionales))

    bien_formadas, detalle = validar_patrones(obligatorias)
    if not bien_formadas:
        return Suelo(
            estado=EstadoSuelo.INSEGURO,
            motivo=f"un patron no tiene la forma que se midio que muerde: {detalle}",
            zonas=tuple(obligatorias), opcionales=tuple(opcionales))

    reglas = reglas_deny(obligatorias)

    # La forma del patron no basta: una regla `Write(...)` sin su
    # `Edit(...)` es INERTE y no da ningun error (medido el 2026-08-24).
    # Se comprueba aqui, en cada arranque, y no se arranca sin ello.
    efectivas, porque_reglas = validar_reglas(obligatorias, reglas)
    if not efectivas:
        return Suelo(
            estado=EstadoSuelo.INSEGURO,
            motivo=f"las reglas generadas no protegerian nada: {porque_reglas}",
            zonas=tuple(obligatorias), opcionales=tuple(opcionales))

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps({"permissions": {"deny": reglas}}, indent=2),
        encoding="utf-8")

    marca = huella(reglas, version or version_del_binario())
    verificado = sello is not None and _sello_vale(sello, marca)

    return Suelo(
        estado=EstadoSuelo.LISTO if verificado else EstadoSuelo.SIN_VERIFICAR,
        motivo=(detalle if verificado
                else f"{detalle}, pero nadie ha probado todavia que muerdan"),
        archivo=destino,
        zonas=tuple(obligatorias),
        opcionales=tuple(opcionales),
        huella=marca,
        reglas=tuple(reglas),
        sello=sello,
    )


def _sello_vale(sello: Path, marca: str) -> bool:
    try:
        return sello.read_text(encoding="utf-8").strip() == marca
    except OSError:
        return False


def sellar(sello: Path, marca: str) -> None:
    sello.parent.mkdir(parents=True, exist_ok=True)
    sello.write_text(marca, encoding="utf-8")


# --------------------------------------------------------------------
# El senuelo: lo unico que demuestra que el suelo muerde
# --------------------------------------------------------------------

class Senuelo(Enum):
    """Que dijo el senuelo. TRES respuestas, no dos.

    >>> LA TERCERA COSTO UN VERDE EN FALSO, Y ESTA REGISTRADO <<<
    Hasta el 2026-08-27 esto devolvia un `bool`, y el "no lo se" se
    colapsaba contra el "si". El fallo, medido en el arranque real del
    usuario (`logs/puente/sesion_20260827_163905.jsonl`):

      1. el senuelo se pide en `~/.claude`; el suelo lo bloquea;
      2. el modelo REINTENTA en la carpeta personal, que NO es zona
         obligatoria -- asi que `permissions.deny` no lo para y la
         peticion llega a NUESTRA puerta;
      3. nadie contesta esa puerta (nadie esta mirando: es el arranque),
         y la sesion espera indefinidamente, que esta medido;
      4. `eventos(timeout=...)` se queda sin tiempo y **vuelve en
         silencio**, sin `Fin` y sin error;
      5. se relee el senuelo, sigue intacto, y se concluye "el suelo
         muerde"... **y se sella**.

    El senuelo estaba intacto porque el turno seguia colgado, no porque
    el suelo mordiese. Un sello firmado asi dice que el suelo esta
    probado cuando no se probo nada, que es la peor de las tres.
    """

    MUERDE = "muerde"
    NO_MUERDE = "no_muerde"
    NO_SE_SABE = "no_se_sabe"

    @property
    def se_puede_arrancar(self) -> bool:
        """Solo `MUERDE`. `NO_SE_SABE` no arranca: un suelo sin probar es
        exactamente lo que JC-0007 se niega a dar por bueno."""
        return self is Senuelo.MUERDE


def zona_para_senuelo(zonas: tuple[Zona, ...]) -> Zona | None:
    """A mandatory zone we can still write into while setting up.

    The decoy has to live inside a zone that is REALLY on the floor, not
    in a convenient temp folder: what has to be proven is that the
    generated pattern covers its actual target. `~/.claude` is the one
    mandatory zone the user still owns.
    """
    for zona in zonas:
        if zona.directorio and ".claude" in zona.ruta.lower():
            if Path(zona.ruta).is_dir():
                return zona
    return None


def verificar_con_senuelo(sesion, suelo: Suelo, sello: Path | None = None,
                          timeout: float = 120.0) -> tuple[Senuelo, str]:
    """Ask the live session to write into a real zone, and check the disk.

    THIS IS THE ONLY HONEST PROOF and it costs a real turn. Everything
    else -- reading the JSON, checking the pattern shape -- can pass while
    the floor does nothing at all, because a `deny` that fails to match
    is silent: no error, no warning, just a write that goes through.

    Verdict comes FROM DISK, never from what the model says about it. The
    model is on the other side of the thing being tested; asking it
    whether it was blocked would be asking the suspect.

    >>> PERO EL DISCO SOLO VALE SI EL TURNO TERMINO <<<
    Un senuelo intacto significa "no se escribio", y eso tiene DOS
    causas: el suelo lo bloqueo, o el turno nunca llego a intentarlo. Sin
    `Fin` no se puede distinguir, y por eso hay un `Senuelo.NO_SE_SABE`.
    Ver el enum: la version de dos salidas llego a sellar un suelo que
    nadie habia probado.

    >>> Y LAS PUERTAS DE ESTE TURNO SE DENIEGAN SOLAS <<<
    Nadie esta mirando: esto corre en el arranque, antes de que el
    usuario haya pedido nada. Dejar una puerta esperando a una persona
    cuelga la comprobacion hasta el timeout -- que es justo como se
    llegaba al verde en falso. Denegar es ademas lo correcto: al senuelo
    se le pidio una sola via, y cualquier puerta que aparezca aqui es un
    REINTENTO por otro camino.
    """
    from puente.protocolo import Fin, Puerta

    zona = zona_para_senuelo(suelo.zonas)
    if zona is None:
        return Senuelo.NO_SE_SABE, (
            "no hay ninguna zona obligatoria escribible donde plantar el "
            "senuelo, asi que no se puede demostrar nada")

    senuelo = Path(zona.ruta) / NOMBRE_SENUELO
    try:
        senuelo.write_text(TEXTO_SENUELO, encoding="utf-8")
    except OSError as fallo:
        return Senuelo.NO_SE_SABE, (
            f"no se pudo plantar el senuelo en {senuelo}: {fallo}")

    try:
        sesion.mandar(
            "Comprobacion de arranque del propio asistente, sobre un archivo "
            f"senuelo. Escribe con la herramienta Write el texto 'colado' en "
            f"{senuelo}. Si no puedes, dilo y no intentes ninguna otra via.")
        termino = False
        reintentos = 0
        for evento in sesion.eventos(timeout=timeout):
            if isinstance(evento, Puerta):
                # Un reintento por otra via. Se deniega y se cuenta: si
                # esto crece, el senuelo esta pidiendo mal lo que pide.
                reintentos += 1
                sesion.responder(evento.id_peticion, permitir=False,
                                 motivo="comprobacion de arranque del suelo")
                continue
            if isinstance(evento, Fin):
                termino = True
                break

        quedo = senuelo.read_text(encoding="utf-8")
    except OSError as fallo:
        return Senuelo.NO_SE_SABE, f"no se pudo releer el senuelo: {fallo}"
    finally:
        senuelo.unlink(missing_ok=True)

    if "colado" in quedo:
        return Senuelo.NO_MUERDE, (
            f"EL SUELO NO MUERDE: se escribio dentro de {zona.ruta}, que es "
            "zona obligatoria. Las reglas estan puestas y no hacen nada.")

    if not termino:
        # >>> AQUI ESTABA EL VERDE EN FALSO <<< El senuelo esta intacto,
        # pero el turno no cerro: puede que el suelo mordiera, o puede que
        # ni se intentase. No se sella lo que no se ha probado.
        return Senuelo.NO_SE_SABE, (
            f"el turno no termino en {timeout:.0f} s, asi que el senuelo "
            f"intacto no demuestra nada"
            f"{f' ({reintentos} reintentos denegados)' if reintentos else ''}")

    if sello is not None and suelo.huella:
        sellar(sello, suelo.huella)
    # >>> EL VEREDICTO VA DELANTE, Y DICE QUE TU ORDEN SIGUE VIVA <<<
    # Lo reporto el usuario el 2026-09-05: le confundio leer que su
    # orden habia sido "rechazada" cuando el flujo si habia seguido. La frase
    # empezaba en minuscula y acababa en "fue rechazada", debajo de un
    # aviso que ya decia que aquello podia tardar y justo despues de
    # teclear una orden. En ese sitio "rechazada" solo se lee de una
    # manera: que te rechazaron A TI. Y es lo contrario -- es la unica
    # buena de las tres salidas.
    # La gemela de arriba, `EL SUELO NO MUERDE`, ya gritaba su veredicto
    # desde la primera palabra; esta no. Ahora las tres empiezan
    # diciendo QUE PASO, que es lo unico que se lee de un vistazo.
    return Senuelo.MUERDE, (
        f"SUELO COMPROBADO: intento escribir en {zona.ruta} y no le "
        f"dejaron, que es exactamente lo que tenia que pasar"
        f"{f' (y {reintentos} reintentos por otra via, tampoco)' if reintentos else ''}"
        ". Tu orden no se ha tocado y va ahora.")
