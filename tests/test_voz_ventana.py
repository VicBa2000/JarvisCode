"""Enseñar y esconder la ventana hablando.

DE DONDE SALE (2026-08-26, el usuario usandolo): con Jarvis en segundo
plano no habia ninguna orden para abrir su ventana hablando. Con la ventana
en la bandeja te oye perfectamente -- el wake word sigue corriendo -- y
no habia forma de pedirle que se enseñara: habia que ir al raton, que es
justo lo que un asistente de voz viene a evitar.

>>> LO QUE ESTE ARCHIVO PROTEGE ES LO MISMO DE SIEMPRE <<<
Es la SEGUNDA orden que no llega al cerebro, asi que el test que importa
no es "reconoce muestrate": es que *"abre el informe de ventas"* siga
llegando a Claude Code. Cada forma nueva que se anada a `voz/ventana.py`
es una forma nueva de comerse una orden buena.
"""

from __future__ import annotations

import pytest

from nucleo.carcasa import Gestos

from voz.ventana import Veredicto, interpretar


# --- 1. NO COMERSE ORDENES BUENAS ---------------------------------------


@pytest.mark.parametrize("frase", [
    # >>> ESTAS SIETE SE RECONOCIAN, Y EL USUARIO LAS QUITO <<<
    # Las quito porque el resto puede estorbar trabajando en una sesion de
    # Claude Code. Sobre codigo se dicen con toda naturalidad, y
    # ahi lo que quieres es que LLEGUEN al cerebro.
    "cierra la ventana",
    "abre la ventana",
    "muestrate",
    "escondete",
    "ocultate",
    "quitate de en medio",
    "ven aqui",
    # Y las de siempre.
    "abre el informe de ventas",
    "abre el bloc de notas y escribe informe listo",
    "cierra el archivo que acabas de crear",
    "abre el proyecto nebula",
    "muestrame los cambios",
    "ensename lo que has hecho",
    "borra la carpeta de descargas",
])
def test_una_orden_normal_LLEGA_al_cerebro(frase: str) -> None:
    """>>> EL TEST QUE DECIDE SI ESTO PUEDE EXISTIR <<<

    El precio de equivocarse NO es simetrico: no reconocer "abrete"
    cuesta ir al raton una vez; tragarse "cierra la ventana" cuesta que
    Jarvis no haga lo que le pediste y que no sepas por que.
    """
    assert interpretar(frase).veredicto is Veredicto.NO_ES


# --- 2. LAS DOS QUE SI ---------------------------------------------------


@pytest.mark.parametrize("frase", ["abrete", "ábrete", "Ábrete", "ABRETE"])
def test_abrete_enseña_la_ventana(frase: str) -> None:
    assert interpretar(frase).veredicto is Veredicto.MOSTRAR


@pytest.mark.parametrize("frase", ["cierrate", "ciérrate", "Ciérrate"])
def test_cierrate_la_esconde(frase: str) -> None:
    assert interpretar(frase).veredicto is Veredicto.ESCONDER


def test_son_DOS_formas_y_no_diez() -> None:
    """Cada forma de mas es una forma de mas de comerse una orden buena.
    Si alguien anade una tercera, que sea con este test delante y sabiendo
    que "abrete" y "cierrate" son reflexivos y no significan nada mas --
    no hay manera de decirselos a Claude Code sobre un archivo.
    """
    from voz.ventana import ESCONDER, MOSTRAR

    assert len(MOSTRAR) == 1 and len(ESCONDER) == 1


def test_las_tildes_no_pierden_la_orden() -> None:
    """El STT no siempre las pone, y perder la orden por un acento seria
    el mismo fallo que ya se arreglo en `nucleo/proyectos.py`."""
    assert interpretar("ábrete").veredicto is interpretar("abrete").veredicto
    assert interpretar("ciérrate").veredicto is interpretar("cierrate").veredicto


def test_dentro_de_una_frase_larga_tampoco_se_cuela() -> None:
    """"abrete camino entre los archivos" no es una orden de ventana...
    pero "abrete" si esta ahi dentro. Se acepta que casen: son palabras
    que nadie usa asi hablandole a un asistente, y exigir que la frase
    sea SOLO eso perderia "jarvis abrete".
    Este test existe para que la decision quede escrita, no escondida.
    """
    assert interpretar("jarvis abrete").veredicto is Veredicto.MOSTRAR


# --- 3. EN EL BUCLE ------------------------------------------------------


class VentanaPostiza:
    def __init__(self) -> None:
        self.mostrada = 0
        self.escondida = 0


@pytest.fixture
def bucle_con_ventana(bucle_de_voz):
    bucle, falsa = bucle_de_voz
    return bucle, falsa


@pytest.fixture
def bucle_de_voz():
    from tests.test_voz_bucle import (
        Ciclo,
        Senales,
        SesionPostiza,
        STTPostizo,
        TTSPostizo,
    )
    from voz.bucle import Bucle

    falsa = VentanaPostiza()
    b = Bucle(sesion=SesionPostiza(), ciclo=Ciclo(senales=Senales()),
              tts=TTSPostizo(), stt=STTPostizo(), micro=object(), altavoz=None)
    b.ciclo.respiro_s = 0.0
    b.gestos = Gestos()
    b.gestos.mostrar = lambda: setattr(falsa, "mostrada", falsa.mostrada + 1)
    b.gestos.esconder = lambda: setattr(falsa, "escondida",
                                         falsa.escondida + 1)
    return b, falsa


def test_pedir_la_ventana_NO_llega_al_cerebro(bucle_con_ventana) -> None:
    bucle, falsa = bucle_con_ventana
    assert bucle._de_la_ventana("abrete") is True
    assert falsa.mostrada == 1
    assert bucle.sesion.mandados == [], "se mando al cerebro"
    assert bucle.cuenta.ventana_movida == 1


def test_esconderla_tambien(bucle_con_ventana) -> None:
    bucle, falsa = bucle_con_ventana
    assert bucle._de_la_ventana("cierrate") is True
    assert falsa.escondida == 1
    assert bucle.sesion.mandados == []


def test_una_orden_normal_sigue_su_camino(bucle_con_ventana) -> None:
    bucle, falsa = bucle_con_ventana
    assert bucle._de_la_ventana("abre el informe") is False
    assert (falsa.mostrada, falsa.escondida) == (0, 0)


def test_sin_ventana_se_DICE_en_vez_de_callarse(bucle_de_voz) -> None:
    """>>> TERCERA SALIDA <<<

    Lanzando `-m puente` desde una terminal no hay ventana. Callarse
    pareceria que no te ha oido, que es la diferencia entre un asistente
    que no puede y uno que parece roto.
    """
    bucle, _ = bucle_de_voz
    bucle.gestos = Gestos()   # sin carcasa: no hay ventana que mover
    assert bucle._de_la_ventana("abrete") is True
    assert "terminal" in " ".join(bucle.tts.dicho)
    assert bucle.sesion.mandados == []


def test_una_ventana_que_falla_no_tumba_el_turno(bucle_de_voz) -> None:
    def revienta():
        raise RuntimeError("la ventana se fue")

    bucle, _ = bucle_de_voz
    bucle.gestos = Gestos(mostrar=revienta)
    assert bucle._de_la_ventana("abrete") is True   # no levanta
    assert bucle.ultimo_fallo


def test_se_contesta_CORTO(bucle_con_ventana) -> None:
    """Es una accion que ya se ve. Un "he abierto la ventana" mientras la
    ventana aparece delante es el asistente contandote lo que miras."""
    bucle, _ = bucle_con_ventana
    bucle._de_la_ventana("abrete")
    dicho = " ".join(bucle.tts.dicho)
    assert len(dicho) < 40, dicho


# --- 4. LA CARCASA LE ENTREGA LOS GESTOS --------------------------------


def test_la_carcasa_le_da_a_la_voz_como_mover_la_ventana() -> None:
    """El `Bucle` vive en `voz/` y no sabe que existe pywebview. Si esto
    se rompe, la orden se reconoce y no hace nada -- un fallo mudo."""
    from pathlib import Path

    from escritorio import __main__ as carcasa

    fuente = Path(carcasa.__file__).read_text(encoding="utf-8")
    # >>> Y VAN A UN OBJETO COMPARTIDO DESDE EL 2026-09-05 <<<
    # Eran tres atributos en el `Bucle`, y la consola no los veia:
    # "apagate" escrito se iba al cerebro. Ahora es un
    # `nucleo.carcasa.Gestos` que comparten los dos canales, y se
    # enchufa SIEMPRE -- antes vivia dentro de un `if voz is not
    # None`, o sea que sin `--voz` no habia a quien pedirselo.
    assert "gestos = self.montaje.consola.gestos" in fuente
    assert "gestos.mostrar = self._mostrar" in fuente
    assert "gestos.esconder = self._esconder" in fuente
    assert "gestos.apagar = self._salir" in fuente
    assert "if voz is not None:" not in fuente, (
        "los gestos han vuelto a depender de que haya voz")


def test_esconder_por_voz_hace_LO_MISMO_que_la_X() -> None:
    """Dos formas de esconder que se separasen serian dos formas de
    dejarse algo."""
    from pathlib import Path

    from escritorio import __main__ as carcasa

    fuente = Path(carcasa.__file__).read_text(encoding="utf-8")
    trozo = fuente[fuente.index("def _esconder"):]
    trozo = trozo[:trozo.index("def _al_navegador")]
    assert "self.ventana.hide()" in trozo


# --- "APAGATE" (2026-08-27) ----------------------------------------------


@pytest.mark.parametrize("frase", [
    "apagate",
    "apágate",           # con tilde, que es como lo escribe el STT
    "APAGATE",
    "jarvis apagate ya",
])
def test_apagate_se_reconoce(frase):
    peticion = interpretar(frase)
    assert peticion.veredicto is Veredicto.APAGAR
    assert peticion.es_el_final


@pytest.mark.parametrize("frase", [
    # >>> LO QUE NO PUEDE APAGAR JARVIS <<< Son frases que se dicen
    # trabajando sobre codigo, y ahi tienen que LLEGAR al cerebro. El
    # precio de equivocarse con esta palabra no es el de las otras dos:
    # no esconde una ventana, mata el asistente y el turno en marcha.
    "apaga el ordenador cuando termines",
    "apaga el servidor de desarrollo",
    "apagalo todo y vuelve a empezar",
    "el led se apaga si no hay senal",
    "comprueba que el proceso se apague bien",
])
def test_lo_que_NO_apaga_jarvis(frase):
    assert interpretar(frase).veredicto is Veredicto.NO_ES


def test_las_tres_palabras_y_ni_una_mas():
    """La regla que el usuario fijo el 2026-08-27 recortando de diez a
    dos: solo reflexivos que no significan nada mas. Si alguien añade
    una cuarta forma con complemento libre, se empieza a comer ordenes
    buenas -- y con `apagate` el error ya no se deshace solo."""
    from voz.ventana import APAGAR, ESCONDER, MOSTRAR

    assert (MOSTRAR, ESCONDER, APAGAR) == (
        (r"\babrete\b",), (r"\bcierrate\b",), (r"\bapagate\b",))


def test_apagar_no_se_confunde_con_las_otras_dos():
    assert interpretar("abrete").veredicto is Veredicto.MOSTRAR
    assert interpretar("cierrate").veredicto is Veredicto.ESCONDER
    assert not interpretar("cierrate").es_el_final
    assert not interpretar("abrete").es_el_final
