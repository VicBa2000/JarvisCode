"""El POV: que se pueda ver trabajar, y que no enseñe lo que no paso.

>>> LO PIDIO EL USUARIO (2026-09-02) <<<
Lo que pidio es ver el POV de Claude, como una pelicula en primera
persona para que se sienta vivo, al estilo del Jarvis de Iron Man: verle
el trabajo en vivo, no solo lo que acaba saliendo por la consola.

>>> Y LA MITAD DE ESTOS TESTS SON SOBRE LO QUE NO SE PUEDE ENSEÑAR <<<
Porque esa es la parte que se rompe sola con el tiempo. Un POV invita a
animar cosas, y aqui hay exactamente dos que NO se pueden animar sin
mentir, las dos medidas contra el binario
(`-m eval.sondas_claude_code.sonda_pov`):

  * la salida de una herramienta llega en UN trozo -- un `Read` de 1400
    caracteres, 0,02 s --, asi que "verle leer" no existe;
  * el contenido de un `Write` viaja ANTES de la puerta, asi que un
    documento denegado se habra visto escribirse ENTERO.

Los tests van contra `logs/sondas/pov.jsonl`, que es una captura de
`claude` de verdad. Si esa traza no esta, se saltan: un test
que se inventa la entrada mide el test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from puente.camara import Camara, valor_parcial
from puente.protocolo import (Fin, ResultadoHerramienta, Trozo, UsoHerramienta,
                              interpretar)

TRAZA = Path(__file__).resolve().parent.parent / "logs" / "sondas" / "pov.jsonl"


def reproducir(hasta=None):
    """Pasa la traza real por la camara y devuelve lo que salio."""
    if not TRAZA.is_file():
        pytest.skip(f"sin {TRAZA.name}: correr -m eval.sondas_claude_code.sonda_pov")
    camara = Camara()
    salidas = []
    for linea in TRAZA.read_text(encoding="utf-8").splitlines():
        for evento in interpretar(linea):
            cambio = camara.ve(evento)
            if cambio is not None:
                salidas.append(cambio)
            if hasta is not None and hasta(camara):
                return camara, salidas
    return camara, salidas


# --- lo que SI se puede enseñar ---------------------------------------

def test_un_documento_se_ve_ESCRIBIRSE_y_no_aparece_de_golpe() -> None:
    """El corazon de todo esto. Medido antes de construirlo: 17 trozos,
    1468 caracteres, 6,88 s. Si algun dia esto se convierte en un solo
    plano con el texto entero, el visor deja de ser un visor."""
    _, salidas = reproducir()
    cuadros = [s for s in salidas if s["clase"] == "Cuadro"]
    assert len(cuadros) >= 10, (
        f"solo {len(cuadros)} crecimientos: el documento estaria "
        f"apareciendo de golpe")
    # El PRIMER plano de cada id, no el ultimo: lo que se comprueba es
    # que nace vacio y se llena con los cuadros.
    primeros: dict[int, dict] = {}
    for s in salidas:
        if s["clase"] == "Plano":
            primeros.setdefault(s["id"], s)
    escritos = [p for p in primeros.values() if p["que"] == "escribiendo"]
    assert escritos, "no se reconocio ningun `Write` como escritura"
    assert len(escritos[0]["texto"]) == 0, (
        "el plano nace VACIO y se llena con los cuadros; si nace lleno, "
        "es que el texto no viajo troceado")


def test_lo_que_se_ve_es_el_DOCUMENTO_y_no_el_json_de_la_herramienta() -> None:
    """Lo que llega es `{"file_path": "...", "content": "El mar resp` --
    o sea el JSON de la entrada construyendose. Enseñar eso tal cual
    seria enseñar tuberia."""
    camara, _ = reproducir(
        hasta=lambda c: c.plano is not None and len(c.plano.texto) > 300)
    texto = camara.plano.texto
    assert "file_path" not in texto
    assert not texto.lstrip().startswith("{")
    assert "\\n" not in texto, "los saltos de linea siguen escapados"


def test_el_asunto_es_el_NOMBRE_del_archivo_y_no_la_ruta() -> None:
    camara, _ = reproducir(
        hasta=lambda c: c.plano is not None and c.plano.sobre != "")
    assert camara.plano.sobre == "notas.md"
    assert "/" not in camara.plano.sobre and "\\" not in camara.plano.sobre


def test_el_rotulo_NO_parpadea_con_el_nombre_de_una_CARPETA() -> None:
    """>>> LO DESTAPO UN TURNO DE VERDAD, NO UN TEST <<<

    La ruta tambien viaja a trozos. A mitad de camino vale
    `C:/Users/.../pov_e2e_toi3muo2/`, y quedarse con el ultimo pedazo de
    eso da el nombre de la CARPETA: el rotulo enseño "escribiendo
    pov_e2e_toi3muo2" antes de enseñar "escribiendo saludo.md". No es
    feo, es FALSO -- durante ese rato dice que escribe algo que no
    existe. Es la regla de las tres salidas: "todavia esta llegando" no
    es "esto es el nombre".
    """
    from puente.protocolo import AbreBloque, AbreMensaje

    camara = Camara()
    camara.ve(AbreMensaje())
    camara.ve(AbreBloque(indice=0, clase="tool_use", herramienta="Write"))
    vistos = []
    for trozo in ['{"file_path": "C', ':/Users/alguien/',
                  'pov_e2e_toi3muo2/', 'saludo.md',
                  '", "content": "El mar']:
        camara.ve(Trozo(indice=0, clase="input_json_delta", texto=trozo))
        vistos.append(camara.plano.sobre)

    assert "pov_e2e_toi3muo2" not in vistos, (
        "el rotulo enseño el nombre de la carpeta mientras llegaba la ruta")
    assert vistos[-1] == "saludo.md"
    assert vistos.count("") == 4, (
        "hasta que la ruta no esta entera, no hay nombre que enseñar")


def test_la_camara_VUELVE_sobre_lo_que_aterriza() -> None:
    """>>> LO DESTAPO LA TRAZA REAL, NO UN TEST <<<

    Un mensaje puede pedir dos herramientas de golpe, y entonces los dos
    planos se crean seguidos ANTES de que vuelva ninguna. Sin volver, la
    salida de la primera no se enseña NUNCA: se midio contra esta misma
    traza y el `dir` se quedaba con su linea de ordenes y sus 370
    caracteres de salida no aparecian.
    """
    _, salidas = reproducir()
    ids = [s["id"] for s in salidas if s["clase"] == "Plano"]
    # Vuelve: hay un id que reaparece despues de que saliera otro mayor.
    volvio = any(ids[i] < max(ids[:i]) for i in range(1, len(ids)))
    assert volvio, "la camara nunca vuelve: lo que aterriza tarde se pierde"

    ultimos = {}
    for s in salidas:
        if s["clase"] == "Plano":
            ultimos[s["id"]] = s
    ejecutados = [p for p in ultimos.values() if p["que"] == "ejecutando"]
    assert ejecutados and len(ejecutados[0]["texto"]) > 100, (
        "la salida de la orden no llego al plano")


# --- lo que NO se puede enseñar, y es la mitad importante --------------

def test_lo_que_LLEGA_DE_GOLPE_se_marca_como_tal() -> None:
    """>>> AQUI VIVE EL "NADA DE MOCKS" DE ESTE MODULO <<<

    Un `Read` de 1400 caracteres llega en un trozo y la herramienta tarda
    0,02 s. La pagina NO puede pintarlo apareciendo poco a poco, porque
    eso no ocurrio. `aterrizo` es lo que se lo impide, y por eso viaja
    hasta el navegador en vez de deducirse alli.
    """
    _, salidas = reproducir()
    ultimos = {}
    for s in salidas:
        if s["clase"] == "Plano":
            ultimos[s["id"]] = s
    leidos = [p for p in ultimos.values() if p["que"] == "leyendo"]
    assert leidos, "no se reconocio ninguna lectura"
    assert leidos[0]["aterrizo"] is True
    assert len(leidos[0]["texto"]) > 500, "el contenido leido no llego"

    escritos = [p for p in ultimos.values() if p["que"] == "escribiendo"]
    assert escritos[0]["aterrizo"] is False, (
        "un documento que se vio escribirse no puede decir que aterrizo")


def test_un_WRITE_DENEGADO_lo_DICE_en_vez_de_desaparecer(tmp_path) -> None:
    """>>> EL CONTENIDO VIAJA ANTES DE LA PUERTA <<<

    O sea que para cuando el usuario dice que no, el documento entero ya
    se vio escribirse. Borrarlo de la pantalla sin mas dejaria en la
    cabeza de quien miraba un archivo que no existe -- y la tira no lo
    contradice, porque un `Write` denegado nunca entra en ella.
    Es la razon por la que el POV y la tira son dos superficies.
    """
    camara = Camara()
    from puente.protocolo import AbreBloque, AbreMensaje, CierraBloque

    camara.ve(AbreMensaje())
    camara.ve(AbreBloque(indice=0, clase="tool_use", herramienta="Write"))
    camara.ve(Trozo(indice=0, clase="input_json_delta",
                    texto='{"file_path": "C:/x/secreto.md", "content": "hola'))
    camara.ve(CierraBloque(indice=0))
    camara.ve(UsoHerramienta(id_uso="u1", herramienta="Write",
                             entrada={"file_path": "C:/x/secreto.md",
                                      "content": "hola"}))
    assert camara.plano.texto == "hola"
    assert camara.plano.negado is False

    final = camara.ve(ResultadoHerramienta(
        id_uso="u1", contenido="El usuario dijo que no.", es_error=True))
    assert final is not None and final["negado"] is True
    assert final["texto"] == "hola", (
        "lo que se vio escribir se queda: taparlo seria borrar la prueba "
        "de que se enseño algo que no paso")


def test_al_cerrar_el_turno_el_ultimo_plano_se_queda_EN_PAUSA() -> None:
    """Irse a negro borraria lo ultimo que hizo justo cuando lo vas a
    mirar. Se queda, y deja de decir que esta vivo."""
    camara, _ = reproducir()
    assert camara.plano is not None
    assert camara.plano.vivo is False
    assert camara.plano.parcial is False


# --- el extractor, que es la pieza fina -------------------------------

class TestValorParcial:
    """Sacar un texto de un JSON que TODAVIA NO ESTA ENTERO.

    Tres salidas y no dos: la clave no ha llegado, ha llegado a
    medias, o esta entera. Colapsar "a medias" contra "no hay" dejaria el
    visor en blanco durante los siete segundos que dura escribirse un
    documento, que es justo lo que se venia a enseñar.
    """

    def test_entero(self) -> None:
        assert valor_parcial('{"content": "hola"}', "content") == ("hola", True)

    def test_a_medias_devuelve_LO_QUE_HAY(self) -> None:
        valor, completo = valor_parcial('{"content": "el mar resp', "content")
        assert valor == "el mar resp"
        assert completo is False

    def test_la_clave_todavia_no_llego(self) -> None:
        assert valor_parcial('{"file_path": "a.md", "cont', "content") == ("", False)

    def test_los_saltos_de_linea_se_deshacen(self) -> None:
        valor, _ = valor_parcial(r'{"content": "uno\ndos\ttres"}', "content")
        assert valor == "uno\ndos\ttres"

    def test_una_barra_a_medias_NO_se_pinta(self) -> None:
        """Si el trozo corta justo en un escape, pintar la barra suelta
        enseñaria basura durante 200 ms. En un visor eso se ve."""
        valor, _ = valor_parcial('{"content": "linea\\', "content")
        assert valor == "linea"

    def test_un_unicode_a_medias_tampoco(self) -> None:
        valor, _ = valor_parcial(r'{"content": "caf\u00', "content")
        assert valor == "caf"
        entero, _ = valor_parcial(r'{"content": "caf\u00e9', "content")
        assert entero == "café"

    def test_una_comilla_escapada_no_cierra_el_valor(self) -> None:
        valor, completo = valor_parcial(r'{"content": "dijo \"hola\" y', "content")
        assert valor == 'dijo "hola" y'
        assert completo is False

    def test_un_valor_que_no_es_texto_no_es_un_plano(self) -> None:
        """`{"limit": 100}` no tiene nada que enseñar, y buscando la
        siguiente comilla a lo bruto se cogeria la clave de al lado."""
        assert valor_parcial('{"limit": 100, "path": "a.md"}', "limit") == ("", False)

    def test_una_clave_que_no_esta(self) -> None:
        assert valor_parcial('{"a": "b"}', "content") == ("", False)


# --- y lo que separa esto de la tira ----------------------------------

def test_el_POV_no_guarda_NADA_del_pasado() -> None:
    """La tira es la pelicula y esto es la camara. Si la camara empezara
    a acumular, serian dos listas del mismo turno diciendo cosas
    distintas -- y una de las dos con piezas que no existen."""
    camara, _ = reproducir()
    assert not hasattr(camara, "piezas")
    assert not hasattr(camara, "planos")
    # Un solo plano vivo, y punto.
    assert isinstance(camara.a_json(), dict)


def test_un_turno_nuevo_no_arrastra_bloques_del_anterior() -> None:
    """`Fin` limpia. Sin eso, un indice de bloque del turno pasado casaria
    con uno del nuevo y el visor pegaria dos textos que no van juntos."""
    from puente.protocolo import AbreBloque, AbreMensaje

    camara = Camara()
    camara.ve(AbreMensaje())
    camara.ve(AbreBloque(indice=0, clase="text"))
    camara.ve(Trozo(indice=0, clase="text_delta", texto="del turno viejo"))
    camara.ve(Fin(session_id="s", subtipo="success", es_error=False,
                  texto="", coste_usd=0.0, duracion_ms=1, num_turnos=1))
    assert camara._bloques == {}
    # Y un trozo rezagado de aquel bloque ya no pega nada.
    assert camara.ve(Trozo(indice=0, clase="text_delta", texto="rezagado")) is None
