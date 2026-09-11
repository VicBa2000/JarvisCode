"""Tests de JC-0002: pedir permiso hablando y entender la respuesta.

>>> ESTE ES EL MODULO DONDE EQUIVOCARSE EJECUTA ALGO <<<
Todo lo demas de la capa de voz se puede repetir si sale mal. Una
aprobacion mal entendida no: se ejecuta. Por eso los casos de aqui salen
de las PUERTAS REALES capturadas en `eval/trazas_claude_code/` pasadas
por la politica de verdad, y no de una `Decision` escrita a mano — que es
justamente lo que no probaria la unica propiedad que importa: **que la
frase hablada y la tarjeta de la consola nombren LO MISMO**.
"""

from __future__ import annotations

import pytest

from puente.politica import Veredicto, decidir
from puente.protocolo import Puerta, interpretar
from voz.permiso import NOMBRES_MAXIMOS, Respuesta, pedir
from voz.permiso import interpretar as leer
from voz.stt import Transcripcion

DIRECTORIO = r"C:\proyectos\carpetadepruebas"


def puertas_de(project_root, nombre: str) -> list[Puerta]:
    ruta = project_root / "eval" / "trazas_claude_code" / f"{nombre}.jsonl"
    if not ruta.is_file():
        pytest.skip(f"falta la traza {nombre}.jsonl")
    puertas = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        puertas.extend(e for e in interpretar(linea) if isinstance(e, Puerta))
    return puertas


@pytest.fixture
def puerta_real(project_root) -> Puerta:
    puertas = puertas_de(project_root, "denegada")
    assert puertas, "la traza tenia que traer una puerta"
    return puertas[0]


def decision_de(puerta: Puerta):
    return decidir(puerta, directorio_sesion=DIRECTORIO)


class TestQueLasDosFormasNombrenLoMismo:
    """La regla de JC-0002, puesta en codigo:

    "LAS DOS FORMAS TIENEN QUE NOMBRAR LO MISMO que muestra la consola:
     si divergen, se aprueba una cosa y se ejecuta otra."
    """

    def test_la_frase_sale_de_la_decision_y_no_de_otro_sitio(self,
                                                             puerta_real):
        decision = decision_de(puerta_real)
        assert decision.hay_que_preguntar
        peticion = pedir(puerta_real, decision, directorio=DIRECTORIO)
        # El motivo de la politica -- lo que la consola pinta como
        # `motivo` -- aparece literal en lo que se locuta.
        assert decision.motivo in peticion.frase
        assert peticion.elementos == tuple(
            e for e in decision.elementos if e)

    def test_dice_CUANTOS_elementos_toca(self, puerta_real):
        """Es la mitad de lo que JC-0002 pide: cuantos y cuales."""
        peticion = pedir(puerta_real, decision_de(puerta_real),
                         directorio=DIRECTORIO)
        assert "Es uno:" in peticion.frase
        assert peticion.se_nombraron_todos

    def test_y_los_NOMBRA(self, puerta_real):
        import os

        decision = decision_de(puerta_real)
        nombre = os.path.basename(decision.elementos[0])
        peticion = pedir(puerta_real, decision, directorio=DIRECTORIO)
        assert nombre in peticion.frase

    def test_con_muchos_manda_el_RECUENTO_y_se_dice_que_hay_mas(self,
                                                                puerta_real):
        """Con mas de tres, lo que informa es cuantos son: una lista de
        siete nombres dictada no se retiene."""
        from dataclasses import replace

        muchos = tuple(f"{DIRECTORIO}\\archivo_{i}.txt" for i in range(7))
        peticion = pedir(puerta_real,
                         replace(decision_de(puerta_real), elementos=muchos),
                         directorio=DIRECTORIO)
        assert "Son siete" in peticion.frase
        assert "entre ellos" in peticion.frase
        assert peticion.cuantos == NOMBRES_MAXIMOS
        assert peticion.se_nombraron_todos is False


class TestComoSuena:
    def test_no_se_locuta_la_ruta_entera(self, puerta_real):
        """Una ruta absoluta dictada no es una frase: es una cadena de
        caracteres, y el oyente llega al final sin entender nada."""
        peticion = pedir(puerta_real, decision_de(puerta_real),
                         directorio=DIRECTORIO)
        assert "C:\\" not in peticion.frase
        assert len(peticion.frase) < 200

    def test_pero_SI_la_carpeta_cuando_es_otra(self, puerta_real):
        """Ahi vive el error caro: dos archivos con el mismo nombre en
        dos carpetas distintas. La puerta de esta traza toca algo FUERA
        del directorio de la sesion, que es justo el caso."""
        decision = decision_de(puerta_real)
        assert decision.regla == "ruta_fuera"
        assert ", en " in pedir(puerta_real, decision,
                                directorio=DIRECTORIO).frase

    def test_dentro_del_proyecto_no_se_dice_la_carpeta(self, puerta_real):
        """Repetir "en carpetadepruebas" en cada permiso es ruido: es donde
        esta todo."""
        from dataclasses import replace

        dentro = (f"{DIRECTORIO}\\informe.pdf",)
        frase = pedir(puerta_real,
                      replace(decision_de(puerta_real), elementos=dentro),
                      directorio=DIRECTORIO).frase
        assert "informe.pdf" in frase
        assert ", en " not in frase

    def test_la_pregunta_ensena_la_respuesta(self, puerta_real):
        """Lo que cuenta como "si" es una lista cerrada, asi que hay que
        decirle al usuario que conteste "si o no". Desconcertarle justo
        en el momento en que consiente es lo que no se puede hacer."""
        frase = pedir(puerta_real, decision_de(puerta_real),
                      directorio=DIRECTORIO).frase
        assert frase.rstrip().endswith("Contesta si o no")


class TestQueCuentaComoSi:
    @pytest.mark.parametrize("dicho", ["si", "Si.", "Vale, adelante.",
                                       "Adelante", "Confirmo.", "Si, hazlo"])
    def test_afirmativas(self, dicho):
        assert leer(dicho) is Respuesta.SI

    @pytest.mark.parametrize("dicho", ["no", "No.", "No, para", "ni de broma",
                                       "no se", "claro que si", "espera"])
    def test_todo_lo_demas_es_no(self, dicho):
        """Incluido "claro que si", y es a proposito: inventar deteccion
        de afirmativas en el unico sitio donde equivocarse EJECUTA algo
        cuesta un archivo; repetir cuesta tres segundos."""
        assert leer(dicho) is Respuesta.NO

    def test_la_coma_del_STT_no_convierte_un_si_en_un_no(self):
        """`small` entrega "Vale, adelante." con coma y punto. Sin
        normalizar, "vale," no casa con "vale" y una autorizacion clara
        salia NO."""
        assert leer("Vale, adelante.") is Respuesta.SI

    def test_la_afirmativa_tiene_que_ABRIR_la_frase(self):
        """"no, si me lo dijo" empieza por "no", y eso es lo que vale."""
        assert leer("no, si me lo dijo") is Respuesta.NO


class TestLaTerceraSalida:
    """El silencio NO es un no, y esa es la decision de esta hoja.

    `seguridad/aprobacion.py` trata el silencio como un no, y para una
    consola es correcto. Aqui no: una puerta sin contestar deja la sesion
    esperando (medido, sin timeout), y sobre esa espera se construye el
    escalado a Telegram. Denegar por silencio convertiria "no estaba
    delante" en "dijo que no".
    """

    def _sin_habla(self, texto: str) -> Transcripcion:
        return Transcripcion(texto=texto, latencia_s=0.3,
                             duracion_audio_s=2.0, prob_sin_habla=0.9,
                             idioma="es", modelo="small",
                             hay_habla_vad=False)

    def test_si_nadie_hablo_no_es_ni_si_ni_no(self):
        transcripcion = self._sin_habla("si")
        assert transcripcion.sin_habla is True
        assert leer(transcripcion) is Respuesta.SIN_RESPUESTA

    def test_un_texto_vacio_tampoco(self):
        assert leer("") is Respuesta.SIN_RESPUESTA
        assert leer("   ") is Respuesta.SIN_RESPUESTA

    def test_con_habla_de_verdad_si_decide(self):
        buena = Transcripcion(texto="si", latencia_s=0.3,
                              duracion_audio_s=2.0, prob_sin_habla=0.05,
                              idioma="es", modelo="small",
                              hay_habla_vad=True)
        assert leer(buena) is Respuesta.SI


class TestContraTodasLasPuertasDeLasTrazas:
    def test_ninguna_frase_se_queda_sin_decir_que_pasa(self, project_root):
        """Contar cuantas veces ocurre el suceso antes de leer
        el resultado. Son pocas puertas, pero son TODAS las reales que
        hay en disco."""
        vistas = 0
        for nombre in ("denegada", "permitida", "parada"):
            for puerta in puertas_de(project_root, nombre):
                decision = decidir(puerta, directorio_sesion=DIRECTORIO)
                if decision.veredicto is Veredicto.PERMITIR:
                    continue
                peticion = pedir(puerta, decision, directorio=DIRECTORIO)
                vistas += 1
                assert decision.motivo in peticion.frase
                assert peticion.frase.rstrip().endswith("Contesta si o no")
                assert "\n" not in peticion.frase
        assert vistas >= 2, f"solo se probaron {vistas} puertas"
