"""Las opciones que se recortan de una pregunta en prosa.

>>> LO QUE ESTE ARCHIVO PROTEGE ES, OTRA VEZ, UNA FRASE <<<
La de JC-0016:

    lo peor que puede pasar si te roban el token es que alguien conteste
    una pregunta de diseño en tu nombre; NO que te borre algo.

Contestar una pregunta en prosa es `Sesion.mandar`, o sea UN TURNO
NUEVO, que es justo lo que aquella decision prohibio. Lo unico que la
mantiene en pie es que el texto que viaja NO lo escriba quien manda el
mensaje: son recortes literales de lo que escribio Claude. Este archivo
comprueba las dos mitades de eso -- que se recorta bien, y que cuando no
se sabe recortar NO se ofrece nada.

Los casos vienen de `logs/puente/*.jsonl`: 42 sesiones reales,
36 preguntas que cierran turno. Se copian literales, no se inventan.
Sonda que los saca: `python -m eval.mirar_preguntas`.
"""

from __future__ import annotations

import pytest

from voz.resumen import (FORMA_DISYUNTIVA, FORMA_DUDOSA, FORMA_NINGUNA,
                         FORMA_SI_NO, opciones_de_pregunta)


class TestLoQueSeRecortaEsLiteral:
    """>>> EL TEST QUE SOSTIENE LA ACOTACION ENTERA <<<

    Si esto cae, por el movil puede viajar texto que Claude no escribio,
    y entonces Telegram deja de "contestar" y pasa a CONDUCIR.
    """

    @pytest.mark.parametrize("pregunta", [
        "¿Arranco con la verificación de verde y el paso 1, o prefieres "
        "que antes registre la decision en el documento?",
        "¿Quieres que abra el PDF de la rutina otra vez, o el navegador "
        "Edge?",
        "¿Retomamos el de la cédula profesional/titulación, o es otro "
        "tema distinto que quieres abrir?",
    ])
    def test_cada_etiqueta_esta_DENTRO_del_texto_de_claude(self, pregunta):
        opciones = opciones_de_pregunta(pregunta)
        assert opciones.contestable
        for etiqueta in opciones.etiquetas:
            assert etiqueta in pregunta, (
                f"{etiqueta!r} no es un recorte de lo que escribio Claude")

    def test_el_si_no_es_la_UNICA_forma_que_no_es_literal(self):
        """Y esta escrito a proposito, no es un descuido.

        "Si" y "No" los ponemos nosotros. Lo que los hace aceptables es
        que no llevan instruccion propia: toda la instruccion esta en la
        proposicion que escribio Claude. Si algun dia hay que apretar
        esto, es la primera forma que hay que mirar.
        """
        opciones = opciones_de_pregunta(
            "¿Quieres que verifique que partimos de verde y arranque "
            "core/memory/?")
        assert opciones.forma == FORMA_SI_NO
        assert opciones.etiquetas == ("Si", "No")


class TestLasTrampasReales:
    """Las dos que estaban en los logs y que un `split(" o ")` se traga."""

    def test_un_o_que_une_DOS_PREGUNTAS_no_son_opciones(self):
        """Real: el `o` no separa alternativas, encadena preguntas.

        Numerarlo mandaria al movil "Que necesitas que te muestre" como
        si fuera algo elegible.
        """
        opciones = opciones_de_pregunta(
            "¿Qué necesitas que te muestre o en qué puedo ayudarte?")
        assert not opciones.contestable
        assert opciones.forma == FORMA_DUDOSA

    def test_un_y_barra_o_NO_es_excluyente(self):
        """Real. "y/o" son dos cosas que se pueden querer LAS DOS.

        Ofrecer un numero obligaria a elegir donde el usuario podia
        pedir ambas.
        """
        opciones = opciones_de_pregunta(
            '¿Quieres que afine el regex del script (para no seguir '
            'contando "objetivo" como falso positivo) y/o que sigamos '
            'juntando muestras?')
        assert not opciones.contestable
        assert opciones.forma == FORMA_DUDOSA

    def test_una_BATERIA_de_preguntas_no_es_una_eleccion(self):
        """Real. Tres preguntas seguidas piden informacion, no una
        eleccion: eso se escribe, no se elige con un numero."""
        opciones = opciones_de_pregunta(
            "- ¿De qué trata Nebula? - ¿Ya existe código en otra "
            "carpeta? - ¿Qué es lo último que se hizo?")
        assert not opciones.contestable
        assert opciones.forma == FORMA_NINGUNA


class TestLaComaQueNoSepara:
    """>>> ESTAS DOS SALIERON DE MIRAR LA SONDA, NO DE IMAGINAR <<<

    La primera version partia las listas en serie por las comas y se
    comia aposiciones y oraciones de relativo, inventando una tercera
    opcion. La regla que las separa es gramatical: en "A, B, C, o D" las
    comas van SIEMPRE delante del `o`. Una coma detras del `o` no separa
    lista, porque la lista ya termino.
    """

    def test_un_aposito_detras_del_o_NO_se_parte(self):
        opciones = opciones_de_pregunta(
            "¿Seguimos por el paso (A) — la prueba manual en la app — o "
            "preferís ir directo al (B), el A/B contra el modelo real?")
        assert len(opciones.etiquetas) == 2, (
            f"se invento una opcion: {opciones.etiquetas}")
        assert "el A/B contra el modelo real" in opciones.etiquetas[1]

    def test_una_oracion_de_relativo_detras_del_o_tampoco(self):
        opciones = opciones_de_pregunta(
            "¿Seguimos por el paso (A) o preferís lanzar directamente el "
            "(B) A/B en vivo, que es la prueba que realmente valida la "
            "decisión del 24-ago?")
        assert len(opciones.etiquetas) == 2, (
            f"se invento una opcion: {opciones.etiquetas}")
        assert not any(e.startswith("que es la prueba")
                       for e in opciones.etiquetas)

    def test_una_serie_de_verdad_SI_se_parte(self):
        """Y esta es la otra mitad: no vale arreglarlo dejando de partir.

        "un archivo, una carpeta, una aplicacion" son tres opciones, y
        mandarlas como un grumo sería mandar al movil algo que nadie
        ofrecio como una sola cosa.
        """
        opciones = opciones_de_pregunta(
            "Por ejemplo, ¿un archivo, una carpeta, una aplicación, o te "
            "referías a otra cosa?")
        assert opciones.forma == FORMA_DISYUNTIVA
        assert len(opciones.etiquetas) == 4
        assert opciones.etiquetas[:3] == ("un archivo", "una carpeta",
                                          "una aplicación")

    def test_las_comas_DENTRO_de_un_parentesis_no_cuentan(self):
        """Real. Sin esto, la enumeracion de un inciso se convertiria en
        opciones sueltas sin sentido."""
        opciones = opciones_de_pregunta(
            "¿Buscas noticias de algún tema específico "
            "(mercados/economía, más recientes en general, tecnología, "
            "etc.) o de algún país en particular?")
        assert len(opciones.etiquetas) == 2


class TestLoQueNoSeOfrece:
    """Cuando no hay nada que numerar, NO se numera nada.

    La direccion segura: se avisa igual por el movil y se contesta en la
    consola. Ofrecer un numero de mas es lo unico que no se puede hacer.
    """

    @pytest.mark.parametrize("pregunta", [
        "¿En qué te gustaría trabajar hoy?",
        "¿Qué fue lo que pasó que te dejó con esta tristeza?",
        "¿Podrías precisar a qué ventana te refieres?",
        "¿Podés aclarar?",
    ])
    def test_una_pregunta_abierta_de_verdad_no_da_opciones(self, pregunta):
        assert not opciones_de_pregunta(pregunta).contestable

    def test_una_cortesia_con_forma_de_si_no_TAMPOCO(self):
        """"¿Podrias precisar...?" se contesta "si" y no le has dado
        nada. Las cortesias se quedan fuera de `ABRE_SI_NO` a proposito:
        la lista es de DECISIONES."""
        opciones = opciones_de_pregunta("¿Podrías especificar?")
        assert opciones.etiquetas == ()

    def test_vacio_no_revienta(self):
        assert opciones_de_pregunta("").etiquetas == ()
        assert opciones_de_pregunta("   ").etiquetas == ()


class TestLaTerceraSalidaSeCuentaAparte:
    """La tercera salida y la magnitud continua a la vez.

    `dudosa` se COMPORTA como `ninguna` -- no se ofrece nada --, pero no
    es lo mismo y por eso no se colapsa: si ese numero crece, hay
    material real para afinar el extractor. Colapsadas, no habria forma
    de enterarse de que se esta quedando corto.
    """

    def test_dudosa_y_ninguna_no_son_el_mismo_valor(self):
        dudosa = opciones_de_pregunta(
            "¿Qué necesitas que te muestre o en qué puedo ayudarte?")
        ninguna = opciones_de_pregunta("¿En qué te gustaría trabajar hoy?")
        assert dudosa.forma == FORMA_DUDOSA
        assert ninguna.forma == FORMA_NINGUNA
        assert dudosa.forma != ninguna.forma
        # ...y las dos se comportan igual, que es lo seguro.
        assert not dudosa.contestable and not ninguna.contestable


class TestElEnunciadoQueSeEnsena:
    def test_se_recorta_la_basura_de_delante(self):
        """Real: una de las 36 arrastra los restos de una lista numerada
        delante del signo de apertura. Mandar eso al movil es ilegible, y
        recortarlo en cada canal serian dos recortadores."""
        opciones = opciones_de_pregunta(
            "Ollama corriendo (qwen2.5:7b)\n"
            "3. cd services\\api && python -m pytest tests -q\n"
            "4. alembic check\n\n"
            "¿Quieres que arranque con esa verificación y luego empiece "
            "el gate de coste diario?")
        assert opciones.enunciado.startswith("¿Quieres que arranque")
        assert "alembic" not in opciones.enunciado
