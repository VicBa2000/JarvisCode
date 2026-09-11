"""Capturas de la consola con piezas dentro, en los cuatro temas.

    python -m eval.mirar_el_panel [--tema jarvis] [--puerto 8799]

>>> POR QUE ESTO EXISTE, Y ES LA LECCION MAS CARA DEL 29 <<<
Una suite verde no dice que la pantalla este bien. El 2026-08-29 los 974
tests pasaban con CUATRO fallos visibles encima -- `.barra` significaba
dos cosas distintas en las dos paginas, las columnas del nucleo estaban
al reves en dos temas, un centrado estaba INLINE (o sea intocable por un
tema) y `header` existia tambien en los ajustes. Ninguno lo cazo un test;
los cuatro se cazaron mirando capturas contra el servidor real.

El panel de piezas es exactamente el mismo riesgo: es marcado nuevo en el
rail y un visor a pantalla completa, y el test de temas solo comprueba
que ninguna hoja los ESCONDA, no que se vean bien.

MONTA UNA SESION POSTIZA A PROPOSITO: no hace falta Claude Code para
mirar una pantalla, y arrancar el binario de 337 MB para esto seria pagar
un turno por una captura. Las piezas se inyectan como las produce la
sesion de verdad -- por sus eventos, no tocando la lista por dentro --,
que es lo unico que hace que la captura ensene lo que se vera.
"""

from __future__ import annotations

import argparse
import base64
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from dataclasses import replace
from pathlib import Path

from eval.captura import captura
from puente.producido import Producido
from puente.protocolo import Imagen, ResultadoHerramienta, UsoHerramienta

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
TEMAS = ("jarvis", "hacker", "despacho", "nexo")
SALIDA = Path("logs") / "capturas"


def _png(ancho: int, alto: int) -> bytes:
    """Un PNG de verdad, hecho a mano. Sin Pillow: el `.venv` no lo tiene
    seguro y esto solo necesita que el navegador pinte ALGO."""
    filas = b"".join(
        b"\x00" + b"".join(bytes([(x * 7 + y * 3) % 256, (x * 3) % 256, 180])
                           for x in range(ancho))
        for y in range(alto))

    def trozo(tipo: bytes, datos: bytes) -> bytes:
        return (struct.pack(">I", len(datos)) + tipo + datos
                + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF))

    cabecera = struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", cabecera)
            + trozo(b"IDAT", zlib.compress(filas)) + trozo(b"IEND", b""))


def _init_de_verdad():
    """El `system/init` de la sesion donde `blender` NO arranco.

    Copiado literal de `logs/puente/` a `mcp_uno_caido.jsonl`:
    es el unico sitio donde hay un servidor realmente caido, y `logs/` no
    se versiona. Inventar aqui un `failed` mediria esta sonda.

    Trae los CUATRO casos de una vez, que es justo lo que hay que mirar:
    uno caido (rojo), uno listo, y tres `needs-auth` que NO son un fallo.
    """
    from puente.protocolo import Inicio, interpretar

    traza = (Path(__file__).resolve().parent / "trazas_claude_code"
             / "mcp_uno_caido.jsonl")
    for linea in traza.read_text(encoding="utf-8").splitlines():
        for evento in interpretar(linea):
            if isinstance(evento, Inicio):
                return evento
    return None


def _cuota_de_verdad():
    """El ultimo `rate_limit_event` de la traza, interpretado de verdad.

    Va por `interpretar` y no construyendo un `Limite` a mano a proposito:
    lo que fallaba era justo el PARSEO -- el campo del que se leia ya no
    viene --, asi que una captura que se saltara esa parte volveria a
    ensenar un numero que la sesion real no produce.
    """
    from puente.protocolo import Limite, interpretar

    traza = (Path(__file__).resolve().parent / "trazas_claude_code"
             / "cuota_dos_relojes.jsonl")
    for linea in traza.read_text(encoding="utf-8").splitlines():
        for evento in interpretar(linea):
            if isinstance(evento, Limite):
                return _con_el_reloj_al_dia(evento)
    return None


def _con_el_reloj_al_dia(limite):
    """La misma cuota, con sus dos relojes puestos en el futuro.

    >>> Y ESTO ESTABA ROTO DESDE EL 2026-09-04, SIN DAR ERROR <<<
    Esta funcion existe desde el 09-03 para que la CARGA se capture "con
    sus numeros y su 'vuelve a las...'", y al dia siguiente entro
    `Ventana.caducada`: una traza de hace tres dias esta CADUCADA hoy, o
    sea que desde entonces las capturas del panel enseñaban un "?" y
    ninguna barra. La pantalla hacia lo correcto; la sonda dejo de mirar
    lo que decia mirar, y como el "?" es un estado legitimo no habia nada
    que pareciera un fallo.
    Se mueve el RELOJ y nada mas: las cifras son las del disco.
    """
    dentro_de_una_hora = int(time.time()) + 3600
    en_tres_dias = int(time.time()) + 3 * 24 * 3600
    return replace(
        limite,
        sesion=(replace(limite.sesion, reinicia_en=dentro_de_una_hora)
                if limite.sesion else None),
        semana=(replace(limite.semana, reinicia_en=en_tres_dias)
                if limite.semana else None))


def _cuota_pasada_de_cien():
    """La ventana del 107 %, para poder MIRAR como se pinta.

    (2026-09-07.) Sale de `cuota_pasada_de_cien.jsonl`, que es el evento
    literal de `logs/puente/`: en 363 eventos reales esto ha pasado UNA
    vez, o sea que esperar a que vuelva a pasar para verlo en pantalla no
    es un plan. La barra no puede crecer mas alla del borde, asi que
    pasado el 100 el dibujo se queda quieto mientras la cifra sigue
    subiendo -- y eso solo se ve mirandolo.
    """
    from puente.protocolo import Limite, interpretar

    traza = (Path(__file__).resolve().parent / "trazas_claude_code"
             / "cuota_pasada_de_cien.jsonl")
    for linea in traza.read_text(encoding="utf-8").splitlines():
        for evento in interpretar(linea):
            if isinstance(evento, Limite) and evento.sesion                     and evento.sesion.porcentaje > 100:
                # >>> SE LE MUEVE EL RELOJ, Y SOLO EL RELOJ <<< La cifra
                # es la del disco y no se toca. Lo que hay que cambiar es
                # `reinicia_en`: la traza es del 09-04, o sea que hoy esa
                # ventana esta CADUCADA y la pantalla escribe "?" -- bien
                # hecho, y justo lo que impide ver como se pinta un 107.
                # Es la diferencia entre inventar el dato (que mediria la
                # sonda) y ponerlo en su momento para poder mirarlo.
                return _con_el_reloj_al_dia(evento)
    return None


class SesionPostiza:
    """Lo justo para que la consola pinte. No abre nada."""

    def __init__(self, directorio: str) -> None:
        self.directorio = directorio
        self.viva = True
        self.session_id = "captura"
        self.modelo = "sonnet"
        self.modo_permisos = "default"
        self.pendientes: tuple = ()
        self.pregunta_abierta = None
        self.reintentando = None
        # >>> LA CUOTA, Y SALE DE UN EVENTO REAL <<< Con `None` la CARGA
        # se captura entera en "?", que es el estado honesto pero no el
        # que hay que mirar: lo que se rehizo el 2026-09-03 son los DOS
        # relojes con sus numeros y su "vuelve a las...". Se replica la
        # primera linea de `cuota_dos_relojes.jsonl`, copiada a su vez de
        # `logs/puente/`: una cuota inventada aqui mediria esta
        # sonda y no la pantalla.
        self.limite = _cuota_de_verdad()
        self.fallo = None
        self.ultimo_evento_en = time.time()
        # `Consola.estado` lo lee, y sin el la peticion revienta ENTERA:
        # `/estado` deja de contestar, la pagina se queda en "conectando"
        # y el panel sale vacio. Costo una captura descubrirlo, que es
        # justamente para lo que existe esta sonda.
        self.silencio_s = 0.4
        self.mcp_vistos: set = set()
        self.servidores_mcp: tuple = ()
        # >>> Y EL `init`, QUE ES LO QUE PINTA LOS SERVIDORES MCP <<<
        # `Consola._mcp` lo lee sin `getattr`: en una `Sesion` de verdad
        # ese campo existe desde el `__init__`, asi que tolerarlo ausente
        # aqui solo serviria para que esta sonda dejara de parecerse a lo
        # que captura. Sin el, `/estado` revienta ENTERA y la captura
        # sale en "conectando" -- el mismo fallo que costo una captura
        # con `silencio_s`.
        self.inicio = _init_de_verdad()
        self.zonas: tuple = ()

    def eventos(self, timeout=None):
        return iter(())

    def cerrar(self) -> None:
        pass


def _con_piezas(producido: Producido, carpeta: Path) -> None:
    """Las mete COMO LAS PRODUCE LA SESION, por sus eventos.

    Y en un ORDEN que se parezca a un turno de verdad, porque la v3 no
    ensena un estado sino una SECUENCIA: un documento, un binario, un
    render que se suelta por peso, otro documento y el render de ahora.
    """
    (carpeta / "estado.md").write_text(
        "# Estado del proyecto\n\n"
        "El panel va por la v3: una tira que corre y un cabezal que late.\n"
        "Lo que queda es oirlo hablando, que no lo puede hacer el agente.\n",
        encoding="utf-8")
    doc = carpeta / "resumen-del-proyecto.md"
    doc.write_text(
        "# Resumen del proyecto\n\n"
        "JarvisCode es un fork cuyo cerebro es Claude Code. La capa de voz\n"
        "sigue siendo local: wake word, VAD, STT y TTS corren en la maquina.\n\n"
        "## Lo que hay hoy\n\n"
        "- El puente, con su puerta y su suelo.\n"
        "- La consola en 127.0.0.1, con cuatro temas.\n"
        "- La voz conectada de punta a punta.\n", encoding="utf-8")
    binario = carpeta / "escena.blend"
    binario.write_bytes(b"BLENDER" + b"\x00" * 400)
    notas = carpeta / "notas.txt"
    notas.write_text(
        "Lo que queda, y es del usuario:\n\n"
        "1. Oirlo hablando. El agente no puede.\n"
        "2. La campana de JC-0011, pendiente desde el 25.\n"
        "3. El banco en ingles de JC-0018.\n", encoding="utf-8")

    def archivo(i: int, ruta: Path) -> None:
        producido.ve(UsoHerramienta(id_uso=f"u{i}", herramienta="Write",
                                    entrada={"file_path": str(ruta)}))
        producido.ve(ResultadoHerramienta(id_uso=f"u{i}", contenido="",
                                          es_error=False))

    def render(i: int, ancho: int, alto: int) -> None:
        """Como la que devuelve `get_viewport_screenshot` del MCP."""
        producido.ve(ResultadoHerramienta(
            id_uso=f"i{i}", contenido="", es_error=False,
            imagenes=(Imagen(tipo="image/png",
                             datos=base64.b64encode(_png(ancho, alto)).decode()),)))

    archivo(0, doc)
    archivo(1, binario)
    render(0, 320, 180)

    # >>> Y AQUI SE FUERZA UNA LAPIDA <<<
    # `Producido` suelta los bytes de las imagenes mas viejas al llegar a
    # 24 MB, y en una tira ese hueco hay que VERLO: un salto callado en
    # una secuencia dice que ese trabajo no ocurrio. Con 24 MB de verdad
    # harian falta cien capturas para mirar esta pantalla, asi que se
    # baja el tope -- es el mismo camino, `_podar_imagenes`. Al tamaño
    # justo de UNA: la vieja se suelta y la de ahora sigue viva, que es
    # el caso que hay que mirar. Con el tope a 1 se soltaban las dos y la
    # tira acababa en una lapida grande y vacia -- se vio en la captura,
    # que es exactamente para lo que sirve.
    producido.tope_imagenes = len(_png(360, 200))
    archivo(2, notas)
    render(1, 360, 200)

    # Un `Write` DENEGADO: no tiene que aparecer en la captura.
    producido.ve(UsoHerramienta(id_uso="ux", herramienta="Write",
                                entrada={"file_path": "C:/no/sale.txt"}))
    producido.ve(ResultadoHerramienta(id_uso="ux", contenido="",
                                      es_error=True))


def _con_registro(consola) -> None:
    """Pinta en el flujo los eventos de un turno REAL.

    Se reproducen los `assistant`/`user` de `logs/sondas/pov.jsonl` por
    el mismo camino que la pagina: `_difundir(a_json(evento))`. Asi la
    captura enseña los renglones tal como se veran, incluido el resumen
    de cada herramienta.
    """
    from puente.consola import a_json
    from puente.protocolo import (ResultadoHerramienta, Texto, UsoHerramienta,
                                  interpretar)

    traza = Path("logs/sondas/pov.jsonl")
    if not traza.is_file():
        return
    for linea in traza.read_text(encoding="utf-8").splitlines():
        for evento in interpretar(linea):
            if isinstance(evento, (UsoHerramienta, ResultadoHerramienta, Texto)):
                consola._difundir(a_json(evento))


def _con_pov(consola, hasta: str = "escribiendo") -> None:
    """Deja la camara a mitad de un `Write`, con LA TRAZA REAL.

    >>> NO SE INVENTAN LOS EVENTOS <<<
    Una captura montada sobre trozos escritos a mano enseñaria lo que yo
    creo que llega, no lo que llega. Se reproduce `logs/sondas/pov.jsonl`,
    que salio de `claude` de verdad, y se para en mitad del documento --
    que es el fotograma que hay que mirar.
    """
    from puente.protocolo import interpretar

    traza = Path("logs/sondas/pov.jsonl")
    if not traza.is_file():
        print("  (sin logs/sondas/pov.jsonl: el POV saldra vacio. "
              "Correr -m eval.sondas_claude_code.sonda_pov)")
        return
    parar = False
    for linea in traza.read_text(encoding="utf-8").splitlines():
        for evento in interpretar(linea):
            cambio = consola.camara.ve(evento)
            if cambio is not None:
                consola._difundir(cambio)
            plano = consola.camara.plano
            # A mitad: con bastante texto para que se vea, y sin cerrar.
            if (plano is not None and plano.que == hasta
                    and len(plano.texto) > 420):
                parar = True
                break
        if parar:
            break


def main(argv: list[str] | None = None) -> int:
    trozos = argparse.ArgumentParser(description=__doc__)
    trozos.add_argument("--puerto", type=int, default=8799)
    trozos.add_argument("--tema", default="", help="uno solo; vacio = los 4")
    args = trozos.parse_args(argv)

    if not EDGE.is_file():
        print(f"No esta Edge en {EDGE}. Sin navegador no hay captura.")
        return 2

    from puente.consola import Consola

    SALIDA.mkdir(parents=True, exist_ok=True)
    temas = (args.tema,) if args.tema else TEMAS
    with tempfile.TemporaryDirectory(prefix="mirar_panel_") as tmp:
        carpeta = Path(tmp)
        consola = Consola(SesionPostiza(str(carpeta)), puerto=args.puerto)
        _con_piezas(consola.producido, carpeta)
        # >>> Y UN TURNO EN MARCHA, QUE ES LA MITAD DE LA v3 <<<
        # El cabezal cuelga de los EVENTOS: sin un turno vivo se captura
        # la mitad quieta del panel y no se ve nunca lo que se rehizo --
        # el punto rojo latiendo, "EN DIRECTO", lo que se hace ahora y el
        # reloj. `anuncia_turno` es el mismo camino que usa la voz, y
        # `_latir` deja el estado listo para la pestaña que llegue.
        consola.anuncia_turno(
            "escribiendo el resumen del proyecto en estado.md", "voz")
        consola.tarea.orden("Renderizando la escena para verla en el panel",
                            origen="claude")
        consola._latir()
        # Y una herramienta EN MARCHA. Es la linea que se añadio el 2
        # porque la frase de al lado se queda atras el 69 % del rato
        # (medido), asi que la captura tiene que enseñar las dos.
        # >>> Y UNOS RENGLONES DE REGISTRO DE VERDAD <<<
        # Sin esto la captura no enseña lo unico que se acaba de cambiar:
        # como se ve un uso de herramienta en el flujo. Salen de la traza
        # real, no inventados.
        _con_registro(consola)
        _con_pov(consola)
        consola._difundir({"clase": "UsoHerramienta", "id_uso": "vivo",
                           "herramienta": "Read",
                           "entrada": {"file_path": str(carpeta / "notas.txt")}})
        servidor = consola.servir(abrir_navegador=False)
        print(f"sirviendo en http://127.0.0.1:{args.puerto}/  "
              f"({len(consola.producido.piezas)} piezas)")
        try:
            for tema in temas:
                # >>> EL TEMA SALE DE `ui.tema`, NO DE LA URL <<<
                # Lo decide `Consola.tema_elegido` leyendo los ajustes, y
                # la primera version de esta sonda le pasaba `?tema=...`
                # creyendo que servia: los cuatro PNG salieron identicos
                # y en `jarvis`. Se descubrio mirandolos, que es lo que
                # esta sonda existe para hacer.
                consola.tema_elegido = (lambda t=tema: t)
                destino = (SALIDA / f"panel_{tema}.png").resolve()
                salio = captura(f"http://127.0.0.1:{args.puerto}/", destino)
                tamano = destino.stat().st_size if destino.is_file() else 0
                print(f"  {tema:<9} {'OK' if salio else 'NO SALIO':<9} "
                      f"{tamano/1024:>7.0f} KB  {destino}")

                # >>> Y SE MIDE SI EL NOMBRE DE UN MCP CABE <<<
                # (2026-09-07.) La fila se arreglo para no PARTIRSE, y
                # entonces aparecio lo otro: en `nexo` el rail es una
                # franja estrecha y los tres de claude.ai se recortaban
                # al mismo texto, o sea tres renglones que se leen igual.
                # Eso no lo dice un test ni se ve bien a ojo: es una
                # resta entre lo que mide la caja y lo que mide el texto.
                mide = ("(() => { const f=[...document.querySelectorAll("
                        "'#listaMcp .canal')]; if(!f.length) return 'SIN FILAS';"
                        " const n=f.map(x=>x.querySelector('.nombre'));"
                        " const peor=n.reduce((a,b)=> (b.scrollWidth-b.clientWidth)"
                        ">(a.scrollWidth-a.clientWidth)?b:a);"
                        " return JSON.stringify({filas:f.length,"
                        "alto:Math.round(f[0].getBoundingClientRect().height),"
                        "caben:Math.round(peor.clientWidth),"
                        "hacen_falta:Math.round(peor.scrollWidth)}); })()")
                medida: list = []
                captura(f"http://127.0.0.1:{args.puerto}/",
                        (SALIDA / f"_mcp_{tema}.png").resolve(),
                        js=mide, recoge=medida, espera_s=5.0)
                print(f"      mcp -> {medida[0] if medida else 'sin medir'}")

                # >>> Y LA CUOTA PASADA DEL 100 %, QUE SOLO SE VE <<<
                # (2026-09-07.) Es el estado que ha ocurrido UNA vez en
                # 363 eventos reales. Se pone la ventana del 107 % y se
                # captura la CARGA: lo que hay que comprobar es que una
                # barra llena y rebasada no se dibuje igual que una
                # llena y justa, porque el ancho ya no puede decirlo.
                consola.sesion.limite = _cuota_pasada_de_cien()
                pasada = (SALIDA / f"cuota_{tema}.png").resolve()
                # El POV se cierra para esta captura: se lleva el alto
                # del rail y deja la CARGA bajo el pliegue, o sea que la
                # barra que hay que MIRAR no sale en la foto. Se mide
                # igual con o sin el; lo que cambia es poder verla.
                lee = ("(() => { document.getElementById('pov').hidden=true;"
                       " const b=document.getElementById('barraSesion');"
                       " const n=document.getElementById('cuotaSesion');"
                       " return JSON.stringify({cifra:n.textContent,"
                       " ancho:b.style.width, marcada:b.classList.contains("
                       "'pasada')}); })()")
                dice: list = []
                captura(f"http://127.0.0.1:{args.puerto}/", pasada,
                        js=lee, recoge=dice, espera_s=5.0)
                print(f"      cuota -> {dice[0] if dice else 'sin medir'}"
                      f"  {pasada}")
                # Y la MISMA barra sin rebasar, para poder comparar: lo
                # que hay que juzgar no es si el rojo es bonito, es si un
                # 107 se distingue de un 100 justo -- y eso no se ve en
                # una foto sola.
                consola.sesion.limite = _cuota_de_verdad()
                normal = (SALIDA / f"cuota_ok_{tema}.png").resolve()
                captura(f"http://127.0.0.1:{args.puerto}/", normal,
                        js="(() => { document.getElementById('pov').hidden=true;"
                           " return 'ok'; })()", espera_s=5.0)

                # Y el VISOR, que es donde se lee de verdad el documento y
                # donde una maqueta puede romperlo sin que salte un test.
                # OJO: este selector era `#piezas .pieza`, o sea el de
                # la v1, y devolvia 'NO' sin que nada fallara -- las
                # capturas del visor salieron todas iguales y nadie lo
                # noto. Un selector viejo no da error: da una captura
                # que parece buena.
                abre = ("(() => { const f=[...document.querySelectorAll("
                        "'#tira .pieza')].find(x=>x.textContent.includes("
                        "'resumen-del-proyecto.md')); if(!f) return 'NO'; "
                        "f.click(); return 'ok'; })()")
                visor = (SALIDA / f"visor_{tema}.png").resolve()
                salio = captura(f"http://127.0.0.1:{args.puerto}/", visor,
                                js=abre)
                print(f"  {'':<9} visor {'OK' if salio else 'NO SALIO'}"
                      f"          {visor}")

                # >>> Y LA CAJA DE ESCRIBIR CON UNA ORDEN LARGA <<<
                # Lo reporto el usuario el 2026-09-03: la caja de texto
                # no crecia, solo se desplazaba su scroll interno, y de
                # una orden larga se veia un unico renglon cortado.
                # Ahora crece, y esto es lo unico que lo
                # demuestra: los tests miran el archivo, no el alto que
                # acaba teniendo la caja en cada tema -- que es distinto,
                # porque los cuatro le ponen otra letra.
                # Se ESCRIBE y se dispara `input`, en vez de llamar a
                # `ajustaCaja()` a mano: asi se prueba el cable entero.
                # Devuelve el alto para que la sonda pueda DECIRLO, que
                # es como se caza un tema que la aplaste.
                escribe = ("(() => { const c=document.getElementById("
                           "'texto'); if(!c) return 'NO'; c.value="
                           "'ve al proyecto epsilon y escribeme un "
                           "documento que resuma en que punto esta el "
                           "proyecto, con lo que quedo pendiente y quien "
                           "tiene que hacerlo, y guardalo como estado.md'; "
                           "c.dispatchEvent(new Event('input')); "
                           "const p=document.getElementById('pie'); "
                           "return 'caja ' + Math.round(c.getBoundingClient"
                           "Rect().height) + 'px (contenido ' + c.scrollHeight"
                           " + ') · pie ' + Math.round(p.getBoundingClient"
                           "Rect().height) + 'px'; })()")
                caja = (SALIDA / f"caja_{tema}.png").resolve()
                salio = captura(f"http://127.0.0.1:{args.puerto}/", caja,
                                js=escribe)
                print(f"  {'':<9} caja {'OK' if salio else 'NO SALIO'}"
                      f"           {caja}")

            # >>> Y CON UNA SOLA PIEZA, QUE ES EL CASO QUE FALLABA <<<
            # El usuario lo vio y tenia razon: con un solo documento la
            # ficha aparecia pegada a la derecha y dejaba un recuadro
            # enorme y vacio a la izquierda. Esta captura es la que dice si el
            # recuadro se ajusta al trabajo o vuelve a ocupar la columna
            # entera para enseñar una cosa.
            consola.tema_elegido = (lambda: temas[0])
            consola.producido = Producido()
            uno = carpeta / "estado.md"
            consola.producido.ve(UsoHerramienta(
                id_uso="solo", herramienta="Write",
                entrada={"file_path": str(uno)}))
            consola.producido.ve(ResultadoHerramienta(
                id_uso="solo", contenido="", es_error=False))
            consola._difundir_producido()
            sola = (SALIDA / f"una_{temas[0]}.png").resolve()
            salio = captura(f"http://127.0.0.1:{args.puerto}/", sola)
            print(f"  {'':<9} una pieza {'OK' if salio else 'NO SALIO'}"
                  f"      {sola}")

            # >>> EL RAIL PLEGADO, QUE ES LO QUE SE PIDIO EL 09-03 <<<
            # Pidio poder ocultar los paneles de perimetro y carga para
            # que el de "ejecutandose" pudiera crecer. Sin esta
            # captura no hay forma de ver el visor crecido: el estado
            # plegado vive en `localStorage`, o sea que una pestaña
            # recien abierta sale siempre con todo desplegado.
            # Se pulsan LOS BOTONES en vez de escribir la clase a mano:
            # asi se prueba tambien que el boton hace lo que dice y que
            # el rotulo cambia a MOSTRAR. Escribir la clase habria
            # medido esta sonda y no la pantalla.
            consola.tema_elegido = (lambda: temas[0])
            consola.producido = Producido()
            _con_piezas(consola.producido, carpeta)
            consola._difundir_producido()
            _con_pov(consola)
            pliega = ("(() => { const b=[...document.querySelectorAll("
                      "'[data-pliega]')]; if(b.length!==2) return 'NO'; "
                      "b.forEach(x=>x.click()); return b.map("
                      "x=>x.textContent).join(','); })()")
            plegado = (SALIDA / f"plegado_{temas[0]}.png").resolve()
            salio = captura(f"http://127.0.0.1:{args.puerto}/", plegado,
                            js=pliega)
            print(f"  {'':<9} rail plegado {'OK' if salio else 'NO SALIO'}"
                  f"   {plegado}")

            # >>> Y EL VISOR MIRANDO ATRAS, QUE NADIE HA VISTO NUNCA <<<
            # El scroll del visor (09-03) trae un estado nuevo: se subio
            # a leer algo, asi que el visor YA NO enseña el final. Si eso
            # no se rotula, un visor que dejo de seguir al texto se lee
            # igual que uno colgado -- que es justo el sintoma que este
            # panel existe para no tener. Se sube del todo y se mira que
            # aparezca el aviso ambar en el pie.
            consola.tema_elegido = (lambda: temas[0])
            # >>> SE ESPERA UN FOTOGRAMA ANTES DE MIRAR LA BANDERA <<<
            # Poner `scrollTop` no dispara el `scroll` en el acto: el
            # handler corre despues, asi que leer `povAtras.hidden` en la
            # linea siguiente devolvia SIEMPRE 'SIN AVISO' -- con el
            # aviso saliendo perfectamente en el PNG un segundo despues.
            # Hasta el 2026-09-03 daba igual porque nadie veia lo que
            # devolvia el js; en cuanto se imprimio, la sonda empezo a
            # gritar por algo que funcionaba. Una sonda que da falsas
            # alarmas se aprende a ignorar, igual que un aviso que no se
            # apaga nunca.
            sube = ("new Promise(r => { const c=document.getElementById("
                    "'povCuerpo'); if(!c) return r('NO');"
                    " if(c.scrollHeight<=c.clientHeight) return r("
                    "'NO DESBORDA'); c.scrollTop=0;"
                    " requestAnimationFrame(() => requestAnimationFrame("
                    "() => r(document.getElementById('povAtras').hidden"
                    " ? 'SIN AVISO' : 'ok'))); })")
            atras = (SALIDA / f"atras_{temas[0]}.png").resolve()
            salio = captura(f"http://127.0.0.1:{args.puerto}/", atras,
                            js=sube)
            print(f"  {'':<9} mirando atras {'OK' if salio else 'NO SALIO'}"
                  f"  {atras}")

            # >>> Y EL CABEZAL EN REPOSO, QUE ES LA OTRA MITAD <<<
            # Sin turno el punto deja de latir, el rotulo vuelve a "TE
            # DEJO" y el reloj pasa a "hace N". Es un estado distinto de
            # la misma linea, y es el que se ve el 90 % del tiempo: si
            # sale mal, lo que se ve mal es lo de siempre.
            consola.tema_elegido = (lambda: temas[0])
            consola.tarea.tarea = ""
            consola.tarea.origen = ""
            consola._tarea_desde = time.time() - 260
            consola._tarea_vista = ("x", "x")
            consola._latir()
            consola._tarea_desde = time.time() - 260
            consola._ultimo_estado["Tarea"]["desde"] = consola._tarea_desde
            reposo = (SALIDA / f"reposo_{temas[0]}.png").resolve()
            salio = captura(f"http://127.0.0.1:{args.puerto}/", reposo)
            print(f"  {'':<9} reposo {'OK' if salio else 'NO SALIO'}"
                  f"         {reposo}")
        finally:
            servidor.shutdown()
    print("\nMIRALAS. El test de temas solo comprueba que ninguna hoja las "
          "ESCONDA,\nno que se vean bien -- que es justo lo que fallo cuatro "
          "veces el 29.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
