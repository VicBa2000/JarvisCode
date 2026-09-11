"""Tests de `voz/resumen.py`: de una respuesta escrita a un oido (JC-0004).

>>> LA ENTRADA SON RESPUESTAS DE CLAUDE CODE DE VERDAD <<<
Se leen de `eval/trazas_claude_code/*.jsonl`, que son capturas crudas de
sesiones reales. La regla otra vez: un resumidor probado con "Hola.
Adios." pasa siempre y no dice nada, porque el problema no es cortar
frases -- es que una respuesta real trae markdown, listas, rutas entre
comillas invertidas y una entradilla que no contesta nada.

La que manda aqui es `respuesta_larga.jsonl` (capturada el 2026-08-25):
2035 caracteres y diez puntos. Su primera frase es "Un proyecto tipico de
asistente de voz en Python se organiza asi:", y locutar ESO era lo que
hacia la version ingenua.
"""

from __future__ import annotations

import json

import pytest

from voz.resumen import (
    LIMITE_HABLADO,
    para_un_oido,
    pregunta_final,
    primeras_frases,
    puntos_de_lista,
    sin_markdown,
)


def respuesta(project_root, nombre: str) -> str:
    ruta = project_root / "eval" / "trazas_claude_code" / f"{nombre}.jsonl"
    if not ruta.is_file():
        pytest.skip(f"falta la traza {nombre}.jsonl")
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        mensaje = json.loads(linea)
        if mensaje.get("type") == "result" and mensaje.get("result"):
            return str(mensaje["result"])
    pytest.skip(f"la traza {nombre}.jsonl no trae respuesta")


@pytest.fixture
def larga(project_root) -> str:
    return respuesta(project_root, "respuesta_larga")


class TestContraUnaRespuestaLargaDeVerdad:
    def test_dos_mil_caracteres_no_se_locutan(self, larga):
        assert len(larga) > 1500
        assert len(para_un_oido(larga).hablado) <= LIMITE_HABLADO + 60

    def test_dice_CUANTOS_puntos_hay(self, larga):
        """Lo que informa de una lista es el recuento, no la entradilla.

        Y es el mismo material que pedira JC-0002 para las aprobaciones:
        cuantos y cuales elementos toca.
        """
        resumen = para_un_oido(larga)
        assert resumen.elementos == 10
        assert "10 puntos" in resumen.hablado

    def test_no_se_queda_en_la_entradilla(self, larga):
        """"...se organiza asi." era todo lo que decia la version
        ingenua: suena a que el asistente se colgo a mitad."""
        hablado = para_un_oido(larga).hablado
        assert not hablado.rstrip().endswith("organiza asi.")
        assert "El primero:" in hablado

    def test_no_se_locutan_los_asteriscos_ni_las_comillas(self, larga):
        hablado = para_un_oido(larga).hablado
        assert "**" not in hablado
        assert "`" not in hablado

    def test_no_corta_en_una_abreviatura(self, larga):
        """Medido contra esta misma respuesta: partia en "ej." y locutaba
        "el primero: main.py (en la raiz, ej..", que es peor que no
        resumir."""
        assert not para_un_oido(larga).hablado.rstrip().endswith("ej..")

    def test_avisa_de_que_recorto(self, larga):
        """Quien llama tiene que poder decir "el resto esta en la
        consola". Sin esta bandera, el usuario no sabe que hay mas."""
        resumen = para_un_oido(larga)
        assert resumen.recortado is True
        assert resumen.fraccion_hablada < 0.2


class TestLasRespuestasCORTASNoSeTocan:
    """La mayoria de las respuestas de un asistente de voz son de una o
    dos frases. Resumir esas seria empeorarlas."""

    @pytest.mark.parametrize("nombre", ["permitida", "denegada", "pregunta"])
    def test_una_respuesta_corta_se_locuta_entera(self, project_root, nombre):
        texto = respuesta(project_root, nombre)
        resumen = para_un_oido(texto)
        assert resumen.recortado is False
        assert resumen.hablado.strip() == texto.strip()

    def test_un_nombre_de_archivo_no_parte_la_frase(self, project_root):
        """'archivo.txt' y 'resumen.txt' llevan punto y NO son finales de
        frase. Es la razon de que el corte pida espacio detras."""
        hablado = para_un_oido(respuesta(project_root, "permitida")).hablado
        assert "archivo.txt" in hablado
        assert "resumen.txt" in hablado


class TestLasPiezas:
    def test_un_bloque_de_codigo_se_va_entero(self):
        """Leer Python en voz alta no informa a nadie y es lo que mas
        tarda. Lo que hace falta saber es que esta en pantalla."""
        texto = "Hecho.\n```python\nprint('hola')\n```\nYa esta."
        assert "print" not in sin_markdown(texto)

    def test_una_lista_se_separa_de_su_entradilla(self):
        entradilla, puntos = puntos_de_lista(
            "He hecho tres cosas:\n- una\n- dos\n- tres")
        assert entradilla == "He hecho tres cosas:"
        assert puntos == ["una", "dos", "tres"]

    def test_los_numeros_tambien_son_puntos(self):
        _, puntos = puntos_de_lista("Pasos:\n1. uno\n2. dos")
        assert puntos == ["uno", "dos"]

    def test_sin_lista_la_entradilla_es_el_texto_entero(self):
        """Quien llame no tiene que preguntar "era una lista?" aparte."""
        entradilla, puntos = puntos_de_lista("Solo una frase.")
        assert puntos == []
        assert entradilla == "Solo una frase."

    def test_se_corta_por_frases_y_no_por_letras(self):
        dicho, recortado = primeras_frases(
            "Primera frase corta. Segunda frase que ya no cabe entera.", 30)
        assert dicho == "Primera frase corta."
        assert recortado is True

    def test_si_ni_una_frase_cabe_se_corta_por_palabras(self):
        """Feo, pero pronunciable. Cortar a media palabra suena a corte
        de linea telefonica."""
        dicho, recortado = primeras_frases("Una sola frase larguisima "
                                           "que no cabe de ninguna manera.", 20)
        assert recortado is True
        assert not dicho.endswith("larguisi")
        assert len(dicho) <= 20


class TestLosCasosVacios:
    def test_sin_texto_no_se_dice_nada(self):
        """Y no se inventa un "hecho": el usuario tiene que poder
        distinguir que el asistente no dijo nada."""
        assert para_un_oido("").hablado == ""
        assert para_un_oido("   \n  ").hablado == ""

    def test_solo_un_bloque_de_codigo_se_manda_a_la_consola(self):
        """Callarse ahi dejaria al usuario esperando una respuesta que SI
        existe. Y leerle el Python en voz alta no informa a nadie."""
        dicho = para_un_oido("```\nx = 1\n```").hablado
        assert "consola" in dicho
        assert "x = 1" not in dicho


class TestSiLaRESPUESTADejaUnaPreguntaAbierta:
    """Lo que decide si el microfono se abre solo. Se probo con el uso, y
    fallo dos veces antes de estar bien -- las dos por clasificar mal.

    Los casos son las respuestas REALES con interrogante que hay en las
    trazas y en los logs de sesiones del usuario (2026-08-25).
    """

    def test_la_que_termina_preguntando(self, project_root):
        texto = respuesta(project_root, "pregunta_en_prosa")
        assert pregunta_final(texto)

    def test_LA_QUE_LLEVA_UN_CIERRE_DETRAS(self, project_root):
        """El caso que rompio la primera version: la pregunta esta en
        medio y detras va una frase de animo ("¡Vamos a dejar ese
        escritorio como los chorros del oro!"). Un asistente que se queda
        sordo porque le anadieron un cierre amable es justo el fallo que
        se venia a arreglar."""
        texto = respuesta(project_root, "pregunta_con_cierre")
        assert not texto.rstrip().endswith("?")   # por eso fallaba
        pregunta = pregunta_final(texto)
        assert pregunta and pregunta.endswith("?")
        assert "chorros" not in pregunta          # el cierre no es la pregunta

    @pytest.mark.parametrize("nombre", ["permitida", "denegada",
                                        "respuesta_larga", "sin_conexion"])
    def test_una_respuesta_que_no_pregunta_no_abre_nada(self, project_root,
                                                        nombre):
        """La otra mitad, y sin ella esto seria "escuchar siempre"."""
        assert pregunta_final(respuesta(project_root, nombre)) is None

    def test_si_la_respuesta_siguio_a_lo_suyo_no_espera(self):
        """Un interrogante seguido de parrafos era retorico. El umbral es
        la COLA, no la posicion."""
        texto = "¿Que hace esto? " + ("Lo explico con calma. " * 30)
        assert pregunta_final(texto) is None

    def test_el_umbral_es_permisivo_a_proposito(self):
        """No hay ni una respuesta real con interrogante que NO este
        preguntando, o sea que la tasa de falsos no se puede estimar. Con eso,
        manda el coste: abrir el microfono de mas se
        cierra solo en 4 s; no abrirlo deja al usuario hablandole a un
        asistente sordo."""
        from voz.resumen import COLA_MAXIMA
        assert COLA_MAXIMA >= 100
