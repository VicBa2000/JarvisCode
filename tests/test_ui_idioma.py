"""El idioma de la PANTALLA: que traduzca, que no rompa y que se note.

QUE SE PRUEBA AQUI. Un traductor que sustituye dentro del archivo que se
sirve tiene exactamente dos formas de salir mal, y las dos son mudas:

  1. **traducir de menos** -- media pantalla en ingles y media en
     español. No da error, y la primera version de este archivo NO LO
     CAZO porque comparaba la pagina contra la lista de claves que yo
     mismo habia extraido: medía la extraccion. Ahora se BARRE la pagina
     servida entera, sin partir de ninguna lista nuestra;
  2. **traducir de mas** -- sustituir dentro del CODIGO. La copia y el JS
     viven en el mismo archivo, asi que una clave corta ("VOZ",
     "ESTADO") podria caer dentro de un identificador. Eso no se ve
     mirando la pagina: se ve cuando algo deja de responder. Se comprueba
     que el JS servido SIGUE SIENDO JS, parseandolo de verdad.

Y una tercera que no es del traductor sino de la promesa: el ajuste dice
"idioma de la PANTALLA" porque la voz NO cambia. Si algun dia alguien
quita ese matiz de la etiqueta, este archivo lo para.

>>> Y LA MITAD QUE FALTABA: EL TEXTO QUE FABRICA EL SERVIDOR <<<
Traducir los dos HTML deja fuera todo lo que la pagina PINTA a partir de
lo que le manda el servidor, y ahi vive el texto mas importante del
programa: el MOTIVO de una peticion de permiso. Lo lee el usuario justo
antes de autorizar, y ademas SE LOCUTA. La seccion 4 lo cubre.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import urllib.request
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
CONSOLA = RAIZ / "puente" / "consola.html"
AJUSTES = RAIZ / "puente" / "ajustes.html"


# --- utilidades ------------------------------------------------------------


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def en_ingles(tmp_path, monkeypatch):
    """Los ajustes puestos en ingles, sin tocar los del usuario."""
    import nucleo.textos as mod

    monkeypatch.setattr(mod, "idioma", lambda *a, **k: "en")
    return mod


def servida(ruta: str, tmp_path) -> str:
    from puente.consola import Consola
    from puente.sesion import Sesion

    c = Consola(Sesion(tmp_path), puerto=puerto_libre())
    c.servir(abrir_navegador=False)
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{c.puerto}{ruta}", timeout=10) as r:
            return r.read().decode("utf-8")
    finally:
        c.parar()


# --- 1. QUE TRADUZCA, Y CUANTO ---------------------------------------------


def test_las_dos_paginas_salen_en_ingles(en_ingles, tmp_path) -> None:
    consola = servida("/", tmp_path)
    ajustes = servida("/ajustes", tmp_path)

    assert '<html lang="en"' in consola
    assert '<html lang="en"' in ajustes
    # Una de cada clase: un rotulo del HTML y un literal del JS.
    assert ">TRANSMISSION LOG<" in consola
    assert '"Asking permission to "' in consola
    assert ">SAVE<" in ajustes
    assert '"Saved and applied."' in ajustes


def test_en_español_no_se_toca_ni_un_byte(tmp_path) -> None:
    """>>> EL IDIOMA DE SERIE NO PASA POR EL TRADUCTOR <<<

    Es lo que hace que añadir ingles no pueda estropear el español: si
    `traducir_pagina` se equivocara, el que lo tiene puesto no se entera
    nunca. La pagina en español tiene que salir tal cual esta en disco,
    salvo los dos huecos que rellena el servidor.
    """
    from nucleo.textos import traducir_pagina

    crudo = (RAIZ / "puente" / "consola.html").read_text(encoding="utf-8")
    assert traducir_pagina(crudo, "es") == crudo


def test_no_queda_espanol_en_la_pagina_servida(en_ingles, tmp_path) -> None:
    """>>> ESTE TEST SUSTITUYE A UNO QUE SE MEDIA A SI MISMO <<<

    La primera version comparaba la pagina contra LA LISTA DE CLAVES QUE
    YO MISMO HABIA EXTRAIDO, dio 198/200, y estaba mal: medía la
    extraccion, no la pagina. Lo que la extraccion no vio -- los
    atributos `title` y `placeholder`, los parrafos largos que el patron
    no casaba -- salio en español y la cifra siguio diciendo 99 %. Lo
    reporto el usuario mirandolo: cambio la pantalla de espanol a ingles y
    aun quedaron partes en espanol. Es la trampa de siempre: una
    sonda que construia su propia entrada.

    Esta version no parte de ninguna lista nuestra: recorre la pagina
    SERVIDA entera -- nodos de texto, atributos visibles y literales de
    JS -- y busca palabras que solo existen en español.
    """
    marcas = re.compile(
        r"\b(el|la|los|las|un|una|del|que|qué|con|sin|por|para|como|"
        r"cuando|donde|pero|porque|su|sus|esta|este|esa|ese|hay|son|"
        r"tiene|tienen|puede|pueden|hacer|dice|decir|mirar|aqui|ahora|"
        r"todo|todos|toda|todas|mas|muy|solo|cada|otro|otra|nada|algo|"
        r"desde|hasta|entre|sobre|antes|despues|ajustes|guardar|carpeta|"
        r"archivo|pantalla|idioma|ninguno|ninguna|abierto|cerrado|"
        r"escuchando|apagado|encendido|sesion|palabra|permiso|permisos|"
        r"ordenes|salida|entrada|estado|prueba|probar|fallo|listo|lista|"
        r"nuevo|nueva|primero|primera)\b",
        re.IGNORECASE)

    # Lo que la red pesca y NO es español. Se listan de una en una a
    # proposito: una lista corta y explicita se revisa; un filtro
    # inteligente esconderia lo que de verdad falte.
    PERMITIDO = {
        "config/ajustes.yaml",   # un nombre de archivo
        "start it with --voz",   # `--voz` es la bandera de verdad
        "no server", "NO FLOOR", "NO VOICE", "no token yet",
        "The user said no.", "None declared, so no MCP can act.",
        "  (no longer connected)", "   (no longer there)",
        "Session cap", "STATE", "STATE —/06",
    }

    quedan = []
    for ruta in ("/", "/ajustes"):
        html = servida(ruta, tmp_path)
        cuerpo = re.sub(r"<style>.*?</style>|<script>.*?</script>|<!--.*?-->",
                        "", html, flags=re.DOTALL)
        visibles = [re.sub(r"\s+", " ", x).strip()
                    for x in re.findall(r">([^<>]+)<", cuerpo)]
        for attr in ("title", "placeholder", "aria-label", "alt"):
            visibles += re.findall(attr + r'="([^"]+)"', html)
        for texto in visibles:
            if texto and texto not in PERMITIDO and marcas.search(texto):
                quedan.append(f"{ruta}: {texto[:70]!r}")
    assert not quedan, "sigue en español:\n  " + "\n  ".join(quedan)


def test_ningun_ROTULO_se_queda_sin_traduccion() -> None:
    """>>> LA SEGUNDA VEZ QUE LA MEDICION SE QUEDO CORTA <<<

    El barrido de arriba busca PALABRAS ESPAÑOLAS, y por eso se dejo los
    seis estados del ciclo de voz. Lo vio el usuario: con el idioma en
    ingles todo habia cambiado menos ellos -- seguia leyendo DORMIDO. El detector los
    habia descartado solos, porque una cadena de solo letras parecia un
    identificador -- y en un archivo con HTML, CSS y JS mezclados casi
    siempre lo es.

    Este no adivina idioma: usa una regla ESTRUCTURAL. En este codigo
    los identificadores son minusculas o camelCase (`div`, `checkbox`,
    `tgResultado`), asi que **un literal de solo letras que empiece por
    mayuscula es copia hasta que se demuestre lo contrario**. Lo que no
    lo sea se declara aqui abajo, de uno en uno: una lista corta que
    obliga a DECIDIR cuando aparece algo nuevo es lo contrario de un
    filtro listo que se lo traga en silencio.
    """
    import re as _re

    from nucleo.textos import PAGINAS_EN

    # Cadenas que empiezan por mayuscula y NO son copia. Casi todas son
    # el `clase` de un evento del puente, que la pagina COMPARA: si
    # alguien las tradujera, el flujo dejaria de pintar ese evento y no
    # habria error en ningun sitio.
    NO_ES_COPIA = {
        # nombres de clase de evento (`puente/protocolo.py`)
        "Texto", "Pensamiento", "UsoHerramienta", "ResultadoHerramienta",
        "Puerta", "Pregunta", "Resuelta", "RespuestaDelUsuario",
        "Reintento", "Limite", "Fin", "SinPuerta", "Caida",
        "TurnoDelUsuario", "FinDelFlujo",
        # Las dos que viajan por el mismo cable y NO son eventos: dicen
        # como estan las cosas AHORA (el cabezal y la tira). La pagina
        # las COMPARA en el mismo `switch`, asi que traducirlas dejaria
        # el panel congelado y sin un solo error.
        "Tarea", "Producido",
        # El POV: el fotograma de ahora y lo que se le añade. Mismo caso
        # -- la pagina los COMPARA en el `switch`.
        "Plano", "Cuadro",
        # Lo que el ARRANQUE esta haciendo mientras el POST sigue
        # bloqueado (2026-09-03). Es una clase mas del `switch`: lo que
        # se traduce es su `motivo`, que viaja por `CLAVES_DE_TEXTO`.
        "Aviso",
        # nombres propios y del DOM/HTTP
        "Jarvis", "JARVIS", "Enter", "Inicio", "POST", "GET", "Content",
        # `DOC` e `IMG` son las mismas tres letras en los dos idiomas, y
        # `Escape` es la tecla, no una palabra.
        "DOC", "IMG", "Escape",
    }

    faltan = []
    for pagina in (CONSOLA, AJUSTES):
        texto = pagina.read_text(encoding="utf-8")
        js = " ".join(_re.findall(r"<script>(.*?)</script>", texto,
                                  flags=_re.DOTALL))
        # Fuera los comentarios ANTES de mirar: un `// menu "Ajustes"`
        # que explica algo no es copia, y contarlo mandaria a traducir un
        # comentario. Lo señalo este mismo test nada mas estrenarse.
        js = _re.sub(r"/\*.*?\*/", " ", js, flags=_re.DOTALL)
        js = _re.sub(r"(?m)//[^\n]*", " ", js)
        for cadena in _re.findall(r'"([A-Za-zÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]{2,})"'
                                 + "|"
                                 + r"'([A-Za-zÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]{2,})'",
                                 js):
            s = cadena[0] or cadena[1]
            if not s or not (s[0].isupper() or s.isupper()):
                continue
            if s in NO_ES_COPIA or s in PAGINAS_EN:
                continue
            faltan.append(f"{pagina.name}: {s!r}")
    assert not faltan, (
        "rotulos sin traduccion (o sin declarar como no-copia): "
        + ", ".join(sorted(set(faltan))))


def test_una_frase_QUE_SE_ARMA_EN_EL_NAVEGADOR_va_entera(en_ingles,
                                                        tmp_path) -> None:
    """>>> EL ORDEN DE LAS PALABRAS NO SE PUEDE TRADUCIR A TROZOS <<<

    El cabezal de la tira dice cuanto hace del ultimo turno, y esa frase
    lleva un numero dentro que solo existe en el navegador. La forma
    obvia -- traducir un `"hace "` suelto y concatenarle "4 min" -- sale
    mal en ingles y NO LA VE NADIE: el ingles lo dice al reves ("4 min
    ago"), asi que quedaria "ago 4 min" en una cadena que ningun test
    mira, porque no esta en el HTML servido sino armada en marcha.

    La salida es mandar la plantilla ENTERA con su hueco, y que la pagina
    sustituya. Este test existe para que nadie la parta en dos.
    """
    html = servida("/", tmp_path)
    assert '"%s ago"' in html, "la plantilla no llego traducida"
    assert '"hace %s"' not in html
    # Fuera los comentarios antes de mirar: el de esta misma funcion
    # NOMBRA el trozo que prohibe, y explicar la trampa no puede hacer
    # saltar la trampa. Es la misma correccion que ya se le hizo al test
    # de los rotulos nada mas estrenarse.
    sin_notas = re.sub(r"/\*.*?\*/", " ", html, flags=re.DOTALL)
    sin_notas = re.sub(r"(?m)^\s*//.*$", " ", sin_notas)
    assert '"hace "' not in sin_notas, (
        "partida en trozos: en ingles saldra al reves")


def test_lo_que_se_COMPARA_no_se_traduce() -> None:
    """>>> EL RIESGO DEL LADO CONTRARIO, Y ROMPE DE VERDAD <<<

    La pagina compara varias cadenas contra lo que manda el servidor:
    `tarea_origen === "claude"`, `zona.eje === "privada"`,
    `estado === "roto"`, y las tres politicas de MCP que se GUARDAN tal
    cual. Traducir cualquiera de esas no deja media pantalla en español:
    deja una funcion que ya no hace nada, y sin error.
    """
    from nucleo.textos import PAGINAS_EN

    intocables = {"claude", "privada", "roto", "listo", "auto", "confirmar",
                  "prohibido", "entrada", "salida", "mal", "ok", "duda",
                  "bien", "mirar", "nada"}
    tocadas = intocables & set(PAGINAS_EN)
    assert not tocadas, (
        f"estas se comparan o se guardan, no son copia: {sorted(tocadas)}")


def test_los_SEIS_estados_del_ciclo_tienen_nombre_en_ingles() -> None:
    """Los seis de JC-0011, por nombre. Es lo que reporto el usuario, y
    va con nombre propio para que se vea si vuelve a faltar uno."""
    from nucleo.textos import PAGINAS_EN

    for estado in ("DORMIDO", "AVISANDO", "ESCUCHANDO", "TRABAJANDO",
                   "HABLANDO", "PREGUNTANDO"):
        assert estado in PAGINAS_EN, f"el estado {estado} no se traduce"


def test_los_botones_de_la_PUERTA_estan_traducidos() -> None:
    """Es lo que el usuario PULSA para consentir (JC-0002). Se escaparon
    del primer barrido por lo mismo que los estados."""
    from nucleo.textos import PAGINAS_EN

    assert PAGINAS_EN["Permitir"] == "Allow"
    assert PAGINAS_EN["Denegar"] == "Deny"
    # Y la tercera salida sigue siendo una salida, no un "no".
    assert PAGINAS_EN["No contestar ahora"] == "Don't answer now"


def test_el_catalogo_de_ajustes_sale_entero_en_ingles(en_ingles) -> None:
    from nucleo.ajustes import por_grupos

    grupos = por_grupos()
    assert [g["titulo"] for g in grupos] == [
        "The screen", "To get started", "Hearing and speaking", "Advanced"]
    sin_traducir = []
    for g in grupos:
        for a in g["ajustes"]:
            for campo in ("etiqueta", "ayuda", "aviso"):
                if not a[campo]:
                    continue
                # Marcadores de español que no aparecen en ingles.
                if re.search(r"\b(que|los|las|para|con|del)\b", a[campo]):
                    sin_traducir.append(f"{a['clave']}.{campo}")
    assert not sin_traducir, f"ajustes en español: {sin_traducir}"


def test_los_nombres_de_dispositivo_NO_se_traducen(en_ingles) -> None:
    """>>> PRINCIPIO 7: LO EXTERNO ES CONTENIDO OBSERVADO <<<

    "Virtual Cable Out A1" lo escribio el fabricante del aparato.
    Traducirlo dejaria al usuario buscando en la lista de Windows un
    nombre que Windows no usa. Solo se traduce el alias NUESTRO.
    """
    from nucleo.ajustes import por_grupos

    oir = next(g for g in por_grupos() if g["clave"] == "oir")
    micro = next(a for a in oir["ajustes"] if a["clave"] == "voz.audio.entrada")
    etiquetas = [o["etiqueta"] for o in micro["opciones"]]
    assert any(e.startswith("Whichever Windows has set") for e in etiquetas)
    # Y ninguna otra ha sido tocada: siguen siendo lo que dice el sistema.
    from nucleo.ajustes import catalogo

    crudas = next(a for a in catalogo() if a.clave == "voz.audio.entrada")
    assert ([o["valor"] for o in micro["opciones"]]
            == [o["valor"] for o in crudas.opciones])


# --- 2. QUE NO ROMPA EL CODIGO ---------------------------------------------


@pytest.mark.parametrize("ruta", ["/", "/ajustes"], ids=["consola", "ajustes"])
def test_el_js_traducido_sigue_siendo_js(en_ingles, tmp_path, ruta) -> None:
    """>>> EL FALLO QUE NO SE VE MIRANDO LA PAGINA <<<

    El traductor sustituye DENTRO de literales de cadena, o sea dentro
    del codigo. Si una clave corta cayera en mitad de un identificador,
    la pagina se veria perfecta y algo dejaria de funcionar al pulsarlo.
    Asi que se parsea de verdad, con el motor de JS que hay en la
    maquina, en vez de mirarlo a ojo.
    """
    node = subprocess.run(["node", "--version"], capture_output=True)
    if node.returncode != 0:
        pytest.skip("no hay node para parsear el JS")

    html = servida(ruta, tmp_path)
    trozos = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
    assert trozos, "la pagina servida se quedo sin JS"
    for i, js in enumerate(trozos):
        archivo = tmp_path / f"trozo_{i}.js"
        archivo.write_text(js, encoding="utf-8")
        r = subprocess.run(
            ["node", "--check", str(archivo)], capture_output=True, text=True)
        assert r.returncode == 0, f"JS roto en {ruta}: {r.stderr[:400]}"


def test_la_ficha_no_pasa_por_el_traductor(en_ingles, tmp_path) -> None:
    """La ficha es un secreto aleatorio: se mete DESPUES de traducir.

    Si entrara antes, el traductor la veria como una cadena mas. La
    probabilidad de tocarla es ridicula, pero "ridicula" no es "cero" y
    aqui no hace falta que lo sea.
    """
    from puente.consola import Consola
    from puente.sesion import Sesion

    c = Consola(Sesion(tmp_path), puerto=puerto_libre())
    c.servir(abrir_navegador=False)
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{c.puerto}/", timeout=10) as r:
            html = r.read().decode("utf-8")
        assert f'const FICHA = "{c.ficha}"' in html
    finally:
        c.parar()


# --- 3. LA PROMESA DE LA ETIQUETA ------------------------------------------


def test_el_ajuste_dice_que_es_SOLO_la_pantalla() -> None:
    """>>> SI ESTO SE AFLOJA, SE REABRE, NO SE ARREGLA EL TEST <<<

    Un "Idioma" a secas promete un Jarvis en ingles entero. La voz va
    medida contra grabaciones en español (JC-0018): quien lo pusiera se
    encontraria a Jarvis contestandole en español sin entender por que.
    """
    from nucleo.ajustes import catalogo

    a = next(x for x in catalogo() if x.clave == "ui.idioma")
    assert "pantalla" in a.etiqueta.lower()
    assert a.aviso and "voz" in a.aviso.lower()
    assert a.aplica == "ya"


def test_solo_hay_dos_idiomas_y_uno_es_el_de_serie() -> None:
    from nucleo.ajustes import catalogo
    from nucleo.textos import IDIOMAS

    a = next(x for x in catalogo() if x.clave == "ui.idioma")
    assert [o["valor"] for o in a.opciones] == list(IDIOMAS)
    assert a.por_defecto == "es"


def test_un_idioma_que_no_existe_cae_al_de_serie(monkeypatch) -> None:
    """Tres respuestas: es / en / no lo se. La tercera es `es`."""
    import nucleo.ajustes as aj
    from nucleo.textos import idioma

    monkeypatch.setattr(aj, "valor_de", lambda *a, **k: "klingon")
    assert idioma() == "es"

    def revienta(*a, **k):
        raise RuntimeError("yaml roto")

    monkeypatch.setattr(aj, "valor_de", revienta)
    assert idioma() == "es"


def test_la_bandeja_tambien_se_traduce(en_ingles) -> None:
    from nucleo.textos import texto

    assert texto("bandeja.salir", "Salir") == "Quit"
    assert texto("bandeja.abrir", "Abrir Jarvis") == "Open Jarvis"
    # Una clave que no existe se queda con el original, no revienta.
    assert texto("bandeja.inventada", "Original") == "Original"


# --- 4. EL TEXTO QUE FABRICA EL SERVIDOR ----------------------------------
# Esta seccion es la que faltaba y la que el usuario vio: la pagina
# traducida enseñando motivos en español.


def test_el_motivo_de_una_puerta_se_traduce(en_ingles) -> None:
    """>>> ES EL TEXTO MAS IMPORTANTE DEL PROGRAMA <<<

    "borra archivos" lo fabrica `puente/politica.py`, se pinta en la
    tarjeta de la puerta y es lo que el usuario lee ANTES de autorizar.
    Con la pantalla en ingles y esto en español, la pregunta se contesta
    a medias.
    """
    from nucleo.textos import mensaje

    assert mensaje("borra archivos", "en") == "deletes files"
    assert (mensaje("escribe fuera del directorio de la sesion", "en")
            == "writes outside the session directory")


def test_los_motivos_con_un_trozo_variable_dentro(en_ingles) -> None:
    """El nombre del servidor y la ruta los pone la accion, no nosotros:
    buscarlos por igualdad no casaria nunca."""
    from nucleo.textos import mensaje

    assert (mensaje("el servidor MCP 'shell' no esta en la lista blanca", "en")
            == "the MCP server 'shell' is not on the whitelist")
    assert (mensaje("C:/Privado es zona privada y no se toca", "en")
            == "C:/Privado is a private zone and is not touched")


def test_el_sufijo_del_SEGUNDO_windows_no_deja_el_motivo_a_medias(
        en_ingles) -> None:
    """>>> DOS PASADAS, Y POR ESO EXISTE ESTE TEST <<<

    El segundo Windows de `E:` -- el que una lista a mano habria dejado
    al descubierto -- pega ", en un Windows que NO es el que arranca" a
    un motivo que YA estaba en la tabla. Sin volver a mirar dentro, la
    mitad de las zonas de `E:` saldrian con el sufijo en ingles y el
    motivo en español.
    """
    from nucleo.textos import mensaje

    assert (mensaje("el sistema operativo, en un Windows que NO es el que "
                    "arranca", "en")
            == "the operating system, on a Windows that is NOT the one "
               "that boots")


def test_el_COSTE_de_una_zona_opcional_se_traduce(en_ingles) -> None:
    """El coste es lo que hace informada la eleccion del perimetro.
    Traducirlo a medias deja al usuario marcando una casilla sin saber
    que pierde."""
    from nucleo.textos import mensaje

    assert (mensaje("Jarvis no podra mirar ni organizar imagenes.", "en")
            == "Jarvis will not be able to look at or organise images.")
    assert mensaje("tus fotos", "en") == "your pictures"


def test_el_veredicto_de_probar_el_micro_se_traduce(en_ingles) -> None:
    """Quien lee esto esta averiguando por que no le oyen."""
    from nucleo.textos import mensaje

    assert (mensaje("Te oye. Ha llegado señal y ha encontrado habla.", "en")
            == "It hears you. Signal arrived and speech was found.")


def test_un_error_de_guardar_nombra_el_ajuste_QUE_SE_VE(en_ingles) -> None:
    """>>> SI NO, NOMBRA UNO QUE NO ESTA EN PANTALLA <<<

    El mensaje lleva dentro la ETIQUETA del ajuste. Con el catalogo
    crudo, un error en una pantalla en ingles nombraria el ajuste por su
    nombre español: el usuario no sabria cual de los que ve ha fallado.
    """
    from nucleo.ajustes import AjustesError, guardar

    with pytest.raises(AjustesError) as fallo:
        guardar({"ui.tema": "no_existe_este_tema"})
    dicho = str(fallo.value)
    assert "How it looks" in dicho, dicho
    assert "Como se ve" not in dicho


def test_todo_lo_que_sale_por_JSON_pasa_por_el_traductor(
        en_ingles, tmp_path) -> None:
    """>>> SE TRADUCE EN LA SALIDA, NO EN CADA SITIO <<<

    Hay una veintena de `return {"ok": False, "motivo": ...}` en
    `puente/consola.py`. Envolverlos uno a uno garantiza que el proximo
    se escriba sin envolver, y ese olvido no daria ningun error.
    """
    from puente.consola import Consola
    from puente.sesion import Sesion

    c = Consola(Sesion(tmp_path), puerto=puerto_libre())
    c.servir(abrir_navegador=False)
    try:
        pet = urllib.request.Request(
            f"http://127.0.0.1:{c.puerto}/estado",
            headers={"X-Jarvis-Ficha": c.ficha})
        with urllib.request.urlopen(pet, timeout=10) as r:
            estado = json.loads(r.read().decode("utf-8"))
    finally:
        c.parar()

    assert estado["suelo"]["motivo"] == (
        "this session is running without the JC-0007 floor")
    assert estado["voz"]["motivo"] == "started without --voz"


def test_una_ruta_dentro_de_una_clave_de_texto_sale_INTACTA(
        en_ingles, tmp_path) -> None:
    """La traduccion es una BUSQUEDA que devuelve la entrada cuando no
    encuentra nada, asi que traducir en la salida no puede estropear una
    ruta ni un nombre de servidor."""
    from puente.consola import traducir_salida

    ruta = r"C:\proyectos\faro\informe.pdf"
    dentro = traducir_salida({"motivo": ruta, "carpeta": ruta})
    assert dentro["motivo"] == ruta
    assert dentro["carpeta"] == ruta


# --- 5. LA COPIA DEL TEMA `despacho` ---------------------------------------
#
# >>> POR QUE ESTO VIVE EN EL ARCHIVO DEL IDIOMA Y NO EN EL DE TEMAS <<<
# Porque es el MISMO mecanismo -- sustituir cadenas dentro del archivo que
# se sirve -- y comparte sus dos formas de salir mal, las dos mudas. La
# diferencia es que aqui hay un tercer fallo posible que no existia con un
# solo diccionario: que las dos capas no compongan. La copia del tema corre
# primero, asi que si el ingles no conoce las frases NUEVAS, el tema
# despacho en ingles sale medio en español -- y nadie lo vería salvo quien
# use ese tema y ese idioma a la vez.


def test_solo_despacho_cambia_las_palabras() -> None:
    """Los otros tres temas se sirven con la copia intacta.

    `jarvis` sobre todo: es la unica pantalla que ya estaba aceptada por
    el usuario, y ni una palabra suya puede moverse desde aqui.
    """
    from nucleo.textos import COPIA_POR_TEMA, traducir_tema

    assert "jarvis" not in COPIA_POR_TEMA, (
        "jarvis no puede tener copia propia: es la pantalla ya aceptada")
    crudo = CONSOLA.read_text(encoding="utf-8")
    for tema in ("jarvis", "hacker", "nexo", None, "", "inventado"):
        assert traducir_tema(crudo, tema) == crudo, f"{tema} salio tocado"
    assert traducir_tema(crudo, "despacho") != crudo, "despacho no cambio nada"


def test_la_copia_de_despacho_casa_con_las_paginas() -> None:
    """Una clave que no case se sirve tal cual, y no da ningun error.

    Es el fallo de siempre de este mecanismo: se escribe la traduccion,
    no casa por una entidad HTML o un espacio, y el rotulo sigue diciendo
    "PERIMETRO" para siempre. Aqui se comprueba que las nueve entran.
    """
    from nucleo.textos import PANTALLA_DESPACHO, traducir_tema

    paginas = {p: p.read_text(encoding="utf-8") for p in (CONSOLA, AJUSTES)}
    juntas = "".join(paginas.values())
    despues = "".join(traducir_tema(t, "despacho") for t in paginas.values())
    sin_casar = [c for c, v in PANTALLA_DESPACHO.items()
                 if re.search(rf">\s*{re.escape(c)}\s*<", juntas)
                 and re.search(rf">\s*{re.escape(c)}\s*<", despues)]
    assert not sin_casar, f"claves que no llegaron a sustituir: {sin_casar}"


def test_despacho_en_ingles_no_se_queda_a_medias() -> None:
    """>>> EL FALLO QUE SOLO VE QUIEN USA LOS DOS A LA VEZ <<<

    La copia del tema corre ANTES que la del idioma. O sea que para
    cuando llega el traductor de ingles, el rotulo ya no dice
    "PERIMETRO": dice "Lo que no puede tocar". Si esa frase no esta en
    `PAGINAS_EN`, se sirve en español dentro de una pantalla inglesa.
    """
    from nucleo.textos import PAGINAS_EN, PANTALLA_DESPACHO

    faltan = [v for v in PANTALLA_DESPACHO.values() if v not in PAGINAS_EN]
    assert not faltan, (
        f"la copia de despacho no tiene ingles: {faltan}. "
        f"Van en PAGINAS_EN o ese tema sale bilingue.")


def test_el_js_sigue_siendo_js_con_la_copia_de_despacho(tmp_path) -> None:
    """Mismo riesgo que con el ingles: se sustituye dentro del codigo.

    Y aqui es MAS facil que pase, porque las claves de `despacho` son
    palabras cortas y en mayusculas ("CARGA", "CANALES") -- justo la
    forma que tiene un identificador o una constante.
    """
    node = subprocess.run(["node", "--version"], capture_output=True)
    if node.returncode != 0:
        pytest.skip("no hay node para parsear el JS")

    from nucleo.textos import traducir_pagina, traducir_tema

    for pagina in (CONSOLA, AJUSTES):
        # Las dos capas, en el orden real en que las aplica el servidor.
        html = traducir_pagina(
            traducir_tema(pagina.read_text(encoding="utf-8"), "despacho"), "en")
        trozos = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
        assert trozos, f"{pagina.name} se quedo sin JS"
        for i, js in enumerate(trozos):
            archivo = tmp_path / f"{pagina.stem}_{i}.js"
            archivo.write_text(js, encoding="utf-8")
            r = subprocess.run(["node", "--check", str(archivo)],
                               capture_output=True, text=True)
            assert r.returncode == 0, (
                f"JS roto en {pagina.name} con despacho+en: {r.stderr[:400]}")


def test_nada_visible_se_queda_IGUAL_al_traducir(en_ingles, tmp_path) -> None:
    """>>> LA TERCERA VEZ QUE LA MEDICION SE QUEDO CORTA (2026-09-09) <<<

    Y la mas cara, porque el usuario tenia Jarvis ENTERO en ingles y
    seguian saliendo en español la cabecera ("CUOTA·", "COSTE·", "SIN
    FRENO", "floor listo"), los rotulos del glosario ("dicha y escrita",
    "solo dicha") y **todos los interruptores, que decian SI**. Sus
    Lo que vio: una pagina de ajustes en ingles llena de interruptores
    que seguian contestando "SI".

    LOS DOS TESTS DE ARRIBA NO PODIAN VERLO, y por dos motivos distintos:

      * el primero **quita los bloques `<script>` antes de mirar**, asi
        que no comprueba ni un literal de JS -- y ahi viven casi todos
        los rotulos;
      * y busca por una LISTA DE PALABRAS españolas en la que no estaban
        "cuota", "coste", "freno" ni "dicha". Una red que solo pesca lo
        que ya conoce da un 99 % perfectamente creible.

    Este no sabe español. Sirve cada pagina en `es` y en `en` y enseña lo
    que NO CAMBIO: una cadena visible identica en los dos idiomas o esta
    traducida a si misma -- y entonces se declara abajo -- o es deuda.
    Es la misma idea que el senuelo del suelo: no preguntarle al sistema
    si funciona, sino ponerle algo que tenga que mover.
    """
    def visibles(html: str) -> set[str]:
        sin_estilo = re.sub(r"<style>.*?</style>|<!--.*?-->", "", html,
                            flags=re.DOTALL)
        cuerpo = re.sub(r"<script>.*?</script>", "", sin_estilo,
                        flags=re.DOTALL)
        fuera = [" ".join(t.split()) for t in re.findall(r">([^<>]{2,})<", cuerpo)]
        for attr in ("title", "placeholder", "aria-label", "alt"):
            fuera += [" ".join(t.split())
                      for t in re.findall(attr + r'="([^"]{2,})"', cuerpo)]
        for bloque in re.findall(r"<script>(.*?)</script>", sin_estilo,
                                 flags=re.DOTALL):
            limpio = re.sub(r"//[^\n]*", "", bloque)
            fuera += [" ".join(t.split())
                      for t in re.findall(r'"([^"\\n]{2,})"', limpio)
                      # >>> AQUI SE CUELA CODIGO Y HAY QUE ECHARLO <<<
                      # Emparejar comillas con una expresion regular se
                      # desalinea en cuanto hay un apostrofo o una
                      # comilla escapada, y lo que sale entonces es el
                      # TROZO DE CODIGO entre el cierre de un literal y
                      # la apertura del siguiente. Una frase de pantalla
                      # no lleva `;`, llaves, parentesis ni una suma.
                      # Un tokenizador seria lo correcto, y seria mas
                      # codigo que el test entero.
                      if not re.search(r"[;{}()\[\]=<>]|\+\s|\s\+", t)
                      # Y un fragmento suele EMPEZAR o ACABAR en un signo
                      # de codigo (`, vuelve:`, `? pr.ritual :`). Una
                      # frase de pantalla no empieza por coma.
                      and not re.match(r"^[\s,;:?]", t)
                      and not re.search(r"[?:,]\s*$", t)]
        return set(fuera)

    # Lo que legitimamente se escribe IGUAL en los dos idiomas. Cada una
    # se declara de una en una a proposito: obligar a decidir cuando
    # aparece algo nuevo es lo contrario de un filtro que se lo traga.
    IGUAL_EN_LOS_DOS = {
        # nombres propios, siglas y unidades
        "Jarvis", "Claude", "Claude Code", "MCP", "Telegram", "MIC", "POV",
        "hey jarvis", "git push", "1234567890:AA...", "@BotFather",
        "@userinfobot", "NO", "OK", "ESC", "USD",
        # Los mismos, escritos en mayusculas de rotulo. Y dos PREFIJOS
        # que no son prosa: "MCP·" va pegado a un recuento y "T+" a unos
        # minutos, o sea que no hay nada que traducir en ellos.
        "JARVIS", "TELEGRAM", "MCP·", "T+",
        # NOMBRES DE CLASE Y DE ESTADO, que la pagina COMPARA. Traducir
        # una de estas no da error: deja de aplicarse un estilo o de
        # pintarse un evento, y no hay nada que lo diga.
        "canal caido", "led off", "no espera", "resultado mal",
        "insignia apagado", "linea auto", "use strict",
        # el hueco de la ficha, que se sustituye en marcha
        "__FICHA__", "POST", "CORE ...... ",
    }

    quedan = []
    for ruta in ("/", "/ajustes"):
        # Las dos versiones de LA MISMA pagina, por el mismo camino.
        import nucleo.textos as _t

        en = visibles(servida(ruta, tmp_path))
        crudo = (RAIZ / "puente" /
                 ("consola.html" if ruta == "/" else "ajustes.html")
                 ).read_text(encoding="utf-8")
        es = visibles(_t.traducir_tema(crudo, "jarvis"))
        for texto in sorted(es & en):
            if texto in IGUAL_EN_LOS_DOS or re.match(r"^[\W\d\s]*$", texto):
                continue
            # Un identificador suelto no es copia: sin espacios y sin
            # mayusculas de rotulo, en este archivo casi siempre es un
            # id, una etiqueta o una variable CSS.
            if " " not in texto and not texto.isupper():
                continue
            if texto.startswith(("var(", "#", ".", "--")) or "/" in texto:
                continue
            quedan.append(f"{ruta}: {texto[:70]!r}")

    assert not quedan, (
        "se quedan IGUAL al traducir, o sea sin traducir:\n  "
        + "\n  ".join(quedan))
