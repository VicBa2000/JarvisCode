"""El hilo que lee la salida de Claude Code. Rapidos y sin binario.

>>> ESTE ARCHIVO EXISTE POR UN FALLO DE UNA TARDE (2026-09-02) <<<
Al meter `--include-partial-messages` se añadio en `Sesion._leer` un
`and not es_un_trozo(linea)` -- y esa funcion **no existia**. El hilo
lector reventaba con un `NameError` en la PRIMERA linea y, como corre en
un hilo daemon, moria en silencio. Por fuera el puente quedaba sordo del
todo: la orden se manda, la pantalla la pinta, el binario contesta y no
llega nunca nada. El registro a cero bytes fue la unica pista.

>>> Y VA EN SU PROPIO ARCHIVO PARA NO MARCARLO LENTO <<<
`test_puente_sesion.py` entero esta marcado `lento` -- abre el binario de
verdad --, y esto no necesita el modelo para nada. Dejarlo alli lo
marcaba lento tambien, o sea que el test escrito para cazar un fallo que
deja el puente MUDO no se habria corrido nunca en la suite rapida. El
marcador no se paga en segundos: se paga en veces que no se corre.
"""

from __future__ import annotations

# --- EL HILO LECTOR, Y POR QUE TIENE TESTS PROPIOS (2026-09-02) ---------


class SalidaFalsa:
    """Un `stdout` con lineas dentro. No hace falta el binario para
    comprobar que se lee lo que llega y se guarda lo que toca."""

    def __init__(self, lineas):
        self._lineas = iter(lineas)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._lineas)


class ProcesoFalso:
    def __init__(self, lineas):
        self.stdout = SalidaFalsa(lineas)

    def poll(self):
        return 0


INIT = ('{"type":"system","subtype":"init","tools":["AskUserQuestion"],'
        '"cwd":"x","model":"sonnet","session_id":"s"}')
TROZO = ('{"type":"stream_event","event":{"type":"content_block_delta",'
         '"index":0,"delta":{"type":"text_delta","text":"hola"}}}')
TEXTO = '{"type":"assistant","message":{"content":[{"type":"text","text":"hola"}]}}'


def _leyendo(tmp_path, lineas, con_registro=True):
    from puente.sesion import Sesion

    registro = (tmp_path / "r.jsonl") if con_registro else None
    sesion = Sesion(tmp_path, registro=registro)
    sesion._proceso = ProcesoFalso([l + "\n" for l in lineas])
    if registro is not None:
        sesion._archivo_registro = registro.open("w", encoding="utf-8")
    sesion._leer()
    if sesion._archivo_registro is not None:
        sesion._archivo_registro.close()
        sesion._archivo_registro = None
    return sesion, registro


class TestLoQueLee:
    """>>> ESTE ARCHIVO EXISTE POR UN FALLO DE UNA TARDE (2026-09-02) <<<

    Al meter `--include-partial-messages` se añadio en `_leer` un
    `and not es_un_trozo(linea)` -- y esa funcion **no existia**. Efecto:
    el hilo lector reventaba con un `NameError` en la PRIMERA linea, y
    como corre en un hilo daemon, moria en silencio. Por fuera el puente
    quedaba sordo del todo: la orden se manda, la pantalla la pinta, el
    binario contesta y no llega nunca nada. El registro se quedaba a cero
    bytes, que fue la unica pista.

    >>> Y LO PEOR: LA COMPROBACION DE PUNTA A PUNTA PASO <<<
    Python corta el `and`. Sin archivo de registro, `es_un_trozo` no
    llegaba a evaluarse NUNCA. La sonda que se escribio para verificarlo
    corria sin registro, asi que la unica configuracion que podia ver el
    fallo era justo la que no se probo -- y la que usa la app de verdad.
    De ahi la forma de estos tests: se lee CON registro, porque es como
    corre en produccion.
    """

    def test_se_lee_lo_que_llega_y_se_encamina(self, tmp_path):
        sesion, _ = _leyendo(tmp_path, [INIT, TEXTO])
        clases = []
        while True:
            evento = sesion._cola.get_nowait()
            if evento is None:
                break
            clases.append(type(evento).__name__)
        assert "Inicio" in clases and "Texto" in clases

    def test_CON_REGISTRO_tambien_se_lee(self, tmp_path):
        """El caso que se escapo. Sin esta linea el test de arriba pasa
        igual y el puente sigue sordo en la maquina del usuario."""
        sesion, registro = _leyendo(tmp_path, [INIT, TEXTO])
        assert sesion._errores == [], f"el lector se rompio: {sesion._errores}"
        assert registro.read_text(encoding="utf-8").strip(), (
            "el registro quedo a cero bytes: es el sintoma exacto")

    def test_los_trozos_NO_se_guardan_pero_SI_se_encaminan(self, tmp_path):
        """Las dos mitades. Guardarlos multiplicaria el crudo por cuatro
        sin un dato nuevo; no encaminarlos dejaria el POV muerto."""
        sesion, registro = _leyendo(tmp_path, [INIT, TROZO, TEXTO])
        guardadas = [l for l in registro.read_text(encoding="utf-8").splitlines()
                     if l.strip()]
        assert len(guardadas) == 2, "el trozo se colo en el registro"
        assert all("stream_event" not in l for l in guardadas)

        clases = []
        while True:
            evento = sesion._cola.get_nowait()
            if evento is None:
                break
            clases.append(type(evento).__name__)
        assert "Trozo" in clases, "el trozo no llego: el POV se queda vacio"

    def test_una_linea_que_no_entendemos_SI_se_guarda(self, tmp_path):
        """Vacia no es troceo. Una linea que no produjo ningun evento es
        justo la que hay que poder mirar despues."""
        sesion, registro = _leyendo(tmp_path, [INIT, "esto no es json"])
        assert "esto no es json" in registro.read_text(encoding="utf-8")

    def test_si_el_lector_REVIENTA_se_dice_en_vez_de_morir_callado(
            self, tmp_path, monkeypatch):
        """>>> LA OTRA MITAD DEL FALLO, Y LA QUE LO HIZO CARO <<<

        Que hubiera un error es normal. Lo que no puede pasar es que el
        puente se quede mudo SIN DECIRLO: con `pythonw` no hay stderr
        donde imprimir la traza, asi que por fuera un lector muerto y una
        sesion que no contesta se ven exactamente igual.
        """
        import puente.sesion as mod

        def revienta(linea):
            raise RuntimeError("algo se rompio leyendo")

        monkeypatch.setattr(mod, "interpretar", revienta)
        sesion, _ = _leyendo(tmp_path, [INIT])
        assert sesion._errores, "el lector murio sin dejar rastro"
        assert "algo se rompio leyendo" in sesion._errores[0]

        # Y ademas se anuncia la caida, que es lo que la pantalla ya sabe
        # pintar: sin eso la consola seguiria diciendo que todo va bien.
        eventos = []
        while True:
            evento = sesion._cola.get_nowait()
            if evento is None:
                break
            eventos.append(evento)
        assert any(type(e).__name__ == "Caida" for e in eventos)
