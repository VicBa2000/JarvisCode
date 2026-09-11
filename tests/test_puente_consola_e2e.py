"""La consola tomando el control de verdad, sin navegador de por medio.

Se conduce por los mismos endpoints HTTP que usa la pagina, contra una
sesion real de Claude Code. Si esto pasa, lo que hace el navegador es
pulsar botones sobre algo que ya esta probado.

Marcado `lento`: llama a Claude Code, que es red y es dinero.

    .venv\\Scripts\\python.exe -m pytest tests/test_puente_consola_e2e.py -m lento -q
"""

from __future__ import annotations

import json
import socket
import time
import urllib.request
from pathlib import Path

import pytest

from puente.consola import Consola
from puente.sesion import Sesion

pytestmark = pytest.mark.lento


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pide(puerto: int, ruta: str, cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    with urllib.request.urlopen(f"http://127.0.0.1:{puerto}{ruta}",
                                data=datos, timeout=15) as r:
        return json.loads(r.read())


def esperar_pendiente(puerto: int, limite: float = 120.0) -> dict:
    fin = time.time() + limite
    while time.time() < fin:
        estado = pide(puerto, "/estado")
        if estado["pendientes"]:
            return estado["pendientes"][0]
        time.sleep(0.5)
    raise AssertionError("no llego ninguna peticion pendiente")


def esperar_sin_pendientes(puerto: int, limite: float = 60.0) -> None:
    fin = time.time() + limite
    while time.time() < fin:
        if not pide(puerto, "/estado")["pendientes"]:
            return
        time.sleep(0.5)
    raise AssertionError("la peticion siguio pendiente")


@pytest.fixture
def montado(tmp_path: Path):
    (tmp_path / "archivo.txt").write_text("hola\n", encoding="utf-8")
    sesion = Sesion(tmp_path)
    sesion.abrir()
    consola = Consola(sesion, puerto=puerto_libre())
    consola.servir(abrir_navegador=False)
    yield consola, tmp_path
    consola.parar()
    sesion.cerrar()


def test_el_usuario_manda_un_turno_y_deniega_un_borrado_desde_la_consola(montado):
    """El caso que pidio el usuario: llega, ve, y decide.

    Nadie ha hablado por voz. Todo ocurre por la pantalla.
    """
    consola, proyecto = montado
    puerto = consola.puerto

    pide(puerto, "/turno", {"texto": "Borra el archivo archivo.txt con el shell."})

    pendiente = esperar_pendiente(puerto)
    assert pendiente["es_pregunta"] is False
    assert pendiente["veredicto"] == "endurecer"
    assert pendiente["motivo"]
    # Lo que la consola ensena y la voz dira: los mismos elementos.
    assert any("archivo.txt" in e for e in pendiente["elementos"])

    respuesta = pide(puerto, "/responder",
                     {"id_peticion": pendiente["id_peticion"],
                      "permitir": False, "motivo": "Ni de broma."})
    assert respuesta["ok"] is True

    esperar_sin_pendientes(puerto)
    assert (proyecto / "archivo.txt").exists(), "se borro tras denegar"


def test_la_consola_puede_permitir_y_entonces_si_se_ejecuta(montado):
    consola, proyecto = montado
    puerto = consola.puerto
    pide(puerto, "/turno", {"texto": "Borra el archivo archivo.txt con el shell."})
    pendiente = esperar_pendiente(puerto)
    assert pide(puerto, "/responder",
                {"id_peticion": pendiente["id_peticion"],
                 "permitir": True})["ok"] is True
    esperar_sin_pendientes(puerto)
    fin = time.time() + 60
    while (proyecto / "archivo.txt").exists() and time.time() < fin:
        time.sleep(0.5)
    assert not (proyecto / "archivo.txt").exists()


def test_el_segundo_canal_que_contesta_se_entera_de_que_llego_tarde(montado):
    """La carrera de JC-0008, probada de verdad y no razonada."""
    consola, _ = montado
    puerto = consola.puerto
    pide(puerto, "/turno", {"texto": "Borra el archivo archivo.txt con el shell."})
    pendiente = esperar_pendiente(puerto)
    ident = pendiente["id_peticion"]

    assert pide(puerto, "/responder",
                {"id_peticion": ident, "permitir": False})["ok"] is True
    # Segunda respuesta a la MISMA peticion, como si viniera de Telegram.
    assert pide(puerto, "/responder",
                {"id_peticion": ident, "permitir": True})["ok"] is False


def test_la_escritura_normal_no_para_a_nadie_y_queda_registrada(montado):
    """El auto mode: pasa solo, pero deja rastro en el flujo."""
    consola, proyecto = montado
    puerto = consola.puerto
    pide(puerto, "/turno", {"texto": "Crea un archivo nuevo.txt que diga hola"})

    fin = time.time() + 120
    while time.time() < fin:
        if any(c["clase"] == "Resuelta" for c in consola.historia):
            break
        time.sleep(0.5)
    resueltas = [c for c in consola.historia if c["clase"] == "Resuelta"]
    assert resueltas, "no quedo rastro de la aprobacion automatica"
    assert resueltas[0]["decision"]["veredicto"] == "permitir"
    assert pide(puerto, "/estado")["pendientes"] == []
