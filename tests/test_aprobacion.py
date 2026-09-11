"""Approval gate tests.

The rule being tested is 'ante ambiguedad, no ejecutar'. Most of these
cases are about what does NOT count as a yes.
"""

from __future__ import annotations

import builtins

import pytest

from seguridad.aprobacion import (
    AprobacionAutomatica,
    AprobacionConsola,
    AprobacionDenegada,
    PeticionAprobacion,
    interpretar_respuesta,
)


@pytest.fixture
def peticion() -> PeticionAprobacion:
    return PeticionAprobacion(
        herramienta="fs.delete",
        args={"ruta": "C:\\Users\\x\\Downloads\\viejo.zip"},
        motivo="'fs.delete' requiere confirmacion",
        descripcion="Borrar el archivo antiguo",
        paso=3,
    )


@pytest.mark.parametrize(
    "respuesta", ["si", "sí", "s", "SI", " Si ", "yes", "y", "vale", "confirmo"]
)
def test_affirmatives_are_accepted(respuesta: str) -> None:
    assert interpretar_respuesta(respuesta).aprobado


@pytest.mark.parametrize(
    "respuesta",
    [
        "",
        "   ",
        None,
        "no",
        "n",
        "quizas",
        "puede ser",
        "sip",
        "si borra todo lo demas tambien",
        "claro que no",
        "0",
        "ok",
    ],
)
def test_everything_else_is_refusal(respuesta: str | None) -> None:
    """Not an explicit yes is a no, including near-misses and silence."""
    assert not interpretar_respuesta(respuesta).aprobado


def test_decision_is_falsy_when_refused() -> None:
    assert not interpretar_respuesta("no")
    assert interpretar_respuesta("si")


def test_question_names_the_real_tool_not_the_description() -> None:
    """A misleading `descripcion` cannot get something else approved."""
    peticion = PeticionAprobacion(
        herramienta="fs.delete",
        args={"ruta": "C:\\Downloads\\todo"},
        motivo="'fs.delete' requiere confirmacion",
        descripcion="hago una copia de seguridad",
    )
    texto = peticion.render()
    assert "fs.delete" in texto
    assert "C:\\Downloads\\todo" in texto
    # The model's words appear, but labelled as the model's words.
    assert "El planner lo describio como" in texto


def test_paths_are_shown_exactly_as_they_will_be_used() -> None:
    """No `repr` doubling: the path asked about is the path touched.

    Approving `C:\\\\Downloads\\\\x` for an action on `C:\\Downloads\\x`
    is a broken question, and in Fase 5 the TTS would read the doubled
    backslashes aloud.
    """
    texto = PeticionAprobacion(
        herramienta="fs.move",
        args={"origen": "C:\\Downloads\\a.pdf", "destino": "D:\\Docs\\a.pdf"},
        motivo="'fs.move' requiere confirmacion",
    ).render()
    assert "C:\\Downloads\\a.pdf" in texto
    assert "D:\\Docs\\a.pdf" in texto
    assert "\\\\" not in texto


def test_console_gate_reads_stdin(monkeypatch, peticion) -> None:
    monkeypatch.setattr(builtins, "input", lambda *_: "si")
    assert AprobacionConsola().solicitar(peticion).aprobado

    monkeypatch.setattr(builtins, "input", lambda *_: "no")
    assert not AprobacionConsola().solicitar(peticion).aprobado


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_console_gate_refuses_when_nobody_answers(
    monkeypatch, peticion, error
) -> None:
    """No console, or the user walked away: both mean no."""

    def interrupted(*_):
        raise error()

    monkeypatch.setattr(builtins, "input", interrupted)
    decision = AprobacionConsola().solicitar(peticion)
    assert not decision.aprobado


def test_non_interactive_gate_always_refuses(peticion) -> None:
    """A batch run cannot obtain consent, so it cannot proceed."""
    assert not AprobacionDenegada().solicitar(peticion).aprobado


def test_automatic_gate_records_what_it_approved(peticion) -> None:
    gate = AprobacionAutomatica()
    assert gate.solicitar(peticion).aprobado
    assert gate.solicitudes == [peticion]
