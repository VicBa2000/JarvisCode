"""Tests del tercer canal: escalado y Telegram (JC-0006).

Nada de aqui toca la red. Lo que se prueba es la POLITICA -- cuando se
escala y cuando no --, que es donde estan las decisiones, y que el
mensaje diga lo mismo que la voz y la consola.

La puerta y su decision son REALES: salen de `eval/trazas_claude_code/`
pasadas por la politica de verdad. Una `Decision` escrita a mano no
probaria lo unico que importa aqui, que es que los tres canales nombren
lo mismo (JC-0002).
"""

from __future__ import annotations

import time

import pytest

from canales.escalado import Escalado
from canales.telegram import Ajustes, Estado as EstadoCanal, Telegram
from nucleo.presencia import Estado, Lectura, Presencia
from puente.politica import decidir
from puente.protocolo import Puerta, interpretar
from puente.sesion import Pendiente

DIRECTORIO = r"C:\proyectos\carpetadepruebas"


class CanalPostizo:
    """Un canal que apunta lo que le mandan. No hay red en estos tests."""

    def __init__(self, disponible: bool = True, funciona: bool = True) -> None:
        self.disponible = disponible
        self.funciona = funciona
        self.mandados: list[str] = []

    def mandar(self, texto: str) -> bool:
        self.mandados.append(texto)
        return self.funciona


class PresenciaFija(Presencia):
    def __init__(self, estado: Estado) -> None:
        super().__init__()
        self._fijo = estado

    def mirar(self, ahora=None) -> Lectura:
        return Lectura(estado=self._fijo, inactivo_s=999.0,
                       escritorio_accesible=True, momento=ahora or 0.0)


@pytest.fixture
def pendiente(project_root):
    ruta = project_root / "eval" / "trazas_claude_code" / "denegada.jsonl"
    if not ruta.is_file():
        pytest.skip("falta la traza denegada.jsonl")
    puertas = [e for linea in ruta.read_text(encoding="utf-8").splitlines()
               for e in interpretar(linea) if isinstance(e, Puerta)]
    assert puertas
    puerta = puertas[0]
    return Pendiente(evento=puerta,
                     decision=decidir(puerta, directorio_sesion=DIRECTORIO),
                     pedido_en=time.time() - 3600)


def escalado(canal, estado=Estado.AUSENTE) -> Escalado:
    return Escalado(canal=canal, presencia=PresenciaFija(estado),
                    directorio=DIRECTORIO)


class TestCuandoSeEscala:
    def test_ausente_y_pasado_el_rato_se_manda(self, pendiente):
        canal = CanalPostizo()
        assert escalado(canal).revisar((pendiente,)) == 1
        assert len(canal.mandados) == 1

    def test_ESTANDO_DELANTE_no_se_manda(self, pendiente):
        """La regla de JC-0009: la presencia silencia el ESCALADO. La
        puerta ya se pidio por voz y ya esta en la consola; lo unico que
        se calla es el movil."""
        canal = CanalPostizo()
        esc = escalado(canal, Estado.PRESENTE)
        assert esc.revisar((pendiente,)) == 0
        assert canal.mandados == []
        assert esc.callados_por_presencia == 1

    def test_si_no_se_sabe_donde_esta_SI_se_manda(self, pendiente):
        """Sesion bloqueada o RDP. La direccion segura es avisar: un
        aviso sobrante se ignora, uno que no se manda no se recupera."""
        canal = CanalPostizo()
        assert escalado(canal, Estado.NO_SE_SABE).revisar((pendiente,)) == 1

    def test_recien_pedida_todavia_no(self, pendiente):
        """Primero contestan la voz y la consola. Telegram es el ultimo
        escalon, no el primero."""
        from dataclasses import replace

        reciente = replace(pendiente, pedido_en=time.time())
        canal = CanalPostizo()
        assert escalado(canal).revisar((reciente,)) == 0

    def test_una_puerta_se_avisa_UNA_vez(self, pendiente):
        """Un canal que repite el mismo aviso cada minuto se silencia en
        el movil, y entonces deja de ser un canal."""
        canal = CanalPostizo()
        esc = escalado(canal)
        for _ in range(5):
            esc.revisar((pendiente,))
        assert len(canal.mandados) == 1

    def test_sin_canal_configurado_no_pasa_nada(self, pendiente):
        """Un canal que no se puso no es un fallo."""
        canal = CanalPostizo(disponible=False)
        assert escalado(canal).revisar((pendiente,)) == 0
        assert canal.mandados == []

    def test_si_el_envio_falla_NO_se_da_por_avisada(self, pendiente):
        """Si no, un corte de red convertiria el aviso en un aviso que
        nadie recibio y nadie volvera a intentar."""
        canal = CanalPostizo(funciona=False)
        esc = escalado(canal)
        esc.revisar((pendiente,))
        esc.revisar((pendiente,))
        assert len(canal.mandados) == 2
        assert esc.enviados == 0

    def test_sin_pendientes_se_olvida_lo_avisado(self, pendiente):
        canal = CanalPostizo()
        esc = escalado(canal)
        esc.revisar((pendiente,))
        esc.revisar(())
        assert esc.avisadas == set()


class TestQueDiceElMensaje:
    def test_dice_LO_MISMO_que_la_voz(self, pendiente):
        """JC-0002 no cambia porque cambie el canal: el mensaje se
        construye desde la MISMA `Decision`."""
        canal = CanalPostizo()
        escalado(canal).revisar((pendiente,))
        texto = canal.mandados[0]
        assert pendiente.decision.motivo in texto
        import os
        assert os.path.basename(pendiente.decision.elementos[0]) in texto

    def test_dice_QUE_POR_AHI_NO_SE_AUTORIZA(self, pendiente):
        """Un mensaje entrante es contenido observado, jamas
        una instruccion. Si el usuario contesta "si" al movil y no pasa
        nada, tiene que saber POR QUE."""
        canal = CanalPostizo()
        escalado(canal).revisar((pendiente,))
        texto = canal.mandados[0].lower()
        assert "no puedo autorizar" in texto
        assert "consola" in texto

    def test_NO_pide_que_contestes_por_ahi(self, pendiente):
        """La frase de la voz acaba en "contesta si o no". Copiarla tal
        cual al movil seria invitar a contestar por un canal que no
        contesta."""
        canal = CanalPostizo()
        escalado(canal).revisar((pendiente,))
        assert "Contesta si o no" not in canal.mandados[0]

    def test_dice_cuanto_lleva_esperando(self, pendiente):
        canal = CanalPostizo()
        escalado(canal).revisar((pendiente,))
        assert "min esperando" in canal.mandados[0]


class TestLosAjustesDeTelegram:
    def test_sin_configurar_no_esta_disponible_y_no_es_un_error(self):
        canal = Telegram(Ajustes())
        assert canal.disponible is False
        assert canal.mandar("hola") is False
        assert canal.comprobar()[0] is EstadoCanal.SIN_CONFIGURAR

    def test_apagado_pero_con_token_sigue_apagado(self):
        """El interruptor manda. Tener la credencial puesta no es querer
        usarla."""
        canal = Telegram(Ajustes(activo=False, token="x", chat_id="1"))
        assert canal.disponible is False

    def test_EL_TOKEN_NO_SALE_NUNCA(self):
        """Ni a la UI ni al log. Se enseñan los cuatro ultimos, que es lo
        justo para reconocer cual pusiste."""
        visto = Ajustes(activo=True, token="123456:ABCDEFGH",
                        chat_id="42").sin_secretos()
        assert "123456" not in str(visto)
        assert visto["token_acaba_en"] == "EFGH"
        assert visto["hay_token"] is True

    def test_se_guarda_y_se_vuelve_a_leer(self, tmp_path):
        from canales import telegram as modulo

        archivo = tmp_path / "telegram.yaml"
        modulo.guardar(Ajustes(activo=True, token="tok", chat_id="99"),
                       archivo)
        leido = modulo.leer(archivo)
        assert leido.activo is True
        assert leido.token == "tok"
        assert leido.chat_id == "99"

    def test_sin_archivo_todo_apagado(self, tmp_path):
        from canales import telegram as modulo

        assert modulo.leer(tmp_path / "no_existe.yaml").completo is False

    def test_el_entorno_gana_al_archivo(self, tmp_path, monkeypatch):
        """Es lo que deja probar esto sin dejar la credencial escrita en
        ningun sitio."""
        from canales import telegram as modulo

        archivo = tmp_path / "telegram.yaml"
        modulo.guardar(Ajustes(activo=True, token="del_archivo",
                               chat_id="1"), archivo)
        monkeypatch.setenv("JARVIS_TELEGRAM_TOKEN", "del_entorno")
        assert modulo.leer(archivo).token == "del_entorno"
