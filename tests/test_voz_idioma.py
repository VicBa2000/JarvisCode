"""JC-0018: el idioma de la VOZ. Lo que no se resuelve traduciendo.

QUE SE PRUEBA AQUI, Y POR QUE NO ES UN `test_ui_idioma` MAS. La pantalla
es un diccionario: si una cadena se queda en español se lee y ya. Aqui
hay cuatro cosas medidas contra un corpus en español -- el ancla, el
lexico de parada, la voz de Piper y el umbral de `sin_habla` -- y las
cuatro fallan SIN DAR ERROR:

  * un lexico de parada traducido palabra por palabra convierte ordenes
    normales en paradas ("stop the server"), y eso no se ve hasta que te
    corta a mitad de trabajo;
  * una voz de Piper del idioma que no es no revienta: lee el texto con
    la fonetica equivocada y suena a aparato roto;
  * un ancla del idioma que no es empeora la transcripcion en silencio;
  * y una frase sin traducir no se calla: se oye en español dentro de una
    conversacion en ingles, que al menos SE NOTA -- por eso el respaldo
    es ese y no el silencio.

Lo que NO se prueba: si el ingles se entiende bien al oirlo. Eso lo
contesta el usuario hablando, y el banco que falta.
"""

from __future__ import annotations

import pytest

from tests.entorno import necesita_todas_las_voces
from tests.entorno import necesita_voces

from voz.idioma import (
    FRASES,
    IDIOMAS,
    PARADA,
    VENTANA,
    frase,
    lexico_de_parada,
)


# --- 1. EL CATALOGO NO PUEDE TENER HUECOS ---------------------------------


def test_todas_las_frases_estan_en_los_dos_idiomas() -> None:
    """Una frase a medias se oye en español en mitad de una conversacion
    en ingles. Es la salida honesta -- se nota --, pero se cuenta aqui
    para que la deuda no crezca sin que nadie la vea."""
    faltan = [c for c, formas in FRASES.items()
              if set(formas) != set(IDIOMAS)]
    assert not faltan, f"frases sin los dos idiomas: {faltan}"


def test_los_huecos_de_formato_coinciden_entre_idiomas() -> None:
    """>>> ESTE ES EL QUE REVIENTA EN CALIENTE <<<

    Si la version inglesa de "Abro {}, en {}" se escribe con un solo
    `{}`, la llamada peta con IndexError EN EL MOMENTO DE HABLAR, o sea
    en mitad de un turno, y no al arrancar. Se cuenta aqui, que sale
    gratis.
    """
    malas = []
    for clave, formas in FRASES.items():
        cuentas = {i: t.count("{}") for i, t in formas.items()}
        if len(set(cuentas.values())) != 1:
            malas.append(f"{clave}: {cuentas}")
    assert not malas, f"huecos distintos entre idiomas: {malas}"


def test_una_clave_que_no_existe_revienta_al_llamarla() -> None:
    """Y no devuelve cadena vacia: una frase muda no se distingue de un
    cuelgue, que es el modo de fallo que este proyecto persigue."""
    with pytest.raises(KeyError):
        frase("no_existe_esta_clave")


# --- 2. LA PUERTA HABLADA SIGUE DICIENDO LAS TRES COSAS (JC-0002) ---------


def test_la_peticion_de_permiso_inglesa_conserva_las_tres_partes() -> None:
    """>>> SI ESTO SE AFLOJA, SE REABRE JC-0002, NO SE ARREGLA EL TEST <<<

    La frase con la que se pide permiso vale porque dice QUE se va a
    hacer, CUANTOS y CUALES, y termina ofreciendo las dos respuestas en
    alto. Una traduccion mas corta o mas elegante que se coma cualquiera
    de las tres degrada el consentimiento a un "si" reflejo, que es
    exactamente lo que aquella decision existia para impedir.
    """
    from puente.politica import Decision, Veredicto
    from puente.protocolo import Puerta
    from voz.permiso import pedir

    puerta = Puerta(id_peticion="1", herramienta="Bash",
                    entrada={"command": "rm a.txt b.txt c.txt"},
                    descripcion="borrar", id_uso="u1")
    decision = Decision(Veredicto.ENDURECER, "deletes files",
                        "orden_destructiva",
                        ("C:/p/a.txt", "C:/p/b.txt", "C:/p/c.txt"))
    dicho = pedir(puerta, decision, "C:/p", idioma="en").frase

    assert "deletes files" in dicho          # QUE
    assert "three" in dicho                  # CUANTOS, en palabras
    assert "a.txt" in dicho and "c.txt" in dicho   # CUALES
    assert dicho.rstrip(".").endswith("yes or no")  # las dos respuestas


def test_los_numeros_se_dicen_en_palabras_en_los_dos_idiomas() -> None:
    """Un TTS leyendo "3" en mitad de una frase corta suena a maquina."""
    from voz.permiso import _en_palabras

    assert _en_palabras(3, "es") == "tres"
    assert _en_palabras(3, "en") == "three"
    # Por encima de diez se dice la cifra, en los dos.
    assert _en_palabras(37, "en") == "37"


def test_la_carpeta_se_nombra_cuando_la_accion_SALE_del_directorio() -> None:
    """Ahi vive el error caro: dos archivos con el mismo nombre."""
    from voz.permiso import _nombrar

    assert _nombrar("C:/p/a.txt", "C:/p", "en") == "a.txt"
    assert _nombrar("C:/otra/a.txt", "C:/p", "en") == "a.txt, in otra"


# --- 3. EL LEXICO DE PARADA NO ES UNA TRADUCCION --------------------------


def test_en_ingles_stop_NO_es_inequivoca() -> None:
    """>>> EL HALLAZGO DE JC-0018 <<<

    En español "stop" es un extranjerismo que casi nadie suelta sin
    querer, y por eso era inequivoco. En ingles es el verbo con el que se
    piden cosas legitimas cada dos por tres.
    """
    assert "stop" in PARADA["es"].inequivocas
    assert "stop" not in PARADA["en"].inequivocas
    assert "stop" in PARADA["en"].ambiguas


@pytest.mark.parametrize("dicho", [
    "stop the server",
    "stop the container",
    "stop the build and try again",
    "cancel the deployment",
])
def test_una_orden_de_trabajo_inglesa_NO_para_a_jarvis(dicho: str) -> None:
    """Lo que este test protege es media docena de ordenes normales.

    Si alguien "arregla" el lexico ingles copiando el español, todas
    estas pasan a parar el turno, y el sintoma es Jarvis cortandose solo
    a mitad de trabajo sin que nada de error.
    """
    from voz.parada import Veredicto, mirar

    assert mirar(dicho, "en").veredicto is Veredicto.SIGUE


@pytest.mark.parametrize("dicho", ["stop", "stop it", "cancel", "abort"])
def test_una_parada_inglesa_de_verdad_SI_para(dicho: str) -> None:
    from voz.parada import Veredicto, mirar

    assert mirar(dicho, "en").veredicto is Veredicto.PARA


def test_el_español_sigue_comportandose_igual() -> None:
    """Añadir ingles no puede mover el idioma que SI esta medido."""
    from voz.parada import Veredicto, mirar

    assert mirar("para", "es").veredicto is Veredicto.PARA
    assert mirar("cancela", "es").veredicto is Veredicto.PARA
    assert (mirar("para el informe que te pedi ayer", "es").veredicto
            is Veredicto.SIGUE)


def test_la_ventana_del_ingles_es_MAS_CORTA_y_esta_sin_medir() -> None:
    """>>> LA CIFRA QUE NO SE PUEDE CITAR COMO MEDIDA <<<

    El 4 del español sale de las tres paradas del corpus real (1, 1 y 3
    palabras). El 2 del ingles esta RAZONADO: "stop the server" son tres
    y con la ventana española se comeria la orden. `medido` lo dice, y
    este test existe para que nadie ponga True sin grabar nada.
    """
    assert PARADA["es"].palabras_max == 4
    assert PARADA["es"].medido is True
    assert PARADA["en"].palabras_max == 2
    assert PARADA["en"].medido is False, (
        "si esto es True, tiene que haber un banco de paradas en ingles")


# --- 4. LAS ORDENES DE VENTANA SIGUEN SIENDO ESTRECHAS --------------------


@pytest.mark.parametrize("dicho", [
    "shut down the container",
    "close the window",
    "open the file",
    "show me the log",
    "hide the column",
])
def test_una_orden_de_trabajo_no_mueve_la_ventana(dicho: str) -> None:
    """La regla del español ("abrete" es reflexivo y no significa nada
    mas") no tiene equivalente en ingles, asi que se cumple de otra
    manera: formas de tres palabras que suenan raras a proposito. Esa
    rareza ES el mecanismo."""
    from voz.ventana import Veredicto, interpretar

    assert interpretar(dicho, "en").veredicto is Veredicto.NO_ES


def test_las_tres_ordenes_inglesas_funcionan() -> None:
    from voz.ventana import Veredicto, interpretar

    assert interpretar("show yourself", "en").veredicto is Veredicto.MOSTRAR
    assert interpretar("hide yourself", "en").veredicto is Veredicto.ESCONDER
    assert interpretar("shut yourself down", "en").veredicto is Veredicto.APAGAR


def test_los_dos_idiomas_declaran_las_MISMAS_tres_ordenes() -> None:
    assert set(VENTANA["es"]) == set(VENTANA["en"]) == {
        "mostrar", "esconder", "apagar"}


# --- 5. LA VOZ TIENE QUE HABLAR EL IDIOMA QUE JARVIS DICE HABLAR ----------


@necesita_voces
@necesita_todas_las_voces
def test_hay_una_voz_de_piper_de_cada_idioma_en_disco() -> None:
    """>>> UN PERFIL SIN MODELO ES UNA OPCION DECORATIVA <<<

    Lo caza tambien `test_voz_perfil.py`, y aqui se repite desde el otro
    lado: si algun dia se anade un idioma, la voz se baja el mismo dia o
    "ingles" se convierte en un ajuste que no hace nada.
    """
    from voz.idioma import VOCES
    from voz.tts import voces_disponibles

    disponibles = set(voces_disponibles())
    for idioma, candidatas in VOCES.items():
        assert disponibles & set(candidatas), (
            f"no hay ninguna voz de '{idioma}' en disco: {candidatas}")


@pytest.mark.idioma_real  # prueba la RESOLUCION del idioma:
# necesita el `hablado` de verdad, no el que fija `conftest`.
def test_una_voz_del_idioma_equivocado_se_RECHAZA(monkeypatch) -> None:
    """No revienta sola: hay que hacerla reventar.

    Piper sintetiza por fonemas del idioma con el que se entreno la voz.
    Una voz española leyendo ingles no da ninguna excepcion -- produce
    ingles con fonetica española --, asi que sin esta comprobacion el
    unico sintoma seria "se oye raro".

    >>> LEIA EL PERFIL DEL AUTOR, Y SE CAYO EL 2026-09-09 <<<
    El comentario decia que el perfil activo del proyecto era el espanol,
    dejo de serlo: el usuario puso la voz en ingles desde el panel y
    `config/ajustes.yaml` paso a `voz.perfil: jarvis_en`. Entonces el
    perfil SI cuadraba con el idioma, `perfil_activo()` no levantaba, y
    el test fallaba **por lo contrario de lo que vigila** -- el codigo
    estaba haciendo justo lo correcto.
    Ahora el perfil que no cuadra se construye AQUI. Un test sobre una
    combinacion prohibida no puede depender de que quien lo corra la
    tenga puesta.
    """
    import voz.idioma as mod_idioma
    from voz.perfil import Perfil, PerfilError, _comprobar_idioma

    monkeypatch.setattr(mod_idioma, "hablado", lambda *a, **k: "en")
    español = Perfil(clave="jarvis", nombre="Jarvis",
                     tts_voz="es_ES-davefx-medium",
                     wake_words=("hey_jarvis",))
    with pytest.raises(PerfilError) as fallo:
        _comprobar_idioma(español)
    assert "fonetica" in str(fallo.value)


def test_una_voz_de_idioma_desconocido_NO_se_rechaza(monkeypatch) -> None:
    """Tres respuestas: coincide / no coincide / no se sabe.

    Una voz propia, con un nombre que no empieza por un prefijo
    reconocible, no se declara mala: denegar ahi convertiria una voz
    legitima en un Jarvis que no arranca.
    """
    import voz.idioma as mod_idioma
    from voz.perfil import Perfil, _comprobar_idioma

    monkeypatch.setattr(mod_idioma, "hablado", lambda *a, **k: "en")
    propia = Perfil(clave="mia", nombre="Mia", tts_voz="mivoz-custom",
                    wake_words=("hey_jarvis",))
    _comprobar_idioma(propia)     # no levanta


# --- 6. LO QUE ESCUCHA Y LO QUE TRANSCRIBE --------------------------------


def test_el_stt_sigue_al_idioma_de_la_voz(monkeypatch) -> None:
    """Sin esto, poner Jarvis en ingles dejaria a Whisper transcribiendo
    ingles como si fuera español: el fallo que no da error."""
    import voz.idioma as mod_idioma
    from voz.stt import STT

    monkeypatch.setattr(mod_idioma, "hablado", lambda *a, **k: "en")
    assert STT._idioma() == "en"


def test_el_ancla_cambia_de_idioma_y_solo_una_esta_medida() -> None:
    from voz.idioma import ancla

    assert "bloc de notas" in ancla("es")
    assert "Notepad" in ancla("en")
    assert ancla("es") != ancla("en")


def test_el_ritual_de_ADR_0029_tiene_su_version_inglesa() -> None:
    """La de FABRICA tiene una por idioma, y eso no cambio.

    >>> Y SE PREGUNTA A `voz.idioma`, NO A `primera_pregunta` <<<
    Desde el 2026-09-05 aquella mira tres fuentes y la primera es lo que
    el usuario haya escrito en su panel. Preguntarle aqui haria que este
    test dependiera del `config/ajustes.yaml` de la maquina: pasaria hoy
    y fallaria el dia que el usuario escribiera su frase, que es
    exactamente cuando la funcion estaria haciendo lo correcto. Lo que
    fija este archivo es el diccionario por idioma; la resolucion entera
    la fija `tests/test_ritual_del_usuario.py`, con su config aparte.
    """
    from voz.idioma import ritual

    assert ritual("es") == "hola, en que nos quedamos?"
    assert ritual("en") == "hi, where did we leave off?"


# --- 7. EL AJUSTE DICE LO QUE CUESTA --------------------------------------


def test_el_ajuste_de_voz_es_DISTINTO_del_de_pantalla() -> None:
    """>>> ATARLOS HABRIA SIDO EL ERROR <<<

    `ui.idioma` es gratis y reversible. Este necesita una voz de Piper en
    disco y deja la transcripcion sin su ancla medida. Si fueran uno
    solo, poner la pantalla en ingles se llevaria la voz por delante sin
    avisar.
    """
    from nucleo.ajustes import catalogo

    claves = {a.clave for a in catalogo()}
    assert {"ui.idioma", "voz.idioma"} <= claves

    voz_ = next(a for a in catalogo() if a.clave == "voz.idioma")
    # No se aplica en caliente: los modelos se cargan al arrancar.
    assert voz_.aplica == "reiniciar"
    # Y dice que no esta medido, que es la mitad honesta.
    #
    # >>> BUSCABA LA FRASE Y AHORA BUSCA LA PROMESA (2026-09-09) <<<
    # Antes exigia el literal "no hay banco". El aviso cambio el dia que
    # el usuario decidio que NO va a grabar el banco ingles, y el test
    # fallo por la redaccion cuando lo que tiene que proteger es lo que
    # se AFIRMA. Peor todavia: el texto viejo decia "todavia no hay
    # banco", y ese *todavia* prometia algo que no viene. Un aviso que
    # promete una medicion que nadie va a hacer es la version amable de
    # citar como medido lo que no lo esta, que es lo que
    # `LexicoDeParada.medido` existe para impedir.
    aviso = voz_.aviso or ""
    assert "medid" in aviso, "el aviso ya no dice que el ingles no esta medido"
    assert "todavia" not in aviso.lower(), (
        "el aviso vuelve a prometer un banco que nadie va a grabar")


def test_un_idioma_de_voz_que_no_existe_cae_al_de_serie(monkeypatch) -> None:
    import nucleo.ajustes as aj
    from voz.idioma import hablado

    monkeypatch.setattr(aj, "valor_de", lambda *a, **k: "klingon")
    assert hablado() == "es"
