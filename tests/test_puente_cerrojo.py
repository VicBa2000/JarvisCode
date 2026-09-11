"""Un solo Jarvis a la vez, y por que el puerto no bastaba.

>>> MEDIDO EL 2026-08-25, Y ES LO CONTRARIO DE LO QUE SE DIJO <<<
En esta misma sesion se afirmo que "el bind al puerto ya sirve de
cerrojo". Es FALSO en Windows: `HTTPServer` trae
`allow_reuse_address = 1`, y con eso un SEGUNDO servidor bindea un puerto
YA OCUPADO sin dar ningun error. Los dos arrancan y las peticiones caen
en uno u otro.

Lo que eso significa aqui no es un puerto compartido: son DOS JARVIS --
dos microfonos escuchando la misma sala y dos politicas decidiendo sobre
la misma PC, que es exactamente lo que rechazo ADR-0018. Y en silencio.

UNA SOLA SESION DE CLAUDE CODE POR JARVIS, ademas. Llevar varias a la vez
seria mas potente, pero abre el problema de a CUAL va una orden hablada;
queda como ajuste experimental futuro, con su propio ADR.
"""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from puente.consola import Consola
from puente.sesion import Sesion
from puente.suelo import QuienTieneElPuerto, quien_tiene_el_puerto


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestElBindEsElCerrojo:
    def test_un_segundo_jarvis_no_puede_bindear(self, tmp_path):
        """La comprobacion que dice si el cerrojo existe de verdad."""
        puerto = _puerto_libre()
        primera = Consola(Sesion(tmp_path), puerto=puerto)
        primera.servir(abrir_navegador=False)
        try:
            segunda = Consola(Sesion(tmp_path), puerto=puerto)
            with pytest.raises(OSError):
                segunda.servir(abrir_navegador=False)
        finally:
            primera.parar()

    def test_sin_desactivar_el_reuso_NO_habria_cerrojo(self):
        """Fija el hallazgo, no el arreglo.

        Si algun dia alguien "simplifica" quitando
        `allow_reuse_address = False`, este test sigue en verde y el de
        arriba se cae -- que es justo lo que tiene que pasar para que se
        note en vez de acabar con dos Jarvis.
        """
        class Permisivo(ThreadingHTTPServer):
            allow_reuse_address = True

        class Nada(BaseHTTPRequestHandler):
            def log_message(self, *_): pass

        puerto = _puerto_libre()
        uno = Permisivo(("127.0.0.1", puerto), Nada)
        threading.Thread(target=uno.serve_forever, daemon=True).start()
        try:
            dos = Permisivo(("127.0.0.1", puerto), Nada)
            dos.server_close()
            colo = True
        except OSError:
            colo = False
        finally:
            uno.shutdown()
            uno.server_close()
        assert colo, ("en esta maquina el reuso ya no deja robar el puerto; "
                      "el motivo del cerrojo cambio y hay que remedirlo")

    def test_se_puede_reabrir_enseguida(self, tmp_path):
        """Un Jarvis que no se puede reiniciar durante dos minutos seria
        peor que el problema que arregla. Medido: ~0,5 s."""
        puerto = _puerto_libre()
        for _ in range(3):
            consola = Consola(Sesion(tmp_path), puerto=puerto)
            consola.servir(abrir_navegador=False)
            consola.parar()


class TestQuienTieneElPuerto:
    """Tres respuestas, no dos. "Ocupado" no basta: no se le
    dice lo mismo al usuario si ya tiene un Jarvis -- traelo al frente --
    que si el puerto se lo quedo otro programa -- cambia de puerto."""

    def test_libre(self):
        quien, _ = quien_tiene_el_puerto(_puerto_libre())
        assert quien is QuienTieneElPuerto.LIBRE

    def test_reconoce_a_otro_jarvis(self, tmp_path):
        puerto = _puerto_libre()
        consola = Consola(Sesion(tmp_path), puerto=puerto)
        consola.servir(abrir_navegador=False)
        try:
            quien, detalle = quien_tiene_el_puerto(puerto)
            assert quien is QuienTieneElPuerto.OTRO_JARVIS
            assert str(puerto) in detalle
        finally:
            consola.parar()

    def test_distingue_otro_programa(self):
        """Un servidor HTTP cualquiera NO es un Jarvis. Confundirlos
        diria "ya tienes uno abierto" señalando a un programa ajeno."""
        class Cualquiera(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

        puerto = _puerto_libre()
        servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Cualquiera)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        try:
            quien, _ = quien_tiene_el_puerto(puerto)
            assert quien is QuienTieneElPuerto.OTRO_PROGRAMA
        finally:
            servidor.shutdown()
            servidor.server_close()

    def test_algo_que_no_habla_HTTP_es_NO_SE_SABE(self):
        """No se finge que esta libre ni que es un Jarvis: se dice que no
        se sabe y no se arranca a ciegas."""
        oyente = socket.socket()
        oyente.bind(("127.0.0.1", 0))
        oyente.listen(1)
        puerto = oyente.getsockname()[1]
        try:
            quien, _ = quien_tiene_el_puerto(puerto)
            assert quien is QuienTieneElPuerto.NO_SE_SABE
        finally:
            oyente.close()

    def test_la_identificacion_va_por_cabecera_no_por_el_html(self, tmp_path):
        """Una pagina cambia; una cabecera puesta a proposito, no."""
        import urllib.request
        puerto = _puerto_libre()
        consola = Consola(Sesion(tmp_path), puerto=puerto)
        consola.servir(abrir_navegador=False)
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{puerto}/", timeout=3) as r:
                assert r.headers.get("X-Jarvis") == "puente"
        finally:
            consola.parar()
