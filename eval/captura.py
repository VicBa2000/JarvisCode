"""Capturar una pagina VIVA, sin esperar a que termine de cargar.

>>> POR QUE `--screenshot` DE EDGE NO SIRVE AQUI, Y ESTA MEDIDO <<<
La consola abre un `EventSource` a `/eventos` que **por definicion no
termina nunca**: es el flujo de la sesion. Con eso, la pagina no llega
jamas a "load complete" y el flag `--screenshot` se queda esperando. Se
probaron los dos headless contra el servidor real el 2026-09-01:

    pagina estatica (file://)      --headless=new  OK     --headless=old  OK
    la consola (127.0.0.1)         --headless=new  nada   --headless=old  nada

O sea que no es Edge: es nuestra pagina, y es correcto que sea asi.

LA SALIDA ES EL PROTOCOLO DE DEVTOOLS: `Page.captureScreenshot` dispara
cuando se le pide, mire la pagina lo que mire. Hace falta un cliente
WebSocket y el `.venv` no tiene ninguno, asi que hay uno minimo aqui
abajo -- solo lo que este uso necesita: apretar de manos, mandar texto y
leer texto, sin fragmentacion ni extensiones. No es una libreria y no
pretende serlo.

    from eval.captura import captura
    captura("http://127.0.0.1:8799/?tema=jarvis", Path("panel.png"))
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


class WebSocketMinimo:
    """Lo justo para hablar CDP. Texto, sin fragmentar, sin extensiones."""

    def __init__(self, url: str) -> None:
        sin_esquema = url.split("://", 1)[1]
        anfitrion, _, camino = sin_esquema.partition("/")
        maquina, _, puerto = anfitrion.partition(":")
        self.sock = socket.create_connection((maquina, int(puerto or 80)),
                                             timeout=30)
        clave = base64.b64encode(secrets.token_bytes(16)).decode()
        peticion = (
            f"GET /{camino} HTTP/1.1\r\n"
            f"Host: {anfitrion}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {clave}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(peticion.encode())
        respuesta = b""
        while b"\r\n\r\n" not in respuesta:
            trozo = self.sock.recv(4096)
            if not trozo:
                raise RuntimeError("el navegador cerro durante el apreton")
            respuesta += trozo
        if b"101" not in respuesta.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"no hubo upgrade: {respuesta[:120]!r}")
        self._resto = respuesta.split(b"\r\n\r\n", 1)[1]

    def manda(self, objeto: dict) -> None:
        carga = json.dumps(objeto).encode()
        # Un cliente SIEMPRE enmascara; sin eso el servidor cierra.
        mascara = secrets.token_bytes(4)
        largo = len(carga)
        if largo < 126:
            cabecera = struct.pack("!BB", 0x81, 0x80 | largo)
        elif largo < (1 << 16):
            cabecera = struct.pack("!BBH", 0x81, 0x80 | 126, largo)
        else:
            cabecera = struct.pack("!BBQ", 0x81, 0x80 | 127, largo)
        enmascarada = bytes(b ^ mascara[i % 4] for i, b in enumerate(carga))
        self.sock.sendall(cabecera + mascara + enmascarada)

    def _lee(self, cuantos: int) -> bytes:
        while len(self._resto) < cuantos:
            trozo = self.sock.recv(65536)
            if not trozo:
                raise RuntimeError("el navegador cerro la conexion")
            self._resto += trozo
        salida, self._resto = self._resto[:cuantos], self._resto[cuantos:]
        return salida

    def recibe(self) -> dict:
        while True:
            primero, segundo = struct.unpack("!BB", self._lee(2))
            largo = segundo & 0x7F
            if largo == 126:
                largo, = struct.unpack("!H", self._lee(2))
            elif largo == 127:
                largo, = struct.unpack("!Q", self._lee(8))
            carga = self._lee(largo)
            if (primero & 0x0F) == 0x1:      # texto
                return json.loads(carga.decode())
            if (primero & 0x0F) == 0x8:      # cierre
                raise RuntimeError("el navegador cerro la sesion CDP")

    def cerrar(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def captura(url: str, destino: Path, ancho: int = 1600, alto: int = 1000,
            espera_s: float = 3.0, puerto_cdp: int = 9333,
            js: str = "", tras_js_s: float = 1.2,
            recoge: list[str] | None = None) -> bool:
    """Abre `url` en Edge headless y guarda un PNG. `True` si salio.

    `js` se evalua en la pagina ANTES de capturar, para poder mirar lo
    que solo existe despues de tocar algo -- el visor de una pieza, por
    ejemplo. Es la unica forma de ver esas pantallas sin un humano
    delante, y este proyecto ya pago cuatro fallos por no mirarlas.

    `recoge`, si se pasa, se lleva DENTRO lo que devolvio el `js`. El
    valor de vuelta se queda siendo el bool de siempre a proposito: hay
    seis llamadas que lo leen asi, y una funcion que devuelve un bool o
    una cadena segun un argumento es la clase de firma que obliga a
    mirar la definicion cada vez que se lee una llamada.
    Existe porque hay sondas que MIDEN con el `js` en vez de tocar algo
    (`eval/mirar_las_columnas.py`), y hasta el 2026-09-04 el valor solo
    se podia imprimir -- o sea leer a ojo, que no es medir.
    """
    if not EDGE.is_file():
        raise FileNotFoundError(f"no esta Edge en {EDGE}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    perfil = Path(tempfile.mkdtemp(prefix="captura_"))
    navegador = subprocess.Popen(
        [str(EDGE), "--headless=new", "--disable-gpu",
         f"--remote-debugging-port={puerto_cdp}",
         f"--user-data-dir={perfil}",
         f"--window-size={ancho},{alto}",
         "--no-first-run", "--no-default-browser-check", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        objetivo = _espera_al_objetivo(puerto_cdp)
        if objetivo is None:
            return False
        # La pagina ya esta cargando; se le da su tiempo de reloj para
        # que el JS pida `/estado` y pinte. No es "esperar a que
        # termine": esta pagina no termina nunca, y ese es el punto.
        time.sleep(espera_s)
        ws = WebSocketMinimo(objetivo)
        try:
            if js:
                ws.manda({"id": 9, "method": "Runtime.evaluate",
                          "params": {"expression": js,
                                     "awaitPromise": True}})
                while True:
                    mensaje = ws.recibe()
                    if mensaje.get("id") == 9:
                        detalle = (mensaje.get("result") or {})
                        if detalle.get("exceptionDetails"):
                            raise RuntimeError(
                                f"el js reventó: {detalle['exceptionDetails']}")
                        # >>> LO QUE DEVUELVE EL JS SE DICE (2026-09-03) <<<
                        # Se tiraba en silencio, y ese silencio ya costo
                        # cuatro capturas: el selector del visor llevaba
                        # desde el 1 apuntando a la v1 (`#piezas .pieza`),
                        # devolvia 'NO' en cada pasada y nadie se entero
                        # porque el PNG salia igual de bonito. Un `return`
                        # que nadie lee es una comprobacion que no existe.
                        valor = (detalle.get("result") or {}).get("value")
                        if valor is not None:
                            if recoge is None:
                                print(f"      js -> {valor}")
                            else:
                                recoge.append(valor)
                        break
                time.sleep(tras_js_s)
            ws.manda({"id": 1, "method": "Page.captureScreenshot",
                      "params": {"format": "png"}})
            while True:
                mensaje = ws.recibe()
                if mensaje.get("id") == 1:
                    datos = (mensaje.get("result") or {}).get("data")
                    if not datos:
                        return False
                    destino.write_bytes(base64.b64decode(datos))
                    return True
        finally:
            ws.cerrar()
    finally:
        navegador.terminate()
        try:
            navegador.wait(timeout=10)
        except subprocess.TimeoutExpired:
            navegador.kill()


def _espera_al_objetivo(puerto: int, segundos: float = 25.0) -> str | None:
    """La `webSocketDebuggerUrl` de la pestana, cuando la haya."""
    limite = time.time() + segundos
    while time.time() < limite:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{puerto}/json/list", timeout=2) as r:
                for objetivo in json.loads(r.read().decode()):
                    if objetivo.get("type") == "page" and objetivo.get(
                            "webSocketDebuggerUrl"):
                        return objetivo["webSocketDebuggerUrl"]
        except OSError:
            pass
        time.sleep(0.4)
    return None
