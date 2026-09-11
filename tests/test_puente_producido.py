"""Lo que Jarvis deja detras, y por que cada regla de aqui existe.

El agujero, dicho por el usuario el 2026-09-01: si le pide crear un
documento que resuma el proyecto lo hace y sale perfecto, pero si no le
pide EXPLICITAMENTE que lo abra, no lo ve nunca.

Y el hallazgo que le dio forma: `protocolo._texto_de` se quedaba SOLO con
los bloques `text`, asi que un bloque `image` de un resultado de
herramienta se tiraba ahi mismo y en silencio. Con el MCP de Blender eso
significa que la captura del viewport llegaba hasta nuestra puerta y la
echabamos a la basura: **Claude la veia y el usuario no**.
"""

from __future__ import annotations

import base64

import pytest

from puente.producido import (CLASE_ARCHIVO, CLASE_HUECO, CLASE_IMAGEN,
                              Producido)
from puente.protocolo import (Fin, Imagen, ResultadoHerramienta,
                              UsoHerramienta, interpretar)

PNG = base64.b64encode(b"no es un png pero son bytes").decode()


def uso(id_uso: str, ruta: str, herramienta: str = "Write") -> UsoHerramienta:
    clave = "notebook_path" if herramienta == "NotebookEdit" else "file_path"
    return UsoHerramienta(id_uso=id_uso, herramienta=herramienta,
                          entrada={clave: ruta})


def resultado(id_uso: str, mal: bool = False,
              imagenes: tuple = ()) -> ResultadoHerramienta:
    return ResultadoHerramienta(id_uso=id_uso, contenido="",
                                es_error=mal, imagenes=imagenes)


# --- el protocolo dejo de tirar imagenes ------------------------------

def test_una_imagen_de_una_herramienta_ya_no_se_tira() -> None:
    """>>> ESTE ES EL AGUJERO, Y ES DE UNA LINEA <<<

    `_texto_de` filtraba por `type == "text"`. Todo lo demas desaparecia
    sin dejar rastro: ni un contador, ni una linea en el log distinta.
    """
    crudo = ('{"type":"user","message":{"content":[{"type":"tool_result",'
             '"tool_use_id":"u1","content":['
             '{"type":"text","text":"hecho"},'
             '{"type":"image","source":{"type":"base64",'
             '"media_type":"image/png","data":"' + PNG + '"}}]}]}}')
    evento, = interpretar(crudo)
    assert evento.contenido == "hecho"
    assert len(evento.imagenes) == 1
    assert evento.imagenes[0].tipo == "image/png"


def test_una_imagen_por_URL_no_se_trata_como_base64() -> None:
    """Existe en el protocolo y no es lo mismo. Decodificarla pintaria
    basura, asi que se ignora en vez de adivinarse."""
    crudo = ('{"type":"user","message":{"content":[{"type":"tool_result",'
             '"tool_use_id":"u1","content":[{"type":"image",'
             '"source":{"type":"url","url":"http://x/y.png"}}]}]}}')
    evento, = interpretar(crudo)
    assert evento.imagenes == ()


# --- lo que cuenta como producido -------------------------------------

def test_un_write_DENEGADO_no_es_una_pieza(tmp_path) -> None:
    """>>> LA REGLA QUE MAS IMPORTA DE ESTE MODULO <<<

    `UsoHerramienta` llega ANTES de ejecutar y puede acabar en la puerta
    y en un `no`. Apuntar ahi listaria como "producido" un archivo que no
    existe, y el usuario lo descubriria pinchandolo -- justo en la
    pantalla que se hizo para que dejara de tener que buscar las cosas.
    """
    p = Producido()
    p.ve(uso("u1", str(tmp_path / "denegado.md")))
    p.ve(resultado("u1", mal=True))
    assert p.piezas == ()


def test_un_write_que_sale_bien_SI_lo_es(tmp_path) -> None:
    doc = tmp_path / "resumen.md"
    doc.write_text("# hola", encoding="utf-8")
    p = Producido()
    p.ve(uso("u1", str(doc)))
    p.ve(resultado("u1"))
    pieza, = p.piezas
    assert pieza.clase == CLASE_ARCHIVO
    assert pieza.nombre == "resumen.md"
    assert pieza.a_json()["existe"] is True


def test_una_shell_no_declara_piezas(tmp_path) -> None:
    """`Bash` y `PowerShell` estan fuera a proposito.

    Pueden crear archivos y no hay forma honesta de saber cuales sin
    adivinar la linea de ordenes -- que es exactamente lo que ya costo
    dos tandas de puertas equivocadas (el `2>&1` del 27 y el acento
    grave del 29). Mejor no ensenar nada que ensenar lo que no es.
    """
    p = Producido()
    p.ve(UsoHerramienta(id_uso="u1", herramienta="Bash",
                        entrada={"command": f"echo hola > {tmp_path}/x.txt"}))
    p.ve(resultado("u1"))
    assert p.piezas == ()


def test_el_mismo_archivo_tres_veces_es_UNA_pieza(tmp_path) -> None:
    """Lo que interesa ver es el archivo, no cuantas pasadas hizo."""
    doc = tmp_path / "a.md"
    doc.write_text("x", encoding="utf-8")
    p = Producido()
    for i in range(3):
        p.ve(uso(f"u{i}", str(doc), herramienta="Edit"))
        p.ve(resultado(f"u{i}"))
    assert len(p.piezas) == 1


def test_las_imagenes_entran_aunque_no_haya_archivo() -> None:
    """El caso de Blender: la herramienta no escribe nada, devuelve una
    imagen."""
    p = Producido()
    p.ve(resultado("u1", imagenes=(Imagen(tipo="image/png", datos=PNG),)))
    pieza, = p.piezas
    assert pieza.clase == CLASE_IMAGEN
    assert pieza.datos == base64.b64decode(PNG)


# --- servir, que es donde esta el riesgo ------------------------------

def test_se_sirve_POR_ID_y_un_id_inventado_no_da_nada(tmp_path) -> None:
    doc = tmp_path / "a.md"
    doc.write_text("secreto", encoding="utf-8")
    p = Producido()
    p.ve(uso("u1", str(doc)))
    p.ve(resultado("u1"))
    pieza, = p.piezas
    assert p.contenido_de(pieza.id)[0] == b"secreto"
    assert p.contenido_de("no-existe") is None


def test_no_hay_forma_de_pedir_una_ruta(tmp_path) -> None:
    """>>> Y NO PUEDE HABERLA <<<

    Una ruta convertiria `127.0.0.1` en un lector del disco entero para
    cualquier cosa que corra en esta PC. El suelo de JC-0007 no lo
    taparia: aquel gobierna a Claude Code, no a nuestro servidor.
    Si algun dia alguien anade ese parametro, este test es el sitio donde
    se discute.
    """
    p = Producido()
    with pytest.raises(TypeError):
        p.contenido_de(ruta=str(tmp_path / "a.md"))   # type: ignore[call-arg]


def test_el_json_de_una_pieza_NO_lleva_los_bytes() -> None:
    """Va al estado, que se pide cada pocos segundos y a cada pestana."""
    p = Producido()
    p.ve(resultado("u1", imagenes=(Imagen(tipo="image/png", datos=PNG),)))
    import json

    texto = json.dumps(p.a_json())
    assert PNG not in texto
    assert "bytes" in texto


def test_el_evento_que_va_a_la_pagina_solo_dice_CUANTAS() -> None:
    """`consola.a_json` hace `asdict`, y eso se llevaria el base64 entero
    a cada cliente conectado por SSE."""
    from puente.consola import a_json

    gordo = base64.b64encode(b"x" * 90_000).decode()
    cuerpo = a_json(resultado("u1", imagenes=(
        Imagen(tipo="image/png", datos=gordo),)))
    assert cuerpo["imagenes"] == 1
    assert len(json_de(cuerpo)) < 1000


def json_de(cuerpo) -> str:
    import json

    return json.dumps(cuerpo)


# --- topes, porque esto corre todo el dia -----------------------------

def test_las_imagenes_viejas_sueltan_sus_bytes_al_llegar_al_tope() -> None:
    p = Producido(tope_imagenes=100)
    for i in range(6):
        datos = base64.b64encode(b"y" * 40).decode()
        p.ve(resultado(f"u{i}", imagenes=(Imagen(tipo="image/png",
                                                 datos=datos),)))
    guardado = sum(len(x.datos) for x in p.piezas if x.datos)
    assert guardado <= 100
    assert any(x.clase == CLASE_HUECO for x in p.piezas), "no se solto ninguna"


def test_una_imagen_SOLTADA_deja_lapida_y_no_un_agujero() -> None:
    """>>> PUNTO 3 DE LA v3, Y ES UNA REGLA DE HONESTIDAD <<<

    Hasta la v2 la pieza desaparecia de la lista, y en una lista eso no
    se notaba. La v3 es una TIRA que cuenta una secuencia: un salto sin
    avisar dice que ese trabajo nunca ocurrio. La lapida conserva el
    sitio, el nombre y el turno, y pierde solo lo que de verdad se
    solto -- los bytes.
    """
    p = Producido(tope_imagenes=100)
    for i in range(4):
        datos = base64.b64encode(b"y" * 40).decode()
        p.ve(resultado(f"u{i}", imagenes=(Imagen(tipo="image/png",
                                                 datos=datos),)))

    assert len(p.piezas) == 4, "la secuencia no puede encoger"
    # `piezas` viene del reves: lo mas nuevo primero.
    clases = [x.clase for x in reversed(p.piezas)]
    assert clases == [CLASE_HUECO, CLASE_HUECO, CLASE_IMAGEN, CLASE_IMAGEN], (
        "se sueltan las mas VIEJAS, y en su sitio")
    lapida = [x for x in p.piezas if x.clase == CLASE_HUECO][0]
    assert lapida.nombre and lapida.datos is None
    assert not lapida.se_pinta_en_linea
    assert lapida.a_json()["bytes"] == 0


def test_una_lapida_no_sirve_contenido(tmp_path) -> None:
    """Su id sigue siendo un id de esta sesion, y aun asi no hay nada
    detras. Pedirlo tiene que dar `None` y no reventar."""
    p = Producido(tope_imagenes=1)
    p.ve(resultado("u1", imagenes=(Imagen(tipo="image/png",
                                          datos=base64.b64encode(b"y" * 40).decode()),)))
    p.ve(resultado("u2", imagenes=(Imagen(tipo="image/png",
                                          datos=base64.b64encode(b"z" * 40).decode()),)))
    lapida = [x for x in p.piezas if x.clase == CLASE_HUECO][0]
    assert p.por_id(lapida.id) is lapida
    assert p.contenido_de(lapida.id) is None


def test_lo_que_se_cae_por_el_OTRO_tope_se_cuenta(tmp_path) -> None:
    """Esas se van por el extremo viejo, donde una lapida por cada una
    llenaria la tira de losas. Ahi basta un "+N antes" -- pero tiene que
    HABERLO: la tira no puede empezar en medio sin decirlo."""
    p = Producido(tope=3)
    for i in range(6):
        ruta = tmp_path / f"a{i}.md"
        ruta.write_text("x", encoding="utf-8")
        p.ve(uso(f"u{i}", str(ruta)))
        p.ve(resultado(f"u{i}"))
    assert len(p.piezas) == 3
    assert p.olvidadas == 3
    assert p.a_json()["olvidadas"] == 3


# --- el vistazo de la tira --------------------------------------------

def test_el_vistazo_recorta_y_NO_puede_ampliar(tmp_path) -> None:
    """La miniatura de un documento son cuatro renglones. Traerse 512 KB
    para pintarlos seria pagar el archivo entero por una miniatura -- y
    al reves, un `vistazo` enorme no puede servir para pedir mas de lo
    que el tope de siempre deja salir."""
    from puente.producido import TOPE_VISTA_BYTES

    ruta = tmp_path / "largo.md"
    ruta.write_text("a" * (TOPE_VISTA_BYTES + 5000), encoding="utf-8")
    p = Producido()
    p.ve(uso("u1", str(ruta)))
    p.ve(resultado("u1"))
    ident = p.piezas[0].id

    datos, _ = p.contenido_de(ident, tope=64)
    assert len(datos) == 64
    enorme, _ = p.contenido_de(ident, tope=TOPE_VISTA_BYTES * 4)
    assert len(enorme) == TOPE_VISTA_BYTES
    entero, _ = p.contenido_de(ident)
    assert len(entero) == TOPE_VISTA_BYTES


def test_una_imagen_NO_se_recorta_por_el_vistazo() -> None:
    """Media imagen no es una miniatura: son bytes rotos. La tira las
    encoge con CSS, que es gratis."""
    p = Producido()
    p.ve(resultado("u1", imagenes=(Imagen(tipo="image/png", datos=PNG),)))
    datos, _ = p.contenido_de(p.piezas[0].id, tope=4)
    assert datos == base64.b64decode(PNG)


def test_un_Fin_cierra_el_turno_y_olvida_lo_que_quedo_a_medias(tmp_path) -> None:
    """Un uso sin su resultado no puede quedarse esperando para siempre:
    si el turno se paro, ese `Write` no va a llegar nunca."""
    p = Producido()
    p.ve(uso("u1", str(tmp_path / "a.md")))
    p.ve(Fin(session_id="s", subtipo="success", es_error=False, texto="",
             coste_usd=0.0, duracion_ms=1, num_turnos=1))
    p.ve(resultado("u1"))
    assert p.piezas == ()
    assert p.turno == 1


# --- abrir fuera, que LANZA UN PROGRAMA -------------------------------

class TestAbrirFuera:
    """`os.startfile` ejecuta. Por eso acepta un id y nunca una ruta."""

    def _consola(self, tmp_path):
        from puente.consola import Consola

        class SesionFalsa:
            directorio = str(tmp_path)
            viva = False
        c = Consola.__new__(Consola)
        c.producido = Producido()
        c.sesion = SesionFalsa()
        return c

    def test_un_id_que_no_es_de_esta_sesion_no_abre_nada(self, tmp_path):
        c = self._consola(tmp_path)
        r = c.abrir_pieza("inventado")
        assert r["ok"] is False
        assert "esta sesion" in r["motivo"]

    def test_una_pieza_cuyo_archivo_ya_no_esta_lo_DICE(self, tmp_path):
        """Tercera respuesta de verdad: la pieza existe y el archivo no.
        Pasa a menudo -- un temporal que la propia sesion borro."""
        doc = tmp_path / "efimero.txt"
        doc.write_text("x", encoding="utf-8")
        c = self._consola(tmp_path)
        c.producido.ve(uso("u1", str(doc)))
        c.producido.ve(resultado("u1"))
        doc.unlink()
        r = c.abrir_pieza(c.producido.piezas[0].id)
        assert r["ok"] is False
        assert "disco" in r["motivo"]

    def test_una_imagen_no_se_abre_fuera(self, tmp_path):
        """Vive en memoria. Escribir un temporal para poder lanzarlo
        seria inventar un archivo que el usuario no pidio."""
        c = self._consola(tmp_path)
        c.producido.ve(resultado("u1", imagenes=(
            Imagen(tipo="image/png", datos=PNG),)))
        r = c.abrir_pieza(c.producido.piezas[0].id)
        assert r["ok"] is False


class TestPararDesdeLaConsola:
    """La tecla Esc, pedida por el usuario el 2026-09-01: que al pulsarla
    en la consola corte de una, igual que ya hace el Claude Code nativo.

    Hasta ese dia la consola **no tenia ninguna forma de parar un turno**:
    ni tecla ni boton. Solo la voz, diciendo "para".
    """

    def _consola(self, voz=None):
        from puente.consola import Consola

        class SesionFalsa:
            def __init__(self):
                self.interrumpida = 0
                self.viva = True
            def interrumpir(self):
                self.interrumpida += 1
                return True
        c = Consola.__new__(Consola)
        c.sesion = SesionFalsa()
        c.voz = voz
        return c

    def test_sin_voz_corta_el_turno(self):
        c = self._consola()
        assert c.parar_el_turno() == {"ok": True, "parado": True, "con_voz": False}
        assert c.sesion.interrumpida == 1

    def test_CON_voz_pasa_por_la_voz_y_no_por_la_sesion(self):
        """>>> LA REGLA QUE ESTO SUJETA, Y COSTO TRES FUGAS <<<

        `sesion.interrumpir` corta el TURNO y nada mas. Parar de verdad es
        ademas callar la frase que ya suena, no decir lo que venia detras
        y vaciar el buzon de narracion (JC-0011, el 2026-08-29). Si la
        consola llamara directo a la sesion, Esc pararia el trabajo y
        Jarvis seguiria recitando la respuesta de algo que ya no existe --
        que es justo lo que el usuario reporto entonces.
        """
        class VozFalsa:
            def __init__(self):
                self.origenes = []
            def parar_el_turno(self, origen="voz"):
                self.origenes.append(origen)
                return True

        voz = VozFalsa()
        c = self._consola(voz)
        assert c.parar_el_turno()["con_voz"] is True
        assert voz.origenes == ["consola"]
        assert c.sesion.interrumpida == 0, (
            "se salto la voz: la frase que suena no se callaria")

    def test_sin_turno_en_marcha_NO_es_un_fallo(self):
        """Tercera respuesta: `ok` sigue siendo True y `parado` es False.

        Pintarlo como error dejaria un aviso rojo cada vez que alguien
        roza Esc en una pantalla quieta.
        """
        c = self._consola()
        c.sesion.interrumpir = lambda: False
        r = c.parar_el_turno()
        assert r["ok"] is True and r["parado"] is False
