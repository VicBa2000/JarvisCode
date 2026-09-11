"""La consola: que sirve, que serializa y que NO interpreta.

Rapidos: levantan el servidor local contra una sesion que ni siquiera se
abre. No hace falta Claude Code para probar el transporte.
"""

from __future__ import annotations

import json
import socket
import urllib.request
from pathlib import Path

import pytest

from puente.consola import PAGINA, Consola, a_json
from puente.protocolo import Fin, Limite, Puerta, Reintento, interpretar
from puente.sesion import Sesion

TRAZAS = Path(__file__).resolve().parent.parent / "eval" / "trazas_claude_code"


def eventos_de(nombre: str) -> list:
    eventos = []
    for linea in (TRAZAS / nombre).read_text(encoding="utf-8").splitlines():
        eventos.extend(interpretar(linea))
    return eventos


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def consola(tmp_path: Path):
    c = Consola(Sesion(tmp_path), puerto=puerto_libre())
    c.servir(abrir_navegador=False)
    yield c
    c.parar()


def pide(consola: Consola, ruta: str, cuerpo: dict | None = None):
    """Una peticion como la que haria la pagina, ficha incluida.

    La ficha se manda SIEMPRE, tambien en los GET: desde el 2026-08-24 la
    consola la exige en todo menos en `/`. Que estos tests tuvieran que
    cambiar es la senal correcta -- si hubieran seguido pasando sin ella,
    es que el cierre no cerraba nada.
    """
    url = f"http://127.0.0.1:{consola.puerto}{ruta}"
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(
        url, data=datos, headers={"X-Jarvis-Ficha": consola.ficha})
    with urllib.request.urlopen(peticion, timeout=10) as r:
        return r.status, r.read()


# --- lo que sirve ----------------------------------------------------------


def test_la_pagina_se_sirve(consola: Consola):
    estado, cuerpo = pide(consola, "/")
    assert estado == 200
    assert b"<!doctype html>" in cuerpo.lower()


def test_el_estado_dice_la_verdad_de_una_sesion_sin_abrir(consola: Consola):
    """>>> ESTE TEST AFIRMABA EL FALLO, Y CON ESE NOMBRE <<<

    (2026-09-09.) Exigia `salud == "caida"` para una sesion que no se
    ha abierto nunca, o sea que la unica prueba que miraba esto daba por
    buena la alarma. Y el puente ARRANCA MUDO a proposito, asi que ese
    es el estado de cada arranque: la pantalla decia "caida" en rojo,
    con un contador subiendo, todos los dias hasta la primera orden.
    Lo encontro arrancar `-m puente` en un clon y MIRAR la consola; no
    lo habria encontrado ningun test, porque el test decia que estaba
    bien."""
    _, cuerpo = pide(consola, "/estado")
    estado = json.loads(cuerpo)
    assert estado["viva"] is False
    assert estado["pendientes"] == []
    assert estado["salud"] == "en_reposo"


def test_reposo_y_caida_NO_son_el_mismo_estado(consola: Consola):
    """Las TRES salidas de "esta viva?", una por una.

    `viva` es False en dos de las tres, que es como se colapsaron. Lo
    que las separa es `_proceso`: `None` si no hay ninguno (nunca se
    abrio, o se cerro a proposito) y un proceso CON codigo de salida si
    se murio. No se toca Claude Code para probarlo: basta un objeto que
    conteste a `poll()`, que es todo lo que se le pregunta."""
    sesion = consola.sesion

    # 1. nunca se abrio
    assert sesion.en_reposo is True
    assert sesion.viva is False
    assert consola._salud(0.0) == "en_reposo"

    class ProcesoPostizo:
        def __init__(self, codigo):
            self._codigo = codigo

        def poll(self):
            return self._codigo

    # 2. corriendo: `poll()` devuelve None porque no ha terminado
    sesion._proceso = ProcesoPostizo(None)
    assert sesion.en_reposo is False
    assert sesion.viva is True
    assert consola._salud(0.0) == "bien"

    # 3. se murio: hay proceso y trae codigo de salida
    sesion._proceso = ProcesoPostizo(1)
    assert sesion.en_reposo is False
    assert sesion.viva is False
    assert consola._salud(0.0) == "caida"

    # Y un cierre DELIBERADO vuelve a reposo, no a caida: cambiar de
    # proyecto cierra la sesion y repunta el directorio, y ahi no se ha
    # roto nada.
    sesion._proceso = None
    assert consola._salud(0.0) == "en_reposo"


def test_la_pagina_sabe_pintar_los_estados_que_manda_el_servidor():
    """Un estado sin etiqueta se pinta como "?" y nadie se entera.

    `ETIQUETAS[s.salud] || ["?", "duda"]` no da error: da un rotulo
    mudo en ambar. Asi que cada salida de `_salud` tiene que estar
    escrita en la pagina, y esto lo comprueba en las dos direcciones."""
    pagina = PAGINA.read_text(encoding="utf-8")
    bloque = pagina.split("const ETIQUETAS = {", 1)[1].split("};", 1)[0]
    en_la_pagina = {
        linea.split(":", 1)[0].strip()
        for linea in bloque.splitlines()
        if ":" in linea and not linea.strip().startswith("//")
    }
    del_servidor = {"bien", "en_reposo", "esperandote", "callada",
                    "sin_servidor", "caida"}
    assert del_servidor <= en_la_pagina, (
        f"la pagina no sabe pintar: {del_servidor - en_la_pagina}")


def test_responder_a_una_peticion_que_no_existe_devuelve_falso(consola: Consola):
    """La carrera entre canales, vista desde el que llega tarde."""
    _, cuerpo = pide(consola, "/responder",
                     {"id_peticion": "no-existe", "permitir": True})
    assert json.loads(cuerpo)["ok"] is False


def test_solo_escucha_en_localhost(consola: Consola):
    """Principio heredado: no se expone ningun puerto a la red."""
    assert consola._servidor is not None
    assert consola._servidor.server_address[0] == "127.0.0.1"


# --- lo que NO hace, que es el punto de seguridad --------------------------


def test_la_pagina_no_interpreta_nada_de_lo_que_llega():
    """La puerta, en el unico sitio donde el usuario cree ver la verdad.

    El texto de la sesion puede venir de la web o de un archivo. Si la
    consola lo metiera con `innerHTML`, una inyeccion se ejecutaria en la
    pantalla donde el usuario aprueba cosas. Este test es tonto y es
    justo por eso: caza el dia que alguien lo escriba por comodidad.
    """
    import re

    fuente = PAGINA.read_text(encoding="utf-8")
    # Se buscan ASIGNACIONES, no la palabra: el comentario que explica
    # por que no se usa `innerHTML` no puede tumbar su propio test.
    assert not re.search(r"\.innerHTML\s*=", fuente)
    assert not re.search(r"\.outerHTML\s*=", fuente)
    assert "insertAdjacentHTML" not in fuente
    assert "document.write" not in fuente
    assert not re.search(r"\beval\s*\(", fuente), (
        "la pagina llama a eval(). Y OJO: esta comprobacion estuvo\n"
        "MUERTA hasta el 2026-08-26 -- el patron llevaba un caracter\n"
        "de retroceso real (0x08) en vez de `\\b`, asi que no casaba\n"
        "con nada. Un guardia que no se dispara nunca."
    )
    assert "textContent" in fuente


# --- lo que serializa ------------------------------------------------------


def test_una_puerta_real_viaja_con_su_crudo_delante():
    puerta = next(e for e in eventos_de("denegada.jsonl")
                  if isinstance(e, Puerta))
    cuerpo = a_json(puerta)
    assert cuerpo["clase"] == "Puerta"
    assert cuerpo["id_peticion"] == puerta.id_peticion
    # Lo que se va a ejecutar, textual, para que las dos formas coincidan.
    assert "rm" in cuerpo["crudo"]
    assert cuerpo["orden_shell"].startswith("rm")


def test_el_limite_viaja_ya_interpretado():
    limite = next(e for e in eventos_de("permitida.jsonl")
                  if isinstance(e, Limite))
    cuerpo = a_json(limite)
    assert cuerpo["porcentaje"] == 86
    assert cuerpo["es_semanal"] is True
    assert cuerpo["agotado"] is False


def test_el_reintento_y_el_fin_fallido_llegan_enteros():
    eventos = eventos_de("sin_conexion.jsonl")
    reintento = a_json(next(e for e in eventos if isinstance(e, Reintento)))
    assert reintento["intento"] == 1
    assert reintento["es_el_ultimo"] is False
    fin = a_json(next(e for e in eventos if isinstance(e, Fin)))
    assert fin["razon_terminal"] == "api_error"
    assert fin["es_error"] is True


def test_una_aprobacion_automatica_serializa(monkeypatch):
    """El hueco por el que se colo un bug de verdad.

    `Resuelta` lleva un `Veredicto`, que es un Enum, y `asdict` no lo
    aplana. Ninguna traza capturada contiene una `Resuelta` -- la produce
    la sesion, no el parser --, asi que los tests contra fixtures no
    podian verlo y solo reventaba con un navegador conectado.
    """
    from puente.politica import decidir
    from puente.sesion import Resuelta

    puerta = next(e for e in eventos_de("permitida.jsonl")
                  if isinstance(e, Puerta) and e.herramienta == "Write")
    decision = decidir(puerta, directorio_sesion=str(
        Path(puerta.entrada["file_path"]).parent))
    cuerpo = a_json(Resuelta(puerta=puerta, decision=decision))
    # Lo que importa: que json.dumps NO explote.
    json.dumps(cuerpo, ensure_ascii=False)
    assert cuerpo["decision"]["veredicto"] == "permitir"
    assert cuerpo["puerta"]["herramienta"] == "Write"


def test_todo_lo_serializado_es_json_de_verdad():
    """Si algo no serializa, el flujo se rompe en vivo y no en un test."""
    for nombre in ("permitida.jsonl", "denegada.jsonl", "pregunta.jsonl",
                   "sin_conexion.jsonl"):
        for evento in eventos_de(nombre):
            json.dumps(a_json(evento), ensure_ascii=False)


# --- LA FRANJA DE TAREA Y EL ANUNCIO (2026-08-27) -------------------------


class TestLaFranjaDeTarea:
    """>>> LO PIDIO EL USUARIO, Y LO COLOCO EL <<<

    Pidio ver escrito en la consola el texto de la instruccion que acaba
    de dar por voz, para saber si le llego bien; y despues, al no
    encontrarlo, pidio ponerlo donde ya sale "escuchando", como una
    frase de "trabajando".
    """

    def _consola(self, tmp_path):
        from puente.consola import Consola
        from puente.sesion import Sesion

        return Consola(Sesion(tmp_path), puerto=0)

    def test_lo_que_dices_se_pinta_y_manda_en_la_franja(self, tmp_path):
        c = self._consola(tmp_path)
        c.anuncia_turno("evalua las semanas de progreso", "voz")
        assert c.historia[-1] == {"clase": "TurnoDelUsuario",
                                  "texto": "evalua las semanas de progreso",
                                  "origen": "voz"}
        assert c.estado()["tarea"] == "evalua las semanas de progreso"
        assert c.estado()["tarea_origen"] == "voz"

    def test_el_RITUAL_se_pinta_pero_NO_se_queda_la_franja(self, tmp_path):
        """>>> LO CORRIGIO EL USUARIO VIENDOLO <<< el flujo del ritual le
        parecio el correcto, pero esa frase no es suya.

        Se sigue viendo en el flujo -- es un turno de verdad --, pero la
        franja existe para comprobar que se te ENTENDIO, y una frase
        nuestra ahi no comprueba nada y ademas tapa la tuya.
        """
        c = self._consola(tmp_path)
        c.anuncia_turno("continua con el proyecto redactor", "voz")
        c.anuncia_turno("hola, en que nos quedamos?", "ritual")
        assert c.historia[-1]["origen"] == "ritual"
        assert c.estado()["tarea"] == "continua con el proyecto redactor"

    def test_mientras_trabaja_la_franja_la_lleva_claude(self, tmp_path):
        from puente.protocolo import Texto, UsoHerramienta

        c = self._consola(tmp_path)
        c.anuncia_turno("haz una cosa", "voz")
        c.tarea.ve(Texto(texto="Ahora reviso el registro de cambios."))
        c.tarea.ve(UsoHerramienta(id_uso="u", herramienta="Read", entrada={}))
        assert c.estado()["tarea"] == "Ahora reviso el registro de cambios."
        assert c.estado()["tarea_origen"] == "claude"

    def test_al_cerrar_el_turno_la_franja_se_VACIA(self, tmp_path):
        """La pagina la esconde cuando esto viene vacio. Una franja que
        se queda con la ultima tarea para siempre dice que se trabaja
        cuando no, y se aprende a ignorar."""
        from puente.protocolo import Fin

        c = self._consola(tmp_path)
        c.anuncia_turno("haz una cosa", "voz")
        c.tarea.ve(Fin(session_id="s", subtipo="success", es_error=False,
                       texto="", coste_usd=0.0, duracion_ms=1, num_turnos=1))
        assert c.estado()["tarea"] == ""

    def test_la_franja_NO_esta_en_la_cabecera(self):
        """>>> POR QUE ESTE TEST EXISTE <<< La primera version la metio
        en `<header>`, y ahi era lo unico elastico de una fila con NODE,
        CUOTA, COSTE, SUELO, dos pestañas y el estado: se encogia a cero
        pixeles y no se veia nunca. El usuario la mando junto a la linea
        de ESCUCHANDO / TRABAJANDO, que es la que contesta "¿que esta
        pasando?".
        """
        from pathlib import Path

        pagina = (Path(__file__).resolve().parent.parent / "puente"
                  / "consola.html").read_text(encoding="utf-8")
        cabecera = pagina[pagina.index("<header"):pagina.index("</header>")]
        assert 'id="tarea"' not in cabecera
        # Y esta donde la puso el usuario: en la columna del estado.
        nucleo = pagina[pagina.index('id="estadoVoz"'):pagina.index('id="onda"')]
        assert 'id="tarea"' in nucleo


# --- el boton de reiniciar (2026-08-28) ------------------------------------
# Se prueba lo unico que puede fallar callado: que una sesion que NO sabe
# reiniciarse lo DIGA en vez de aceptar el POST y no hacer nada. Ese es el
# fallo caro -- el usuario cree aplicado un ajuste que sigue sin aplicarse
# -- y es el que convertiria el boton en un guardia decorativo.

def test_sin_carcasa_no_se_puede_reiniciar_y_se_dice(consola):
    assert consola.al_reiniciar is None
    estado, cuerpo = pide(consola, "/reiniciar", {})
    assert estado == 200
    respuesta = json.loads(cuerpo)
    assert respuesta["ok"] is False
    assert respuesta["motivo"]


def test_el_estado_dice_si_se_puede_reiniciar(consola):
    _, cuerpo = pide(consola, "/estado")
    assert json.loads(cuerpo)["reiniciable"] is False

    consola.al_reiniciar = lambda: None
    _, cuerpo = pide(consola, "/estado")
    assert json.loads(cuerpo)["reiniciable"] is True


def test_con_carcasa_contesta_ANTES_de_morir(consola):
    """El 200 tiene que salir por el cable antes de que nadie muera.

    Si `al_reiniciar` se llamase dentro del manejador, el proceso se
    cerraria con la respuesta a medio escribir y el navegador veria una
    conexion cortada: indistinguible de "el boton no hizo nada".
    """
    import threading

    llamado = threading.Event()
    consola.al_reiniciar = llamado.set

    estado, cuerpo = pide(consola, "/reiniciar", {})
    assert estado == 200
    assert json.loads(cuerpo)["ok"] is True
    # Todavia no: la respuesta va primero.
    assert not llamado.is_set()
    assert llamado.wait(timeout=5)


def test_un_reinicio_que_revienta_no_tumba_la_consola(consola):
    """Quien pide morir puede fallar, y la consola sigue contestando."""
    def explota():
        raise RuntimeError("la ventana ya no existe")

    consola.al_reiniciar = explota
    estado, _ = pide(consola, "/reiniciar", {})
    assert estado == 200
    import time

    time.sleep(1.0)
    estado, _ = pide(consola, "/estado")
    assert estado == 200


# --- EL CABEZAL EN DIRECTO (v3 de la tira, 2026-09-02) --------------------


class TestElCabezalCuelgaDeLosEventos:
    """>>> EL PUNTO 1 DE LOS CUATRO QUE DEJO ESCRITOS LA v2 <<<

    El panel de piezas se rechazo dos veces, y la segunda con este
    veredicto: no le parecia vivo todavia, no se sentia como una
    transmision en directo. El
    diagnostico con el que se eligio la v3 fue que el panel **no
    participaba del turno**: solo cambiaba cuando aterrizaba un archivo.

    De ahi el cabezal. Y de ahi que tenga que ir por SSE: `/estado` se
    sondea cada 2 s, asi que un cabezal colgado de ahi va hasta dos
    segundos por detras de la linea que el usuario acaba de ver aparecer
    en el registro. Eso no se lee como "un poco lento", se lee como
    muerto -- que es la queja entera.
    """

    def _consola(self, tmp_path):
        from puente.consola import Consola
        from puente.sesion import Sesion

        return Consola(Sesion(tmp_path), puerto=0)

    def _latidos(self, c):
        return [x for x in c._ultimo_estado.values() if x["clase"] == "Tarea"]

    def test_una_orden_enciende_el_cabezal_al_instante(self, tmp_path):
        """Y AQUI, no al primer evento de la sesion: entre que el usuario
        habla y el primer `Texto` de Claude Code hay el arranque en frio
        del binario (~3,5 s medidos en JC-0003). Un cabezal que se
        enciende al final de esa espera deja muerto justamente el rato en
        el que uno se pregunta si le ha oido."""
        c = self._consola(tmp_path)
        c.anuncia_turno("resume el proyecto", "voz")
        latido = self._latidos(c)[0]
        assert latido["tarea"] == "resume el proyecto"
        assert latido["trabajando"] is True
        assert latido["desde"] > 0

    def test_el_reloj_va_en_EPOCA_ABSOLUTA_y_no_en_segundos_transcurridos(
            self, tmp_path):
        """>>> Y NO ES UN DETALLE: ES LA PESTAÑA QUE LLEGA TARDE <<<

        A una pestaña que se abre a mitad de turno se le replica la
        historia de golpe. Con un "van 14 s" dentro del evento, el reloj
        arrancaria de cero y diria que el turno acaba de empezar. Con la
        epoca, el navegador resta -- y es el MISMO reloj, porque esto
        vive en 127.0.0.1.
        """
        import time

        c = self._consola(tmp_path)
        antes = time.time()
        c.anuncia_turno("haz una cosa", "consola")
        assert antes <= self._latidos(c)[0]["desde"] <= time.time()

    def test_solo_late_cuando_CAMBIA_algo(self, tmp_path):
        """Un latido por evento seria ruido: hay turnos con cientos, y la
        pagina repintaria lo mismo una y otra vez."""
        from puente.protocolo import Texto, UsoHerramienta

        c = self._consola(tmp_path)
        c.anuncia_turno("haz una cosa", "voz")
        primero = self._latidos(c)[0]["desde"]

        # Un `Texto` solo no cambia la tarea: todavia no se sabe si es
        # narracion o la respuesta (hace falta ver el evento siguiente).
        c.tarea.ve(Texto(texto="Voy a mirar el registro."))
        c._latir()
        assert self._latidos(c)[0]["desde"] == primero

        # La herramienta detras SI la destapa como narracion, y con la
        # tarea nueva el reloj tiene que REEMPEZAR.
        # >>> EL PUNTO DE PARTIDA SE ENVEJECE A MANO <<< Fiarlo a que dos
        # llamadas seguidas caigan en tics distintos hacia este test
        # inestable 1 de cada 5: `time.time()` en Windows avanza a saltos
        # de ~16 ms, y los dos latidos caben de sobra en uno. Es el reloj
        # de la maquina, no el codigo -- y para un reloj que se pinta en
        # segundos da igual.
        c._tarea_desde -= 100
        antiguo = c._tarea_desde
        c.tarea.ve(UsoHerramienta(id_uso="u", herramienta="Read", entrada={}))
        c._latir()
        assert self._latidos(c)[0]["tarea"] == "Voy a mirar el registro."
        assert self._latidos(c)[0]["desde"] > antiguo

    def test_al_acabar_el_turno_el_cabezal_lo_DICE(self, tmp_path):
        """`SeguidorDeTarea` vacia la tarea en el `Fin` -- una franja que
        congela la ultima tarea para siempre dice que se esta trabajando
        cuando no --, y el cabezal tiene que enterarse: es lo que apaga
        el punto y cambia el reloj por el "hace %s"."""
        from puente.protocolo import Fin

        c = self._consola(tmp_path)
        c.anuncia_turno("haz una cosa", "voz")
        c.tarea.ve(Fin(session_id="s", subtipo="success", es_error=False,
                       texto="ya esta", coste_usd=0.0, duracion_ms=1,
                       num_turnos=1))
        c._latir()
        assert self._latidos(c)[0]["trabajando"] is False
        assert self._latidos(c)[0]["tarea"] == ""

    def test_el_RITUAL_no_enciende_el_cabezal(self, tmp_path):
        """Misma regla que la franja: el flujo del ritual esta bien, pero
        esa frase no es del usuario."""
        c = self._consola(tmp_path)
        c.anuncia_turno("hola, en que nos quedamos?", "ritual")
        assert self._latidos(c) == [] or not self._latidos(c)[0]["trabajando"]


class TestLoQueEsESTADOyNoUnRenglonDelLog:
    """>>> LA TIRA Y EL CABEZAL VIAJAN POR EL CABLE DE LOS EVENTOS, Y NO
    SON EVENTOS <<<

    `historia` es lo que se le replica a una pestaña que llega tarde, y
    para un log eso esta bien: se repinta el turno entero. Pero de estos
    dos lo unico que se quiere es el ULTIMO. Replicar los cuarenta
    latidos de un turno seria pasarle una pelicula del reloj, y replicar
    cada version de la tira la haria crecer y encogerse sola al abrirla.
    """

    def _consola(self, tmp_path):
        from puente.consola import Consola
        from puente.sesion import Sesion

        return Consola(Sesion(tmp_path), puerto=0)

    def test_los_latidos_no_ensucian_el_registro(self, tmp_path):
        c = self._consola(tmp_path)
        c.anuncia_turno("haz una cosa", "voz")
        assert [x["clase"] for x in c.historia] == ["TurnoDelUsuario"]

    def test_una_pestaña_que_llega_tarde_recibe_el_estado_AL_FINAL(
            self, tmp_path):
        """Al final y no al principio: si el replay del log fuera despues,
        la pestaña nueva se quedaria pintando lo de hace diez minutos."""
        c = self._consola(tmp_path)
        c.anuncia_turno("haz una cosa", "voz")
        c._difundir_producido()
        cola = c._suscribir()
        clases = []
        while not cola.empty():
            clases.append(cola.get()["clase"])
        assert clases[0] == "TurnoDelUsuario"
        assert set(clases[1:]) == {"Tarea", "Producido"}

    def test_de_cada_uno_se_guarda_SOLO_EL_ULTIMO(self, tmp_path):
        c = self._consola(tmp_path)
        for i in range(5):
            c.anuncia_turno(f"orden {i}", "consola")
        guardados = [x for x in c._ultimo_estado.values()
                     if x["clase"] == "Tarea"]
        assert len(guardados) == 1
        assert guardados[0]["tarea"] == "orden 4"


class TestLaTiraLlegaSola:
    """La pieza que aterriza no espera al sondeo de `/estado`."""

    def test_una_pieza_nueva_se_difunde_entera(self, tmp_path):
        """>>> VA LA LISTA COMPLETA, Y NO LA PIEZA SUELTA <<<

        Porque la lista NO es la suma de lo que llego: el mismo archivo
        escrito tres veces es UNA pieza, y una imagen soltada por peso se
        convierte en lapida. Mandando la pieza suelta, la pagina tendria
        que repetir esas dos reglas para no pintar duplicados -- y dos
        copias de una regla es como divergieron los tres normalizadores
        de `voz/`.
        """
        from puente.consola import Consola
        from puente.producido import Producido
        from puente.protocolo import ResultadoHerramienta, UsoHerramienta
        from puente.sesion import Sesion

        c = Consola(Sesion(tmp_path), puerto=0)
        ruta = tmp_path / "estado.md"
        ruta.write_text("# estado", encoding="utf-8")
        c.producido.ve(UsoHerramienta(id_uso="u1", herramienta="Write",
                                      entrada={"file_path": str(ruta)}))
        assert c.producido.ve(ResultadoHerramienta(
            id_uso="u1", contenido="", es_error=False)) is not None
        c._difundir_producido()

        cuerpo = c._ultimo_estado["Producido"]
        assert cuerpo["clase"] == "Producido"
        assert [p["nombre"] for p in cuerpo["piezas"]] == ["estado.md"]
        assert cuerpo["olvidadas"] == 0
        assert isinstance(Producido().a_json()["olvidadas"], int)

    def test_el_estado_manda_la_MISMA_forma_que_el_evento(self, tmp_path):
        """Un solo dibujante en la pagina. Si las dos formas divergen, la
        tira se pinta bien por un camino y se rompe por el otro -- y el
        que se rompe es el del sondeo, o sea el que se ve al recargar."""
        from puente.consola import Consola
        from puente.sesion import Sesion

        c = Consola(Sesion(tmp_path), puerto=0)
        c._difundir_producido()
        del_evento = dict(c._ultimo_estado["Producido"])
        del_evento.pop("clase")
        assert del_evento == c.estado()["producido"]


class TestLaFraseSeQuedaAtrasYPorEsoNoVaSOLA:
    """>>> LO REPORTO EL USUARIO Y LA MEDICION LE DIO LA RAZON <<<

    Conto que a veces lo que la pantalla dice que Jarvis hace y lo que
    esta haciendo de verdad no coinciden, y sospechaba que la frase de
    "en vivo" se quedaba sin actualizar en algun momento.

    No era una sospecha. Medido contra las 38 sesiones reales de
    `logs/puente/` (`-m eval.mirar_el_desfase`): **236 de 343
    herramientas, el 69 %, corren dentro de una racha de tres o mas con
    la MISMA frase**, y la racha mas larga es de 16.

    La causa no es un fallo: es la regla de `SeguidorDeTarea`, que solo
    mueve la frase cuando Claude NARRA y detras viene una herramienta.
    Esa frase es lo que Claude DIJO, y esta bien que sea eso. Lo que
    faltaba era lo otro -- lo que esta corriendo AHORA --, y eso la
    pagina lo saca de los `UsoHerramienta`/`ResultadoHerramienta` que ya
    recibe. Este test protege la MEDICION y la regla, que es lo que un
    dia querra volver a aflojarse.
    """

    def test_la_frase_NO_se_mueve_con_cada_herramienta(self) -> None:
        """Si algun dia esto empieza a moverse sola, alguien habra hecho
        que la barra parafrasee -- y entonces deja de servir para lo que
        existe: comprobar que se te entendio."""
        from puente.protocolo import SeguidorDeTarea, Texto, UsoHerramienta

        seguidor = SeguidorDeTarea()
        seguidor.ve(Texto(texto="Voy a revisar el registro."))
        seguidor.ve(UsoHerramienta(id_uso="u1", herramienta="Read",
                                   entrada={"file_path": "a.md"}))
        assert seguidor.tarea == "Voy a revisar el registro."

        for i in range(2, 12):
            seguidor.ve(UsoHerramienta(id_uso=f"u{i}", herramienta="Read",
                                       entrada={"file_path": f"{i}.md"}))
        assert seguidor.tarea == "Voy a revisar el registro.", (
            "diez herramientas despues sigue diciendo lo mismo, y esta "
            "bien: es lo que Claude DIJO. Lo que corre ahora lo enseña "
            "el cabezal aparte")

    def test_la_medicion_del_desfase_sigue_pudiendo_hacerse(self) -> None:
        """La sonda que dio el 69 % se queda en el arbol: es el numero
        con el que se decidio, y sin ella la proxima discusion sobre esto
        vuelve a ser de impresiones."""
        from pathlib import Path

        sonda = Path(__file__).resolve().parent.parent / "eval" / "mirar_el_desfase.py"
        assert sonda.is_file()


class TestElLatidoVaBajoCERROJO:
    """>>> RAZONADO, NO MEDIDO, Y ASI SE QUEDA ESCRITO <<<

    `_latir` compara con lo ultimo mandado y, si cambio, apunta y manda.
    Entran DOS hilos: el que bombea el flujo y el que anuncia un turno
    (voz, consola o Telegram). El entrelazado que hace daño es este:

        tarea=A, apuntado=A
        hilo 1  pone tarea=B, entra en `_latir`, LEE B  -> lo echan
        hilo 2  pone tarea=C, entra en `_latir`, lee C, apunta C, manda C
        hilo 1  sigue: apunta B y manda B

    y a partir de ahi la pantalla dice B, la tarea real es C y **no hay
    ningun cambio futuro que lo arregle**: el proximo `_latir` comparara
    contra B. O sea el otro camino por el que "el estado queda sin
    actualizar", que es lo que reporto el usuario.

    >>> PERO NO SE HA CONSEGUIDO REPRODUCIR <<<
    Sonda con dos hilos, 400 ordenes cada tanda, 20 tandas y
    `setswitchinterval(1e-6)`: **0 de 20 sin cerrojo y 0 de 20 con el**.
    O sea que la ventana existe en el razonamiento y no se ha visto ni
    una vez (con cero sucesos, la tanda no ha respondido nada).
    El cerrojo se queda porque no cuesta nada y el entrelazado de arriba
    es correcto; lo que NO se hace es escribir un test que finja
    demostrarlo -- un test que no puede fallar es peor que ninguno,
    porque cierra la pregunta. Este solo comprueba que el cerrojo SIGUE
    ESTANDO, que es lo unico que aqui se puede comprobar de verdad.
    """

    def test_la_comparacion_se_hace_con_el_cerrojo_tomado(self, tmp_path):
        from puente.consola import Consola
        from puente.sesion import Sesion

        c = Consola(Sesion(tmp_path), puerto=0)
        tomas = []

        class Espia:
            def __enter__(self):
                tomas.append(1)
                return self

            def __exit__(self, *a):
                return False

        c._cerrojo_latido = Espia()
        c._difundir = lambda cuerpo: None
        c.tarea.orden("una orden cualquiera", origen="consola")
        c._latir()
        assert tomas, "`_latir` ya no toma el cerrojo"

    def test_y_no_es_el_MISMO_cerrojo_que_el_de_difundir(self, tmp_path):
        """Seria un abrazo mortal en el primer latido: `_difundir` toma
        `_cerrojo`, y un `threading.Lock` no es reentrante."""
        from puente.consola import Consola
        from puente.sesion import Sesion

        c = Consola(Sesion(tmp_path), puerto=0)
        assert c._cerrojo_latido is not c._cerrojo
        c.tarea.orden("y esto no se puede colgar", origen="consola")
        c._latir()          # si fueran el mismo, aqui se queda parado
        assert c._ultimo_estado["Tarea"]["tarea"] == "y esto no se puede colgar"


# --- los servidores MCP ----------------------------------------------------
# Ver `Consola._mcp`. Lo que esto protege es el TERCER estado: antes del
# primer turno no hay `init`, y ahi la respuesta no es "no hay ninguno".


def test_antes_del_primer_turno_no_se_sabe_que_mcp_hay(consola: Consola):
    """>>> Y ESTO NO ES UNA LISTA VACIA <<<

    `system/init` no se emite al abrir el proceso, solo cuando hay un
    turno en marcha (medido en JC-0003), asi que aqui no se ha mirado
    nada todavia. Servir `servidores: []` con `sabido: true` pintaria
    "todo en orden" sobre algo que nadie ha comprobado, que es
    exactamente el 0 % de cuota que estuvo seis dias en pantalla.
    """
    _, cuerpo = pide(consola, "/estado")
    mcp = json.loads(cuerpo)["mcp"]
    assert mcp["sabido"] is False
    assert mcp["servidores"] == []
    assert mcp["caidos"] == []


def test_el_estado_cuenta_el_servidor_caido(consola: Consola):
    """Con el init de una sesion REAL en la que blender no arranco."""
    from puente.protocolo import Inicio
    consola.sesion.inicio = [e for e in eventos_de("mcp_uno_caido.jsonl")
                             if isinstance(e, Inicio)][0]
    _, cuerpo = pide(consola, "/estado")
    mcp = json.loads(cuerpo)["mcp"]
    assert mcp["sabido"] is True
    assert mcp["caidos"] == ["blender"]
    porNombre = {s["nombre"]: s for s in mcp["servidores"]}
    assert porNombre["godot"]["arranco"] is True
    assert porNombre["blender"]["fallo"] is True
    # Los tres de claude.ai viajan, para poder pintarlos SIN alarma.
    assert porNombre["claude.ai Gmail"]["necesita_login"] is True
    assert porNombre["claude.ai Gmail"]["fallo"] is False
