"""Capturas de la PESTANA DE AJUSTES, en los cuatro temas.

    python -m eval.mirar_los_ajustes [--tema jarvis] [--puerto 8798]

>>> POR QUE HACIA FALTA UNA SONDA NUEVA Y NO VALIA `mirar_el_panel` <<<
Aquella captura `/`, o sea la CONSOLA. Los ajustes viven en un `iframe`
que es un DOCUMENTO APARTE -- por eso `tema.css` existe -- y nunca se han
capturado: hasta hoy, todo lo que se ha mirado a ojo de esa pagina se
miro abriendo la ventana a mano.

Y el 2026-09-05 esa pagina gano dos controles NUEVOS de un tipo que no
existia: un `textarea` de ajuste (`tipo: "parrafo"`) y, dentro de cada
proyecto, un desplegable de tres estados con su caja de texto al lado.
Este arbol lleva CUATRO veces que un tema rompe algo con la suite entera
en verde -- la caja de texto, la tira aplastada, un `display` inline y el
modal transparente --, y las cuatro se cazaron mirando, no testeando.

LO QUE MIDE, ademas de sacar el PNG:
  * que los dos controles nuevos EXISTEN y tienen alto de verdad. Es la
    leccion de la tira: el test de temas mira que ninguna hoja los
    ESCONDA, y aplastar no es esconder -- la tarjeta a 28 px con la
    miniatura dentro a 15 pasaba los 1211 tests de aquel dia;
  * que la caja del proyecto APARECE al elegir "otra cosa" y no antes,
    que es el cable entero de los tres estados;
  * y que el `textarea` del ajuste no se sale de su columna.

MONTA UNA SESION POSTIZA: no hace falta Claude Code para mirar una
pantalla. Y escribe su propio `proyectos.yaml` en una carpeta temporal,
porque la fila que hay que mirar es la de UN PROYECTO REGISTRADO y la
maquina donde corra esto puede no tener ninguno.
"""

from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from eval.captura import captura

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
TEMAS = ("jarvis", "hacker", "despacho", "nexo")
SALIDA = Path("logs") / "capturas"


class SesionPostiza:
    """Lo justo para que la consola conteste. No abre nada."""

    def __init__(self, directorio: str) -> None:
        self.directorio = directorio
        self.viva = True
        self.session_id = "captura"
        self.modelo = "sonnet"
        self.modo_permisos = "default"
        self.pendientes: tuple = ()
        self.pregunta_abierta = None
        self.reintentando = None
        self.limite = None
        self.fallo = None
        self.ultimo_evento_en = time.time()
        self.silencio_s = 0.4
        self.mcp_vistos: set = set()
        self.servidores_mcp: tuple = ()
        self.zonas: tuple = ()

    def eventos(self, timeout=None):
        return iter(())

    def cerrar(self) -> None:
        pass


# >>> SE CAPTURA `/ajustes` DIRECTAMENTE, NO EL IFRAME <<<
# En la ventana de verdad esta pagina vive dentro de un `iframe` de la
# consola, pero ese iframe no tiene `id` -- es `vistaAjustes.firstChild`
# -- y llegar hasta su `contentDocument` desde el JS de fuera es tres
# saltos que se pueden romper solos. `/ajustes` se sirve entera y sin
# ficha (es de donde sale la pagina), y enlaza `tema.css` y su hoja de
# tema por su cuenta: eso es justamente por lo que la paleta vive en un
# archivo y no en dos `:root`. Asi que lo que se ve aqui es lo que se ve
# dentro del marco, con el ancho del marco puesto a mano.

# Todo en UNA sola expresion: `captura` evalua el `js` con
# `awaitPromise`, o sea que espera UNA promesa. Dos IIFE separadas por
# `;` arrancarian a la vez y la medicion correria antes de que la pagina
# terminara de pintar -- y no daria error, daria numeros de una pantalla
# a medio montar.
MIRAR = """(async () => {
  const SITIO = %r;
  for (let i = 0; i < 80; i++) {
    await new Promise(r => setTimeout(r, 100));
    const l = document.getElementById('listaProyectos');
    if (l && l.querySelector('.fila')) break;
  }
  // >>> AVANZADO NACE PLEGADO, Y LA PRIMERA PASADA MIDIO 0 px POR ESO
  // <<< `#avanzado[hidden]` es `display:none`, y ahi un
  // `getBoundingClientRect()` devuelve 0 de alto Y de ancho sin dar
  // error: la sonda dijo "ajuste 0 px" en los cuatro temas y parecia
  // una caja aplastada. Se pulsa el BOTON de verdad y no se toca
  // `hidden` a mano, que es lo mismo que hace la sonda de la caja de
  // texto: asi lo que se mide es la pagina y no una version de la
  // pagina que solo existe en la sonda.
  const ver = document.getElementById('verAvanzado');
  if (!ver) return 'NO ESTA EL BOTON DE AVANZADO';
  ver.click();
  for (const det of document.querySelectorAll('details')) det.open = true;
  await new Promise(r => setTimeout(r, 300));

  const fuera = [];
  // El ajuste nuevo: se busca por su ROTULO, no por posicion en la
  // lista -- un ajuste que se anada antes moveria el indice y la sonda
  // mediria otra fila sin decirlo.
  // >>> Y SE COMPRUEBA QUE ESTA EN LA SECCION DE PROYECTOS <<<
  // Lo reporto el usuario el 09-05: con el interruptor puesto no habia
  // ningun campo donde escribir el mensaje global; no aparecia.
  // mientras el interruptor de abajo decia "la de arriba". Ahora se pinta
  // dentro de TUS PROYECTOS, asi que la sonda mira DONDE cuelga y no solo
  // que exista: existir ya existia.
  let aj = null;
  for (const f of document.querySelectorAll('.fila')) {
    const t = f.querySelector('.titulo');
    if (t && /abrir un proyecto|opens a project/i.test(t.textContent)) aj = f;
  }
  fuera.push('la global cuelga de ' +
    (aj ? (aj.closest('#seccionProyectos') ? 'TUS PROYECTOS'
         : (aj.closest('#avanzado') ? 'avanzado (MAL)' : 'otro sitio'))
        : 'NO ESTA'));
  fuera.push('y va ' + (aj && document.getElementById('proyRitualManda')
      && (aj.compareDocumentPosition(
            document.getElementById('proyRitualManda').closest('.fila'))
          & Node.DOCUMENT_POSITION_FOLLOWING) ? 'ENCIMA' : 'DEBAJO') +
    ' del interruptor');
  const ta = aj ? aj.querySelector('textarea') : null;
  fuera.push('ajuste ' + (ta ? Math.round(ta.getBoundingClientRect().height)
                             : 'NO ESTA') + ' px');
  if (ta) {
    fuera.push('desborda ' +
      Math.round(ta.getBoundingClientRect().width
                 - aj.getBoundingClientRect().width) + ' px');
  }

  const filaP = document.querySelector('#listaProyectos .fila');
  const sel = filaP ? filaP.querySelector('select') : null;
  const suya = filaP ? filaP.querySelector('textarea') : null;
  fuera.push('select ' + (sel ? Math.round(sel.getBoundingClientRect().height)
                              : 'NO ESTA') + ' px');
  fuera.push('opciones ' + (sel ? sel.options.length : 0));
  fuera.push('empieza en ' + (sel ? sel.value : '?') +
             ', caja oculta ' + (suya ? suya.hidden : '?'));
  // >>> EN LA PASADA DEL OVERRIDE NO SE TOCA <<< La primera version si,
  // y daba "2 avisos en 2 filas": poner la fila 1 en "otra cosa" le da
  // una frase propia, asi que el override la pisa TAMBIEN y la medicion
  // decia que si en las dos. Cierto y sin valor -- estaba midiendo lo
  // que la sonda acababa de hacer, o sea midiendo la sonda. Sin
  // tocarla, la fila 1 HEREDA y la 2 tiene la suya, o sea que "1 de 2"
  // es lo unico que prueba "solo en las que pisa".
  if (sel && SITIO !== 'override') {
    // Se dispara el `change` de verdad en vez de llamar al handler: asi
    // se prueba el cable entero, que es lo que hizo la sonda de la caja
    // de texto el 09-03.
    sel.value = 'propia';
    sel.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 120));
    fuera.push('al elegir propia: ' +
      Math.round(suya.getBoundingClientRect().height) + ' px, prellena "' +
      suya.value.slice(0, 22) + '"');
  }
  // Y el segundo proyecto, que YA trae la suya escrita: tiene que abrir
  // en "propia" con su texto dentro y sin que nadie toque nada.
  const otra = document.querySelectorAll('#listaProyectos .fila')[1];
  const sel2 = otra ? otra.querySelector('select') : null;
  const ta2 = otra ? otra.querySelector('textarea') : null;
  fuera.push('el que ya tenia: ' + (sel2 ? sel2.value : 'NO ESTA') +
             ' "' + (ta2 ? ta2.value : '') + '" oculta ' +
             (ta2 ? ta2.hidden : '?'));
  // >>> Y EL OVERRIDE ENCENDIDO, QUE ES OTRA PANTALLA <<<
  // Encenderlo tiene que marcar EN AMBAR las filas que pisa, y solo
  // esas. Ahi es donde este ajuste se gana o se pierde: un override que
  // no se ve donde muerde es la barra de la cuota otra vez.
  if (SITIO === 'override') {
    const sw = document.getElementById('proyRitualManda');
    if (!sw) return 'NO ESTA EL INTERRUPTOR';
    sw.checked = true;
    sw.dispatchEvent(new Event('change'));
    await new Promise(r => setTimeout(r, 150));
    const filas = [...document.querySelectorAll('#listaProyectos .fila')];
    const avisos = filas.filter(f => /manda la frase de arriba|sentence above wins/i
                                     .test(f.textContent)).length;
    fuera.push('con override: ' + avisos + ' avisos en ' +
               filas.length + ' filas');
  }

  // >>> Y SE BAJA HASTA LO QUE HAY QUE MIRAR <<< La primera tanda salio
  // con la pagina por arriba y los dos controles nuevos debajo del
  // pliegue: cuatro PNG que no ensenaban NADA de lo que se acaba de
  // escribir, y los numeros de al lado decian que todo estaba bien. Es
  // el mismo silencio del selector viejo del visor -- una captura que
  // parece buena.
  // Se vuelve a BUSCAR el contenedor en vez de reusar `filaP`: al
  // encender el override la lista se repinta entera, asi que el nodo de
  // antes queda huerfano y su `parentElement` es null. Reventaba con un
  // TypeError -- que al menos SE VE, porque `captura` levanta si el js
  // falla; guardarse el nodo y que la captura saliera igual habria sido
  // el silencio del selector viejo otra vez.
  // En la pasada del override se baja hasta LA FILA PISADA, no hasta la
  // seccion: el interruptor y su aviso estan a media pantalla de
  // distancia y el aviso -- que es lo unico nuevo -- caia justo debajo
  // del corte. Se vio en la captura, que es para lo que sirve.
  // >>> Y EL GLOSARIO, QUE ES SECCION NUEVA (2026-09-05) <<<
  // Se mide cuantas filas trae y si alguna dice "todavia no": ese
  // rotulo es el que impide que la lista prometa algo que hoy se va
  // entero al cerebro (el cambio de proyecto en ingles).
  if (SITIO === 'glosario') {
    const filas = [...document.querySelectorAll('#listaGlosario .fila')];
    fuera.push('glosario: ' + filas.length + ' filas, ' +
      filas.filter(f => /todavia no|not available/i.test(f.textContent))
           .length + ' con "todavia no"');
    fuera.push('alto de la 1a: ' + (filas[0]
      ? Math.round(filas[0].getBoundingClientRect().height) : 0) + ' px');
  }

  let ancla = SITIO === 'ajuste' ? aj
            : document.getElementById(
                SITIO === 'glosario' ? 'seccionGlosario' : 'seccionProyectos');
  if (SITIO === 'override') {
    ancla = [...document.querySelectorAll('#listaProyectos .fila')].find(
      f => /manda la frase de arriba|sentence above wins/i.test(f.textContent)
    ) || ancla;
  }
  ancla.scrollIntoView({block: SITIO === 'proyectos' ? 'start' : 'center'});
  await new Promise(r => setTimeout(r, 200));
  return fuera.join(' | ');
})()"""

# Dos capturas por tema, porque los dos controles nuevos estan a media
# pagina de distancia y en una sola no caben los dos.
DONDE = ("ajuste", "proyectos", "override", "glosario")


def main(argv: list[str] | None = None) -> int:
    trozos = argparse.ArgumentParser(description=__doc__)
    trozos.add_argument("--puerto", type=int, default=8798)
    trozos.add_argument("--tema", default="", help="uno solo; vacio = los 4")
    args = trozos.parse_args(argv)

    if not EDGE.is_file():
        print(f"No esta Edge en {EDGE}. Sin navegador no hay captura.")
        return 2

    from nucleo.proyectos import Proyecto, guardar
    from puente.consola import Consola

    SALIDA.mkdir(parents=True, exist_ok=True)
    temas = (args.tema,) if args.tema else TEMAS
    with tempfile.TemporaryDirectory(prefix="mirar_ajustes_") as tmp:
        carpeta = Path(tmp)
        # >>> UN REGISTRO PROPIO, Y NO EL DE LA MAQUINA <<<
        # La fila que hay que mirar es la de un proyecto registrado. Si
        # esto leyera `config/proyectos.yaml`, la captura saldria bien o
        # mal segun quien la corra -- y ademas guardar desde el panel
        # reescribiria el registro de verdad del usuario.
        import nucleo.proyectos as mod

        antes = mod.CONFIG_DIR
        mod.CONFIG_DIR = carpeta
        uno = carpeta / "faro"
        uno.mkdir()
        otro = carpeta / "nebula"
        otro.mkdir()
        guardar((Proyecto("Faro", str(uno)),
                 Proyecto("nebula", str(otro), ritual="mira el roadmap")),
                activo=True, config_dir=carpeta)

        consola = Consola(SesionPostiza(str(carpeta)), puerto=args.puerto)
        servidor = consola.servir(abrir_navegador=False)
        print(f"sirviendo en http://127.0.0.1:{args.puerto}/")
        try:
            for tema in temas:
                # El tema sale de `ui.tema`, no de la URL: pasarselo por
                # query dejo cuatro capturas identicas el 2026-09-01.
                consola.tema_elegido = (lambda t=tema: t)
                for sitio in DONDE:
                    destino = (SALIDA
                               / f"ajustes_{sitio}_{tema}.png").resolve()
                    recoge: list[str] = []
                    # Ancho 900: en la ventana de verdad el iframe ocupa
                    # todo el ancho y la hoja se maqueta a 860 px. Una
                    # captura a 1600 dejaria la columna centrada en un
                    # mar de fondo y no ensenaria si algo se sale.
                    salio = captura(
                        f"http://127.0.0.1:{args.puerto}/ajustes",
                        destino, js=MIRAR % sitio, recoge=recoge,
                        ancho=900, alto=1000)
                    marca = "OK" if salio else "NO SALIO"
                    print(f"  {tema:<9} {sitio:<10} {marca:<9} {destino}")
                    for linea in recoge:
                        print(f"  {'':<9} {'':<10} {linea}")
        finally:
            servidor.shutdown()
            consola.parar()
            mod.CONFIG_DIR = antes
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
