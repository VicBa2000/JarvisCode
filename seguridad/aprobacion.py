"""Approval gates.

Section 8.2: every destructive or irreversible action passes through an
explicit confirmation, and **when in doubt, do not execute**. This module
owns that moment.

Three decisions are baked in here.

**Silence is refusal.** `interpretar_respuesta` accepts a short list of
affirmatives and treats everything else — an empty line, "quizas", a
typo, EOF — as no. This is the opposite of the usual `[Y/n]` convention,
on purpose: the cost of a wrongly-approved `fs.delete` is not symmetric
with the cost of asking again.

**The question is built from the resolved call, never from the model's
prose.** What the user is asked to approve is the tool name and the
actual arguments, so a plan whose `descripcion` says "hago una copia de
seguridad" while its step is `fs.delete` cannot get a deletion approved
by describing it as something else. The description is shown as context,
clearly separated, and it does not determine what is asked.

**The gate is an interface, not a print statement.** Fase 5 replaces the
console with speech, and tests need a gate that never blocks. Both
are implementations of `PuertaAprobacion`; the executor never learns
which one it holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

# Only these mean yes. Everything else means no — see the module
# docstring on why this list is short and closed.
# >>> EL INGLES SE ANADIO SIN ENSANCHAR LA LISTA (JC-0018, 2026-08-28) <<<
# La tentacion era generosa -- "yeah", "sure", "sounds good", "do it" --
# y no se hizo: ensanchar aqui es inventar deteccion de afirmativas en el
# UNICO sitio donde equivocarse ejecuta algo irreversible. Ademas es
# innecesario, porque la peticion hablada TERMINA diciendo "Answer yes or
# no": la palabra que se pide es la que esta en la lista.
#
# >>> Y "ok" SE QUEDO FUERA, AVISADO POR UN TEST <<<
# El primer intento metia "ok"/"okay" como equivalentes de "vale".
# `tests/test_aprobacion.py` los tenia listados COMO RECHAZO desde el
# proyecto original, a proposito. Se retiraron en vez de aflojar el test:
# la asimetria "vale si, ok no" sera discutible, pero la decision de que
# cuenta como consentimiento ya estaba tomada y no se cambia de paso
# mientras se hace otra cosa. Si algun dia se quiere, es una decision
# propia y con su entrada.
_AFIRMATIVAS = {
    "si", "sí", "s", "vale", "adelante", "confirmo",
    "yes", "y", "go ahead", "confirm",
}


def _mostrar(value: Any) -> str:
    """Format one argument for a human reading the confirmation.

    Strings are shown as written, not `repr`'d: `repr` doubles the
    backslashes of a Windows path, so the user would be asked to approve
    `C:\\\\Downloads\\\\x` for an action on `C:\\Downloads\\x`. Being
    shown a path that is not the path being touched defeats the point of
    asking. Quotes are added only when the value would otherwise be
    ambiguous — empty, or padded with spaces.
    """
    if isinstance(value, str):
        return value if value.strip() == value and value else f'"{value}"'
    # A value whose class wrote its own `__str__` said how it wants to be
    # read by a person; the containment step resolves some arguments into
    # objects (a window title becomes a `Ventana`) and the default repr
    # would put its handle in the question — noise now, and noise the TTS
    # would read out loud in Fase 5.
    if type(value).__str__ is not object.__str__:
        return str(value)
    return repr(value)


@dataclass(frozen=True)
class PeticionAprobacion:
    """What the user is being asked to allow."""

    herramienta: str
    args: dict[str, Any]
    motivo: str
    descripcion: str = ""
    paso: int | None = None
    # What the step will actually do, when the arguments do not say it.
    #
    # `fs.delete(ruta=...)` names the file it destroys, so the call is the
    # question. `vision.act(objetivo='abre el menu Archivo')` does not: a
    # model decides the keystroke after looking at the screen, and asking
    # about the goal would be asking for a blank cheque. The executor
    # fills this in from the prepared action — never from the planner's
    # prose — so the question names the thing being consented to.
    accion_concreta: str = ""

    def render(self) -> str:
        """The question, in Spanish, as the user sees or hears it."""
        args = ", ".join(f"{k}={_mostrar(v)}" for k, v in self.args.items())
        cabecera = f"Paso {self.paso}: " if self.paso is not None else ""
        lineas = [
            f"{cabecera}Jarvis quiere ejecutar:",
            f"    {self.herramienta}({args})",
        ]
        if self.accion_concreta:
            # Above the motive, because it is the question. Everything
            # else on this screen is context for it.
            lineas.append(f"  En concreto: {self.accion_concreta}")
        lineas.append(f"  Motivo: {self.motivo}")
        if self.descripcion:
            # Shown as context and labelled as the model's words, so it
            # informs the user without defining what is being approved.
            lineas.append(f"  El planner lo describio como: {self.descripcion}")
        return "\n".join(lineas)


@dataclass(frozen=True)
class Decision:
    aprobado: bool
    respuesta: str = ""

    def __bool__(self) -> bool:
        return self.aprobado


def interpretar_respuesta(texto: str | None) -> Decision:
    """Turn a free-form answer into a decision, defaulting to refusal."""
    limpio = (texto or "").strip().lower().rstrip(".!")
    return Decision(aprobado=limpio in _AFIRMATIVAS, respuesta=(texto or "").strip())


class PuertaAprobacion(Protocol):
    """Anything that can answer an approval request."""

    def solicitar(self, peticion: PeticionAprobacion) -> Decision: ...


class AprobacionConsola:
    """Asks on stdin. The Fase 2 gate; Fase 5 swaps it for voice."""

    def solicitar(self, peticion: PeticionAprobacion) -> Decision:
        print(f"\n{peticion.render()}")
        try:
            respuesta = input("  ¿Autorizas? (si / no) > ")
        except (EOFError, KeyboardInterrupt):
            # No console to answer on, or the user walked away. Both are
            # 'not an explicit yes', which is a no.
            print()
            return Decision(aprobado=False, respuesta="[sin respuesta]")
        return interpretar_respuesta(respuesta)


class AprobacionDenegada:
    """Refuses everything without asking.

    The right gate for any non-interactive run: a batch job cannot obtain
    explicit consent, so it must not be able to proceed as if it had.
    """

    def solicitar(self, peticion: PeticionAprobacion) -> Decision:
        return Decision(
            aprobado=False,
            respuesta="[modo no interactivo: sin aprobacion posible]",
        )


class AprobacionAutomatica:
    """Approves everything. **Tests only.**

    Deliberately named so that it is obvious in a diff. If this ever
    appears on a path the user can reach, that is the bug — not whatever
    it approved.
    """

    def __init__(self) -> None:
        self.solicitudes: list[PeticionAprobacion] = []

    def solicitar(self, peticion: PeticionAprobacion) -> Decision:
        self.solicitudes.append(peticion)
        return Decision(aprobado=True, respuesta="[aprobacion automatica de test]")
