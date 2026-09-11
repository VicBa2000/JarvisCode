"""«Apagate» tiene que hacer lo mismo dicho que escrito.

>>> LO REPORTO EL USUARIO EL 2026-09-05, USANDOLO <<<
Dicho por voz, `apagate` lo intercepta Jarvis y se apaga, que es lo que
debe pasar; escrito en la consola, la misma palabra se le pasaba entera a
Claude Code.

Y su traza lo enseñaba entero: escribio `apagate`, salio "Turno nuevo en
la misma sesion", y Claude Code contesto con una despedida educada --
daba el trabajo por cerrado y se despedia hasta la proxima --. Un turno
pagado, y Jarvis siguio vivo.

>>> ES EL HUECO DEL 2026-09-03 CON OTRA FORMA, Y ESO ES LO GRAVE <<<
Aquel era `cambiar_a`, y tambien vivia SOLO en `voz/bucle.py`. Aquel dia
se escribio un test que barre el arbol para que no volviera a haber dos
llamadores... y no se miro si habia mas interceptaciones con la misma
forma. Habia una. Este archivo es su pariente, y la regla dicha en voz
alta: al arreglar un fallo de forma hay que buscar los demas sitios con
esa forma.

El argumento que justifica interceptar no ha cambiado y sigue sin
depender del canal:

    se intercepta lo que el cerebro no PUEDE hacer, jamas lo que seria
    mas rapido hacer aqui.

Claude Code no tiene esta ventana, no sabe que existe, y no puede matar
al proceso que lo esta conduciendo. Eso es verdad la digas o la escribas.

>>> Y "PARA" NO ENTRA AQUI. LO DECIDIO EL USUARIO <<<
Escrita es una preposicion normal ("para el servidor", "para que veas"),
y comersela seria tragarse una orden buena -- que es el fallo caro de
esta capa. La consola ya tiene Esc, que corta lo mismo, esta rotulado y
no puede confundirse con texto. Hay un test abajo que lo fija, porque
"se nos olvido" y "se decidio que no" se ven igual en el codigo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nucleo.carcasa import Gestos
from voz.ventana import Hecho, Veredicto, atender

RAIZ = Path(__file__).resolve().parent.parent


class SesionDeMentira:
    def __init__(self, viva: bool = True) -> None:
        self.viva = viva
        self.interrumpida = 0

    def interrumpir(self) -> None:
        self.interrumpida += 1


# --- 1. EL DECISOR, QUE ES UNO -----------------------------------------


class TestElDecisorEsUno:
    def test_solo_hay_UN_llamador_de_interpretar(self) -> None:
        """>>> ESTA ES LA REGLA ENTERA, Y SE MIRA EN EL ARBOL <<<

        `voz.ventana.interpretar` dice si una frase es una orden SOBRE
        Jarvis. Si vuelve a haber dos sitios que lo llamen, los dos
        canales volveran a decidirlo cada uno -- que es exactamente como
        se llego al fallo que este archivo documenta.
        """
        llamadores = []
        for ruta in RAIZ.rglob("*.py"):
            partes = ruta.relative_to(RAIZ).parts
            if partes[0] in ("tests", ".venv", "eval") or "__pycache__" in partes:
                continue
            if ruta.name == "ventana.py":
                continue
            # >>> LO QUE SE PROHIBE ES `interpretar`, NO EL MODULO <<<
            # Los dos canales importan `atender` y `Hecho`, y tienen que
            # hacerlo: son el decisor y su respuesta. Lo que no puede
            # volver a pasar es que alguien mire la frase por su cuenta y
            # decida que hacer, que es lo que habia en `voz/bucle.py`.
            for linea in ruta.read_text(encoding="utf-8").splitlines():
                if ("voz.ventana import" in linea
                        and "interpretar" in linea):
                    llamadores.append(str(ruta.relative_to(RAIZ)))
        assert llamadores == [], (
            f"estos llaman a `voz.ventana.interpretar` por su cuenta: "
            f"{llamadores}. El unico que lo llama es `atender`, y a "
            f"`atender` lo llaman los dos canales.")

    def test_los_dos_canales_llaman_a_ATENDER(self) -> None:
        for archivo in ("voz/bucle.py", "puente/consola.py"):
            fuente = (RAIZ / archivo).read_text(encoding="utf-8")
            assert "from voz.ventana import Hecho, atender" in fuente, archivo
            assert "atender(texto, self.gestos" in fuente, archivo

    def test_la_consola_lo_mira_ANTES_de_abrir_la_sesion(self) -> None:
        """"apagate" no puede levantar el binario de 337 MB para matarlo
        acto seguido. Y va antes del cambio de proyecto, que es el mismo
        orden que la voz: de la mas barata a la mas cara."""
        fuente = (RAIZ / "puente" / "consola.py").read_text(encoding="utf-8")
        trozo = fuente[fuente.index('if self.path == "/turno"'):]
        trozo = trozo[:trozo.index("elif self.path ==")]
        assert (trozo.index("de_la_ventana")
                < trozo.index("cambiar_de_proyecto")
                < trozo.index("asegurar_sesion"))


# --- 2. LOS GESTOS SON UN SOLO OBJETO ----------------------------------


class TestUnSoloJuegoDeGestos:
    def test_la_consola_y_la_voz_comparten_EL_MISMO(self) -> None:
        """Por referencia, no una copia. Con dos juegos de atributos,
        enchufar uno y olvidar el otro no da ningun error: da la misma
        frase haciendo cosas distintas segun el canal."""
        fuente = (RAIZ / "puente" / "__main__.py").read_text(encoding="utf-8")
        assert "gestos=consola.gestos," in fuente

    def test_se_enchufan_AUNQUE_NO_HAYA_VOZ(self) -> None:
        """El segundo fallo, debajo del primero: vivian dentro de un
        `if voz is not None`, y ese es justo el modo en el que SOLO
        existe la consola."""
        fuente = (RAIZ / "escritorio" / "__main__.py").read_text(
            encoding="utf-8")
        assert "gestos = self.montaje.consola.gestos" in fuente
        assert "if voz is not None:" not in fuente

    def test_sin_carcasa_NO_se_mata_el_proceso_a_lo_bruto(self) -> None:
        """Tercera salida. Matarlo desde aqui dejaria la sesion
        de Claude Code sin cerrar y el hijo `claude` vivo, que es lo
        contrario de lo que "apagate" viene a hacer."""
        r = atender("apagate", Gestos(), interrumpir=None)
        assert r.hecho is Hecho.SIN_CARCASA
        assert r.se_ocupo, "no puede seguir al cerebro como si nada"
        assert r.es_el_final


# --- 3. QUE HACE CADA UNA ----------------------------------------------


class TestLoQueHace:
    def test_abrete_y_cierrate(self) -> None:
        visto: list[str] = []
        g = Gestos(mostrar=lambda: visto.append("m"),
                   esconder=lambda: visto.append("e"))
        assert atender("abrete", g).hecho is Hecho.MOSTRADA
        assert atender("cierrate", g).hecho is Hecho.ESCONDIDA
        assert visto == ["m", "e"]

    def test_apagate_CORTA_EL_TURNO_antes_de_apagar(self) -> None:
        """JC-0011 lo midio: el interrupt corta en centesimas y corta las
        herramientas de verdad. Es la diferencia entre apagarse y
        desenchufar -- sin esto, Claude Code se queda a medias de una
        cadena de herramientas."""
        sesion = SesionDeMentira()
        r = atender("apagate", Gestos(apagar=lambda: None),
                    interrumpir=sesion.interrumpir)
        assert r.hecho is Hecho.APAGANDO
        assert sesion.interrumpida == 1

    def test_APAGANDO_no_apaga_el_solo_y_eso_es_a_proposito(self) -> None:
        """>>> `apagar` NO VUELVE: mata el proceso <<<

        Si el decisor lo llamara, el canal no llegaria a despedirse -- y
        por voz un apagado mudo y un cuelgue se ven exactamente igual.
        Devuelve APAGANDO y apaga el canal, cuando ya ha dicho lo suyo.
        """
        apagados: list[int] = []
        r = atender("apagate", Gestos(apagar=lambda: apagados.append(1)))
        assert r.hecho is Hecho.APAGANDO
        assert apagados == [], "se apago antes de que el canal se despidiera"

    def test_un_gesto_que_revienta_NO_tumba_el_turno(self) -> None:
        def revienta() -> None:
            raise RuntimeError("no hay ventana")

        r = atender("abrete", Gestos(mostrar=revienta))
        assert r.hecho is Hecho.ROTO
        assert "no hay ventana" in r.error

    def test_una_orden_normal_no_se_toca(self) -> None:
        for frase in ("abre el informe", "cierra la conexion",
                      "apaga el servidor de pruebas", "muestrame el diff"):
            r = atender(frase, Gestos(mostrar=lambda: None,
                                      esconder=lambda: None,
                                      apagar=lambda: None))
            assert r.hecho is Hecho.NO_ES, frase
            assert not r.se_ocupo, frase


# --- 4. LO QUE SE DECIDIO NO HACER -------------------------------------


def test_PARA_no_se_intercepta_escrita_y_es_una_DECISION() -> None:
    """>>> "SE NOS OLVIDO" Y "SE DECIDIO QUE NO" SE VEN IGUAL <<<

    Por eso esto es un test y no un comentario. El usuario lo eligio el
    2026-09-05 entre tres salidas: escrita, "para" es una preposicion
    normal ("para el servidor", "para que veas") y comersela seria
    tragarse una orden buena, que es el fallo caro de esta capa. La
    consola ya tiene Esc, que corta lo mismo y esta rotulado.

    Si algun dia se quiere, lo que hay que cambiar es esta decision --
    y este test --, no colar la palabra en `voz/ventana.py`.
    """
    from voz.ventana import Veredicto as V

    from voz.ventana import interpretar

    assert interpretar("para").veredicto is V.NO_ES
    assert interpretar("cancela").veredicto is V.NO_ES

    fuente = (RAIZ / "puente" / "consola.py").read_text(encoding="utf-8")
    trozo = fuente[fuente.index("def de_la_ventana"):
                   fuente.index("def cambiar_de_proyecto")]
    assert "parada" not in trozo, (
        "la consola ha empezado a interceptar 'para' escrita; eso reabre "
        "una decision del usuario, no es un arreglo")
