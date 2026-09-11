"""Telegram: el tercer canal (JC-0006). SOLO PARA AVISAR.

>>> TELEGRAM AVISA. NO AUTORIZA. Y NO ES UNA LIMITACION TECNICA <<<
La regla de este proyecto -- todo lo externo es no confiable -- lo
dejo decidido antes de que existiera este archivo:

    "un mensaje de Telegram entrante es contenido observado, jamas una
     instruccion"

O sea que este modulo **solo manda**. No lee mensajes, no tiene bucle de
recepcion y no hay forma de contestar una puerta desde el movil. Si la
hubiera, quien controlase ese chat controlaria esta PC con la autoridad
entera del usuario (JC-0007), y eso no se compra con la comodidad de
contestar "si" desde el sofa.

Lo que Telegram hace es lo que hace falta: **que te enteres**. Una puerta
sin contestar deja la sesion esperando indefinidamente (medido), y si no
estas delante ni oyes la voz, hoy no te entera nadie. Con esto si, y
entonces vas a la consola o vuelves y lo dices en voz alta.

>>> ES OPCIONAL Y NACE APAGADO <<<
Sin configurar, `disponible` es False y `mandar` devuelve False sin
intentar nada. Un canal que no esta puesto no es un fallo: es un canal
que no esta puesto, y el resto del sistema funciona igual.

>>> DONDE VIVE EL TOKEN, Y POR QUE NO EN `config/jarvis.yaml` <<<
En `config/telegram.yaml`, que esta en el `.gitignore`. Un token de bot
es una credencial: quien la tenga puede escribir en tu chat. Desde el
2026-08-25 este arbol esta en git, asi que meterlo en un archivo
versionado seria meterlo en el historial -- de donde no se borra
facilmente ni aunque se quite despues.

>>> UN ANTIVIRUS QUE INTERCEPTA TLS MUERDE AQUI TAMBIEN <<<
Trampa 13 del registro: con TLS interceptado, cualquier descarga falla
con CERTIFICATE_VERIFY_FAILED. Se resuelve apuntando al
bundle de `.certs/`, NUNCA desactivando la verificacion: este es un
proyecto cuya premisa es la seguridad, y `verify=False` en el canal que
lleva tus avisos es exactamente la clase de atajo que no se toma.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARCHIVO = PROJECT_ROOT / "config" / "telegram.yaml"
BUNDLE = PROJECT_ROOT / ".certs" / "bundle.pem"

# Telegram corta los mensajes en 4096 caracteres. Se recorta ANTES de
# mandar para que el recorte lo decidamos nosotros y no el servidor.
LARGO_MAXIMO = 3900

# Un aviso que tarda mas que esto no es un aviso. Y no puede quedarse
# colgado: esto corre en el hilo que vigila las puertas.
ESPERA_S = 10.0


class Estado(Enum):
    """Tres salidas, no dos."""

    LISTO = "listo"
    SIN_CONFIGURAR = "sin_configurar"
    """No hay token o esta apagado. NO es un error: es que no se puso."""

    ROTO = "roto"
    """Configurado y NO funciona. Esto si hay que decirlo: un canal de
    avisos que falla en silencio es peor que no tenerlo, porque se cuenta
    con el."""


@dataclass(frozen=True)
class Ajustes:
    """Lo que hace falta para mandar, y si se quiere mandar."""

    activo: bool = False
    token: str = ""
    chat_id: str = ""
    responde: bool = False
    """JC-0016: si ademas de avisar acepta RESPUESTAS a preguntas.

    >>> NACE APAGADO, Y ES OTRA DECISION, NO UN DETALLE DE ESTA <<<
    `activo` convierte esto en un canal de SALIDA. `responde` lo
    convierte en un canal de ENTRADA a un agente que actua sobre esta PC,
    y eso es una decision distinta con un riesgo distinto: quien tenga el
    token puede escribir en el chat. Por eso son dos interruptores y no
    uno, y por eso lo que se acepta esta acotado -- ver
    `canales/respuestas.py`.
    """

    @property
    def completo(self) -> bool:
        return bool(self.activo and self.token and self.chat_id)

    def sin_secretos(self) -> dict:
        """Para la UI y para el log: NUNCA el token.

        Se enseña si HAY token y sus ultimos cuatro caracteres, que es lo
        justo para que el usuario reconozca cual puso sin que el valor
        acabe en una captura de pantalla o en un registro.
        """
        return {
            "activo": self.activo,
            "responde": self.responde,
            "hay_token": bool(self.token),
            "token_acaba_en": self.token[-4:] if self.token else "",
            "chat_id": self.chat_id,
        }


def leer(archivo: Path | None = None) -> Ajustes:
    """Los ajustes de disco. Sin archivo, todo apagado.

    Se lee tambien de las variables de entorno `JARVIS_TELEGRAM_TOKEN` y
    `JARVIS_TELEGRAM_CHAT`, que ganan al archivo: es lo que deja probar
    esto sin dejar la credencial escrita en ningun sitio.
    """
    ruta = archivo or ARCHIVO
    datos: dict = {}
    if ruta.is_file():
        # >>> EL `except` ES ESTRECHO A PROPOSITO <<<
        # La primera version atrapaba `Exception` "por si el yaml esta
        # roto", y lo que atrapo fue una llamada mal escrita mia: se
        # tragaba el `TypeError` y devolvia "no hay nada configurado".
        # O sea que un error de programacion se disfrazaba de ajuste
        # ausente, que es exactamente el fallo silencioso que este
        # proyecto persigue. Un YAML roto SI se traga -- no puede impedir
        # arrancar --, un fallo mio no.
        from nucleo.configuracion import ConfigError, load_yaml
        try:
            datos = load_yaml(ruta) or {}
        except ConfigError:
            datos = {}

    token = os.environ.get("JARVIS_TELEGRAM_TOKEN") or str(
        datos.get("token") or "")
    chat = os.environ.get("JARVIS_TELEGRAM_CHAT") or str(
        datos.get("chat_id") or "")
    return Ajustes(activo=bool(datos.get("activo", False)),
                   token=token.strip(), chat_id=chat.strip(),
                   # AUSENTE = APAGADO. Un `telegram.yaml` escrito antes
                   # de que JC-0016 existiera no puede estrenar un canal
                   # de ENTRADA por haberse actualizado el programa.
                   responde=bool(datos.get("responde", False)))


def guardar(ajustes: Ajustes, archivo: Path | None = None) -> Path:
    """Escribe los ajustes. El archivo esta en `.gitignore`."""
    ruta = archivo or ARCHIVO
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        "# Credenciales de Telegram. ESTE ARCHIVO NO VA A GIT.\n"
        "# Lo escribe la consola; se puede editar a mano.\n"
        f"activo: {'true' if ajustes.activo else 'false'}\n"
        "# responde: acepta RESPUESTAS a preguntas desde el movil (JC-0016).\n"
        "# NUNCA permisos: un borrado se autoriza delante del ordenador.\n"
        f"responde: {'true' if ajustes.responde else 'false'}\n"
        f"token: \"{ajustes.token}\"\n"
        f"chat_id: \"{ajustes.chat_id}\"\n",
        encoding="utf-8")
    return ruta


def _contexto_ssl() -> ssl.SSLContext:
    """El contexto TLS, con el bundle de `.certs/` si esta.

    NUNCA se devuelve un contexto sin verificar. Si el bundle no esta, se
    usa el del sistema y que falle: un fallo ruidoso se arregla, y una
    verificacion desactivada se queda para siempre.
    """
    if BUNDLE.is_file():
        return ssl.create_default_context(cafile=str(BUNDLE))
    return ssl.create_default_context()


@dataclass
class Telegram:
    """El canal. Sin ajustes completos, no hace nada y lo dice."""

    ajustes: Ajustes = None  # type: ignore[assignment]
    enviados: int = 0
    fallos: int = 0
    ultimo_error: str = ""

    def __post_init__(self) -> None:
        if self.ajustes is None:
            self.ajustes = leer()

    @property
    def disponible(self) -> bool:
        return self.ajustes.completo

    def _llamar(self, metodo: str, campos: dict) -> tuple[bool, str]:
        url = f"https://api.telegram.org/bot{self.ajustes.token}/{metodo}"
        datos = urllib.parse.urlencode(campos).encode("utf-8")
        peticion = urllib.request.Request(url, data=datos)
        try:
            with urllib.request.urlopen(peticion, timeout=ESPERA_S,
                                        context=_contexto_ssl()) as respuesta:
                cuerpo = json.loads(respuesta.read().decode("utf-8"))
            if not cuerpo.get("ok"):
                return False, str(cuerpo.get("description", "respuesta sin ok"))
            return True, ""
        except urllib.error.HTTPError as exc:
            # El cuerpo del error trae la razon de Telegram ("chat not
            # found", "Unauthorized"), que es lo unico accionable.
            try:
                detalle = json.loads(exc.read().decode("utf-8"))
                return False, str(detalle.get("description", exc))
            except Exception:  # noqa: BLE001
                return False, f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001 - red, DNS, TLS
            return False, f"{type(exc).__name__}: {exc}"

    def comprobar(self) -> tuple[Estado, str]:
        """Pregunta a Telegram si esto funciona, sin mandar un aviso.

        Existe para que la UI pueda decir la verdad ANTES de que haga
        falta: un canal de avisos que descubres que no funciona el dia
        que lo necesitas no es un canal de avisos. Usa `getMe`, que no
        escribe nada en el chat.
        """
        if not self.ajustes.activo:
            return Estado.SIN_CONFIGURAR, "esta apagado"
        if not self.ajustes.token or not self.ajustes.chat_id:
            return Estado.SIN_CONFIGURAR, "falta el token o el chat"
        bien, error = self._llamar("getMe", {})
        if not bien:
            self.ultimo_error = error
            return Estado.ROTO, error
        return Estado.LISTO, "responde"

    def probar(self) -> tuple[Estado, str]:
        """Manda un mensaje DE VERDAD al chat configurado.

        >>> `comprobar` NO BASTA, Y ESTA ES LA DIFERENCIA <<<
        `getMe` valida el TOKEN. No mira el `chat_id`, asi que un chat mal
        puesto pasa esa comprobacion y solo falla el dia que hay algo que
        avisar -- justo el fallo que este canal existe para evitar. Lo
        unico que valida el chat es escribirle.

        Por eso esto se ofrece aparte y no se hace en cada guardado: manda
        un mensaje real, y un boton que escribe en tu Telegram tiene que
        pulsarlo alguien a proposito.
        """
        estado, detalle = self.comprobar()
        if estado is not Estado.LISTO:
            return estado, detalle
        if self.mandar("Jarvis: prueba de canal. Si lees esto, el aviso "
                       "llega. (Por aqui solo aviso; autorizar se hace en "
                       "la consola o hablando.)"):
            return Estado.LISTO, "mensaje de prueba enviado"
        return Estado.ROTO, self.ultimo_error or "no se pudo enviar"

    def _consultar(self, metodo: str) -> tuple[bool, dict | str]:
        """GET a la API. Devuelve el `result` crudo o el error.

        Aparte de `_llamar` porque aquel devuelve solo si fue bien: para
        diagnosticar hace falta lo que contesto, no si contesto.
        """
        url = f"https://api.telegram.org/bot{self.ajustes.token}/{metodo}"
        try:
            with urllib.request.urlopen(url, timeout=ESPERA_S,
                                        context=_contexto_ssl()) as respuesta:
                cuerpo = json.loads(respuesta.read().decode("utf-8"))
            if not cuerpo.get("ok"):
                return False, str(cuerpo.get("description", "sin ok"))
            return True, cuerpo.get("result")
        except urllib.error.HTTPError as exc:
            try:
                detalle = json.loads(exc.read().decode("utf-8"))
                return False, str(detalle.get("description", exc))
            except Exception:  # noqa: BLE001
                return False, f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"

    def mandar(self, texto: str) -> bool:
        """Manda un aviso. False si no se pudo o si no esta configurado.

        NO levanta excepciones: esto lo llama el vigilante de puertas, y
        un canal de avisos que revienta se llevaria por delante al que
        vigila -- o sea que un fallo de Telegram apagaria tambien lo que
        funcionaba.
        """
        if not self.disponible or not texto.strip():
            return False
        recortado = texto.strip()[:LARGO_MAXIMO]
        bien, error = self._llamar("sendMessage", {
            "chat_id": self.ajustes.chat_id,
            "text": recortado,
            "disable_web_page_preview": "true",
        })
        if bien:
            self.enviados += 1
        else:
            self.fallos += 1
            self.ultimo_error = error
        return bien


@dataclass(frozen=True)
class Entrante:
    """Un mensaje que llego por Telegram. **Contenido observado.**

    Nunca una instruccion: todo lo externo es no confiable, y aqui con
    mas motivo que en ningun otro sitio del arbol, porque al otro lado hay
    un agente con la autoridad entera del usuario sobre esta PC.
    """

    id_update: int
    chat_id: str
    texto: str


def _es_de_quien_debe(mensaje: dict, chat_id: str) -> bool:
    chat = (mensaje.get("chat") or {}).get("id")
    return chat is not None and str(chat) == str(chat_id)


class TelegramEntrada:
    """La mitad que ESCUCHA. Separada de `Telegram` a proposito.

    `Telegram` manda avisos y no sabe recibir; esto recibe y no sabe
    mandar. Tenerlas juntas haria que encender lo segundo fuese un campo
    mas del mismo objeto, cuando es una decision distinta -- pasar de un
    canal de salida a uno de ENTRADA a un agente que actua sobre la PC.

    >>> ALLOWLIST DE `chat_id`, NO SOLO DEL BOT <<<
    Un bot de Telegram le contesta a cualquiera que le escriba. Sin este
    filtro, cualquier persona que diera con el nombre del bot podria
    contestar por ti. Lo que NO protege es que te roben el token, y por
    eso `canales/respuestas.py` acota ademas QUE se puede contestar.
    """

    def __init__(self, ajustes: "Ajustes") -> None:
        self.ajustes = ajustes
        self.offset: int | None = None
        self.recibidos = 0
        self.descartados_por_origen = 0
        """Mensajes de OTRO chat. Se cuentan y se tiran; que este numero
        crezca es la señal de que alguien mas conoce el bot."""
        self.ultimo_error = ""

    @property
    def disponible(self) -> bool:
        a = self.ajustes
        return bool(a.activo and a.responde and a.token and a.chat_id)

    def recibir(self) -> tuple[Entrante, ...]:
        """Lo nuevo desde la ultima vez. Vacio si no hay o no se pudo.

        NO levanta: esto lo llama el mismo latido que atiende el escalado,
        y un fallo de red no puede llevarse por delante lo que si
        funciona. Misma regla que `Telegram.mandar`.

        SIN LONG-POLL (`timeout=0`): se pregunta desde el latido que ya
        existe cada pocos segundos, y una peticion que se queda colgada 25
        s dentro de ese latido pararia el escalado. La latencia que se
        paga es de segundos y la respuesta a una pregunta no es urgente.
        """
        if not self.disponible:
            return ()
        metodo = "getUpdates?timeout=0&allowed_updates=%5B%22message%22%5D"
        if self.offset is not None:
            metodo += f"&offset={self.offset}"
        bien, cuerpo = Telegram(self.ajustes)._consultar(metodo)
        if not bien or not isinstance(cuerpo, list):
            if not bien:
                self.ultimo_error = str(cuerpo)
            return ()

        salida = []
        for update in cuerpo:
            uid = update.get("update_id")
            if isinstance(uid, int):
                # Se avanza el offset SIEMPRE, incluso con lo descartado:
                # si no, un mensaje ajeno se volveria a leer para siempre
                # y taparia los buenos.
                self.offset = uid + 1
            mensaje = update.get("message") or {}
            texto = str(mensaje.get("text") or "").strip()
            if not texto:
                continue
            if not _es_de_quien_debe(mensaje, self.ajustes.chat_id):
                self.descartados_por_origen += 1
                continue
            self.recibidos += 1
            salida.append(Entrante(id_update=uid or 0,
                                   chat_id=str(self.ajustes.chat_id),
                                   texto=texto))
        return tuple(salida)

    def ponerse_al_dia(self) -> None:
        """Tira lo que hubiera pendiente sin contestarlo.

        Se llama al arrancar. Sin esto, un mensaje escrito mientras Jarvis
        estaba apagado se contestaria al encenderlo -- respondiendo una
        pregunta que ya no existe, o peor, la siguiente que aparezca.
        """
        if not self.disponible:
            return
        self.recibir()


def _diagnostico() -> int:
    """`python -m canales.telegram`: por que `getUpdates` sale vacio.

    >>> EXISTE PORQUE "ok: true, result: []" NO DICE QUE PASA <<<
    Es la pantalla que se encuentra todo el mundo montando esto, y tiene
    al menos tres causas que se arreglan de forma distinta:

      1. **Le escribiste a OTRO bot.** Facil de hacer: en la lista de
         chats, @BotFather y tu bot estan uno al lado del otro. `getMe`
         dice de QUIEN es el token, y con ese @usuario delante se
         comprueba en un segundo.
      2. **Hay un webhook puesto.** Con webhook, Telegram entrega por ahi
         y `getUpdates` devuelve vacio PARA SIEMPRE, sin error. Es la
         causa silenciosa, y `getWebhookInfo` la caza.
      3. **Los updates ya se consumieron.** Cada lectura con `offset`
         confirma los anteriores y Telegram los borra. Si algo los leyo
         (otra pestaña, un script), no vuelven: hay que mandar OTRO
         mensaje.

    NO IMPRIME EL TOKEN. Lee de `config/telegram.yaml` o de
    `JARVIS_TELEGRAM_TOKEN`, y de el solo enseña los cuatro ultimos
    caracteres -- esta salida acaba pegada en un chat, y una credencial
    en un historial no se recupera.
    """
    ajustes = leer()
    if not ajustes.token:
        print("No hay token. Ponlo en config/telegram.yaml:")
        print('    token: "123456789:AA..."')
        print("o en la variable de entorno JARVIS_TELEGRAM_TOKEN.")
        print("\nY NO lo pegues en un chat: esto lo lee de disco a")
        print("proposito, y de el solo enseña los cuatro ultimos.")
        return 2

    canal = Telegram(ajustes)
    print(f"Token ...{ajustes.token[-4:]}  (activo: {ajustes.activo})")
    print(f"chat_id configurado: {ajustes.chat_id or '(ninguno)'}\n")

    # 1. DE QUIEN es el token.
    bien, yo = canal._consultar("getMe")
    if not bien:
        print(f"  getMe FALLA: {yo}")
        print("  -> el token no vale. Copialo otra vez de @BotFather.")
        return 1
    usuario = yo.get("username", "?")
    print(f"  1. El token es del bot @{usuario} ({yo.get('first_name','')})")
    print(f"     >>> COMPRUEBA QUE LE ESCRIBISTE A @{usuario} <<<")
    print("     En la lista de chats, @BotFather y tu bot estan juntos.")

    # 2. Un webhook deja `getUpdates` vacio para siempre, sin error.
    bien, gancho = canal._consultar("getWebhookInfo")
    if bien and isinstance(gancho, dict) and gancho.get("url"):
        print(f"\n  2. !! HAY UN WEBHOOK PUESTO: {gancho['url']}")
        print("     Con webhook, getUpdates devuelve vacio SIEMPRE y sin")
        print("     error. Se quita abriendo en el navegador:")
        print(f"       https://api.telegram.org/bot<TOKEN>/deleteWebhook")
        return 1
    print("  2. No hay webhook (bien: getUpdates puede entregar)")

    # 3. Que hay pendiente.
    bien, updates = canal._consultar("getUpdates")
    if not bien:
        print(f"\n  3. getUpdates FALLA: {updates}")
        return 1
    if not updates:
        print("\n  3. getUpdates viene VACIO.")
        print("     Quedan dos causas, y las dos se arreglan igual:")
        print(f"       a) le escribiste a otro bot -> escribele a @{usuario}")
        print("       b) alguien ya leyo esos updates (otra pestaña, un")
        print("          script) y Telegram los borro -> manda OTRO mensaje")
        print("     Manda un mensaje NUEVO al bot y vuelve a correr esto.")
        return 1

    print(f"\n  3. {len(updates)} update(s). Los chat_id que aparecen:")
    vistos = {}
    for u in updates:
        mensaje = u.get("message") or u.get("edited_message") or {}
        chat = mensaje.get("chat") or {}
        if not chat.get("id"):
            continue
        vistos[chat["id"]] = chat
    for id_chat, chat in vistos.items():
        quien = chat.get("username") or chat.get("first_name") or chat.get("title", "")
        print(f"       chat_id = {id_chat}    ({chat.get('type','')}, {quien})")
    if not vistos:
        print("       (ninguno trae un chat: son updates de otro tipo)")
        return 1

    print("\n  Ese numero es el que va en la consola, o en")
    print("  config/telegram.yaml como chat_id. Despues, guarda con")
    print('  "probar": true para que mande un mensaje de verdad: getMe')
    print("  valida el token, pero el chat solo lo valida escribirle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_diagnostico())
