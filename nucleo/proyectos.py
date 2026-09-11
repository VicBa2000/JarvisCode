"""Que carpeta es "el proyecto nebula" (ADR-0029, decision abierta 1).

>>> POR QUE UN REGISTRO EXPLICITO Y NO BUSCAR EN EL DISCO <<<
Lo dejo escrito el propio ADR-0029 y sigue siendo la razon:

    "abrir la carpeta equivocada aqui significa lanzar un agente con
     auto mode sobre codigo que no era"

Evaluaba tres formas y se quedaba con la tercera: (a) coincidencia
exacta bajo una raiz, (b) coincidencia difusa, (c) **registro explicito
con alias**. La (c) es la unica que no puede equivocarse, y la razon es
que aqui la entrada NO es texto tecleado: es una transcripcion. "nebula"
puede llegar como "ne bula", "nebula" o "ne-bula" segun como se
diga, y una busqueda difusa sobre nombres de carpeta tiene que decidir
sola cual de tres se parece mas. Un registro no decide: o esta o no esta.

LA FRICCION SE QUITA POR OTRO LADO, no aflojando esto: el panel de
ajustes lista las carpetas que hay bajo una raiz configurada y las añade
de un clic. Descubrir es barato; ABRIR sin que nadie lo haya declarado es
lo que no se hace.

>>> TRES RESPUESTAS, NO DOS <<<

    UNO      una sola candidata: se puede abrir
    VARIOS   mas de una, y NO se elige por nosotros. Se pregunta.
    NINGUNO  no esta registrado. Tampoco se busca a ver si suena.

VARIOS es la que importa y es la que el ADR nombra: ante varias
candidatas, se pregunta. Quedarse con la primera seria elegir por el
usuario justo donde equivocarse cuesta mas caro.

UN ARCHIVO AUSENTE SIGNIFICA "NINGUNO REGISTRADO", nunca "todas las
carpetas del disco". Misma regla que `zonas.yaml` y `mcp.yaml`.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePath
from typing import Any

import yaml

from nucleo.configuracion import CONFIG_DIR

ARCHIVO = "proyectos.yaml"

# Palabras que la gente mete al nombrar un proyecto y que no distinguen a
# ninguno: "abre EL PROYECTO nebula". Se quitan de los dos lados, asi
# que registrar un alias con ellas dentro sigue funcionando.
RELLENO = frozenset({"el", "la", "los", "las", "de", "del", "proyecto",
                     "proyectos", "carpeta", "mi", "mis"})


class Cuantas(str, Enum):
    UNO = "uno"
    VARIOS = "varios"
    NINGUNO = "ninguno"


class ProyectosError(RuntimeError):
    """El registro esta malformado o la carpeta no sirve."""


@dataclass(frozen=True)
class Proyecto:
    alias: str
    carpeta: str
    auto: bool = True
    """Si la sesion de ESTE proyecto corre en el auto mode de Claude Code.

    >>> ES EL UNICO INTERRUPTOR DEL ARBOL QUE NACE ENCENDIDO Y PESA <<<
    Y lo pidio el usuario asi, con su argumento (2026-08-29): el auto
    mode es algo que se activa o se desactiva en Claude Code, no algo con
    lo que se nace siempre, y en los proyectos ya registrados tiene que
    venir activado por defecto. Estar en este registro ya es una decision
    deliberada -- ADR-0029 lo hizo explicito precisamente para que abrir
    la carpeta equivocada no pudiera pasar por accidente --, asi que
    heredar el auto mode de esa decision no regala nada que no se hubiera
    dado ya.

    >>> LO QUE SE APAGA CON ESTO, POR NOMBRE Y NO EN ABSTRACTO <<<
    En auto mode el puente se queda SORDO: la puerta no llega (medido el
    2026-08-21, un `rm` ejecutandose sin un solo aviso). Y entonces dejan
    de mirarse, a la vez y en silencio:
      * la lista endurecida de JC-0001 -- borrado, `git push`, `rm -rf`;
      * la lista blanca de MCP de JC-0015;
      * la peticion hablada de JC-0002, porque no hay nada que pedir.
    LO QUE SIGUE EN PIE, y esta medido el 2026-08-27 contra los cinco
    modos: **el suelo de JC-0007 muerde igual**, bypass incluido. Y
    SORDOS NO ES CIEGOS -- los `tool_use` se siguen viendo, asi que la
    consola lo sigue ensenando todo. Esto no te deja a oscuras: te deja
    sin freno.
    """

    ritual: str | None = None
    """La frase que Jarvis manda solo al abrir ESTE proyecto. Tres estados.

    >>> AUSENTE NO ES VACIO, Y ESA ES LA MITAD DEL ASUNTO <<<

        None    no se ha dicho nada de este proyecto -> manda la GLOBAL
        ""      dicho y explicito: abre la carpeta y NO mandes nada
        "texto" esta frase, en vez de la global

    Colapsar las dos primeras es el error por defecto de este arbol y
    aqui ademas se nota poco: un proyecto que hereda y otro que calla se
    ven igual en el YAML si la clave se escribe siempre. Por eso
    `guardar` SOLO escribe la clave cuando hay algo que decir, y el panel
    la pinta con un desplegable de tres y no con una caja vacia.

    >>> Y NO ES UN CAMPO DECORATIVO: ES UN TURNO CON TU AUTORIDAD <<<
    Lo que se ponga aqui se manda a Claude Code sin que tu estes delante,
    y si este proyecto tiene `auto` puesto (JC-0017) no pasa por ninguna
    puerta. Una frase que diga "borra los temporales" se ejecuta. El
    panel lo dice con todas las letras; esto lo repite aqui porque quien
    edite el YAML a mano no ve el panel.
    """

    @property
    def existe(self) -> bool:
        return Path(self.carpeta).is_dir()

    @property
    def modo_permisos(self) -> str:
        """El valor de `--permission-mode` para este proyecto.

        `default` NO esta anunciado en el `--help` de `claude 2.1.248`
        --lo acepta y lo devuelve en `system/init`, pero no lo lista--, y
        aun asi es el que hace que la puerta llegue. Si un dia deja de
        aceptarse, esto es lo que hay que cambiar, y el sintoma seria que
        la puerta no se dispara NUNCA en ningun proyecto.
        """
        return "auto" if self.auto else "default"

    def a_json(self) -> dict[str, Any]:
        # `existe` se calcula al pedirlo y no se guarda: una carpeta
        # borrada o un disco desconectado tienen que verse HOY, no cuando
        # se escribio el archivo.
        return {"alias": self.alias, "carpeta": self.carpeta,
                "existe": self.existe, "auto": self.auto,
                # `None` viaja como null y NO como "": el panel tiene que
                # poder distinguir "hereda" de "no mandes nada", que es
                # justo lo que el dataclass separa arriba.
                "ritual": self.ritual}


@dataclass(frozen=True)
class Resolucion:
    """A que carpeta lleva lo que se dijo. Tres salidas."""

    cuantas: Cuantas
    dicho: str
    candidatos: tuple[Proyecto, ...] = ()

    @property
    def proyecto(self) -> Proyecto | None:
        return self.candidatos[0] if self.cuantas is Cuantas.UNO else None


def normalizar(texto: str) -> str:
    """Para comparar: sin tildes, sin mayusculas y sin relleno.

    Lo de las tildes no es cosmetico: el STT escribe "informática" con
    tilde y un alias escrito a mano puede no llevarla, y entonces el
    proyecto "no existe" por un acento.
    """
    plano = unicodedata.normalize("NFKD", texto.lower())
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    limpio = "".join(c if c.isalnum() or c.isspace() else " " for c in plano)
    palabras = [p for p in limpio.split() if p and p not in RELLENO]
    return " ".join(palabras)


def ruta(config_dir: Path | None = None) -> Path:
    return (config_dir or CONFIG_DIR) / ARCHIVO


def leer(config_dir: Path | None = None) -> tuple[Proyecto, ...]:
    """Los proyectos registrados. Vacio si no hay archivo.

    UN YAML MALFORMADO LEVANTA. Arrancar con un registro distinto del que
    el usuario escribio, y callarselo, es como se acaba abriendo un agente
    sobre la carpeta que no era.
    """
    destino = ruta(config_dir)
    if not destino.is_file():
        return ()
    try:
        with destino.open("r", encoding="utf-8") as f:
            datos = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ProyectosError(f"YAML invalido en {destino}: {exc}") from exc
    if not datos:
        return ()
    crudos = datos.get("proyectos") if isinstance(datos, dict) else datos
    if not isinstance(crudos, list):
        raise ProyectosError(f"{destino} deberia tener una lista `proyectos`.")

    salida = []
    for fila in crudos:
        if not isinstance(fila, dict):
            raise ProyectosError(f"Entrada que no es un mapa: {fila!r}")
        alias = str(fila.get("alias") or "").strip()
        carpeta = str(fila.get("carpeta") or "").strip()
        if not alias or not carpeta:
            raise ProyectosError(
                f"Entrada sin alias o sin carpeta en {destino}: {fila!r}")
        # >>> AUSENTE SIGNIFICA ENCENDIDO, Y ES LO CONTRARIO DEL RESTO <<<
        # En `zonas.yaml` y en `mcp.yaml` una clave ausente significa
        # NINGUNA, porque alli lo que se declara es permiso. Aqui lo que
        # se declara es un PROYECTO, y el usuario decidio que estar en la
        # lista ya implica el auto mode (ver `Proyecto.auto`). `guardar`
        # lo escribe siempre, asi que un archivo nuestro nunca depende de
        # este defecto: solo lo hereda uno editado a mano.
        auto = fila.get("auto", True)
        if not isinstance(auto, bool):
            raise ProyectosError(
                f"`auto` tiene que ser true o false en {destino}: {fila!r}")
        # >>> AQUI LA CLAVE AUSENTE SI SIGNIFICA "NO SE HA DICHO" <<<
        # Al reves que `auto`, y a proposito: `auto` declara un permiso y
        # tiene que tener valor siempre, mientras que el ritual tiene una
        # global detras a la que caer. `ritual:` a secas (YAML lo lee
        # como None) cuenta como ausente -- borrar el valor a mano
        # devuelve a la global, que es lo que uno espera al borrarlo.
        # Una cadena VACIA no: esa es la tercera salida y se conserva.
        crudo = fila.get("ritual")
        if crudo is not None and not isinstance(crudo, str):
            raise ProyectosError(
                f"`ritual` tiene que ser texto en {destino}: {fila!r}")
        ritual = None if crudo is None else crudo.strip()
        salida.append(Proyecto(alias, carpeta, auto=auto, ritual=ritual))
    return tuple(salida)


CLAVE_INTERCEPTA = "intercepta_proyectos"
CLAVE_VIEJA = "por_voz"
"""El nombre que tuvo hasta el 2026-09-03. Se sigue LEYENDO, no se escribe.

>>> POR QUE CAMBIO DE NOMBRE <<<
Nacio gobernando solo la voz, porque solo la voz interceptaba. Cuando la
consola empezo a hacerlo tambien, `por_voz` paso a decidir sobre frases
ESCRITAS y el nombre se volvio una mentira -- de las que se descubren
tres semanas mas tarde leyendo el YAML para entender por que una frase
tecleada no llega al cerebro.

No se migra el archivo del usuario a la fuerza: se leen los dos y se
escribe el nuevo la proxima vez que el panel guarde. Un renombrado que
te deja el asistente sin la funcion encendida no es un renombrado, es una
regresion silenciosa.
"""


def intercepta(config_dir: Path | None = None) -> bool:
    """Si "continua con el proyecto X" se mira antes de ir al cerebro.

    >>> NACE APAGADO, Y ES DECISION DEL USUARIO <<<
    Es la unica orden que Jarvis mira antes de mandarla al cerebro, asi
    que encenderla es aceptar que una frase tuya deje de llegar a Claude
    Code. Eso no se da por hecho: se pide. Y apagado, `voz/proyecto.py`
    ni se consulta -- las frases van intactas al cerebro como siempre.

    >>> Y GOBIERNA LOS DOS CANALES DESDE EL 2026-09-03 <<<
    Antes solo la voz. Lo reporto el usuario: la MISMA frase daba
    resultados distintos dicha que escrita -- por voz abria
    `C:\\proyectos\\faro`, por consola dejaba la sesion en la carpeta
    base y Claude Code se ponia a buscar `**/*faro*` dentro. Sin error.
    """
    datos = _cabecera(config_dir)
    if CLAVE_INTERCEPTA in datos:
        return bool(datos[CLAVE_INTERCEPTA])
    return bool(datos.get(CLAVE_VIEJA))


CLAVE_RITUAL_MANDA = "ritual_manda"


def manda_la_global(config_dir: Path | None = None) -> bool:
    """Si la frase de Ajustes PISA la que tenga cada proyecto.

    >>> NACE APAGADO, Y ES LO CONTRARIO DE LO NORMAL AQUI <<<
    El orden natural es que lo mas concreto gane a lo mas general -- es
    lo que hace `modo_para` con las carpetas y lo que hacia el ritual
    desde que existe. Este interruptor lo INVIERTE, y lo pidio el usuario
    y lo pidio el usuario: una frase global opcional que pueda pisar a
    las frases escritas proyecto a proyecto.

    >>> LO QUE CUESTA, Y POR ESO SE VE EN LA LISTA Y NO SOLO AQUI <<<
    Encendido, las frases que hayas escrito proyecto a proyecto SIGUEN
    ESCRITAS y dejan de usarse. Eso es un fallo mudo de manual: mirarias
    la fila de `nebula` diciendo "mira el roadmap" mientras Jarvis
    manda otra cosa. Por eso vive en la SECCION DE PROYECTOS y no en
    Avanzado, y por eso cada fila pisada lo dice en ambar. Un override
    que no se ve en lo que pisa no es un ajuste: es una pantalla que
    miente, que es exactamente lo que ya paso con la barra de la cuota.

    Y ojo con el caso de abajo: encendido y con la frase global VACIA,
    NINGUN proyecto manda ritual. Es coherente -- "manda la global" y la
    global es "callate" -- y hay que poder llegar a el, pero no se puede
    tropezar con el sin verlo.
    """
    return bool(_cabecera(config_dir).get(CLAVE_RITUAL_MANDA))


def _cabecera(config_dir: Path | None = None) -> dict:
    """Las claves sueltas del archivo, sin la lista. `{}` si no se puede.

    Los interruptores de esta cabecera se leen SIN levantar: el motivo de
    un YAML roto ya lo grita `leer()`, que es quien lee de verdad, y aqui
    una excepcion caeria en mitad de una frase dicha. Un archivo que no
    se puede leer significa APAGADO, que en los dos casos es la respuesta
    segura -- no interceptar, y no pisar lo que el usuario escribio.
    """
    destino = ruta(config_dir)
    if not destino.is_file():
        return {}
    try:
        with destino.open("r", encoding="utf-8") as f:
            datos = yaml.safe_load(f)
    except yaml.YAMLError:
        return {}
    return datos if isinstance(datos, dict) else {}


def por_voz(config_dir: Path | None = None) -> bool:
    """El nombre viejo de `intercepta`. Se queda por si alguien lo llama.

    NO se marca como obsoleto con un aviso: el unico sitio del arbol que
    lo usaba ya llama al nuevo, y un `DeprecationWarning` en una funcion
    que nadie llama es ruido en la salida de los tests.
    """
    return intercepta(config_dir)


def modo_para(carpeta: str | Path,
              proyectos: tuple[Proyecto, ...] | None = None,
              global_auto: bool | None = None,
              config_dir: Path | None = None) -> str:
    """En que `--permission-mode` abre Jarvis una sesion sobre esta carpeta.

    >>> UN SOLO SITIO QUE LO DECIDE, Y ES A PROPOSITO (JC-0017) <<<
    Lo necesitan DOS caminos -- el arranque (`puente/__main__.py`) y el
    cambio de proyecto hablando (`voz/bucle.py`, ADR-0029) --, y son
    justo los dos que ya divergieron una vez este mes: la ventana de
    seguimiento no pasaba por `_mandar` y por eso no anunciaba el turno.
    Escrito dos veces, el sintoma seria que un proyecto abre con freno
    al arrancar y sin freno al cambiarse a el hablando, o al reves. Y
    nadie mira la linea de ordenes.

    DOS FUENTES Y EL ORDEN IMPORTA:
      1. el interruptor GLOBAL (`sesion.auto_por_defecto`), que si esta
         puesto vale para todo, tambien para la carpeta base;
      2. el proyecto REGISTRADO al que pertenezca la carpeta.
    Una carpeta que no es ninguno de los dos abre en `default`, o sea con
    la puerta puesta. Ese es el suelo de esta funcion y no se negocia:
    "no se me ha dicho nada de esta carpeta" no puede significar "sin
    frenos".

    La pertenencia se mira con `_dentro_de`, no con igualdad: trabajar en
    `C:/proyectos/X/core` es seguir dentro de X. Un subdirectorio que
    ademas fuera otro proyecto registrado gana el MAS PROFUNDO, que es el
    que el usuario nombro mas de cerca.
    """
    if global_auto is None:
        from nucleo.ajustes import valor_de
        global_auto = bool(valor_de("sesion.auto_por_defecto", False,
                                    config_dir=config_dir))
    if global_auto:
        return "auto"

    if proyectos is None:
        try:
            proyectos = leer(config_dir)
        except ProyectosError:
            # Un registro roto no puede ABRIR permisos. Lo grita `leer()`
            # donde toca; aqui la respuesta segura es la de siempre.
            return "default"

    mejor: Proyecto | None = None
    for proyecto in proyectos:
        if not _dentro_de(carpeta, proyecto.carpeta):
            continue
        if mejor is None or len(str(proyecto.carpeta)) > len(str(mejor.carpeta)):
            mejor = proyecto
    return mejor.modo_permisos if mejor else "default"


def _dentro_de(carpeta: str | Path, raiz: str | Path) -> bool:
    """Si `carpeta` es `raiz` o cuelga de ella. Sin tocar el disco."""
    import os

    try:
        uno = os.path.normcase(os.path.normpath(str(Path(carpeta))))
        dos = os.path.normcase(os.path.normpath(str(Path(raiz))))
        return PurePath(uno).is_relative_to(PurePath(dos))
    except (ValueError, OSError):
        return False


def guardar(proyectos: tuple[Proyecto, ...] | list[Proyecto],
            activo: bool = False,
            config_dir: Path | None = None,
            ritual_manda: bool = False) -> None:
    """Reescribe el registro ENTERO, no fusiona. Ver `nucleo/mcp.py`."""
    destino = ruta(config_dir)
    destino.parent.mkdir(parents=True, exist_ok=True)
    cabecera = (
        "# Los proyectos que Jarvis puede abrir por voz (ADR-0029).\n"
        "#\n"
        "# REGISTRO EXPLICITO, y no una busqueda por el disco: lo que se\n"
        "# dice llega TRANSCRITO, y abrir la carpeta equivocada aqui\n"
        "# significa lanzar un agente sobre codigo que no era.\n"
        "#\n"
        "#\n"
        "#   intercepta_proyectos: false   ni se mira; tus frases van\n"
        "#                                 intactas al cerebro\n"
        "#   intercepta_proyectos: true    \"continua con el proyecto X\"\n"
        "#                                 cambia de carpeta, LA DIGAS O LA\n"
        "#                                 ESCRIBAS EN LA CONSOLA\n"
        "#\n"
        "# Se llamo `por_voz` hasta el 2026-09-03, cuando la consola\n"
        "# empezo a interceptar tambien y ese nombre paso a mentir. El\n"
        "# viejo se sigue leyendo; este es el que se escribe.\n"
        "#\n"
        "#\n"
        "# Y POR PROYECTO, `auto` (JC-0017). AUSENTE SIGNIFICA TRUE:\n"
        "#\n"
        "#   auto: true   la sesion corre en el auto mode de Claude Code.\n"
        "#                No pregunta nada, y con ello dejan de mirarse\n"
        "#                el borrado, `git push`, `rm -rf` y la lista\n"
        "#                blanca de MCP. El puente se queda SORDO: no es\n"
        "#                que apruebe rapido, es que no se entera.\n"
        "#   auto: false  la puerta llega y se endurece la lista corta.\n"
        "#\n"
        "# LO QUE NO CAMBIA CON `auto`, y esta medido contra los cinco\n"
        "# modos: el suelo de JC-0007 muerde igual, y la consola sigue\n"
        "# ensenando cada herramienta. Te deja sin freno, no a oscuras.\n"
        "#\n"
        "#\n"
        "# Y `ritual`, la frase que Jarvis manda solo al abrir ESTE\n"
        "# proyecto. TRES ESTADOS, y la clave AUSENTE no es la vacia:\n"
        "#\n"
        "#   (sin clave)     manda la frase global de Ajustes\n"
        "#   ritual: ''      abre la carpeta y NO manda nada\n"
        "#   ritual: la frase  manda ESA, en vez de la global\n"
        "#\n"
        "# Lo que pongas aqui se manda a Claude Code sin que estes\n"
        "# delante, y con `auto: true` no pasa por ninguna puerta.\n"
        "#\n"
        "#\n"
        "# Y `ritual_manda`, que INVIERTE el orden de arriba. AUSENTE\n"
        "# SIGNIFICA FALSE, o sea que lo mas concreto sigue ganando:\n"
        "#\n"
        "#   ritual_manda: false  gana la frase de cada proyecto, y la\n"
        "#                        de Ajustes es el suelo para el que\n"
        "#                        no tenga la suya\n"
        "#   ritual_manda: true   gana la de Ajustes SIEMPRE. Las de\n"
        "#                        aqui siguen escritas y dejan de\n"
        "#                        usarse -- el panel lo dice en cada\n"
        "#                        fila pisada, porque si no seria\n"
        "#                        leer una cosa y que Jarvis mande\n"
        "#                        otra\n"
        "#\n"
        "# OJO: encendido y con la frase global VACIA, ningun proyecto\n"
        "# manda ritual. Es coherente, pero conviene saberlo.\n"
        "# Borrar este archivo significa NINGUNO, nunca todas.\n"
    )
    filas = []
    for p in proyectos:
        # La clave solo se escribe si hay algo que decir: poner
        # `ritual: null` en cada fila haria que "hereda" y "no
        # mandes nada" se parecieran en el archivo, que es justo la
        # distincion que este campo existe para mantener.
        fila = {"alias": p.alias, "carpeta": p.carpeta,
                "auto": bool(p.auto)}
        if p.ritual is not None:
            fila["ritual"] = p.ritual
        filas.append(fila)
    with destino.open("w", encoding="utf-8") as f:
        f.write(cabecera)
        yaml.safe_dump({CLAVE_INTERCEPTA: bool(activo),
                        CLAVE_RITUAL_MANDA: bool(ritual_manda),
                        "proyectos": filas}, f,
                       allow_unicode=True, sort_keys=False)


def resolver(dicho: str,
             proyectos: tuple[Proyecto, ...] | None = None,
             config_dir: Path | None = None) -> Resolucion:
    """De "el proyecto nebula" a una carpeta. Tres salidas.

    Se compara contra el ALIAS y contra el nombre de la CARPETA, los dos
    normalizados. Contra la carpeta tambien porque es lo que uno dice sin
    pensar, y registrarla no deberia obligar a repetir su nombre.

    NO HAY COINCIDENCIA PARCIAL. "auto" no abre "nebula": la mitad de
    un nombre es justo el caso en el que dos proyectos empiezan igual, y
    ahi la respuesta correcta es preguntar, no adivinar. Lo que si se
    ignora es el relleno ("el", "de", "proyecto"), que no distingue nada.

    >>> Y DESDE EL 2026-09-03, TAMPOCO EL ESPACIO DISTINGUE NADA <<<
    Lo reporto el usuario creyendo que era otra cosa: que el nombre del
    proyecto le llegaba a veces con la mayuscula inicial y a veces sin
    ella, y que con esa diferencia ya no lo encontraba. **La mayuscula NO
    era la causa y esta medido**: `normalizar` baja el texto desde el
    la causa y esta medido**: `normalizar` baja el texto desde el primer
    dia, asi que "Redactor", "redactor" y "REDACTOR" resuelven los tres.
    Lo que fallaba era lo que iba PEGADO a la mayuscula -- el STT parte
    un nombre en CamelCase en dos palabras --, y eso si rompia:

        dicho                  normalizado        antes    ahora
        "torreazul"         torreazul       UNO      UNO
        "Torre Azul"        torre azul      NINGUNO  UNO
        "Ne Bula"            ne bula          NINGUNO  UNO
        "Jarvis Code"          jarvis code        NINGUNO  NINGUNO (*)

    (*) no esta registrado, que es la respuesta correcta.

    Y estaba PREDICHO en la cabecera de este archivo desde que se
    escribio -- que "nebula" puede llegar como "ne bula", "nebula" o
    "ne-bula" segun como se diga --: se uso para argumentar que hacia
    falta un registro explicito, y luego se comparo con los espacios
    dentro. El aviso estaba y la comparacion no lo recogia.

    >>> DOS PASADAS, Y LA SEGUNDA SIGUE SIENDO EXACTA <<<
    Primero se compara el normalizado tal cual; solo si NADIE casa se
    vuelve a comparar con los espacios quitados de los dos lados. Eso no
    es coincidencia difusa y la diferencia importa: sigue siendo igualdad
    de la cadena ENTERA, o sea que "auto" sigue sin abrir "nebula". Lo
    unico que se ignora es donde cayo un espacio, igual que ya se ignoran
    la tilde y la mayuscula. Un guion tambien, porque `normalizar` ya lo
    convierte en espacio.

    La primera pasada MANDA sobre la segunda a proposito: si hay un
    proyecto que casa letra por letra, ese es, y no se le suman los que
    solo casan pegados. Y si al pegar casan dos, sale VARIOS -- se
    pregunta, que es la salida que ADR-0029 reservo para la duda.
    """
    registrados = leer(config_dir) if proyectos is None else proyectos
    aguja = normalizar(dicho)
    if not aguja:
        return Resolucion(Cuantas.NINGUNO, dicho)
    pegada = aguja.replace(" ", "")

    casan = []
    pegados = []
    for p in registrados:
        nombres = {normalizar(p.alias), normalizar(Path(p.carpeta).name)}
        if aguja in nombres:
            casan.append(p)
        elif pegada in {n.replace(" ", "") for n in nombres if n}:
            pegados.append(p)
    casan = casan or pegados

    if not casan:
        return Resolucion(Cuantas.NINGUNO, dicho)
    if len(casan) > 1:
        # >>> NO SE ELIGE POR EL USUARIO <<< Es la regla que el propio
        # ADR-0029 escribio: "ante varias candidatas, se pregunta".
        return Resolucion(Cuantas.VARIOS, dicho, tuple(casan))
    return Resolucion(Cuantas.UNO, dicho, (casan[0],))


def candidatas_bajo(raiz: str | Path) -> tuple[str, ...]:
    """Las subcarpetas de una raiz, para OFRECERLAS en el panel.

    Descubrir es barato; lo que no se hace es ABRIR una que nadie haya
    declarado. Esta funcion no resuelve nada: solo rellena una lista de
    la que el usuario elige.
    """
    base = Path(raiz).expanduser()
    if not base.is_dir():
        return ()
    try:
        return tuple(sorted(
            str(h) for h in base.iterdir()
            if h.is_dir() and not h.name.startswith(".")))
    except OSError:
        return ()
