"""JC-0015: un servidor MCP no entra si no esta en la lista blanca.

>>> EL AGUJERO QUE ESTO TAPA, MEDIDO ANTES DE TAPARLO (2026-08-26) <<<
Con Claude Code de cerebro, su ecosistema de MCP queda al alcance. Se
midio que pasaria, contra la politica y el suelo REALES:

    Write   -> C:\\Windows        denegar    zona_de_sistema
    Bash    -> rm -rf             endurecer  orden_destructiva
    mcp__archivos__escribir       permitir   por_defecto
    mcp__archivos__borrar         permitir   por_defecto
    mcp__shell__ejecutar          permitir   por_defecto

**Una herramienta de MCP atravesaba la puerta entera sin tocarla.** La
lista endurecida de JC-0001 endurece por NOMBRE (`Write`, `Edit`,
`Bash`); el suelo de JC-0007 tiene reglas `Read(...)`/`Write(...)`. Un
`mcp__x__y` no casa con ninguna de las dos, asi que **las dos capas
caian a la vez** -- que es justo lo que las hacia dos.

LO QUE MAS SE PRUEBA AQUI es que "no declarado" DENIEGUE y no pregunte.
Si preguntara, esto no seria una lista blanca sino un aviso, y un aviso
que salta a todas horas se aprende a aprobar sin leerlo.
"""

from __future__ import annotations

import pytest
import yaml

from nucleo import mcp as mod
from nucleo.mcp import McpError, Politica, Servidor
from puente.politica import Veredicto, decidir
from puente.protocolo import Puerta


def puerta(herramienta: str, entrada: dict | None = None) -> Puerta:
    return Puerta(id_peticion="p1", id_uso="u1", herramienta=herramienta,
                  entrada=entrada or {}, descripcion="")


DECLARADOS = (
    Servidor("archivos", Politica.AUTO),
    Servidor("correo", Politica.CONFIRMAR),
    Servidor("shell", Politica.PROHIBIDO),
)


# --- 1. LA REGRESION QUE ESTE ARCHIVO IMPIDE ----------------------------


def test_un_mcp_desconocido_NO_atraviesa_la_puerta() -> None:
    """Antes de JC-0015 esto salia `permitir / por_defecto`."""
    d = decidir(puerta("mcp__loquesea__borrar_todo"), servidores_mcp=())
    assert d.veredicto is Veredicto.DENEGAR
    assert d.regla == "mcp_no_declarado"


def test_no_declarado_DENIEGA_y_no_pregunta() -> None:
    """>>> LA DIFERENCIA ENTRE UNA LISTA BLANCA Y UN AVISO <<<

    Si esto endureciera en vez de denegar, cualquier servidor recien
    instalado podria actuar en cuanto alguien apruebe de carrerilla. Una
    lista blanca dice que no; lo que la hace usable es que el motivo
    NOMBRE al servidor.
    """
    d = decidir(puerta("mcp__nuevo__cosa"), servidores_mcp=DECLARADOS)
    assert d.veredicto is Veredicto.DENEGAR
    assert d.veredicto is not Veredicto.ENDURECER
    assert "nuevo" in d.motivo, "el motivo tiene que nombrar al servidor"


@pytest.mark.parametrize("herramienta,esperado,regla", [
    ("mcp__archivos__escribir", Veredicto.PERMITIR, "mcp_auto"),
    ("mcp__correo__enviar", Veredicto.ENDURECER, "mcp_confirmar"),
    ("mcp__shell__ejecutar", Veredicto.DENEGAR, "mcp_prohibido"),
    ("mcp__desconocido__x", Veredicto.DENEGAR, "mcp_no_declarado"),
])
def test_cada_politica_hace_lo_que_dice(herramienta, esperado, regla) -> None:
    d = decidir(puerta(herramienta), servidores_mcp=DECLARADOS)
    assert (d.veredicto, d.regla) == (esperado, regla)


def test_lo_que_NO_es_de_mcp_sigue_como_siempre() -> None:
    """La regla nueva no puede cambiarle el veredicto a nada de antes."""
    d = decidir(puerta("Bash", {"command": "git status"}),
                servidores_mcp=DECLARADOS)
    assert d.veredicto is Veredicto.PERMITIR
    assert not d.regla.startswith("mcp_")


# --- 2. EL ORDEN DE LAS CAPAS -------------------------------------------


def test_el_suelo_gana_a_un_mcp_autorizado(tmp_path) -> None:
    """>>> DETRAS DEL SUELO, DELANTE DE TODO LO DEMAS <<<

    Si un servidor autorizado llegase a nombrar una ruta de zona de
    sistema, eso se deniega por lo que TOCA y no por quien lo pide. Al
    reves, `auto` seria una forma de saltarse el suelo pidiendoselo a un
    amigo.
    """
    from seguridad.zonas import Eje, Zona

    zona = Zona(ruta=r"C:\Windows", motivo="el sistema", eje=Eje.SISTEMA,
                obligatoria=True, coste="")
    p = Puerta(id_peticion="p", id_uso="u", herramienta="mcp__archivos__escribir",
               entrada={}, descripcion="", ruta_afectada=r"C:\Windows\x.dll")
    d = decidir(p, servidores_mcp=DECLARADOS, zonas=(zona,))
    assert d.veredicto is Veredicto.DENEGAR
    assert d.regla != "mcp_auto", "el suelo tiene que ganar"


def test_sin_lista_NO_es_lo_mismo_que_lista_vacia() -> None:
    """Tercera salida. `None` es "no se me ha dicho" -- lo que
    hace un test que construye una Puerta a mano -- y no deniega. Una
    tupla VACIA si es "ninguno declarado" y deniega.

    Colapsarlos haria que la unica capa que entiende estos nombres
    dependiera de que nadie olvide un argumento.
    """
    sin_decir = decidir(puerta("mcp__x__y"), servidores_mcp=None)
    ninguno = decidir(puerta("mcp__x__y"), servidores_mcp=())
    assert sin_decir.veredicto is not Veredicto.DENEGAR
    assert ninguno.veredicto is Veredicto.DENEGAR


def test_una_sesion_viva_NUNCA_corre_con_None(tmp_path) -> None:
    """Y por eso `Sesion` lo normaliza: olvidarse del argumento no puede
    significar abrir la puerta."""
    from puente.sesion import Sesion

    s = Sesion(tmp_path)
    assert s.servidores_mcp == ()
    assert s.servidores_mcp is not None


# --- 3. EL ARCHIVO ------------------------------------------------------


def test_sin_archivo_no_hay_ningun_servidor(tmp_path) -> None:
    """Ausente significa NINGUNO, nunca todos. Misma regla que
    `zonas.yaml`: leer una config que no esta como consentimiento es como
    acaba habilitado lo que nadie habilito."""
    assert mod.leer(config_dir=tmp_path) == ()


def test_ida_y_vuelta(tmp_path) -> None:
    mod.guardar(DECLARADOS, config_dir=tmp_path)
    vueltos = mod.leer(config_dir=tmp_path)
    assert [(s.nombre, s.politica) for s in vueltos] == [
        (s.nombre, s.politica) for s in DECLARADOS]


def test_guardar_REESCRIBE_y_no_fusiona(tmp_path) -> None:
    """Fusionar haria imposible quitar un servidor: se colaria otra vez
    en el siguiente guardado y nadie lo notaria."""
    mod.guardar(DECLARADOS, config_dir=tmp_path)
    mod.guardar((Servidor("archivos", Politica.AUTO),), config_dir=tmp_path)
    assert [s.nombre for s in mod.leer(config_dir=tmp_path)] == ["archivos"]


def test_un_nombre_suelto_entra_como_confirmar(tmp_path) -> None:
    """Declarar un servidor es decir "lo conozco", no "que haga lo que
    quiera". Es el `politica_por_defecto: confirmar` que heredamos."""
    (tmp_path / "mcp.yaml").write_text("servidores:\n  - archivos\n",
                                       encoding="utf-8")
    assert mod.leer(config_dir=tmp_path)[0].politica is Politica.CONFIRMAR


def test_un_yaml_roto_LEVANTA(tmp_path) -> None:
    """Arrancar con una lista blanca distinta de la que el usuario
    escribio, y callarselo, es peor que no arrancar."""
    (tmp_path / "mcp.yaml").write_text("servidores: [no cierra\n",
                                       encoding="utf-8")
    with pytest.raises(McpError):
        mod.leer(config_dir=tmp_path)


def test_una_politica_inventada_LEVANTA(tmp_path) -> None:
    """`politica: casi` no puede leerse como ninguna de las tres."""
    (tmp_path / "mcp.yaml").write_text(
        yaml.safe_dump({"servidores": [{"nombre": "x", "politica": "casi"}]}),
        encoding="utf-8")
    with pytest.raises(McpError):
        mod.leer(config_dir=tmp_path)


# --- 4. SE AUTORIZA AL SERVIDOR, NO A LA HERRAMIENTA --------------------


def test_la_autoridad_es_del_SERVIDOR() -> None:
    """Un servidor decide que herramientas expone y puede cambiarlas sin
    avisar, asi que autorizar herramienta a herramienta daria una
    sensacion de control que no existe."""
    assert mod.servidor_de("mcp__archivos__escribir") == "archivos"
    assert mod.servidor_de("mcp__archivos__borrar") == "archivos"
    unos = decidir(puerta("mcp__archivos__escribir"), servidores_mcp=DECLARADOS)
    otros = decidir(puerta("mcp__archivos__borrar"), servidores_mcp=DECLARADOS)
    assert unos.veredicto is otros.veredicto


def test_se_reconoce_lo_que_es_de_mcp_y_lo_que_no() -> None:
    assert mod.es_de_mcp("mcp__x__y")
    assert not mod.es_de_mcp("Bash")
    assert not mod.es_de_mcp("Write")
    # Ni un nombre que solo lo parezca.
    assert not mod.es_de_mcp("mcpservidor")


def test_las_skills_y_los_plugins_NO_pasan_por_aqui() -> None:
    """>>> LA DISTINCION QUE AHORRA TRABAJO <<<

    Una skill son INSTRUCCIONES, no autoridad: las herramientas que acabe
    usando siguen siendo `Write`, `Bash`... y pasan por la puerta como
    siempre. Meterlas en la lista blanca seria pedir permiso para leer un
    documento.
    """
    d = decidir(puerta("Write", {"file_path": r"C:\proyectos\x\a.txt"}),
                directorio_sesion=r"C:\proyectos\x", servidores_mcp=())
    assert d.veredicto is Veredicto.PERMITIR
