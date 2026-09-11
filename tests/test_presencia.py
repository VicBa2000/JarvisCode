"""Tests de `nucleo/presencia.py` (JC-0009).

Lo que se puede probar sin una persona delante es la HISTERESIS y las
tres salidas; lo que no se puede probar es si el numero de la ventana es
el bueno, porque eso depende de cuanto tarda un humano en tocar una
tecla. El dato que hay sobre eso esta medido y escrito en el modulo: 265
segundos de inactividad con el usuario sentado y leyendo.

El sistema se sustituye por dentro (`_inactividad_s`, `_escritorio_
accesible`) porque lo contrario seria probar Windows, no esto. Hay un
test que SI llama a Windows de verdad, y comprueba solo lo unico que
tiene sentido comprobar sin saber donde esta el usuario: que las dos
llamadas contestan algo coherente.
"""

from __future__ import annotations

import pytest

from nucleo import presencia as modulo
from nucleo.presencia import AUSENTE_TRAS_S, Estado, Presencia


@pytest.fixture
def sistema(monkeypatch):
    """Deja fijar que contesta Windows, sin tocar Windows."""
    estado = {"inactivo": 0.0, "accesible": True}

    monkeypatch.setattr(modulo, "_inactividad_s",
                        lambda: estado["inactivo"])
    monkeypatch.setattr(modulo, "_escritorio_accesible",
                        lambda: estado["accesible"])
    return estado


class TestLasTresSalidas:
    """Tres salidas, y en el original fallo abierto ocho veces."""

    def test_entrada_reciente_es_presente(self, sistema):
        sistema["inactivo"] = 3.0
        assert Presencia().mirar().estado is Estado.PRESENTE

    def test_sin_entrada_durante_la_ventana_es_ausente(self, sistema):
        sistema["inactivo"] = AUSENTE_TRAS_S + 1
        assert Presencia().mirar().estado is Estado.AUSENTE

    def test_escritorio_bloqueado_es_NO_SE_SABE_y_no_ausente(self, sistema):
        """Es un estado distinto y se registra como tal: si el 90 % de las
        sesiones cayeran aqui, el mecanismo no estaria funcionando y hay
        que poder enterarse mirando, no por sorpresa."""
        sistema["accesible"] = False
        sistema["inactivo"] = 1.0
        lectura = Presencia().mirar()
        assert lectura.estado is Estado.NO_SE_SABE

    def test_si_la_llamada_falla_tampoco_se_inventa(self, sistema):
        """`None` no es un cero: un fallo de la llamada no puede
        parecerse a "acaba de teclear"."""
        sistema["inactivo"] = None
        assert Presencia().mirar().estado is Estado.NO_SE_SABE

    def test_NO_SE_SABE_cuenta_como_ausente_para_escalar(self):
        """La direccion segura: un aviso sobrante se ignora, uno que no
        se manda no se recupera. Y el colapso ocurre en UN sitio."""
        assert Estado.NO_SE_SABE.hay_que_escalar is True
        assert Estado.AUSENTE.hay_que_escalar is True
        assert Estado.PRESENTE.hay_que_escalar is False


class TestLaHisteresis:
    def test_se_vuelve_presente_con_UNA_entrada(self, sistema):
        """Inmediato, que es lo que uno espera al sentarse."""
        presencia = Presencia()
        sistema["inactivo"] = AUSENTE_TRAS_S + 10
        assert presencia.mirar().estado is Estado.AUSENTE
        sistema["inactivo"] = 0.2
        assert presencia.mirar().estado is Estado.PRESENTE

    def test_NO_se_vuelve_ausente_por_un_rato_corto(self, sistema):
        """Con un umbral seco, un golpe de raton al pasar haria
        parpadear los canales."""
        presencia = Presencia()
        for inactivo in (10, 60, 120, 299):
            sistema["inactivo"] = inactivo
            assert presencia.mirar().estado is Estado.PRESENTE, inactivo

    def test_la_ventana_por_defecto_aguanta_a_alguien_leyendo(self):
        """El numero que la justifica: 265 s de inactividad medidos con
        el usuario SENTADO DELANTE, leyendo. Un minuto le habria dado
        por ausente."""
        assert AUSENTE_TRAS_S > 265


class TestLoQueSeGuardaParaDespues:
    def test_la_lectura_lleva_los_segundos_y_no_solo_el_estado(self, sistema):
        """Continua, no bandera: "ausente" no distingue a quien acaba de
        irse de quien lleva tres horas fuera, y eso es lo que decide si se
        insiste."""
        sistema["inactivo"] = 900.0
        lectura = Presencia().mirar()
        assert lectura.inactivo_s == 900.0
        assert "900" in lectura.describe()

    def test_se_cuenta_cuantas_veces_cae_en_cada_estado(self, sistema):
        presencia = Presencia()
        sistema["inactivo"] = 1.0
        presencia.mirar()
        sistema["accesible"] = False
        presencia.mirar()
        presencia.mirar()
        assert presencia.veces[Estado.PRESENTE] == 1
        assert presencia.veces[Estado.NO_SE_SABE] == 2


class TestContraWindowsDeVerdad:
    def test_las_dos_llamadas_contestan_algo_coherente(self):
        """No se comprueba DONDE esta el usuario -- eso no se sabe aqui --
        sino que el mecanismo responde. Si un dia `ctypes` deja de
        funcionar, esto lo dice; sin este test, la presencia se quedaria
        en "no se sabe" para siempre y nadie se enteraria."""
        inactivo = modulo._inactividad_s()
        accesible = modulo._escritorio_accesible()
        assert inactivo is None or inactivo >= 0
        assert accesible in (True, False, None)
        # Y en la maquina de desarrollo, con la sesion abierta, las dos
        # tienen que dar algo util. Si esto falla en un CI sin escritorio,
        # el mensaje dice por que.
        assert inactivo is not None, "GetLastInputInfo no contesto"
