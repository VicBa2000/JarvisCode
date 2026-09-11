"""JC-0018: el idioma de la VOZ. Todo lo que Jarvis dice y escucha.

>>> ESTO NO ES `nucleo/textos.py`, Y LA DIFERENCIA ES EL PUNTO ENTERO <<<
Aquel traduce la pantalla y es un diccionario: cambiar el idioma de lo
que se LEE no tiene mas consecuencia que leerlo. Esto no se puede
resolver traduciendo, y la razon es que aqui hay cuatro cosas MEDIDAS
contra un corpus en español:

    el ancla de vocabulario   bajo el WER de 4,2 % a 2,4 % (2026-08-21)
    el lexico de parada       partido en inequivocas/ambiguas PORQUE
                              "para" es una preposicion del español
    la voz de Piper           5 en disco, las 5 españolas
    el umbral de sin_habla    va atado al ancla, y el ancla es de idioma

Cambiar de idioma invalida las cuatro. Las 30 ordenes de
`eval/audio_ordenes/` -- lo irreemplazable de este arbol, regrabado dos
veces -- estan en español y NO sirven para medir ingles. Un Jarvis en
ingles nace SIN BANCO, o sea sin aceptacion medida, y eso hay que decirlo en
vez de descubrirlo.

>>> EL HALLAZGO QUE NO ERA OBVIO: EN INGLES EL PELIGRO SE INVIERTE <<<
En español, "para" es una preposicion que aparece cada tres frases, y
por eso el lexico esta partido: las AMBIGUAS solo cuentan si ABREN una
frase corta (<= 4 palabras). "stop" era INEQUIVOCA, porque en español es
un extranjerismo que casi nadie suelta sin querer.

En ingles eso deja de ser verdad, y al reves de como parece:

    "stop the server"      es una ORDEN perfectamente normal
    "stop the container"   idem
    "cancel the build"     idem

O sea que la palabra mas obvia para parar es tambien el verbo con el que
se pide media docena de cosas legitimas mientras se trabaja. Asi que
"stop" NO puede ser inequivoca en ingles: pasa a ambigua, y ademas con
una ventana MAS CORTA que la del español -- 2 palabras y no 4 --, porque
"stop the server" son tres y con la ventana española se comeria la
orden.

>>> Y ESE 2 ES UN PUNTO DE PARTIDA, NO UNA MEDICION <<<
El 4 del español sale de las tres paradas del corpus real (1, 1 y 3
palabras). En ingles no hay corpus todavia, asi que el 2 esta RAZONADO y
no medido, y esta escrito aqui para que nadie lo cite como si lo
estuviera. Lo cierra `eval/parada_bench_en.py` cuando existan las
grabaciones.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

IDIOMAS = ("es", "en")


def hablado(config_dir: Path | None = None) -> str:
    """El idioma de la voz. `es` ante cualquier duda.

    >>> ES UN AJUSTE APARTE DEL DE LA PANTALLA, Y A PROPOSITO <<<
    `ui.idioma` cambia lo que se lee y es gratis. Este cambia lo que se
    oye y cuesta: hace falta una voz de Piper del idioma en disco, y la
    transcripcion pierde su ancla medida. Atarlos habria hecho que poner
    la pantalla en ingles -- barato, reversible -- se llevara por delante
    la voz sin avisar.
    """
    try:
        from nucleo.ajustes import valor_de

        elegido = str(valor_de("voz.idioma", "es", config_dir) or "es")
    except Exception:  # noqa: BLE001
        return "es"
    return elegido if elegido in IDIOMAS else "es"


# ----------------------------------------------------------------------
#  1. Lo que Jarvis DICE
# ----------------------------------------------------------------------
# Las claves son cortas y describen la SITUACION, no el texto: el dia que
# se retoque una frase, la clave sigue valiendo. Y el español es la
# fuente -- si falta una traduccion se locuta en español, que se oye, en
# vez de callarse, que no se distingue de un cuelgue.

FRASES: dict[str, dict[str, str]] = {
    # --- el microfono y el oido ---
    "perdi_microfono": {
        "es": "He perdido el microfono.",
        "en": "I've lost the microphone.",
    },
    "no_te_oi_bien": {
        "es": "No te he oido bien.",
        "en": "I didn't catch that.",
    },
    "no_te_oi_consola": {
        "es": "No te he oido. Contestame en la consola.",
        "en": "I didn't hear you. Answer me in the console.",
    },
    # --- la ventana ---
    "sin_ventana": {
        "es": "No tengo ventana: estoy corriendo desde una terminal.",
        "en": "I have no window: I'm running from a terminal.",
    },
    "no_pude_mover_ventana": {
        "es": "No he podido mover la ventana.",
        "en": "I couldn't move the window.",
    },
    "aqui_estoy": {"es": "Aqui estoy.", "en": "Here I am."},
    "no_puedo_apagarme": {
        "es": "No puedo apagarme solo: cierra la terminal.",
        "en": "I can't shut myself down: close the terminal.",
    },
    # Esta se dice ANTES de morir, y por eso existe: un apagado mudo y un
    # cuelgue se ven igual desde fuera.
    "hasta_luego": {
        "es": "Hasta luego. Me apago.",
        "en": "Goodbye. Shutting down.",
    },
    "no_pude_apagarme": {
        "es": "No he podido apagarme.",
        "en": "I couldn't shut down.",
    },
    # --- cambiar de proyecto (ADR-0029) ---
    "que_proyecto": {
        "es": "¿Que proyecto? Dimelo con su nombre.",
        "en": "Which project? Tell me its name.",
    },
    "proyectos_mal": {
        "es": "La lista de proyectos esta mal escrita. Miralo en los ajustes.",
        "en": "The project list is malformed. Take a look in the settings.",
    },
    "proyecto_desconocido": {
        "es": "No tengo ningun proyecto que se llame {}. Se añaden en "
              "los ajustes.",
        "en": "I have no project called {}. You add them in the settings.",
    },
    "proyectos_varios": {
        "es": "Tengo {} que se llaman asi: {}. Dime cual.",
        "en": "I have {} with that name: {}. Tell me which one.",
    },
    "proyecto_sin_carpeta": {
        "es": "{} esta registrado pero su carpeta ya no esta.",
        "en": "{} is registered but its folder is gone.",
    },
    "no_pude_cambiar_proyecto": {
        "es": "No he podido cambiar de proyecto.",
        "en": "I couldn't switch projects.",
    },
    # Dice el alias Y LA CARPETA: ahi vive el error caro de ADR-0029, dos
    # proyectos con el mismo nombre corto.
    "abro_proyecto": {"es": "Abro {}, en {}.", "en": "Opening {}, in {}."},
    "no_pude_abrir_sesion": {
        "es": "No he podido abrir la sesion.",
        "en": "I couldn't open the session.",
    },
    # --- el turno ---
    "vale": {"es": "Vale.", "en": "Okay."},
    "vale_paro": {"es": "Vale, paro.", "en": "Okay, stopping."},
    "autorizado": {"es": "Autorizado.", "en": "Authorised."},
    # El separador de las opciones de un `AskUserQuestion` dicho en alto.
    "o_bien": {"es": ", o ", "en": ", or "},
    "limite_agotado": {
        "es": "Se ha agotado el limite de uso.",
        "en": "The usage limit has run out.",
    },
    "sin_servidor": {
        "es": "No llego al servidor.",
        "en": "I can't reach the server.",
    },
    "problemas_servidor": {
        "es": "Estoy teniendo problemas para llegar al servidor.",
        "en": "I'm having trouble reaching the server.",
    },
    "turno_mal": {
        "es": "El turno no ha terminado bien. Esta en la consola.",
        "en": "The turn didn't finish properly. It's in the console.",
    },
    "resto_en_consola": {
        "es": "El resto esta en la consola.",
        "en": "The rest is in the console.",
    },
    # --- lo que dejo detras (2026-09-01) ---
    # >>> SE DICE EL NOMBRE Y NO LA RUTA, Y ESO ESTA MEDIDO ANTES <<<
    # Una ruta leida en alto no se entiende: es la misma razon por la que
    # `voz/narracion.py` las deja fuera del filtro. El nombre del archivo
    # SI se entiende, y ademas es lo que el usuario va a buscar.
    "te_deje_uno": {
        "es": "Te he dejado {0} en el panel.",
        "en": "I left you {0} in the panel.",
    },
    "te_deje_varios": {
        "es": "Te he dejado {0} cosas en el panel, entre ellas {1}.",
        "en": "I left you {0} things in the panel, {1} among them.",
    },
    "te_deje_una_imagen": {
        "es": "Te he dejado una vista en el panel.",
        "en": "I left you a view in the panel.",
    },
    # --- preguntas y permisos ---
    "te_pregunta": {
        "es": "Te esta preguntando algo. Contestale en la consola.",
        "en": "It's asking you something. Answer it in the console.",
    },
    "puedes_decir": {"es": "Puedes decir: ", "en": "You can say: "},
    "necesito_permiso": {
        "es": "Necesito permiso para algo. Miralo en la consola.",
        "en": "I need permission for something. Take a look in the console.",
    },
    "pendiente_consola": {
        "es": "Te lo dejo pendiente en la consola.",
        "en": "I'll leave it pending in the console.",
    },
    "usuario_dijo_no": {
        "es": "El usuario dijo que no.",
        "en": "The user said no.",
    },
    "no_autorizo": {"es": "No lo autorizo.", "en": "I'm not authorising it."},
    # --- la peticion hablada de permiso (JC-0002) ---
    # >>> ESTA ES LA MAS DELICADA DE TODO EL ARCHIVO <<< Es donde el
    # usuario CONSIENTE. Se traduce conservando las tres cosas que la
    # hacen valida: dice QUE se va a hacer, dice CUANTOS y CUALES, y
    # termina ofreciendo las dos respuestas en alto. Una traduccion mas
    # corta o mas elegante que se coma cualquiera de las tres degrada el
    # consentimiento a un "si" reflejo.
    "permiso.en_carpeta": {"es": "{}, en {}", "en": "{}, in {}"},
    "permiso.es_uno": {"es": "Es uno: {}", "en": "It's one: {}"},
    "permiso.y_mas": {"es": " y {}", "en": " and {}"},
    "permiso.son_n": {"es": "Son {}: {}", "en": "There are {}: {}"},
    "permiso.son_n_entre": {
        "es": "Son {}, entre ellos {}",
        "en": "There are {}, among them {}",
    },
    "permiso.quiere_hacer": {
        "es": "Quiere hacer algo que {}",
        "en": "It wants to do something that {}",
    },
    "permiso.quiere_usar": {"es": "Quiere usar {}", "en": "It wants to use {}"},
    "permiso.la_orden_es": {
        "es": "La orden es: {}",
        "en": "The command is: {}",
    },
    "permiso.lo_autorizo": {
        "es": "¿Lo autorizo? Contesta si o no",
        "en": "Shall I allow it? Answer yes or no",
    },
    # --- el resumen (JC-0004) ---
    "resumen.te_lo_deje": {
        "es": "Te lo he dejado en la consola.",
        "en": "I've left it for you in the console.",
    },
    "resumen.codigo_en_consola": {
        "es": " El codigo esta en la consola.",
        "en": " The code is in the console.",
    },
    # Una lista NO se resume como un texto: se dice la entradilla, cuantos
    # puntos hay y el primero. Ver JC-0004.
    "resumen.son_n_puntos": {
        "es": "Son {} puntos",
        "en": "There are {} points",
    },
    "resumen.el_primero": {
        "es": ". El primero: {}.",
        "en": ". The first: {}.",
    },
    # --- el consejo del ciclo (JC-0011) ---
    "consejo_ruido": {
        "es": "Cuando me llames, baja el ruido lo que puedas. Con musica "
              "suelo oirte; tecleando, menos de la mitad de las veces.",
        "en": "When you call me, keep the noise down as much as you can. "
              "With music I usually hear you; while you type, less than "
              "half the time.",
    },
}


def frase(clave: str, *args: object, idioma: str | None = None,
          config_dir: Path | None = None) -> str:
    """Lo que hay que decir, en el idioma de la voz.

    >>> UNA CLAVE QUE FALTE SE DICE EN ESPAÑOL, NO SE CALLA <<<
    Es la misma eleccion que en la pantalla y por el mismo motivo: media
    frase en español se oye y se corrige; un silencio es indistinguible
    de un cuelgue, que es el modo de fallo que este proyecto lleva desde
    el principio intentando no tener.
    """
    cual = idioma or hablado(config_dir)
    formas = FRASES.get(clave)
    if formas is None:
        raise KeyError(f"no hay frase '{clave}'")
    texto = formas.get(cual) or formas["es"]
    return texto.format(*args) if args else texto


# ----------------------------------------------------------------------
#  2. Lo que Jarvis ESCUCHA
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class LexicoDeParada:
    """Las palabras con las que se le manda callar, y su ventana.

    `palabras_max` no es un detalle de implementacion: es LA decision.
    Dice cuantas palabras puede tener una frase para que una palabra
    ambigua que la abre cuente como parada, y cambia de idioma porque
    cambia lo que la gente dice de verdad.
    """

    inequivocas: frozenset[str]
    ambiguas: frozenset[str]
    palabras_max: int
    medido: bool
    """Si el numero de arriba sale de un corpus o esta razonado.

    Existe para que no se pueda citar como medido lo que no lo esta. En
    español es True -- tres paradas reales de 1, 1 y 3
    palabras --; en ingles es False hasta que haya grabaciones.
    """


PARADA: dict[str, LexicoDeParada] = {
    "es": LexicoDeParada(
        # Se dicen solas y nadie las suelta sin querer, asi que valen en
        # cualquier posicion de la frase.
        inequivocas=frozenset({
            "cancela", "cancelalo", "cancelala", "cancelar", "cancelo",
            "detente", "deten", "detenlo",
            "basta", "stop", "aborta", "abortar",
            "olvidalo", "dejalo", "parate",
        }),
        # Palabras corrientes del español que TAMBIEN son paradas.
        ambiguas=frozenset({"para", "no", "alto", "espera", "quieto", "ya"}),
        # Las tres paradas del corpus miden 1, 1 y 3 palabras.
        palabras_max=4,
        medido=True,
    ),
    "en": LexicoDeParada(
        # >>> EN INGLES CASI NADA ES INEQUIVOCO, Y ESTO LO DESTAPO UN
        # TEST QUE YO MISMO ESCRIBI PARA OTRA COSA <<<
        # La primera version de esta lista dejaba "cancel" y "abort" como
        # inequivocas, con el mismo razonamiento con el que se saco
        # "stop". Y el test de ordenes de trabajo lo tumbo al instante:
        #
        #     "cancel the deployment"   -> paraba el turno
        #     "cancel the build"        -> idem
        #     "abort the migration"     -> idem
        #
        # O sea que el hallazgo era mas grande de lo que parecia: en
        # ingles, TODOS los verbos de parar son tambien verbos de pedir
        # cosas, porque el ingles no distingue el imperativo. En español
        # "cancela" es inequivocamente una orden a Jarvis; "cancel" puede
        # ser el principio de cualquier cosa.
        #
        # Queda UNA sola, y es la que no es un verbo: "nevermind" escrito
        # junto. No existe forma de empezar con eso una orden de trabajo.
        inequivocas=frozenset({"nevermind"}),
        # Todo lo demas pasa por la ventana corta: "stop" y "stop it"
        # paran, "stop the server" no.
        ambiguas=frozenset({
            "stop", "cancel", "abort", "halt", "quit", "scrap",
            "no", "wait", "hold", "enough", "quiet",
            # Para "never mind" y "forget it", que se dicen en dos
            # palabras y caben justo en la ventana.
            "never", "forget",
        }),
        # >>> RAZONADO, NO MEDIDO. Ver `medido`. <<<
        # 2 y no 4 porque "stop the server" son tres palabras: con la
        # ventana del español se comeria la orden. Lo cierra el banco
        # cuando existan las grabaciones en ingles.
        palabras_max=2,
        medido=False,
    ),
}


def lexico_de_parada(idioma: str | None = None,
                     config_dir: Path | None = None) -> LexicoDeParada:
    return PARADA[idioma or hablado(config_dir)]


# --- las ordenes de ventana -------------------------------------------
# La regla del español vale igual: reflexivas, que no significan nada mas
# y que no hay forma de decirle a Claude Code sobre un archivo. En ingles
# no hay reflexivos, asi que se usa la forma mas corta que NO es una
# orden de trabajo plausible: "show yourself" / "hide yourself" /
# "shut yourself down". Suenan raras a proposito -- esa rareza es lo que
# impide que se digan sin querer trabajando sobre codigo.
VENTANA: dict[str, dict[str, tuple[str, ...]]] = {
    "es": {
        "mostrar": (r"\babrete\b",),
        "esconder": (r"\bcierrate\b",),
        "apagar": (r"\bapagate\b",),
    },
    "en": {
        "mostrar": (r"\bshow yourself\b",),
        "esconder": (r"\bhide yourself\b",),
        # Tres palabras y no "shut down": "shut down the container" es una
        # orden que se dice de verdad. El "yourself" es lo que la hace
        # inconfundible, y esta es la que mata el asistente.
        "apagar": (r"\bshut yourself down\b",),
    },
}


def formas_de_ventana(idioma: str | None = None,
                      config_dir: Path | None = None) -> dict[str, tuple[str, ...]]:
    return VENTANA[idioma or hablado(config_dir)]


# --- el ritual de ADR-0029 --------------------------------------------
# >>> ES EL SUELO, NO LA UNICA (2026-09-05) <<<
# Hasta ese dia esta era LA frase, y su ser fija era parte del argumento
# de ADR-0029. Ahora la escribe el usuario (`proyectos.ritual` en el
# panel, o `ritual:` por proyecto), y esto es lo que se manda si no ha
# dicho nada -- que sigue siendo el caso de casi todo el mundo. Quien
# resuelve las tres fuentes es `voz.proyecto.primera_pregunta`; aqui NO
# se mira el ajuste, para que este modulo siga siendo el diccionario por
# idioma y nada mas.
RITUAL = {
    "es": "hola, en que nos quedamos?",
    "en": "hi, where did we leave off?",
}


def ritual(idioma: str | None = None, config_dir: Path | None = None) -> str:
    """La frase de FABRICA con la que Jarvis abre un proyecto.

    La de fabrica SI tiene una por idioma; la del usuario es una sola
    cadena y pisa a las dos (decision suya, 2026-09-05).
    """
    return RITUAL[idioma or hablado(config_dir)]


# --- como se pide cambiar de proyecto (ADR-0029) -----------------------
# >>> ESTO ESTABA CLAVADO EN ESPAÑOL Y LO REPORTO EL USUARIO <<<
# (2026-09-09, usandolo en ingles.) Dijo *"Carry on with Project Faro"*,
# el STT lo transcribio PERFECTO, y no paso nada: la sesion se quedo en
# la carpeta base y Claude Code se puso a mirar el disco a ver que era
# eso. Los patrones vivian en `voz/proyecto.py` y pedian un verbo español
# mas la palabra "proyecto", asi que en ingles no casaba ninguno.
# Es el peor fallo que puede tener esta capa y ya esta escrito en su
# cabecera: **una orden dictada que desaparece sin dejar rastro** -- no
# hay error, no hay linea en el log, y Jarvis contesta algo razonable a
# otra pregunta. La misma forma del 2026-09-03, cuando la consola no
# interceptaba y la voz si.
#
# SE PIDE UN VERBO **Y** LA PALABRA "PROYECTO" en los dos idiomas, y por
# el mismo motivo: sin ella, "continua con el informe" -- o "carry on
# with the report" -- se interceptaria como un cambio de carpeta y nunca
# llegaria al cerebro.


@dataclass(frozen=True)
class FormasDeProyecto:
    """Como se pide un cambio de proyecto, y donde acaba el nombre.

    Las tres van JUNTAS porque las tres leen la misma frase: separarlas
    permitiria formas inglesas cortando por conectores españoles, que no
    da error -- deja el nombre con media orden pegada detras.
    """

    formas: tuple[re.Pattern[str], ...]
    colgantes: re.Pattern[str]
    """Lo que sobra por delante del nombre una vez cortada la forma."""
    conector: re.Pattern[str]
    """Donde acaba el nombre y empieza lo que ADEMAS se pidio."""


PROYECTO: dict[str, FormasDeProyecto] = {
    "es": FormasDeProyecto(
        formas=(
            re.compile(r"\b(?:continua|continuemos|sigue|seguimos)\b"
                       r"[^.]*?\bproyecto\b\s*(?P<nombre>.*)", re.I),
            # `ve(?:te)?\s+al?` y no `ve\s+a`: se dice "ve AL proyecto", y
            # con `\ba\b` el "al" no casaba. Lo encontro un test.
            re.compile(r"\b(?:abre|abrime|abreme|entra\s+en|ve(?:te)?\s+al?)\b"
                       r"[^.]*?\bproyecto\b\s*(?P<nombre>.*)", re.I),
            re.compile(r"\b(?:cambia|cambiate|pasa|pasate|muevete)\b"
                       r"[^.]*?\bproyecto\b\s*(?P<nombre>.*)", re.I),
            re.compile(r"\b(?:trabaja|trabajemos|ponte)\b"
                       r"[^.]*?\bproyecto\b\s*(?P<nombre>.*)", re.I),
        ),
        colgantes=re.compile(r"^(?:de|del|el|la|en|con|al|a|los|las)\b\s*", re.I),
        conector=re.compile(r"\s+\b(?:y|luego|despues|para|que)\b\s+", re.I),
    ),
    "en": FormasDeProyecto(
        formas=(
            # "carry on with project X" es la que dijo el usuario, y va
            # primera porque es la que mas se dice.
            re.compile(r"\b(?:carry\s+on|continue|keep\s+going|resume)\b"
                       r"[^.]*?\bproject\b\s*(?P<nombre>.*)", re.I),
            re.compile(r"\b(?:open|go\s+to|switch\s+to|move\s+to|jump\s+to)\b"
                       r"[^.]*?\bproject\b\s*(?P<nombre>.*)", re.I),
            re.compile(r"\b(?:work\s+on|start\s+on|let\'?s\s+work\s+on)\b"
                       r"[^.]*?\bproject\b\s*(?P<nombre>.*)", re.I),
        ),
        colgantes=re.compile(r"^(?:the|on|with|to|in|at|a|an|of|my|our)\b\s*", re.I),
        # >>> MAS CORTA QUE LA ESPAÑOLA, Y A PROPOSITO <<<
        # La española corta tambien en "para" y "que", que en ingles
        # serian "to" y "that" -- y las dos aparecen DENTRO de nombres y
        # de ordenes normales mucho mas que sus equivalentes españolas
        # ("go to project X to review it" cortaria bien, pero "the report
        # that is there" ya se comio una frase entera el 2026-09-03).
        # Con menos conectores el nombre se puede quedar largo, y de eso
        # se encarga el corte por PUNTUACION, que es mas fiable y no
        # depende del idioma.
        conector=re.compile(r"\s+\b(?:and|then|afterwards)\b\s+", re.I),
    ),
}


def formas_de_proyecto(idioma: str | None = None,
                       config_dir: Path | None = None) -> FormasDeProyecto:
    return PROYECTO[idioma or hablado(config_dir)]


# --- el ancla de vocabulario del STT ----------------------------------
# >>> LA DEL ESPAÑOL ESTA MEDIDA; LA DEL INGLES NO <<<
# La española bajo el WER de 4,2 % a 2,4 % contra las 30 ordenes reales.
# La inglesa es la MISMA IDEA -- las palabras que este usuario dice a
# menudo -- traducida, y no tiene banco detras. Se deja porque el ancla
# vacia tampoco es neutra (mueve el umbral de `sin_habla`, ver
# `voz/stt.py`), pero no se puede citar como medida.
ANCLA = {
    "es": ("bloc de notas, Descargas, Documentos, Imagenes, Escritorio, "
           "papelera, captura, informe, factura, carpeta, archivo, "
           "navegador, calculadora, explorador, git status, pip list, PDF"),
    "en": ("Notepad, Downloads, Documents, Pictures, Desktop, "
           "recycle bin, screenshot, report, invoice, folder, file, "
           "browser, calculator, explorer, git status, pip list, PDF"),
}


def ancla(idioma: str | None = None, config_dir: Path | None = None) -> str:
    return ANCLA[idioma or hablado(config_dir)]


# --- las voces de Piper -----------------------------------------------
# Lo que se BUSCA en `modelos/piper/` para cada idioma. No es una
# promesa: si no esta descargada, `voz/perfil.py` lo dice y no arranca la
# voz. Ver `-m voz.descargar_voz`.
VOCES = {
    "es": ("es_ES-davefx-medium", "es_MX-claude-high", "es_ES-sharvard-medium"),
    "en": ("en_US-lessac-medium", "en_GB-alba-medium", "en_US-amy-medium"),
}


def voces_del_idioma(idioma: str | None = None,
                     config_dir: Path | None = None) -> tuple[str, ...]:
    return VOCES[idioma or hablado(config_dir)]


# --- si o no, dicho en alto -------------------------------------------
# >>> AQUI NO HAY LISTA, Y ES DELIBERADO <<<
# La primera version de este archivo traia un `SI_Y_NO` por idioma. Se
# quito el mismo dia: la unica autoridad sobre "que cuenta como un si"
# es `seguridad/aprobacion.py`, y `voz/permiso.py` ya avisa por escrito
# de por que --
#
#     "dos listas de 'que significa si' en dos archivos acaban
#      divergiendo, y esa divergencia se paga en aprobaciones"
#
# -- o sea que poner la segunda aqui habria sido cometer, a mano, el
# error del que el codigo advierte tres lineas mas arriba. Las
# afirmativas inglesas viven ALLI, y son las mismas seis que las
# españolas: una por una, sin ensanchar la lista. Ensancharla es
# inventar deteccion de afirmativas en el unico sitio donde equivocarse
# EJECUTA algo irreversible.
