"""JC-0015, la mitad que faltaba: que el servidor EXISTA (2026-09-01).

>>> LA LISTA BLANCA GOBERNABA UNA PUERTA QUE NO LLEVABA A NINGUN SITIO <<<
`tests/test_puente_mcp.py` cubre el PERMISO y esta entero. Lo que no
habia era donde decir COMO se arranca un servidor: `Servidor` sabia el
nombre y la politica, y nada mas. Comprobado el 2026-09-01 contra la
maquina real -- cero servidores en `~/.claude.json` (36 proyectos),
ningun `.mcp.json` en el arbol, ningun `config/mcp.yaml` --, o sea que la
lista era exacta y estaba vacia, y no habia forma de llenarla.

MEDIDO CONTRA EL BINARIO ese mismo dia, antes de escribir nada
(`claude 2.1.252`, un servidor MCP de verdad por stdio):

    servidores en system/init   [{"name": "sonda", "status": "connected"}]
    herramientas en init        ["mcp__sonda__sumar"]
    la puerta llega             SI, `can_use_tool` con
                                `tool_name: mcp__sonda__sumar`

Ese ultimo punto es el que importaba y no estaba medido: la tabla de
JC-0015 salio de nuestra `politica.py`, no de una sesion viva. Ahora se
sabe que el nombre que llega es exactamente el que la politica mira.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nucleo import mcp as mod
from nucleo.mcp import Lanzamiento, McpError, Politica, Servidor
from puente.sesion import Sesion


def escribir(tmp_path, texto: str) -> None:
    (tmp_path / "mcp.yaml").write_text(texto, encoding="utf-8")


# --- leer el bloque `lanzar` ------------------------------------------

def test_sin_lanzar_sigue_siendo_valido(tmp_path) -> None:
    """Una entrada sin `lanzar` es PERMISO para uno que venga de fuera.

    Es lo que habia antes del 2026-09-01, y no puede dejar de valer: si
    `lanzar` fuese obligatorio, la lista blanca dejaria de poder gobernar
    los servidores que el usuario tenga en su propio Claude Code.
    """
    escribir(tmp_path, "servidores:\n  - nombre: ajeno\n    politica: auto\n")
    servidor, = mod.leer(config_dir=tmp_path)
    assert servidor.lanzamiento is None
    assert mod.configuracion_para_claude((servidor,)) == {"mcpServers": {}}


def test_stdio(tmp_path) -> None:
    escribir(tmp_path, "servidores:\n"
                       "  - nombre: archivos\n"
                       "    politica: confirmar\n"
                       "    lanzar:\n"
                       "      orden: [npx, -y, servidor-de-archivos, 'C:/x']\n")
    servidor, = mod.leer(config_dir=tmp_path)
    assert servidor.lanzamiento.es_stdio
    assert mod.configuracion_para_claude((servidor,)) == {"mcpServers": {
        "archivos": {"command": "npx",
                     "args": ["-y", "servidor-de-archivos", "C:/x"]}}}


def test_http(tmp_path) -> None:
    escribir(tmp_path, "servidores:\n"
                       "  - nombre: sentry\n"
                       "    politica: auto\n"
                       "    lanzar:\n"
                       "      url: https://ejemplo/mcp\n"
                       "      cabeceras: {Authorization: hola}\n")
    servidor, = mod.leer(config_dir=tmp_path)
    assert not servidor.lanzamiento.es_stdio
    assert mod.configuracion_para_claude((servidor,)) == {"mcpServers": {
        "sentry": {"type": "http", "url": "https://ejemplo/mcp",
                   "headers": {"Authorization": "hola"}}}}


@pytest.mark.parametrize("bloque, porque", [
    ("      orden: [npx]\n      url: https://x\n", "las dos"),
    ("      entorno: {A: b}\n", "ninguna de las dos"),
    ("      orden: npx -y cosa\n", "una cadena en vez de una lista"),
])
def test_un_lanzar_a_medias_LEVANTA(tmp_path, bloque, porque) -> None:
    """>>> Y NO SE IGNORA, QUE ES LA TENTACION <<<

    Un servidor que el usuario creia declarado para arrancar y que no
    arranca es un fallo MUDO: la sesion sube igual, la herramienta
    simplemente no esta, y no hay nada que mirar. Misma regla que un YAML
    roto en `zonas.yaml`.
    """
    escribir(tmp_path, "servidores:\n  - nombre: x\n    politica: auto\n"
                       "    lanzar:\n" + bloque)
    with pytest.raises(McpError):
        mod.leer(config_dir=tmp_path)


def test_una_orden_en_una_cadena_no_se_parte_por_espacios(tmp_path) -> None:
    """Adivinar donde acaba una ruta con espacios es Windows entero."""
    escribir(tmp_path, "servidores:\n  - nombre: x\n    politica: auto\n"
                       "    lanzar:\n      orden: C:/Archivos de programa/x.exe\n")
    with pytest.raises(McpError) as exc:
        mod.leer(config_dir=tmp_path)
    assert "espacios" in str(exc.value)


# --- los secretos -----------------------------------------------------

def test_un_token_se_toma_del_entorno_y_no_del_yaml(tmp_path, monkeypatch) -> None:
    """`config/mcp.yaml` SI se versiona, al reves que telegram.yaml."""
    monkeypatch.setenv("UN_TOKEN_DE_PRUEBA", "secreto-de-verdad")
    escribir(tmp_path, "servidores:\n  - nombre: s\n    politica: auto\n"
                       "    lanzar:\n      url: https://x\n"
                       "      cabeceras: {Authorization: '${UN_TOKEN_DE_PRUEBA}'}\n")
    servidores = mod.leer(config_dir=tmp_path)
    generado = mod.configuracion_para_claude(servidores)
    assert generado["mcpServers"]["s"]["headers"]["Authorization"] == "secreto-de-verdad"
    # Y en el archivo del usuario NO esta el secreto.
    assert "secreto-de-verdad" not in (tmp_path / "mcp.yaml").read_text(encoding="utf-8")


def test_una_variable_que_no_existe_se_deja_a_la_vista(tmp_path, monkeypatch) -> None:
    """Quedarse en blanco daria un 401 raro; el ${NOMBRE} dice que falta."""
    monkeypatch.delenv("NO_EXISTE_ESTA_VARIABLE", raising=False)
    escribir(tmp_path, "servidores:\n  - nombre: s\n    politica: auto\n"
                       "    lanzar:\n      url: https://x\n"
                       "      cabeceras: {Authorization: '${NO_EXISTE_ESTA_VARIABLE}'}\n")
    generado = mod.configuracion_para_claude(mod.leer(config_dir=tmp_path))
    assert generado["mcpServers"]["s"]["headers"]["Authorization"] == \
        "${NO_EXISTE_ESTA_VARIABLE}"


# --- que se arranca y que no ------------------------------------------

def test_un_prohibido_NO_SE_ARRANCA() -> None:
    """>>> "PROHIBIDO" TIENE QUE SIGNIFICAR QUE NO CORRE <<<

    Arrancarlo para denegarle cada llamada despues seria ejecutar el
    programa igual. Un servidor MCP es un PROCESO, no una regla: quedaria
    un subproceso vivo, con la autoridad de la sesion, cuya unica
    diferencia con uno permitido es que nadie le contesta. Y esto puede
    estar corriendo todo el dia desde el inicio de Windows.
    """
    lanza = Lanzamiento(orden=("cosa",))
    servidores = (Servidor("bueno", Politica.AUTO, lanzamiento=lanza),
                  Servidor("malo", Politica.PROHIBIDO, lanzamiento=lanza))
    generado = mod.configuracion_para_claude(servidores)
    assert list(generado["mcpServers"]) == ["bueno"]


# --- que el panel no se lo cargue -------------------------------------

def test_guardar_desde_el_panel_NO_borra_el_lanzar(tmp_path) -> None:
    """>>> EL FALLO MUDO QUE ESTO IMPIDE, Y APARECIO CONSTRUYENDO <<<

    `guardar` reescribe el archivo ENTERO -- tiene que hacerlo, o no se
    podria quitar un servidor -- y el panel solo conoce nombre, politica
    y nota. Sin arrastrar el `lanzamiento` que ya estaba, cambiar una
    politica de `confirmar` a `auto` borraba la linea de ordenes: al
    reiniciar la herramienta ya no existia, sin un solo error y con la
    pantalla diciendo "guardado".
    """
    mod.guardar((Servidor("archivos", Politica.CONFIRMAR,
                          lanzamiento=Lanzamiento(orden=("npx", "-y", "x"))),),
                config_dir=tmp_path)

    # Lo que hace la consola: rehacer las filas desde el formulario.
    antes = {s.nombre: s.lanzamiento for s in mod.leer(config_dir=tmp_path)}
    rehecho = (Servidor("archivos", Politica.AUTO, "", antes.get("archivos")),)
    mod.guardar(rehecho, config_dir=tmp_path)

    despues, = mod.leer(config_dir=tmp_path)
    assert despues.politica is Politica.AUTO, "no se guardo el cambio"
    assert despues.lanzamiento is not None, "el panel borro el `lanzar`"
    assert despues.lanzamiento.orden == ("npx", "-y", "x")


def test_ida_y_vuelta_con_lanzar(tmp_path) -> None:
    original = (
        Servidor("uno", Politica.AUTO,
                 lanzamiento=Lanzamiento(orden=("a", "b"), entorno={"K": "v"})),
        Servidor("dos", Politica.CONFIRMAR, "una nota",
                 lanzamiento=Lanzamiento(url="https://x",
                                         cabeceras={"H": "v"})),
        Servidor("tres", Politica.PROHIBIDO),
    )
    mod.guardar(original, config_dir=tmp_path)
    assert mod.leer(config_dir=tmp_path) == original


def test_el_archivo_generado_es_el_que_espera_claude_code(tmp_path) -> None:
    """La forma la fija el binario, no nosotros: `{"mcpServers": {...}}`.

    Comprobada contra `claude 2.1.252` el 2026-09-01: con esta forma el
    `system/init` devolvio `status: connected` y la herramienta aparecio
    como `mcp__sonda__sumar`.
    """
    generado = mod.configuracion_para_claude(
        (Servidor("sonda", Politica.AUTO,
                  lanzamiento=Lanzamiento(orden=("python", "s.py", "h.txt"))),))
    assert generado == {"mcpServers": {
        "sonda": {"command": "python", "args": ["s.py", "h.txt"]}}}


# --- el cableado de la sesion -----------------------------------------

def test_la_sesion_pasa_el_archivo() -> None:
    orden = Sesion("C:/", mcp_config="C:/logs/mcp.json").orden
    assert "--mcp-config" in orden
    # Resuelta, no literal: la lee el hijo contra SU cwd. Ver
    # `TestLasRutasQueLeeElHijo` al final de este archivo.
    assert (Path(orden[orden.index("--mcp-config") + 1])
            == Path("C:/logs/mcp.json").resolve())
    assert "--strict-mcp-config" not in orden


def test_sin_servidores_no_aparece_el_flag() -> None:
    assert "--mcp-config" not in Sesion("C:/").orden


def test_el_estricto_es_aparte_del_archivo() -> None:
    """Son dos decisiones: cuales trae Jarvis, y si ademas entran otros."""
    orden = Sesion("C:/", mcp_config="m.json", mcp_estricto=True).orden
    assert "--strict-mcp-config" in orden


def test_lo_que_se_deniega_no_depende_del_estricto() -> None:
    """>>> LA FRASE QUE SOSTIENE EL AJUSTE, Y HAY QUE PODER PROBARLA <<<

    El aviso del panel dice que el estricto NO cambia lo que se deniega,
    solo lo que se arranca. Quien decide lo primero es `politica.py` con
    `servidores_mcp`, que no sabe nada de esto.
    """
    from puente.politica import Veredicto, decidir
    from puente.protocolo import Puerta

    puerta = Puerta(id_peticion="1", herramienta="mcp__ajeno__lo_que_sea",
                    entrada={}, descripcion="", id_uso="u")
    for estricto in (True, False):
        sesion = Sesion("C:/", mcp_config="m.json", mcp_estricto=estricto,
                        servidores_mcp=())
        assert ("--strict-mcp-config" in sesion.orden) is estricto
        assert decidir(puerta, servidores_mcp=sesion.servidores_mcp
                       ).veredicto is Veredicto.DENEGAR


class TestLasRutasQueLeeElHijo:
    """>>> LAS RESUELVE `claude`, NO NOSOTROS (medido el 2026-09-01) <<<

    Aparecio probando el servidor de Blender de punta a punta, que es lo
    unico que podia enseñarlo: `--mcp-config` y `--settings` los abre el
    proceso hijo contra SU directorio de trabajo, que es el del proyecto
    del usuario y no el nuestro. Con una ruta relativa, la sesion entera
    muere al abrirse y el sintoma es malo de leer:

        stderr: Error: Invalid MCP configuration:
        stderr: MCP config file not found: <cwd del proyecto>/logs/...

    Eso llega como `LineaIlegible` y acaba en un `Caida` sin codigo. Hoy
    `puente/__main__.py` las construye desde `PROJECT_ROOT`, o sea
    absolutas, asi que estaba tapado por casualidad: cualquiera que
    montase una `Sesion` a mano se lo comia entero.

    Van las DOS en el mismo sitio a proposito: es un fallo de
    FORMA, y al arreglarlo en `--mcp-config` habia que mirar quien mas
    entregaba una ruta por `str()`. Solo estas dos.
    """

    def test_el_mcp_config_va_absoluto(self) -> None:
        orden = Sesion("C:/", mcp_config="logs/puente/mcp.json").orden
        entregada = orden[orden.index("--mcp-config") + 1]
        assert Path(entregada).is_absolute()

    def test_el_suelo_va_absoluto(self) -> None:
        orden = Sesion("C:/", ajustes="logs/puente/suelo.json").orden
        entregada = orden[orden.index("--settings") + 1]
        assert Path(entregada).is_absolute()

    def test_una_ruta_ya_absoluta_no_se_toca(self, tmp_path) -> None:
        archivo = tmp_path / "mcp.json"
        archivo.write_text("{}", encoding="utf-8")
        orden = Sesion("C:/", mcp_config=archivo).orden
        assert orden[orden.index("--mcp-config") + 1] == str(archivo)
