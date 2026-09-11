"""Los cuatro temas: que sean CUATRO PALETAS y no cuatro paginas.

QUE SE PRUEBA AQUI Y QUE NO. **No se prueba que se vean bonitos**: eso
lo tiene que mirar una persona, y quien dicta no ve la terminal. Lo que
si se prueba es todo lo que se rompe EN SILENCIO, que en un sistema de
temas es casi todo:

  * un token que a un tema se le olvide definir NO da error: cae al
    valor de `:root`, o sea que el tema "hacker" saldria verde con una
    linea cian y no habria nada roto que arreglar. Ese es el fallo por
    defecto de cualquier paleta por capas y el motivo principal de este
    archivo;
  * un color literal que se cuele otra vez en el HTML se queda igual en
    los cuatro temas, y solo se nota mirando los cuatro;
  * una regla de maqueta dentro de `tema.css` haria que cambiar de tema
    moviera la pagina de sitio, y "tema" habria dejado de significar
    "colores" sin que nadie lo decidiera;
  * un tema que exista en el CSS y no en la lista blanca del servidor
    (o al reves) es un tema que no se puede elegir, o peor, un valor que
    se estampa dentro de nuestro HTML sin comprobar.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
CSS = RAIZ / "puente" / "tema.css"
CONSOLA = RAIZ / "puente" / "consola.html"
AJUSTES = RAIZ / "puente" / "ajustes.html"


def bloques() -> dict[str, dict[str, str]]:
    """Cada bloque de variables del CSS, por tema.

    Se lee el ARCHIVO REAL y no una copia: la premisa de una tanda se
    verifica contra lo que hay en disco.
    """
    texto = CSS.read_text(encoding="utf-8")
    # Fuera los comentarios: llevan ejemplos con `--cian-rgb` dentro y
    # contarlos como definiciones daria un verde falso.
    texto = re.sub(r"/\*.*?\*/", "", texto, flags=re.DOTALL)
    salida: dict[str, dict[str, str]] = {}
    for cabecera, cuerpo in re.findall(
            r"(:root(?:\[data-tema=\"[a-z]+\"\])?)\s*\{([^}]*)\}", texto):
        nombre = "jarvis"
        marca = re.search(r'data-tema="([a-z]+)"', cabecera)
        if marca:
            nombre = marca.group(1)
        variables = dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", cuerpo))
        salida.setdefault(nombre, {}).update(variables)
    return salida


# --- 1. NINGUN TEMA PUEDE OLVIDARSE UN TOKEN ------------------------------


def test_los_cuatro_temas_definen_LO_MISMO() -> None:
    """>>> EL TEST QUE JUSTIFICA ESTE ARCHIVO <<<

    Un token sin definir no falla: hereda el de `:root`, que es cian. O
    sea que el precio de olvidarse una variable en el tema claro es un
    resplandor cian en mitad de una pagina color cafe, sin ningun error
    en ningun sitio. Se compara el conjunto ENTERO, no un puñado.
    """
    todos = bloques()
    base = set(todos["jarvis"])
    assert len(base) > 40, "la paleta base se ha quedado corta: revisa el parseo"
    for tema, variables in todos.items():
        if tema == "jarvis":
            continue
        faltan = base - set(variables)
        sobran = set(variables) - base
        assert not faltan, f"a '{tema}' le faltan: {sorted(faltan)}"
        assert not sobran, f"'{tema}' define de mas: {sorted(sobran)}"


def test_ningun_tema_deja_un_token_vacio() -> None:
    for tema, variables in bloques().items():
        for clave, valor in variables.items():
            assert valor.strip(), f"{tema}: {clave} esta vacio"


# --- 2. LA MAQUETA YA NO ESTA PROHIBIDA. LO PROHIBIDO ES OTRA COSA -------

# >>> LEE ESTO ANTES DE TOCAR NADA DE ESTA SECCION <<<
#
# Hasta el 2026-08-29 aqui vivia `test_el_css_de_tema_no_toca_la_maqueta`,
# que fallaba si aparecia un `padding` en `tema.css`. Su intencion era
# buena y estaba escrita en su propio docstring: *"los cuatro temas
# tienen que pintar LA MISMA pantalla"*.
#
# Pero medía otra cosa. "La misma pantalla" no significa "los mismos
# pixeles": significa que los cuatro ENSEÑAN LO MISMO. Un tema puede
# mover la puerta de sitio, cambiarle la letra y ponerla del doble de
# grande sin quitarle ni una palabra -- y ese tema era imposible de
# escribir con el test viejo. Al reves tambien: aquel test pasaba
# tranquilamente si alguien ponia `--cian: transparent` y dejaba media
# consola invisible, porque eso es una variable de color.
#
# O sea que prohibia lo inofensivo y dejaba pasar lo grave.
#
# Lo sustituyen estos:
#   * `test_tema_css_sigue_siendo_solo_tokens` -- la hoja COMPARTIDA
#     sigue sin poder llevar maqueta, porque la leen los cuatro y una
#     regla ahi tocaria tambien a `jarvis`, el unico ya aceptado en
#     pantalla. La maqueta de cada tema va en `puente/temas/<tema>.css`.
#   * `test_ningun_tema_esconde_una_pieza_obligatoria` -- el que de
#     verdad protege lo que importaba.
#
# Si algun dia hay que aflojar el segundo, lo que se afloja es el
# CONSENTIMIENTO. Esa es la conversacion, no un test que estorba.

HOJAS = RAIZ / "puente" / "temas"


def test_un_modulo_QUE_SE_PLIEGA_no_puede_llevar_display_inline() -> None:
    """>>> ESTE TEST NACE DE UNA CAPTURA, EL 2026-09-03 <<<

    El plegado de PERIMETRO y CARGA se escribio, la clase `plegado` se
    ponia, los botones cambiaban a MOSTRAR... y el cuerpo seguia entero
    en pantalla. La causa: los hijos llevaban `style="display:flex..."`
    INLINE, y un estilo inline le gana a cualquier regla sin
    `!important`. La firma se vio en la captura -- en PERIMETRO
    desaparecio la unica fila SIN inline y se quedaron las que lo
    llevaban.

    Es la CUARTA vez que un `display` inline muerde en esta pagina; la
    tercera fue el centrado de la franja, que ningun tema podia tocar.
    Aqui no se trata de estetica: un inline en estos dos modulos deja el
    boton de plegar mintiendo -- dice MOSTRAR y no ha ocultado nada --,
    y eso no lo caza ningun otro test porque el HTML es correcto y la
    suite entera sigue verde.
    """
    html = CONSOLA.read_text(encoding="utf-8")
    culpables = []
    for cual in ("modPerimetro", "modCarga"):
        ini = html.index(f'id="{cual}"')
        # Hasta el arranque del siguiente hermano de primer nivel, que
        # en los dos casos es un comentario o el div que sigue.
        fin = html.index("\n    <", ini + 1)
        for estilo in re.findall(r'style="([^"]*)"', html[ini:fin]):
            if "display" in estilo:
                culpables.append(f"{cual}: {estilo}")
    assert not culpables, (
        "un `display` inline aqui hace que el plegado no oculte nada, y "
        "el boton se queda diciendo MOSTRAR sin haber ocultado: "
        + "; ".join(culpables))


def test_la_caja_del_VISOR_no_es_un_panel_de_los_que_un_tema_aplana() -> None:
    """>>> ESTE TEST NACE DE OTRA CAPTURA, EL 2026-09-04 <<<

    Lo reporto el usuario probandolo: al abrir un documento desde la
    bandeja de "te dejo", se abria bien, pero con el fondo verde y
    transparente casi no se podia leer. Y se vio entero en
    `logs/capturas/visor_hacker.png`: el texto del documento cayendo
    encima del registro, de la tira y del rail a la vez.

    La causa no era el visor: era que llevaba la clase `vidrio`, y
    `hacker` aplana `.vidrio` a `background: transparent` con
    `backdrop-filter: none`, porque ahi los paneles son filetes y no
    cajas. Esa regla del tema es CORRECTA para lo que gobierna -- paneles
    que comparten pantalla con lo que tienen al lado --, y el visor no es
    uno de esos: es un modal, y tapar lo de detras es todo su trabajo.

    Ningun test lo cazaba porque los que hay miran que ninguna hoja lo
    ESCONDA (`visor` esta en OBLIGATORIAS), y esto no lo escondia: lo
    dejaba ver a traves. Mismo hueco por el que se colo la tira aplastada
    a 28 px con la suite entera en verde.
    """
    html = CONSOLA.read_text(encoding="utf-8")
    caja = re.search(r'<div class="([^"]*visorCaja[^"]*)"', html)
    assert caja, "no esta la caja del visor: el selector envejecio"
    assert "vidrio" not in caja.group(1).split(), (
        "la caja del visor volvio a ser un panel `vidrio`, y un tema que "
        "aplane `.vidrio` -- hacker lo hace, y es su identidad -- la deja "
        "transparente encima del registro: el documento no se lee")

    # Y que tenga fondo PROPIO, que es la otra mitad: quitarle `vidrio`
    # sin darle uno la dejaria transparente igual, y en los cuatro temas.
    regla = re.search(r"^\.visorCaja \{(.*?)\}", html, re.DOTALL | re.MULTILINE)
    assert regla and "background:" in regla.group(1), (
        "la caja del visor se quedo sin fondo propio: sin `vidrio` y sin "
        "`background` es transparente en los cuatro temas, no en uno")


@pytest.mark.parametrize("hoja", sorted(HOJAS.glob("*.css")), ids=lambda h: h.stem)
def test_ningun_tema_devuelve_el_VISOR_a_transparente(hoja: Path) -> None:
    """La otra direccion: que ninguna hoja de maqueta lo deshaga.

    Quitarle `vidrio` arregla lo de hoy; una regla nueva en un tema
    volveria a abrirlo manana, y otra vez sin que nada de error.
    """
    for selector, cuerpo in reglas(hoja):
        if "visorCaja" not in selector:
            continue
        assert "transparent" not in cuerpo.replace(" ", ""), (
            f"{hoja.name} deja la caja del visor transparente: encima del "
            "registro eso es un documento que no se puede leer")


@pytest.mark.parametrize("hoja", sorted(HOJAS.glob("*.css")),
                         ids=lambda h: h.stem)
def test_un_tema_que_REPINTA_EL_SEMAFORO_dice_sus_estados(
        hoja: Path) -> None:
    """>>> SEXTA VEZ QUE UN TEMA ROMPE ALGO CON LA SUITE VERDE <<<

    (2026-09-09.) `#salud` es el rotulo que dice si Jarvis esta vivo, y
    sus estados los pinta la pagina (`.mal`, `.duda`, y desde hoy
    `.quieto`). Pero un tema escribe `:root[data-tema=X] #salud`, que
    tiene MAS especificidad Y va despues, asi que su `color` y su
    `background` se cuelan por debajo de todos los estados a la vez.

    MEDIDO EN LOS CUATRO, y salieron dos cosas:
      * el REPOSO recien puesto salia con el verde encendido de una
        sesion trabajando en `hacker`, y con el punto VERDE del
        semaforo de `nexo`;
      * y debajo, algo que llevaba ahi desde siempre: en `hacker`,
        "en marcha", "te espera" y "sesion caida" daban EL MISMO
        color. El semaforo estaba ciego en ese tema y no lo cazaba
        nada, porque la clase se ponia bien -- la pintaba otro.

    Subir la especificidad en la pagina es la carrera que el tema
    siempre gana, y un `!important` deja el semaforo fuera del alcance
    de los temas. Asi que lo dice el TEMA, y esto comprueba que lo
    diga ENTERO: quien repinta el semaforo se queda con los tres
    estados.

    El estado puede ir en la CAJA o en el PUNTO -- `nexo` usa el punto
    y deja el texto siempre tenue, y es una decision suya --, asi que
    vale con que este declarado en cualquiera de los dos."""
    PINTA = ("background:", "background-color:", "color:")
    ESTADOS = {"mal", "duda", "quieto"}

    repinta = False
    declarados: set[str] = set()
    for selector, cuerpo in reglas(hoja):
        if "#salud" not in selector:
            continue
        estados = set(re.findall(r"#salud\.(\w+)", selector))
        if estados:
            declarados |= estados
            continue
        # Una regla sobre `#salud` a secas (o su `::before`) que toque
        # el color es la que se cuela por debajo de todos los estados.
        if any(x in cuerpo.replace(" ", "") for x in PINTA):
            repinta = True

    if not repinta:
        return
    faltan = ESTADOS - declarados
    assert not faltan, (
        f"{hoja.name} repinta el color de #salud y no dice como se ven "
        f"{sorted(faltan)}: su regla gana por especificidad a las de la "
        "pagina, asi que esos estados saldran con el color de 'todo "
        "bien\'. El rotulo que dice si Jarvis esta vivo dejaria de "
        "cambiar de color.")


def test_los_dos_modulos_plegables_conservan_su_boton() -> None:
    """El rotulo y su boton NO se esconden al plegar: un panel plegado
    del todo no se puede volver a abrir. Y `rail.perimetro` es ademas
    una pieza OBLIGATORIA -- si el `data-ensena` acabara dentro de lo
    que se oculta, el test de temas seguiria verde y la pieza estaria
    escondida de todas formas."""
    html = CONSOLA.read_text(encoding="utf-8")
    for cual in ("modPerimetro", "modCarga"):
        ini = html.index(f'id="{cual}"')
        cabeza = html.index('class="cabeza"', ini)
        cierra = html.index("</div>", cabeza)
        assert f'data-pliega="{cual}"' in html[cabeza:cierra], (
            f"{cual}: el boton de plegar tiene que vivir DENTRO de "
            f"`.cabeza`, que es lo unico que no se oculta")
    # Y el marcador obligatorio, en la cabeza y no en el cuerpo.
    ini = html.index('id="modPerimetro"')
    cabeza = html.index('class="cabeza"', ini)
    cierra = html.index("</div>", cabeza)
    assert 'data-ensena="rail.perimetro"' in html[cabeza:cierra]



# Las piezas que los cuatro temas tienen que enseñar, con el nombre que
# llevan en `data-ensena`. NO es una lista de "cosas bonitas": cada una
# esta aqui porque no verla cambia lo que el usuario puede hacer o
# decidir. Añadir una obligatoria nueva obliga a tocar esta lista a
# proposito, que es justo lo que se quiere.
OBLIGATORIAS = {
    # >>> LO QUE JARVIS PRODUCE, Y POR QUE ES OBLIGATORIO <<<
    # La queja que lo origino fue "creo un documento y nunca lo veo". Un
    # tema que escondiera esto devolveria al usuario exactamente donde
    # estaba, y sin un solo error: la sesion seguiria escribiendo el
    # documento y el seguiria sin verlo.
    "producido.vivo",
    "visor",
    # >>> EL POV, Y ESTA AQUI POR LO MISMO QUE LA TIRA <<<
    # Es la unica superficie que enseña el trabajo MIENTRAS pasa, y
    # ademas la unica que dice "NO SE HIZO" cuando algo que se vio
    # escribirse acaba denegado. Un tema que lo escondiera dejaria en
    # pantalla el recuerdo de un documento que no existe y ninguna forma
    # de enterarse.
    "pov",
    # La puerta: las cuatro cosas que exige JC-0002, mas la zona donde
    # aparece -- sin ella no hay donde pintarla.
    "puerta.zona",
    "puerta.titulo",      # QUE se va a hacer
    "puerta.motivo",      # la herramienta, y sobre que
    # Lo que Claude PREGUNTA cuando la tarjeta es una pregunta y no un
    # permiso. Sin esto se ven las opciones y no la pregunta, o sea que
    # se elige a ciegas.
    "puerta.enunciado",
    "puerta.crudo",       # la orden ENTERA, y nunca plegada
    "puerta.permitir",    # las tres salidas
    "puerta.denegar",
    "puerta.esperar",
    # El estado: si te oye ahora mismo, y que te toca hacer.
    "nucleo.estado",
    "nucleo.instruccion",
    "nucleo.telemetria",
    "nucleo.cuentas",
    "nucleo.onda",
    # Lo que esta pasando, y por donde se manda una orden.
    "registro",
    "pie.entrada",
    # Los paneles de estado.
    "rail.canales",
    "rail.perimetro",
    "rail.carga",
    # >>> LOS SERVIDORES MCP, Y ES LA MISMA LECCION QUE EL RESTO <<<
    # (2026-09-07.) `blender` estuvo caido TRES sesiones y no habia
    # donde verlo: el estado llegaba en el `system/init` y se tiraba. Un
    # tema que volviera a esconderlo devolveria el sintoma exacto -- la
    # herramienta no esta, y eso se ve igual que si el modelo hubiera
    # decidido no usarla. El modulo se oculta SOLO cuando no hay ningun
    # servidor, y eso lo decide el JS con `hidden`, no una hoja.
    "rail.mcp",
    # La cabecera.
    "cabecera.pestanas",
    "cabecera.salud",
    "cabecera.nodo",
    "cabecera.cuota",
    "cabecera.coste",
    "cabecera.suelo",
    # >>> Y LA PUERTA, QUE ES LA MAS IMPORTANTE DE LA CABECERA <<<
    # JC-0017. Con el auto mode puesto no queda NINGUN otro sintoma: se
    # siguen viendo todas las herramientas, solo que ya nada las para. Un
    # tema que escondiera esto dejaria una sesion sin frenos con la misma
    # pinta que una con frenos, y eso afloja el CONSENTIMIENTO, que es lo
    # que este test existe para no dejar aflojar.
    "cabecera.puerta",
    # El aviso de que un servidor MCP no arranco. Va en la cabecera por
    # la misma regla que el suelo: el DETALLE se pliega, el aviso no.
    "cabecera.mcp",
    # Los ajustes.
    "ajustes.secciones",
    "ajustes.zonas",
    "ajustes.proyectos",
    # Donde se aprende que frases NO llegan al cerebro. Un tema que la
    # esconda deja al usuario sin saber que "apagate" es especial.
    "ajustes.glosario",
    "ajustes.telegram",
    "ajustes.mcp",
    "ajustes.guardar",
    "ajustes.reiniciar",
}

# Las formas de dejar de pintar algo sin borrarlo. Un tema que use
# cualquiera sobre una pieza obligatoria la esta escondiendo, aunque el
# nodo siga en el DOM.
FORMAS_DE_ESCONDER = (
    "display:none", "display: none",
    "visibility:hidden", "visibility: hidden",
    "opacity:0", "opacity: 0",
    "content-visibility:hidden", "content-visibility: hidden",
)


def marcas_de_las_paginas() -> set[str]:
    """Los `data-ensena` de las dos paginas, escritos como sea.

    >>> HAY QUE MIRAR EN DOS SITIOS, Y OLVIDARSE DE UNO ES UN FALSO OK <<<
    La mitad de las piezas obligatorias estan en el HTML como atributo:

        <div id="flujo" data-ensena="registro">

    y la otra mitad -- las SEIS de la puerta -- no pueden estarlo,
    porque la tarjeta de permiso se construye al vuelo cuando llega la
    peticion. Ahi el marcador se pone desde JavaScript:

        titulo.dataset.ensena = "puerta.titulo";

    Un detector que solo mirase el atributo diria que faltan las seis de
    la puerta, que son justo las que mas importan.
    """
    marcadas: set[str] = set()
    for pagina in (CONSOLA, AJUSTES):
        texto = pagina.read_text(encoding="utf-8")
        marcadas |= set(re.findall(r'data-ensena="([^"]+)"', texto))
        marcadas |= set(re.findall(r'\.dataset\.ensena\s*=\s*"([^"]+)"', texto))
    return marcadas


def reglas(hoja: Path) -> list[tuple[str, str]]:
    """Cada regla del archivo, como (selectores, declaraciones)."""
    texto = re.sub(r"/\*.*?\*/", "", hoja.read_text(encoding="utf-8"),
                   flags=re.DOTALL)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", texto)


def test_tema_css_sigue_siendo_solo_tokens() -> None:
    """La paleta compartida no lleva maqueta, y sigue sin llevarla.

    No es el test viejo aunque se le parezca: aquel decia que NINGUN
    tema podia mover nada; este dice que la hoja que leen los CUATRO no
    puede hacerlo, porque ahi dentro no hay forma de tocar a uno sin
    tocar a `jarvis`. Cada tema mueve lo que quiera en su hoja.
    """
    texto = re.sub(r"/\*.*?\*/", "",
                   CSS.read_text(encoding="utf-8"), flags=re.DOTALL)
    prohibidas = ("display:", "padding:", "margin:", "position:", "width:",
                  "height:", "flex", "grid", "z-index:")
    for linea in texto.splitlines():
        limpia = linea.strip().lower()
        if limpia.startswith("--"):
            continue  # un nombre de variable puede llamarse como quiera
        for palabra in prohibidas:
            assert palabra not in limpia, (
                f"maqueta en tema.css: {linea!r}. La maqueta de un tema va "
                f"en puente/temas/<tema>.css, no aqui.")


def test_las_piezas_obligatorias_estan_marcadas_en_las_paginas() -> None:
    """Antes de comprobar que nadie las esconde: que existan.

    Un `data-ensena` con una errata no da error en ningun sitio -- la
    pieza se pinta igual --, y el test de abajo pasaria porque no
    encuentra a nadie escondiendo un nombre que no existe. O sea que sin
    esto, el guardia se apaga solo con un dedo torcido.
    """
    marcadas = marcas_de_las_paginas()
    faltan = OBLIGATORIAS - marcadas
    assert not faltan, f"sin marcar en el HTML: {sorted(faltan)}"
    sobran = marcadas - OBLIGATORIAS
    assert not sobran, (
        f"marcadas pero no declaradas obligatorias: {sorted(sobran)}. "
        f"O entran en OBLIGATORIAS, o se les quita el data-ensena.")


@pytest.mark.parametrize("hoja", sorted(HOJAS.glob("*.css")),
                         ids=lambda p: p.stem)
def test_ningun_tema_esconde_una_pieza_obligatoria(hoja: Path) -> None:
    """>>> EL QUE SUSTITUYE AL DE LA MAQUETA, Y EL QUE IMPORTA <<<

    El tema cambia COMO se ve, no QUE se ve. Un tema puede mover la
    puerta, cambiarle la letra, hacerla el doble de grande y ponerla de
    otro color; lo que no puede es dejar de enseñarla.

    Se mira por SELECTOR y no por captura de pantalla porque el fallo
    que hay que cazar es el de alguien limpiando una pantalla que le
    parece cargada -- un `display:none` sobre el crudo de la puerta
    "que asusta", o sobre el tercer boton "que confunde" --, y eso se
    escribe en el CSS: no se descubre mirando.

    LA UNICA EXCEPCION ES `<details>`, y esta acordada: `despacho` puede
    plegar el detalle tecnico del registro. Plegar no es esconder --
    sigue en el DOM y se abre con un clic --, y ademas eso lo decide
    `consola.html` en JavaScript y no una regla de aqui.
    """
    for selector, cuerpo in reglas(hoja):
        plano = cuerpo.replace("\n", " ").lower()
        if not any(forma in plano for forma in FORMAS_DE_ESCONDER):
            continue
        for pieza in OBLIGATORIAS:
            marca = f'[data-ensena="{pieza}"]'
            assert marca not in selector, (
                f"{hoja.name} esconde {pieza}:\n"
                f"  {selector.strip()} {{{cuerpo.strip()}}}\n"
                f"El tema cambia COMO se ve, no QUE se ve.")


@pytest.mark.parametrize("hoja", sorted(HOJAS.glob("*.css")),
                         ids=lambda p: p.stem)
def test_cada_hoja_de_tema_solo_pinta_su_tema(hoja: Path) -> None:
    """Una regla sin `[data-tema=...]` se aplicaria a los cuatro.

    Es el fallo de copiar una regla de una hoja a otra y olvidarse el
    prefijo: el tema `jarvis` -- el unico ya aceptado en pantalla, y el
    unico sin hoja propia -- empezaria a cambiar sin que nadie lo
    pidiera, y desde un archivo en el que nadie va a ir a buscar.
    """
    for selector, _ in reglas(hoja):
        limpio = selector.strip()
        if not limpio or limpio.startswith("@"):
            continue
        for uno in limpio.split(","):
            if not uno.strip():
                continue
            assert f'[data-tema="{hoja.stem}"]' in uno, (
                f"{hoja.name}: regla sin acotar al tema -> {uno.strip()!r}")


def test_las_hojas_de_maqueta_son_las_de_la_lista_blanca() -> None:
    """Una hoja que el servidor no sirve es una hoja muerta, y al reves.

    `jarvis` NO tiene hoja, y es deliberado: su maqueta es la de las
    propias paginas, y sin archivo no hay nada que pueda romperla por
    accidente.
    """
    from puente.consola import TEMAS

    hay = {p.stem for p in HOJAS.glob("*.css")}
    assert hay == set(TEMAS) - {"jarvis"}, (
        f"hojas en disco {sorted(hay)} contra temas {sorted(TEMAS)}")

# --- 3. LA TOKENIZACION NO SE PUEDE DESHACER SOLA -------------------------


@pytest.mark.parametrize("pagina", [CONSOLA, AJUSTES], ids=["consola", "ajustes"])
def test_no_quedan_colores_a_pelo_en_el_html(pagina: Path) -> None:
    """>>> EL PASO 0 DE LOS TEMAS, CON GUARDIA <<<

    El 2026-08-28 se sacaron 113 literales de `consola.html` y 47 de
    `ajustes.html`. Un literal nuevo no rompe nada hoy: se ve bien en el
    tema en el que se escribio, y aparece descolgado en los otros tres
    -- que es justo el fallo que nadie prueba, porque uno mira el tema
    que esta usando.
    """
    texto = pagina.read_text(encoding="utf-8")
    literales = re.findall(r"#[0-9A-Fa-f]{3,8}\b|rgba?\((?!var)[^()]*\)", texto)
    assert not literales, f"colores a pelo en {pagina.name}: {sorted(set(literales))}"


@pytest.mark.parametrize("pagina", [CONSOLA, AJUSTES], ids=["consola", "ajustes"])
def test_las_dos_paginas_enlazan_la_MISMA_paleta(pagina: Path) -> None:
    """Los ajustes viven en un `iframe`: documento aparte, que no hereda
    ni una variable del padre. Sin este `<link>`, la pestaña de ajustes
    se quedaria con el tema de siempre mientras la consola cambia."""
    texto = pagina.read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="/tema.css">' in texto
    assert "__ATRIBUTOS__" in texto, "el <html> ya no admite el tema"


# --- 4. EL SERVIDOR Y EL CSS TIENEN QUE HABLAR DEL MISMO CONJUNTO ---------


def test_la_lista_blanca_del_servidor_y_el_css_coinciden() -> None:
    from puente.consola import TEMAS

    assert set(TEMAS) == set(bloques()), (
        "un tema que este en un sitio y no en el otro no se puede elegir, "
        "o se estampa sin comprobar")


def test_el_ajuste_ofrece_exactamente_esos_temas() -> None:
    from nucleo.ajustes import catalogo
    from puente.consola import TEMAS

    tema = next(a for a in catalogo() if a.clave == "ui.tema")
    assert [o["valor"] for o in tema.opciones] == list(TEMAS)
    # Se aplica al momento y hay que decirlo: prometer un reinicio que no
    # hace falta es la pantalla mintiendo en la direccion contraria.
    assert tema.aplica == "ya"


# --- 5. LO QUE SE ESTAMPA DENTRO DE NUESTRO HTML -------------------------


def test_un_tema_desconocido_NO_se_estampa(tmp_path, monkeypatch) -> None:
    """El valor sale de un YAML que el usuario puede editar a mano.

    Sin lista blanca, un valor con comillas cerraria el atributo y
    abriria una etiqueta DENTRO de la consola -- que es la pantalla desde
    la que se aprueba lo que Claude Code hace sobre la PC.
    """
    from puente import consola as mod
    from puente.consola import Consola
    from puente.sesion import Sesion

    c = Consola(Sesion(tmp_path), puerto=1)
    monkeypatch.setattr(mod, "valor_de", None, raising=False)

    import nucleo.ajustes as aj

    monkeypatch.setattr(aj, "valor_de",
                        lambda *a, **k: '"><script>malo</script>')
    atributos = c.atributos_del_html()
    assert "script" not in atributos
    assert atributos == ' lang="es"'


def test_el_tema_de_siempre_no_estampa_nada(tmp_path, monkeypatch) -> None:
    """`jarvis` es `:root`. Sin atributo, una pagina servida por un
    Jarvis viejo -- o abierta desde disco -- se sigue pintando bien."""
    import nucleo.ajustes as aj
    from puente.consola import Consola
    from puente.sesion import Sesion

    monkeypatch.setattr(aj, "valor_de", lambda *a, **k: "jarvis")
    assert Consola(Sesion(tmp_path), puerto=1).atributos_del_html() == ' lang="es"'


def test_un_ajustes_roto_no_deja_la_consola_sin_servir(tmp_path, monkeypatch) -> None:
    """La consola es la pantalla desde la que se arregla un ajuste malo.

    Si un `ajustes.yaml` corrupto impidiera servirla, el usuario se
    quedaria sin la unica superficie donde corregirlo.
    """
    import nucleo.ajustes as aj
    from puente.consola import Consola
    from puente.sesion import Sesion

    def revienta(*a, **k):
        raise RuntimeError("yaml roto")

    monkeypatch.setattr(aj, "valor_de", revienta)
    assert Consola(Sesion(tmp_path), puerto=1).atributos_del_html() == ' lang="es"'


# --- 6. EL ICONO SIGUE AL TEMA, MENOS EN UNA COSA ------------------------


def test_cada_tema_tiene_su_icono_completo() -> None:
    from escritorio.icono import PALETAS

    esperado = {"listo", "escucha", "trabajando", "roto", "fondo"}
    for tema, paleta in PALETAS.items():
        assert set(paleta) == esperado, f"al icono de '{tema}' le falta algo"


def test_ROTO_es_el_mismo_rojo_en_los_cuatro() -> None:
    """>>> LA EXCEPCION, Y ES DELIBERADA <<<

    Los otros tres colores son identidad; este es una SEÑAL. Con Jarvis
    en la carpeta Inicio, el icono es la unica superficie donde enterarse
    de que el suelo no muerde. Un tema que lo pintara "en su gama"
    estaria eligiendo la estetica por encima de lo unico que no puede
    mentir.
    """
    from escritorio.icono import PALETAS

    rojos = {p["roto"] for p in PALETAS.values()}
    assert len(rojos) == 1, f"'roto' cambia de color entre temas: {rojos}"


def test_un_tema_que_no_existe_no_tumba_el_icono() -> None:
    """El icono es lo ultimo que puede dejar de dibujarse: es donde se
    lee que algo va mal."""
    from escritorio.icono import PALETAS, paleta_de

    assert paleta_de("inventado") == PALETAS["jarvis"]
    assert paleta_de(None) == PALETAS["jarvis"]


def test_los_temas_del_icono_son_los_del_css() -> None:
    from escritorio.icono import PALETAS

    assert set(PALETAS) == set(bloques())
