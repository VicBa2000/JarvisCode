"""Donde acaba cada columna en los cuatro temas (2026-09-04).

    .venv\\Scripts\\python.exe -m eval.mirar_las_columnas [--puerto 8801]

>>> DE DONDE SALE, Y SON DOS QUEJAS DEL MISMO DIA <<<
Las dos las reporto el usuario usandolo, y las dos son de maqueta, o sea
de las que la suite entera da por buenas:

  * en el tema verde de terminal, la consola queda muy abajo y no se
    aprecia del todo su final;
  * en el tema minimalista, la ventana de "ejecutandose" crece hacia
    arriba por como esta acomodado todo, y se ve mal.

>>> POR QUE UNA SONDA Y NO UN TEST <<<
Ninguna de las dos se puede leer en el CSS. La primera es una resta -- el
borde de abajo de la caja de escribir contra el alto de la ventana -- y
la segunda es una CADENA de reglas que solo se resuelve cuando el
navegador reparte el hueco: la fila del rail en `nexo` es `auto`, o sea
que la manda el contenido, y `.povCuerpo` es `flex: 1 1 auto`, o sea que
su base es su propio texto. Nada de eso esta escrito en ningun sitio; se
calcula. `eval/mirar_el_panel.py` ya saca las capturas, pero una captura
dice "esto se ve mal" y esto dice CUANTO.

>>> QUE DIO LA PRIMERA PASADA, Y ES LO QUE JUSTIFICO LOS DOS ARREGLOS <<<
Ventana de 908 px, con un turno real dentro:

    tema      caja de escribir acaba en    registro
    jarvis            895                  311 px
    despacho          887                  249 px
    hacker            908  <-- el borde      418 px
    nexo              650                   16 px  <-- para 599 de texto

O sea: `hacker` era el unico de los cuatro sin un solo punto de aire
debajo (y el mismo margen se llevaba por delante el pie de la CARGA), y
en `nexo` el visor crecia con lo que Claude fuera escribiendo hasta
dejar el registro en UN RENGLON.

Tras los arreglos: hacker 898 y nexo 83 px de registro, con el visor ya
recortandose (174 px de alto para 273 de texto, o sea que la barra de
scroll de dentro por fin se usa).

OJO AL LEERLO: estas cifras salen del codigo de HOY y de una
ventana de 908 px. Lo que hay que mirar no es el numero exacto, son las
dos relaciones: que la caja de escribir no acabe EN el borde, y que el
registro no se quede sin sitio.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from eval.captura import captura
from eval.mirar_el_panel import (SesionPostiza, _con_piezas, _con_pov,
                                 _con_registro)

TEMAS = ("jarvis", "hacker", "despacho", "nexo")
SALIDA = Path("logs") / "capturas"

# Lo que se mide, en el navegador y sobre el DOM ya repartido. Se
# devuelve `scrollHeight` ademas del alto: es la unica forma de
# distinguir "cabe" de "esta recortado", que es media sonda.
MEDIR = """(() => {
  const caja = (id) => {
    const e = document.getElementById(id);
    if (!e) return null;
    const b = e.getBoundingClientRect();
    return {alto: Math.round(b.height), fin: Math.round(b.bottom),
            dentro: e.scrollHeight};
  };
  const d = {};
  for (const id of ["cuerpo", "izquierda", "flujo", "pie", "rail",
                    "pov", "povCuerpo", "modCarga"]) d[id] = caja(id);
  // >>> EL AIRE SE MIDE CONTRA LA ULTIMA TINTA, NO CONTRA LA ULTIMA CAJA
  // <<< Es la correccion que pidio la propia sonda: `#cuerpo` acaba en
  // el borde en `hacker` Y en `nexo`, pero solo uno de los dos estaba
  // mal. En `nexo` la franja del rail va A SANGRE a proposito y su
  // contenido lleva 14 px de `padding` dentro; en `hacker` la caja de
  // escribir tenia `padding: 0`, o sea que lo que tocaba el borde era el
  // TEXTO. Una caja pegada al borde puede estar bien; una letra pegada
  // al borde se lee como una letra cortada, y eso es lo que se reporto.
  //
  // >>> Y HAY QUE RECORTAR CONTRA LOS PANELES CON SCROLL <<<
  // Segunda correccion de la sonda a si misma: `despacho` daba -4 px y
  // la culpable era una linea del REGISTRO, que esta dentro de `#flujo`
  // y la recorta su propia caja, no la ventana. Un renglon a medio pintar
  // dentro de un panel que se desplaza es lo normal; lo que se busca es
  // lo que la VENTANA corta. Asi que a cada elemento se le calcula el
  // borde de abajo que de verdad se ve, cruzandolo con el de todos sus
  // ancestros que recortan.
  const bordeVisible = (e) => {
    let fin = e.getBoundingClientRect().bottom;
    for (let p = e.parentElement; p; p = p.parentElement) {
      const est = getComputedStyle(p);
      const recorta = (est.overflowY !== "visible" && est.overflowY !== "")
                   || (est.overflow !== "visible" && est.overflow !== "");
      if (recorta) fin = Math.min(fin, p.getBoundingClientRect().bottom);
    }
    return fin;
  };
  let tinta = 0, quien = "";
  for (const e of document.querySelectorAll("body *")) {
    const propio = [...e.childNodes].some(
      n => n.nodeType === 3 && n.textContent.trim());
    if (!propio) continue;
    const est = getComputedStyle(e);
    if (est.visibility === "hidden" || est.display === "none"
        || parseFloat(est.opacity) === 0) continue;
    const b = e.getBoundingClientRect();
    if (b.width === 0 || b.height === 0) continue;
    const fin = Math.round(bordeVisible(e));
    if (fin > tinta) { tinta = fin;
                       quien = e.id || e.className || e.tagName; }
  }
  return JSON.stringify({ventana: window.innerHeight, cajas: d,
                         tinta: tinta, tinta_quien: String(quien).slice(0, 34)});
})()"""


def _linea(tema: str, medida: dict) -> str:
    """Un tema, en las dos relaciones que importan.

    >>> Y ESTA FUNCION LA CORRIGIO LA PROPIA SONDA, DOS VECES <<<
    La primera version restaba desde el PIE, y en `nexo` daba 258 px de
    aire con la pantalla llena hasta abajo: alli el pie no es lo ultimo
    -- el rail es una franja horizontal y va DEBAJO --, o sea que la
    sonda declaraba holgado justo al tema que no lo esta.
    La segunda restaba desde `#cuerpo`, y entonces `hacker` y `nexo`
    daban los dos CERO... pero solo uno de los dos estaba mal: en `nexo`
    la franja va a sangre a proposito y su contenido lleva 14 px de
    `padding` dentro, mientras que en `hacker` la caja de escribir tenia
    `padding: 0` y lo que tocaba el borde era el TEXTO.
    Una caja pegada al borde puede estar bien; una LETRA pegada al borde
    se lee como una letra cortada, y eso es lo que se reporto. Asi que se
    mide la ultima tinta, lo dice el JS, y se dice ademas de quien es --
    sin eso, un cero no dice donde mirar.
    """
    cajas = medida["cajas"]
    ventana = medida["ventana"]
    pie = cajas.get("pie") or {}
    flujo = cajas.get("flujo") or {}
    pov = cajas.get("povCuerpo") or {}

    # >>> EL AIRE DE ABAJO, QUE ES LA PRIMERA QUEJA <<< Cero significa
    # que la ultima LETRA acaba en el borde de la ventana, y ahi no se lee
    # como una fila a sangre: se lee como una fila cortada.
    aire = ventana - medida.get("tinta", ventana)
    marca = (f" <-- PEGADO AL BORDE ({medida.get('tinta_quien','?')})"
             if aire <= 2 else f"  (lo ultimo: {medida.get('tinta_quien','?')})")

    # >>> Y EL REGISTRO, QUE ES LA SEGUNDA <<< Con el visor creciendo con
    # su propio contenido, esta columna se quedaba en un renglon.
    alto_flujo = flujo.get("alto", 0)
    corto = " <-- UN RENGLON" if alto_flujo < 40 else ""

    # Y si el visor se recorta o no: es la diferencia entre "cabe" y
    # "crece con el texto", que es media sonda.
    recorta = ("se recorta" if pov.get("dentro", 0) > pov.get("alto", 0)
               else "NO se recorta: crece con el texto")
    return (f"  {tema:<9} aire abajo {aire:>4} px{marca}\n"
            f"  {'':<9}   registro {alto_flujo:>4} px para "
            f"{flujo.get('dentro', 0)} de texto{corto}\n"
            f"  {'':<9}   visor    {pov.get('alto', 0):>4} px para "
            f"{pov.get('dentro', 0)} de texto ({recorta})\n"
            f"  {'':<9}   la caja de escribir acaba en "
            f"{pie.get('fin', 0)} de {ventana}")


def main(argv: list[str] | None = None) -> int:
    trozos = argparse.ArgumentParser(description=__doc__)
    trozos.add_argument("--puerto", type=int, default=8801)
    args = trozos.parse_args(argv)

    import json

    from puente.consola import Consola

    SALIDA.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="columnas_") as tmp:
        carpeta = Path(tmp)
        consola = Consola(SesionPostiza(str(carpeta)), puerto=args.puerto)
        # El mismo montaje que `mirar_el_panel`: piezas de verdad, un
        # turno en marcha y la camara a mitad de un `Write`. Sin el POV
        # lleno no se puede medir lo unico que se vino a medir.
        _con_piezas(consola.producido, carpeta)
        consola.anuncia_turno("escribiendo el resumen del proyecto en "
                              "estado.md", "voz")
        consola.tarea.orden("Renderizando la escena para verla en el panel",
                            origen="claude")
        consola._latir()
        _con_registro(consola)
        _con_pov(consola)
        servidor = consola.servir(abrir_navegador=False)
        print(f"sirviendo en http://127.0.0.1:{args.puerto}/\n")
        try:
            for tema in TEMAS:
                consola.tema_elegido = (lambda t=tema: t)
                destino = (SALIDA / f"columnas_{tema}.png").resolve()
                # `captura` IMPRIME lo que devuelve el JS; aqui hace
                # falta el valor para restar con el, asi que se recoge.
                # Leerlo a ojo de la salida no es medir.
                recoge: list[str] = []
                salio = captura(f"http://127.0.0.1:{args.puerto}/", destino,
                                js=MEDIR, recoge=recoge)
                if not salio or not recoge:
                    print(f"  {tema:<9} NO SALIO")
                    continue
                print(_linea(tema, json.loads(recoge[0])))
        finally:
            servidor.shutdown()

    print("\nLAS DOS RELACIONES QUE IMPORTAN, y no el numero exacto:\n"
          "  * la caja de escribir no puede acabar EN el borde;\n"
          "  * el registro no puede quedarse sin sitio porque el visor\n"
          "    crezca con lo que Claude vaya escribiendo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
