"""Enseñar o esconder la ventana, hablando.

>>> DE DONDE SALE <<<
2026-08-26, el usuario usandolo: con Jarvis en segundo plano no habia
ninguna orden para abrir su ventana hablando. Y era verdad: con la ventana
escondida en la bandeja, Jarvis te oye perfectamente -- el wake word
sigue corriendo -- pero no habia forma de pedirle que se enseñara. Habia
que ir al raton, que es justo lo que un asistente de voz viene a evitar.

>>> POR QUE ESTO NO VA AL CEREBRO <<<
La misma razon que `voz/proyecto.py`, y la misma regla:

    **se intercepta lo que el cerebro no PUEDE hacer, jamas lo que
    seria mas rapido hacer aqui.**

Claude Code no tiene la ventana. Ni siquiera sabe que existe: es de la
carcasa (`escritorio/`), que vive en otro proceso conceptual y no le
enseña nada. Mandarle "muestrate" seria pedirle que enseñe algo que no
tiene. Quien puede es el puente, y por eso lo mira el puente.

>>> Y ESTE NO LLEVA INTERRUPTOR, A DIFERENCIA DEL DE PROYECTOS <<<
No es un descuido. Cambiar de proyecto MUEVE la sesion a otra carpeta y
manda un turno solo -- hace cosas, y por eso se pide permiso para
encenderlo. Esto solo enseña o esconde una ventana: no toca la sesion,
no manda nada a la nube, no escribe en disco. Es el mismo caso que
"para" (JC-0011), que tampoco lo lleva.

Lo que si hace falta es que las frases sean ESTRECHAS. Ver `FORMAS`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class Veredicto(str, Enum):
    MOSTRAR = "mostrar"
    ESCONDER = "esconder"
    APAGAR = "apagar"
    NO_ES = "no_es"


# >>> DOS PALABRAS, Y NI UNA MAS <<<
# La primera version aceptaba diez formas -- "muestrate", "abre la
# ventana", "cierra la ventana", "escondete", "quitate de en medio"... --
# y el usuario las recorto el 2026-08-27 con el motivo exacto:
#
#     "el resto pueden afectar cuando trabajemos en sesion de claude code"
#
# Y tiene razon. Trabajando sobre codigo se dice "cierra la ventana" o
# "muestrame eso" con toda naturalidad, y ahi lo que quieres es que la
# frase LLEGUE al cerebro. Cada forma de mas es una forma de mas de
# comerse una orden buena, y el precio de equivocarse no es simetrico:
# no reconocer "abrete" cuesta ir al raton una vez; tragarse "cierra la
# ventana" cuesta que Jarvis no haga lo que le pediste y no sepas por que.
#
# `abrete` y `cierrate` son reflexivos y no significan nada mas: no hay
# forma de decirselos a Claude Code sobre un archivo. Esa es toda la
# regla, y por eso son dos y no diez.
#
# LOS PATRONES VAN SIN TILDES y el texto se normaliza antes (ver
# `_plano`): listar cada grafia a mano ya fallo una vez.
MOSTRAR = (r"\babrete\b",)
ESCONDER = (r"\bcierrate\b",)

# >>> Y UNA TERCERA, QUE NO CUESTA LO MISMO QUE LAS OTRAS DOS <<<
# La pidio el usuario el 2026-08-27: una palabra mas, "apagate", que mate
# del todo a Jarvis y a sus procesos.
#
# Cabe en la misma regla -- es reflexiva, no significa nada mas y no hay
# forma de decirsela a Claude Code sobre un archivo --, pero su
# asimetria NO es la de las otras dos: equivocarse con "cierrate"
# esconde una ventana y se recupera con un clic en la bandeja;
# equivocarse con "apagate" mata el asistente Y el turno que estuviera
# en marcha. Por eso, y solo por eso, esta se DESPIDE antes de morir:
# un apagado silencioso y un cuelgue se ven igual desde fuera, y ahi
# vuelve el modo de fallo que este proyecto lleva persiguiendo desde el
# principio -- no saber si te esta oyendo.
APAGAR = (r"\bapagate\b",)

# >>> Y EN INGLES NO HAY REFLEXIVOS, ASI QUE LA REGLA SE CUMPLE DE OTRA
# MANERA (JC-0018) <<<
# "abrete" funciona porque es reflexivo y no hay forma de decirselo a
# Claude Code sobre un archivo. En ingles no existe esa forma, y las
# obvias -- "open", "close", "shut down" -- son ordenes de trabajo que se
# dicen a diario ("shut down the container"). Las formas inglesas viven
# en `voz/idioma.py` y son de tres palabras a proposito: "show yourself",
# "hide yourself", "shut yourself down". Suenan raras, y esa rareza ES el
# mecanismo -- lo que no se dice sin querer, no se traga una orden buena.
_COMPILADAS: dict[str, dict[str, tuple]] = {}


def _formas(idioma: str | None = None) -> dict[str, tuple]:
    """Los patrones ya compilados de ese idioma. Se guardan una vez."""
    from voz.idioma import formas_de_ventana, hablado

    cual = idioma or hablado()
    if cual not in _COMPILADAS:
        crudas = formas_de_ventana(cual)
        _COMPILADAS[cual] = {
            nombre: tuple(re.compile(f, re.I) for f in patrones)
            for nombre, patrones in crudas.items()
        }
    return _COMPILADAS[cual]


# Los tres nombres de siempre, que son los del ESPAÑOL. Se conservan
# porque los tests miden contra ellos y porque el codigo se lee igual.
_MOSTRAR = tuple(re.compile(f, re.I) for f in MOSTRAR)
_ESCONDER = tuple(re.compile(f, re.I) for f in ESCONDER)
_APAGAR = tuple(re.compile(f, re.I) for f in APAGAR)


def _plano(texto: str) -> str:
    """Sin tildes, sin mayusculas y sin puntuacion.

    >>> SE REUTILIZA EL DE `voz/parada.py`, NO SE ESCRIBE OTRO <<<
    Este archivo tenia su propia copia, y el 2026-08-27 se vio a donde
    lleva eso: `voz/proyecto.py` NO normalizaba, "continúa" no casaba con
    `continua`, y el flujo entero de ADR-0029 no funcionaba en su primera
    prueba real. Habia tres formas distintas de quitar tildes en el arbol.
    Ahora hay una, la que esta medida contra lo que devuelve `small`.
    """
    from voz.parada import normalizar

    return " ".join(normalizar(texto))


@dataclass(frozen=True)
class Peticion:
    veredicto: Veredicto
    dicho: str = ""

    @property
    def es_de_ventana(self) -> bool:
        return self.veredicto is not Veredicto.NO_ES

    @property
    def es_el_final(self) -> bool:
        """La unica que no se puede deshacer sola. Se pregunta aparte
        para que ningun sitio la trate como "una de ventana mas"."""
        return self.veredicto is Veredicto.APAGAR


def interpretar(texto: str, idioma: str | None = None) -> Peticion:
    """Si esta frase pide enseñar, esconder o APAGAR.

    ESCONDER SE MIRA PRIMERO, y no da igual: "cierra la ventana y abre el
    informe" empieza pareciendo las dos cosas. Ninguna forma de MOSTRAR
    acepta complemento libre, asi que en la practica no colisionan -- pero
    el orden lo deja fijado en vez de depender de que siga siendo asi.
    """
    limpio = (texto or "").strip()
    if not limpio:
        return Peticion(Veredicto.NO_ES, limpio)
    aguja = _plano(limpio)
    formas = _formas(idioma)

    # APAGAR va PRIMERO, y por la misma razon por la que ESCONDER va
    # antes que MOSTRAR: no colisionan hoy, y el orden lo deja fijado en
    # vez de depender de que siga siendo asi.
    for nombre, veredicto in (("apagar", Veredicto.APAGAR),
                              ("esconder", Veredicto.ESCONDER),
                              ("mostrar", Veredicto.MOSTRAR)):
        for forma in formas[nombre]:
            if forma.search(aguja):
                return Peticion(veredicto, limpio)
    return Peticion(Veredicto.NO_ES, limpio)


# ======================================================================
#  EL DECISOR, Y LO LLAMAN LOS DOS CANALES
# ======================================================================
# >>> POR QUE ESTO EXISTE (2026-09-05) <<<
# Lo reporto el usuario: dicho por voz, "apagate" lo intercepta Jarvis y
# se apaga, que es lo correcto; escrito en la consola, la misma palabra se
# le pasaba entera a Claude Code.
# Escrito, "apagate" se iba al cerebro, gastaba un turno entero, Claude
# Code contestaba una despedida educada... y Jarvis seguia vivo.
#
# ES EL HUECO DEL 2026-09-03 CON OTRA FORMA. Aquel era `cambiar_a` y
# tambien vivia solo en `voz/bucle.py`. El motivo por el que se
# intercepta habla de la NATURALEZA de la orden -- Claude Code no tiene
# esta ventana, ni sabe que existe, ni puede matar al proceso que lo
# conduce --, y eso no depende de si la dices o la tecleas.
#
# ASI QUE AQUI VIVE LA DECISION Y NADA MAS. Hablar es de la voz y pintar
# es de la consola: son las dos unicas cosas que no se pueden compartir.
# Igual que `voz.proyecto.atender`, y por la misma leccion.


class Hecho(str, Enum):
    """Que paso con la frase. `NO_ES` es la unica que sigue al cerebro."""

    NO_ES = "no_es"
    MOSTRADA = "mostrada"
    ESCONDIDA = "escondida"
    APAGANDO = "apagando"
    SIN_CARCASA = "sin_carcasa"
    """No hay ventana que mover ni proceso que matar: `-m puente` pelado."""
    ROTO = "roto"
    """El gesto existia y levanto. El detalle va en `error`."""


@dataclass(frozen=True)
class Resultado:
    hecho: Hecho
    veredicto: Veredicto = Veredicto.NO_ES
    error: str = ""

    @property
    def se_ocupo(self) -> bool:
        """Si la frase ya esta atendida y NO debe ir al cerebro."""
        return self.hecho is not Hecho.NO_ES

    @property
    def es_el_final(self) -> bool:
        return self.veredicto is Veredicto.APAGAR


def atender(texto: str, gestos: Any, interrumpir: Any = None,
            idioma: str | None = None) -> Resultado:
    """Mira la frase y, si es una orden SOBRE Jarvis, la ejecuta.

    NO dice nada y NO pinta nada: eso es del canal. Devuelve que paso.

    `interrumpir` es opcional y solo se usa al APAGAR: corta el turno en
    marcha antes de morir. Si no se pasa, no se corta -- y entonces
    apagarse deja a Claude Code a medias de una cadena de herramientas,
    que es la diferencia entre apagarse y desenchufar (JC-0011 lo midio:
    el interrupt corta en centesimas y corta las herramientas de verdad).
    """
    peticion = interpretar(texto, idioma)
    if peticion.veredicto is Veredicto.NO_ES:
        return Resultado(Hecho.NO_ES)

    if peticion.es_el_final:
        if gestos is None or gestos.apagar is None:
            # Tercera salida: no hay carcasa que apagar. NO se
            # mata el proceso desde aqui a lo bruto, que dejaria la
            # sesion de Claude Code sin cerrar y el hijo `claude` vivo.
            return Resultado(Hecho.SIN_CARCASA, peticion.veredicto)
        if interrumpir is not None:
            try:
                interrumpir()
            except Exception as exc:  # noqa: BLE001
                # Que no se pueda cortar el turno NO impide apagarse: la
                # sesion se cierra igual al salir. Se dice y se sigue.
                print(f"  (no se pudo cortar el turno al apagar: {exc})")
        # >>> SE DEVUELVE ANTES DE APAGAR, Y NO ES UN DETALLE <<<
        # `apagar` no vuelve: mata el proceso. Si se llamara aqui, el
        # canal no llegaria a despedirse -- y por voz un apagado mudo y
        # un cuelgue se ven exactamente igual. El canal apaga cuando ya
        # ha dicho lo suyo.
        return Resultado(Hecho.APAGANDO, peticion.veredicto)

    mostrar = peticion.veredicto is Veredicto.MOSTRAR
    gesto = None if gestos is None else (
        gestos.mostrar if mostrar else gestos.esconder)
    if gesto is None:
        return Resultado(Hecho.SIN_CARCASA, peticion.veredicto)

    try:
        gesto()
    except Exception as exc:  # noqa: BLE001
        return Resultado(Hecho.ROTO, peticion.veredicto, str(exc))

    return Resultado(Hecho.MOSTRADA if mostrar else Hecho.ESCONDIDA,
                     peticion.veredicto)
