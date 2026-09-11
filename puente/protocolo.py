"""Reading the wire Claude Code speaks, and turning it into events.

Claude Code talks `stream-json`: one JSON object per line on stdout. This
module is the only place that knows that shape. Everything above it works
with the events below and never touches a raw dict.

WHAT THE WIRE ACTUALLY CARRIES, measured on 2026-08-21 against
`claude 2.1.239` and kept as fixtures in `eval/trazas_claude_code/`. The
parser is written against those captures, never against JSON typed by
hand -- the rule of this project: una sonda que construye su propia
entrada mide la sonda.

THE ONE DISTINCTION THAT MATTERS, and it is not obvious from the type
alone: **an approval and a question arrive as the SAME message type.**
Both come as `control_request` / `can_use_tool`. What separates them is a
single field:

    tool_name        requires_user_interaction
    Write            (ausente)                  -> es una APROBACION
    Bash             (ausente)                  -> es una APROBACION
    AskUserQuestion  True                       -> es una PREGUNTA

Verified across the four gates in the three fixtures. The difference is
not cosmetic: an approval may be answered by policy without waking
anyone, and **a question may never be**. Collapsing them would let the
bridge answer on the user's behalf, which is exactly the second agent
ADR-0018 refused. So they are two event types here, not one with a flag.

WHAT IS NOT ON THIS WIRE: not every tool call passes through a gate.
Measured -- a `Read`, and a shell `ls -la`, execute without ever asking,
in `default` and in `manual` alike. The gate is Claude Code's ASKS, not
an inventory of what it did. For "what happened" the source is the
`UsoHerramienta` stream, which does carry them. Two different questions:
one is "que paso", the other "quien dijo que si".

UNKNOWN IS NOT EMPTY. A message type this module does not recognise comes
out as `Desconocido`, and a line that is not JSON comes out as
`LineaIlegible`. Neither is dropped. Claude Code is an external
dependency that will grow message types without asking us, and a parser
that silently discards what it does not understand is how a bridge goes
quietly deaf.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


class Evento:
    """Anything that came off the wire. Base class, never instantiated."""


ESTADOS_MCP_CONOCIDOS = ("connected", "failed", "needs-auth")
"""Lo que se ha VISTO decir al binario, y nada mas.

Medido el 2026-09-07 sobre los `system/init` de `logs/puente/`: los tres
salen ahi. La lista existe para poder decir "esto no lo conozco" en vez
de meterlo en el cajon de los buenos: Claude Code va a inventarse estados
nuevos sin preguntarnos, igual que hizo con `unifiedWindows` en la cuota.
"""


@dataclass(frozen=True)
class ServidorMcp:
    """Un servidor MCP y si llego a levantarse, tal y como lo dijo el init.

    >>> ESTO SE TIRABA, Y COSTO TRES SESIONES (2026-09-07) <<<
    `system/init` trae `mcp_servers` desde siempre y este modulo se
    quedaba solo con `tools`. El 09-04 `blender` estuvo **`failed` tres
    sesiones seguidas** -- un `${UV_SYSTEM_CERTS}` sin resolver que `uv`
    rechaza por no ser booleano -- y Jarvis no lo dijo NUNCA, porque no
    habia donde decirlo: el unico sintoma era que la herramienta no
    estaba, y eso se parece muchisimo a que el modelo decidiera no
    usarla. Dos fallos distintos con el mismo sintoma, que es la forma
    que este proyecto lleva persiguiendo desde la cuota.

    `crudo` se conserva ademas del veredicto a proposito: si manana
    aparece un estado nuevo, la pantalla puede escribir la palabra exacta
    que llego en vez de tragarsela.
    """

    nombre: str
    crudo: str
    """El `status` literal del init. Nunca se normaliza a la baja."""

    @property
    def arranco(self) -> bool | None:
        """Si esta disponible. **TRES respuestas, no dos**.

        `None` es "no se sabe", y es lo que devuelve un estado que no
        esta en `ESTADOS_MCP_CONOCIDOS`. Colapsarlo contra `False`
        pintaria una alarma por algo que quiza funciona; contra `True`
        haria justo lo que costo las tres sesiones. `needs-auth` SI se
        sabe y NO arranco: falta que alguien entre.
        """
        if self.crudo == "connected":
            return True
        if self.crudo in ("failed", "needs-auth"):
            return False
        return None

    @property
    def necesita_login(self) -> bool:
        """No es un fallo. Son los tres de `claude.ai` y llevan ahi
        desde el principio: pintarlos en rojo seria una alarma diaria
        por algo que el usuario no ha pedido nunca."""
        return self.crudo == "needs-auth"

    @property
    def fallo(self) -> bool:
        """Esto SI es un fallo: se intento levantar y no subio."""
        return self.crudo == "failed"

    def a_json(self) -> dict[str, Any]:
        return {"nombre": self.nombre, "estado": self.crudo,
                "arranco": self.arranco, "fallo": self.fallo,
                "necesita_login": self.necesita_login}


@dataclass(frozen=True)
class Inicio(Evento):
    """The session announced itself. Always the first useful line."""

    session_id: str
    directorio: str
    modelo: str
    modo_permisos: str
    herramientas: tuple[str, ...]
    servidores: tuple[ServidorMcp, ...] = ()
    """Los MCP y su estado. Vacio significa NINGUNO, que es lo normal."""

    @property
    def mcp_caidos(self) -> tuple[ServidorMcp, ...]:
        """Los que hay que decir. Un estado desconocido entra aqui.

        No entra `needs-auth`: no arranco, pero no esta roto, y la
        pantalla los separa porque la accion del usuario es otra.
        """
        return tuple(s for s in self.servidores
                     if s.arranco is not True and not s.necesita_login)

    @property
    def puede_preguntar(self) -> bool:
        """Whether this session can ask the user anything at all.

        Measured: without `--permission-prompt-tool stdio`, Claude Code
        does not even load `AskUserQuestion`. A session where this is
        False can still work, but it will silently decide on its own
        every time it should have asked. That is not a degraded mode, it
        is a different product, and `sesion.py` refuses to start on it.
        """
        return "AskUserQuestion" in self.herramientas


@dataclass(frozen=True)
class Texto(Evento):
    """Prose meant for the user. This is what gets spoken and shown."""

    texto: str


@dataclass(frozen=True)
class Pensamiento(Evento):
    """Reasoning. Shown in the console, NEVER spoken and never summarised.

    It is the model thinking out loud, not an answer, and reading it
    aloud would be the `</think>` leak of 2026-08-04 all over again --
    which that day reached the user through a path the tests did not
    cover.
    """

    texto: str


@dataclass(frozen=True)
class UsoHerramienta(Evento):
    """Claude Code is about to use a tool. Arrives whether it asks or not."""

    id_uso: str
    herramienta: str
    entrada: dict[str, Any]


@dataclass(frozen=True)
class Imagen:
    """Una imagen que devolvio una herramienta. NO es un `Evento`.

    >>> HASTA EL 2026-09-01 ESTO SE TIRABA, Y EN SILENCIO <<<
    `_texto_de` se quedaba solo con los bloques `text`, asi que un bloque
    `image` desaparecia sin dejar rastro. Con el MCP de Blender eso
    significa que `get_viewport_screenshot` llegaba hasta aqui, **Claude
    la veia y el usuario no**. No faltaba vision: faltaba mirar lo que ya
    llegaba.

    `datos` es base64 tal y como vino, sin decodificar: quien la vaya a
    servir decidira, y decodificar aqui seria pagar la memoria de todas
    las que pasen aunque nadie las mire.
    """

    tipo: str
    """El media type, `image/png` y compania."""
    datos: str
    """base64, en crudo."""


@dataclass(frozen=True)
class ResultadoHerramienta(Evento):
    """How a tool call ended. `es_error` includes 'the user said no'."""

    id_uso: str
    contenido: str
    es_error: bool
    imagenes: tuple[Imagen, ...] = ()
    """>>> NO VIAJA A LA PAGINA TAL CUAL, Y ES DELIBERADO <<<
    Una captura son cientos de KB en base64. `consola.a_json` hace
    `asdict` de cada evento, asi que dejarlas aqui las meteria enteras en
    el JSON de CADA cliente conectado. La pagina recibe un recuento y las
    pide por id. Ver `puente/producido.py`.
    """


@dataclass(frozen=True)
class Puerta(Evento):
    """An approval request. Nothing has been executed yet.

    `entrada` is the whole truth of what will run, and it is what the
    spoken sentence and the console must BOTH be built from. If the two
    forms are derived separately they can drift, and then the user
    approves one thing while another executes.
    """

    id_peticion: str
    herramienta: str
    entrada: dict[str, Any]
    descripcion: str
    id_uso: str
    ruta_afectada: str | None = None
    """The resolved path this action touches, when Claude Code names one.

    On the wire the field is called `blocked_path`, and the name lies.
    Measured on the three fixtures: it appeared on both `rm` gates and
    carried the absolute path of the file to be deleted -- **inside the
    session directory in every case**. It is not "this path is
    forbidden"; it is "this is what the command resolves to".

    That makes it better material than parsing the command line
    ourselves, which is why the policy prefers it when naming what an
    action touches. Reading it as a veto would have hardened every
    single shell gate, which is how it was first written here.
    """

    @property
    def orden_shell(self) -> str | None:
        """The command line, when this gate is a shell call."""
        if self.herramienta not in ("Bash", "PowerShell"):
            return None
        orden = self.entrada.get("command")
        return orden if isinstance(orden, str) else None


@dataclass(frozen=True)
class Pregunta(Evento):
    """Claude Code is asking the USER something. Policy must not answer it.

    Comes down the same channel as `Puerta` and is told apart by
    `requires_user_interaction`. Kept separate on purpose: see the module
    docstring.
    """

    id_peticion: str
    id_uso: str
    preguntas: tuple[dict[str, Any], ...]

    @property
    def enunciados(self) -> tuple[str, ...]:
        """Just the question texts, for the spoken form."""
        return tuple(
            str(p.get("question", "")) for p in self.preguntas if p.get("question")
        )


@dataclass(frozen=True)
class Fin(Evento):
    """The turn is over. The session stays alive and accepts another."""

    session_id: str
    subtipo: str
    es_error: bool
    texto: str
    coste_usd: float
    duracion_ms: int
    num_turnos: int
    estado_error_api: str | None = None
    razon_terminal: str = ""

    @property
    def fue_mal(self) -> bool:
        """Whether this turn failed. DO NOT read `subtipo` for this.

        >>> `subtipo` MIENTE EN EL FALLO DE RED, y esta medido. <<<
        Con el CLI apuntado a una direccion muerta, tras 174 s y diez
        reintentos, el turno cerro asi:

            subtype:         "success"      <-- eso dice
            is_error:        true
            terminal_reason: "api_error"
            result:          "API Error: Connection refused ..."

        Un `subtype == "success"` sobre un fallo total. Quien decida por
        ese campo dara por buena una respuesta que nunca existio, y en un
        asistente por voz eso se convierte en decirle al usuario que todo
        fue bien. Los campos que dicen la verdad son `is_error` y
        `terminal_reason`, y por eso se miran los cuatro.
        """
        return (
            self.es_error
            or bool(self.estado_error_api)
            or (self.razon_terminal not in ("", "completed"))
        )

    @property
    def sin_servidor(self) -> bool:
        """Whether the turn died because it could not reach the API."""
        return self.razon_terminal == "api_error"

    @property
    def parado(self) -> bool:
        """El turno no fallo: lo paro alguien. Y hay que mirarlo ANTES.

        >>> UNA PARADA LLEGA DISFRAZADA DE ERROR, Y ESTA MEDIDO <<<
        Al mandar `control_request / interrupt` (2026-08-25, sonda
        `eval/sondas_claude_code/sonda_parar.py`, traza cruda en
        `eval/trazas_claude_code/parada.jsonl`), el turno cierra asi:

            subtype:         "error_during_execution"
            is_error:        true
            terminal_reason: "aborted_streaming"  <- o "aborted_tools"
            result:          null

        O sea que `fue_mal` dice True, y dice la verdad -- el turno no
        termino --, pero la CAUSA es que el usuario dijo "para". Quien
        lea solo `fue_mal` le contestara "algo ha ido mal" a alguien que
        acaba de mandarle callar, que es la peor manera de obedecer.

        DOS RAZONES Y NO UNA, segun donde le pillara: `aborted_streaming`
        si estaba escribiendo, `aborted_tools` si estaba encadenando
        herramientas. Las dos se midieron el mismo dia.
        """
        return self.razon_terminal in ("aborted_streaming", "aborted_tools")


@dataclass(frozen=True)
class Ventana:
    """One quota clock: how much is spent and when it comes back.

    There are two of them and they are not interchangeable. The session
    window comes back in hours; the weekly one can be days away. Telling
    somebody "se acabo" without saying which clock, or when it returns,
    is not an answer anybody can act on.
    """

    utilizacion: float
    reinicia_en: int | None = None

    @property
    def porcentaje(self) -> int:
        return int(round(self.utilizacion * 100))

    def caducada(self, ahora: float | None = None) -> bool | None:
        """Si este reloj ya se reinicio, o sea si su cifra es de un pasado.

        >>> TRES RESPUESTAS, NO DOS, Y ES EL SINTOMA DEL 2026-09-04 <<<
        Lo reporto el usuario: al llegar al limite de la sesion basta con
        esperar a que la ventana se reinicie para volver a trabajar, pero
        las cuotas de la pantalla no se actualizaban hasta reiniciar
        Jarvis entero.
        Y la causa esta en el codigo, no en el transporte: `Sesion.limite`
        guarda el ULTIMO evento y nadie lo caduca nunca -- `reinicia_en`
        solo se usaba para escribir "vuelve a las 02:10". O sea que una
        ventana que se agoto a las 21:00 y se reinicio a las 01:20 seguia
        diciendo 97 % a las 03:00, y no era mentira de nadie: era una
        cifra correcta de una ventana que ya no existe.
        Y el momento en que se lee es justo el peor: al agotarse la cuota
        se DEJA de trabajar, o sea que no hay turnos, o sea que no llega
        ningun evento nuevo que la pise. La unica forma de moverla era
        reiniciar Jarvis, que es lo que el usuario acabo haciendo.

        MEDIDO CONTRA LOS LOGS REALES: los `rate_limit_event` llegan de
        sobra -- 265 en 139 turnos de 68 sesiones, o sea ~2 por turno, y
        en 168 de los huecos ni siquiera cambia el turno --, asi que el
        numero SI se refresca en cuanto se trabaja. Lo que no existia era
        la respuesta para el rato de en medio.
        Ese rato no aparece en el corpus (0 sesiones siguieron vivas
        pasado el reinicio de su ventana), y por eso esto no se justifica
        con una tasa: se justifica con el mecanismo, que si
        esta leido. Las sesiones de ese corpus son cortas; Jarvis en uso
        arranca con Windows y vive el dia entero.

        >>> Y LO QUE DEVUELVE NO ES UN CERO <<< Una ventana caducada NO
        significa "0 % gastado": significa que no se sabe cuanto se lleva
        hasta que llegue el proximo evento. Escribir 0 seria repetir
        exactamente el fallo que costo seis dias de "cuota al 0 %".
        Sin `reinicia_en` la respuesta es `None`, que es la tercera.
        """
        if self.reinicia_en is None:
            return None
        return (time.time() if ahora is None else ahora) >= self.reinicia_en


@dataclass(frozen=True)
class Limite(Evento):
    """How much of the quota is spent, and when it comes back.

    Captured verbatim on 2026-08-21, mid-session and unprompted:

        {"status": "allowed_warning", "rateLimitType": "seven_day",
         "utilization": 0.86, "resetsAt": 1787619600,
         "isUsingOverage": false, "surpassedThreshold": 0.75}

    >>> Y ESA FORMA YA NO ES LA QUE LLEGA. MEDIDO EL 2026-09-03 <<<
    Lo reporto el usuario: la cuota que ensenabamos no era la real --
    salia la semanal -- y ademas parecia venir siempre a 0, cosa que no
    era.
    Tenia razon, y el conteo sobre los 195 `rate_limit_event` reales de
    `logs/puente/` dice exactamente por que:

        eventos con `utilization` arriba ....  75 de 195  (39 %)
        eventos SIN `utilization` arriba ... 120 de 195  (61 %)
        eventos con `unifiedWindows` ....... 193 de 195  (98 %)

    O sea que el campo del que leiamos DESAPARECIO de la mayoria de los
    eventos, y los numeros de verdad se mudaron a un campo que no
    mirabamos. La forma nueva, copiada de un evento real del dia 3:

        {"status": "allowed", "rateLimitType": "five_hour",
         "resetsAt": 1788426600, "overageStatus": "rejected",
         "unifiedWindows": {
            "five_hour": {"utilization": 0.30, "resetsAt": 1788426600},
            "seven_day": {"utilization": 0.37, "resetsAt": 1788829200}}}

    >>> Y EL FALLO ERA MUDO, QUE ES LO QUE LO HIZO DURAR <<<
    `float(info.get("utilization") or 0.0)` no da error cuando la clave
    no esta: da **0.0**, que es un numero perfectamente creible para una
    cuota. La pantalla decia "0 %" con toda la confianza del mundo. Es
    otra vez el mismo colapso -- "no lo se" contra un valor --, y por
    eso ahora las dos ventanas son `None` cuando no vienen y la pantalla
    tiene que escribir "?" en vez de un cero.

    LAS DOS VENTANAS VIENEN EN EL MISMO EVENTO, y eso cambia la
    pantalla: hasta hoy `Sesion.limite` guardaba el ultimo evento y la
    consola ensenaba UN reloj, el que trajera `rateLimitType` -- por eso
    se veia "semanal" o "sesion" segun el momento, sin que nadie lo
    hubiera elegido. Con `unifiedWindows` se pueden ensenar los dos
    siempre, que es lo que se preguntaba: cuanto le queda a la sesion de
    ahora y que tan llena esta la semana.

    `tipo` se conserva crudo: es el reloj que motivo el aviso, y sigue
    siendo lo que decide si hay que hablar.

    `agotado` IS INFERRED, NOT MEASURED. Forcing a real exhaustion means
    burning the user's actual quota, so the only status seen with our own
    eyes is `allowed_warning`. Anything that is not an explicit allow is
    therefore treated as spent, which errs towards telling the user too
    early. If the real exhausted status ever shows up in a log, this is
    the line to correct, and `estado` is kept raw precisely so the log
    can prove what came.
    """

    estado: str
    tipo: str
    utilizacion: float
    reinicia_en: int | None = None
    en_exceso: bool = False
    umbral_superado: float | None = None
    sesion: Ventana | None = None
    """El reloj corto (`five_hour`). `None` es NO SE SABE, jamas cero."""
    semana: Ventana | None = None
    """El reloj largo (`seven_day`). `None` es NO SE SABE, jamas cero."""

    @property
    def agotado(self) -> bool:
        """Whether the quota looks spent. See the caveat above."""
        return not self.estado.startswith("allowed")

    @property
    def es_semanal(self) -> bool:
        return "seven" in self.tipo or "week" in self.tipo

    @property
    def porcentaje(self) -> int:
        return int(round(self.utilizacion * 100))


@dataclass(frozen=True)
class Reintento(Evento):
    """Claude Code cannot reach its server and is backing off.

    THE REASON THIS EVENT HAS TO EXIST: measured with the CLI pointed at
    a dead address, a disconnected session is INDISTINGUISHABLE from a
    session that is thinking hard. No error, no exit, no `result` -- it
    emits `init` and then goes quiet. The only thing that betrays it is
    this.

    Measured backoff, ten attempts, real values in ms:

        523, 1070, 2197, 4003, 8150, 18711, 38871, 39337, 32307, 34694

    That is **~180 s of silence** before the retries are even used up. A
    voice assistant that says nothing for three minutes is broken as far
    as the user is concerned, so the bridge speaks up on the FIRST
    retry, not on the last.
    """

    intento: int
    intentos_maximos: int
    espera_ms: int
    estado_error: str | None = None
    error: str = ""

    @property
    def es_el_ultimo(self) -> bool:
        return self.intento >= self.intentos_maximos

    @property
    def espera_s(self) -> float:
        return self.espera_ms / 1000.0


@dataclass(frozen=True)
class Desconocido(Evento):
    """A message type this module does not know. Logged, never discarded."""

    tipo: str
    crudo: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass(frozen=True)
class LineaIlegible(Evento):
    """Something on stdout that was not JSON.

    Claude Code does print the odd plain-text warning (`no stdin data
    received in 3s` is one). It is not a crash and must not become one.
    """

    crudo: str


# --------------------------------------------------------------------
# LOS TROZOS: ver trabajar, y no solo el resultado (2026-09-02)
# --------------------------------------------------------------------
#
# >>> POR QUE ESTOS EVENTOS SON DISTINTOS DE TODOS LOS DEMAS <<<
# Los demas cuentan algo que YA PASO y se apuntan en el registro. Estos
# son el mismo hecho llegando a plazos: el `assistant` que viene detras
# trae la entrada COMPLETA de la herramienta y el texto entero, asi que
# un trozo no añade informacion -- añade el MOMENTO en que se supo.
# Por eso no se guardan en el registro crudo (ver `Sesion._leer`) y por
# eso la consola no los pinta en el flujo: alimentan el visor y nada mas.
#
# Medido contra `claude` real antes de escribir esto
# (`-m eval.sondas_claude_code.sonda_pov`, 2026-09-02):
#   * el contenido de un `Write` llega en 17 trozos de ~97 caracteres
#     repartidos en 6,88 s -- o sea que se ve escribirse de verdad;
#   * el mayor rato sin que llegue NADA en todo el turno es de 1,05 s,
#     asi que un visor colgado de esto no parece congelado;
#   * la SALIDA de una herramienta llega SIEMPRE en un solo trozo
#     (`Read` 1400 caracteres, `PowerShell` 370). Ver leer no existe en
#     el transporte, y pintarlo seria inventarselo.


@dataclass(frozen=True)
class AbreBloque(Evento):
    """Empieza algo que se va a ir generando: prosa, pensamiento o el
    input de una herramienta.

    `indice` viene del binario y **REINICIA en cada mensaje**, no en cada
    turno: un turno con tres herramientas trae tres mensajes y tres
    indices 0. Quien lleve la cuenta tiene que contar los mensajes
    tambien -- lo hace `puente/camara.py`. Costo una medicion entera:
    la primera version de la sonda indexaba solo por `indice`, el bloque
    del `Write` lo machacaba el `Read` siguiente, y la tabla salio
    tranquilizadora y falsa.
    """

    indice: int
    clase: str
    """`text`, `thinking` o `tool_use`."""
    herramienta: str = ""
    id_uso: str = ""


@dataclass(frozen=True)
class Trozo(Evento):
    """Un pedazo de lo que se esta generando ahora mismo."""

    indice: int
    clase: str
    """`text_delta`, `thinking_delta` o `input_json_delta`."""
    texto: str = ""


@dataclass(frozen=True)
class CierraBloque(Evento):
    """Ese bloque ya esta entero."""

    indice: int


@dataclass(frozen=True)
class AbreMensaje(Evento):
    """Empieza un mensaje del asistente, y con el los indices vuelven a
    cero. Es lo unico que hace falta para no confundir dos bloques."""


def _trozo(mensaje: dict[str, Any]) -> list[Evento]:
    evento = mensaje.get("event")
    if not isinstance(evento, dict):
        return [Desconocido(tipo="stream_event", crudo=mensaje)]
    clase = evento.get("type")
    indice = evento.get("index")
    indice = int(indice) if isinstance(indice, int) else -1

    if clase == "message_start":
        return [AbreMensaje()]
    if clase == "content_block_start":
        bloque = evento.get("content_block")
        bloque = bloque if isinstance(bloque, dict) else {}
        return [AbreBloque(
            indice=indice,
            clase=str(bloque.get("type") or ""),
            herramienta=str(bloque.get("name") or ""),
            id_uso=str(bloque.get("id") or ""),
        )]
    if clase == "content_block_delta":
        delta = evento.get("delta")
        delta = delta if isinstance(delta, dict) else {}
        # Los tres nombres del texto segun de que bloque venga. Un
        # `signature_delta` no trae nada que enseñar y cae aqui como un
        # trozo vacio, que es lo que es.
        texto = (delta.get("text") or delta.get("partial_json")
                 or delta.get("thinking") or "")
        return [Trozo(indice=indice, clase=str(delta.get("type") or ""),
                      texto=str(texto))]
    if clase == "content_block_stop":
        return [CierraBloque(indice=indice)]
    # `message_delta` y `message_stop` no dicen nada que el visor pueda
    # enseñar, y el `result` que viene detras ya cierra el turno. No se
    # tiran en silencio: se declaran como lo que son.
    return [Desconocido(tipo=f"stream_event/{clase}", crudo=mensaje)]


def interpretar(linea: str) -> list[Evento]:
    """Turn one line of `stream-json` into zero or more events.

    One line can carry several events: an `assistant` message holds a
    list of content blocks, and a single one of those lines routinely
    mixes thinking, prose and a tool call.
    """
    linea = linea.strip()
    if not linea:
        return []
    try:
        mensaje = json.loads(linea)
    except json.JSONDecodeError:
        return [LineaIlegible(crudo=linea)]
    if not isinstance(mensaje, dict):
        return [LineaIlegible(crudo=linea)]

    tipo = mensaje.get("type")
    if tipo == "system":
        return _sistema(mensaje)
    if tipo == "assistant":
        return _asistente(mensaje)
    if tipo == "user":
        return _usuario(mensaje)
    if tipo == "control_request":
        return _peticion_de_control(mensaje)
    if tipo == "result":
        return [_fin(mensaje)]
    if tipo == "stream_event":
        return _trozo(mensaje)
    if tipo == "rate_limit_event":
        info = mensaje.get("rate_limit_info") or {}
        reinicia = info.get("resetsAt")
        umbral = info.get("surpassedThreshold")
        clase = str(info.get("rateLimitType", ""))
        ventanas = info.get("unifiedWindows")
        sesion = _ventana(ventanas, "five_hour")
        semana = _ventana(ventanas, "seven_day")
        # >>> DE DONDE SALE `utilizacion` CUANDO ARRIBA NO VIENE <<<
        # En el 61 % de los eventos reales la clave no esta, y leerla con
        # `or 0.0` daba un CERO creible. La ventana que corresponde al
        # reloj que motivo el aviso es la misma cifra que traia antes, o
        # sea que esto no inventa nada: la busca donde se mudo.
        propia = semana if ("seven" in clase or "week" in clase) else sesion
        arriba = info.get("utilization")
        if arriba is None and propia is not None:
            arriba = propia.utilizacion
        return [Limite(
            estado=str(info.get("status", "")),
            tipo=clase,
            utilizacion=float(arriba or 0.0),
            reinicia_en=int(reinicia) if reinicia is not None else None,
            en_exceso=bool(info.get("isUsingOverage")),
            umbral_superado=float(umbral) if umbral is not None else None,
            sesion=sesion,
            semana=semana,
        )]
    return [Desconocido(tipo=str(tipo), crudo=mensaje)]


def _ventana(ventanas: Any, clave: str) -> Ventana | None:
    """Un reloj de `unifiedWindows`, o `None` si no vino.

    >>> `None` NO ES CERO, Y ESA ES TODA LA FUNCION <<< Devolver 0.0
    cuando el dato falta es lo que tuvo la consola ensenando "0 %" de
    cuota durante seis dias sin un solo error. Si el campo no esta, la
    respuesta es "no se sabe" y la pantalla lo escribe.
    """
    if not isinstance(ventanas, dict):
        return None
    cruda = ventanas.get(clave)
    if not isinstance(cruda, dict):
        return None
    uso = cruda.get("utilization")
    if uso is None:
        return None
    reinicia = cruda.get("resetsAt")
    try:
        return Ventana(utilizacion=float(uso),
                       reinicia_en=int(reinicia) if reinicia is not None
                       else None)
    except (TypeError, ValueError):
        # Un numero que no es un numero es lo mismo que no tenerlo: no se
        # sabe. Lo que no puede pasar es que tumbe el lector de la sesion,
        # que corre en un hilo daemon y muere callado.
        return None


def _sistema(mensaje: dict[str, Any]) -> list[Evento]:
    subtipo = mensaje.get("subtype")
    if subtipo == "api_retry":
        return [Reintento(
            intento=int(mensaje.get("attempt") or 0),
            intentos_maximos=int(mensaje.get("max_retries") or 0),
            espera_ms=int(mensaje.get("retry_delay_ms") or 0),
            estado_error=mensaje.get("error_status"),
            error=str(mensaje.get("error") or ""),
        )]
    if subtipo != "init":
        # `thinking_tokens` and friends are progress noise, not events.
        return []
    return [Inicio(
        session_id=str(mensaje.get("session_id", "")),
        directorio=str(mensaje.get("cwd", "")),
        modelo=str(mensaje.get("model", "")),
        modo_permisos=str(mensaje.get("permissionMode", "")),
        herramientas=tuple(mensaje.get("tools") or ()),
        servidores=_servidores_mcp(mensaje.get("mcp_servers")),
    )]


def _servidores_mcp(crudo: Any) -> tuple[ServidorMcp, ...]:
    """`mcp_servers` del init -> piezas. Lo que no cuadre se ignora.

    Un elemento sin nombre no se puede pintar ni nombrar, asi que no es
    "un servidor en estado desconocido": no es un servidor. Y un `status`
    ausente SI entra, con el crudo vacio, que `arranco` clasifica como
    "no se sabe" -- que es exactamente lo que es.
    """
    if not isinstance(crudo, list):
        return ()
    piezas = []
    for entrada in crudo:
        if not isinstance(entrada, dict):
            continue
        nombre = entrada.get("name")
        if not nombre:
            continue
        piezas.append(ServidorMcp(nombre=str(nombre),
                                  crudo=str(entrada.get("status") or "")))
    return tuple(piezas)


def _asistente(mensaje: dict[str, Any]) -> list[Evento]:
    eventos: list[Evento] = []
    for bloque in (mensaje.get("message") or {}).get("content") or ():
        clase = bloque.get("type")
        if clase == "text" and bloque.get("text", "").strip():
            eventos.append(Texto(texto=bloque["text"]))
        elif clase == "thinking" and bloque.get("thinking", "").strip():
            eventos.append(Pensamiento(texto=bloque["thinking"]))
        elif clase == "tool_use":
            eventos.append(UsoHerramienta(
                id_uso=str(bloque.get("id", "")),
                herramienta=str(bloque.get("name", "")),
                entrada=dict(bloque.get("input") or {}),
            ))
    return eventos


def _usuario(mensaje: dict[str, Any]) -> list[Evento]:
    eventos: list[Evento] = []
    for bloque in (mensaje.get("message") or {}).get("content") or ():
        if bloque.get("type") != "tool_result":
            continue
        eventos.append(ResultadoHerramienta(
            id_uso=str(bloque.get("tool_use_id", "")),
            contenido=_texto_de(bloque.get("content")),
            es_error=bool(bloque.get("is_error")),
            imagenes=_imagenes_de(bloque.get("content")),
        ))
    return eventos


def _texto_de(contenido: Any) -> str:
    """Tool results arrive as a string or as a list of blocks."""
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        return "\n".join(
            b.get("text", "") for b in contenido
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return "" if contenido is None else str(contenido)


def _imagenes_de(contenido: Any) -> tuple[Imagen, ...]:
    """Los bloques `image` de un resultado, que antes se perdian.

    La forma la fija quien las manda, no nosotros: un bloque
    `{"type": "image", "source": {"type": "base64", "media_type": ...,
    "data": ...}}`. Lo que no case con eso se ignora en vez de adivinarse
    -- un `source` de tipo `url` existe en el protocolo y no es lo mismo,
    y tratarlo como base64 pintaria basura.
    """
    if not isinstance(contenido, list):
        return ()
    salida = []
    for bloque in contenido:
        if not isinstance(bloque, dict) or bloque.get("type") != "image":
            continue
        fuente = bloque.get("source")
        if not isinstance(fuente, dict) or fuente.get("type") != "base64":
            continue
        datos = fuente.get("data")
        if not isinstance(datos, str) or not datos:
            continue
        salida.append(Imagen(tipo=str(fuente.get("media_type") or "image/png"),
                             datos=datos))
    return tuple(salida)


def _peticion_de_control(mensaje: dict[str, Any]) -> list[Evento]:
    peticion = mensaje.get("request") or {}
    if peticion.get("subtype") != "can_use_tool":
        return [Desconocido(tipo=f"control_request/{peticion.get('subtype')}",
                            crudo=mensaje)]
    id_peticion = str(mensaje.get("request_id", ""))
    entrada = dict(peticion.get("input") or {})

    if peticion.get("requires_user_interaction"):
        preguntas = entrada.get("questions")
        return [Pregunta(
            id_peticion=id_peticion,
            id_uso=str(peticion.get("tool_use_id", "")),
            preguntas=tuple(preguntas) if isinstance(preguntas, list) else (),
        )]

    return [Puerta(
        id_peticion=id_peticion,
        herramienta=str(peticion.get("tool_name", "")),
        entrada=entrada,
        descripcion=str(peticion.get("description", "")),
        id_uso=str(peticion.get("tool_use_id", "")),
        ruta_afectada=peticion.get("blocked_path"),
    )]


def _fin(mensaje: dict[str, Any]) -> Fin:
    return Fin(
        session_id=str(mensaje.get("session_id", "")),
        subtipo=str(mensaje.get("subtype", "")),
        es_error=bool(mensaje.get("is_error")),
        texto=str(mensaje.get("result") or ""),
        coste_usd=float(mensaje.get("total_cost_usd") or 0.0),
        duracion_ms=int(mensaje.get("duration_ms") or 0),
        num_turnos=int(mensaje.get("num_turns") or 0),
        estado_error_api=mensaje.get("api_error_status"),
        razon_terminal=str(mensaje.get("terminal_reason") or ""),
    )


# --------------------------------------------------------------------
# Que se esta haciendo AHORA. Una sola regla, dos consumidores.
# --------------------------------------------------------------------

# Cuanto cabe en la barra superior de la consola. No es un limite bonito:
# por encima de esto la barra parte la linea y el resto de la cabecera se
# descoloca, que es peor que no poner nada.
LARGO_DE_TAREA = 90


class SeguidorDeTarea:
    """Sigue el flujo y sabe en todo momento que se esta haciendo.

    >>> UN `Texto` NO SE PUEDE JUZGAR AL LLEGAR <<<
    Es NARRACION -- lo que Claude Code va contando mientras trabaja -- si
    detras viene una herramienta, y es LA RESPUESTA si detras viene
    `Fin`. Hay que esperar al evento siguiente para saber cual de las dos.

    >>> Y POR ESO ESTA REGLA VIVE AQUI Y NO EN `voz/` <<<
    La necesitan dos: la voz, para locutar la narracion (2026-08-27), y
    la consola, para la barra de "TAREA". Es una propiedad del FLUJO, no
    de la voz. Escribirla dos veces es exactamente como acabaron
    divergiendo los tres normalizadores de `voz/` -- y aqui el sintoma
    seria peor: la barra diria una cosa y el altavoz otra.
    """

    def __init__(self) -> None:
        self.pendiente: str | None = None
        self.tarea: str = ""
        self.origen: str = ""

    def orden(self, texto: str, origen: str = "") -> None:
        """Una orden del usuario. Es la tarea hasta que Claude diga otra.

        Se guarda LITERAL (solo recortada para que quepa): la barra no
        parafrasea. Lo que el usuario tiene que poder comprobar de un
        vistazo es que se le entendio, y un resumen nuestro taparia justo
        el fallo que viene a enseñar.
        """
        self.tarea = _recorta(texto)
        self.origen = origen
        self.pendiente = None

    def ve(self, evento: Evento) -> str | None:
        """Come un evento. Devuelve la NARRACION si este la destapa.

        `None` no significa "no ha pasado nada": significa "este evento no
        era una narracion". Quien quiera saber la tarea mira `.tarea`.
        """
        if isinstance(evento, Texto):
            self.pendiente = evento.texto
            return None
        if isinstance(evento, UsoHerramienta):
            narracion, self.pendiente = self.pendiente, None
            if narracion:
                self.tarea = _recorta(narracion)
                self.origen = "claude"
            return narracion
        if isinstance(evento, Puerta):
            # Una puerta es una pregunta que hay que contestar: lo que se
            # estuviera contando al lado deja de ser lo que pasa.
            self.pendiente = None
            return None
        if isinstance(evento, Fin):
            # Era la respuesta, no narracion. Y el turno acabo, asi que ya
            # no se esta haciendo nada: la barra tiene que quedarse vacia
            # en vez de congelar la ultima tarea para siempre.
            self.pendiente = None
            self.tarea = ""
            self.origen = ""
            return None
        return None


def _recorta(texto: str) -> str:
    """Una linea, sin saltos, y que quepa. Se corta por PALABRA entera."""
    plano = " ".join((texto or "").split())
    if len(plano) <= LARGO_DE_TAREA:
        return plano
    corte = plano[:LARGO_DE_TAREA].rsplit(" ", 1)[0]
    return (corte or plano[:LARGO_DE_TAREA]) + "..."
