"""De una respuesta escrita a una frase que quepa en un oido (JC-0004).

Una respuesta de Claude Code esta escrita para LEERSE: markdown, listas,
rutas entre comillas invertidas, negritas. Locutarla entera es
inservible, y no por larga: por su forma. JC-0004 lo dice y JC-0008 lo
resuelve casi entero -- se locutan una o dos frases y el detalle queda en
la consola. Este modulo es esas una o dos frases.

>>> LO QUE ENSENO UNA RESPUESTA REAL, Y CAMBIO EL DISENO <<<
`eval/trazas_claude_code/respuesta_larga.jsonl` es una respuesta de
verdad, capturada el 2026-08-25: 2035 caracteres, ocho puntos con
negritas y rutas. Su PRIMERA FRASE es:

    "Un proyecto tipico de asistente de voz en Python se organiza asi:"

Locutar "las dos primeras frases" habria dicho eso y se habria quedado
tan ancho. Es una entradilla: no contesta nada, y encima suena a que el
asistente se ha quedado colgado a mitad.

Asi que una lista NO se resume como un texto. Se dice la entradilla, se
dice CUANTOS puntos hay, y se dice el primero. "Son ocho puntos, el
primero es el punto de entrada" es una frase con contenido; "se organiza
asi" no lo es. Ademas el recuento es justo lo que JC-0002 pedira para las
aprobaciones -- cuantos y cuales elementos --, y viene del mismo sitio.

>>> LO QUE ESTE MODULO NO ARREGLA, Y CONVIENE SABERLO <<<
Las RUTAS siguen sonando mal. "asistente/main.py" leido por el TTS no se
parece a lo que un humano diria, y este proyecto ya se cobro esa
diferencia una vez ('captura.png' contra 'captura punto png' en el banco
de STT, que inflo el WER de los cinco modelos por igual). Aqui se quitan
los adornos de markdown -- que si son ruido puro -- y no se toca el
contenido: inventar como se pronuncia una ruta es otro problema, y uno
que se resuelve mal a ciegas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Cuanto se locuta. No es un limite de caracteres elegido bonito: son
# ~15 segundos de habla con las voces de piper, que es lo que aguanta
# alguien que esta esperando una respuesta y no leyendo una pagina.
LIMITE_HABLADO = 240

# Cuanto puede venir DETRAS de una pregunta sin que deje de contar como
# pregunta pendiente. Ver `pregunta_final`: son los cierres amables que
# el modelo pone tras preguntar (56 caracteres en `pregunta_con_cierre`,
# que es el caso real que rompio la version anterior). Por encima de
# esto se entiende que la respuesta siguio a lo suyo.
COLA_MAXIMA = 200

# Lo que marca un punto de lista al principio de una linea: guion,
# asterisco, o un numero seguido de punto.
MARCA_DE_PUNTO = re.compile(r"^\s{0,4}(?:[-*+]|\d{1,2}[.)])\s+")

# Un final de frase de verdad. Pide DOS cosas y las dos hacen falta,
# medidas contra la respuesta real de `respuesta_larga.jsonl`:
#   * espacio detras del punto, o 'informe.pdf' serian dos frases;
#   * que lo siguiente empiece como empieza una frase (mayuscula, numero
#     o signo de apertura), o "ej. asistente/main.py" se parte en dos y
#     el resumen locuta "el primero: main.py (en la raiz, ej..", que es
#     peor que no resumir. Las abreviaturas del español son minoria de
#     casos y mayoria de destrozos.
FIN_DE_FRASE = re.compile(r"(?<=[.!?])\s+(?=[¿¡\"'(A-ZÁÉÍÓÚÜÑ0-9])")


@dataclass(frozen=True)
class Resumen:
    """Lo que se dice, y las magnitudes para saber que se dejo fuera.

    Los numeros son continuos a proposito. "se recorto" es una
    bandera y no deja distinguir haber dejado fuera dos frases de haber
    dejado fuera dos mil caracteres, que es la diferencia entre un
    resumen util y uno que engana.
    """

    hablado: str
    elementos: int = 0
    """Cuantos puntos tenia la lista. 0 si no era una lista."""

    largo_original: int = 0
    recortado: bool = False

    @property
    def fraccion_hablada(self) -> float:
        if not self.largo_original:
            return 1.0
        return len(self.hablado) / self.largo_original

    def describe(self) -> str:
        return (f"{len(self.hablado)} de {self.largo_original} caracteres"
                f"{f', {self.elementos} puntos' if self.elementos else ''}"
                f"{' (recortado)' if self.recortado else ''}")


def sin_markdown(texto: str) -> str:
    """Quita los adornos y deja las palabras.

    Los bloques de codigo se van ENTEROS: leer en voz alta tres lineas de
    Python no informa a nadie, y ademas es lo que mas tarda. Lo que hace
    falta saber de un bloque de codigo es que esta en pantalla.
    """
    limpio = re.sub(r"```.*?```", " ", texto, flags=re.DOTALL)
    limpio = re.sub(r"`([^`]*)`", r"\1", limpio)
    limpio = re.sub(r"\*\*([^*]+)\*\*", r"\1", limpio)
    limpio = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", limpio)
    limpio = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", limpio)
    limpio = re.sub(r"^\s{0,3}#{1,6}\s*", "", limpio, flags=re.MULTILINE)
    return limpio


def puntos_de_lista(texto: str) -> tuple[str, list[str]]:
    """Separa la entradilla de los puntos, si es que hay puntos.

    Devuelve la entradilla y la lista. Sin lista, la lista viene vacia y
    la entradilla es el texto entero: quien llame no tiene que preguntar
    "era una lista?" por su cuenta.
    """
    entradilla: list[str] = []
    puntos: list[str] = []
    for linea in texto.splitlines():
        if MARCA_DE_PUNTO.match(linea):
            puntos.append(MARCA_DE_PUNTO.sub("", linea).strip())
        elif not puntos and linea.strip():
            entradilla.append(linea.strip())
    return " ".join(entradilla), puntos


def primeras_frases(texto: str, limite: int) -> tuple[str, bool]:
    """Todo lo que quepa en `limite`, cortando por frases y no por letras.

    Cortar a media palabra suena a corte de linea telefonica. Si ni la
    primera frase cabe, se corta por palabras -- que es feo pero sigue
    siendo pronunciable -- y se avisa de que se recorto.
    """
    frases = [f.strip() for f in FIN_DE_FRASE.split(texto.strip()) if f.strip()]
    if not frases:
        return "", False

    dicho: list[str] = []
    for frase in frases:
        candidato = " ".join([*dicho, frase])
        if dicho and len(candidato) > limite:
            return " ".join(dicho), True
        dicho.append(frase)
    entero = " ".join(dicho)
    if len(entero) <= limite:
        return entero, len(dicho) < len(frases)

    # Ni una frase cabe: se corta por palabras.
    palabras = entero.split()
    recorte: list[str] = []
    for palabra in palabras:
        if recorte and len(" ".join([*recorte, palabra])) > limite:
            break
        recorte.append(palabra)
    return " ".join(recorte), True


def pregunta_final(texto: str) -> str | None:
    """La pregunta que deja una respuesta esperando, si es que la deja.

    >>> ESTO ES LO QUE DE VERDAD PASA, Y NO LA HERRAMIENTA <<<
    `AskUserQuestion` existe y llega por el canal de control, pero se usa
    para elegir entre opciones DENTRO de una tarea. Lo que hace Claude
    Code la mayor parte de las veces es preguntar EN PROSA y cerrar el
    turno. Capturado contra el binario en `pregunta_en_prosa.jsonl`, un
    turno que cierra asi:

        "Puedo organizarte los archivos del escritorio por tipo, fecha o
         proyecto [...]. ¿En que ruta esta ese escritorio, que criterio
         de orden quieres usar y hay algo que deba dejar intacto o
         excluir?"

    y en TODO el turno hay **cero** `control_request`. O sea que un
    asistente que solo abre el microfono cuando llega la herramienta se
    queda callado justo cuando le acaban de preguntar algo -- que es lo
    que se vio y se reporto usandolo.

    >>> Y NO BASTA CON QUE LA ULTIMA FRASE SEA LA PREGUNTA <<<
    Eso fue la primera version y fallo en el primer uso. La respuesta que
    la rompio, tambien capturada (`pregunta_con_cierre.jsonl`):

        "¿Que tipo de archivos son y como quieres organizarlos (por
         fecha, tipo o proyecto)? ¡Vamos a dejar ese escritorio como los
         chorros del oro!"

    La pregunta esta en medio y detras va un cierre amable. Un asistente
    que se queda sordo porque le anadieron una frase de animo es
    exactamente el fallo que se venia a arreglar.

    LO QUE HAY MEDIDO, sobre las respuestas con interrogante de las
    trazas que acompanan a este codigo:

        cola detras del ultimo "?"      cuantas
        0 caracteres                       1
        56 ("¡Vamos a dejar ese escritorio...!")               1

    La tanda con la que se eligio el umbral (2026-08-25) fueron cinco, y
    las otras tres salian de logs de sesiones reales, que son del autor
    y no se publican. La forma que decide es la misma y esta aqui.

    Asi que la regla mira LA COLA: si detras del ultimo interrogante
    queda poco, la pregunta sigue en pie. Si detras hay parrafos, es que
    la respuesta siguio a lo suyo y aquello era retorico.

    >>> Y EL UMBRAL SE ELIGE HACIA EL LADO PERMISIVO, A PROPOSITO <<<
    No hay ni una sola respuesta en las trazas que lleve interrogante SIN
    estar preguntando, o sea que la tasa de falsos no se puede estimar
    (el suceso ocurrio 0 veces). Con eso, lo que decide es el
    coste:

        abrir el microfono de mas   suena el aviso, se graban 4 s, no
                                    dices nada y se cierra solo.
        no abrirlo cuando tocaba    le contestas a un asistente sordo.
                                    Es la queja con la que empezo esto.

    No son comparables. `COLA_MAXIMA` es generosa por eso, y es un punto
    de partida: si en el uso resulta que abre el microfono donde no toca,
    se baja -- pero eso hay que verlo, no suponerlo.
    """
    limpio = sin_markdown(texto).strip()
    corte = limpio.rfind("?")
    if corte < 0:
        return None
    if len(limpio) - corte - 1 > COLA_MAXIMA:
        return None
    frases = [f.strip() for f in FIN_DE_FRASE.split(limpio[:corte + 1])
              if f.strip()]
    return frases[-1] if frases else None


def para_un_oido(texto: str, limite: int | None = LIMITE_HABLADO,
                 idioma: str | None = None) -> Resumen:
    """La respuesta escrita, convertida en lo que se va a locutar.

    Tres formas distintas segun lo que llegue, y no una sola con
    excepciones: nada, una lista, o prosa. La del medio es la que
    justifica que este modulo exista.

    >>> `limite=None` LO DICE TODO, Y ES LO QUE PIDIO EL USUARIO <<<
    JC-0004 decidio locutar una o dos frases y dejar el detalle en la
    consola. Usandolo, el usuario pidio lo contrario: "quiero que diga
    siempre todo el texto". Es su decision y manda, pero conviene tener
    la cifra delante: la respuesta larga que hay en las trazas son 2035
    caracteres, o sea unos **145 segundos hablando**. El interruptor para
    volver al resumen es `-m puente ... --voz --resumir`.

    Lo que NO se locuta ni pidiendo "todo" son los bloques de codigo:
    leer Python en voz alta no informa a nadie. Se dice que estan y donde
    mirarlos, que es la unica parte con contenido.
    """
    from voz.idioma import frase as _f

    original = len(texto)
    tenia_codigo = "```" in texto
    limpio = sin_markdown(texto).strip()
    if not limpio:
        # Puede haber quedado vacio porque TODO era codigo. Callarse ahi
        # seria dejar al usuario esperando una respuesta que si existe.
        if tenia_codigo:
            return Resumen(hablado=_f("resumen.te_lo_deje", idioma=idioma),
                           largo_original=original, recortado=True)
        return Resumen(hablado="", largo_original=original)

    if limite is None:
        entero = " ".join(limpio.split())
        if tenia_codigo:
            entero += _f("resumen.codigo_en_consola", idioma=idioma)
        _, puntos = puntos_de_lista(limpio)
        return Resumen(hablado=entero, elementos=len(puntos),
                       largo_original=original, recortado=False)

    entradilla, puntos = puntos_de_lista(limpio)
    if len(puntos) >= 2:
        # Una lista. Lo que informa es CUANTOS y el primero; el resto
        # esta en la consola y ahi se lee mejor que se oye.
        cabecera = entradilla.rstrip(":").strip()
        primero = primeras_frases(puntos[0], max(60, limite // 2))[0]
        cuantos = _f("resumen.son_n_puntos", len(puntos), idioma=idioma)
        partes = [p for p in (cabecera, cuantos) if p]
        hablado = ". ".join(partes) + _f("resumen.el_primero", primero,
                                         idioma=idioma)
        return Resumen(hablado=hablado, elementos=len(puntos),
                       largo_original=original, recortado=True)

    hablado, recortado = primeras_frases(limpio, limite)
    return Resumen(hablado=hablado, largo_original=original,
                   recortado=recortado)


# ---------------------------------------------------------------------
# Las opciones de una pregunta en prosa (JC-0016 ampliado, 2026-08-29)
# ---------------------------------------------------------------------
#
# >>> POR QUE ESTO EXISTE, Y POR QUE NO ES UN PARSER MAS <<<
# Una pregunta en prosa CIERRA el turno. Contestarla no es `responder`
# -- no queda nada esperando en la puerta de control --: es `mandar`, o
# sea UN TURNO NUEVO. Y "mandar ordenes nuevas" es exactamente lo que
# JC-0016 prohibio por escrito, porque convierte Telegram en un canal
# que CONDUCE la PC en vez de uno que contesta.
#
# Lo unico que mantiene en pie la frase que sostiene JC-0016 --
# "lo peor que puede pasar si te roban el token es que alguien conteste
# una pregunta de diseno en tu nombre" -- es que por ahi NO pueda entrar
# texto libre. De ahi este modulo: de la prosa salen ETIQUETAS, y lo que
# viaja es una de ellas.
#
# >>> Y LAS ETIQUETAS SON TROZOS LITERALES DE LO QUE ESCRIBIO CLAUDE <<<
# No se redactan aqui, se RECORTAN. Quien tenga el token elige entre N
# fragmentos que redacto el propio modelo; no puede colar una palabra.
# Si el fragmento elegido acaba disparando algo destructivo, se para
# igual en la puerta (JC-0001), que sigue sin poder contestarse desde el
# movil. La unica excepcion es el si/no, y esta dicha mas abajo.
#
# >>> MEDIDO CONTRA LAS 36 PREGUNTAS REALES QUE HAY EN DISCO <<<
# `python -m eval.mirar_preguntas`, sobre `logs/puente/*.jsonl`: 42
# sesiones, 76 turnos cerrados, 36 que terminan preguntando (47 %, o sea
# que este NO es el camino raro: es casi la mitad de los turnos).

FORMA_NINGUNA = "ninguna"
FORMA_DUDOSA = "dudosa"
FORMA_DISYUNTIVA = "disyuntiva"
FORMA_SI_NO = "si_no"

# Una etiqueta mas larga que esto no es una opcion, es un parrafo: si
# aparece, es que el corte se hizo por donde no era.
ETIQUETA_MAXIMA = 160

# Y por debajo de esto tampoco es una opcion ("o", "si", restos de
# puntuacion que sobrevivieron al recorte).
ETIQUETA_MINIMA = 3

# Cuando un elemento de una lista en serie ("un archivo, una carpeta,
# una aplicacion, o otra cosa") pasa de esto, ya no parece un elemento
# de lista sino una frase con comas dentro, y partir por ahi inventaria
# opciones. Ver `_partir_en_serie`.
ELEMENTO_DE_SERIE_MAXIMO = 60

# >>> LA PRIMERA TRAMPA, Y ESTA EN LOS DATOS REALES <<<
#     "...que afine el regex del script ... y/o que sigamos juntando
#      muestras ...?"
# `y/o` NO es excluyente: son dos cosas que se pueden querer las dos.
# Numerarlas invitaria a elegir una donde el usuario podia pedir ambas.
Y_O = re.compile(r"\by\s*/\s*o\b", re.IGNORECASE)

# >>> LA SEGUNDA TRAMPA, Y TAMBIEN ES REAL <<<
#     "Que necesitas que te muestre o en que puedo ayudarte?"
# Ese `o` no separa opciones: une DOS PREGUNTAS ABIERTAS. Se reconoce
# porque el trozo empieza por un interrogativo -- ninguna opcion de
# verdad lo hace.
INTERROGATIVO = re.compile(
    "^(?:[" + "¿" + "(]\\s*)?"
    "(?:de|en|a|con|por|para|sobre|hacia|desde)?\\s*"
    "(?:que|qué|quien|quién|quienes|quiénes|como|cómo|"
    "cual|cuál|cuales|cuáles|cuando|cuándo|donde|dónde|"
    "cuanto|cuánto|cuanta|cuánta|cuantos|cuántos|cuantas|"
    "cuántas)\\b",
    re.IGNORECASE)

# Con que se abre una pregunta que se contesta si o no. Es una lista
# CORTA y de DECISIONES, no de cortesias: "podrias precisar...?" tiene
# forma de si/no y lo que pide es informacion -- contestarle "si" no le
# da nada, asi que esas se quedan fuera a proposito.
ABRE_SI_NO = re.compile(
    "^(?:[" + "¿" + "(]\\s*)?(?:"
    "quieres|queres|querés|quiere|quieren|"
    "empiezo|empezamos|empieza|"
    "arranco|arrancamos|arranca|"
    "sigo|seguimos|sigue|continuo|continúo|continuamos|"
    "procedo|procedemos|"
    "hago|hacemos|"
    "te refieres|te referias|te referías|"
    "confirmas|confirmás|"
    "retomamos|retomo|"
    "lanzo|lanzamos|abro|abrimos|creo|creamos"
    ")\\b",
    re.IGNORECASE)


@dataclass(frozen=True)
class Opciones:
    """Lo que se puede numerar de una pregunta en prosa.

    >>> CUATRO SALIDAS Y NO DOS, Y LA CUARTA ES LA QUE IMPORTA <<<
    Tres salidas: "hay opciones" / "no hay opciones" / "hay algo que PARECE
    opciones y no se sabe". Colapsar la tercera contra la primera manda
    al movil una eleccion que nadie ofrecio; colapsarla contra la
    segunda es la direccion segura -- se avisa igual, y se contesta en
    la consola.

    Asi que `dudosa` SE COMPORTA como `ninguna` a proposito, pero se
    cuenta aparte: si ese numero crece, es que el extractor se
    esta quedando corto y hay material para afinarlo. Colapsadas, no
    habria forma de enterarse.
    """

    etiquetas: tuple[str, ...] = ()
    forma: str = FORMA_NINGUNA
    enunciado: str = ""
    """La pregunta ya limpia, para enseñarla en otro canal.

    Existe porque `pregunta_final` devuelve la COLA del texto, y una de
    las 36 reales arrastra escombros de una lista numerada delante del
    signo de apertura ("Ollama corriendo ... 3. cd services\api ... 4.
    alembic check ... ¿Quieres que arranque con esa verificacion?").
    Mandar eso al movil es ilegible, y recortarlo en cada canal seria
    tener dos recortadores que se separan. Se recorta aqui,
    que es donde ya se sabe donde empieza la pregunta.

    Vacio cuando no se sabe recortarla (una bateria de varias): entonces
    el canal enseña el texto entero, que es lo que habia antes.
    """

    @property
    def contestable(self) -> bool:
        """Si esto se puede mandar numerado al movil."""
        return bool(self.etiquetas)


def _nucleo(pregunta: str) -> str:
    """De la frase entera a lo que hay entre el ultimo signo de apertura
    y el de cierre.

    Hace falta porque las preguntas reales vienen con delantal:
    "Por ejemplo, ¿un archivo, una carpeta, ...?". Ese "Por ejemplo,"
    no es parte de ninguna opcion.
    """
    texto = (pregunta or "").strip()
    corte = texto.rfind("?")
    if corte >= 0:
        texto = texto[:corte]
    abre = texto.rfind("¿")
    if abre >= 0:
        texto = texto[abre + 1:]
    return texto.strip()


def _sin_parentesis(texto: str) -> str:
    """El mismo texto con lo que hay entre parentesis tapado por puntos.

    NO se borra: se SUSTITUYE por relleno del mismo largo, para que los
    indices sigan valiendo sobre el texto original. Es lo que permite
    buscar separadores "de nivel cero" -- una coma dentro de
    "(mercados/economia, mas recientes, etc.)" no separa opciones.
    """
    salida = list(texto)
    profundidad = 0
    for i, c in enumerate(texto):
        if c in "([":
            profundidad += 1
        elif c in ")]":
            profundidad = max(0, profundidad - 1)
        elif profundidad > 0:
            salida[i] = "."
    return "".join(salida)


def _limpiar(trozo: str) -> str:
    """Quita la puntuacion y las rayas que sobreviven a un corte."""
    return trozo.strip().strip(",;:—–-").strip()


def _partir(texto: str, patron: "re.Pattern") -> list[str]:
    """Parte por el patron, pero solo donde NO hay parentesis abiertos."""
    plano = _sin_parentesis(texto)
    trozos: list[str] = []
    ultimo = 0
    for coincidencia in patron.finditer(plano):
        trozos.append(texto[ultimo:coincidencia.start()])
        ultimo = coincidencia.end()
    trozos.append(texto[ultimo:])
    return [t for t in (_limpiar(x) for x in trozos) if t]


# El `o` que separa alternativas, con la coma opcional que suele llevar
# delante. Va con espacio a los lados a proposito: sin ellos casaria
# dentro de cualquier palabra.
SEPARA_O = re.compile(r"\s*,?\s+o\s+(?:si\s+)?", re.IGNORECASE)
SEPARA_COMA = re.compile(r"\s*,\s*")


# Con que NO empieza un elemento de una lista, y por tanto delata que la
# coma era un aposito o una oracion de relativo. Ver `_partir_en_serie`.
EMPIEZA_RELATIVO = re.compile(
    r"^(?:que|quien|quienes|el cual|la cual|los cuales|las cuales|"
    r"lo que|y|pero|porque|ya que|as[ií] que|donde|cuando|mientras)",
    re.IGNORECASE)


def _partir_en_serie(trozo: str) -> list[str]:
    """Una lista en serie dentro de un trozo, si es que lo es.

    "un archivo, una carpeta, una aplicacion" son TRES opciones, y
    quedarse con la cadena entera mandaria al movil un grumo que nadie
    ofrecio como unidad. Pero
    "preferis ir directo al (B), el A/B contra el modelo real" NO es una
    lista: es un aposito, y partirlo inventa una tercera opcion.

    >>> LAS DOS COSAS SE PARECEN, Y LAS SEPARA LA POSICION <<<
    Esta funcion se llama SOLO sobre el trozo que va ANTES del `o`, y esa
    es la regla que de verdad decide. En una serie -- "A, B, C, o D" --
    las comas caen siempre delante de la disyuncion; una coma que aparece
    DETRAS del `o` nunca separa lista, porque la lista ya termino.
    Las dos preguntas reales que rompian la version anterior
    (`-m eval.mirar_preguntas`) tenian las dos su coma detras del `o`.

    Encima de eso, dos guardas baratas: los elementos de una serie son
    CORTOS, y ninguno empieza por un relativo. Si algo no cuadra no se
    parte y se devuelve el trozo entero -- direccion segura, porque un
    trozo de mas sigue siendo literal de lo que escribio Claude.
    """
    partes = _partir(trozo, SEPARA_COMA)
    if len(partes) < 2:
        return [trozo]
    if any(len(p) > ELEMENTO_DE_SERIE_MAXIMO for p in partes):
        return [trozo]
    if any(EMPIEZA_RELATIVO.match(p) for p in partes):
        return [trozo]
    return partes


def opciones_de_pregunta(pregunta: str) -> Opciones:
    """Las alternativas que ofrece una pregunta escrita en prosa.

    Disenado y medido contra las 36 preguntas reales que hay en
    `logs/puente/*.jsonl` (`python -m eval.mirar_preguntas`), no contra
    preguntas imaginadas.
    """
    texto = (pregunta or "").strip()
    if not texto:
        return Opciones()

    # >>> UNA BATERIA DE PREGUNTAS NO ES UNA ELECCION <<<
    # Tres de las 36 son varias preguntas seguidas ("De que trata? Ya
    # existe codigo? Que es lo ultimo?"). No hay nada que numerar: lo
    # que se pide es informacion, y eso se escribe, no se elige.
    if texto.count("?") > 1:
        return Opciones(forma=FORMA_NINGUNA)

    nucleo = _nucleo(texto)
    if not nucleo:
        return Opciones()
    enunciado = "¿" + nucleo + "?"

    if Y_O.search(nucleo):
        return Opciones(forma=FORMA_DUDOSA, enunciado=enunciado)

    partes = _partir(nucleo, SEPARA_O)
    if len(partes) >= 2:
        # El `o` que une dos preguntas abiertas, no dos opciones.
        if any(INTERROGATIVO.match(p) for p in partes):
            return Opciones(forma=FORMA_DUDOSA, enunciado=enunciado)
        # La serie solo se busca en el PRIMER trozo: ver
        # `_partir_en_serie`. Los demas se quedan enteros.
        etiquetas: list[str] = list(_partir_en_serie(partes[0]))
        etiquetas.extend(partes[1:])
        etiquetas = [e for e in (_limpiar(x) for x in etiquetas) if e]
        if len(etiquetas) < 2:
            return Opciones(forma=FORMA_DUDOSA, enunciado=enunciado)
        if any(len(e) < ETIQUETA_MINIMA or len(e) > ETIQUETA_MAXIMA
               for e in etiquetas):
            return Opciones(forma=FORMA_DUDOSA, enunciado=enunciado)
        return Opciones(etiquetas=tuple(etiquetas),
                        forma=FORMA_DISYUNTIVA, enunciado=enunciado)

    # >>> EL SI/NO ES LA UNICA FORMA QUE NO ES LITERAL, Y SE DICE <<<
    # "Si" y "No" los ponemos nosotros; no son un recorte de lo que
    # escribio Claude. Lo que los hace aceptables es que no llevan
    # instruccion propia: toda la instruccion esta en la proposicion que
    # Claude acaba de escribir, y lo unico que se manda es aceptarla o
    # rechazarla. Aun asi es la forma que hay que mirar primero si algun
    # dia esto hay que apretar.
    if INTERROGATIVO.match(nucleo):
        return Opciones(forma=FORMA_NINGUNA, enunciado=enunciado)
    if ABRE_SI_NO.match(nucleo):
        return Opciones(etiquetas=("Si", "No"), forma=FORMA_SI_NO,
                        enunciado=enunciado)

    return Opciones(forma=FORMA_NINGUNA, enunciado=enunciado)
