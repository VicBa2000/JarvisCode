"""Tests de `voz/parada.py`: lo unico que se sigue oyendo mientras trabaja.

>>> LA ENTRADA SALE DEL DISCO, NO DE MI TECLADO <<<
Los casos que importan se leen de `eval/trazas_voz/ordenes_small_ancla.json`,
que es lo que el STT de produccion entrego de verdad al pasarle las 30
ordenes grabadas por el usuario. La regla esta escrita justo para esto:
un test que compara `mirar("para")` no prueba nada, porque el STT no
entrega "para", entrega 'para.'; y 'Cancela' con mayuscula; y 'No, ese
no.' con una coma en medio. Las tres formas rompen una comparacion
ingenua.

La traza se regenera con `python -m eval.sonda_parada --transcribir`
(~65 s). Aqui se lee de disco para no cargar Whisper: un test de un
minuto es un test que no se corre.

Los casos escritos a mano que SI hay son los que el corpus no contiene --
la preposicion enterrada, el desacuerdo con el VAD -- y van marcados
como lo que son.
"""

from __future__ import annotations

import json

import pytest

from voz.parada import Veredicto, mirar, normalizar
from voz.stt import Transcripcion

TRAZA = "eval/trazas_voz/ordenes_small_ancla.json"

# Las que el usuario dicto como paradas, etiquetadas a oido el 2026-08-21.
PARADAS = {26, 27, 29}


@pytest.fixture(scope="module")
def transcripciones(project_root) -> list[dict]:
    ruta = project_root / TRAZA
    if not ruta.is_file():
        pytest.skip(f"falta {TRAZA}; se genera con -m eval.sonda_parada "
                    f"--transcribir")
    return json.loads(ruta.read_text(encoding="utf-8"))


def texto_de(transcripciones: list[dict], indice: int) -> str:
    return next(t["texto"] for t in transcripciones if t["indice"] == indice)


class TestContraLoQueDijoElSTTDeVerdad:
    def test_caza_las_tres_paradas_del_corpus(self, transcripciones):
        """'Cancela', 'para.' y 'No, ese no.' -- con su mayuscula, su
        punto y su coma."""
        for indice in sorted(PARADAS):
            juicio = mirar(texto_de(transcripciones, indice))
            assert juicio.veredicto is Veredicto.PARA, juicio.describe()

    def test_ninguna_de_las_27_ordenes_normales_para_nada(self, transcripciones):
        """La otra mitad del asunto, y la que se olvida: una parada falsa
        detiene trabajo que nadie pidio detener."""
        falsas = [t["texto"] for t in transcripciones
                  if t["indice"] not in PARADAS
                  and mirar(t["texto"]).veredicto is Veredicto.PARA]
        assert falsas == []

    def test_el_corpus_entero_pasa_por_las_dos_ramas(self, transcripciones):
        """Antes de leer un resultado, contar cuantas veces
        ocurrio el suceso. Son 3 paradas y 27 no-paradas; si esto se
        queda en 0 de algo, el test de arriba no ha respondido nada."""
        assert len(transcripciones) == 30
        assert len(PARADAS) == 3


class TestLaNormalizacion:
    def test_quita_mayusculas_tildes_y_puntuacion(self):
        assert normalizar("¡Para YA!") == ["para", "ya"]
        assert normalizar("No, ese no.") == ["no", "ese", "no"]

    def test_un_texto_vacio_no_es_una_parada(self):
        assert mirar("").veredicto is Veredicto.SIGUE
        assert mirar("   ").veredicto is Veredicto.SIGUE


class TestLasInequivocas:
    def test_valen_en_cualquier_sitio_de_la_frase(self):
        """Nadie suelta "cancela" por casualidad, asi que no se le pide
        que abra la frase."""
        juicio = mirar("oye una cosa, cancela lo que estabas haciendo")
        assert juicio.veredicto is Veredicto.PARA
        assert juicio.disparador == "cancela"


class TestLasAmbiguas:
    """La regla dificil, y la que el corpus NO puede probar.

    >>> NINGUNA DE LAS 30 GRABACIONES DICE "para" COMO PREPOSICION <<<
    Asi que esto esta RAZONADO, no medido, y estos tests fijan el
    razonamiento para que no se mueva sin querer. Lo que lo probaria es
    una tanda hablando cerca del microfono mientras Jarvis trabaja.
    """

    def test_sola_o_abriendo_una_frase_corta_es_parada(self):
        assert mirar("para").veredicto is Veredicto.PARA
        assert mirar("para ya").veredicto is Veredicto.PARA
        assert mirar("no, ese no").veredicto is Veredicto.PARA

    def test_enterrada_en_una_frase_larga_no_lo_es(self):
        """"para" aparece cada tres frases en español corriente. Un
        reconocedor que pare con cualquiera no es prudente: es uno que no
        puede trabajar."""
        assert mirar(
            "es un regalo para mi hermana que cumple anos manana"
        ).veredicto is Veredicto.SIGUE

    def test_ni_siquiera_en_lo_que_dice_el_propio_jarvis(self):
        """El caso que MAS va a ocurrir, porque es el audio que esta mas
        cerca del microfono mientras Jarvis habla: su propia voz."""
        assert mirar(
            "he creado la carpeta para tus facturas en documentos"
        ).veredicto is Veredicto.SIGUE

    def test_la_frontera_esta_en_las_palabras_y_no_en_la_suerte(self):
        """Cuatro palabras entran, cinco ya no. Que este numero exista
        escrito es lo que separa una regla de una casualidad."""
        assert mirar("para eso que estas").veredicto is Veredicto.PARA
        assert mirar("para eso que estas haciendo").veredicto is Veredicto.SIGUE


class TestLaTerceraSalida:
    """Si / no / no lo se. La duda no se colapsa contra el no."""

    def _con_desacuerdo(self, texto: str) -> Transcripcion:
        """Texto de parada, pero el VAD dice que ahi no hablo nadie.

        No es un caso inventado por gusto: es el desacuerdo que el propio
        `Transcripcion.sin_habla` existe para representar, y `small` se
        inventa texto ante el silencio 12 de 12 veces (medido el
        2026-08-20).
        """
        return Transcripcion(
            texto=texto, latencia_s=0.5, duracion_audio_s=2.0,
            prob_sin_habla=0.1, idioma="es", modelo="small",
            hay_habla_vad=False,
        )

    def test_texto_de_parada_con_el_vad_en_contra_es_dudosa(self):
        transcripcion = self._con_desacuerdo("para")
        assert transcripcion.sin_habla is True
        assert mirar(transcripcion).veredicto is Veredicto.DUDOSA

    def test_con_el_texto_suelo_esa_pregunta_no_se_ha_hecho(self):
        """`mirar("para")` no puede saber si el VAD estaba de acuerdo, y
        no se finge que si: sale PARA, y quien quiera la tercera salida
        tiene que pasar la transcripcion entera."""
        assert mirar("para").veredicto is Veredicto.PARA

    def test_una_frase_normal_con_el_vad_en_contra_sigue_siendo_sigue(self):
        """La duda solo aparece si ADEMAS sono a parada. Si no, no hay
        nada que dudar."""
        assert mirar(
            self._con_desacuerdo("abre el bloc de notas")
        ).veredicto is Veredicto.SIGUE


class TestLoQueSeVeDespues:
    def test_el_juicio_dice_que_palabra_lo_causo_y_cuantas_habia(self):
        """Magnitud continua, no bandera. Cuando alguien revise
        por que se paro solo, "PARA" a secas no le sirve de nada."""
        juicio = mirar("no, ese no")
        assert juicio.disparador == "no"
        assert juicio.palabras == 3
        assert "no, ese no" in juicio.describe()


class TestElCanalIngles:
    """>>> LA MITAD DE JC-0018 QUE SE PUEDE CERRAR SIN GRABAR NADA <<<

    El lexico ingles se juzga sobre TEXTO, asi que aqui no hace falta ni
    una voz: el numero es real. Lo que sigue abierto es la mitad
    acustica -- si esas frases se OYEN al decirlas --, y eso solo lo
    contesta el banco dictado (`-m eval.stt_bench --grabar --idioma en`).
    Por eso `LexicoDeParada.medido` sigue en False y hay un test abajo
    que impide ponerlo a True sin las grabaciones.
    """

    def test_el_corpus_ingles_entero_se_clasifica_bien(self):
        from eval.stt_bench import ORDENES_EN, PARADAS_EN

        for indice, frase in enumerate(ORDENES_EN, start=1):
            debia = indice in PARADAS_EN
            assert mirar(frase, idioma="en").para is debia, (
                f"{indice} {frase!r}: debia "
                f"{'PARAR' if debia else 'SEGUIR'}")

    def test_las_ordenes_que_EMPIEZAN_como_parada_no_paran(self):
        """>>> SON LA RAZON DE SER DEL CORPUS INGLES <<<

        En ingles no hay imperativo, asi que "stop", "cancel" y "abort"
        abren tanto una parada como una orden normal. Estas tres son las
        que dicen si la ventana de 2 palabras esta bien puesta, y no
        tienen equivalente en español: alli "cancela" es inequivoca.
        """
        from eval.stt_bench import ORDENES_EN, ORDENES_QUE_EMPIEZAN_COMO_PARADA_EN

        for indice in ORDENES_QUE_EMPIEZAN_COMO_PARADA_EN:
            frase = ORDENES_EN[indice - 1]
            assert not mirar(frase, idioma="en").para, (
                f"{frase!r} es trabajo, no una parada")

    def test_la_unica_inequivoca_llega_PARTIDA_desde_el_STT(self):
        """Medido el 2026-09-08 con la sonda: Whisper escribe `nevermind`
        como "Never mind.", en dos palabras. O sea que la unica parada
        inequivoca del ingles NO llega nunca por su camino de inequivoca:
        entra por la ventana corta, gracias a que `never` esta en las
        ambiguas. Sigue parando -- no es un fallo mudo --, pero el diseño
        no puede apoyarse en esa palabra como si llegara entera.
        """
        assert mirar("nevermind", idioma="en").para
        assert mirar("Never mind.", idioma="en").para

    def test_el_lexico_ingles_NO_puede_declararse_medido_sin_banco(self):
        """La ventana de 2 esta RAZONADA. Ponerla a `medido=True` sin las
        grabaciones seria exactamente lo que ese campo existe para
        impedir."""
        from pathlib import Path

        from voz.idioma import lexico_de_parada

        corpus = Path(__file__).resolve().parent.parent / "eval" / "audio_ordenes_en"
        hay_banco = corpus.is_dir() and any(corpus.glob("*.wav"))
        if not hay_banco:
            assert lexico_de_parada("en").medido is False, (
                "el ingles se declara medido y no hay grabaciones en "
                f"{corpus}")
