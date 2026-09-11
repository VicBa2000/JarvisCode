"""La misma frase tiene que hacer lo mismo dicha que escrita.

>>> LO REPORTO EL USUARIO EL 2026-09-03, CON LAS DOS TRAZAS <<<
El usuario conto que la misma instruccion dada por consola y dada por voz
producia resultados distintos. Dijo y escribio la MISMA frase -- continuar
con el proyecto Faro, mirar que avance tiene y escribir un documento
llamado roadmap.md -- y salio esto:

    por voz      Sesion abierta en C:\\proyectos\\faro
    por consola  Sesion abierta en C:\\proyectos\\carpetadepruebas
                 ...y Claude Code haciendo `Glob **/*faro*` ahi dentro

La interceptacion de ADR-0029 vivia SOLO en `voz/bucle.py`, y
`Sesion.cambiar_a` tenia UN unico llamador en todo el arbol.

>>> NO ERA UNA DECISION, ERA UN HUECO <<<
El razonamiento que justifica interceptar -- que Claude Code no puede
cambiar el directorio de su propia sesion -- habla de la NATURALEZA de
la orden, no del canal. Tecleada sigue siendo una orden SOBRE Jarvis.

Y el fallo era de los caros: NO DA ERROR. El cerebro es capaz, asi que
hace algo plausible en la carpeta que no es -- y te escribe el documento
alli.

LO QUE FIJA ESTE ARCHIVO: que el decisor sea UNO. No que las dos salidas
sean iguales al pie de la letra -- la voz habla y la consola pinta, y eso
no se puede compartir --, sino que la DECISION salga del mismo sitio.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nucleo.proyectos import CLAVE_INTERCEPTA, CLAVE_VIEJA, Proyecto, intercepta
from voz.proyecto import Cambio, atender

RAIZ = Path(__file__).resolve().parent.parent


class SesionPostiza:
    """Solo lo que `atender` toca: mudarse de carpeta."""

    def __init__(self) -> None:
        self.movidas: list[tuple[str, str | None]] = []

    def cambiar_a(self, carpeta, modo_permisos=None) -> None:
        self.movidas.append((str(carpeta), modo_permisos))


@pytest.fixture
def registro(tmp_path):
    """Un registro con un proyecto de verdad y el interruptor puesto."""
    carpeta = tmp_path / "faro"
    carpeta.mkdir()
    (tmp_path / "proyectos.yaml").write_text(
        f"{CLAVE_INTERCEPTA}: true\n"
        f"proyectos:\n- alias: Faro\n  carpeta: {carpeta}\n  auto: true\n",
        encoding="utf-8")
    return tmp_path, carpeta


# --- 1. EL INTERRUPTOR, QUE CAMBIO DE NOMBRE ---------------------------


class TestElInterruptor:
    def test_se_lee_el_nombre_NUEVO(self, tmp_path) -> None:
        (tmp_path / "proyectos.yaml").write_text(
            f"{CLAVE_INTERCEPTA}: true\nproyectos: []\n", encoding="utf-8")
        assert intercepta(tmp_path) is True

    def test_y_el_VIEJO_SIGUE_VALIENDO(self, tmp_path) -> None:
        """>>> ESTO NO ES CORTESIA, ES NO ROMPER LO QUE YA FUNCIONA <<<

        `config/proyectos.yaml` del usuario dice `por_voz: true` desde
        agosto. Un renombrado que se lo deje apagado sin avisar no es un
        renombrado: es una regresion muda, y ademas en el interruptor que
        decide si una frase suya llega al cerebro.
        """
        (tmp_path / "proyectos.yaml").write_text(
            f"{CLAVE_VIEJA}: true\nproyectos: []\n", encoding="utf-8")
        assert intercepta(tmp_path) is True

    def test_el_nuevo_MANDA_sobre_el_viejo(self, tmp_path) -> None:
        """Con los dos escritos gana el nuevo, que es el que se escribe
        hoy: si no, apagarlo desde el panel no lo apagaria."""
        (tmp_path / "proyectos.yaml").write_text(
            f"{CLAVE_INTERCEPTA}: false\n{CLAVE_VIEJA}: true\nproyectos: []\n",
            encoding="utf-8")
        assert intercepta(tmp_path) is False

    def test_ausente_significa_APAGADO(self, tmp_path) -> None:
        (tmp_path / "proyectos.yaml").write_text(
            "proyectos: []\n", encoding="utf-8")
        assert intercepta(tmp_path) is False

    def test_lo_que_se_ESCRIBE_es_el_nombre_nuevo(self, tmp_path) -> None:
        from nucleo.proyectos import guardar

        guardar((Proyecto("x", str(tmp_path)),), activo=True,
                config_dir=tmp_path)
        crudo = (tmp_path / "proyectos.yaml").read_text(encoding="utf-8")
        # El comentario de cabecera nombra los dos; lo que se mira es la
        # CLAVE de datos, o sea la linea sin `#` delante.
        datos = [l for l in crudo.splitlines() if not l.lstrip().startswith("#")]
        assert any(l.startswith(CLAVE_INTERCEPTA + ":") for l in datos)
        assert not any(l.startswith(CLAVE_VIEJA + ":") for l in datos)


# --- 2. EL DECISOR, QUE ES UNO -----------------------------------------


class TestElDecisorEsUno:
    def test_solo_hay_UN_llamador_de_cambiar_a(self) -> None:
        """>>> ESTA ES LA REGLA ENTERA, Y SE MIRA EN EL ARBOL <<<

        `Sesion.cambiar_a` mueve la sesion de carpeta. Si vuelve a
        haber dos sitios que lo llamen, los dos canales volveran a
        resolver el mismo nombre de dos maneras -- que es como
        divergieron los tres normalizadores de `voz/`, y por lo que
        existe `nucleo.proyectos.modo_para`.

        El unico llamador legitimo es `voz.proyecto.atender`, que es
        justo el sitio que comparten la voz y la consola.
        """
        llamadores = []
        for paquete in ("puente", "voz", "nucleo", "canales", "escritorio"):
            for ruta in (RAIZ / paquete).rglob("*.py"):
                texto = ruta.read_text(encoding="utf-8")
                for n, linea in enumerate(texto.splitlines(), 1):
                    limpia = linea.strip()
                    if limpia.startswith("#") or "def cambiar_a" in limpia:
                        continue
                    if ".cambiar_a(" in limpia:
                        llamadores.append(f"{ruta.name}:{n}")
        assert llamadores == ["proyecto.py:" + llamadores[0].split(":")[1]], (
            f"cambiar_a se llama desde {llamadores}. Tiene que llamarse "
            f"SOLO desde `voz.proyecto.atender`: un segundo sitio es un "
            f"segundo criterio para resolver el mismo nombre.")

    def test_APAGADO_ni_se_mira_la_frase(self, tmp_path) -> None:
        """Y ese orden importa: mirando la frase primero, una orden
        normal que sonara a esto se quedaria por el camino con el flujo
        apagado -- interceptada por algo que nadie encendio."""
        (tmp_path / "proyectos.yaml").write_text(
            "proyectos: []\n", encoding="utf-8")
        sesion = SesionPostiza()
        r = atender("continua con el proyecto Faro", sesion, tmp_path)
        assert r.cambio is Cambio.APAGADO
        assert r.se_ocupo is False, "apagado, la frase va al cerebro"
        assert sesion.movidas == []

    def test_una_orden_normal_NO_se_toca(self, registro) -> None:
        config, _ = registro
        sesion = SesionPostiza()
        r = atender("abre el bloc de notas", sesion, config)
        assert r.cambio is Cambio.NO_ES
        assert r.se_ocupo is False
        assert sesion.movidas == []

    def test_LA_FRASE_DEL_USUARIO_abre_y_conserva_la_cola(self, registro):
        """La frase exacta que reporto, con su coma y su cola."""
        config, carpeta = registro
        sesion = SesionPostiza()
        r = atender(
            "continua con el proyecto Faro, checa que avance tiene el "
            "proyecto y hazme un documento llamado roadmap.md",
            sesion, config)
        assert r.cambio is Cambio.ABIERTO
        assert sesion.movidas == [(str(carpeta), "auto")]
        # La cola NO se pierde: es la mitad de la orden.
        assert "roadmap.md" in r.cola
        # Y con su punto, que sale del texto ORIGINAL y no del
        # normalizado -- "roadmap md" no es un nombre de archivo.
        assert "roadmap.md" in r.cola and "roadmap md" not in r.cola

    def test_sin_cola_no_hay_cola(self, registro) -> None:
        """Sin instruccion detras, el canal manda el ritual. Que la cola
        salga vacia es lo que se lo dice."""
        config, _ = registro
        r = atender("continua con el proyecto Faro", SesionPostiza(), config)
        assert r.cambio is Cambio.ABIERTO
        assert r.cola == ""

    def test_un_nombre_que_no_existe_NO_abre_nada(self, registro) -> None:
        """ADR-0029: no se busca por el disco a ver si suena. Abrir la
        carpeta equivocada lanza un agente sobre codigo que no era."""
        config, _ = registro
        sesion = SesionPostiza()
        r = atender("continua con el proyecto morrocotudo", sesion, config)
        assert r.cambio is Cambio.DESCONOCIDO
        assert r.se_ocupo is True, "no puede seguir al cerebro como si nada"
        assert sesion.movidas == []

    def test_sin_nombre_se_PREGUNTA(self, registro) -> None:
        config, _ = registro
        r = atender("ve al proyecto, mira el readme", SesionPostiza(), config)
        assert r.cambio is Cambio.SIN_NOMBRE
        assert r.se_ocupo is True

    def test_el_modo_VIAJA_con_la_carpeta(self, registro) -> None:
        """JC-0017: el auto mode es del PROYECTO. Quedarse con el del
        anterior seria estrenar -- o perder -- permisos por pedir un
        cambio de carpeta, y el fallo es mudo en las dos direcciones."""
        config, carpeta = registro
        sesion = SesionPostiza()
        atender("continua con el proyecto Faro", sesion, config)
        assert sesion.movidas[0][1] == "auto"


# --- 3. LA CONSOLA, QUE ES LO QUE FALTABA ------------------------------


class TestLaConsolaTambien:
    def test_la_consola_llama_al_MISMO_decisor(self) -> None:
        """Se mira el codigo y no el comportamiento a proposito: lo que
        no puede volver a pasar es que la consola tenga su propia copia
        de la decision."""
        fuente = (RAIZ / "puente" / "consola.py").read_text(encoding="utf-8")
        assert "from voz.proyecto import" in fuente
        assert "atender(" in fuente
        # Y NO puede tener su propio resolvedor.
        assert "resolver(" not in fuente, (
            "la consola esta resolviendo nombres por su cuenta")

    def test_el_turno_intercepta_ANTES_de_abrir_la_sesion(self) -> None:
        """`cambiar_a` cierra la sesion y repunta el directorio. Abrir
        primero levantaria el binario de 337 MB en la carpeta VIEJA para
        cerrarlo acto seguido -- y con el sello caducado, pagando ademas
        un turno de senuelo en el sitio equivocado."""
        fuente = (RAIZ / "puente" / "consola.py").read_text(encoding="utf-8")
        trozo = fuente[fuente.index('if self.path == "/turno"'):]
        trozo = trozo[:trozo.index('elif self.path ==')]
        assert trozo.index("cambiar_de_proyecto") < trozo.index(
            "asegurar_sesion"), (
            "se abre la sesion antes de saber en que carpeta va")

    def test_se_anuncia_lo_que_ESCRIBISTE_lo_primero(self) -> None:
        """Aunque la frase acabe siendo un cambio de proyecto y lo que
        viaje sea la cola. El anuncio existe para que compruebes que se
        te entendio; es la misma regla que la voz."""
        fuente = (RAIZ / "puente" / "consola.py").read_text(encoding="utf-8")
        trozo = fuente[fuente.index('if self.path == "/turno"'):]
        trozo = trozo[:trozo.index('elif self.path ==')]
        assert trozo.index('anuncia_turno(texto, "consola")') < trozo.index(
            "cambiar_de_proyecto")

    def test_el_ritual_no_se_pinta_como_tuyo(self) -> None:
        """Lo corrigio el usuario mirandolo el 2026-08-27: el flujo del
        ritual esta bien, pero esa frase no es suya.

        >>> Y DESDE EL 2026-09-05 EL RITUAL SI LO ESCRIBE EL USUARIO,
            ASI QUE HAY QUE DECIR POR QUE ESTO SIGUE VALIENDO <<<
        La distincion no era "quien redacto el texto", era CUANDO se
        dijo. La cola es lo que acabas de dictar o teclear en ESTA
        frase, y el registro la pinta como tuya para que compruebes que
        se te entendio -- que es para lo que existe ese renglon. El
        ritual lo dejaste escrito en Ajustes hace semanas: pintarlo como
        recien dicho enseñaria una transcripcion que nadie hizo. Sigue
        siendo `"ritual"` y no `"consola"`.
        """
        fuente = (RAIZ / "puente" / "consola.py").read_text(encoding="utf-8")
        trozo = fuente[fuente.index("def cambiar_de_proyecto"):
                       fuente.index("def avisa")]
        assert 'return r.cola, "consola"' in trozo
        assert 'return ritual, "ritual"' in trozo
