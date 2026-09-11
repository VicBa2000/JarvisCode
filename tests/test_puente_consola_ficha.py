"""La consola pide ficha (JC-0008), y por que hizo falta.

MEDIDO EL 2026-08-24, antes de que existiera esto: el servidor aceptaba
un `POST /turno` con `Origin` ajeno y `Content-Type: text/plain`. Ese par
NO dispara preflight, asi que cualquier pagina abierta en el navegador
podia mandarlo; y aunque CORS le impida LEER la respuesta, no le hace
falta -- el turno ya se habria ejecutado con la autoridad entera del
usuario sobre Claude Code.

Importaba poco mientras la consola se lanzaba a mano y duraba minutos.
Con la app arrancando con Windows y viva todo el dia, es la puerta
trasera del sistema, asi que se cerro antes de construir la carcasa.

DE QUE **NO** PROTEGE, y esta escrito para que nadie lo lea al reves: de
otro proceso local no protege, ni puede. Quien ya corre en esta maquina
con esta cuenta puede lanzar `claude` el mismo.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from puente.consola import Consola
from puente.sesion import Sesion
from puente.suelo import preparar

VERSION_FALSA = "2.1.241-en-pruebas"


@pytest.fixture
def consola_viva():
    tmp = Path(tempfile.mkdtemp())
    suelo = preparar(tmp / "suelo.json", config_dir=tmp, version=VERSION_FALSA)
    consola = Consola(Sesion(tmp, ajustes=suelo.archivo), puerto=8788,
                      suelo=suelo)
    consola.servir(abrir_navegador=False)
    time.sleep(0.4)
    try:
        yield consola, f"http://127.0.0.1:{consola.puerto}"
    finally:
        consola.parar()


def _pide(url, cabeceras=None, cuerpo=None):
    peticion = urllib.request.Request(
        url, headers=cabeceras or {},
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None)
    try:
        with urllib.request.urlopen(peticion, timeout=4) as respuesta:
            return respuesta.status
    except urllib.error.HTTPError as fallo:
        return fallo.code


class TestLaFicha:
    def test_cada_consola_tiene_la_suya(self, tmp_path):
        """Si fuera fija, valdria de una maquina a otra y de una sesion a
        la siguiente, que es tanto como no tenerla."""
        a = Consola(Sesion(tmp_path))
        b = Consola(Sesion(tmp_path))
        assert a.ficha != b.ficha
        assert len(a.ficha) >= 20

    def test_la_pagina_la_lleva_dentro(self, consola_viva):
        consola, base = consola_viva
        pagina = urllib.request.urlopen(base + "/", timeout=4).read().decode()
        assert "__FICHA__" not in pagina, "el marcador no se sustituyo"
        assert consola.ficha in pagina

    def test_la_pagina_se_sirve_sin_pedirla(self, consola_viva):
        """Es de donde sale la ficha. Servirla no es peligroso: una pagina
        ajena no puede leer la respuesta."""
        _, base = consola_viva
        assert _pide(base + "/") == 200


class TestElAtaqueQueFuncionaba:
    """El caso exacto que se midio el 2026-08-24 y que ahora se rechaza."""

    def test_post_de_una_pagina_cualquiera_se_rechaza(self, consola_viva):
        _, base = consola_viva
        assert _pide(base + "/turno",
                     {"Content-Type": "text/plain",
                      "Origin": "https://sitio-cualquiera.example"},
                     {"texto": "borra algo"}) == 403

    def test_sin_ficha_no_se_lee_ni_el_estado(self, consola_viva):
        _, base = consola_viva
        for ruta in ("/estado", "/zonas"):
            assert _pide(base + ruta) == 403, ruta

    def test_sin_ficha_no_se_guardan_zonas(self, consola_viva):
        _, base = consola_viva
        assert _pide(base + "/zonas", {"Content-Type": "text/plain"},
                     {"rutas": []}) == 403

    def test_una_ficha_inventada_no_vale(self, consola_viva):
        _, base = consola_viva
        assert _pide(base + "/estado", {"X-Jarvis-Ficha": "loquesea"}) == 403


class TestLasDosPuertas:
    """Ficha y `Origin` se comprueban por separado, y las dos tienen que
    pasar: si una se rompiera al tocar el codigo, la otra aguanta."""

    def test_con_ficha_y_origen_propio_pasa(self, consola_viva):
        consola, base = consola_viva
        assert _pide(base + "/zonas",
                     {"X-Jarvis-Ficha": consola.ficha, "Origin": base},
                     {"rutas": []}) == 200

    def test_ficha_buena_pero_origen_ajeno_se_rechaza(self, consola_viva):
        consola, base = consola_viva
        assert _pide(base + "/zonas",
                     {"X-Jarvis-Ficha": consola.ficha,
                      "Origin": "https://malo.example"},
                     {"rutas": []}) == 403

    def test_el_rechazo_es_limpio_y_no_un_reset(self, consola_viva):
        """Se drena el cuerpo antes de contestar. Sin eso la conexion se
        corta en seco y el que llama ve un reset: un rechazo que parece
        una averia acaba investigandose como una averia."""
        _, base = consola_viva
        assert _pide(base + "/zonas", {"Content-Type": "text/plain"},
                     {"rutas": []}) == 403

    def test_sin_Origin_la_ficha_basta(self, consola_viva):
        """Un cliente que no es un navegador -- la voz, Telegram, un test
        -- no manda `Origin`. No puede quedarse fuera."""
        consola, base = consola_viva
        assert _pide(base + "/estado",
                     {"X-Jarvis-Ficha": consola.ficha}) == 200
