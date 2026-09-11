"""Tests de la parada: `Fin.parado`, `Sesion.interrumpir` y los oyentes.

Rapidos y sin binario: la aceptacion contra Claude Code de verdad vive en
`tests/test_puente_sesion.py` (marcada `lento`). Lo de aqui se prueba
contra la CAPTURA CRUDA de un turno interrumpido de verdad --
`eval/trazas_claude_code/parada.jsonl`, del 2026-08-25 -- y no contra
JSON escrito a mano, que mediria el test y no el parser.
"""

from __future__ import annotations

import json

import pytest

from puente.protocolo import Fin, interpretar
from puente.sesion import Sesion


@pytest.fixture
def eventos_de_la_parada(project_root):
    ruta = project_root / "eval" / "trazas_claude_code" / "parada.jsonl"
    if not ruta.is_file():
        pytest.skip("falta eval/trazas_claude_code/parada.jsonl")
    eventos = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        eventos.extend(interpretar(linea))
    return eventos


class TestComoSeVeUnaParadaPorDentro:
    def test_el_turno_interrumpido_viene_marcado_como_error(
            self, eventos_de_la_parada):
        """Y esto NO es un detalle de formato: es la razon de que exista
        `parado`. Un turno que el usuario mando parar llega con
        `is_error: true` y `subtype: error_during_execution`."""
        fin = [e for e in eventos_de_la_parada if isinstance(e, Fin)][0]
        assert fin.subtipo == "error_during_execution"
        assert fin.es_error is True
        assert fin.razon_terminal == "aborted_streaming"
        assert fin.texto == ""      # `result` venia a null

    def test_parado_lo_distingue_y_fue_mal_no(self, eventos_de_la_parada):
        fin = [e for e in eventos_de_la_parada if isinstance(e, Fin)][0]
        assert fin.parado is True
        assert fin.fue_mal is True     # las dos cosas a la vez
        assert fin.sin_servidor is False

    def test_el_turno_siguiente_de_la_misma_sesion_esta_sano(
            self, eventos_de_la_parada):
        """La sesion sobrevivio a la parada: mismo `session_id`, contexto
        intacto y un `result` normal."""
        fines = [e for e in eventos_de_la_parada if isinstance(e, Fin)]
        assert len(fines) == 2
        assert fines[1].parado is False
        assert fines[1].fue_mal is False
        assert fines[0].session_id == fines[1].session_id
        assert fines[1].texto.strip()

    def test_las_dos_razones_de_parada_cuentan_como_parada(self):
        """`aborted_streaming` si le pillo escribiendo y `aborted_tools`
        si le pillo encadenando herramientas. Las dos se midieron el
        2026-08-25 con la misma sonda; la traza guardada es de la
        primera, asi que la segunda se fija aqui para que no se pierda.
        """
        def fin(razon: str) -> Fin:
            return Fin(session_id="s", subtipo="error_during_execution",
                       es_error=True, texto="", coste_usd=0.0,
                       duracion_ms=5873, num_turnos=2, razon_terminal=razon)

        assert fin("aborted_tools").parado is True
        assert fin("aborted_streaming").parado is True
        assert fin("api_error").parado is False
        assert fin("completed").parado is False


class TestInterrumpir:
    def test_sin_sesion_viva_no_hay_nada_que_parar(self, tmp_path):
        """Y devuelve False en vez de reventar: que no hubiera nada
        corriendo no es un fallo del usuario que dijo "para"."""
        assert Sesion(tmp_path).interrumpir() is False

    def test_manda_el_control_request_que_el_binario_entiende(self, tmp_path):
        """La forma del mensaje esta medida contra el binario (sonda
        `sonda_parar.py`), asi que se fija aqui: si alguien la cambia, el
        "para" se queda mudo y no lo dice nadie."""
        sesion = Sesion(tmp_path)
        escrito: list[dict] = []
        sesion._escribir = escrito.append
        sesion._proceso = type("Postizo", (), {"poll": lambda self: None})()

        assert sesion.interrumpir() is True
        assert len(escrito) == 1
        assert escrito[0]["type"] == "control_request"
        assert escrito[0]["request"] == {"subtype": "interrupt"}
        assert escrito[0]["request_id"].startswith("parada_")

    def test_dos_paradas_seguidas_no_comparten_identificador(self, tmp_path):
        """En el registro crudo tiene que verse cual ack contesto a cual
        parada; con el mismo id, las dos serian la misma."""
        sesion = Sesion(tmp_path)
        escrito: list[dict] = []
        sesion._escribir = escrito.append
        sesion._proceso = type("Postizo", (), {"poll": lambda self: None})()

        sesion.interrumpir()
        import time
        time.sleep(0.002)
        sesion.interrumpir()
        assert escrito[0]["request_id"] != escrito[1]["request_id"]


class TestLosOyentesDeLaConsola:
    """La voz recibe los eventos TIPADOS por aqui, y no tirando de
    `sesion.eventos()`: esa cola tiene UN consumidor, y con dos, cada
    evento caeria en uno de los dos al azar."""

    def _consola(self, eventos):
        from puente.consola import Consola

        class SesionPostiza:
            viva = False
            session_id = None
            directorio = "."
            modelo = "sonnet"
            silencio_s = 0.0
            reintentando = None
            limite = None
            pendientes = ()

            def eventos(self, timeout=None):
                yield from eventos

        return Consola(SesionPostiza())

    def test_el_oyente_recibe_el_evento_tipado(self, eventos_de_la_parada):
        consola = self._consola(eventos_de_la_parada)
        recibidos = []
        consola.oyentes.append(recibidos.append)
        consola.bombear()
        assert any(isinstance(e, Fin) for e in recibidos)
        assert len(recibidos) == len(eventos_de_la_parada)

    def test_un_oyente_que_revienta_no_para_el_bombeo(self,
                                                      eventos_de_la_parada):
        """Si la voz se cae, la consola tiene que seguir pintando y las
        puertas tienen que seguir llegando. Al reves, un fallo de un
        canal deja al usuario sin los dos."""
        consola = self._consola(eventos_de_la_parada)

        def reventar(_evento):
            raise RuntimeError("la voz se fue")

        consola.oyentes.append(reventar)
        consola.bombear()
        assert len(consola.historia) == len(eventos_de_la_parada) + 1
        assert consola.fallos_de_oyentes
        assert "la voz se fue" in consola.fallos_de_oyentes[0]
