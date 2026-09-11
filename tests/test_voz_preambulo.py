"""El preambulo dice cuatro cosas del canal. Las cuatro tienen que ser
verdad, y por eso cada una tiene aqui su test contra el codigo que la
produce -- no contra su docstring.

>>> QUE SE ROMPE SI UNO DE ESTOS FALLA <<<
No "un test". Lo que se rompe es que el texto que se le manda al modelo
en CADA turno le describa mal su propia salida. Un preambulo que miente
es peor que no tener ninguno: el modelo escribe contra un canal que no
existe y nadie ve el fallo, porque la respuesta sigue sonando.

Asi que si uno de estos salta, se arregla EL TEXTO, no el test.
"""

from __future__ import annotations

import pytest

from puente.consola import a_json
from puente.protocolo import Fin
from puente.sesion import Sesion
from voz.preambulo import CABECERA as PREAMBULO_IDIOMAS
from voz.preambulo import preambulo
from voz.resumen import LIMITE_HABLADO, para_un_oido

CON_CODIGO = (
    "Ya esta arreglado, era el umbral.\n\n"
    "```python\nUMBRAL_SIN_SENAL = 7e-5\nprint('no me leas en alto')\n```\n"
)
CON_TABLA = (
    "Esto es lo que hay:\n\n"
    "| modo | puertas |\n"
    "|------|---------|\n"
    "| auto | 0       |\n"
)


# --- las cuatro afirmaciones del texto --------------------------------

def test_el_codigo_no_se_locuta():
    """"Los bloques de codigo NO se locutan nunca"."""
    hablado = para_un_oido(CON_CODIGO, limite=None).hablado
    assert "UMBRAL_SIN_SENAL" not in hablado
    assert "no me leas en alto" not in hablado
    assert "umbral" in hablado          # la prosa si pasa
    for idioma in PREAMBULO_IDIOMAS:
        texto = preambulo(idioma)
        assert "NEVER spoken" in texto or "NO se locutan nunca" in texto


def test_las_tablas_si_se_locutan_y_el_texto_lo_admite():
    """"Las tablas SI se locutan, con sus barras".

    >>> ESTE TEST PINEA ALGO INCOMODO, Y A PROPOSITO <<<
    `sin_markdown` no toca las tablas: llegan al TTS enteras. El dia que
    alguien las filtre, ESTE test falla -- y esa es toda su gracia,
    porque ese dia el preambulo pasa a mentir y hay que reescribirlo.
    Son 5 de 93 en los registros reales (`-m eval.mirar_respuestas`).
    """
    hablado = para_un_oido(CON_TABLA, limite=None).hablado
    assert "|" in hablado, (
        "las tablas ya no llegan al TTS: quita esa linea del preambulo")


def test_los_dos_canales_son_de_verdad_distintos():
    """"Se locuta ENTERA" y "solo las primeras frases" son las dos ciertas,
    cada una en su modo. Es la razon de que el texto sea variable.

    >>> ESTO LO DESTAPO `config/ajustes.yaml`, NO LA PROSA <<<
    El documento dice que JC-0004 se revoco y que se locuta todo. El
    archivo en disco dice `voz.resumir: true`. Manda el archivo.
    """
    largo = "Primera frase. " + ("Otra frase mas larga que la anterior. " * 40)

    entera = para_un_oido(largo, limite=None)
    assert not entera.recortado
    assert len(entera.hablado) > 1000

    cortada = para_un_oido(largo, limite=LIMITE_HABLADO)
    assert cortada.recortado
    assert len(cortada.hablado) <= LIMITE_HABLADO
    assert len(cortada.hablado) < len(entera.hablado) / 4, (
        "el resumen ya no recorta: el preambulo del modo resumido miente")


@pytest.mark.parametrize("idioma", sorted(PREAMBULO_IDIOMAS))
def test_cada_modo_dice_lo_suyo_y_solo_lo_suyo(idioma):
    """Decirle el canal que NO es deja al modelo optimizando contra un
    canal que no tiene, y eso no da ningun error: la respuesta suena."""
    resumido = preambulo(idioma, resumido=True)
    entero = preambulo(idioma, resumido=False)
    assert resumido != entero

    marca_de_corte = {"es": "no se oye nunca", "en": "never heard"}[idioma]
    marca_de_entero = {"es": "ENTERA", "en": "IN FULL"}[idioma]
    assert marca_de_corte in resumido and marca_de_corte not in entero
    assert marca_de_entero in entero and marca_de_entero not in resumido


def test_todo_se_ve_ademas_en_la_consola():
    """"Todo lo que escribes se ve ademas en una consola en pantalla"."""
    fin = Fin(session_id="s", subtipo="success", es_error=False,
              texto=CON_CODIGO, coste_usd=0.0, duracion_ms=1,
              num_turnos=1)
    cuerpo = a_json(fin)
    assert "UMBRAL_SIN_SENAL" in cuerpo["texto"], (
        "la consola ya no recibe el texto entero: el preambulo miente")


# --- lo que el preambulo NO puede hacer -------------------------------

PALABRAS_DE_AUTORIDAD = (
    "permiso", "permisos", "autoriza", "autorizar", "aprobar", "aprobacion",
    "puerta", "denegar", "prohibido", "sudo",
    "permission", "approve", "approval", "denied", "allowed to run",
)


@pytest.mark.parametrize("idioma", sorted(PREAMBULO_IDIOMAS))
def test_no_le_da_autoridad_ni_le_habla_de_la_puerta(idioma):
    """No describe permisos, y ni nombra la puerta.

    Un preambulo que explicase la lista endurecida de JC-0001 le estaria
    enseñando al modelo por donde no pasa. Quien decide es la puerta, no
    lo que el modelo crea.
    """
    texto = preambulo(idioma).lower()
    for palabra in PALABRAS_DE_AUTORIDAD:
        assert palabra not in texto, f"el preambulo habla de {palabra!r}"


@pytest.mark.parametrize("idioma", sorted(PREAMBULO_IDIOMAS))
def test_dice_en_que_idioma_contestar(idioma):
    """Sin esto, una voz inglesa puede acabar recitando español (JC-0018)."""
    esperado = {"es": "Contesta en español", "en": "Answer in English"}
    assert esperado[idioma] in preambulo(idioma)


def test_sigue_al_idioma_hablado_y_no_al_de_la_pantalla(monkeypatch):
    """`voz.idioma`, no `ui.idioma`: quien lo recita es la voz de Piper."""
    import voz.idioma as idioma_mod

    monkeypatch.setattr(idioma_mod, "hablado", lambda config_dir=None: "en")
    assert "Answer in English" in preambulo()


# --- el cableado ------------------------------------------------------

def test_la_sesion_lo_pasa_por_la_linea_de_ordenes():
    orden = Sesion("C:\\", preambulo="ESTO ES EL PREAMBULO").orden
    assert "--append-system-prompt" in orden
    i = orden.index("--append-system-prompt")
    assert orden[i + 1] == "ESTO ES EL PREAMBULO"


def test_sin_preambulo_no_aparece_el_flag():
    """`None` es la sesion sin voz, y no puede colar un flag vacio."""
    orden = Sesion("C:\\").orden
    assert "--append-system-prompt" not in orden


def test_el_preambulo_va_antes_del_suelo():
    """El suelo de JC-0007 y lo que se pase a mano quedan detras.

    Misma razon que la del comentario de `orden`: lo que se anade a mano
    tiene que verse DESPUES en la linea, no tapando lo de la casa.
    """
    orden = Sesion("C:\\", preambulo="P", ajustes="suelo.json",
                   extra=("--add-dir", "C:/otra")).orden
    assert (orden.index("--append-system-prompt")
            < orden.index("--settings") < orden.index("--add-dir"))


# --- quien decide que haya preambulo ----------------------------------

class TestLoDecideElLanzador:
    """Solo `puente/__main__.py` sabe si hay altavoz, asi que solo el
    puede componerlo. Es el mismo reparto que el de `modo_permisos`
    (JC-0017): el modulo lo guarda y lo usa, no lo decide."""

    def _arrancar(self, tmp_path, monkeypatch, argv):
        """Corre `main()` hasta justo despues de construir la sesion.

        Se corta en la Consola y no antes: la sesion ya esta construida
        ahi, y lo que viene detras -- Telegram, la voz, el servidor --
        toca la red y la tarjeta de sonido.
        """
        import puente.__main__ as lanzador
        from puente.suelo import EstadoSuelo, QuienTieneElPuerto, Suelo

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
        monkeypatch.setattr("sys.argv", ["puente", str(tmp_path)] + argv)
        with pytest.raises(KeyboardInterrupt):
            lanzador.main()
        return visto

    def test_con_voz_lo_lleva(self, tmp_path, monkeypatch):
        visto = self._arrancar(tmp_path, monkeypatch, ["--voz"])
        assert visto["preambulo"], "con altavoz y sin preambulo"
        assert "altavoz" in visto["preambulo"]

    def test_sin_voz_no_lo_lleva(self, tmp_path, monkeypatch):
        """>>> LA MITAD QUE IMPORTA <<<

        Sin `--voz` nadie va a oir nada: decirle al modelo que le leen en
        alto seria mentirle, y encima le pediria prosa corta a cambio de
        tablas -- o sea que empeoraria la consola, que sin voz es la
        UNICA salida que hay.
        """
        # Solo `voz.encendida`: el resto sigue leyendose de verdad. Un
        # doble que conteste a TODAS las claves apaga de paso el auto
        # mode y el suelo, y entonces el test mide el doble.
        import nucleo.ajustes as ajustes_mod

        de_verdad = ajustes_mod.valor_de
        monkeypatch.setattr(
            ajustes_mod, "valor_de",
            lambda clave, *a, **k: (False if clave == "voz.encendida"
                                    else de_verdad(clave, *a, **k)))
        visto = self._arrancar(tmp_path, monkeypatch, [])
        assert visto["preambulo"] is None

    def test_se_puede_apagar_para_medir(self, tmp_path, monkeypatch):
        """Sin interruptor no hay A/B, y sin A/B esto no se puede leer."""
        visto = self._arrancar(tmp_path, monkeypatch,
                               ["--voz", "--sin-preambulo"])
        assert visto["preambulo"] is None

    def _con_resumir(self, monkeypatch, encendido):
        import nucleo.ajustes as ajustes_mod

        de_verdad = ajustes_mod.valor_de
        monkeypatch.setattr(
            ajustes_mod, "valor_de",
            lambda clave, *a, **k: (encendido if clave == "voz.resumir"
                                    else de_verdad(clave, *a, **k)))

    def test_el_preambulo_y_el_tts_no_pueden_discrepar(self, tmp_path,
                                                       monkeypatch):
        """>>> EL FALLO QUE ESTO IMPIDE NO DEJA NI UN RASTRO <<<

        Si el preambulo dice "se locuta entera" mientras el TTS corta a
        240 caracteres, el modelo escribe una respuesta larga confiando en
        que se oiga toda y el usuario oye la primera cuarta parte. No hay
        error, no hay log, y la respuesta suena perfectamente bien: solo
        esta incompleta. Por eso `resumido` sale del MISMO `resumir` que
        recibe el bucle de voz y no de una segunda lectura del ajuste.
        """
        self._con_resumir(monkeypatch, True)
        visto = self._arrancar(tmp_path, monkeypatch, ["--voz"])
        assert "no se oye nunca" in visto["preambulo"]

        self._con_resumir(monkeypatch, False)
        visto = self._arrancar(tmp_path, monkeypatch, ["--voz"])
        assert "ENTERA" in visto["preambulo"]

    def test_la_linea_de_ordenes_gana_al_panel(self, tmp_path, monkeypatch):
        """`--resumir` a mano con el ajuste apagado: manda la linea."""
        self._con_resumir(monkeypatch, False)
        visto = self._arrancar(tmp_path, monkeypatch, ["--voz", "--resumir"])
        assert "no se oye nunca" in visto["preambulo"]
