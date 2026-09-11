"""Aceptacion del puente: la cadena entera contra el binario de verdad.

Marcado `lento` porque llama a Claude Code, que es red y es dinero. Los
tests del protocolo y de la politica NO lo estan, y esa es la razon de la
regla: el marcador no se paga en segundos, se paga en las veces que no
se corre.

Lo que se prueba aqui no se puede probar de otra forma (nada de
mocks): que la puerta LLEGA, que la politica la contesta sola cuando debe,
que NO la contesta cuando no debe, y que el archivo aparece o no aparece
EN DISCO segun lo que se respondio.

    .venv\\Scripts\\python.exe -m pytest tests/test_puente_sesion.py -m lento -q
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from puente.politica import Veredicto
from puente.protocolo import Fin, Pregunta, Puerta
from puente.sesion import Resuelta, Sesion

pytestmark = pytest.mark.lento

ESPERA = 120.0


def esperar(sesion: Sesion, *clases: type, limite: float = ESPERA):
    """Consume events until one of `clases` shows up, or give up."""
    fin = time.time() + limite
    vistos = []
    for evento in sesion.eventos(timeout=10.0):
        vistos.append(type(evento).__name__)
        if isinstance(evento, clases):
            return evento
        if time.time() > fin:
            break
    raise AssertionError(f"no llego {clases}; se vio: {vistos}")


@pytest.fixture
def proyecto(tmp_path: Path) -> Path:
    (tmp_path / "archivo.txt").write_text("hola\n", encoding="utf-8")
    return tmp_path


def test_la_sesion_arranca_con_puerta_y_se_anuncia(proyecto: Path):
    with Sesion(proyecto) as sesion:
        # El init no llega hasta que hay turno en marcha: medido.
        sesion.mandar('Responde solamente: listo')
        sesion.esperar_inicio()
        assert sesion.inicio is not None
        assert sesion.inicio.puede_preguntar, (
            "arranco sin AskUserQuestion: el flag de la puerta no hizo efecto"
        )
        assert sesion.inicio.modo_permisos == "default"
        assert sesion.session_id


def test_una_escritura_dentro_del_proyecto_no_molesta_a_nadie(proyecto: Path):
    """El auto mode del usuario, hecho por el puente."""
    with Sesion(proyecto) as sesion:
        sesion.mandar("Crea un archivo nuevo.txt con el texto: hola")
        resuelta = esperar(sesion, Resuelta)
        assert isinstance(resuelta, Resuelta)
        assert resuelta.decision.veredicto is Veredicto.PERMITIR
        assert resuelta.puerta.herramienta == "Write"
        esperar(sesion, Fin)
        assert (proyecto / "nuevo.txt").exists()
        # Y nadie se quedo esperando.
        assert sesion.pendientes == ()


def test_un_borrado_para_la_sesion_y_espera_a_una_persona(proyecto: Path):
    """La lista endurecida, de punta a punta.

    Es el caso que el usuario pidio: todo fluido menos lo irreversible.
    """
    with Sesion(proyecto) as sesion:
        sesion.mandar("Borra el archivo archivo.txt usando el shell.")
        puerta = esperar(sesion, Puerta)
        assert isinstance(puerta, Puerta)
        assert "rm" in (puerta.orden_shell or "").lower()

        pendientes = sesion.pendientes
        assert len(pendientes) == 1
        assert pendientes[0].decision is not None
        assert pendientes[0].decision.veredicto is Veredicto.ENDURECER
        # Lo que la frase hablada tendra que nombrar.
        assert pendientes[0].decision.elementos

        # Nadie contesta durante un rato: la sesion espera, no ejecuta.
        time.sleep(5)
        assert (proyecto / "archivo.txt").exists()
        assert sesion.pendientes

        assert sesion.responder(puerta.id_peticion, permitir=False,
                                motivo="El usuario dijo que no.")
        # Segunda respuesta a la misma puerta: ya estaba consumida.
        assert not sesion.responder(puerta.id_peticion, permitir=True)

        esperar(sesion, Fin)
        assert (proyecto / "archivo.txt").exists(), "se borro tras denegar"
        assert sesion.pendientes == ()


def test_permitir_un_borrado_lo_ejecuta_de_verdad(proyecto: Path):
    """El otro lado del mismo interruptor. Si esto no borra, la puerta miente."""
    with Sesion(proyecto) as sesion:
        sesion.mandar("Borra el archivo archivo.txt usando el shell.")
        puerta = esperar(sesion, Puerta)
        assert sesion.responder(puerta.id_peticion, permitir=True)
        esperar(sesion, Fin)
        assert not (proyecto / "archivo.txt").exists()


def test_parar_un_turno_lo_corta_y_NO_cuesta_la_sesion(proyecto: Path):
    """El "para" de JC-0011, de punta a punta y contra el binario.

    Lo que se comprueba, y las tres cosas hacen falta:
      * el turno cierra marcado como PARADO, no como fallo;
      * la sesion SIGUE VIVA y con contexto -- o sea que parar no cuesta
        la conversacion, que es lo que decidiria si "para" se puede usar
        con naturalidad o solo como ultimo recurso;
      * y el turno interrumpido llega con `is_error: true`, que es la
        trampa: quien lea `fue_mal` sin mirar `parado` le contestara
        "algo ha ido mal" a alguien que acaba de mandarle callar.
    """
    with Sesion(proyecto) as sesion:
        sesion.mandar("Sin usar herramientas, escribe un ensayo de 2000 "
                      "palabras sobre la historia del reloj mecanico.")
        sesion.esperar_inicio()
        assert sesion.interrumpir() is True

        fin = esperar(sesion, Fin)
        assert fin.parado, f"razon_terminal={fin.razon_terminal!r}"
        assert fin.es_error and fin.fue_mal   # la trampa, por escrito

        sesion.mandar("Sin usar herramientas, responde solo: sigo aqui")
        siguiente = esperar(sesion, Fin)
        assert not siguiente.parado
        assert siguiente.session_id == fin.session_id


def test_contestar_una_pregunta_le_llega_al_modelo(proyecto: Path):
    """Permitir una pregunta NO la contesta. Hay que llevar la eleccion.

    Hasta el 2026-08-25 el puente contestaba `allow` con `updatedInput`
    vacio: dejaba pasar la herramienta sin decir que se habia elegido, y
    por fuera se veia igual -- el turno seguia y el modelo contestaba
    algo. Esa es la clase de fallo que este proyecto persigue, asi que la
    prueba es que el modelo REPITA la opcion.
    """
    with Sesion(proyecto) as sesion:
        sesion.mandar(
            "Usa AskUserQuestion para preguntarme si prefiero Mayusculas o "
            "Minusculas (esas dos etiquetas exactas). Cuando tengas mi "
            "respuesta no hagas nada mas: dime en una frase que elegi."
        )
        pregunta = esperar(sesion, Pregunta)
        enunciado = pregunta.enunciados[0]
        assert sesion.responder(pregunta.id_peticion, permitir=True,
                                respuestas={enunciado: "Minusculas"})

        fin = esperar(sesion, Fin)
        assert not fin.fue_mal
        assert "minuscul" in fin.texto.lower(), fin.texto


def test_la_sesion_sigue_viva_para_otro_turno(proyecto: Path):
    with Sesion(proyecto) as sesion:
        sesion.mandar("Responde solamente: uno")
        primero = esperar(sesion, Fin)
        sesion.mandar("Responde solamente: dos")
        segundo = esperar(sesion, Fin)
        assert primero.session_id == segundo.session_id
        assert "dos" in segundo.texto.lower()
