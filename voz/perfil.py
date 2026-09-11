"""Voice personas: the name Jarvis answers to, its voice, and its trigger.

WHY A PROFILE AND NOT THREE LOOSE SETTINGS (asked for on 2026-08-20):
the three travel together. Switching to a female voice while the system
still calls itself Jarvis and still answers to "Hey Jarvis" is three
half-changes, and the half that gets forgotten is always the one nobody
is looking at. A profile makes the switch atomic and makes the parts
that CANNOT change independently visible.

WHAT A PROFILE CAN AND CANNOT CHANGE, which is the whole reason this
file carries a warning:

    nombre      free. It is just what the system calls itself.
    tts_voz     free. Any voice downloaded into modelos/piper.
    wake_words  NOT FREE. openWakeWord ships exactly four usable
                pretrained phrases -- alexa, hey_mycroft, hey_jarvis,
                hey_rhasspy -- and ADR-0002 picked "hey_jarvis"
                precisely because it needs ZERO training. Any other
                phrase means training a model, which is hours of work
                and a decision ADR-0002 deliberately avoided.

So a persona whose name is not one of those four either keeps a trigger
phrase that does not match its name, or stops being free. That trade is
the user's to make, and it is written here so the choice is made with
the cost visible instead of discovered in 5.4.

WHY `wake_words` IS A LIST: openWakeWord loads several models at once
and scores them in the same pass, so one persona can answer to more than
one phrase at no extra design cost. Asked for on 2026-08-20 ("hey
epsilon" as a second name for Jarvis, after Pluto). Making it plural now
costs nothing; making it plural after 5.4 would be a migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nucleo.configuracion import load_general_config

# The pretrained phrases openWakeWord can use without training anything.
# `timer` and `weather` are in the same registry but they are commands,
# not activation phrases.
WAKE_WORDS_SIN_ENTRENAR = ("alexa", "hey_mycroft", "hey_jarvis", "hey_rhasspy")


class PerfilError(RuntimeError):
    """The requested persona is missing or incomplete."""


@dataclass(frozen=True)
class Perfil:
    """One persona: what it is called, how it sounds, what wakes it."""

    clave: str
    nombre: str
    tts_voz: str
    wake_words: tuple[str, ...]

    @property
    def wake_words_a_entrenar(self) -> tuple[str, ...]:
        """The trigger phrases that do not exist yet as a model.

        Not an error: training one is a legitimate choice with a cost,
        and the cost belongs in 5.4. What would be wrong is discovering
        it there.
        """
        return tuple(w for w in self.wake_words if w not in WAKE_WORDS_SIN_ENTRENAR)

    @property
    def wake_words_listas(self) -> tuple[str, ...]:
        """The ones that work today, with no training at all."""
        return tuple(w for w in self.wake_words if w in WAKE_WORDS_SIN_ENTRENAR)

    @property
    def puede_despertarse_hoy(self) -> bool:
        """Whether this persona can be woken with what is downloaded.

        A profile whose every phrase still needs training is not a
        configuration mistake -- it is a plan. But it cannot be the
        ACTIVE one, or Jarvis simply never wakes up.
        """
        return bool(self.wake_words_listas)

    def describe(self) -> str:
        listas = ", ".join(f"'{w}'" for w in self.wake_words_listas) or "(ninguna)"
        lineas = [
            f"{self.clave}: se llama {self.nombre}, voz {self.tts_voz}, "
            f"se activa con {listas}"
        ]
        if self.wake_words_a_entrenar:
            pendientes = ", ".join(f"'{w}'" for w in self.wake_words_a_entrenar)
            lineas.append(f"  [!] pendientes de ENTRENAR: {pendientes}")
        return "\n".join(lineas)


def perfiles_declarados(config_dir: Path | None = None) -> dict[str, Perfil]:
    """Every persona in `config/jarvis.yaml`, by key."""
    try:
        bloque = (load_general_config(config_dir) or {}).get("voz") or {}
    except Exception as exc:  # noqa: BLE001
        raise PerfilError(f"No se pudo leer config/jarvis.yaml: {exc}") from exc

    declarados = bloque.get("perfiles") or {}
    perfiles: dict[str, Perfil] = {}
    for clave, datos in declarados.items():
        datos = datos or {}
        faltan = [c for c in ("nombre", "tts_voz", "wake_words") if not datos.get(c)]
        if faltan:
            raise PerfilError(
                f"El perfil de voz '{clave}' esta incompleto: falta {', '.join(faltan)}. "
                f"Un perfil a medias es peor que ninguno: cambiaria la voz y dejaria "
                f"el nombre o el disparador del anterior."
            )
        palabras = datos["wake_words"]
        if isinstance(palabras, str):
            # Una cadena suelta se acepta como una lista de uno. Tolerar
            # el adorno al ENTRAR es la estrategia aprobada;
            # lo que no vale es que 'hey_jarvis' se lea como diez frases
            # de una letra.
            palabras = [palabras]
        perfiles[str(clave)] = Perfil(
            clave=str(clave),
            nombre=str(datos["nombre"]),
            tts_voz=str(datos["tts_voz"]),
            wake_words=tuple(str(w) for w in palabras),
        )
    return perfiles


def perfil_activo(config_dir: Path | None = None) -> Perfil:
    """The persona selected by `voz.perfil`.

    Refuses to pick one on its own when the setting is missing or points
    nowhere, and enumerates what IS declared -- the same shape as
    `voz.audio.seleccionar` and `voz.tts.ruta_de_voz`. Falling back to
    "the first one" would mean the system quietly answers to a different
    name than the config says.
    """
    try:
        bloque = (load_general_config(config_dir) or {}).get("voz") or {}
    except Exception as exc:  # noqa: BLE001
        raise PerfilError(f"No se pudo leer config/jarvis.yaml: {exc}") from exc

    perfiles = perfiles_declarados(config_dir)
    if not perfiles:
        raise PerfilError("config/jarvis.yaml no declara ningun perfil en voz.perfiles.")

    clave = bloque.get("perfil")
    if not clave:
        raise PerfilError(
            "config/jarvis.yaml no dice cual es el perfil activo (voz.perfil). "
            f"Declarados: {', '.join(sorted(perfiles))}."
        )
    if str(clave) not in perfiles:
        raise PerfilError(
            f"El perfil activo '{clave}' no esta declarado en voz.perfiles.\n"
            f"  declarados: {', '.join(sorted(perfiles))}"
        )
    perfil = perfiles[str(clave)]
    if not perfil.puede_despertarse_hoy:
        # Un perfil cuyas frases estan todas por entrenar es un PLAN
        # legitimo, y por eso puede declararse. Lo que no puede es estar
        # activo: Jarvis se quedaria escuchando sin poder despertarse
        # nunca, y eso no daria ningun error en marcha.
        raise PerfilError(
            f"El perfil activo '{perfil.clave}' no tiene ninguna frase de "
            f"activacion utilizable hoy: {', '.join(perfil.wake_words)} estan "
            f"todas por entrenar.\n"
            f"  preentrenadas (cero entrenamiento): "
            f"{', '.join(WAKE_WORDS_SIN_ENTRENAR)}"
        )
    _comprobar_idioma(perfil, config_dir)
    return perfil


def _comprobar_idioma(perfil: Perfil, config_dir: Path | None = None) -> None:
    """Que la voz hable el idioma que Jarvis dice hablar (JC-0018).

    >>> EL FALLO QUE ESTO EVITA SE OYE, PERO NO DA ERROR <<<
    Piper sintetiza por fonemas del idioma con el que se entreno la voz.
    Una voz española leyendo texto ingles no revienta: produce ingles con
    fonetica española, o sea algo que se entiende a medias y suena a
    aparato roto. Y al reves igual. Como no hay excepcion que capturar,
    sin esta comprobacion el unico sintoma seria el usuario diciendo "se
    oye raro" y nadie sabiendo por que.

    TRES RESPUESTAS Y NO DOS: coincide / no coincide / **no se
    sabe**. Un nombre de voz que no empiece por un prefijo de idioma
    reconocible no se declara malo -- podria ser una voz propia -- y se
    deja pasar. Denegar ahi convertiria una voz legitima en un Jarvis que
    no arranca.
    """
    from voz.idioma import hablado

    try:
        quiere = hablado(config_dir)
    except Exception:  # noqa: BLE001
        return
    prefijo = perfil.tts_voz.split("_", 1)[0].lower()
    if prefijo not in ("es", "en"):
        return  # no se sabe: no es asunto nuestro
    if prefijo == quiere:
        return
    raise PerfilError(
        f"El perfil activo '{perfil.clave}' habla con una voz {prefijo!r} "
        f"({perfil.tts_voz}) pero Jarvis esta puesto en {quiere!r}.\n"
        f"  Una voz de otro idioma no da error: lee el texto con la "
        f"fonetica que no es, y solo se nota al oirlo.\n"
        f"  Elige un perfil del idioma en los ajustes, o cambia el "
        f"idioma de la voz."
    )
