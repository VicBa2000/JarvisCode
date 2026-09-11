"""Lo unico que Claude Code sabe de que le estan hablando por un altavoz.

>>> POR QUE ESTO NO EXISTIA, Y QUE COSTABA <<<
`Sesion.mandar()` manda un bloque de texto pelado y la linea de ordenes
no llevaba `--append-system-prompt`. O sea que el cerebro escribia para
una PANTALLA porque nadie le habia dicho nunca otra cosa.

>>> Y HAY DOS CANALES DISTINTOS, NO UNO (LO DESTAPO `ajustes.yaml`) <<<
La prosa del proyecto dice que JC-0004 quedo revocado y que la respuesta
se locuta ENTERA. En disco, `config/ajustes.yaml` dice `voz.resumir:
true` -- el usuario lo volvio a encender desde el panel. Son dos canales
con consejos OPUESTOS, y escribir un solo texto para los dos habria
mentido en uno de ellos. El archivo manda sobre la prosa, y
aqui la prosa era justamente la que describe el proyecto.

Medido sobre las 93 respuestas reales que hay en disco, antes de escribir
esto (`-m eval.mirar_respuestas`):

                    ENTERA (limite=None)   RESUMIDA (limite=240)
    mediana            198 car /  14 s        166 car / 12 s
    p90               1642 car / 117 s        495 car / 35 s
    maximo            2656 car / 190 s       1013 car / 72 s
    pasa de 60 s        24/93                   3/93

RESUMIDA es el modo vivo hoy, y su consejo no es "se breve": es que solo
se oyen las PRIMERAS FRASES y el resto no llega nunca. Es exactamente el
hallazgo con el que se diseno `voz/resumen.py`: la respuesta larga de las
trazas empieza con "...se organiza asi:", que locutada sola no dice NADA
y suena a que el asistente se colgo.

>>> LO QUE SE LE DICE ES VERDAD, Y ESO NO ES UN DETALLE <<<
Cada afirmacion del texto esta comprobada contra el codigo que la
produce, no contra su docstring:

    "todo se ve ademas en una consola"   `puente/consola.py`, y sigue
                                         siendo cierto en auto mode:
                                         sordos no es ciegos (medido el
                                         2026-08-27, los cinco modos).
    "solo se oyen las primeras frases"   `para_un_oido(..., limite=240)`
    / "se locuta entera"                 segun `voz.resumir`. Lo elige el
                                         lanzador, que es quien lo lee.
    "el codigo NO se locuta"             `voz/resumen.py`, la primera
                                         sustitucion de `sin_markdown`:
                                         los bloques se van enteros y en
                                         su lugar se dice donde estan.
    "las tablas SI se locutan"           y es lo incomodo: `sin_markdown`
                                         no las toca. Llegan al TTS con
                                         sus barras. Son 5 de 93 en los
                                         registros reales, en LOS DOS
                                         modos.

Si alguna deja de ser cierta, este texto pasa a MENTIRLE al modelo sobre
su propio canal, que es peor que no decirle nada. Hay un test por cada
una precisamente por eso.

>>> NO SE LE DA AUTORIDAD, Y NI SE MENCIONA LA PUERTA <<<
Esto describe el CANAL de salida y nada mas. No dice que puede hacer, no
habla de permisos, no nombra la lista endurecida de JC-0001 ni el suelo
de JC-0007. Un preambulo que explicase la puerta le estaria ensenando al
modelo por donde no pasa, y quien decide sigue siendo la puerta, no lo
que el modelo crea. La ultima linea del texto lo dice en voz alta para
que tampoco lo deduzca.

>>> Y SOLO EXISTE CON LA VOZ ENCENDIDA <<<
Sin `--voz` esto seria una mentira completa: nadie va a oir nada, la
consola es todo lo que hay, y pedirle prosa corta a cambio de tablas
empeoraria la unica salida que queda. Lo decide el LANZADOR, igual que
`modo_permisos`: ver `puente/__main__.py`.
"""

from __future__ import annotations

from pathlib import Path

# El idioma del texto es el idioma HABLADO (JC-0018) y no el de la
# pantalla: lo que se pide aqui es en que idioma va a contestar, y quien
# lo recita es la voz de Piper que eligio `voz.idioma`. Atarlo a
# `ui.idioma` habria dejado a una voz inglesa recitando espanol el dia
# que alguien pusiera la pantalla en ingles y la voz no.

CABECERA = {
    "es": ("Estas conectado a Jarvis. Quien te escribe te esta HABLANDO por"
           " un microfono, y tu respuesta se lee en alto por un altavoz."),
    "en": ("You are connected to Jarvis. The person writing to you is"
           " SPEAKING into a microphone, and your answer is read aloud"
           " through a speaker."),
}

# >>> LA PARTE QUE CAMBIA, Y SUS CONSEJOS SON OPUESTOS <<<
# Con resumen, lo que no quepa en las primeras frases NO SE OYE JAMAS: el
# problema es que la respuesta empiece por una entradilla vacia. Sin
# resumen se oye todo, y el problema es la duracion. Decirle el que no es
# deja al modelo optimizando contra un canal que no tiene.
CANAL = {
    True: {
        "es": ("- De tu respuesta SOLO se locutan las primeras frases (unos"
               " 240 caracteres). El resto no se oye nunca: se queda en la"
               " consola.\n"
               "- Asi que la primera frase tiene que llevar ya la respuesta."
               " Una entradilla del tipo \"esto se organiza asi:\" se locuta"
               " sola y no dice nada."),
        "en": ("- Only the FIRST sentences of your answer are spoken (about"
               " 240 characters). The rest is never heard: it stays in the"
               " console.\n"
               "- So the first sentence must already carry the answer. An"
               " opener like \"here is how this breaks down:\" gets spoken"
               " alone and says nothing."),
    },
    False: {
        "es": ("- Tu respuesta se locuta ENTERA, no resumida. Cien palabras"
               " son casi un minuto de altavoz.\n"
               "- Asi que se breve por defecto: si algo se puede decir en"
               " tres frases, tres."),
        "en": ("- Your answer is spoken IN FULL, not summarised. A hundred"
               " words is nearly a minute of speaker time.\n"
               "- So be brief by default: if it fits in three sentences,"
               " use three."),
    },
}

CUERPO = {
    "es": ("- Todo lo que escribes se ve ademas en una consola en pantalla,"
           " asi que el detalle no se pierde.\n"
           "- Los bloques de codigo NO se locutan nunca: se quitan antes de"
           " llegar al altavoz y en su lugar se dice que estan en la"
           " consola.\n"
           "- Las tablas SI se locutan, con sus barras y sus guiones, y asi"
           " no se entienden.\n"
           "\n"
           "Que se te pide, por tanto:\n"
           "- Escribe para que funcione OIDO: prosa, frases cortas, y lo que"
           " importa delante.\n"
           "- El detalle largo, las tablas y el codigo son para la PANTALLA:"
           " ponlos detras, y que lo hablado se entienda sin ellos.\n"
           "- En lo hablado, evita rutas, comandos e identificadores cuando"
           " puedas nombrarlos de otro modo: leidos en alto no se"
           " entienden.\n"
           "- Contesta en español.\n"
           "\n"
           "Esto describe por donde sale tu respuesta. No cambia lo que"
           " puedes hacer."),
    "en": ("- Everything you write is also shown in an on-screen console, so"
           " detail is not lost.\n"
           "- Code blocks are NEVER spoken: they are stripped before the"
           " speaker and replaced by a note saying they are in the"
           " console.\n"
           "- Tables ARE spoken, pipes and dashes and all, which is"
           " unintelligible.\n"
           "\n"
           "So what is asked of you:\n"
           "- Write to work when HEARD: prose, short sentences, what matters"
           " first.\n"
           "- Long detail, tables and code are for the SCREEN: put them"
           " after, and make the spoken part stand without them.\n"
           "- In the spoken part, avoid paths, commands and identifiers"
           " where you can name the thing another way: they are not"
           " intelligible aloud.\n"
           "- Answer in English.\n"
           "\n"
           "This describes where your answer comes out. It does not change"
           " what you can do."),
}


def preambulo(idioma: str | None = None, resumido: bool = False,
              config_dir: Path | None = None) -> str:
    """El texto para `--append-system-prompt`, en el idioma HABLADO.

    `resumido` es `voz.resumir`, y no tiene un defecto que adivine: lo lee
    el lanzador del mismo sitio del que lo lee la voz
    (`nucleo.ajustes.valor_de`), para que no puedan discrepar. Ver
    `puente/__main__.py`.
    """
    from voz.idioma import hablado

    cual = idioma or hablado(config_dir)
    return (CABECERA[cual] + "\n\n"
            + "Como llega de verdad lo que escribes:\n"
            + CANAL[bool(resumido)][cual] + "\n"
            + CUERPO[cual])
