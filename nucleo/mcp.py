"""La lista blanca de servidores MCP (JC-0015).

>>> POR QUE HACE FALTA, Y ESTA MEDIDO <<<
Con Claude Code de cerebro, su ecosistema de MCP queda al alcance y da
mucha potencia. Pero el 2026-08-26 se midio que pasaria hoy, contra la
politica y el suelo REALES:

    herramienta                  veredicto  regla
    Write   -> C:\\Windows        denegar    zona_de_sistema
    Bash    -> rm -rf             endurecer  orden_destructiva
    mcp__archivos__escribir       permitir   por_defecto
    mcp__archivos__borrar         permitir   por_defecto
    mcp__shell__ejecutar          permitir   por_defecto

**Una herramienta de MCP atravesaba la puerta entera sin tocarla.**
`puente/politica.py` endurece por NOMBRE (`Write`, `Edit`, `Bash`) y por
la ruta que Claude Code nombra en `blocked_path`; un `mcp__x__y` no casa
con ninguna de las dos y caia en el PERMITIR por defecto. Y el suelo de
JC-0007 tampoco lo tapaba: sus reglas son `Read(...)`, `Write(...)`,
`Edit(...)`, y no hay patron que case un nombre de herramienta que no
existia cuando se escribieron. **Las dos capas caian a la vez**, que es
justo lo que las hacia dos.

>>> LA DECISION DEL USUARIO (2026-08-26): LISTA BLANCA <<<
Una lista blanca abierta y configurable por el usuario. O sea:

    declarado con `auto`        pasa solo
    declarado con `confirmar`   te pregunta          <- el defecto al añadir
    declarado con `prohibido`   no pasa
    NO DECLARADO                no pasa, y se dice cual es

Y NO DECLARADO ES **DENEGAR**, NO PREGUNTAR. Si preguntara, esto no seria
una lista blanca: seria un aviso. La diferencia importa porque un
servidor MCP no es una herramienta mas -- es un proveedor de herramientas
ARBITRARIAS con la autoridad de la sesion, y ADR-0018 ya lo decia de su
token: quien lo tenga se salta al executor entero.

Lo que hace que denegar sea usable en vez de frustrante es que el motivo
NOMBRA al servidor, asi que enterarse y añadirlo es un paso, no una
investigacion.

>>> LO QUE ESTO **NO** GOBIERNA <<<
Las **skills** y los **plugins**. No son lo mismo y no tienen este
agujero: una skill son INSTRUCCIONES, no autoridad. Las herramientas que
acabe usando siguen siendo `Write`, `Bash`... y pasan por la puerta como
siempre. Meterlas aqui seria pedir permiso para leer un documento.

UN ARCHIVO AUSENTE SIGNIFICA "NINGUNO", NUNCA "TODOS". Es la misma regla
que `zonas.yaml`: leer una config que no esta como consentimiento es como
acaba habilitado lo que nadie habilito.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from nucleo.configuracion import CONFIG_DIR

ARCHIVO = "mcp.yaml"

# El prefijo con el que Claude Code nombra las herramientas de un
# servidor MCP: `mcp__<servidor>__<herramienta>`.
PREFIJO = "mcp__"


class Politica(str, Enum):
    """Que se hace con las herramientas de un servidor declarado."""

    AUTO = "auto"
    CONFIRMAR = "confirmar"
    PROHIBIDO = "prohibido"


# El defecto al AÑADIR uno nuevo. Heredado del `permisos.yaml` del
# original (`politica_por_defecto: confirmar`) y por la misma razon:
# declarar un servidor es decir "lo conozco", no "hace lo que quiera".
POLITICA_AL_ANADIR = Politica.CONFIRMAR


class McpError(RuntimeError):
    """La lista blanca esta malformada."""


@dataclass(frozen=True)
class Lanzamiento:
    """COMO se arranca un servidor. Opcional, y esa es la mitad del asunto.

    >>> DECLARAR Y LANZAR SON DOS COSAS, Y HASTA HOY SOLO HABIA UNA <<<
    JC-0015 construyo la lista blanca el 2026-08-26 y quedo gobernando una
    puerta que no llevaba a ningun sitio: `Servidor` sabia el NOMBRE y la
    POLITICA, y no habia donde decir como se arranca. Comprobado el
    2026-09-01: cero servidores en `~/.claude.json` (36 proyectos), ningun
    `.mcp.json` en el arbol y ningun `config/mcp.yaml`. O sea que la lista
    era exacta y estaba vacia, y no habia forma de llenarla.

    Sin `lanzar`, una entrada sigue siendo valida y significa lo que
    significaba: PERMISO para un servidor que venga de fuera -- de la
    configuracion global del usuario o de un `.mcp.json` del proyecto.
    Por eso esto es opcional y no un campo obligatorio nuevo.

    >>> LOS SECRETOS NO VIVEN AQUI <<< `config/mcp.yaml` NO esta en el
    `.gitignore` -- al contrario que `config/telegram.yaml` --, porque la
    lista blanca es justo lo que interesa versionar. Asi que un valor de
    `entorno` o de `cabeceras` que sea `${NOMBRE}` se resuelve contra el
    entorno del proceso al generar la configuracion, y el token no llega
    nunca al YAML. Una variable que no exista se deja tal cual en vez de
    quedar en blanco: un `Authorization: Bearer ` vacio da un 401 raro,
    y `${TOKEN_DE_SENTRY}` sin resolver dice lo que falta.
    """

    orden: tuple[str, ...] = ()
    """Para un servidor de stdio: el programa y sus argumentos."""
    entorno: dict[str, str] = field(default_factory=dict)
    url: str = ""
    """Para un servidor http/sse. Excluyente con `orden`."""
    cabeceras: dict[str, str] = field(default_factory=dict)

    @property
    def es_stdio(self) -> bool:
        return bool(self.orden)

    def a_claude(self) -> dict[str, Any]:
        """La entrada tal y como la espera `--mcp-config`."""
        if self.es_stdio:
            cuerpo: dict[str, Any] = {"command": self.orden[0]}
            if len(self.orden) > 1:
                cuerpo["args"] = list(self.orden[1:])
            if self.entorno:
                cuerpo["env"] = {k: _del_entorno(v)
                                 for k, v in self.entorno.items()}
            return cuerpo
        cuerpo = {"type": "http", "url": self.url}
        if self.cabeceras:
            cuerpo["headers"] = {k: _del_entorno(v)
                                 for k, v in self.cabeceras.items()}
        return cuerpo


def _del_entorno(valor: str) -> str:
    """`${NOMBRE}` -> lo que valga en el entorno. Lo demas, tal cual.

    Si la variable no existe se devuelve el `${NOMBRE}` intacto, a
    proposito: ver el aviso de secretos en `Lanzamiento`.
    """
    texto = str(valor)
    if texto.startswith("${") and texto.endswith("}"):
        return os.environ.get(texto[2:-1], texto)
    return texto


@dataclass(frozen=True)
class Servidor:
    nombre: str
    politica: Politica
    nota: str = ""
    lanzamiento: Lanzamiento | None = None
    """`None` = Jarvis no lo arranca; si aparece, viene de fuera."""

    def a_json(self) -> dict[str, Any]:
        return {"nombre": self.nombre, "politica": self.politica.value,
                "nota": self.nota, "lo_lanza_jarvis": self.lanzamiento is not None}


def ruta(config_dir: Path | None = None) -> Path:
    return (config_dir or CONFIG_DIR) / ARCHIVO


def es_de_mcp(herramienta: str) -> bool:
    return herramienta.startswith(PREFIJO)


def servidor_de(herramienta: str) -> str:
    """`mcp__archivos__escribir` -> `archivos`.

    Se corta por el SERVIDOR y no por la herramienta a proposito: quien
    tiene autoridad es el servidor -- decide que herramientas expone y
    puede cambiarlas sin avisar --, asi que autorizar herramienta a
    herramienta daria una sensacion de control que no existe.
    """
    resto = herramienta[len(PREFIJO):]
    return resto.split("__", 1)[0] if resto else ""


def leer(config_dir: Path | None = None) -> tuple[Servidor, ...]:
    """Los servidores declarados. Vacio si no hay archivo.

    UN YAML MALFORMADO LEVANTA en vez de ignorarse: arrancar con una
    lista blanca distinta de la que el usuario escribio, y callarselo, es
    peor que no arrancar. Misma regla que `zonas.yaml`.
    """
    destino = ruta(config_dir)
    if not destino.is_file():
        return ()
    try:
        with destino.open("r", encoding="utf-8") as f:
            datos = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise McpError(f"YAML invalido en {destino}: {exc}") from exc
    if not datos:
        return ()
    crudos = datos.get("servidores") if isinstance(datos, dict) else datos
    if not isinstance(crudos, list):
        raise McpError(f"{destino} deberia tener una lista `servidores`.")

    salida = []
    for fila in crudos:
        if isinstance(fila, str):
            salida.append(Servidor(fila.strip(), POLITICA_AL_ANADIR))
            continue
        if not isinstance(fila, dict) or not fila.get("nombre"):
            raise McpError(f"Entrada sin `nombre` en {destino}: {fila!r}")
        bruto = str(fila.get("politica") or POLITICA_AL_ANADIR.value)
        try:
            politica = Politica(bruto)
        except ValueError as exc:
            raise McpError(
                f"'{bruto}' no es una politica valida en {destino}. "
                f"Hay: {', '.join(p.value for p in Politica)}") from exc
        salida.append(Servidor(str(fila["nombre"]).strip(), politica,
                               str(fila.get("nota") or ""),
                               _lanzamiento_de(fila.get("lanzar"), destino,
                                               fila["nombre"])))
    return tuple(salida)


def _lanzamiento_de(crudo: Any, destino: Path, nombre: Any) -> Lanzamiento | None:
    """Lee el bloque `lanzar`. Ausente es `None`, y `None` es valido.

    UN `lanzar` A MEDIAS LEVANTA en vez de ignorarse, por la misma razon
    que un YAML malformado: un servidor que el usuario creia declarado
    para arrancar y que no arranca es un fallo mudo -- la sesion sube, la
    herramienta no aparece, y no hay nada que mirar.
    """
    if crudo is None:
        return None
    if not isinstance(crudo, dict):
        raise McpError(f"`lanzar` de '{nombre}' en {destino} deberia ser un "
                       f"bloque con `orden` o con `url`.")
    orden = crudo.get("orden") or ()
    url = str(crudo.get("url") or "").strip()
    if isinstance(orden, str):
        raise McpError(f"`orden` de '{nombre}' en {destino} es una lista, no "
                       f"una cadena: cortarla por espacios adivinaria donde "
                       f"acaba una ruta con espacios, que en Windows es lo "
                       f"normal.")
    orden = tuple(str(x) for x in orden)
    if bool(orden) == bool(url):
        raise McpError(f"`lanzar` de '{nombre}' en {destino} necesita `orden` "
                       f"(stdio) O `url` (http), y exactamente una de las dos.")
    return Lanzamiento(
        orden=orden, url=url,
        entorno={str(k): str(v) for k, v in (crudo.get("entorno") or {}).items()},
        cabeceras={str(k): str(v)
                   for k, v in (crudo.get("cabeceras") or {}).items()},
    )


def guardar(servidores: tuple[Servidor, ...] | list[Servidor],
            config_dir: Path | None = None) -> None:
    """Reescribe la lista ENTERA, no fusiona.

    Fusionar haria imposible quitar un servidor -- se volveria a colar en
    el siguiente guardado -- y nadie lo notaria. El archivo ES la
    eleccion, igual que en `zonas.yaml`.
    """
    destino = ruta(config_dir)
    destino.parent.mkdir(parents=True, exist_ok=True)
    cabecera = (
        "# Servidores MCP que Jarvis deja actuar (JC-0015).\n"
        "#\n"
        "# LISTA BLANCA: lo que no este aqui NO PASA. Un servidor MCP no es\n"
        "# una herramienta mas, es un proveedor de herramientas arbitrarias\n"
        "# con la autoridad de la sesion, y ni la lista endurecida de\n"
        "# JC-0001 ni el suelo de JC-0007 saben nada de sus nombres.\n"
        "#\n"
        "#   auto       sus herramientas pasan solas\n"
        "#   confirmar  te pregunta cada vez  (el defecto al anadir uno)\n"
        "#   prohibido  no pasan\n"
        "#\n"
        "# Borrar este archivo significa NINGUNO, nunca todos.\n"
        "#\n"
        "# `lanzar` es OPCIONAL y son dos cosas distintas:\n"
        "#   con `lanzar`  Jarvis arranca el servidor el mismo.\n"
        "#   sin `lanzar`  solo se le da PERMISO, para uno que venga de\n"
        "#                 tu configuracion de Claude Code o del proyecto.\n"
        "#\n"
        "# LOS TOKENS NO VAN AQUI: este archivo SI se versiona (al reves\n"
        "# que config/telegram.yaml). Un valor ${NOMBRE} en `entorno` o en\n"
        "# `cabeceras` se resuelve contra el entorno del proceso.\n"
        "#\n"
        "#   - nombre: archivos\n"
        "#     politica: confirmar\n"
        "#     lanzar:\n"
        "#       orden: [npx, -y, '@modelcontextprotocol/server-filesystem',\n"
        "#               'C:/proyectos']\n"
    )
    filas = []
    for s in servidores:
        fila: dict[str, Any] = {"nombre": s.nombre, "politica": s.politica.value}
        if s.nota:
            fila["nota"] = s.nota
        if s.lanzamiento is not None:
            bloque: dict[str, Any] = {}
            if s.lanzamiento.es_stdio:
                bloque["orden"] = list(s.lanzamiento.orden)
            else:
                bloque["url"] = s.lanzamiento.url
            if s.lanzamiento.entorno:
                bloque["entorno"] = dict(s.lanzamiento.entorno)
            if s.lanzamiento.cabeceras:
                bloque["cabeceras"] = dict(s.lanzamiento.cabeceras)
            fila["lanzar"] = bloque
        filas.append(fila)
    with destino.open("w", encoding="utf-8") as f:
        f.write(cabecera)
        yaml.safe_dump({"servidores": filas}, f, allow_unicode=True,
                       sort_keys=False)


def politica_de(herramienta: str,
                servidores: tuple[Servidor, ...]) -> Politica | None:
    """Que politica rige esa herramienta. `None` = no esta declarado.

    None NO es "permitir" y no se puede leer asi: es la tercera respuesta, y
    quien llama tiene que decidir explicitamente que hace
    con ella. Aqui la decide `puente/politica.py`: denegar.
    """
    quien = servidor_de(herramienta)
    for s in servidores:
        if s.nombre == quien:
            return s.politica
    return None


def configuracion_para_claude(
        servidores: tuple[Servidor, ...]) -> dict[str, Any]:
    """Los servidores que Jarvis ARRANCA, en el formato de `--mcp-config`.

    >>> UN `prohibido` NO SE LANZA, Y NO ES UN ATAJO <<<
    Arrancarlo para denegarle despues cada llamada seria ejecutar el
    programa igual: un servidor MCP es un PROCESO, no una regla, y
    "prohibido" tiene que significar que no corre. Lo contrario deja un
    subproceso vivo, con la autoridad de la sesion, cuya unica diferencia
    con uno permitido es que nadie le contesta -- y esto arranca con
    Windows y corre todo el dia sin que nadie lo mire.

    Los que no traen `lanzamiento` tampoco salen: esos son permiso para
    un servidor que viene de fuera, y meterlos aqui seria inventarles una
    linea de ordenes.
    """
    cuerpo = {s.nombre: s.lanzamiento.a_claude()
              for s in servidores
              if s.lanzamiento is not None and s.politica is not Politica.PROHIBIDO}
    return {"mcpServers": cuerpo}


# ======================================================================
#  DESCUBRIR LO QUE YA TIENE TU CLAUDE CODE
# ======================================================================
# >>> LO PIDIO EL USUARIO (2026-09-03) <<<
# Pidio que Jarvis detectara directamente los MCP que el Claude Code
# nativo de la maquina ya tiene conectados o definidos, en vez de lo que
# habia hasta entonces.
#
# >>> Y SE ELIGIO DESCUBRIR, NO CONFIAR <<<
# Son dos cosas distintas y solo una es segura. Jarvis YA CARGA los
# servidores del Claude Code nativo -- `--strict-mcp-config` esta apagado
# y el binario dice literalmente "Only use MCP servers from --mcp-config,
# ignoring all other MCP configurations", o sea que sin el la config de
# Jarvis es ADITIVA. Lo que los para no es que no se carguen: es la lista
# blanca de JC-0015, que deniega lo no declarado.
#
# Lo que faltaba era ENTERARSE sin que un servidor tuviera que intentar
# actuar primero y comerse una negativa. Eso es esto. Lo que NO se hace
# es autorizarlos solos, y hay tres motivos, los tres comprobados:
#
#   1. Un `mcp__*` atraviesa la puerta entera sin tocarla, y el suelo de
#      JC-0007 tampoco lo caza -- sus reglas son `Read(...)`/`Write(...)`
#      y no hay patron que case un nombre que no existia al escribirlas.
#   2. Un `.mcp.json` es un archivo DENTRO de la carpeta de un proyecto.
#      Confiar en el significa que clonar un repo concede ejecucion de
#      herramientas arbitrarias con la autoridad entera de la sesion.
#   3. **El propio Claude Code nativo tampoco confia en ellos**, y se
#      miro: `enabledMcpjsonServers` y `disabledMcpjsonServers` estan los
#      dos ausentes en `~/.claude.json`, o sea que el usuario no ha
#      aprobado ni uno. Auto-confiar aqui les daria MAS permiso del que
#      tienen en el sitio donde se declararon.
#
# >>> DONDE SE MIRA, Y POR QUE AHI Y NO EN TODO EL DISCO <<<
# En los mismos sitios donde mira el propio Claude Code:
#
#   ~/.claude.json  ->  mcpServers                    (todo el equipo)
#   ~/.claude.json  ->  projects[<ruta>].mcpServers   (esa carpeta)
#   <ruta>/.mcp.json                                  (ese proyecto)
#
# Y las rutas salen de los proyectos que ESE archivo ya conoce, mas la
# carpeta de la sesion. No es un barrido del disco: son carpetas donde
# el usuario ya ha abierto Claude Code, que es una lista mucho mas
# corta y que ademas el ha elegido.

ARCHIVO_DE_CLAUDE = ".claude.json"
ARCHIVO_DE_PROYECTO = ".mcp.json"


@dataclass(frozen=True)
class Encontrado:
    """Un servidor ya declarado en tu Claude Code, y aun sin autorizar."""

    nombre: str
    origen: str
    """El archivo donde se declaro. Se enseña: sin el, autorizar es a ciegas."""
    alcance: str
    """`equipo` (global) | `carpeta` (por proyecto) | `proyecto` (.mcp.json)."""
    lanzamiento: "Lanzamiento | None" = None
    claves_de_entorno: tuple = ()
    """SOLO los nombres. Los valores no salen de aqui: pueden ser tokens."""

    @property
    def resumen(self) -> str:
        """Una linea para el panel. Nunca un valor de entorno."""
        if self.lanzamiento is None:
            return "(sin forma de arrancarlo)"
        if self.lanzamiento.es_stdio:
            return " ".join(self.lanzamiento.orden)[:120]
        return self.lanzamiento.url[:120]

    def a_json(self) -> dict:
        return {"nombre": self.nombre, "origen": self.origen,
                "alcance": self.alcance, "resumen": self.resumen,
                "claves_de_entorno": list(self.claves_de_entorno)}


def _lanzamiento_de_claude(crudo: Any) -> tuple:
    """Traduce una entrada de `mcpServers` al `Lanzamiento` de aqui.

    >>> LOS VALORES DE ENTORNO NO SE COPIAN, Y NO ES UN OLVIDO <<<
    `config/mcp.yaml` SI se versiona -- al reves que `config/telegram.yaml`
    --, asi que copiar un `env` literal de un `.mcp.json` ajeno meteria un
    token en un archivo que va a git. Se traen los NOMBRES como
    `${NOMBRE}`, que es lo que `_del_entorno` ya sabe resolver contra el
    entorno del proceso, y el valor se queda donde estaba.

    NO se intenta adivinar cual "parece" un secreto: un detector que
    acierta el 90 % de las veces filtra el otro 10 % sin decir nada, y
    este proyecto ya sabe lo que cuestan las reglas que adivinan -- van
    cuatro veces con las ordenes de la puerta.
    """
    if not isinstance(crudo, dict):
        return None, ()
    claves = tuple(str(k) for k in (crudo.get("env") or {}))
    url = str(crudo.get("url") or "").strip()
    if url:
        cabeceras = {str(k): "${" + str(k) + "}"
                     for k in (crudo.get("headers") or {})}
        return Lanzamiento(url=url, cabeceras=cabeceras), claves
    orden = str(crudo.get("command") or "").strip()
    if not orden:
        return None, claves
    args = [str(a) for a in (crudo.get("args") or [])]
    entorno = {c: "${" + c + "}" for c in claves}
    return Lanzamiento(orden=(orden, *args), entorno=entorno), claves


def _lee_json(destino: Path) -> dict:
    """Un archivo ilegible NO revienta el descubrimiento: se salta.

    Esto corre al pintar un panel, y `~/.claude.json` es de otro programa
    -- puede estar a medio escribir justo cuando se mira. Dejar la
    pantalla sin abrir por eso seria peor que enseñar un servidor de
    menos, que ademas se sigue viendo por `mcp_vistos` en cuanto actue.
    """
    try:
        with destino.open("r", encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return datos if isinstance(datos, dict) else {}


def descubrir(carpetas_extra: tuple = (),
              casa: Path | None = None) -> tuple:
    """Los servidores MCP que tu Claude Code ya tiene declarados.

    NO los autoriza: solo dice que estan y de donde salen. Autorizar es
    un clic del usuario, y escribe en `config/mcp.yaml` con la politica
    de siempre al añadir (`confirmar`).

    Se devuelven TAMBIEN los que ya estan en la lista blanca: el panel
    los necesita para poder decir "este ya lo tienes, pero con otra linea
    de ordenes": el mismo servidor declarado dos veces, una con un
    ejecutable suelto y otra con un lanzador de paquetes, que es como
    pasa. Dos definiciones de la misma cosa acaban divergiendo, y esa
    es la leccion de los tres normalizadores de `voz/`.
    """
    raiz = casa or Path.home()
    encontrados = []
    vistos = set()

    def apunta(nombre: Any, crudo: Any, origen: Path, alcance: str) -> None:
        nombre = str(nombre or "").strip()
        if not nombre:
            return
        clave = (nombre, str(origen))
        if clave in vistos:
            return
        vistos.add(clave)
        lanzamiento, claves = _lanzamiento_de_claude(crudo)
        encontrados.append(Encontrado(
            nombre=nombre, origen=str(origen), alcance=alcance,
            lanzamiento=lanzamiento, claves_de_entorno=claves))

    de_claude = raiz / ARCHIVO_DE_CLAUDE
    datos = _lee_json(de_claude) if de_claude.is_file() else {}

    for nombre, crudo in (datos.get("mcpServers") or {}).items():
        apunta(nombre, crudo, de_claude, "equipo")

    proyectos = datos.get("projects") or {}
    carpetas = [str(c) for c in proyectos] + [str(c) for c in carpetas_extra]
    for carpeta in carpetas:
        for nombre, crudo in ((proyectos.get(carpeta) or {})
                              .get("mcpServers") or {}).items():
            apunta(nombre, crudo, de_claude, "carpeta")
        try:
            propio = Path(carpeta) / ARCHIVO_DE_PROYECTO
            if not propio.is_file():
                continue
        except OSError:
            continue
        for nombre, crudo in (_lee_json(propio).get("mcpServers") or {}).items():
            apunta(nombre, crudo, propio, "proyecto")

    return tuple(sorted(encontrados, key=lambda e: (e.nombre.lower(), e.origen)))
