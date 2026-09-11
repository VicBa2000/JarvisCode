"""Lo que Claude Code va contando MIENTRAS trabaja, para un oido.

>>> DE DONDE SALE (2026-08-27, peticion del usuario) <<<
Es muy comun que Claude Code suelte comentarios mientras trabaja -- del
tipo "ahora verifico el dato contra el codigo" --, que no son una
pregunta ni la respuesta a nada: se los va contando al usuario segun
avanza. Pidio que esos pasaran por el TTS, porque asi se nota que
trabaja de verdad.

Y con el limite puesto en la misma peticion: al TTS solo texto, nunca
comandos, o el sintetizador acaba leyendo en alto una ruta con dos puntos
y comas.

>>> QUE ES NARRACION Y QUE NO <<<
Un `Texto` SEGUIDO de una herramienta. El texto que va justo antes de
`Fin` es la RESPUESTA, y esa ya se locuta desde el 2026-08-25 por otro
camino (`_al_terminar`). Confundirlas locutaria la respuesta dos veces.

>>> EL FILTRO SE DISENO CONTRA LAS 23 NARRACIONES REALES <<<
`python -m eval.mirar_narracion` las saca de los registros crudos. Lo que
enseñaron, y no es lo que yo habria supuesto:

  * NINGUNA es un comando. Claude Code narra en prosa; el miedo del
    usuario no se materializa como una linea de bash suelta.
  * PERO llevan dentro cosas que no se pueden locutar. La peor del
    corpus, y es real:
        "Lanzo el reanalisis A/B del D4 (submission
         `2000d4720205e2ad09640ba48aeb7bd9`)"
    Eso son 32 caracteres de hexadecimal leidos uno a uno.
  * Y rutas de Windows: `C:\\proyectos\\nebula` se locuta como "ce dos
    puntos barra invertida proyectos barra invertida...".

>>> LA REGLA, Y SU ASIMETRIA <<<
Se tira la FRASE que lleva algo impronunciable, no el token. Sustituir el
token obligaria a inventar como se dice una ruta, que es justo lo que
`voz/resumen.py` se niega a hacer a ciegas; y borrarlo deja frases
mutiladas ("El proyecto esta en."). Tirar la frase entera se puede hacer
sin inventar nada.

Se puede tirar porque **la narracion es un lujo**: el detalle entero esta
en la consola, siempre. No oir una frase de charla no cuesta nada; oir
basura es exactamente lo que el usuario pidio evitar. La asimetria va en
esa direccion a proposito, igual que en `voz/parada.py` va en la
contraria.

>>> TRES SALIDAS, NO DOS <<<

    SE_DICE       queda prosa locutable
    NADA_QUE_DECIR  el bloque era codigo, o una linea tecnica entera
    NO_ES_NARRACION no venia seguido de herramienta; es la respuesta

La segunda no es la tercera: "no habia nada que locutar" y "esto no era
narracion" se cuentan por separado, porque si la primera crece mucho es
que el filtro esta demasiado apretado y hay que mirarlo, no que Claude
Code haya dejado de narrar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from voz.resumen import FIN_DE_FRASE, sin_markdown

# Cuanto se locuta de una narracion. Mas corto que una respuesta a
# proposito: es una acotacion al margen mientras trabaja, no la respuesta
# que se estaba esperando. ~9 s con las voces de piper.
LIMITE_NARRADO = 150

# Lo que hace impronunciable a una frase. Cada uno esta en el corpus real
# o es la forma obvia del mismo problema.
IMPRONUNCIABLE = (
    # Ruta de Windows con unidad: `C:\proyectos\nebula`. La barra
    # invertida no se locuta de ninguna forma util.
    (re.compile(r"[A-Za-z]:[\\/]"), "ruta con unidad"),
    (re.compile(r"\\\\"), "ruta de red"),
    (re.compile(r"[^\s]*\\[^\s]"), "barra invertida"),
    # Un identificador largo sin vocales suficientes: el hexadecimal de
    # 32 del corpus. Se pide LARGO y POBRE EN VOCALES para no cazar una
    # palabra normal ni un nombre de archivo corriente.
    (re.compile(r"\b(?=[0-9a-fA-F]{12,}\b)[0-9a-fA-F]{12,}\b"), "identificador"),
    # Un identificador con letras Y numeros pegados por guion o guion
    # bajo: `gemma2-27b`, `ca6a5746-7a4f`. Se exigen las DOS cosas: con
    # solo numeros cazaba "15-30 min", que es un rango y se dice bien.
    (re.compile(r"\b(?=\w*[A-Za-z])(?=\w*\d)\w*[_-]\w*\b"), "codigo mezclado"),
    # Un flag de linea de ordenes: `--query-gpu=utilization.gpu`.
    (re.compile(r"(?:^|\s)-{1,2}[A-Za-z]"), "opcion de comando"),
    # Una asignacion: `OLLAMA_HOST=127.0.0.1`.
    (re.compile(r"\w=\S"), "asignacion"),
    # Puerto suelto (`:8765`) y direccion IP.
    (re.compile(r":\d{2,5}\b"), "puerto"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "direccion IP"),
    # Simbolos de shell que no se dicen.
    # `%` y `~` quedan FUERA: en prosa son "3% de uso" y "~15 min", y
    # meterlos aqui tiraba dos narraciones buenas del corpus.
    (re.compile(r"[{}|$<>^]|&&|\|\||~/"), "simbolo de shell"),
)

# Cuantas palabras de verdad tiene que quedar para que merezca decirse.
# Por debajo de esto es una etiqueta ("Ubicado."), no una frase.
#
# DOS Y NO TRES, y lo dijo el corpus: con tres se caia "Procedo a
# borrarlo", que es prosa perfecta y ademas la mitad informativa del
# comentario. Un articulo de una letra no cuenta como palabra.
MINIMO_PALABRAS = 2

# Una palabra "de verdad": letras, con al menos una vocal. `training.db`
# la pasa (tiene vocales); `2000d472...` no.
PALABRA = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}")


class Veredicto(str, Enum):
    SE_DICE = "se_dice"
    NADA_QUE_DECIR = "nada_que_decir"


@dataclass(frozen=True)
class Narracion:
    """Lo que se locuta, y las magnitudes para saber que se dejo fuera.

    `frases_caidas` y `largo_original` son continuas. Una
    bandera "se filtro algo" no distinguiria haber tirado una coletilla
    de haber tirado el comentario entero, que es la diferencia entre un
    filtro que afina y uno que amordaza.
    """

    veredicto: Veredicto
    hablado: str = ""
    frases_dichas: int = 0
    frases_caidas: int = 0
    motivos: tuple[str, ...] = ()
    largo_original: int = 0
    recortado: bool = False

    @property
    def se_dice(self) -> bool:
        return self.veredicto is Veredicto.SE_DICE

    def describe(self) -> str:
        return (f"{self.frases_dichas} frases dichas, {self.frases_caidas} "
                f"caidas ({', '.join(self.motivos) or 'ninguna'}), "
                f"{len(self.hablado)} de {self.largo_original} caracteres")


PARENTESIS = re.compile(r"\s*\(([^()]*)\)")


def sin_el_parentesis_tecnico(frase: str) -> str:
    """Quita los incisos entre parentesis que no se pueden locutar.

    >>> ESTO NO ES INVENTAR PRONUNCIACION, Y AHI ESTA LA LINEA <<<
    Un inciso entre parentesis es gramaticalmente opcional: quitarlo deja
    una frase entera y correcta. Sustituir un token por una palabra que
    nos inventemos, no. Por eso se hace esto y no lo otro.

    Lo pidio la medicion contra el corpus: "El Agent Service ya esta
    arriba (:8765 health OK), pero la ventana..." se caia ENTERA por un
    numero de puerto metido en un inciso, y la frase de fuera era buena.
    """
    def juzgar(casa: re.Match) -> str:
        dentro = casa.group(1)
        return "" if _lo_impronunciable(dentro) else casa.group(0)

    return PARENTESIS.sub(juzgar, frase).strip()


def _lo_impronunciable(trozo: str) -> str | None:
    for patron, motivo in IMPRONUNCIABLE:
        if patron.search(trozo):
            return motivo
    return None


def por_que_no_se_dice(frase: str) -> str | None:
    """Que hace impronunciable a esta frase, si es que algo lo hace."""
    motivo = _lo_impronunciable(frase)
    if motivo:
        return motivo
    if len(PALABRA.findall(frase)) < MINIMO_PALABRAS:
        return "no llega a frase"
    return None


def para_un_oido(texto: str, limite: int | None = LIMITE_NARRADO) -> Narracion:
    """De un comentario al margen a algo que se pueda decir en voz alta.

    Frase a frase, y no todo o nada: en el corpus real casi todas las
    narraciones mezclan prosa buena con un parentesis tecnico, y tirar el
    comentario entero por el parentesis seria callarse casi siempre.
    """
    largo = len(texto or "")
    limpio = sin_markdown(texto or "").strip()
    if not limpio:
        return Narracion(Veredicto.NADA_QUE_DECIR, largo_original=largo,
                         motivos=("solo codigo",))

    frases = [f.strip() for f in FIN_DE_FRASE.split(limpio) if f.strip()]
    buenas: list[str] = []
    motivos: list[str] = []
    for frase in frases:
        # Una frase de varias lineas es una lista o una tabla disfrazada:
        # se juntan sus lineas antes de juzgarla, o el salto la parte.
        frase = sin_el_parentesis_tecnico(" ".join(frase.split()))
        porque = por_que_no_se_dice(frase)
        if porque is None:
            buenas.append(frase)
        elif porque not in motivos:
            motivos.append(porque)

    caidas = len(frases) - len(buenas)
    if not buenas:
        return Narracion(Veredicto.NADA_QUE_DECIR, frases_caidas=caidas,
                         motivos=tuple(motivos), largo_original=largo)

    hablado = " ".join(buenas)
    recortado = False
    if limite is not None and len(hablado) > limite:
        # Se corta por frase entera, nunca a mitad: media frase locutada
        # suena a que el asistente se colgo.
        cabe: list[str] = []
        for frase in buenas:
            if cabe and len(" ".join(cabe + [frase])) > limite:
                break
            cabe.append(frase)
        hablado = " ".join(cabe)
        recortado = len(cabe) < len(buenas)
        buenas = cabe

    return Narracion(
        Veredicto.SE_DICE, hablado=hablado, frases_dichas=len(buenas),
        frases_caidas=caidas, motivos=tuple(motivos),
        largo_original=largo, recortado=recortado)
