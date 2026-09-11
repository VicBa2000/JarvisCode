"""JC-0017: el auto mode nativo, acotado por proyecto (2026-08-29).

>>> QUE SE DECIDIO, Y QUIEN <<<
El usuario, despues de desarrollar un proyecto entero hablando: el auto
mode es algo que se activa o se desactiva en Claude Code, no algo con lo
que se nace siempre; en los proyectos ya registrados viene activado por
defecto, y ademas hay un interruptor global, dejando explicito lo que eso
implica y con el usuario aceptandolo.

>>> LO QUE SE APAGA CON ESTO, Y POR ESO ESTOS TESTS EXISTEN <<<
En auto mode el puente se queda SORDO -- medido el 2026-08-21, un `rm`
ejecutandose sin un solo aviso --, asi que dejan de mirarse a la vez la
lista endurecida de JC-0001, la lista blanca de MCP de JC-0015 y la
peticion hablada de JC-0002. Lo que NO se apaga, medido el 27 contra los
cinco modos: el suelo de JC-0007.

Asi que lo que se prueba aqui no es "que funcione": es que **el modo no
se encienda solo en sitios donde nadie lo pidio**, y que cuando este
encendido se VEA. Cada test que se afloje aqui es un sitio donde una
sesion se queda sin frenos sin que el usuario lo sepa.
"""

from __future__ import annotations

import pytest

from nucleo.proyectos import Proyecto, ProyectosError, guardar, leer, modo_para


def registro(tmp_path, proyectos, por_voz=True):
    guardar(proyectos, activo=por_voz, config_dir=tmp_path)
    return tmp_path


class TestElProyectoLlevaSuModo:

    def test_un_proyecto_registrado_nace_con_auto_mode(self):
        """Lo pidio el usuario asi, y va contra el patron del arbol.

        Estar en el registro ya es una decision deliberada -- ADR-0029 lo
        hizo explicito para que abrir la carpeta equivocada no pudiera
        pasar por accidente --, asi que el auto mode se hereda de esa
        decision y no de un descuido.
        """
        assert Proyecto("x", r"C:\p\x").auto is True
        assert Proyecto("x", r"C:\p\x").modo_permisos == "auto"

    def test_se_puede_apagar_por_proyecto(self):
        """"Acotado por proyecto" quiere decir que se puede acotar."""
        apagado = Proyecto("x", r"C:\p\x", auto=False)
        assert apagado.modo_permisos == "default"

    def test_el_modo_llega_al_json_que_pinta_la_pantalla(self):
        assert Proyecto("x", r"C:\p\x", auto=False).a_json()["auto"] is False


class TestElRegistroEnDisco:

    def test_ausente_significa_ENCENDIDO_y_es_al_reves_que_el_resto(
            self, tmp_path):
        """>>> LA EXCEPCION DEL ARBOL, ESCRITA EN UN TEST <<<
        En `zonas.yaml` y en `mcp.yaml` una clave ausente significa
        NINGUNA, porque alli lo que se declara es permiso. Aqui lo que se
        declara es un PROYECTO. Si alguien "uniformiza" esto, un registro
        editado a mano se quedaria sin auto mode en silencio.
        """
        (tmp_path / "proyectos.yaml").write_text(
            "por_voz: true\nproyectos:\n- alias: x\n  carpeta: C:\\p\\x\n",
            encoding="utf-8")
        assert leer(tmp_path)[0].auto is True

    def test_un_auto_false_escrito_a_mano_se_respeta(self, tmp_path):
        (tmp_path / "proyectos.yaml").write_text(
            "proyectos:\n- alias: x\n  carpeta: C:\\p\\x\n  auto: false\n",
            encoding="utf-8")
        assert leer(tmp_path)[0].auto is False

    def test_un_auto_que_no_es_booleano_LEVANTA(self, tmp_path):
        """`auto: "no"` es una cadena, y una cadena no vacia es cierta.

        Tragarselo encenderia el auto mode en el proyecto de alguien que
        acaba de escribir lo contrario.
        """
        (tmp_path / "proyectos.yaml").write_text(
            'proyectos:\n- alias: x\n  carpeta: C:\\p\\x\n  auto: "no"\n',
            encoding="utf-8")
        with pytest.raises(ProyectosError):
            leer(tmp_path)

    def test_guardar_lo_escribe_SIEMPRE_y_dice_lo_que_implica(self, tmp_path):
        """Un archivo nuestro no depende nunca del defecto, y el que lo
        abra tiene que leer lo que apaga sin ir a buscarlo."""
        registro(tmp_path, [Proyecto("x", r"C:\p\x", auto=False)])
        crudo = (tmp_path / "proyectos.yaml").read_text(encoding="utf-8")
        assert "auto: false" in crudo
        assert "git push" in crudo, "no dice lo que deja de mirarse"
        assert "SORDO" in crudo
        assert "suelo de JC-0007" in crudo, "ni lo que SI sigue en pie"


class TestQueModoLeTocaACadaCarpeta:
    """`modo_para` es el UNICO sitio que lo decide, y por eso se prueba
    aqui entero: lo usan el arranque y el cambio de proyecto hablando."""

    def test_un_proyecto_registrado_abre_en_auto(self, tmp_path):
        registro(tmp_path, [Proyecto("x", r"C:\p\x")])
        assert modo_para(r"C:\p\x", global_auto=False,
                         config_dir=tmp_path) == "auto"

    def test_un_SUBDIRECTORIO_del_proyecto_tambien(self, tmp_path):
        """Trabajar en `X/core` es seguir dentro de X. Con igualdad de
        rutas, el auto mode se apagaria en cuanto Claude Code se moviera
        a una subcarpeta, que es lo que hace todo el rato."""
        registro(tmp_path, [Proyecto("x", r"C:\p\x")])
        assert modo_para(r"C:\p\x\core\memory", global_auto=False,
                         config_dir=tmp_path) == "auto"

    def test_una_carpeta_QUE_NO_ES_NADIE_abre_con_freno(self, tmp_path):
        """>>> EL SUELO DE ESTA FUNCION, Y NO SE NEGOCIA <<<
        "No se me ha dicho nada de esta carpeta" no puede significar
        "sin frenos"."""
        registro(tmp_path, [Proyecto("x", r"C:\p\x")])
        assert modo_para(r"C:\otra\cosa", global_auto=False,
                         config_dir=tmp_path) == "default"

    def test_un_proyecto_con_auto_false_abre_con_freno(self, tmp_path):
        registro(tmp_path, [Proyecto("x", r"C:\p\x", auto=False)])
        assert modo_para(r"C:\p\x", global_auto=False,
                         config_dir=tmp_path) == "default"

    def test_el_interruptor_GLOBAL_alcanza_a_la_carpeta_base(self, tmp_path):
        """Es lo que lo distingue del de por proyecto: vale para todo."""
        registro(tmp_path, [Proyecto("x", r"C:\p\x")])
        assert modo_para(r"C:\otra\cosa", global_auto=True,
                         config_dir=tmp_path) == "auto"

    def test_gana_el_proyecto_MAS_PROFUNDO(self, tmp_path):
        """Un proyecto dentro de otro: manda el que se nombro mas de
        cerca, no el que estuviera primero en el archivo."""
        registro(tmp_path, [Proyecto("fuera", r"C:\p"),
                            Proyecto("dentro", r"C:\p\x", auto=False)])
        assert modo_para(r"C:\p\x\core", global_auto=False,
                         config_dir=tmp_path) == "default"

    def test_un_registro_ROTO_no_puede_abrir_permisos(self, tmp_path):
        """`leer()` grita donde toca. Aqui un archivo roto tiene que
        contestar lo seguro, no lo comodo."""
        (tmp_path / "proyectos.yaml").write_text(
            "proyectos: [[[", encoding="utf-8")
        assert modo_para(r"C:\p\x", global_auto=False,
                         config_dir=tmp_path) == "default"

    def test_sin_archivo_de_registro_tampoco(self, tmp_path):
        assert modo_para(r"C:\p\x", global_auto=False,
                         config_dir=tmp_path) == "default"


class TestElModoLlegaALaLineaDeOrdenes:

    def _sesion(self, tmp_path, **kw):
        from puente.sesion import Sesion

        return Sesion(tmp_path, **kw)

    def test_por_defecto_la_puerta_sigue_puesta(self, tmp_path):
        """El defecto del constructor NO cambio, y es importante: los
        tests, las sondas y el senuelo del suelo lo dan por hecho."""
        assert "--permission-mode" in self._sesion(tmp_path).orden
        orden = self._sesion(tmp_path).orden
        assert orden[orden.index("--permission-mode") + 1] == "default"

    def test_el_modo_pedido_viaja_al_binario(self, tmp_path):
        orden = self._sesion(tmp_path, modo_permisos="auto").orden
        assert orden[orden.index("--permission-mode") + 1] == "auto"

    def test_cambiar_de_proyecto_REPUNTA_el_modo(self, tmp_path):
        """>>> EL FALLO SERIA MUDO EN LAS DOS DIRECCIONES <<<
        Entrar en un proyecto con freno desde otro sin freno significa
        que te empieza a preguntar y no sabes por que; al reves,
        significa que deja de preguntarte sin que nadie lo pidiera.
        """
        otra = tmp_path / "otro"
        otra.mkdir()
        sesion = self._sesion(tmp_path, modo_permisos="auto")
        sesion.cambiar_a(otra, modo_permisos="default")
        assert sesion.modo_permisos == "default"
        assert sesion.orden[sesion.orden.index("--permission-mode") + 1] \
            == "default"

    def test_sin_decir_el_modo_no_se_toca(self, tmp_path):
        """Un cambio de carpeta que no venga del registro no reparte
        permisos por su cuenta."""
        otra = tmp_path / "otro"
        otra.mkdir()
        sesion = self._sesion(tmp_path, modo_permisos="auto")
        sesion.cambiar_a(otra)
        assert sesion.modo_permisos == "auto"

    def test_el_suelo_NO_viaja_con_el_proyecto(self, tmp_path):
        """La otra mitad, y es la que no puede cambiar: el suelo es de la
        MAQUINA. Cambiar de carpeta no puede estrenar permisos."""
        otra = tmp_path / "otro"
        otra.mkdir()
        zona = object()
        sesion = self._sesion(tmp_path, zonas=(zona,), modo_permisos="auto")
        sesion.cambiar_a(otra, modo_permisos="default")
        assert sesion.zonas == (zona,)


class TestLaPantallaLoDICE:
    """>>> SORDOS NO ES CIEGOS, PERO TIENE QUE VERSE QUE ESTAMOS SORDOS <<<
    En auto mode la consola sigue ensenando cada `tool_use`. Lo que deja
    de verse es que ya nada lo para, y esa ausencia no tiene sintoma: la
    pantalla de una sesion sin frenos y la de una que no ha hecho nada
    peligroso son identicas.
    """

    def _consola(self, tmp_path, modo):
        from puente.consola import Consola
        from puente.sesion import Sesion

        return Consola(Sesion(tmp_path, modo_permisos=modo))

    def test_con_auto_mode_la_cabecera_lo_dice(self, tmp_path):
        puerta = self._consola(tmp_path, "auto")._puerta()
        assert puerta["auto"] is True
        assert puerta["modo"] == "auto"
        assert "git push" in puerta["motivo"], "no nombra lo que se apaga"
        assert "selladas" in puerta["motivo"], "ni lo que sigue en pie"

    def test_y_TAMBIEN_lo_dice_cuando_esta_puesta(self, tmp_path):
        """Misma regla que el suelo: un aviso que solo aparece cuando
        algo va mal se confunde con que no hay aviso."""
        puerta = self._consola(tmp_path, "default")._puerta()
        assert puerta["auto"] is False
        assert puerta["motivo"]
