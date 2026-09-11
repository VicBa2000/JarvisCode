"""Las palabras que Jarvis SE QUEDA antes de mandarlas al cerebro.

>>> LO PIDIO EL USUARIO EL 2026-09-05 <<<
Pidio un glosario con las palabras "clave" que Jarvis usa y reconoce.
Y hace falta por una razon concreta: estas
son las UNICAS frases que no llegan a Claude Code. Todo lo demas viaja
entero. Si no estan escritas en ningun sitio, la unica forma de
enterarse de que "apagate" es especial es decirlo sin querer.

>>> SE COMPRUEBA CONTRA QUIEN INTERCEPTA, NO SE FIA DE SI MISMO <<<
Una lista copiada es prosa, y la prosa envejece sin avisar -- este arbol
ya se ha cobrado varias. Aqui cada entrada trae su FRASE DE EJEMPLO, y
`tests/test_voz_glosario.py` la pasa por el interprete de verdad, EN LOS
DOS IDIOMAS: si alguien afina una forma y no toca el glosario, el test
falla. La lista no puede mentir sobre lo que Jarvis reconoce porque se
comprueba contra lo que Jarvis reconoce.

Lo que se escribe a mano es la explicacion ("apaga Jarvis entero"),
porque eso no vive en ningun sitio del que sacarlo.

>>> Y VA POR IDIOMA DESDE EL ORIGEN, NO TRADUCIDO EN LA PAGINA <<<
Estas frases NO son las mismas traducidas: en ingles son `show yourself`
/ `hide yourself` / `shut yourself down`, de tres palabras y raras a
proposito, porque el ingles no distingue el imperativo y "stop the
server" es una orden normal (JC-0018). Un glosario que tradujera
"abrete" a "open yourself" enseñaria una frase que Jarvis NO reconoce --
que es exactamente el fallo que este modulo existe para evitar. Ademas
viaja como JSON, o sea que `traducir_pagina` no lo tocaria nunca.

>>> Y DICE POR QUE CANAL VALE CADA UNA, QUE ES LA OTRA MITAD <<<
No todas valen en los dos, y las diferencias son decisiones tomadas:
  * las de ventana y el cambio de proyecto valen DICHAS Y ESCRITAS
    (2026-09-03 y 2026-09-05, los dos huecos que reporto el usuario);
  * el lexico de parada vale solo DICHO. Escrita, "para" es una
    preposicion normal, y la consola tiene Esc, que corta lo mismo.
Sin esto, alguien escribe "para", no pasa nada, y se queda mirando.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Entrada:
    """Una frase que Jarvis se queda, y todo lo que hay que saber de ella."""

    frase: str
    """El ejemplo, tal cual se dice. Es lo que el test pasa por el
    interprete de verdad, y por eso no puede ser inventado."""
    hace: str
    canales: tuple[str, ...]
    encendida: bool | None = True
    """`None` = no tiene interruptor porque no le hace falta. `False` =
    lo tiene y esta apagado, o sea que esa frase HOY viaja al cerebro."""
    aviso: str = ""

    def a_json(self) -> dict:
        return {"frase": self.frase, "hace": self.hace,
                "canales": list(self.canales), "encendida": self.encendida,
                "aviso": self.aviso}


# >>> LAS FRASES SON LAS DE VERDAD DE CADA IDIOMA <<<
# Copiadas de `voz/idioma.py`, y el test las pasa por el interprete para
# que copiar no pueda salir mal. En ingles son deliberadamente raras: el
# idioma no distingue el imperativo, asi que "stop"/"close" a secas son
# ordenes normales y comerselas seria tragarse trabajo de verdad.
_TEXTOS = {
    "es": {
        "mostrar": ("abrete",
                    "Enseña la ventana de Jarvis si estaba en la bandeja."),
        "esconder": ("cierrate",
                     "Esconde la ventana. Jarvis sigue vivo y sigue "
                     "oyendote."),
        "apagar": ("apagate",
                   "Apaga Jarvis entero y cierra la sesion de Claude Code."),
        "apagar_aviso": "Corta antes el turno que este en marcha. NO mata lo "
                        "que Claude Code haya arrancado por ti -- un docker, "
                        "un servidor de desarrollo --: esos son tus procesos.",
        # El NOMBRE lo pone `_un_proyecto_tuyo`: sale de tu registro, o
        # es un hueco declarado si no tienes ninguno. Aqui estuvo
        # "faro" -- un proyecto del autor -- hasta que el usuario lo
        # vio: en una lista de palabras del programa, un nombre suyo se
        # lee como un comando.
        "proyecto": ("continua con el proyecto {}",
                     "Abre ese proyecto: mueve la sesion a su carpeta y le "
                     "manda tu frase de arranque. Valen tambien 've al', "
                     "'cambia al' y 'trabajemos en'."),
        "sin_proyectos": "el-que-tu-registres",
        "sin_ninguno": "TODAVIA NO TIENES NINGUNO: se añaden aqui abajo, en TUS PROYECTOS.",
        "proyecto_off": "Es la unica de la lista con interruptor, y nace "
                        "apagada: encenderla es aceptar que una frase tuya "
                        "deje de llegar al cerebro. Se enciende aqui mismo, "
                        "en TUS PROYECTOS.",
        "proyecto_on": "Si dices algo mas detras de la coma, eso manda y "
                       "sustituye a la frase de arranque.",
        "parar": ("para", "Corta lo que este haciendo AHORA y le calla la "
                          "voz."),
        "parar_aviso": "Escribiendo se usa la tecla Esc, que hace lo mismo. "
                       "La palabra no se intercepta escrita a proposito: "
                       "tecleada es una preposicion normal (“para el "
                       "servidor”) y comersela seria tragarse una orden "
                       "buena.",
        "cancelar": ("cancela",
                     "Lo mismo que 'para'. Tambien valen 'basta', 'dejalo', "
                     "'olvidalo', 'deten', 'aborta' y 'stop'."),
        "cancelar_aviso": "Estas se oyen en cualquier posicion de la frase. "
                          "Las dudosas -- 'para', 'no', 'espera', 'alto', "
                          "'quieto', 'ya' -- solo cuentan si abren una frase "
                          "corta, porque si no se llevarian por delante "
                          "ordenes normales.",
    },
    "en": {
        "mostrar": ("show yourself",
                    "Brings the Jarvis window back if it was in the tray."),
        "esconder": ("hide yourself",
                     "Hides the window. Jarvis stays alive and keeps "
                     "listening."),
        "apagar": ("shut yourself down",
                   "Shuts Jarvis down and closes the Claude Code session."),
        "apagar_aviso": "It stops whatever turn is running first. It does "
                        "NOT kill what Claude Code started for you -- a "
                        "docker, a dev server --: those are your processes.",
        # >>> DECIA "NOT AVAILABLE IN ENGLISH YET" Y DEJO DE SER CIERTO
        # <<< (2026-09-09.) Lo era: `voz/proyecto.py` tenia los patrones
        # compilados en español y con la voz en ingles la frase se iba
        # entera al cerebro -- que es justo lo que reporto el usuario
        # diciendo "Carry on with Project Faro" y viendo a Claude Code
        # buscar por el disco. Ese mismo dia los patrones se mudaron a
        # `voz.idioma.PROYECTO` y el ingles intercepta igual que el
        # español. La prosa se queda vieja sin avisar, y esta
        # se leia en la pantalla donde alguien decide si la frase le
        # sirve: peor que no decir nada.
        # >>> Y EL ORDEN DE LAS PALABRAS NO ES COSMETICO <<<
        # Decia "carry on with the {} project", que es la frase española
        # traducida palabra por palabra. Los patrones ingleses de
        # `voz.idioma.PROYECTO` capturan el nombre DETRAS de `project`
        # (`\bproject\b\s*(?P<nombre>.*)`), asi que con el nombre delante
        # la captura sale VACIA: no da error, da `SIN_NOMBRE` -- Jarvis
        # entiende que quieres cambiar y te pregunta a cual, con el
        # nombre dicho. Un ejemplo del glosario que hay que repreguntar
        # es un ejemplo malo, y encima el usuario ya dijo la buena:
        # "Carry on with Project Faro".
        "proyecto": ("carry on with project {}",
                     "Opens that project and moves the session to its "
                     "folder."),
        "sin_proyectos": "whichever-you-register",
        "sin_ninguno": "YOU HAVE NONE YET: you add them right below, under YOUR PROJECTS.",
        "proyecto_off": "It is the only one here with a switch, and it is "
                        "born off: turning it on means accepting that a "
                        "sentence of yours stops reaching the brain. You "
                        "turn it on right here, under YOUR PROJECTS.",
        "proyecto_on": "If you say anything after the comma, that wins and "
                       "replaces the opening sentence.",
        "parar": ("nevermind", "Stops whatever it is doing NOW and shuts "
                               "its voice up."),
        "parar_aviso": "When typing, use the Esc key, which does the same. "
                       "In English only “nevermind” is "
                       "unmistakable: the language does not mark the "
                       "imperative, so “stop the server” is a real "
                       "order and eating it would swallow real work.",
        "cancelar": ("stop", "Same as “nevermind”, but this one "
                             "only counts when it opens a short sentence."),
        "cancelar_aviso": "“stop”, “cancel” and "
                          "“abort” are ordinary orders in English, "
                          "so they only count inside a window of two words. "
                          "That 2 is reasoned, not measured: English has no "
                          "bank yet (JC-0018).",
    },
}


def _un_proyecto_tuyo(config_dir: Path | None, hueco: str) -> str:
    """El nombre para el ejemplo: uno TUYO, o un hueco que lo diga.

    >>> AQUI ESTUVO HARCODEADO UN PROYECTO DEL AUTOR <<<
    Y el usuario lo vio: en una lista donde "apagate" y "para" SI son
    palabras del programa, un nombre suyo se lee como una tercera. Quien
    instale esto de cero no tiene ese proyecto y se quedaria buscandolo.

    Sale del registro y se coge el PRIMERO: no hay forma de elegir "el
    mas representativo" sin inventarse un criterio, y el primero es el
    que el usuario ve arriba del todo en TUS PROYECTOS. Si el registro
    esta vacio -- que es como sale Jarvis recien instalado -- va un hueco
    que se lee como hueco, no un nombre de mentira que parezca real.
    """
    from nucleo.proyectos import ProyectosError, leer

    try:
        registrados = leer(config_dir)
    except ProyectosError:
        # Un registro roto ya lo grita quien lo lee de verdad. Aqui la
        # respuesta util es el hueco, no una excepcion en mitad de una
        # pantalla de ayuda.
        return hueco
    return registrados[0].alias if registrados else hueco


def glosario(config_dir: Path | None = None,
             idioma: str | None = None) -> tuple[Entrada, ...]:
    """Todo lo que Jarvis mira antes de mandarlo, con su estado de HOY.

    El estado se lee de verdad -- `intercepta()` mira el YAML -- porque
    una lista que enseñara "encendido" con el interruptor apagado seria
    peor que no tenerla: mandaria a alguien a probar una frase que hoy no
    hace nada.

    El idioma es el de la VOZ y no el de la pantalla, y eso importa: lo
    que se lista son las frases que hay que DECIR, y las reconoce el
    interprete del idioma hablado. Enseñar las inglesas con la voz en
    español seria un glosario de frases que no funcionan.
    """
    from nucleo.proyectos import intercepta
    from voz.idioma import hablado

    quien = idioma or hablado(config_dir)
    t = _TEXTOS[quien]
    con_proyectos = intercepta(config_dir)

    def par(clave):
        return t[clave]

    frase, hace = par("mostrar")
    mostrar = Entrada(frase, hace, ("voz", "consola"), encendida=None)
    frase, hace = par("esconder")
    esconder = Entrada(frase, hace, ("voz", "consola"), encendida=None)
    frase, hace = par("apagar")
    apagar = Entrada(frase, hace, ("voz", "consola"), encendida=None,
                     aviso=t["apagar_aviso"])
    frase, hace = par("proyecto")
    tuyo = _un_proyecto_tuyo(config_dir, t["sin_proyectos"])
    frase = frase.format(tuyo)
    # >>> SIN NINGUNO REGISTRADO SE DICE, Y NO SE FINGE UN EJEMPLO <<<
    # Es el estado de quien acaba de instalarlo. Enseñar la frase con un
    # hueco dentro y callarse dejaria a alguien probandola tal cual y
    # preguntandose por que no pasa nada -- no hay proyecto que abrir.
    if tuyo == t["sin_proyectos"]:
        hace = t["sin_ninguno"] + " " + hace
    # >>> LOS DOS CANALES EN LOS DOS IDIOMAS, DESDE EL 2026-09-09 <<<
    # Aqui habia un `if quien == "es"` triplicado que dejaba el ingles
    # con `canales=()` -- "todavia no, en este idioma" --, porque los
    # patrones estaban solo en español. Ya no: `voz.idioma.PROYECTO`
    # tiene los dos. La rama de "por ningun canal" se queda VIVA en
    # `ajustes.html` a proposito, porque es la tercera salida honesta
    # para el dia que se añada un idioma sin patrones; lo que no puede
    # es seguir disparandose para uno que si los tiene.
    proyecto = Entrada(
        frase, hace, ("voz", "consola"), encendida=con_proyectos,
        aviso=t["proyecto_on"] if con_proyectos else t["proyecto_off"])
    frase, hace = par("parar")
    parar = Entrada(frase, hace, ("voz",), encendida=None,
                    aviso=t["parar_aviso"])
    frase, hace = par("cancelar")
    cancelar = Entrada(frase, hace, ("voz",), encendida=None,
                       aviso=t["cancelar_aviso"])

    return (mostrar, esconder, apagar, proyecto, parar, cancelar)
