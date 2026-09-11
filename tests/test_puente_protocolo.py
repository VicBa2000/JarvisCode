"""The parser is tested against REAL captures, never against handmade JSON.

`eval/trazas_claude_code/*.jsonl` are byte-for-byte captures of
`claude 2.1.239` taken on 2026-08-21 with
`eval/sondas_claude_code/capturar_traza.py`. La regla: si el dato existe
en un log real, se copia de ahi. A parser that passes on invented input
proves the invention, not the parser.

These are fast: no model, no network, no subprocess. No `lento` marker: ese
se paga en las veces que no se corre.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from puente.protocolo import (
    Desconocido,
    Fin,
    Inicio,
    LineaIlegible,
    Pregunta,
    Puerta,
    ResultadoHerramienta,
    Texto,
    UsoHerramienta,
    interpretar,
)

TRAZAS = Path(__file__).resolve().parent.parent / "eval" / "trazas_claude_code"


def eventos_de(nombre: str) -> list:
    ruta = TRAZAS / nombre
    eventos = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        eventos.extend(interpretar(linea))
    return eventos


def solo(eventos: list, clase: type) -> list:
    return [e for e in eventos if isinstance(e, clase)]


# --- La traza donde todo se permitio --------------------------------------


def test_la_sesion_se_anuncia_y_puede_preguntar():
    inicios = solo(eventos_de("permitida.jsonl"), Inicio)
    assert len(inicios) == 1
    assert inicios[0].session_id
    assert inicios[0].modo_permisos == "default"
    # Captured with --permission-prompt-tool stdio, so the tool is there.
    assert inicios[0].puede_preguntar


def test_una_lectura_no_pasa_por_la_puerta():
    """The measured fact the whole audit design rests on.

    `Read` shows up as a tool call and never as a gate. If this ever
    starts failing, the bridge is seeing more than it used to and the
    policy needs re-reading, not the test.
    """
    eventos = eventos_de("permitida.jsonl")
    usos = {u.herramienta for u in solo(eventos, UsoHerramienta)}
    puertas = {p.herramienta for p in solo(eventos, Puerta)}
    assert "Read" in usos
    assert "Read" not in puertas


def test_las_dos_puertas_traen_la_orden_entera():
    puertas = solo(eventos_de("permitida.jsonl"), Puerta)
    assert [p.herramienta for p in puertas] == ["Write", "Bash"]
    assert puertas[0].entrada["file_path"].endswith("resumen.txt")
    # `orden_shell` is what the hardened list will be evaluated against.
    assert "rm" in (puertas[1].orden_shell or "")
    assert puertas[1].id_peticion and puertas[1].id_uso


def test_el_turno_cierra_con_su_coste():
    fines = solo(eventos_de("permitida.jsonl"), Fin)
    assert len(fines) == 1
    assert fines[0].subtipo == "success"
    assert not fines[0].es_error
    assert fines[0].duracion_ms > 0
    assert fines[0].coste_usd > 0


# --- La traza donde se denego ---------------------------------------------


def test_denegar_llega_al_modelo_como_error_de_herramienta():
    eventos = eventos_de("denegada.jsonl")
    fallos = [r for r in solo(eventos, ResultadoHerramienta) if r.es_error]
    assert len(fallos) == 1
    assert "no" in fallos[0].contenido.lower()
    # Y el modelo lo dice en prosa, que es lo que se locutara.
    assert any("borr" in t.texto.lower() for t in solo(eventos, Texto))


def test_un_ls_no_abre_puerta_pero_un_rm_si():
    eventos = eventos_de("denegada.jsonl")
    ordenes_usadas = [
        u.entrada.get("command", "") for u in solo(eventos, UsoHerramienta)
    ]
    ordenes_con_puerta = [p.orden_shell for p in solo(eventos, Puerta)]
    assert any(o.startswith("ls") for o in ordenes_usadas)
    assert not any((o or "").startswith("ls") for o in ordenes_con_puerta)
    assert any((o or "").startswith("rm") for o in ordenes_con_puerta)


# --- La traza de la pregunta ----------------------------------------------


def test_una_pregunta_no_es_una_puerta():
    """El punto entero del modulo.

    Si `AskUserQuestion` cayera en `Puerta`, la politica la contestaria
    sola y el puente pasaria a ser un segundo agente decidiendo.
    """
    eventos = eventos_de("pregunta.jsonl")
    preguntas = solo(eventos, Pregunta)
    assert len(preguntas) == 1
    assert not solo(eventos, Puerta)
    assert preguntas[0].id_peticion
    assert preguntas[0].enunciados
    assert "?" in preguntas[0].enunciados[0]


def test_la_pregunta_conserva_sus_opciones():
    pregunta = solo(eventos_de("pregunta.jsonl"), Pregunta)[0]
    opciones = pregunta.preguntas[0]["options"]
    assert len(opciones) >= 2
    assert all("label" in o for o in opciones)


# --- Lo que no se entiende --------------------------------------------------


def test_un_tipo_nuevo_no_se_tira_a_la_basura():
    eventos = interpretar('{"type":"algo_que_no_existia_ayer","x":1}')
    assert len(eventos) == 1
    assert isinstance(eventos[0], Desconocido)
    assert eventos[0].tipo == "algo_que_no_existia_ayer"


def test_una_linea_que_no_es_json_no_revienta_la_sesion():
    eventos = interpretar("Warning: no stdin data received in 3s")
    assert [type(e) for e in eventos] == [LineaIlegible]


def test_una_linea_vacia_no_produce_nada():
    assert interpretar("") == []
    assert interpretar("   \n") == []


@pytest.mark.parametrize("nombre", ["permitida.jsonl", "denegada.jsonl",
                                    "pregunta.jsonl", "sin_conexion.jsonl"])
def test_ninguna_linea_real_queda_sin_entender(nombre):
    """Nothing in a real capture should come out as Desconocido.

    If it does, Claude Code grew a message type and this module has to
    learn it before anything above it can be trusted.
    """
    raros = solo(eventos_de(nombre), Desconocido)
    assert not raros, [r.tipo for r in raros]


# --------------------------------------------------------------------
# QUE SE ESTA HACIENDO AHORA (2026-08-27). Una regla, dos consumidores.
# --------------------------------------------------------------------

class TestSeguidorDeTarea:
    """>>> POR QUE ESTA REGLA VIVE AQUI Y NO EN `voz/` <<<

    "Un `Texto` es narracion si detras viene una herramienta, y es LA
    RESPUESTA si detras viene `Fin`" la necesitan dos: la voz para
    locutarla y la consola para su barra de TAREA. Es una propiedad del
    FLUJO, no de la voz. Escrita dos veces acabarian divergiendo -- como
    los tres normalizadores de `voz/` -- y el sintoma seria que la barra
    dice una cosa y el altavoz otra.
    """

    def _seguidor(self):
        from puente.protocolo import SeguidorDeTarea

        return SeguidorDeTarea()

    def _texto(self, t):
        from puente.protocolo import Texto

        return Texto(texto=t)

    def _herramienta(self):
        from puente.protocolo import UsoHerramienta

        return UsoHerramienta(id_uso="u1", herramienta="Read", entrada={})

    def _fin(self):
        from puente.protocolo import Fin

        return Fin(session_id="s", subtipo="success", es_error=False,
                   texto="ya esta", coste_usd=0.0, duracion_ms=1, num_turnos=1)

    def test_la_orden_del_usuario_va_LITERAL(self):
        """La barra no parafrasea: lo que el usuario tiene que poder
        comprobar de un vistazo es que el dictado se entendio."""
        s = self._seguidor()
        s.orden("evalua las semanas de progreso", origen="voz")
        assert s.tarea == "evalua las semanas de progreso"
        assert s.origen == "voz"

    def test_un_texto_solo_NO_cambia_la_tarea(self):
        """Todavia no se sabe si era narracion o la respuesta."""
        s = self._seguidor()
        s.orden("haz una cosa", origen="voz")
        assert s.ve(self._texto("Voy a mirar el codigo.")) is None
        assert s.tarea == "haz una cosa"

    def test_un_texto_SEGUIDO_de_herramienta_es_la_tarea(self):
        s = self._seguidor()
        s.orden("haz una cosa", origen="voz")
        s.ve(self._texto("Voy a mirar el codigo."))
        assert s.ve(self._herramienta()) == "Voy a mirar el codigo."
        assert s.tarea == "Voy a mirar el codigo."
        assert s.origen == "claude"

    def test_un_texto_SEGUIDO_de_Fin_es_la_respuesta_y_no_narra(self):
        s = self._seguidor()
        s.orden("haz una cosa", origen="voz")
        s.ve(self._texto("Ya esta todo listo."))
        assert s.ve(self._fin()) is None

    def test_al_cerrar_el_turno_la_barra_se_VACIA(self):
        """Congelar la ultima tarea para siempre diria que se esta
        trabajando cuando no. Un indicador que no se apaga es un
        indicador que se aprende a ignorar."""
        s = self._seguidor()
        s.orden("haz una cosa", origen="voz")
        s.ve(self._fin())
        assert s.tarea == ""
        assert s.origen == ""

    def test_una_puerta_tira_lo_pendiente(self):
        """Una puerta es una pregunta que hay que contestar: lo que se
        estuviera contando al lado deja de ser lo que pasa."""
        from puente.protocolo import Puerta

        s = self._seguidor()
        s.ve(self._texto("Voy a mirar el codigo."))
        s.ve(Puerta(id_peticion="r", herramienta="Bash",
                    entrada={"command": "ls"}, descripcion="", id_uso="u"))
        assert s.ve(self._herramienta()) is None

    def test_se_recorta_por_palabra_para_que_quepa(self):
        from puente.protocolo import LARGO_DE_TAREA

        s = self._seguidor()
        s.orden("palabra " * 60, origen="voz")
        assert len(s.tarea) <= LARGO_DE_TAREA + 3
        assert s.tarea.endswith("...")
        assert not s.tarea.endswith("palab...")   # cortado por palabra

    def test_los_saltos_de_linea_no_rompen_la_barra(self):
        s = self._seguidor()
        s.orden("primera linea\n\nsegunda linea", origen="consola")
        assert "\n" not in s.tarea
        assert s.tarea == "primera linea segunda linea"


# --- Los servidores MCP, y si llegaron a levantarse -----------------------
# >>> ESTO SE TIRABA, Y COSTO TRES SESIONES MUDAS (2026-09-07) <<<
# `system/init` trae `mcp_servers` desde siempre y el parser se quedaba
# solo con `tools`. El 2026-09-04 `blender` estuvo `failed` tres sesiones
# seguidas y la pantalla no lo dijo nunca, porque el dato no llegaba a
# existir aqui. La traza es la de ESA sesion, copiada literal de
# `logs/puente/`: es el unico sitio donde hay un servidor
# realmente caido, y `logs/` no se versiona.


def test_el_init_dice_que_servidores_mcp_arrancaron():
    inicio = solo(eventos_de("mcp_uno_caido.jsonl"), Inicio)[0]
    porNombre = {s.nombre: s for s in inicio.servidores}
    assert porNombre["godot"].arranco is True
    assert porNombre["blender"].arranco is False
    assert porNombre["blender"].fallo


def test_needs_auth_no_es_un_fallo():
    """Los tres de `claude.ai` llevan ahi desde siempre.

    Contarlos como caidos convertiria esta pantalla en una alarma diaria
    por algo que el usuario no ha pedido nunca, y una alarma que siempre
    esta encendida es una alarma que ya no se mira -- que es como se
    pierde el aviso que SI importa.
    """
    inicio = solo(eventos_de("mcp_uno_caido.jsonl"), Inicio)[0]
    drive = {s.nombre: s for s in inicio.servidores}["claude.ai Google Drive"]
    assert drive.necesita_login
    assert not drive.fallo
    # No arranco -- eso es cierto y se dice --, pero no esta roto.
    assert drive.arranco is False
    assert "claude.ai Google Drive" not in [s.nombre for s in inicio.mcp_caidos]


def test_solo_blender_cuenta_como_caido():
    inicio = solo(eventos_de("mcp_uno_caido.jsonl"), Inicio)[0]
    assert [s.nombre for s in inicio.mcp_caidos] == ["blender"]


def test_un_estado_que_no_conocemos_no_es_un_si():
    """La tercera salida, en el sitio exacto donde este proyecto ya se quemo.

    Claude Code inventa campos sin avisar -- paso con `unifiedWindows` en
    la cuota, y el `utilization` ausente se leyo como 0 % durante seis
    dias. Un `status` que este codigo no conozca tiene que salir como NO
    SE SABE: colapsarlo contra "arranco" reproduce el fallo mudo que todo
    esto viene a arreglar, y contra "fallo" pinta una alarma inventada.
    """
    linea = json.dumps({"type": "system", "subtype": "init",
                        "mcp_servers": [{"name": "raro", "status": "pending"}]})
    inicio = solo(interpretar(linea), Inicio)[0]
    raro = inicio.servidores[0]
    assert raro.arranco is None
    assert not raro.fallo and not raro.necesita_login
    # El crudo se conserva para poder escribir la palabra que llego.
    assert raro.crudo == "pending"
    # Y entra en los caidos: no se sabe que pasa, asi que se dice.
    assert [s.nombre for s in inicio.mcp_caidos] == ["raro"]


def test_un_servidor_sin_nombre_no_es_un_servidor():
    """No se puede pintar ni nombrar, asi que no se inventa una fila."""
    linea = json.dumps({"type": "system", "subtype": "init",
                        "mcp_servers": [{"status": "failed"}, "basura",
                                        {"name": "bueno", "status": "connected"}]})
    inicio = solo(interpretar(linea), Inicio)[0]
    assert [s.nombre for s in inicio.servidores] == ["bueno"]


def test_sin_mcp_no_hay_servidores_y_no_es_un_fallo():
    """Lo normal: casi nadie tiene MCP puestos."""
    inicio = solo(eventos_de("permitida.jsonl"), Inicio)[0]
    assert inicio.servidores == ()
    assert inicio.mcp_caidos == ()
