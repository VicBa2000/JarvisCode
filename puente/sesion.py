"""Driving one live Claude Code session, and holding its gate.

This is the process side of JC-0003 and the enforcement side of JC-0001.
Everything here follows from measurements taken on 2026-08-21 against
`claude 2.1.239`; the reasoning behind it is JC-0003.

ONE PROCESS, MANY TURNS, and it is not an optimisation. Measured: a
one-shot `claude -p` costs ~8 s of wall clock for a trivial answer, of
which ~3.5 s is the cold start of a 337 MB binary. Eight seconds to turn
up the volume is a bad product. The process stays alive after `result`,
keeps its `session_id` and keeps its context, so the bridge opens it once
and feeds it turns.

THE STARTUP CHECK IS NOT CEREMONY. `--permission-prompt-tool stdio` does
not appear in `claude --help`. Without it, Claude Code answers its own
permission requests -- measured: `rm victima.txt` executed and the gate
never fired -- and the bridge would run happily forever while the user
consented to nothing. There is no error to catch when that happens, so
the bridge checks a POSITIVE signal instead: with the flag in effect the
session loads `AskUserQuestion`, without it that tool is absent. The
check rides on `system/init`, which arrives with the first turn and
before any `tool_use` -- so nothing has run when it fires. If the flag
ever stops working the session is killed on the spot rather than going
quietly deaf.

NOBODY ANSWERS A QUESTION EXCEPT A PERSON. A `Puerta` may be resolved by
policy. A `Pregunta` never is -- it is handed out and the session waits.
Measured: an unanswered gate waits indefinitely (140 s and counting, no
timeout, nothing executed), so waiting is safe and is the honest third
exit. The moment this module starts answering "the easy ones" it stops
being a conduit and becomes the second agent ADR-0018 refused.

FIRST ANSWER WINS. With voice, Telegram and the console all live, two
channels can answer the same `request_id`. `responder` consumes the id
under a lock and tells the loser it was already decided, because the
alternative -- a second answer silently dropped -- means the user
believes they approved something they did not.
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from puente.politica import Decision, Veredicto, decidir
from puente.protocolo import (
    AbreBloque,
    AbreMensaje,
    CierraBloque,
    Desconocido,
    Evento,
    Fin,
    Inicio,
    Limite,
    LineaIlegible,
    Pregunta,
    Puerta,
    Reintento,
    Trozo,
    interpretar,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Sin esto no hay consentimiento posible, solo su apariencia.
FLAG_PUERTA = "--permission-prompt-tool"

ESPERA_INICIO_S = 60.0

# >>> LOS VALORES DE `--effort`, Y SE VALIDAN AQUI POR UNA RAZON <<<
# El binario NO da error con un valor invalido: lo IGNORA y sigue con el
# defecto, avisando por stderr (medido el 2026-09-01 con `--effort
# disparate`). En este montaje stderr llega como `LineaIlegible`, o sea
# que una errata en `ajustes.yaml` dejaria el esfuerzo en el defecto para
# siempre y sin un solo sintoma. Es la misma forma que el
# `--permission-prompt-tool` de JC-0003: un flag que se cree puesto.
ESFUERZOS = ("low", "medium", "high", "xhigh", "max")


class PuenteError(RuntimeError):
    """The session could not be opened, or was opened without a gate."""


@dataclass(frozen=True)
class Pendiente:
    """A gate or a question that is waiting on a human."""

    evento: Puerta | Pregunta
    decision: Decision | None
    pedido_en: float

    @property
    def es_pregunta(self) -> bool:
        return isinstance(self.evento, Pregunta)

    @property
    def segundos_esperando(self) -> float:
        return time.time() - self.pedido_en


@dataclass(frozen=True)
class PreguntaAbierta:
    """Una pregunta que CERRO el turno, en prosa, sin herramienta detras.

    >>> Y NO ES UNA `Pendiente`, A PROPOSITO <<<
    `_pendientes` significa una cosa muy concreta en todo el arbol: la
    sesion esta BLOQUEADA esperando, hay un `id_peticion` vivo en el
    canal de control, y se contesta con `responder`. La consola lo pinta
    asi, `Buzon` lo recorre asi, y `Caida` cuenta las que se pierden.
    Meter aqui algo que no bloquea nada cambiaria el significado de esos
    tres sitios a la vez y sin que salte un solo test.

    Esto es lo contrario: el turno ya cerro, no hay nada esperando en el
    cable, y contestarla es `mandar` -- UN TURNO NUEVO. Por eso viaja por
    su propia propiedad y no mezclada con las puertas.

    >>> LO QUE SE PUEDE MANDAR AL MOVIL SALE DE `etiquetas` <<<
    Y son recortes literales de lo que escribio Claude
    (`voz.resumen.opciones_de_pregunta`). Si esta vacia, la pregunta se
    AVISA igual pero se contesta en la consola o hablando: eso es lo que
    mantiene en pie la frase de JC-0016.
    """

    id: str
    pregunta: str
    """Lo que devolvio `pregunta_final`: la cola del texto."""
    enunciado: str
    """La misma pregunta ya recortada para enseñarla en otro canal."""
    etiquetas: tuple[str, ...]
    forma: str
    abierta_en: float

    @property
    def contestable(self) -> bool:
        """Si esto se puede mandar numerado y contestar con un numero."""
        return bool(self.etiquetas)

    @property
    def segundos_esperando(self) -> float:
        return time.time() - self.abierta_en

    def texto_de(self, numero: int) -> str | None:
        """La etiqueta que corresponde a un numero. None si no hay."""
        if 1 <= numero <= len(self.etiquetas):
            return self.etiquetas[numero - 1]
        return None


@dataclass(frozen=True)
class SinPuerta(Evento):
    """The session came up without a working gate. Fatal, and it kills it.

    Emitted instead of raised because it is discovered on the reader
    thread, and it arrives with `system/init` -- which is before any tool
    call, so nothing has run yet when we pull the plug.
    """

    motivo: str


@dataclass(frozen=True)
class Caida(Evento):
    """The process is gone. Whatever was pending will never be answered.

    Emitted before the stream closes so that a console showing "esperando
    tu aprobacion" can take it down. A gate left on screen after the
    session died is worse than no gate: the user thinks the machine is
    waiting for them when there is nothing left to wait for.
    """

    codigo: int | None
    errores: tuple[str, ...] = ()
    pendientes_perdidas: int = 0


@dataclass(frozen=True)
class Resuelta(Evento):
    """A gate the policy answered on its own. Emitted so it can be logged.

    It exists because "el puente aprobo esto sin preguntar" has to be
    visible somewhere. An auto-approval that leaves no trace is
    indistinguishable from no gate at all.
    """

    puerta: Puerta
    decision: Decision


class Sesion:
    """One live Claude Code process, with its gate held by us."""

    def __init__(
        self,
        directorio: str | Path,
        modelo: str = "sonnet",
        registro: Path | None = None,
        extra: tuple[str, ...] = (),
        ajustes: Path | None = None,
        zonas: tuple = (),
        servidores_mcp: tuple | None = None,
        modo_permisos: str = "default",
        preambulo: str | None = None,
        mcp_config: "Path | None" = None,
        mcp_estricto: bool = False,
        esfuerzo: str | None = None,
    ) -> None:
        self.directorio = str(Path(directorio))
        self.modelo = modelo
        self.modo_permisos = modo_permisos
        """`--permission-mode`. `default` = la puerta llega; `auto` = no.

        >>> ESTO NO ES UN AJUSTE DE VELOCIDAD (JC-0017) <<<
        Con `auto` este modulo se queda SORDO -- medido el 2026-08-21: un
        `rm` ejecutandose sin un solo aviso --, o sea que se apagan a la
        vez y en silencio la lista endurecida de JC-0001, la lista blanca
        de MCP de JC-0015 y la peticion hablada de JC-0002.
        Lo que NO se apaga, medido el 27 contra los cinco modos: el suelo
        de JC-0007 muerde igual, bypass incluido, y los `tool_use` se
        siguen viendo. La consola lo sigue ensenando TODO.

        Lo elige el LANZADOR, no este modulo: por proyecto en
        `config/proyectos.yaml` y en global con `sesion.auto_por_defecto`.
        Aqui solo se guarda y se usa, para que quien lea `orden` vea la
        linea de ordenes de verdad y no una constante que ya no es cierta.
        """
        if esfuerzo is not None and esfuerzo not in ESFUERZOS:
            raise PuenteError(
                f"'{esfuerzo}' no es un esfuerzo valido. Hay: "
                f"{', '.join(ESFUERZOS)}. Se levanta en vez de seguir con el "
                f"defecto porque el binario ya hace eso, y en silencio.")
        self.esfuerzo = esfuerzo
        """`--effort`. `None` = el que traiga Claude Code de serie.

        >>> NO ES UN DIAL DE CALIDAD: ES UN DIAL DE SEGUNDOS <<<
        Medido el 2026-09-01 contra `claude 2.1.252`, mismo acertijo,
        5 turnos por nivel:

            sin flag   0 de 5 turnos pensaron    5,4 s   0,0454 USD
            max        5 de 5 turnos pensaron   23,7 s   0,0658 USD
                       (850 a 3550 tokens)

        O sea 4,4 veces el reloj de pared. En una consola eso es esperar;
        con la voz son VEINTICUATRO SEGUNDOS DE SILENCIO, y un asistente
        callado 24 s es indistinguible de uno colgado. Por eso nace en
        `None` y por eso el panel lleva la cifra escrita.
        `low` y `high` no se separaron del defecto (0 de 2 turnos
        pensando cada uno), y con esos numeros la sonda no dice que sean
        iguales: dice que no los ha separado.
        """
        self.mcp_config = mcp_config
        """El archivo que lista los servidores MCP que Jarvis ARRANCA.

        >>> DECLARAR Y LANZAR SON DOS COSAS (JC-0015, ampliado el 09-01) <<<
        `servidores_mcp` de abajo es la lista blanca: decide si una
        herramienta `mcp__x__y` PASA. Esto decide si el servidor `x`
        llega siquiera a existir en la sesion. Hasta hoy solo habia lo
        primero, asi que la lista blanca gobernaba una puerta que no
        llevaba a ningun sitio: comprobado que en esta maquina no hay ni
        un servidor configurado, en ningun sitio.

        Los dos siguen haciendo falta y no se sustituyen. Un servidor que
        Jarvis lanza sigue pasando por la lista blanca; y uno que venga
        de la configuracion del usuario no aparece aqui y la lista blanca
        lo gobierna igual.
        """
        self.mcp_estricto = mcp_estricto
        """`--strict-mcp-config`: SOLO los de `mcp_config`, ninguno mas.

        >>> LO QUE CAMBIA NO ES QUE SE DENIEGA, ES QUE SE ARRANCA <<<
        Con o sin esto, la lista blanca deniega exactamente lo mismo: lo
        no declarado no pasa. La diferencia es que sin esto, un servidor
        que el usuario tenga puesto en SU Claude Code se arranca tambien
        aqui -- un proceso mas, todos los dias, lanzado por algo que vive
        en el inicio de Windows -- y sus llamadas se deniegan una a una.
        A cambio, sin esto la sesion VE esos servidores, y eso es lo que
        alimenta `mcp_vistos` y el boton de "he visto estos, los
        autorizo?" que pidio el usuario. Con esto puesto, ese boton no
        puede aparecer nunca, porque el servidor no llega a cargarse.
        Nace apagado para no romper esa mitad de la decision de JC-0015.
        """
        self.preambulo = preambulo
        """Lo que sabe el cerebro de su canal de salida. `None` = nada.

        >>> `None` NO ES UN DESCUIDO: ES LA SESION SIN VOZ <<<
        Sin altavoz, contarle que le leen en alto seria mentirle, y ademas
        empeoraria la unica salida que le queda -- la consola, donde una
        tabla se lee mejor que la prosa que la sustituiria. Lo compone el
        LANZADOR, igual que `modo_permisos`, porque es el unico que sabe
        si `--voz` esta puesto: ver `voz/preambulo.py`.
        """
        self.extra = extra
        self.registro = registro
        self.ajustes = ajustes
        """The JC-0007 floor, as a `--settings` file. `None` means NO floor.

        A session without one is not a broken session -- the tests drive
        plenty of them -- but it is a session where writing to
        `C:\\Windows` is gated by nothing but `politica.py`. Whoever
        launches one is expected to say so out loud;
        `puente/__main__.py` refuses to.
        """
        self.zonas = zonas
        # >>> NUNCA `None` EN UNA SESION VIVA (JC-0015) <<<
        # `None` significa "no se me ha dicho" y la politica lo deja
        # pasar; una tupla vacia significa "ninguno declarado" y deniega.
        # Aqui se normaliza a tupla precisamente para que olvidarse del
        # argumento no sea lo mismo que abrir la puerta: si el lanzador
        # no pasa lista, la lista esta vacia y no pasa ningun MCP.
        self.servidores_mcp: tuple = tuple(servidores_mcp or ())
        self.mcp_vistos: set[str] = set()
        """Servidores MCP que han pedido algo y NO estan declarados.

        Es lo que hace que la lista blanca sea ABIERTA en vez de un muro:
        denegar sin decir QUE se denego obliga a leer el log para
        enterarse. Con esto, el panel puede ofrecer "he visto estos,
        ¿los autorizo?" -- que es enterarse en un paso.

        Solo el NOMBRE del servidor. Ni la herramienta ni sus argumentos:
        eso ya esta en el registro crudo, y aqui solo hace falta para
        rellenar un desplegable.
        """
        """The same zones, enforced HERE as well: the second of two layers.

        The settings layer covers what never asks; this one covers what
        gets past it and DOES ask -- the path laundering the ADR measured
        (`cp` out of a private zone). See `_toca_una_zona` en
        `politica.py`.
        """
        self.session_id: str | None = None
        self.inicio: Inicio | None = None
        self.fallo: str | None = None
        # Lo ultimo que se supo del otro lado. `reintentando` es la unica
        # forma de distinguir "esta pensando" de "no llega al servidor".
        self.reintentando: Reintento | None = None
        self.limite: Limite | None = None
        self.ultimo_evento_en: float = time.time()
        self._errores: list[str] = []

        self._proceso: subprocess.Popen[str] | None = None
        self._cola: queue.Queue[Evento | None] = queue.Queue()
        self._pendientes: dict[str, Pendiente] = {}
        self._abierta: PreguntaAbierta | None = None
        self._abiertas_vistas: int = 0
        self._cerrojo = threading.Lock()
        self._escritura = threading.Lock()
        self._archivo_registro = None

    # --- ciclo de vida ---------------------------------------------------

    @staticmethod
    def _absoluta(ruta: "str | Path") -> str:
        r"""Una ruta que el HIJO pueda resolver, y eso no es cosmetica.

        >>> MEDIDO EL 2026-09-01, Y NO FALLA EN SILENCIO: NO ARRANCA <<<
        `--mcp-config` y `--settings` los resuelve `claude` contra SU
        directorio de trabajo, que es el del proyecto y no el nuestro.
        Con una ruta relativa la sesion entera muere al abrirse:

            stderr: Error: Invalid MCP configuration:
            stderr: MCP config file not found: <cwd del proyecto>\logs\...

        Y ese mensaje llega como `LineaIlegible`, o sea que el sintoma es
        un `Caida` sin codigo. Se resuelve aqui, una vez, y no en cada
        sitio que construya una: quien pasa una ruta no tiene por que
        saber contra que directorio se va a leer.
        """
        return str(Path(ruta).resolve())

    @property
    def orden(self) -> list[str]:
        """The exact command line, so it can be logged and reproduced."""
        return [
            "claude", "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            # >>> LO QUE HACE QUE SE PUEDA VER TRABAJAR, Y NO SOLO EL
            # RESULTADO <<< (2026-09-02, el POV)
            # Sin este flag un turno entero son 12 lineas: el `Write` se
            # anuncia y 0,19 s despues el archivo ya esta en disco, o sea
            # nueve segundos de nada y luego todo de golpe (medido,
            # `-m eval.sondas_claude_code.sonda_en_vivo`). Con el, el
            # CONTENIDO del documento llega en trozos mientras el modelo
            # lo redacta -- 17 trozos, 1468 caracteres repartidos en
            # 6,88 s en la medicion -- y eso se puede enseñar sin
            # inventar nada.
            # NO CUESTA UN TOKEN: es el mismo contenido, troceado. Y no
            # engorda el registro crudo, porque `_leer` no guarda los
            # trozos (ver alli el porque).
            "--include-partial-messages",
            "--model", self.modelo,
            *(("--effort", self.esfuerzo) if self.esfuerzo else ()),
            # `default` hace que la puerta llegue; `auto` deja sordo a
            # este modulo (medido el 2026-08-21, un `rm` sin un solo
            # aviso). Quien lo elige es el lanzador: ver `modo_permisos`.
            "--permission-mode", self.modo_permisos,
            FLAG_PUERTA, "stdio",
            # Lo unico que el cerebro sabe de que le hablan por un
            # altavoz. Va aqui y no en cada turno a proposito: es
            # constante durante toda la sesion, asi que repetirlo en cada
            # `mandar` seria pagarlo entero cada vez y ademas dejarlo
            # dentro del texto del usuario, donde el modelo no puede
            # distinguir lo que dijo una persona de lo que dijo el puente.
            *(("--append-system-prompt", self.preambulo)
              if self.preambulo else ()),
            # Los servidores MCP que trae Jarvis. Van por `--mcp-config` y
            # no por la configuracion global del usuario a proposito: sus
            # consolas de terminal son suyas (JC-0010) y esta es nuestra.
            *(("--mcp-config", self._absoluta(self.mcp_config))
              if self.mcp_config else ()),
            *(("--strict-mcp-config",) if self.mcp_estricto else ()),
            # El suelo de JC-0007. Va ANTES de `extra` a proposito: lo que
            # se pase a mano queda detras y se ve en la linea, en vez de
            # que un flag suelto tape el suelo sin dejar rastro.
            *(("--settings", self._absoluta(self.ajustes))
              if self.ajustes else ()),
            *self.extra,
        ]

    def abrir(self) -> None:
        """Start the process. The gate check happens on the first turn.

        IT CANNOT HAPPEN HERE, and that is measured, not a shortcut:
        `system/init` is not emitted when the process starts. It arrives
        once a turn is under way -- a session opened and left alone
        prints nothing at all. So `abrir` launches, `mandar` starts the
        turn, and the vetting rides on the `Inicio` that follows. It
        still lands before any `tool_use`, which is the only thing that
        matters: nothing has executed yet when the check runs.
        """
        if self._proceso is not None:
            raise PuenteError("la sesion ya estaba abierta")
        if self.registro is not None:
            self.registro.parent.mkdir(parents=True, exist_ok=True)
            self._archivo_registro = self.registro.open(
                "a", encoding="utf-8", newline="\n")

        self._proceso = subprocess.Popen(
            self.orden,
            cwd=self.directorio,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # Explicito y no por defecto: en Windows la codificacion del
            # sistema romperia las tildes, y lo que sale de aqui acaba en
            # el TTS. Medido: el transporte es UTF-8 correcto.
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            # >>> SIN CONSOLA PROPIA, Y NO ES COSMETICO <<<
            # `claude` es una aplicacion de consola. Cuando el padre NO
            # tiene una -- que es exactamente el caso de la carcasa, que
            # corre con `pythonw.exe` --, Windows le REGALA una ventana
            # nueva al hijo. Medido el 2026-08-27 con la sonda: 1 ventana
            # visible titulada 'claude'.
            #
            # El usuario la vio y pregunto lo correcto: por que al hacer
            # algo desde la interfaz se le abria una ventana de Claude
            # Code aparte. El flujo SI era el correcto -- esa era nuestra
            # sesion y su salida volvia por las tuberias --, pero la
            # ventana no pinta nada: no se puede escribir en ella (stdin
            # es una tuberia), no se lee de ella (stdout tambien), y
            # parece un segundo Jarvis que nadie abrio.
            #
            # No cambia nada mas: el proceso ya recibia las tres corrientes
            # por tuberia, asi que ya no era una TTY. Esto solo evita que
            # Windows le asigne una ventana.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(target=self._leer, daemon=True).start()
        threading.Thread(target=self._leer_errores, daemon=True).start()

    def esperar_inicio(self, limite: float = ESPERA_INICIO_S) -> Inicio:
        """Block until the session announces itself. Call after `mandar`.

        Raises if the gate is missing, so a caller that uses this gets
        the failure as an exception; a caller that just iterates
        `eventos` gets it as `SinPuerta`. Same fact, two shapes, because
        the console and a script want it differently.
        """
        fin = time.time() + limite
        while time.time() < fin:
            if self.inicio is not None:
                return self.inicio
            if self.fallo is not None:
                raise PuenteError(self.fallo)
            time.sleep(0.05)
        raise PuenteError("la sesion no se anuncio a tiempo")

    def cerrar(self) -> None:
        proceso, self._proceso = self._proceso, None
        if proceso is not None:
            try:
                if proceso.stdin:
                    proceso.stdin.close()
                proceso.wait(timeout=5)
            except Exception:
                proceso.kill()
        if self._archivo_registro is not None:
            self._archivo_registro.close()
            self._archivo_registro = None

    def cambiar_a(self, carpeta: str | Path,
                  modo_permisos: str | None = None) -> None:
        """Mueve la sesion a otro proyecto (ADR-0029, pasos 1-2).

        >>> EL MODO VIAJA CON LA CARPETA, Y TIENE QUE HACERLO (JC-0017) <<<
        El auto mode es una propiedad DEL PROYECTO, asi que cambiarse a
        uno sin repuntar el modo dejaria la sesion nueva con los permisos
        del proyecto anterior. Y el fallo seria mudo en las dos
        direcciones: entrar en un proyecto con freno desde otro sin freno
        significa que te empieza a preguntar y no sabes por que; al reves
        significa que dejo de preguntarte sin que nadie lo pidiera.
        `None` = no se toca, que es lo que quiere un cambio de carpeta
        que no venga del registro.

        CIERRA Y CAMBIA EL DIRECTORIO; no abre. La siguiente orden abrira
        el proceso ahi, que es como funciona el arranque mudo desde el
        principio: mientras nadie pida nada, no hay proceso de 337 MB y
        **no ha salido nada de la maquina**. Reabrir aqui tiraria esa
        propiedad por un cambio de carpeta.

        >>> SE CONSERVA EL OBJETO, Y ESO NO ES PEREZA <<<
        La consola, la voz y el escalado tienen una referencia a ESTA
        sesion. Crear otra obligaria a re-cablear las tres a la vez, y la
        que se olvidase seguiria hablando con la sesion vieja sin dar un
        solo error -- mirando un proyecto que ya nadie usa.

        Lo que NO se conserva es la conversacion: es otro proyecto, y
        arrastrar el contexto del anterior seria peor que empezar de cero.
        `session_id` se limpia por eso.
        """
        nueva = Path(carpeta).expanduser()
        if not nueva.is_dir():
            raise PuenteError(f"no existe la carpeta del proyecto: {nueva}")
        self.cerrar()
        self.directorio = str(nueva)
        self.session_id = None
        if modo_permisos is not None:
            self.modo_permisos = modo_permisos
        # Los servidores MCP y el suelo NO se tocan: son de la maquina y
        # del usuario, no del proyecto. Cambiar de carpeta no puede ser
        # una forma de estrenar permisos.
        # >>> Y EL MODO SI SE TOCA, QUE NO ES LA MISMA COSA <<<
        # El suelo es de la MAQUINA -- las zonas selladas siguen selladas
        # se abra el proyecto que se abra, y esta medido que muerden en
        # los cinco modos. El auto mode es del PROYECTO, porque es una
        # decision del usuario sobre codigo suyo. Por eso uno viaja y el
        # otro no.

    def __enter__(self) -> "Sesion":
        self.abrir()
        return self


    def __exit__(self, *_: object) -> None:
        self.cerrar()

    # --- hablar con la sesion --------------------------------------------

    def mandar(self, texto: str) -> None:
        """Send one user turn. The session must already be open."""
        self._olvidar_abierta()
        self._escribir({
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": texto}]},
        })

    def interrumpir(self) -> bool:
        """Para el turno que este en marcha. Es el "para" de JC-0011.

        >>> MEDIDO CONTRA EL BINARIO EL 2026-08-25, NO SUPUESTO <<<
        Sonda: `eval/sondas_claude_code/sonda_parar.py`. Traza cruda:
        `eval/trazas_claude_code/parada.jsonl`.

            ack del interrupt      0,01 s   {"still_queued": []}
            el turno cierra en     0,08 s   terminal_reason aborted_*
            la SESION SOBREVIVE    y el contexto tambien: al turno
                                   siguiente contesto "estaba a punto de
                                   crear sonda_parar_1.txt".
            contra disco           se pidieron 6 archivos, existen 0.

        Ese ultimo punto es el que importa: los mensajes dicen lo que se
        pidio, el disco dice lo que paso. La secuencia de herramientas se
        corto de verdad.

        LO QUE **NO** PARA, y hay que decirlo: un comando que YA se esta
        ejecutando. Si Claude Code lanzo un borrado y el borrado esta a
        medias, esto corta lo que venia DESPUES, no lo que ya salio. La
        defensa de eso es la puerta (JC-0001), que actua antes.

        Devuelve False si no habia sesion viva que interrumpir, que no es
        un fallo: es que no habia nada que parar.
        """
        if not self.viva:
            return False
        self._escribir({
            "type": "control_request",
            # Un id por parada: si se piden dos seguidas, dos acks
            # distintos, y en el registro crudo se ve cual contesto a
            # cual.
            "request_id": f"parada_{int(time.time() * 1000)}",
            "request": {"subtype": "interrupt"},
        })
        return True

    def responder(self, id_peticion: str, permitir: bool,
                  motivo: str = "", respuestas: dict[str, str] | None = None) -> bool:
        """Answer a pending gate. False means somebody already answered it.

        Returns False rather than raising: two channels racing is normal
        operation, not a bug, and the loser needs to be told so it can
        stop showing a question that no longer exists.

        >>> `respuestas` ES LO QUE CONTESTA DE VERDAD UNA PREGUNTA <<<
        Empareja el ENUNCIADO con la ETIQUETA elegida, y sin el, permitir
        un `AskUserQuestion` deja pasar la herramienta SIN DECIR QUE SE
        ELIGIO. Por fuera se ve igual -- el turno sigue y el modelo
        contesta algo --, que es justo por lo que estuvo asi hasta que se
        midio (2026-08-25, `eval/sondas_claude_code/sonda_pregunta.py`).
        Con `answers`, el resultado de la herramienta llega literalmente
        asi:

            "Your questions have been answered: "<enunciado>"="<etiqueta>".
             You can now continue with these answers in mind."

        y el modelo la nombra en su respuesta. Tambien funciona denegar
        con la eleccion escrita en el `message` -- se midio, y el modelo
        se entera igual --, pero eso marca la herramienta como error y
        aqui no hubo ningun error: hubo una respuesta.
        """
        with self._cerrojo:
            pendiente = self._pendientes.pop(id_peticion, None)
        if pendiente is None:
            return False
        if pendiente.es_pregunta and not permitir:
            # Denegar una pregunta es valido: es "no te contesto".
            pass
        self._responder_control(id_peticion, permitir, motivo,
                                pendiente.evento, respuestas)
        return True

    @property
    def viva(self) -> bool:
        proceso = self._proceso
        return proceso is not None and proceso.poll() is None

    @property
    def en_reposo(self) -> bool:
        """No hay proceso, y su ausencia NO es un fallo.

        >>> LA TERCERA SALIDA DE "ESTA VIVA?", Y FALTABA <<<
        (2026-09-09, encontrado probando un clon con `-m puente`.) Habia
        dos respuestas donde hay tres: **nunca se abrio** / **esta
        corriendo** / **se cayo**. `viva` es False en la primera y en la
        tercera, y quien lo leia las contaba como lo mismo, asi que la
        consola decia "caida" -- en rojo, con un contador subiendo --
        desde el primer segundo de cada arranque.
        Y ese es el estado NORMAL: el puente arranca mudo a proposito
        (ver `puente/__main__.py`), asi que la pantalla daba la alarma en
        cada boot, todos los dias, hasta la primera orden. Un aviso que
        se enciende siempre es un aviso que se aprende a ignorar -- que
        es justo lo que dice el comentario del senuelo tres archivos mas
        alla --, y encima la TERMINAL lo decia bien ("la sesion se abre
        con la PRIMERA ORDEN, no ahora"). Con `pythonw` no hay terminal:
        la unica version que se ve es la roja.

        >>> Y NO HACE FALTA UNA BANDERA NUEVA: EL DATO YA ESTABA <<<
        `_proceso` se asigna en exactamente dos sitios -- el `Popen` de
        `abrir` y el `None` de `cerrar` --, asi que:

            _proceso is None                      -> reposo
            _proceso vivo (`poll()` es None)      -> en marcha
            _proceso con codigo de salida         -> se cayo

        O sea que un cierre DELIBERADO (apagar, o `cambiar_a`, que cierra
        y repunta el directorio) tambien cae en reposo, que es lo
        correcto: ahi tampoco se ha roto nada.
        """
        return self._proceso is None

    @property
    def silencio_s(self) -> float:
        """Seconds since anything at all came off the wire.

        THE THIRD ANSWER for "is the other side alive?" -- si / no / no
        lo se. A live session that is thinking and a session whose
        network died look identical from here, and the measurement says
        the dead one can stay quiet for ~180 s while it retries. So
        silence is not evidence of failure and must not be reported as
        one; it is a doubt, and the caller decides at what point a doubt
        is worth saying out loud.
        """
        return time.time() - self.ultimo_evento_en

    @property
    def pendientes(self) -> tuple[Pendiente, ...]:
        """What is waiting on a human right now, oldest first."""
        with self._cerrojo:
            return tuple(sorted(self._pendientes.values(),
                                key=lambda p: p.pedido_en))

    # --- la pregunta que cierra el turno ---------------------------------

    @property
    def pregunta_abierta(self) -> "PreguntaAbierta | None":
        """La pregunta en prosa que dejo el ultimo turno, si la dejo.

        Va aparte de `pendientes` a proposito: ver `PreguntaAbierta`.
        """
        with self._cerrojo:
            return self._abierta

    def _anotar_abierta(self, fin: Fin) -> None:
        """Mira si el turno cerro preguntando, y lo apunta.

        >>> ESTO NO ESTABA, Y ESE ERA EL FALLO <<<
        Hasta el 2026-08-29 la unica pieza del arbol que miraba esto era
        `voz/bucle.py`, o sea que sin `--voz` no lo miraba NADIE. Y como
        una pregunta en prosa no deja nada en `_pendientes`, el escalado
        de JC-0006 recibia una tupla vacia y no tenia nada que mandar:
        Telegram no la descartaba, es que no la veia. Lo reporto el
        usuario probando el escalado, y son el 42 % de los turnos
        (`-m eval.mirar_preguntas`).

        Se hace aqui y no en el bucle de voz porque el turno cierra en un
        solo sitio, y porque los tres canales lo necesitan igual.
        """
        if fin.parado or fin.fue_mal or fin.sin_servidor:
            # Un turno que no llego a contestar no dejo ninguna pregunta.
            # `parado` va el primero por lo de siempre: una parada llega
            # disfrazada de error.
            return
        from voz.resumen import opciones_de_pregunta, pregunta_final

        pregunta = pregunta_final(fin.texto)
        if not pregunta:
            return
        opciones = opciones_de_pregunta(pregunta)
        with self._cerrojo:
            self._abiertas_vistas += 1
            self._abierta = PreguntaAbierta(
                id=f"abierta-{self._abiertas_vistas}",
                pregunta=pregunta,
                enunciado=opciones.enunciado or pregunta,
                etiquetas=opciones.etiquetas,
                forma=opciones.forma,
                abierta_en=time.time())

    def _olvidar_abierta(self) -> None:
        """Un turno nuevo deja la pregunta anterior sin efecto.

        Da igual quien lo mande -- la voz, la consola, Telegram o el
        propio ritual de ADR-0029 --: en cuanto hay otro turno, contestar
        a la pregunta de antes seria contestar a destiempo. Y sin esto,
        el escalado seguiria avisando por el movil de una pregunta que ya
        no esta en pantalla.
        """
        with self._cerrojo:
            self._abierta = None

    def contestar_abierta(self, id_abierta: str, texto: str) -> bool:
        """Contesta la pregunta en prosa. False si ya no estaba.

        >>> AQUI VIVE EL PRIMERA-RESPUESTA-GANA, Y HACIA FALTA <<<
        `responder` ya lo tenia: dos canales compitiendo por la misma
        puerta es lo normal, y el que pierde tiene que enterarse. Con
        `mandar` no habia nada, asi que contestar por voz y por el movil
        a la vez habria mandado DOS TURNOS -- y el segundo, encima,
        contestando a una pregunta que el modelo ya no tenia delante.

        Se comprueba el id, no solo que haya algo abierto: entre que
        Telegram lee un mensaje y lo enruta puede haber cerrado un turno
        y abierto otra pregunta distinta, y entonces el numero que mando
        el usuario ya no significa lo que el creia.
        """
        with self._cerrojo:
            abierta = self._abierta
            if abierta is None or abierta.id != id_abierta:
                return False
            self._abierta = None
        self.mandar(texto)
        return True

    def eventos(self, timeout: float | None = None) -> Iterator[Evento]:
        """Everything that comes off the wire, gates already triaged.

        Gates the policy allows are answered before they are yielded, and
        arrive as `Resuelta`. Gates that need a person are yielded as
        `Puerta` and stay pending until someone calls `responder`.
        """
        while True:
            try:
                evento = self._cola.get(timeout=timeout)
            except queue.Empty:
                return
            if evento is None:
                return
            yield evento

    # --- entrañas ---------------------------------------------------------

    def _escribir(self, objeto: dict[str, Any]) -> None:
        proceso = self._proceso
        if proceso is None or proceso.stdin is None:
            raise PuenteError("la sesion no esta abierta")
        with self._escritura:
            proceso.stdin.write(json.dumps(objeto) + "\n")
            proceso.stdin.flush()

    def _responder_control(self, id_peticion: str, permitir: bool,
                           motivo: str, evento: Puerta | Pregunta,
                           respuestas: dict[str, str] | None = None) -> None:
        if permitir:
            if isinstance(evento, Puerta):
                entrada: dict[str, Any] = dict(evento.entrada)
            else:
                # Una pregunta se contesta devolviendole su propia
                # entrada con las respuestas dentro. Devolver `{}` -- que
                # es lo que se hacia -- permite la herramienta y no
                # contesta nada.
                entrada = {"questions": list(evento.preguntas)}
                if respuestas:
                    entrada["answers"] = dict(respuestas)
            respuesta: dict[str, Any] = {"behavior": "allow",
                                         "updatedInput": entrada}
        else:
            respuesta = {"behavior": "deny",
                         "message": motivo or "El usuario no lo autorizo."}
        self._escribir({
            "type": "control_response",
            "response": {"subtype": "success", "request_id": id_peticion,
                         "response": respuesta},
        })

    def _leer(self) -> None:
        proceso = self._proceso
        if proceso is None or proceso.stdout is None:
            return
        try:
            for linea in proceso.stdout:
                eventos = interpretar(linea)
                # >>> LOS TROZOS NO SE GUARDAN, Y NO ES UN DESCUIDO <<<
                # `--include-partial-messages` multiplica el crudo por
                # cuatro (medido: 12,7 KB -> 49,9 KB el mismo turno) y no
                # aporta un solo dato nuevo: el mensaje `assistant` que
                # llega al final trae la entrada COMPLETA de la
                # herramienta y el texto entero, o sea que el trozo es esa
                # misma informacion partida. El registro existe para dos
                # cosas -- saber que paso, y escribir tests contra
                # capturas de verdad -- y para las dos vale el
                # mensaje completo. Con 50 sesiones a 1,9 MB de media,
                # guardarlos ademas seria multiplicar por cuatro el unico
                # archivo del arbol que lleva palabra por palabra lo que
                # el usuario dijo.
                if self._archivo_registro is not None and not _solo_troceo(eventos):
                    self._archivo_registro.write(
                        linea if linea.endswith("\n") else linea + "\n")
                    self._archivo_registro.flush()
                for evento in eventos:
                    self._encaminar(evento)
        except Exception as exc:  # noqa: BLE001
            # >>> UN FALLO AQUI DEJA EL PUENTE SORDO, Y HASTA HOY EN
            # SILENCIO <<< (2026-09-02)
            # Esto corre en un hilo daemon: una excepcion lo mata, Python
            # la imprime en un stderr que con `pythonw` NO EXISTE, y por
            # fuera se ve exactamente igual que una sesion que no
            # contesta -- la orden se manda, la pantalla la pinta y no
            # pasa nada nunca mas. Paso de verdad: un `NameError` por una
            # funcion que se llamaba y no existia dejo la consola muda un
            # rato entero, con 1235 tests en verde.
            # No se traga: se cuenta como lo que es, una caida, que es lo
            # unico que la pantalla ya sabe pintar.
            self._errores.append(f"leyendo la salida: {type(exc).__name__}: {exc}")
        self._anunciar_caida()
        self._cola.put(None)

    def _anunciar_caida(self) -> None:
        proceso = self._proceso
        codigo = proceso.poll() if proceso is not None else None
        with self._cerrojo:
            perdidas = len(self._pendientes)
            self._pendientes.clear()
        self._cola.put(Caida(
            codigo=codigo,
            errores=tuple(self._errores[-5:]),
            pendientes_perdidas=perdidas,
        ))

    def _leer_errores(self) -> None:
        proceso = self._proceso
        if proceso is None or proceso.stderr is None:
            return
        for linea in proceso.stderr:
            if linea.strip():
                self._errores.append(linea.rstrip())
                self._cola.put(LineaIlegible(crudo=f"stderr: {linea.rstrip()}"))

    def _encaminar(self, evento: Evento) -> None:
        """Where the gate is actually held."""
        self.ultimo_evento_en = time.time()

        if isinstance(evento, Reintento):
            self.reintentando = evento
            self._cola.put(evento)
            return

        if isinstance(evento, Limite):
            self.limite = evento
            self._cola.put(evento)
            return

        if isinstance(evento, Fin):
            # Un turno que termina es la prueba de que la red volvio.
            self.reintentando = None
            self._anotar_abierta(evento)

        if isinstance(evento, Pregunta):
            # NUNCA la contesta la politica. Se pone a esperar a alguien.
            self._anotar(evento, None)
            self._cola.put(evento)
            return

        if isinstance(evento, Puerta):
            decision = decidir(evento, directorio_sesion=self.directorio,
                               zonas=self.zonas,
                               servidores_mcp=self.servidores_mcp)
            if decision.regla == "mcp_no_declarado":
                from nucleo.mcp import servidor_de

                quien = servidor_de(evento.herramienta)
                if quien:
                    self.mcp_vistos.add(quien)
            if decision.veredicto is Veredicto.PERMITIR:
                self._responder_control(evento.id_peticion, True, "", evento)
                self._cola.put(Resuelta(puerta=evento, decision=decision))
                return
            if decision.veredicto is Veredicto.DENEGAR:
                # El suelo es FIJO: preguntar aqui seria ofrecer un "si"
                # que no existe. Se deniega y se anuncia, porque una
                # negativa que no deja rastro no se distingue de un fallo.
                self._responder_control(evento.id_peticion, False,
                                        decision.motivo, evento)
                self._cola.put(Resuelta(puerta=evento, decision=decision))
                return
            self._anotar(evento, decision)
            self._cola.put(evento)
            return

        if isinstance(evento, Inicio):
            self.inicio = evento
            self.session_id = evento.session_id
            self._cola.put(evento)
            if not evento.puede_preguntar:
                self.fallo = (
                    f"la sesion arranco SIN puerta: {FLAG_PUERTA} no hizo "
                    "efecto y Claude Code decidira los permisos solo. No se "
                    "sigue: el usuario no consentiria nada."
                )
                self._cola.put(SinPuerta(motivo=self.fallo))
                self._matar()
            return

        if isinstance(evento, Fin) and evento.session_id:
            self.session_id = evento.session_id
        self._cola.put(evento)

    def _matar(self) -> None:
        """Pull the plug from the reader thread. No waiting, no joining."""
        proceso = self._proceso
        if proceso is not None and proceso.poll() is None:
            proceso.kill()

    def _anotar(self, evento: Puerta | Pregunta, decision: Decision | None) -> None:
        with self._cerrojo:
            self._pendientes[evento.id_peticion] = Pendiente(
                evento=evento, decision=decision, pedido_en=time.time())


def _solo_troceo(eventos: list[Evento]) -> bool:
    """La linea era SOLO troceo, o sea que no aporta nada al registro.

    >>> SE DECIDE SOBRE LOS EVENTOS Y NO BUSCANDO TEXTO EN LA LINEA <<<
    Un `"type":"stream_event"` a pelo casaria tambien dentro del contenido
    de un archivo que Claude estuviera escribiendo, que es justo la clase
    de regla que en este proyecto ya ha mentido cuatro veces sobre lo que
    hace una orden. La linea ya esta interpretada aqui arriba: se mira
    lo que salio.

    Vacia NO es troceo: una linea que no produjo ningun evento es algo
    que no entendimos, y eso se guarda -- es la unica pista que quedaria.
    """
    if not eventos:
        return False
    return all(
        isinstance(e, (AbreMensaje, AbreBloque, Trozo, CierraBloque))
        or (isinstance(e, Desconocido) and e.tipo.startswith("stream_event"))
        for e in eventos)
