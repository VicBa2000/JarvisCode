"""`--effort`: cuanto se lo piensa, y lo que eso cuesta en segundos.

>>> LO QUE ESTO PROTEGE NO ES EL FLAG, ES QUE ESTE PUESTO DE VERDAD <<<
Medido el 2026-09-01 contra `claude 2.1.252`:

    claude -p --effort disparate "di solo OK"
    Warning: Unknown --effort value 'disparate' - ignoring it and using
    the default effort. Valid values: low, medium, high, xhigh, max.

**Un valor invalido no da error: se ignora.** Y en nuestro montaje ese
aviso sale por stderr, que llega como `LineaIlegible` y no se ve. O sea
que una errata en `ajustes.yaml` dejaria a Jarvis pensando lo de siempre
mientras la pantalla dice que piensa mas -- la misma forma que la deuda
de JC-0003 con `--permission-prompt-tool`, y que la regla `Write(...)`
sin su `Edit(...)` de JC-0007. Por eso se valida de este lado.

Y LA CIFRA QUE JUSTIFICA EL DEFECTO, misma sonda, 5 turnos por nivel
(`-m eval.sondas_claude_code.sonda_esfuerzo`):

    sin flag   0 de 5 turnos pensaron     5,4 s   0,0454 USD
    max        5 de 5 turnos pensaron    23,7 s   0,0658 USD

4,4 veces el reloj. Hablando, 24 segundos callado.
"""

from __future__ import annotations

import pytest

from nucleo.ajustes import catalogo
from puente.sesion import ESFUERZOS, PuenteError, Sesion


def test_el_flag_va_con_su_valor() -> None:
    orden = Sesion("C:/", esfuerzo="max").orden
    assert orden[orden.index("--effort") + 1] == "max"


def test_sin_esfuerzo_no_hay_flag() -> None:
    """`None` = el de Claude Code de serie, y es el defecto."""
    assert "--effort" not in Sesion("C:/").orden


@pytest.mark.parametrize("malo", ["maximo", "MAX", "alto", "", " "])
def test_un_valor_invalido_LEVANTA_en_vez_de_colarse(malo) -> None:
    """>>> LA TERCERA SALIDA NO PUEDE SER "SIGUE COMO SIEMPRE" <<<

    Es lo que hace el binario, y en silencio. Si aqui se copiara ese
    comportamiento, el unico sitio donde se podria descubrir seria
    cronometrando turnos.
    """
    with pytest.raises(PuenteError) as exc:
        Sesion("C:/", esfuerzo=malo)
    assert "esfuerzo valido" in str(exc.value)


def test_los_valores_son_los_que_acepta_el_binario() -> None:
    """Si `claude` cambia la lista, esto se entera al releerlo, no antes.

    Se deja escrito el origen: `--effort <level>` en `claude --help` de
    2.1.252, y confirmado por el propio aviso del binario.
    """
    assert ESFUERZOS == ("low", "medium", "high", "xhigh", "max")


class TestElAjuste:
    def _el_ajuste(self):
        return [a for a in catalogo() if a.clave == "sesion.esfuerzo"][0]

    def test_nace_en_el_de_siempre(self) -> None:
        """Con la voz, subirlo de serie seria un asistente que calla 24 s."""
        ajuste = self._el_ajuste()
        assert ajuste.por_defecto == ""
        assert ajuste.opciones[0]["valor"] == ""

    def test_todas_sus_opciones_las_acepta_la_sesion(self) -> None:
        """El panel no puede ofrecer un valor que el binario ignore."""
        for opcion in self._el_ajuste().opciones:
            valor = opcion["valor"]
            if not valor:
                continue
            assert valor in ESFUERZOS
            Sesion("C:/", esfuerzo=valor)   # no levanta

    def test_el_aviso_lleva_la_cifra_medida(self) -> None:
        """>>> UN COSTE EN ABSTRACTO NO SE LEE <<<

        "tarda mas" no hace que nadie decida distinto; "de 5,4 a 23,7
        segundos" si. Es la misma regla que las zonas opcionales de
        JC-0007, que llevan su coste delante.
        """
        aviso = self._el_ajuste().aviso
        assert "5,4" in aviso and "23,7" in aviso


class TestLoLeeElLanzador:
    def _arrancar(self, tmp_path, monkeypatch, ajuste):
        import nucleo.ajustes as ajustes_mod
        import puente.__main__ as lanzador
        from puente.suelo import EstadoSuelo, QuienTieneElPuerto, Suelo

        de_verdad = ajustes_mod.valor_de
        monkeypatch.setattr(
            ajustes_mod, "valor_de",
            lambda clave, *a, **k: (ajuste if clave == "sesion.esfuerzo"
                                    else de_verdad(clave, *a, **k)))
        monkeypatch.setattr(
            lanzador, "quien_tiene_el_puerto",
            lambda _p: (QuienTieneElPuerto.LIBRE, "libre"))
        monkeypatch.setattr(lanzador, "preparar", lambda **_: Suelo(
            estado=EstadoSuelo.LISTO, motivo="sellado",
            archivo=tmp_path / "s.json"))

        visto: dict = {}

        class SesionFalsa:
            def __init__(self, *a, **k):
                visto.update(k)
                self.viva = False
            def cerrar(self):
                pass

        class ConsolaFalsa:
            def __init__(self, *a, **k):
                raise KeyboardInterrupt

        monkeypatch.setattr(lanzador, "Sesion", SesionFalsa)
        monkeypatch.setattr(lanzador, "Consola", ConsolaFalsa)
        monkeypatch.setattr("sys.argv", ["puente", str(tmp_path)])
        with pytest.raises(KeyboardInterrupt):
            lanzador.main()
        return visto

    def test_lo_que_diga_el_panel(self, tmp_path, monkeypatch) -> None:
        assert self._arrancar(tmp_path, monkeypatch, "max")["esfuerzo"] == "max"

    def test_vacio_es_no_tocar_nada(self, tmp_path, monkeypatch) -> None:
        assert self._arrancar(tmp_path, monkeypatch, "")["esfuerzo"] is None

    def test_un_yaml_editado_a_mano_con_un_valor_malo_NO_impide_arrancar(
            self, tmp_path, monkeypatch, capsys) -> None:
        """>>> PERO SE DICE, QUE ES LA MITAD QUE IMPORTA <<<

        Levantar aqui dejaria a Jarvis sin arrancar por una errata en un
        ajuste de comodidad, y esto vive en el inicio de Windows: el
        sintoma seria "no abre" y la causa una palabra mal escrita.
        Arranca sin el flag -- que es lo mismo que hace el binario -- pero
        LO DICE, que es justo lo que el binario no hace donde se pueda
        ver.
        """
        visto = self._arrancar(tmp_path, monkeypatch, "maximo")
        assert visto["esfuerzo"] is None
        assert "maximo" in capsys.readouterr().out
