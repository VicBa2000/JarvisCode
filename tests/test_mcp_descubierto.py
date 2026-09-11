"""Descubrir los MCP del Claude Code nativo. DESCUBRIR, no confiar.

>>> LO PIDIO EL USUARIO EL 2026-09-03 <<<
Pidio que Jarvis detectara directamente los MCP que el Claude Code nativo
de la maquina ya tiene conectados o definidos.

Y se le puso delante la diferencia, porque son dos cosas y solo una es
segura. Eligio DESCUBRIR: el panel lista lo que tu Claude Code tiene, con
un boton para autorizar cada uno. La lista blanca de JC-0015 sigue
mandando, y no declarado sigue denegando.

LO QUE MAS SE PRUEBA AQUI es lo que, si se rompe, se rompe en silencio:

  1. **que los valores de entorno NO se copien.** `config/mcp.yaml` SI se
     versiona -- al reves que `config/telegram.yaml` --, asi que importar
     un `env` literal de un `.mcp.json` ajeno meteria un token en git.
     Un fallo aqui no da error: da un secreto en un commit.
  2. **que autorizar entre en `confirmar`.** Un clic no puede valer mas
     que escribirlo a mano. Y que un servidor ya estuviera en tu Claude
     Code no dice que deba pasar sin preguntar: se comprobo que el
     propio Claude Code tampoco lo da por aprobado
     (`enabledMcpjsonServers` ausente).
  3. **que la definicion salga del ARCHIVO y no de la pagina.** Lo que se
     guarda es algo que Jarvis va a EJECUTAR.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nucleo import mcp as mod
from nucleo.mcp import Politica, Servidor, descubrir


def _casa(tmp_path: Path, datos: dict) -> Path:
    (tmp_path / ".claude.json").write_text(json.dumps(datos), encoding="utf-8")
    return tmp_path


# --- 1. DE DONDE SALEN -------------------------------------------------


class TestDondeSeMira:
    def test_el_global_de_tu_claude_code(self, tmp_path) -> None:
        casa = _casa(tmp_path, {"mcpServers": {
            "sentry": {"command": "npx", "args": ["-y", "sentry-mcp"]}}})
        (uno,) = descubrir(casa=casa)
        assert uno.nombre == "sentry"
        assert uno.alcance == "equipo"
        assert uno.resumen == "npx -y sentry-mcp"

    def test_el_de_una_carpeta_dentro_de_claude_json(self, tmp_path) -> None:
        proy = tmp_path / "p"
        proy.mkdir()
        casa = _casa(tmp_path, {"projects": {str(proy): {"mcpServers": {
            "local": {"command": "node", "args": ["s.js"]}}}}})
        (uno,) = descubrir(casa=casa)
        assert uno.alcance == "carpeta"

    def test_el_mcp_json_de_un_proyecto(self, tmp_path) -> None:
        proy = tmp_path / "proyecto"
        proy.mkdir()
        (proy / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "godot": {"command": "npx", "args": ["-y", "godot-mcp"]}}}),
            encoding="utf-8")
        casa = _casa(tmp_path, {"projects": {str(proy): {}}})
        (uno,) = descubrir(casa=casa)
        assert uno.nombre == "godot"
        assert uno.alcance == "proyecto"
        assert uno.origen.endswith(".mcp.json")

    def test_la_carpeta_de_la_SESION_aunque_no_la_conozca_claude(self, tmp_path):
        """Es el caso que mas falta hace: una carpeta recien abierta no
        esta todavia entre los proyectos de `~/.claude.json`."""
        suelta = tmp_path / "nueva"
        suelta.mkdir()
        (suelta / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "x": {"command": "run"}}}), encoding="utf-8")
        casa = _casa(tmp_path, {})
        assert descubrir(casa=casa) == ()
        (uno,) = descubrir(carpetas_extra=(str(suelta),), casa=casa)
        assert uno.nombre == "x"

    def test_NO_barre_el_disco(self, tmp_path) -> None:
        """>>> ESTO NO ES UNA OPTIMIZACION, ES EL ALCANCE <<<

        Se mira donde mira el propio Claude Code: su config y las
        carpetas donde lo has usado. Un barrido del disco encontraria
        `.mcp.json` de repos clonados que nunca has abierto, y los
        pondria en una pantalla con un boton de autorizar al lado.
        """
        escondido = tmp_path / "no_lo_conoce"
        escondido.mkdir()
        (escondido / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "colado": {"command": "malo"}}}), encoding="utf-8")
        assert descubrir(casa=_casa(tmp_path, {})) == ()

    def test_un_json_roto_no_tumba_el_panel(self, tmp_path) -> None:
        """Corre al pintar una pantalla, y `~/.claude.json` es de otro
        programa: puede estar a medio escribir justo cuando se mira."""
        proy = tmp_path / "p"
        proy.mkdir()
        (proy / ".mcp.json").write_text("{ esto no cierra", encoding="utf-8")
        casa = _casa(tmp_path, {"projects": {str(proy): {}}})
        assert descubrir(casa=casa) == ()

    def test_sin_claude_json_no_hay_nada_y_no_revienta(self, tmp_path) -> None:
        assert descubrir(casa=tmp_path) == ()


# --- 2. LOS SECRETOS, QUE ES LO QUE NO PUEDE FALLAR ---------------------


class TestLosSecretosNoSeCopian:
    def test_del_entorno_solo_viajan_los_NOMBRES(self, tmp_path) -> None:
        """>>> SI ESTO SE ROMPE, EL FALLO ES UN TOKEN EN UN COMMIT <<<"""
        proy = tmp_path / "p"
        proy.mkdir()
        (proy / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "s": {"command": "run",
                  "env": {"API_TOKEN": "sk-secreto-de-verdad-123"}}}}),
            encoding="utf-8")
        casa = _casa(tmp_path, {"projects": {str(proy): {}}})
        (uno,) = descubrir(casa=casa)

        assert uno.claves_de_entorno == ("API_TOKEN",)
        crudo = repr(uno) + uno.resumen + json.dumps(uno.a_json())
        assert "sk-secreto" not in crudo, "el valor del token ha salido"
        # Lo que se guardaria es la REFERENCIA, que `_del_entorno`
        # resuelve contra el entorno del proceso al arrancar.
        assert uno.lanzamiento.entorno == {"API_TOKEN": "${API_TOKEN}"}

    def test_lo_mismo_con_las_cabeceras_de_un_http(self, tmp_path) -> None:
        casa = _casa(tmp_path, {"mcpServers": {
            "remoto": {"url": "https://ejemplo/mcp",
                       "headers": {"Authorization": "Bearer sk-no-copiar"}}}})
        (uno,) = descubrir(casa=casa)
        assert uno.lanzamiento.cabeceras == {
            "Authorization": "${Authorization}"}
        assert "sk-no-copiar" not in json.dumps(uno.a_json())

    def test_no_se_adivina_cual_parece_un_secreto(self) -> None:
        """Ni siquiera un `env` inofensivo se copia.

        Un detector de secretos que acierte el 90 % filtra el otro 10 %
        sin decir nada. Este arbol ya lleva cuatro reglas que adivinaban
        lo que hacia una orden y mentian.
        """
        lanzamiento, claves = mod._lanzamiento_de_claude(
            {"command": "uvx", "args": ["blender-mcp"],
             "env": {"UV_SYSTEM_CERTS": "1"}})
        assert claves == ("UV_SYSTEM_CERTS",)
        assert lanzamiento.entorno == {"UV_SYSTEM_CERTS": "${UV_SYSTEM_CERTS}"}


# --- 3. AUTORIZAR, QUE ES UN CLIC Y NO UN CHEQUE EN BLANCO --------------


@pytest.fixture
def consola(tmp_path, monkeypatch):
    """Una consola con su `config/` propio, para no tocar el del usuario."""
    from puente.consola import Consola
    from puente.sesion import Sesion

    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(mod, "CONFIG_DIR", config)

    proy = tmp_path / "proyecto"
    proy.mkdir()
    (proy / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "godot": {"command": "npx", "args": ["-y", "godot-mcp"]},
        "blender": {"command": "uvx", "args": ["blender-mcp@1.6.1"],
                    "env": {"UV_SYSTEM_CERTS": "1"}}}}), encoding="utf-8")
    casa = _casa(tmp_path, {"projects": {str(proy): {}}})
    monkeypatch.setattr(Path, "home", staticmethod(lambda: casa))

    return Consola(Sesion(tmp_path), puerto=8791)


class TestAutorizar:
    def test_el_panel_los_LISTA_sin_autorizarlos(self, consola) -> None:
        """Descubrir no es confiar: mirarlos no los mete en la lista."""
        m = consola.mcp()
        assert sorted(e["nombre"] for e in m["encontrados"]) == [
            "blender", "godot"]
        assert m["servidores"] == [], "descubrir NO puede autorizar"

    def test_autorizar_entra_en_CONFIRMAR(self, consola) -> None:
        """Un clic no vale mas que escribirlo a mano. Que ya estuviera en
        tu Claude Code no dice que deba pasar sin preguntar."""
        r = consola.autorizar_mcp({"nombre": "godot"})
        assert r["ok"] is True
        (uno,) = [s for s in r["servidores"] if s["nombre"] == "godot"]
        assert uno["politica"] == mod.POLITICA_AL_ANADIR.value == "confirmar"
        assert uno["lo_lanza_jarvis"] is True

    def test_la_nota_DICE_de_donde_salio_y_que_falta(self, consola) -> None:
        """Un servidor que no arranca por una variable que falta es de
        los que se depuran a ciegas."""
        consola.autorizar_mcp({"nombre": "blender"})
        (uno,) = [s for s in mod.leer() if s.nombre == "blender"]
        assert ".mcp.json" in uno.nota
        assert "UV_SYSTEM_CERTS" in uno.nota
        assert "NO se copian" in uno.nota
        assert "se versiona" in uno.nota, "hay que decir POR QUE no se copian"

    def test_la_definicion_sale_del_ARCHIVO_no_de_la_pagina(self, consola):
        """>>> LO QUE SE GUARDA ES ALGO QUE JARVIS VA A EJECUTAR <<<

        Del cliente se acepta CUAL, no COMO. Una pagina que pudiera
        mandar la linea de ordenes convertiria este boton en ejecucion
        arbitraria a un POST de distancia.
        """
        consola.autorizar_mcp({"nombre": "godot", "orden": ["rm", "-rf", "/"],
                               "command": "malo"})
        (uno,) = [s for s in mod.leer() if s.nombre == "godot"]
        assert uno.lanzamiento.orden == ("npx", "-y", "godot-mcp")

    def test_uno_que_no_esta_se_rechaza(self, consola) -> None:
        r = consola.autorizar_mcp({"nombre": "inventado"})
        assert r["ok"] is False and "inventado" in r["motivo"]

    def test_IMPORTAR_no_toca_la_politica_que_ya_tenia(self, consola) -> None:
        """>>> BAJARLE EL FRENO POR PULSAR "IMPORTAR" SERIA CAMBIAR
        PERMISOS POR LA PUERTA DE ATRAS <<<

        Es el caso de un servidor declarado con una orden aqui y otra en
        el proyecto. Importar sirve para quedarse con UNA definicion, no
        para reabrir lo que ya decidiste sobre el.
        """
        mod.guardar((Servidor("blender", Politica.PROHIBIDO, "", None),))
        consola.autorizar_mcp({"nombre": "blender"})
        (uno,) = [s for s in mod.leer() if s.nombre == "blender"]
        assert uno.politica is Politica.PROHIBIDO, "le han quitado el freno"
        # Pero la definicion SI se queda con la del archivo.
        assert uno.lanzamiento.orden == ("uvx", "blender-mcp@1.6.1")

    def test_la_sesion_se_entera_EN_CALIENTE(self, consola) -> None:
        """Sin esto el usuario autoriza, ve "guardado", y la siguiente
        peticion sigue denegada: la pantalla mintiendo sobre lo unico que
        no puede mentir."""
        assert consola.sesion.servidores_mcp == ()
        consola.autorizar_mcp({"nombre": "godot"})
        assert [s.nombre for s in consola.sesion.servidores_mcp] == ["godot"]
