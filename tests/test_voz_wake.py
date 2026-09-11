"""Tests de `voz/wake.py`, la pieza que esta encendida siempre.

Ninguno necesita microfono ni que nadie hable: todo lo que DECIDE -- el
umbral, el refractario, la sordera -- vive en la mitad sin hardware, y
esa mitad se prueba con buffers. Lo que si necesita una persona es la
aceptacion dictada (20 activaciones con y sin ruido), y esa vive
en `eval/wake_bench.py`, no aqui.

NINGUNO VA MARCADO `lento`, y se penso antes de no marcarlos: en este
fork `lento` NO significa "tarda segundos", significa "llama a Claude
Code de verdad: es red y es dinero". Cargar un ONNX local no es ninguna
de las dos cosas. La suite entera de este archivo tarda ~5 s, y el
marcador no se paga en segundos: se paga en las veces que no se corre.
"""

from __future__ import annotations

import numpy as np
import pytest

from pathlib import Path

from tests.entorno import necesita_modelos_wake
from voz.wake import (
    SORDO_S,
    TRAMA,
    TRAMA_S,
    UMBRAL,
    Activacion,
    Escucha,
    Wake,
    WakeError,
    _umbral_configurado,
    ruta_del_modelo,
)

RAIZ = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------
# Sin modelo: lo que se puede saber sin cargar nada
# --------------------------------------------------------------------

class TestLaTrama:
    def test_la_trama_es_la_que_espera_openwakeword(self):
        """1280 muestras = 80 ms a 16 kHz. No es configurable: el
        preprocesador trocea a ese tamaño igualmente, asi que si esto
        cambia es que alguien se equivoco, no que se afino."""
        assert TRAMA == 1280
        assert abs(TRAMA_S - 0.08) < 1e-9

    def test_el_umbral_de_partida_no_pretende_estar_medido(self):
        """0.5 es el punto de partida de openWakeWord. Se ajusta contando
        falsos positivos en esta sala, no eligiendolo bonito."""
        assert UMBRAL == 0.5


class TestElUmbralConfigurado:
    """`voz.wake_word.umbral` tiene que LLEGAR hasta aqui (2026-09-03).

    Desde el 2026-08-26 el panel ofrecia este ajuste, lo validaba y lo
    guardaba, y `voz/bucle.py` construia `Wake()` sin argumento: el mando
    giraba en el vacio. Estos tests miran el valor que sale, no la
    plomeria, porque la plomeria fue exactamente lo que parecia bien
    durante ocho dias.
    """

    def _config(self, tmp_path, ajustes: str | None = None):
        import shutil

        destino = tmp_path / "config"
        destino.mkdir(parents=True)
        shutil.copy(RAIZ / "config" / "jarvis.yaml", destino / "jarvis.yaml")
        if ajustes is not None:
            (destino / "ajustes.yaml").write_text(ajustes, encoding="utf-8")
        return destino

    def test_sin_ajustes_manda_el_medido(self, tmp_path):
        assert _umbral_configurado(self._config(tmp_path)) == UMBRAL

    def test_lo_que_pone_el_panel_es_lo_que_se_usa(self, tmp_path):
        config = self._config(tmp_path, "voz.wake_word.umbral: 0.35\n")
        assert _umbral_configurado(config) == 0.35

    def test_un_valor_fuera_de_rango_NO_se_recorta_en_silencio(self, tmp_path):
        """>>> RECORTAR AQUI SERIA UN FALLO MUDO <<<

        `ajustes.yaml` se puede editar a mano, asi que un 5,0 es posible.
        Recortarlo a 0,9 dejaria a Jarvis casi sordo -- muy por encima
        del 0,494 que dio el intento bueno mas flojo -- con la pantalla
        enseñando 5,0 tan tranquila; recortar un 0,0 a 0,2 lo dejaria
        disparando solo. Ninguno de los dos da error: dan un wake word
        que se porta raro. Se avisa y se usa el medido.
        """
        for malo in ("5.0", "0.0", "-1"):
            config = self._config(tmp_path / malo,
                                  f"voz.wake_word.umbral: {malo}\n")
            assert _umbral_configurado(config) == UMBRAL, malo

    def test_una_basura_no_tumba_el_arranque(self, tmp_path):
        """Sin ajustes legibles se arranca con lo medido, no se revienta:
        el wake word es lo unico que puede volver a dar el control."""
        config = self._config(tmp_path, "voz.wake_word.umbral: hola\n")
        assert _umbral_configurado(config) == UMBRAL


class TestLaSordera:
    """Tres estados y no dos: activo / callado / SORDO.

    Un wake word escuchando silencio digital se comporta EXACTAMENTE
    igual que uno esperando: ninguno dispara. Este proyecto ya lo pago --
    16 de los 23 endpoints de esta maquina son cables virtuales que
    entregan ceros exactos sin dar error.
    """

    def test_recien_creada_no_esta_sorda(self):
        assert Escucha().sordo is False

    def test_lo_esta_tras_el_umbral_de_silencio(self):
        assert Escucha(mudo_desde_s=SORDO_S).sordo is True

    def test_justo_por_debajo_todavia_no(self):
        """El limite importa: declararse sordo demasiado pronto haria que
        el asistente dijera "no te oigo" en cada pausa larga."""
        assert Escucha(mudo_desde_s=SORDO_S - TRAMA_S).sordo is False

    def test_los_segundos_salen_de_las_tramas(self):
        assert abs(Escucha(tramas=125).segundos - 10.0) < 1e-9


class TestLaActivacion:
    def test_se_puede_locutar(self):
        """Acaba dicha en voz alta o escrita en un log; si no se entiende
        al leerla, tampoco al oirla."""
        texto = str(Activacion(puntuacion=0.87, segundo=3.2))
        assert "3.2" in texto and "0.87" in texto


class TestElModeloQueFalta:
    def test_un_modelo_inexistente_dice_como_arreglarlo(self):
        """Vive DENTRO del .venv: recrear el entorno se lo lleva. El
        mensaje trae la orden que lo baja, que es la diferencia entre
        media hora perdida y treinta segundos."""
        with pytest.raises(WakeError) as fallo:
            ruta_del_modelo("no_existe_este_modelo.onnx")
        assert "download_models" in str(fallo.value)


# --------------------------------------------------------------------
# Con el modelo cargado. Local, sin red y sin dinero: no van marcados.
#
# Pero SI necesitan que los .onnx esten bajados DENTRO del .venv, y eso
# no lo da `pip install`: lo da una orden aparte que el README pedia sin
# decirlo. Sin ella estos trece salian en ROJO en un clon recien hecho.
# Ver `tests/entorno.py`.
# --------------------------------------------------------------------

@necesita_modelos_wake
class TestConElModelo:
    def _tono(self, segundos: float, hz: float = 440.0) -> np.ndarray:
        t = np.arange(int(16000 * segundos)) / 16000
        return (0.3 * np.sin(2 * np.pi * hz * t)).astype(np.float32)

    def test_el_silencio_digital_deja_sorda_a_la_escucha(self):
        w = Wake()
        w.recorrer(np.zeros(16000 * 7, dtype=np.float32))
        assert w.escucha.sordo
        assert w.escucha.activaciones == 0

    def test_el_ruido_de_sala_NO_deja_sorda_a_la_escucha(self):
        """Una sala real tiene suelo de ruido (-31 dBFS medidos con el
        una webcam). Si el ruido contara como silencio digital, el asistente
        diria "no te oigo" estando perfectamente."""
        ruido = np.random.default_rng(0).normal(0, 0.01, 16000 * 7)
        w = Wake()
        w.recorrer(ruido.astype(np.float32))
        assert not w.escucha.sordo

    def test_ni_el_ruido_ni_un_tono_disparan(self):
        """Falsos positivos: el asistente que se despierta solo es peor
        que el que cuesta despertar."""
        w = Wake()
        w.recorrer(np.random.default_rng(1).normal(0, 0.05, 16000 * 5).astype(np.float32))
        w.recorrer(self._tono(5.0))
        assert w.escucha.activaciones == 0

    def test_int16_y_float32_dan_lo_mismo(self):
        """Las dos formas circulan por el arbol: `audio.grabar` entrega
        float32 y los wav del corpus se leen int16. Si difirieran, una
        medicion hecha con wav no valdria para el microfono.

        >>> SE SIEMBRA EL RNG GLOBAL, Y NO ES MANIA <<<
        `AudioFeatures.__init__` de openWakeWord ceba su buffer con RUIDO
        ALEATORIO del RNG global de numpy, asi que cada `Wake` nace en un
        sitio distinto: el mismo audio dio 0,2011 / 0,2248 / 0,2032 sin
        sembrar, y 0,1949 tres veces sembrando. Sin esto el test pasaba
        SUELTO y fallaba dentro de la suite, segun lo que hubiera tocado
        el RNG antes -- y la culpa parecia del codigo de aqui.
        """
        rng = np.random.default_rng(2)
        f32 = rng.normal(0, 0.05, TRAMA * 20).astype(np.float32)
        i16 = (np.clip(f32, -1, 1) * 32767).astype(np.int16)

        np.random.seed(1234)
        a = Wake()
        np.random.seed(1234)
        b = Wake()
        a.recorrer(f32)
        b.recorrer(i16)
        # Con el arranque igualado, lo unico que queda es el redondeo de
        # la conversion. Si esto se separa, es que difieren de verdad.
        assert abs(a.escucha.mejor_puntuacion - b.escucha.mejor_puntuacion) < 0.01

    def test_dos_wake_sin_sembrar_NO_dan_lo_mismo(self):
        """Fija el hallazgo, no el arreglo.

        Si algun dia openWakeWord deja de cebar con ruido, este test se
        cae y hay que releer lo que dice `voz/wake.py` sobre comparar
        puntuaciones -- que entonces pasaria a ser mas facil, no menos.
        """
        rng = np.random.default_rng(7)
        audio = rng.normal(0, 0.05, TRAMA * 20).astype(np.float32)
        puntuaciones = []
        for _ in range(3):
            w = Wake()
            w.recorrer(audio)
            puntuaciones.append(w.escucha.mejor_puntuacion)
        assert len(set(puntuaciones)) > 1, (
            "el mismo audio dio la misma puntuacion tres veces: el cebado "
            "aleatorio de openWakeWord cambio y hay que remedir")

    def test_el_refractario_impide_disparar_dos_veces_seguidas(self, monkeypatch):
        """Sin el, una sola "ey jarvis" abre dos ordenes: el modelo puntua
        por encima del umbral durante varias tramas de la misma palabra."""
        w = Wake(refractario_s=2.0)
        monkeypatch.setattr(w, "procesar", lambda _t: 0.99)

        tramas = np.zeros((30, TRAMA), dtype=np.float32)
        activaciones = [w.mirar(t) for t in tramas]
        disparos = [a for a in activaciones if a is not None]

        # 30 tramas son 2,4 s: entra la primera y, pasado el refractario,
        # como mucho una segunda. Lo que NO puede es dispararlas todas.
        assert 1 <= len(disparos) <= 2, f"{len(disparos)} disparos en 2,4 s"

    def test_un_umbral_mas_alto_dispara_menos(self, monkeypatch):
        """El umbral tiene que MANDAR de verdad, porque es la unica
        perilla que quedara para ajustar falsos positivos en esta sala."""
        duro = Wake(umbral=0.99)
        monkeypatch.setattr(duro, "procesar", lambda _t: 0.60)
        assert duro.mirar(np.zeros(TRAMA, dtype=np.float32)) is None

        blando = Wake(umbral=0.50)
        monkeypatch.setattr(blando, "procesar", lambda _t: 0.60)
        assert blando.mirar(np.zeros(TRAMA, dtype=np.float32)) is not None

    def test_recorrer_no_se_come_ni_inventa_tramas(self):
        w = Wake()
        w.recorrer(np.zeros(TRAMA * 12, dtype=np.float32))
        assert w.escucha.tramas == 12

    def test_la_escucha_mide_si_la_sala_estaba_viva(self):
        """>>> ES LO QUE HACE QUE UN "0 FALSOS POSITIVOS" SIGNIFIQUE ALGO <<<

        Una tanda de falsos positivos en una habitacion vacia mide una
        habitacion vacia. El banco lo AVISABA por escrito y no lo
        comprobaba, y la primera tanda real dio "0" sin que nadie supiera
        si habia sonado algo. Con este contador, "no salto nada" se lee
        junto a "y habia ruido el 40 % del tiempo".
        """
        callada = Wake()
        callada.recorrer(np.zeros(16000 * 3, dtype=np.float32))
        assert callada.escucha.fraccion_con_sonido == 0.0

        viva = Wake()
        t = np.arange(16000 * 3) / 16000
        viva.recorrer((0.4 * np.sin(2 * np.pi * 300 * t)).astype(np.float32))
        assert viva.escucha.fraccion_con_sonido > 0.9

    def test_el_suelo_de_ruido_de_una_sala_no_cuenta_como_sonido(self):
        """Medido en esta casa: la sala en reposo da pico ~0,04 con el
        micro USB. Si eso contara como "sonando", la comprobacion diria
        siempre que si y no comprobaria nada."""
        w = Wake()
        rng = np.random.default_rng(11)
        w.recorrer((rng.normal(0, 0.008, 16000 * 3)).astype(np.float32))
        assert w.escucha.fraccion_con_sonido < 0.05
