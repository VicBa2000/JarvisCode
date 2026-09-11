"""El idioma de la PANTALLA. Español de serie, ingles si se pide.

>>> LO PRIMERO, PARA QUE NADIE SE LLEVE LA SORPRESA <<<
Esto traduce lo que se LEE. Lo que Jarvis HABLA -- y lo que entiende
cuando le hablas -- no vive aqui: es JC-0018, y es otra cosa entera
porque no se resuelve traduciendo. La voz de Piper, el ancla de
vocabulario del STT y el lexico de parada estan MEDIDOS contra un corpus
en español; cambiarlos de idioma es rehacer esas mediciones, no cambiar
unas cadenas. El ajuste de la UI lo dice con esas palabras: si dijera
"Idioma" a secas, alguien lo pondria en ingles y se encontraria a Jarvis
contestandole en español sin entender por que.

>>> SE TRADUCE EL ARCHIVO QUE SE SIRVE, NO EL DOM <<<
La alternativa obvia era marcar cada nodo con un `data-t` y recorrerlos
con JS al cargar. Se descarto por dos cosas que se ven:

  1. la pagina llegaria en español y se repintaria en ingles medio
     fotograma despues, en cada apertura de la ventana;
  2. dejaria fuera la mitad del texto. Buena parte de lo que se lee no
     esta en el HTML: lo construye el JS al vuelo ("Guardado y
     aplicado.", "no se pudo guardar: "...). Un recorrido del DOM al
     cargar no ve nada de eso, y un recorrido permanente seria vigilar
     la pagina entera para traducir doce frases.

Traduciendo el TEXTO del archivo antes de mandarlo, las dos clases caen
en el mismo sitio: el parrafo del HTML y el literal del JS son, aqui,
dos cadenas iguales.

>>> Y SE SUSTITUYE SOLO EN DOS POSICIONES, NUNCA A LO BRUTO <<<
Un `replace` suelto sobre el archivo entero podria cambiar un trozo de
codigo: hay claves cortas ("VOZ", "ESTADO", "MODO") que tambien son
pedazos de nombres. Se sustituye unicamente:

    >texto<      un nodo de texto del HTML
    "texto"      un literal de JS o el valor de un atributo
    'texto'      idem

o sea en los sitios donde una cadena ES texto y no puede ser un
identificador. Los espacios del HTML se tratan como uno solo, porque un
parrafo escrito en cuatro lineas indentadas es UNA frase.

>>> UNA CLAVE SIN TRADUCIR SE QUEDA EN ESPAÑOL, Y SE VE <<<
No hay marcador de "falta esto": lo que no este en el diccionario se
sirve tal cual. Es la salida honesta -- media pantalla en ingles y media
en español se nota al primer vistazo --, y `tests/test_ui_idioma.py`
cuenta cuanto queda para que la deuda no crezca en silencio.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

IDIOMAS = ("es", "en")
"""Los que hay. `es` es el de serie y NO tiene diccionario: la copia
original vive en las paginas, que es donde se escribe y se corrige."""


# ----------------------------------------------------------------------
#  1. La copia de las dos paginas
# ----------------------------------------------------------------------
# Las claves se SACARON DE LOS ARCHIVOS, no se copiaron a mano: llevan
# comillas tipograficas, entidades (`&mdash;`) y saltos de linea dentro
# de un parrafo, y una sola diferencia invisible deja una traduccion que
# no casa nunca -- y que ademas no da error.

PAGINAS_EN: dict[str, str] = {
    # --- la consola: cabecera y paneles ---
    "CONSOLA": "CONSOLE",
    "AJUSTES": "SETTINGS",
    "conectando": "connecting",
    "MIC": "MIC",
    "PALABRA": "WAKE WORD",
    "SALIDA": "OUTPUT",
    "MODO": "MODE",
    "ESTADO —/06": "STATE —/06",
    "ESTADO ": "STATE ",
    "SIN VOZ": "NO VOICE",
    "arranca con --voz": "start it with --voz",
    "TURNOS": "TURNS",
    "PARADAS": "STOPS",
    "PERMISOS": "PERMISSIONS",
    "SIN CONTESTAR": "UNANSWERED",
    "REGISTRO DE TRANSMISION": "TRANSMISSION LOG",
    "EJECUTAR": "RUN",
    "CANALES": "CHANNELS",
    # El panel de lo que la sesion produjo (2026-09-01). "TE DEJO" en
    # segunda persona a proposito: el rotulo dice a QUIEN le habla, que
    # es lo que lo separa de un registro tecnico mas.
    "TE DEJO": "LEFT FOR YOU",
    "VER LO QUE TE DEJO": "SHOW WHAT IT LEFT YOU",
    "OCULTAR": "HIDE",
    # Plegar PERIMETRO y CARGA, y el aviso de que el visor no esta
    # ensenando el final (2026-09-03).
    "MOSTRAR": "SHOW",
    "MIRANDO ATRAS": "LOOKING BACK",
    "esto no se pinta aqui": "this cannot be shown here",
    # El cabezal de la tira (v3, 2026-09-02). `EN DIRECTO` alterna con
    # `TE DEJO` en el MISMO rotulo: cuando hay turno el bloque es una
    # transmision y cuando no, es lo que te dejo. Las dos son ciertas y
    # el cambio en si ya dice que hay algo pasando.
    "EN DIRECTO": "ON AIR",
    # >>> ESTE VA ENTERO, CON SU HUECO DENTRO <<< En ingles el orden se
    # invierte ("4 min ago"), asi que traducir un "hace " suelto dejaria
    # "ago 4 min" -- y no lo veria ningun test, porque la cadena se
    # arma en el navegador. La pagina hace `.replace("%s", ...)`.
    "hace %s": "%s ago",
    "se solto para hacer sitio": "dropped to make room",
    # El POV (2026-09-02). Los rotulos de que esta haciendo. OJO: lo que
    # se traduce es el ROTULO, no la palabra que manda el servidor --
    # `escribiendo` se COMPARA en la pagina para decidir el cursor, y una
    # cadena que se compara no se traduce nunca.
    "POV": "POV",
    "VER LO QUE HACE": "SHOW WHAT IT IS DOING",
    "ESCRIBIENDO": "WRITING",
    "LEYENDO": "READING",
    "EJECUTANDO": "RUNNING",
    "BUSCANDO": "SEARCHING",
    "PENSANDO": "THINKING",
    "DICIENDO": "SAYING",
    "MIRANDO": "LOOKING",
    "DELEGANDO": "DELEGATING",
    "PLANEANDO": "PLANNING",
    "USANDO": "USING",
    # Y el pie, que es donde vive la honestidad del visor.
    "NO SE HIZO": "IT DID NOT HAPPEN",
    "la imagen esta abajo": "the picture is below",
    "llego de golpe": "arrived all at once",
    "en pausa": "paused",
    "en vivo": "live",
    # El resumen de una herramienta en el registro (2026-09-02). Va
    # entero con su hueco, por lo mismo que "hace %s": la cifra la pone
    # el navegador y en ingles la unidad cambia de sitio o de palabra.
    "%s car": "%s chars",
    # La parada manual desde la consola (2026-09-01). Se rotula porque
    # una tecla sin rotulo es lo mismo que la tercera salida de la puerta
    # antes del 29: existia y nadie la usaba.
    "· ESC PARA PARAR": "· ESC TO STOP",
    "todavia nada": "nothing yet",
    "ABRIR FUERA": "OPEN OUTSIDE",
    "CERRAR": "CLOSE",
    "esto no se pinta aqui; abrelo fuera":
        "this cannot be shown here; open it outside",
    "ya no esta en disco": "no longer on disk",
    "no se pudo leer: ": "could not read it: ",
    "EN USO": "IN USE",
    "VOZ": "VOICE",
    "APAGADA": "OFF",
    "TELEGRAM": "TELEGRAM",
    "SIN PONER": "NOT SET",
    # --- los servidores MCP (2026-09-07) ---
    # "LISTO" ya estaba (de los botones de ajustes) y "SERVIDORES MCP"
    # tambien, del panel de la lista blanca: el rail reusa esa etiqueta a
    # proposito -- es el mismo asunto -- y con ella hereda gratis la
    # copia del tema `despacho` ("Programas conectados").
    "CAIDO": "DOWN",
    "CAIDOS": "DOWN",
    "SIN ENTRAR": "NEEDS LOGIN",
    "SIN ESTADO": "NO STATE",
    "PERIMETRO": "PERIMETER",
    "ZONAS SELLADAS": "SEALED ZONES",
    "ESTADO": "STATE",
    "CARGA": "LOAD",
    "CUOTA": "QUOTA",
    # Los dos relojes de cuota (2026-09-03). Van en la direccion en que se
    # preguntan y por eso NO son la misma palabra: de la sesion interesa
    # lo que queda, de la semana lo que ya se gasto.
    "SESION GASTADA": "SESSION USED",
    "SEMANA GASTADA": "WEEK USED",
    "ya se reinicio, sin dato hasta el proximo turno":
        "already reset, no figure until the next turn",
    "SESION": "SESSION",
    "SEMANA": "WEEK",
    "VENTANAS UTILES": "USEFUL WINDOWS",
    "LE DIJISTE": "YOU SAID",
    # --- LA COPIA DE `despacho` (ver PANTALLA_DESPACHO mas abajo).
    # Tiene que estar aqui o ese tema se queda a medio traducir: la capa
    # del tema corre ANTES que esta, asi que para cuando llega el ingles
    # el rotulo ya no dice "PERIMETRO" sino "Lo que no puede tocar", y la
    # clave vieja no casa con nada. No daria error -- se serviria en
    # español -- que es justo el fallo mudo que hay que evitar.
    "Lo que no puede tocar": "What it cannot touch",
    "carpetas protegidas": "protected folders",
    "Cuanto lleva gastado": "How much it has used",
    "Ratos utiles que quedan": "Useful stretches left",
    "Como te avisa": "How it reaches you",
    "Lo que Jarvis ha hecho": "What Jarvis has done",
    "Tus carpetas de trabajo": "Your work folders",
    "Avisarme al movil": "Text me on my phone",
    "Programas conectados": "Connected programs",
    "Lo que te ha dejado": "What it left for you",
    # --- Lo nuevo de la puerta (2026-08-29), en los cuatro temas.
    "Ver detalle tecnico": "See technical detail",
    "La instruccion exacta que va a ejecutar": "The exact instruction it will run",
    "Se ejecuta ahora mismo": "It runs right now",
    "No se hace, y el turno sigue": "It is not done, and the turn goes on",
    "Queda pendiente, y te aviso al movil": "It stays pending, and I text your phone",
    # --- ATRIBUTOS. Se leen igual que un parrafo y no estaban en la
    # extraccion original: `title` sale al pasar el raton y
    # `placeholder` esta escrito DENTRO de la caja de texto, o sea es lo
    # primero que se lee al ir a escribir. ---
    "ver las zonas": "see the zones",
    "introduce una orden, o dila en voz alta":
        "type an order, or say it out loud",
    "como lo llamas": "what you call it",
    "nombre del servidor": "server name",
    # Un salto de linea DENTRO de un literal de JS: la clave lleva la
    # barra invertida tal cual esta en el archivo, no el salto de verdad.
    "PUEDE MIRAR,\\nNO CAMBIAR": "CAN LOOK,\\nNOT CHANGE",
    "SUELO ..... ": "FLOOR ..... ",
    "SESION .... ": "SESSION .. ",
    "CORE ...... ": "CORE ...... ",
    "sin abrir": "not open",
    "SIN SUELO": "NO FLOOR",
    "suelo ": "floor ",
    " zonas)": " zones)",
    "semanal ": "weekly ",
    "sesion ": "session ",
    # --- la consola: la puerta y las preguntas (JC-0002) ---
    # Se traduce con el MISMO cuidado que el original: dice QUE se pide y
    # deja "No contestar ahora" como una salida de verdad, porque callarse
    # no es decir que no.
    "Claude te pregunta": "Claude is asking you",
    "Pide permiso para ": "Asking permission to ",
    "No contestar ahora": "Don't answer now",
    "El usuario dijo que no.": "The user said no.",
    "Esa peticion ya la habia contestado otro canal.":
        "Another channel had already answered that request.",
    # --- la consola: el flujo ---
    "linea ": "line ",
    "Sesion abierta en ": "Session open in ",
    " con ": " with ",
    "Turno nuevo en la misma sesion": "New turn in the same session",
    "jarvis (al abrir)": "jarvis (on opening)",
    "tu (": "you (",
    "permitido solo": "allowed on its own",
    "sin servidor": "no server",
    "Reintento ": "Retry ",
    " de ": " of ",
    "; espera ": "; waiting ",
    "De sesion": "Session cap",
    " al ": " at ",
    "turno fallido": "turn failed",
    "arranque abortado": "startup aborted",
    # El aviso del arranque y lo que pasa al mandar un turno
    # (2026-09-03). Ver `Consola.avisa` y `manda()`.
    "arranque": "starting up",
    "MANDANDO…": "SENDING…",
    "no se mando": "not sent",
    "el servidor lo rechazo": "the server refused it",
    "no se pudo hablar con Jarvis: ": "could not reach Jarvis: ",
    "sesion caida": "session down",
    "Termino con codigo ": "Exited with code ",
    "; se perdieron ": "; lost ",
    " peticiones sin contestar.": " unanswered requests.",
    "en marcha": "working",
    # El estado en que arranca Jarvis siempre, y que hasta el 2026-09-09
    # se pintaba como "caida". Ver `Sesion.en_reposo`.
    "en reposo · se abre al primer turno": "idle · opens on your first order",
    "te espera": "waiting for you",
    "callada, no se si piensa o no llega":
        "silent, can't tell if it's thinking or not answering",
    " s en silencio)": " s of silence)",
    " USD": " USD",
    "Ajustes de Jarvis": "Jarvis settings",
    "ver las carpetas protegidas, en Ajustes":
        "see the protected folders, under Settings",
    # --- LOS BOTONES DE LA PUERTA. Son la accion, no un rotulo ---
    # Se escaparon del primer barrido igual que los estados, y son peores:
    # "Permitir" y "Denegar" es lo que el usuario PULSA para consentir.
    "Permitir": "Allow",
    "Denegar": "Deny",
    "Permitido": "Allowed",
    "Denegado": "Denied",
    # >>> LA SEGUNDA TANDA, Y LA ENCONTRO EL USUARIO MIRANDO (2026-09-09)
    # <<< Con todo puesto en ingles seguian saliendo en español la
    # cabecera entera ("CUOTA·", "COSTE·", "SIN FRENO", "floor listo"),
    # los rotulos de cada orden del glosario ("dicha y escrita", "solo
    # dicha") y **los interruptores, que decian SI y NO**. Lo que vio:
    # una pagina de ajustes en ingles llena de opciones que contestaban
    # "SI" o "NO".
    #
    # POR QUE EL TEST DE COBERTURA NO LAS VEIA, que es lo que hay que
    # arreglar de verdad: `test_no_queda_espanol_en_la_pagina_servida`
    # **quita los bloques `<script>` antes de mirar** -- asi que no
    # comprueba ni un literal de JS, que es justo donde viven los
    # rotulos -- y ademas busca por una LISTA DE PALABRAS españolas en
    # la que no estaban "cuota", "coste", "freno" ni "dicha". Una red
    # que pesca solo lo que ya conoce da un 99 % perfectamente creible.
    # Se sustituye por una que compara la pagina `es` con la `en` y
    # enseña lo que NO cambio, que no depende de saberse el idioma.
    "CUOTA&middot;": "QUOTA&middot;",
    "COSTE&middot;": "COST&middot;",
    "SIN FRENO": "NO BRAKES",
    "puerta puesta": "gate on",
    # El estado del suelo, que llega del servidor como dato y se pinta
    # por tabla (`ESTADO_DEL_SUELO`). Las claves son el dato y no se
    # tocan; esto son los valores, que si son texto.
    "en pie": "up",
    "sin verificar": "unverified",
    "inseguro": "unsafe",
    # `sin_suelo` entro en la tabla el 2026-09-09: el rail y el pie
    # tecnico se pegaban el estado CRUDO, y en la captura inglesa se leia
    # "NO FLOOR" en la cabecera y "SIN_SUELO" en el modulo PERIMETER de
    # la misma pantalla. La cabecera tiene ademas su propio literal
    # ("SIN SUELO", en mayusculas, arriba en este mismo diccionario)
    # porque alli no lleva el recuento de zonas detras.
    "sin suelo": "no floor",
    # Los interruptores. Solo aparecen en `ajustes.html` y solo como
    # texto de un ternario, comprobado uno por uno: no hay ningun
    # identificador que se llame asi.
    "SI": "YES",
    # Los rotulos de canal del glosario (`ajustes.html`). Son texto
    # puro; `"resultado mal"` e `"insignia apagado"`, que salen al lado
    # en la misma sonda, son NOMBRES DE CLASE y por eso no estan aqui:
    # traducirlos habria dejado el estilo sin aplicar.
    "dicha y escrita": "spoken and typed",
    "solo dicha": "spoken only",
    # Cuando vuelve la cuota, y el estado de un servidor MCP. Los cuatro
    # los pesco la sonda nueva y NINGUNO lo veia la vieja: dos viven en
    # literales de JS (que aquella se saltaba entera al quitar los
    # `<script>`) y uno en un atributo `title`.
    "vuelve a las ": "back at ",
    "vuelve el ": "back on ",
    "sin estado": "no status",
    "servidores MCP": "MCP servers",
    "todavia no, en este idioma": "not in this language yet",
    "lo arranca Jarvis": "Jarvis starts it",
    # --- el registro de transmision ---
    # >>> SEIS ROTULOS SE QUEDABAN EN ESPAÑOL, Y LOS VIO EL USUARIO <<<
    # (2026-09-09, usando Jarvis entero en ingles.) En su registro salian
    # "starting up" y "allowed on its own" al lado de "cuota", "sesion",
    # "fallo" y "resultado". No era una traduccion olvidada: eran los
    # cuatro rotulos que **se escriben igual que un identificador**, asi
    # que meterlos aqui habria roto la pagina en vez de traducirla --
    # `nucleo/textos.py` sustituye el literal "texto" en TODO el archivo:
    #
    #   "cuota"   era ademas `id="cuota"`, y el CSS lo referencia como
    #             `#cuota.mal` (el color de alarma al pasar del 100 %).
    #             El id se habria traducido y el selector no: la alarma
    #             dejaria de pintarse SIN un solo error.
    #   "sesion"  era la clave de `CAJAS_CUOTA`, y
    #             `CAJAS_CUOTA["session"]` es `undefined`: la cuota
    #             entera dejaria de pintarse, tambien en silencio.
    #
    # SE APARTO EL IDENTIFICADOR, NO EL ROTULO: `id="cifraCuota"` y las
    # claves `ventanaSesion`/`ventanaSemana`. Un identificador se renombra
    # sin que nadie lo note; la palabra que se lee en pantalla, no.
    # OJO: `"sesion "` -- con espacio, mas arriba -- es mas larga y gana
    # por el orden de sustitucion, asi que en la practica es ella la que
    # traduce este rotulo, y el resultado en pantalla es el mismo. Esta
    # linea se queda igualmente y no es redundante: el dia que aquella se
    # vaya o cambie, sin esto el rotulo volveria al español sin que nadie
    # tocara el registro.
    "sesion": "session",
    "cuota": "quota",
    "fallo": "failure",
    "resultado": "result",
    "turno": "turn",
    "consola": "console",
    "pensando": "thinking",
    "Semanal": "Weekly",
    "caida": "down",
    "HACIENDO": "DOING",
    # --- los ajustes: botones sueltos ---
    "PROBAR": "TEST",
    "QUITAR": "REMOVE",
    "LISTO": "READY",
    # --- la consola: los seis estados del ciclo de voz (JC-0011) ---
    # >>> LOS NOMBRES, QUE FALTABAN, Y LO VIO EL USUARIO <<<
    # El primer barrido traducio lo que cada estado SIGNIFICA ('di "hey
    # jarvis"', "HABLA YA") y se dejo los NOMBRES. El detector los
    # descarto solos: una palabra de solo letras parecia un
    # identificador, y en este archivo casi siempre lo es. Los seis
    # estaban en la misma tabla, a dos columnas de distancia de algo que
    # si se tradujo.
    # Los seis ingleses son mas cortos que los españoles, asi que no
    # mueven la maqueta de la franja.
    "DORMIDO": "ASLEEP",
    "AVISANDO": "CHIMING",
    "ESCUCHANDO": "LISTENING",
    "TRABAJANDO": "WORKING",
    "HABLANDO": "SPEAKING",
    "PREGUNTANDO": "ASKING",
    'di "hey jarvis"': 'say "hey jarvis"',
    "suena el aviso, no hables": "chime playing, don't talk yet",
    "HABLA YA": "TALK NOW",
    'actuando · solo oye "para"': 'acting · only hears "stop"',
    'te contesta · solo "para"': 'answering you · only "stop"',
    "contesta sin la palabra": "answer without the wake word",
    "hey jarvis · J inglesa": "hey jarvis · English J",
    "locuta entero": "reads it all out",
    " · sigue escuchando": " · keeps listening",
    " MIN": " MIN",

    # --- los ajustes: cabecera ---
    "Se guardan en": "Saved in",
    ". El archivo con los valores de fabrica no se toca, asi que siempre "
    "puedes volver borrando ese.":
        ". The file with the factory values is never touched, so you can "
        "always go back by deleting that one.",
    # --- los ajustes: el perimetro (JC-0007) ---
    "QUE NO PUEDE TOCAR": "WHAT IT CANNOT TOUCH",
    "Jarvis trabaja sobre la carpeta que le has dado. Fuera de ahi hay "
    "sitios donde no se puede meter":
        "Jarvis works on the folder you gave it. Outside of that there are "
        "places it cannot go into",
    "aunque tu se lo pidas": "even if you ask it to",
    ". Se detectan solos en cada arranque.":
        ". They are detected on their own at every start.",
    "PUEDE MIRAR, NO CAMBIAR": "CAN LOOK, NOT CHANGE",
    "&mdash; carpetas de Windows y de programas. Leerlas es inofensivo y "
    "hace falta (&ldquo;¿que version de driver tengo?&rdquo;); lo que rompe "
    "el ordenador es escribir en ellas.":
        "&mdash; Windows and program folders. Reading them is harmless and "
        "necessary (&ldquo;which driver version do I have?&rdquo;); what "
        "breaks the computer is writing to them.",
    "NI MIRAR": "NOT EVEN LOOK",
    "&mdash; carpetas privadas. Aqui el riesgo no es romper nada: es que":
        "&mdash; private folders. Here the risk is not breaking anything: "
        "it is that",
    "lo de dentro viaje": "what is inside travels",
    ". Todo lo que Jarvis lee se lo manda a Claude para poder contestarte.":
        ". Everything Jarvis reads it sends to Claude in order to answer you.",
    "VER LAS": "SEE THE",
    "QUE NO SE PUEDEN QUITAR": "THAT CANNOT BE REMOVED",
    "Estas no son opcionales: son las que impiden romper el ordenador. Se "
    "enseñan porque tienes derecho a ver de que se te protege &mdash; una "
    "proteccion que no se puede mirar se parece demasiado a una que no "
    "existe.":
        "These are not optional: they are the ones that keep the computer "
        "from being broken. They are shown because you have a right to see "
        "what you are being protected from &mdash; a protection you cannot "
        "look at looks far too much like one that isn't there.",
    # --- el glosario de palabras clave (2026-09-05) ---
    # Solo la CABECERA. Las entradas viajan como JSON y ya vienen en su
    # idioma desde `voz/glosario.py`: no son traducciones -- en ingles
    # las frases son OTRAS ("show yourself"), porque las españolas no las
    # reconoce nadie alli.
    "LO QUE JARVIS SE QUEDA": "WHAT JARVIS KEEPS FOR ITSELF",
    "Estas son las unicas frases que": "These are the only sentences that",
    "no llegan a Claude Code": "never reach Claude Code",
    ": las mira Jarvis y se las queda. Todo lo demas que digas o escribas "
    "viaja entero. Se quedan solo cosas que el cerebro NO PUEDE hacer "
    "&mdash; no tiene esta ventana, ni puede mudar su propia sesion de "
    "carpeta, ni matar al proceso que lo conduce.":
        ": Jarvis looks at them and keeps them. Everything else you say or "
        "type travels whole. It only keeps things the brain CANNOT do "
        "&mdash; it has no window here, it cannot move its own session to "
        "another folder, and it cannot kill the process driving it.",
    # --- los ajustes: proyectos (ADR-0029) ---
    "TUS PROYECTOS": "YOUR PROJECTS",
    "Los que puedes abrir diciendo": "The ones you can open by saying",
    # >>> SIN NOMBRES REALES (2026-09-05) <<< Aqui habia un proyecto
    # del autor. Lo vio el usuario: esto se publica, y un nombre suyo
    # en un ejemplo se lee como parte del programa.
    "&ldquo;hey jarvis, continua con el proyecto X&rdquo;":
        "&ldquo;hey jarvis, carry on with project X&rdquo;",
    "la carpeta, por ejemplo C:\\ruta\\a\\tu\\proyecto":
        "the folder, for example C:\\path\\to\\your\\project",
    # >>> YA NO ES SOLO HABLANDO (2026-09-03) <<< La consola intercepta
    # la misma frase, con el mismo interruptor. Los rotulos lo dicen.
    # >>> Y DESDE EL 2026-09-05 LA FRASE LA ESCRIBE EL USUARIO <<< Aqui
    # ya no se puede CITAR: era una constante y ahora es un ajuste, asi
    # que el parrafo dice donde se escribe en vez de que dice. Las dos
    # entradas viejas (la cita y su cola) se fueron con ella.
    "&mdash; con X el nombre que le pongas abajo &mdash;, o escribiendo "
    "esa misma frase en la consola. Al abrir uno, Jarvis le pregunta solo "
    "una cosa para tener con que empezar, y te lee la respuesta. Esa "
    "pregunta la escribes tu aqui mismo, y cada proyecto de la lista puede "
    "tener la suya, o ninguna.":
        "&mdash; where X is whatever you name it below &mdash;, or by "
        "typing that same sentence in the console. When it opens one, "
        "Jarvis asks it a single thing so it has somewhere to start, and "
        "reads you the answer. You write that question right here, and "
        "each project in the list can have its own, or none at all.",
    "Usar la de arriba en todos": "Use the one above for all of them",
    # Es UN solo nodo de texto -- el `&mdash;` va dentro y no parte nada --,
    # asi que la clave tiene que ser la frase entera: `_patron` exige
    # `>texto<` completo, y media frase no casa nunca (y no da error, deja
    # el parrafo en español).
    "Normalmente gana la frase de cada proyecto, y la de arriba es solo "
    "para los que no tengan la suya. Enciende esto y manda la de arriba "
    "SIEMPRE: las que hayas escrito aqui abajo se quedan escritas y dejan de "
    "usarse &mdash; cada una te lo dira. Si la de arriba esta vacia, "
    "entonces no pregunta nada en ningun proyecto.":
        "Normally each project's own sentence wins, and the one above is "
        "only for those without one. Turn this on and the one above ALWAYS "
        "wins: the ones you wrote down here stay written and stop being "
        "used &mdash; each one will tell you. If the one above is empty, "
        "then it asks nothing in any project.",
    "Ahora no se usa: manda la frase de arriba.":
        "Not in use right now: the sentence above wins.",
    "Al abrir este:": "When it opens this one:",
    "le pregunta lo de siempre": "it asks the usual thing",
    "le pregunta otra cosa…": "it asks something else…",
    "no le pregunta nada": "it asks nothing",
    "Dejar que lo pida por su nombre": "Let it be asked for by name",
    "Apagado, esa frase le llega a Claude Code como cualquier otra y Jarvis "
    "no se mete. Es el unico sitio donde Jarvis mira lo que le pides antes de "
    "pasarlo, asi que lo enciendes tu. Vale para las dos formas: dicha y "
    "escrita.":
        "Off, that sentence reaches Claude Code like any other and Jarvis "
        "stays out of it. It is the only place where Jarvis looks at what "
        "you ask before passing it on, so you are the one who turns it on. "
        "It covers both ways: spoken and typed.",
    "Carpetas que hay donde guardas tus proyectos":
        "Folders found where you keep your projects",
    "Añade las que quieras poder abrir por voz.":
        "Add the ones you want to be able to open by voice.",
    "Añadir uno a mano": "Add one by hand",
    "AÑADIR": "ADD",
    "¿POR QUE HAY QUE REGISTRARLOS?": "WHY DO THEY HAVE TO BE REGISTERED?",
    "Porque lo que Jarvis recibe es una TRANSCRIPCION, no algo que hayas "
    "tecleado: un nombre pegado puede llegar partido en dos palabras, o "
    "con un guion, segun como lo digas. Buscar por el disco a ver que se "
    "parece obligaria a decidir sola entre carpetas parecidas, y "
    "equivocarse aqui significa poner a trabajar un agente sobre codigo "
    "que no era. Si dos coinciden, Jarvis pregunta en vez de elegir.":
        "Because what Jarvis receives is a TRANSCRIPT, not something you "
        "typed: a run-together name can arrive split into two words, or "
        "hyphenated, depending on how you say it. Searching the disk for "
        "whatever looks similar would force it to choose on its own "
        "between lookalike folders, and getting this wrong means setting "
        "an agent to work on code that wasn't the one. If two match, "
        "Jarvis asks instead of choosing.",
    # --- los ajustes: Telegram (JC-0006 y JC-0016) ---
    "AVISARME POR TELEGRAM": "REACH ME ON TELEGRAM",
    "Opcional. Si Jarvis necesita tu permiso para algo y no le contestas, "
    "te escribe al movil &mdash; pero":
        "Optional. If Jarvis needs your permission for something and you "
        "don't answer, it writes to your phone &mdash; but",
    "solo avisa, no obedece": "it only warns, it does not obey",
    ": no lee mensajes y no se le puede autorizar nada desde ahi. Quien "
    "controlase ese chat no controlaria tu PC.":
        ": it does not read messages and nothing can be authorised from "
        "there. Whoever controlled that chat would not control your PC.",
    "Mandarme avisos": "Send me alerts",
    "Token del bot": "Bot token",
    "Se saca hablando con": "You get one by talking to",
    "en Telegram:": "on Telegram:",
    ", le pones nombre y te da el token.":
        ", give it a name and it hands you the token.",
    "¿POR QUE NO SE VE EL QUE YA HAY?": "WHY ISN'T THE CURRENT ONE SHOWN?",
    "Un token es una credencial: quien lo tenga puede escribir en tu chat. "
    "No se enseña ni se guarda en el registro, y vive en un archivo que git "
    "ignora. Dejarlo en blanco NO borra el que ya tengas puesto.":
        "A token is a credential: whoever has it can write in your chat. It "
        "is neither shown nor written to the log, and it lives in a file "
        "git ignores. Leaving it blank does NOT erase the one you already "
        "have.",
    "A que chat": "Which chat",
    "Tu identificador de Telegram. Se lo puedes preguntar a":
        "Your Telegram id. You can ask it from",
    "MANDARME UNA PRUEBA": "SEND ME A TEST",
    "Dejarme contestarle desde el movil": "Let me answer it from the phone",
    "Cuando Jarvis te pregunte algo &mdash; una eleccion, un &ldquo;¿lo "
    "hago asi o asa?&rdquo; &mdash; te llegan las opciones numeradas y "
    "contestas con el numero.":
        "When Jarvis asks you something &mdash; a choice, a &ldquo;shall I "
        "do it this way or that?&rdquo; &mdash; the options reach you "
        "numbered and you answer with the number.",
    "¿QUE NO SE PUEDE HACER DESDE EL MOVIL?":
        "WHAT CANNOT BE DONE FROM THE PHONE?",
    "Dar permisos. Un borrado, un": "Granting permission. A deletion, a",
    "o tocar algo fuera de la carpeta se autorizan delante del ordenador, y "
    "punto. Tampoco se pueden mandar ordenes nuevas: eso va por voz. El "
    "motivo es que quien tenga el token del bot puede escribir en ese chat, "
    "asi que lo que se acepta esta acotado a propósito &mdash; lo peor que "
    "puede pasar es que alguien conteste una pregunta de diseño en tu "
    "nombre, no que te borre algo.":
        "or touching anything outside the folder are authorised in front of "
        "the computer, full stop. New orders cannot be sent either: those go "
        "by voice. The reason is that whoever has the bot token can write in "
        "that chat, so what is accepted is fenced in on purpose &mdash; the "
        "worst that can happen is that someone answers a design question in "
        "your name, not that they delete something of yours.",
    # --- los ajustes: MCP (JC-0015) ---
    "SERVIDORES MCP": "MCP SERVERS",
    "Los MCP le dan herramientas nuevas a Jarvis y con eso mucha potencia. "
    "Por eso es una":
        "MCPs give Jarvis new tools and with them a lot of power. That is "
        "why this is a",
    "lista blanca": "whitelist",
    ": lo que no aparezca aqui no se ejecuta. Un servidor no es una "
    "herramienta suelta &mdash; decide el solo cuales ofrece y puede "
    "cambiarlas &mdash;, asi que lo que autorizas es el servidor entero.":
        ": whatever is not listed here does not run. A server is not a "
        "single tool &mdash; it decides on its own which ones it offers and "
        "can change them &mdash;, so what you authorise is the whole server.",
    # --- lo que ya tiene declarado tu Claude Code (2026-09-03) ---
    "Los que ya tiene tu Claude Code": "The ones your Claude Code already has",
    "Estan declarados en tu Claude Code de siempre, pero Jarvis no los deja "
    "actuar hasta que tu lo digas. Se enseña de que archivo sale cada uno: "
    "autorizar sin saberlo seria autorizar a ciegas.":
        "They are declared in your usual Claude Code, but Jarvis will not let "
        "them act until you say so. Each one shows the file it comes from: "
        "authorising without knowing that would be authorising blind.",
    "AUTORIZAR": "AUTHORISE",
    "IMPORTAR": "IMPORT",
    "Necesita, y no se copian: ": "Needs, and these are not copied: ",
    "Ya lo tienes declarado. Importar se queda con ":
        "You already have it declared. Importing keeps ",
    "esta definicion y NO toca su politica.":
        "this definition and does NOT touch its policy.",
    "no se pudo autorizar: ": "could not authorise: ",
    "no se pudo autorizar": "could not authorise",
    "Autorizado. Hace falta reabrir la sesion para que arranque.":
        "Authorised. The session has to be reopened for it to start.",
    "Han pedido algo y no estan en la lista":
        "They asked for something and are not on the list",
    "Jarvis se lo ha denegado. Si los conoces, añadelos aqui.":
        "Jarvis denied them. If you know them, add them here.",
    "¿POR QUE HACE FALTA ESTA LISTA?": "WHY IS THIS LIST NEEDED?",
    "Se midio el 2026-08-26: una herramienta de un MCP atravesaba la puerta "
    "de Jarvis sin tocarla. Las protecciones miran el NOMBRE de la "
    "herramienta (Write, Edit, Bash) y las rutas que nombra Claude Code; un "
    "nombre de MCP no casa con ninguna de las dos, asi que caia en "
    "\"permitir por defecto\" &mdash; incluso una que escribiera en "
    "C:\\Windows. Las dos capas fallaban a la vez, que es justo lo que las "
    "hacia dos.":
        "Measured on 2026-08-26: an MCP tool went straight through Jarvis's "
        "gate without touching it. The guards look at the NAME of the tool "
        "(Write, Edit, Bash) and at the paths Claude Code names; an MCP name "
        "matches neither, so it fell into \"allow by default\" &mdash; even "
        "one writing to C:\\Windows. Both layers failed at once, which is "
        "exactly what made them two.",
    # --- los ajustes: la barra ---
    "GUARDAR": "SAVE",
    "DESHACER": "UNDO",
    "REINICIAR JARVIS": "RESTART JARVIS",
    "CONFIRMAR REINICIO": "CONFIRM RESTART",
    "MOSTRAR AJUSTES AVANZADOS": "SHOW ADVANCED SETTINGS",
    "OCULTAR AJUSTES AVANZADOS": "HIDE ADVANCED SETTINGS",
    "¿POR QUE?": "WHY?",
    # --- los ajustes: cuando se aplica cada cosa ---
    "se aplica al momento": "applies right away",
    "hace falta reabrir la sesion": "the session has to be reopened",
    "hace falta reiniciar Jarvis": "Jarvis has to be restarted",
    "cuando ": "when ",
    # --- los ajustes: probar el micro y el altavoz ---
    "grabando dos segundos... di algo": "recording two seconds... say something",
    "nivel ": "level ",
    " dBFS. ": " dBFS. ",
    "no se pudo probar: ": "could not test it: ",
    "no se pudieron leer los ajustes: ": "could not read the settings: ",
    "  (ya no esta conectado)": "  (no longer connected)",
    # --- los ajustes: estados y mensajes ---
    "NO FUNCIONA": "NOT WORKING",
    "SIN CONFIGURAR": "NOT SET UP",
    "ya hay uno puesto, acaba en …": "one is already set, ending in …",
    "todavia no hay token": "no token yet",
    "no se pudo guardar: ": "could not save: ",
    "no se pudo guardar": "could not save",
    "Mandado. Mira tu Telegram: si no te ha llegado, el chat no es ese.":
        "Sent. Check your Telegram: if it didn't arrive, that isn't the chat.",
    "Guardado, pero no funciona: ": "Saved, but it does not work: ",
    "Guardado y comprobado.": "Saved and checked.",
    "Guardado.": "Saved.",
    "Guardado. ": "Saved. ",
    "Guardado y aplicado.": "Saved and applied.",
    "no has cambiado nada": "you haven't changed anything",
    "Guardado. Recargando la pantalla...": "Saved. Reloading the screen...",
    "Un cambio no se nota": "One change won't show",
    " cambios no se notan": " changes won't show",
    " hasta que reinicies Jarvis.": " until you restart Jarvis.",
    " hasta reabrir la sesion.": " until the session is reopened.",
    "Si la bloqueas: ": "If you block it: ",
    "Esta sesion corre SIN proteccion de carpetas.":
        "This session is running WITHOUT folder protection.",
    " fijas y ": " fixed and ",
    " que puedes elegir.": " you can choose.",
    "no se pudieron guardar las carpetas: ": "could not save the folders: ",
    "no se pudieron guardar las carpetas": "could not save the folders",
    "Guardado. Para que se aplique del todo, reinicia Jarvis: lo que ":
        "Saved. For it to apply fully, restart Jarvis: what ",
    "acabas de bloquear ya se deniega al escribir, pero LEER no pasa por ":
        "you just blocked is already denied on writing, but READING does not "
        "go through ",
    "esa comprobacion.": "that check.",
    "Ninguno todavia. Añade el primero abajo.":
        "None yet. Add the first one below.",
    "  — es el que esta abierto": "  — this is the one open",
    "   (ya no existe)": "   (no longer there)",
    "no se pudieron guardar los proyectos: ": "could not save the projects: ",
    "no se pudieron guardar los proyectos": "could not save the projects",
    "sus herramientas pasan solas": "its tools go through on their own",
    "te pregunta cada vez": "asks you every time",
    "no pasan": "do not go through",
    "Ninguno declarado, asi que ningun MCP puede actuar.":
        "None declared, so no MCP can act.",
    "no se pudo guardar los MCP: ": "could not save the MCPs: ",
    "no se pudieron guardar los MCP": "could not save the MCPs",
    # --- los ajustes: el boton de reiniciar ---
    "Jarvis se esta cerrando. La ventana volvera sola.":
        "Jarvis is shutting down. The window will come back on its own.",
    "no se pudo reiniciar": "could not restart",
    "Reiniciando. La ventana se cierra y vuelve sola.":
        "Restarting. The window closes and comes back on its own.",
    "Esta sesion no se puede reiniciar sola: se lanzo a mano desde una ":
        "This session cannot restart itself: it was launched by hand from a ",
    "terminal, no desde la aplicacion.": "terminal, not from the application.",
    "TIENES CAMBIOS SIN GUARDAR. ": "YOU HAVE UNSAVED CHANGES. ",
    "HAY UN TURNO EN MARCHA y se corta. ":
        "A TURN IS RUNNING and it gets cut off. ",
    "Reiniciar cierra la sesion de Claude Code y pierde el contexto de ":
        "Restarting closes the Claude Code session and loses the context of ",
    "la conversacion. Pulsa otra vez para confirmar.":
        "the conversation. Press again to confirm.",
}


# ----------------------------------------------------------------------
#  2. El catalogo de ajustes
# ----------------------------------------------------------------------
# Aqui NO se indexa por la cadena española sino por `clave.campo`. El
# motivo es que estas cadenas viven en `nucleo/ajustes.py`, que es
# nuestro: se puede pedir la traduccion por un identificador estable en
# vez de por el texto, y entonces retocar una coma del original no deja
# la traduccion muerta sin avisar.

AJUSTES_EN: dict[str, str] = {
    "grupo.pantalla.titulo": "The screen",
    "grupo.pantalla.ayuda":
        "How you see it and in which language. It changes nothing about "
        "what Jarvis does.",
    "grupo.empezar.titulo": "To get started",
    "grupo.empezar.ayuda": "The least that makes Jarvis useful.",
    "grupo.oir.titulo": "Hearing and speaking",
    "grupo.oir.ayuda":
        "Where it hears you and where it answers you. Test them: it is the "
        "only way to know you got it right.",
    "grupo.avanzado.titulo": "Advanced",
    "grupo.avanzado.ayuda":
        "It already works without touching any of this. Each one says what "
        "it costs to change it.",

    "sesion.carpeta.etiqueta": "Working folder",
    "sesion.carpeta.ayuda":
        "The folder Jarvis is allowed to work on. Everything it does goes "
        "on in here.",
    "sesion.carpeta.aviso":
        "Outside this folder Jarvis ASKS you before touching anything, and "
        "there are system areas where it cannot write even if you tell it "
        "to. That does not depend on this setting.",

    "ui.idioma.etiqueta": "Language of the screen",
    "ui.idioma.ayuda":
        "Changes what you READ. What Jarvis speaks, and what it understands "
        "when you talk to it, is set separately below.",
    "ui.idioma.aviso":
        "It does not change the voice. The wake word, the transcription and "
        "the voice it answers with are measured against Spanish recordings, "
        "so switching them is not a translation: it is a different setting "
        "with its own cost.",
    "ui.idioma.opcion.es": "Spanish",
    "ui.idioma.opcion.en": "English",

    "ui.tema.etiqueta": "How it looks",
    "ui.tema.ayuda":
        "Only changes the colours and the typography. The screen shows "
        "exactly the same in all four: what Jarvis does, and the question "
        "when it asks you for permission.",
    "ui.tema.aviso":
        "Applies right away, no restart. What does NOT change with the "
        "theme is WHAT is shown: the permission request says the same in "
        "all four, because that is where you authorise, and a \u201csimpler"
        "\u201d version of that would be authorising without knowing what.",
    "ui.tema.opcion.jarvis": "Jarvis \u2014 cyan on black, the usual one",
    "ui.tema.opcion.hacker": "Terminal \u2014 green on black",
    "ui.tema.opcion.despacho": "Office \u2014 light, for working with documents",
    "ui.tema.opcion.nexo": "Nexus \u2014 light and minimal",

    "voz.encendida.etiqueta": "Talk to it instead of typing",
    "voz.encendida.ayuda":
        "You say \u201chey jarvis\u201d and talk to it. If you leave it off, "
        "Jarvis works the same by typing here.",
    "voz.encendida.aviso":
        "Say it with the English J, as in \u201cyellow\u201d: \u201chey "
        "YAR-vis\u201d. Measured with the user's voice: the Spanish way it "
        "gets 1 in 20, the English way 5 in 6. Turning it on adds ~9 s to "
        "startup, which is what the models take to load.",

    "voz.idioma.etiqueta": "Language it speaks and hears you in",
    "voz.idioma.ayuda":
        "The language you talk to it in and the one it answers you in. "
        "It is different from the language of the screen.",
    # Ver el comentario del mismo aviso en `nucleo/ajustes.py`: la version
    # vieja prometia que este ajuste cambiaba solo el perfil de voz, y no
    # lo hace en ninguno de los dos idiomas.
    # >>> Y ESTA ES LA VERSION QUE MAS IMPORTA (2026-09-09) <<<
    # La lee justamente quien va a usar el ingles, o sea la unica
    # persona que puede cerrar el hueco. Decia "there is no bench yet",
    # y ese "yet" prometia algo que no viene: el autor no le habla en
    # ingles y decidio no grabarlo. Dicho asi deja de ser una promesa y
    # pasa a ser una invitacion con las herramientas ya puestas.
    "voz.idioma.aviso":
        "This is not the same as the language of the screen. In Spanish, "
        "the transcription and the words used to STOP it are measured "
        "against 30 real recordings; in English they are NOT, and that is "
        "not a pending task: whoever wrote this does not speak English to "
        "Jarvis, so only somebody who uses it that way can record that "
        "bench. It works; what is missing is the number, and if you speak "
        "English the project ships what you need to measure it (see the "
        "README). SAVING THIS ALSO CHANGES “the voice it "
        "speaks with”, because the two travel together: a Spanish "
        "voice reading English would give no error, it would just sound "
        "wrong, so Jarvis refuses to start on that pair. If you would "
        "rather have another voice of that language, pick it below "
        "afterwards.",
    "voz.idioma.opcion.es": "Spanish",
    "voz.idioma.opcion.en": "English",
    "voz.audio.entrada.etiqueta": "Microphone",
    "voz.audio.entrada.ayuda":
        "Where it hears you. Hit Test and say something.",
    "voz.audio.entrada.aviso":
        "ALWAYS TEST IT when you change it. This machine has 16 inputs that "
        "are not microphones: they are internal cables of other programs. "
        "If you pick one, Jarvis gives no error at all -- it simply never "
        "hears you again.",
    "voz.audio.salida.etiqueta": "Speaker",
    "voz.audio.salida.ayuda":
        "Where it answers you. Leaving it on the Windows one, plugging in "
        "headphones is enough for it to follow.",
    "audio.el_de_windows": "Whichever Windows has set (now: {})",

    "voz.perfil.etiqueta": "Voice it speaks with",
    "voz.perfil.ayuda": "Its name and its voice.",
    "voz.perfil.aviso":
        "If you pick a voice of another language, saving also changes "
        "\u201cthe language it speaks and hears you in\u201d: they "
        "travel together. "
        "You still call it \u201chey jarvis\u201d even if you change the "
        "name: the word it wakes up on is a separately trained model and "
        "there is no other one made (ADR-0002).",

    # JC-0017. La etiqueta dice lo que HACE y no "fast mode": es la unica
    # casilla del panel que apaga la puerta, y una etiqueta que suene a
    # comodidad la haria elegir por comodidad.
    "sesion.auto_por_defecto.etiqueta": "Never ask me, in every folder",
    "sesion.auto_por_defecto.ayuda":
        "Jarvis opens ALL its sessions in Claude Code's auto mode, including "
        "folders that are not a registered project. Without this, only the "
        "projects on your list get it.",
    "sesion.auto_por_defecto.aviso":
        "With this on, three things stop being asked, by name: deleting "
        "files, `git push`, and tools from MCP servers you have not "
        "authorised. It is not that Jarvis approves fast: it never hears "
        "the request. What does NOT change, measured against all five "
        "modes: the sealed system zones stay blocked, and the console still "
        "shows you every tool it uses. It leaves you without brakes, not in "
        "the dark.",

    # JC-0015. El aviso separa a proposito lo que se DENIEGA de lo que se
    # ARRANCA: son dos cosas y solo cambia la segunda.
    "lo arranca Jarvis": "started by Jarvis",
    # La etiqueta habla de TIEMPO y no de calidad: es lo que se paga.
    "sesion.esfuerzo.etiqueta": "How long it thinks first",
    "sesion.esfuerzo.ayuda":
        "How much it reasons before answering you. The normal setting is "
        "fine for almost everything; raising it is for hard problems.",
    "sesion.esfuerzo.aviso":
        "THIS IS PAID IN SECONDS, and it is measured: with \"as much as it "
        "can\", the same question went from 5.4 to 23.7 seconds. Out loud "
        "that is twenty-four seconds of silence, and an assistant quiet "
        "that long is indistinguishable from one that has hung. The money "
        "barely moves (45 %). And you do not need this for a one-off: "
        "asking it to \"think it through\" in the order itself reaches the "
        "brain just the same.",
    "El de siempre (recomendado)": "The usual (recommended)",
    "Mas": "More",
    "Todo lo que pueda": "As much as it can",

    "mcp.estricto.etiqueta": "Only the MCP servers Jarvis declares",
    "mcp.estricto.ayuda":
        "Jarvis starts only the servers on its own list, not the ones you "
        "have configured in your terminal Claude Code. Without this it "
        "starts both.",
    "mcp.estricto.aviso":
        "What does NOT change is what gets denied: a server that is not on "
        "your allow-list does not pass, with or without this. What changes "
        "is whether it gets STARTED -- each server is a process, and Jarvis "
        "may be running all day from Windows startup. The price of turning "
        "it on: Jarvis stops SEEING servers you add elsewhere, so the panel "
        "can no longer offer them at the click of a button and you have to "
        "declare them here by hand.",

    "voz.seguimiento.etiqueta": "Follow the conversation",
    "voz.seguimiento.ayuda":
        "After answering you it keeps listening for a moment, so you don't "
        "have to call it again. You go quiet and it goes quiet.",
    "voz.seguimiento.aviso":
        "While that window is open it transcribes whatever is said in the "
        "room, whoever is talking.",

    "voz.narrar.etiqueta": "Tell you what it is doing",
    "voz.narrar.ayuda":
        "While it works it tells you out loud what it is doing (\"now I'm "
        "checking the code...\"), as if it were keeping you company. The "
        "detail stays whole in the console.",
    "voz.narrar.aviso":
        "Only prose is spoken: paths, commands and identifiers are left "
        "out, because read aloud they make no sense. Measured with "
        "-m eval.mirar_narracion.",

    "voz.resumir.etiqueta": "Sum up what it says",
    "voz.resumir.ayuda":
        "Off, it reads you the whole answer. On, it tells you the gist and "
        "leaves the detail written in the console.",
    "voz.resumir.aviso":
        "A really long answer is ~145 seconds of talking.",

    "voz.wake_word.umbral.etiqueta": "How easily it hears you calling it",
    "voz.wake_word.umbral.ayuda":
        "Lower, it hears you with less effort but wakes up on its own more "
        "often.",
    "voz.wake_word.umbral.aviso":
        "0.5 is not a number picked by eye: it is measured with the user's "
        "voice at the distance they really speak from, and the weakest good "
        "attempt landed at 0.494. With 0.6 it would have been lost.",

    "sesion.modelo.etiqueta": "Claude Code model",
    "sesion.modelo.opcion.sonnet": "Sonnet (recommended)",
    "sesion.modelo.ayuda": "The brain that thinks and acts.",
    "voz.stt.modelo.etiqueta": "Model that transcribes your voice",
    "voz.stt.modelo.ayuda": "Only the ones already downloaded show up.",
    "voz.stt.modelo.aviso":
        "The smallest ones wreck the words used to STOP it "
        "(\u201ccancel\u201d comes out \u201ccancer\u201d), which is the "
        "thing you can least afford to get wrong while something is acting "
        "on your PC.",

    "voz.stt.ancla_vocabulario.etiqueta": "Words it hears often",
    "voz.stt.ancla_vocabulario.ayuda":
        "Names of folders and programs you tend to say, separated by "
        "commas. They help it not to mix them up.",
    "voz.stt.ancla_vocabulario.aviso":
        "Measured: with this list it gets it wrong half as often (4.2 % -> "
        "2.4 %). EMPTYING IT IS NOT NEUTRAL: Jarvis also adjusts, on its "
        "own, how sure it has to be that somebody spoke. That is why that "
        "second number is not touched from here.",

    "tiempos.telegram_minutos.etiqueta": "Ping me on Telegram if I take too long",
    "tiempos.telegram_minutos.ayuda":
        "How long it waits for you to answer before writing to you, and "
        "only if you are not in front of the computer.",
    "tiempos.ausente_minutos.etiqueta": "Consider me away after",
    "tiempos.ausente_minutos.ayuda": "Without touching keyboard or mouse.",
    "tiempos.ausente_minutos.aviso":
        "Measured: Windows went as far as reporting 265 seconds of "
        "inactivity with the user sitting right there, reading. Below ~5 "
        "min it will call you away while you are present.",

    "proyectos.raiz.etiqueta": "Where you keep your projects",
    "proyectos.raiz.ayuda":
        "The folder that holds them. It only serves to OFFER them to you "
        "below in one click; Jarvis opens none that you have not added.",

    "proyectos.ritual.etiqueta": "What Jarvis asks when it opens a project",
    "proyectos.ritual.ayuda":
        "When you say or type “carry on with project X”, Jarvis "
        "opens the folder and sends this on its own, so it has somewhere to "
        "start. Leave it EMPTY and it will open the folder without saying "
        "anything.",
    "proyectos.ritual.aviso":
        "THIS IS SENT WITHOUT YOU BEING THERE, and with the full authority "
        "of the session: if that project has auto mode on, whatever you "
        "write here goes through no gate at all. A line saying “delete "
        "the temp files” gets carried out. It also overrides the "
        "language: it is sent exactly as you write it, with the voice in "
        "Spanish too. And each project in the list below can have its "
        "own, or none.",

    "tiempos.seguimiento_s.etiqueta": "How long it waits for you to keep talking",
    "tiempos.seguimiento_s.ayuda":
        "Only counts if \u201cfollow the conversation\u201d is on.",

    "unidad.min": "min",
    "unidad.s": "s",

    # --- la bandeja y los cuadros de la carcasa ---
    # Van aqui y no en un diccionario aparte porque son lo mismo: texto
    # nuestro, indexado por una clave estable. Lo que NO cabe aqui es la
    # copia de las paginas, que se indexa por la cadena original porque
    # esa vive en un HTML y no en codigo nuestro.
    "bandeja.abrir": "Open Jarvis",
    "bandeja.ajustes": "Settings",
    "bandeja.navegador": "Open in the browser",
    "bandeja.inicio": "Start with Windows",
    "bandeja.log": "See the startup log",
    "bandeja.salir": "Quit",
    "carcasa.no_arranco": "Jarvis could not start.",
    "carcasa.mira_el_log": "The detail is in:",
    "carcasa.sin_carpeta":
        "There is no working folder. Pass it at startup or set it in the "
        "settings (config/ajustes.yaml, key sesion.carpeta).",
    "carcasa.no_reinicio":
        "It did not restart: {}. Jarvis has closed; open it by hand when "
        "port {} is free.",
    "carcasa.no_relanzo": "Jarvis could not be relaunched: {}",
}


# ----------------------------------------------------------------------
#  3. Los MOTIVOS de la puerta
# ----------------------------------------------------------------------
# >>> ESTE ES EL TEXTO MAS IMPORTANTE DEL PROGRAMA <<<
# El motivo de una peticion de permiso -- "borra archivos", "escribe
# fuera del directorio de la sesion" -- lo fabrica `puente/politica.py`,
# se ve en la tarjeta de la consola Y SE LOCUTA dentro de la frase de
# JC-0002. O sea que es a la vez lo que se lee y lo que se oye en el
# momento en que el usuario CONSIENTE.
#
# >>> VIVE AQUI Y NO EN `politica.py`, Y NO ES ORDEN <<<
# La `Decision` sigue llevando su motivo en español, que es lo que va al
# registro de auditoria: un log que cambia de idioma con un ajuste de la
# UI deja de servir para comparar dos sesiones. Se traduce al PINTARLO y
# al DECIRLO, que es justo lo que manda JC-0002 -- "la frase se DERIVA,
# no se redacta".
#
# Y ESTA EN UN SOLO SITIO aunque lo usen la pantalla y la voz, que
# pueden estar en idiomas distintos. Dos diccionarios de motivos
# acabarian diciendo cosas distintas sobre la misma accion, y entonces
# se aprobaria una cosa oyendo otra -- que es exactamente el fallo que
# JC-0002 existe para impedir.

MOTIVOS_EN: dict[str, str] = {
    # --- lo que dice el arranque mientras abre la sesion ---
    # Van por `motivo` y no por un campo nuevo precisamente para caer
    # aqui: un campo propio no estaria en `CLAVES_DE_TEXTO` y el aviso
    # saldria en espanol en una pantalla en ingles.
    "Primera orden: abriendo la sesion de Claude Code. Tarda unos "
    "segundos la primera vez.":
        "First instruction: opening the Claude Code session. It takes a "
        "few seconds the first time.",
    "Primera orden: `claude` cambio de version, asi que hay que volver "
    "a comprobar que el suelo muerde. Cuesta un turno entero en una "
    "sesion aparte y puede tardar. No esta colgado.":
        "First instruction: `claude` changed version, so the floor has "
        "to be proven again. It costs a whole turn in a separate "
        "session and may take a while. It is not stuck.",
    # --- ordenes destructivas de git ---
    "sube codigo a un remoto": "pushes code to a remote",
    "descarta cambios sin guardar": "throws away unsaved changes",
    "borra archivos sin seguimiento": "deletes untracked files",
    "borra una rama": "deletes a branch",
    # --- lo que rompe la PC sin tocar ninguna ruta ---
    "borra una clave del registro de Windows":
        "deletes a Windows registry key",
    "escribe en el registro del sistema": "writes to the system registry",
    "borra una clave del registro": "deletes a registry key",
    "cambia como arranca Windows": "changes how Windows boots",
    "reescribe el arranque del disco": "rewrites the disk boot record",
    "toca la particion de arranque": "touches the boot partition",
    "reparticiona discos": "repartitions disks",
    "formatea una unidad": "formats a drive",
    "formatea o reparticiona un disco": "formats or repartitions a disk",
    "borra los puntos de restauracion": "deletes the restore points",
    "borra un servicio de Windows": "deletes a Windows service",
    "borra una tarea programada": "deletes a scheduled task",
    "se apropia de archivos del sistema": "takes ownership of system files",
    "cambia quien puede tocar unos archivos":
        "changes who can touch some files",
    "modifica la instalacion de Windows": "modifies the Windows install",
    "toca el sistema de archivos a bajo nivel":
        "touches the file system at a low level",
    "borra en el destino todo lo que no este en el origen":
        "deletes everything at the destination that is not at the source",
    "sobrescribe el espacio libre del disco":
        "overwrites the free space on the disk",
    "crea o borra una cuenta de usuario": "creates or deletes a user account",
    # --- ordenes que no se pueden leer ---
    "la orden construye parte de si misma":
        "the command builds part of itself",
    "la orden se evalua en tiempo de ejecucion":
        "the command is evaluated at run time",
    "la orden se canaliza a un interprete":
        "the command is piped into an interpreter",
    # --- rutas y perimetro ---
    "toca un archivo fuera del directorio de la sesion":
        "touches a file outside the session directory",
    "escribe fuera del directorio de la sesion":
        "writes outside the session directory",
    "escribe dentro del directorio de la sesion":
        "writes inside the session directory",
    "no se ve sobre que archivo escribe":
        "it cannot be seen which file it writes to",
    # --- lo demas ---
    "no esta en la lista endurecida": "is not on the hardened list",
    "la orden llego vacia": "the command arrived empty",
    "borra archivos": "deletes files",
    "reescribe un archivo entero y no se sabe si existia":
        "rewrites a whole file and it is not known whether it existed",
}

# --- y el resto del texto que fabrica el servidor ---------------------
# Todo esto viaja en los JSON de `/estado`, `/zonas`, `/mcp` y el flujo
# de eventos, y la pagina lo pinta tal cual. Con la consola en ingles y
# esto en español, media pantalla se queda a medias -- que es justo lo
# que reporto el usuario.
SERVIDOR_EN: dict[str, str] = {
    # --- el suelo y la sesion ---
    "esta sesion corre sin el suelo de JC-0007":
        "this session is running without the JC-0007 floor",
    "arranco sin --voz": "started without --voz",
    "esta sesion no se puede reiniciar sola: lanzala desde la aplicacion "
    "de escritorio":
        "this session cannot restart itself: launch it from the desktop "
        "application",
    "esta sesion corre sin suelo": "this session is running without a floor",
    # --- errores de guardado ---
    "falta la lista de proyectos": "the project list is missing",
    "hay una entrada mal formada": "there is a malformed entry",
    "cada proyecto necesita alias y carpeta":
        "every project needs an alias and a folder",
    "falta la lista de servidores": "the server list is missing",
    "hay una entrada sin nombre": "there is an entry with no name",
    "se prueba 'entrada' o 'salida'": "test either 'entrada' or 'salida'",
    # --- probar el micro y el altavoz ---
    # Estas frases son lo que hace SEGURO dejar elegir dispositivo: en
    # esta maquina 16 de 23 endpoints aceptan o entregan silencio digital
    # sin dar error. Quien las lee esta averiguando por que no le oyen,
    # asi que son de las que menos pueden quedarse en otro idioma.
    "Ha sonado un tono. ¿Lo has oido? Si no, este no es tu altavoz: "
    "hay salidas que aceptan el audio sin quejarse y no lo sacan por "
    "ningun sitio.":
        "A tone played. Did you hear it? If not, this is not your speaker: "
        "there are outputs that accept the audio without complaining and "
        "send it nowhere.",
    "Por ahi no entra nada. Lo mas probable es que este SILENCIADO "
    "(muchos micros tienen un boton o una placa tactil, y el microfono USB se "
    "silencia tocandolo por arriba); mira tambien el volumen de entrada "
    "en Windows. Si esta bien y sigue asi, es que ese endpoint no es un "
    "microfono de verdad: elige otro.":
        "Nothing is coming in there. Most likely it is MUTED (many mics "
        "have a button or a touch plate, and the micro USB mutes by "
        "tapping the top); check the input volume in Windows too. If that "
        "is fine and it stays like this, that endpoint is not a real "
        "microphone: pick another.",
    "Te oye. Ha llegado señal y ha encontrado habla.":
        "It hears you. Signal arrived and speech was found.",
    "Llega señal, pero no ha encontrado habla. Si has hablado, prueba "
    "otra vez mas cerca o mas alto.":
        "Signal arrives, but no speech was found. If you did speak, try "
        "again closer or louder.",
    "Llega señal. No se ha podido comprobar si habia habla.":
        "Signal arrives. Whether there was speech could not be checked.",
    # --- las zonas obligatorias del suelo (JC-0007) ---
    "el sistema operativo": "the operating system",
    "los programas instalados": "the installed programs",
    "los programas de 32 bits": "the 32-bit programs",
    "las aplicaciones de la Store": "the Store apps",
    "la particion de recuperacion montada":
        "the mounted recovery partition",
    "el entorno de recuperacion de Windows":
        "the Windows recovery environment",
    "una actualizacion de Windows a medio aplicar":
        "a half-applied Windows update",
    "una actualizacion de Windows descargada":
        "a downloaded Windows update",
    "las imagenes de instalacion de Windows":
        "the Windows installation images",
    "los puntos de restauracion y las instantaneas VSS":
        "the restore points and VSS snapshots",
    "un instalador en curso": "an installer in progress",
    "el archivo de paginacion": "the page file",
    "el archivo de hibernacion": "the hibernation file",
    "el archivo de intercambio": "the swap file",
    "el volcado de fallos del sistema": "the system crash dump",
    "la configuracion de Claude Code, que es donde viven las reglas que "
    "limitan a Jarvis":
        "the Claude Code configuration, which is where the rules that "
        "limit Jarvis live",
    "la configuracion de Claude Code": "the Claude Code configuration",
    "el binario de Claude Code": "the Claude Code binary",
    # --- las zonas opcionales, con SU COSTE (JC-0007) ---
    # El coste es lo que hace que la eleccion sea informada. Traducirlo a
    # medias dejaria al usuario marcando una casilla sin saber que pierde.
    "datos de aplicaciones instaladas para todo el equipo":
        "data of applications installed for the whole machine",
    "Jarvis no podra instalar ni actualizar programas que guarden ahi "
    "(chocolatey, Docker, controladores).":
        "Jarvis will not be able to install or update programs that store "
        "things there (chocolatey, Docker, drivers).",
    "tus documentos": "your documents",
    "Jarvis no podra leer ni escribir nada ahi: ni buscar un PDF ni "
    "guardarte un resumen.":
        "Jarvis will not be able to read or write anything there: neither "
        "find a PDF nor save you a summary.",
    "tu escritorio": "your desktop",
    "Jarvis no podra dejarte archivos a la vista ni leer lo que sueltes "
    "ahi.":
        "Jarvis will not be able to leave you files in plain sight nor "
        "read whatever you drop there.",
    "tus fotos": "your pictures",
    "Jarvis no podra mirar ni organizar imagenes.":
        "Jarvis will not be able to look at or organise images.",
}

# Los que llevan un trozo variable dentro. Se resuelven con el patron
# porque el nombre del servidor o la ruta los pone la accion, no
# nosotros: buscarlos por igualdad no casaria nunca.
MOTIVOS_PATRON: tuple[tuple[str, str], ...] = (
    (r"^el servidor MCP '(.*)' no esta en la lista blanca$",
     "the MCP server '{}' is not on the whitelist"),
    (r"^el servidor MCP '(.*)' esta prohibido$",
     "the MCP server '{}' is forbidden"),
    (r"^lo pide el servidor MCP '(.*)'$",
     "the MCP server '{}' is asking for it"),
    (r"^el servidor MCP '(.*)' esta autorizado$",
     "the MCP server '{}' is authorised"),
    (r"^(.*) es zona privada y no se toca$",
     "{} is a private zone and is not touched"),
    (r"^(.*) es zona de sistema y no se escribe$",
     "{} is a system zone and is not written to"),
    # El segundo Windows de `E:` -- el que una lista a mano habria dejado
    # al descubierto -- pega este sufijo a cualquier motivo de zona.
    (r"^(.*), en un Windows que NO es el que arranca$",
     "{}, on a Windows that is NOT the one that boots"),
    (r"^'(.*)' no es una politica$", "'{}' is not a policy"),
    # --- los errores de validar un ajuste, que se leen al GUARDAR ---
    # Llevan dentro la etiqueta del ajuste, que ya viene traducida
    # porque `guardar()` usa el catalogo traducido. Ver alli el porque.
    (r"^No existe el ajuste '(.*)'\.$", "There is no setting '{}'."),
    (r"^'(.*)' es un si o un no\.$", "'{}' is a yes or a no."),
    (r"^'(.*)' tiene que ser un numero\.$", "'{}' has to be a number."),
    (r"^'(.*)' es una lista\.$", "'{}' is a list."),
    (r"^'(.*)' no puede bajar de (.*)$", "'{}' cannot go below {}"),
    (r"^'(.*)' no puede pasar de (.*)$", "'{}' cannot go above {}"),
    (r"^'(.*)' no es una opcion valida de '(.*)'\. Hay: (.*)$",
     "'{}' is not a valid option of '{}'. There are: {}"),
    (r"^YAML invalido en (.*)$", "Invalid YAML in {}"),
    (r"^(.*) deberia ser un mapa de clave a valor\.$",
     "{} should be a key-to-value map."),
    (r"^(.*) deberia tener una lista `(.*)`\.$",
     "{} should have a `{}` list."),
    (r"^Entrada que no es un mapa: (.*)$", "Entry that is not a map: {}"),
    (r"^Entrada sin alias o sin carpeta en (.*)$",
     "Entry with no alias or no folder in {}"),
    (r"^Entrada sin `nombre` en (.*)$", "Entry with no `nombre` in {}"),
    (r"^'(.*)' no es una politica valida en (.*)\. Hay: (.*)$",
     "'{}' is not a valid policy in {}. There are: {}"),
)

_MOTIVOS_COMPILADOS = tuple(
    (re.compile(patron), ingles) for patron, ingles in MOTIVOS_PATRON)


def mensaje(texto: str, a: str | None = None,
            config_dir: Path | None = None) -> str:
    """Cualquier texto que el servidor manda a la pagina.

    Es `motivo` mas el resto: estados del suelo, errores de guardado y
    los motivos y COSTES de las zonas. Se resuelve en dos pasadas porque
    el sufijo del segundo Windows -- ", en un Windows que NO es el que
    arranca" -- se pega a un motivo que ya estaba en la tabla: sin
    volver a mirar, la mitad de las zonas de `E:` saldrian a medias.
    """
    cual = a or idioma(config_dir)
    if cual != "en" or not texto:
        return texto
    directo = SERVIDOR_EN.get(texto) or MOTIVOS_EN.get(texto)
    if directo:
        return directo
    for patron, plantilla in _MOTIVOS_COMPILADOS:
        marca = patron.match(texto)
        if marca:
            dentro = [mensaje(g, cual, config_dir) for g in marca.groups()]
            return plantilla.format(*dentro)
    return texto


def motivo(texto: str, a: str | None = None,
           config_dir: Path | None = None) -> str:
    """El motivo de una puerta, en el idioma que se pida.

    Un motivo que no este traducido se devuelve TAL CUAL, en español. Es
    la salida honesta y ademas la unica aceptable aqui: dejar en blanco
    la razon por la que se pide permiso convertiria la pregunta en un
    "¿lo autorizo?" sin objeto, o sea el consentimiento reflejo que
    JC-0002 existe para impedir.
    """
    cual = a or idioma(config_dir)
    if cual != "en" or not texto:
        return texto
    exacto = MOTIVOS_EN.get(texto)
    if exacto:
        return exacto
    for patron, plantilla in _MOTIVOS_COMPILADOS:
        marca = patron.match(texto)
        if marca:
            return plantilla.format(*marca.groups())
    return texto


# ----------------------------------------------------------------------
#  4. La maquinaria
# ----------------------------------------------------------------------


def idioma(config_dir: Path | None = None) -> str:
    """El idioma de la pantalla. `es` ante cualquier duda.

    Se lee de los ajustes en cada llamada y no se guarda en memoria: son
    dos accesos a un YAML pequeño, y a cambio cambiar el idioma se nota
    sin reiniciar nada.
    """
    try:
        from nucleo.ajustes import valor_de

        elegido = str(valor_de("ui.idioma", "es", config_dir) or "es")
    except Exception:  # noqa: BLE001 - un ajustes.yaml roto no puede
        # dejar la consola sin servir: es la pantalla desde la que se
        # arregla.
        return "es"
    return elegido if elegido in IDIOMAS else "es"


def texto(clave: str, defecto: str, config_dir: Path | None = None) -> str:
    """Un texto NUESTRO por su clave, o el original en español.

    "Nuestro" quiere decir que vive en codigo de este proyecto -- el
    catalogo de ajustes, la bandeja, los cuadros de la carcasa --, y por
    eso se puede pedir por un identificador estable. La copia de las
    paginas no puede: vive en un HTML y se indexa por la cadena, que es
    lo que permite sacarla del archivo en vez de copiarla a mano.
    """
    if idioma(config_dir) != "en":
        return defecto
    return AJUSTES_EN.get(clave, defecto)


def de_ajuste(clave: str, defecto: str, config_dir: Path | None = None) -> str:
    """El nombre viejo de `texto`, que es lo que llama `nucleo/ajustes.py`."""
    return texto(clave, defecto, config_dir)


def _patron(clave: str) -> re.Pattern[str]:
    """Donde puede aparecer una cadena SIENDO texto y no codigo.

    Los espacios de DENTRO se vuelven `\\s+` porque un parrafo escrito en
    cuatro lineas indentadas del HTML es una sola frase, y el que la
    escribio no eligio donde partirla.

    >>> Y LOS DE LOS EXTREMOS SE TRATAN DISTINTO SEGUN DONDE ESTE <<<
    Esto costo la mitad de la traduccion, y el sintoma fue exactamente el
    que reporto el usuario: los rotulos cortos salian en ingles y los
    PARRAFOS LARGOS seguian en español. La primera version exigia
    `>texto<` pegado, y en el HTML un parrafo se escribe asi:

        <p>
          Jarvis trabaja sobre la carpeta que le has dado...
        </p>

    o sea que entre el `>` y la primera letra hay un salto de linea y dos
    espacios de indentacion. Ningun parrafo casaba nunca. Y como una
    clave sin traducir se sirve tal cual, no habia error en ningun sitio:
    solo media pantalla en español.

    Asi que el nodo de texto lleva `\\s*` SIEMPRE -- ese espacio lo
    colapsa el navegador y no significa nada --, y el literal entre
    comillas NO: ahi hay claves que son trozos de frase (" de ",
    "Guardado. ") y comerse su espacio juntaria las palabras al
    concatenar.
    """
    trozos = [re.escape(t) for t in clave.split()]
    flexible = r"\s+".join(trozos)
    izq = r"\s*" if clave[:1].isspace() else ""
    der = r"\s*" if clave[-1:].isspace() else ""
    return re.compile(
        "(?:"
        rf">\s*{flexible}\s*<"
        "|"
        rf'"{izq}{flexible}{der}"'
        "|"
        rf"'{izq}{flexible}{der}'"
        ")")


_PATRONES: dict[str, re.Pattern[str]] | None = None


def _patrones() -> dict[str, re.Pattern[str]]:
    global _PATRONES
    if _PATRONES is None:
        _PATRONES = {clave: _patron(clave) for clave in PAGINAS_EN if clave.strip()}
    return _PATRONES


PANTALLA_DESPACHO: dict[str, str] = {
    # --- la consola ---
    "CANALES": "Como te avisa",
    # `TE DEJO` ya esta en segunda persona, pero en MAYUSCULAS de rotulo
    # tecnico. En el tema de quien no ha abierto una terminal, el resto
    # de la columna dice "Como te avisa" y "Lo que no puede tocar": dejar
    # este a gritos rompe la voz de la pantalla entera. Se vio en una
    # captura, no en un test.
    "TE DEJO": "Lo que te ha dejado",
    "PERIMETRO": "Lo que no puede tocar",
    "ZONAS SELLADAS": "carpetas protegidas",
    # >>> DECIA "Cuanto le queda hoy" Y DESDE EL 2026-09-04 ES AL REVES <<<
    # Las dos barras de dentro pasaron a decir lo GASTADO (el usuario se
    # quedo sin sesion leyendo un "QUEDA 3 %" con la barra casi vacia),
    # asi que un titulo que promete lo que queda encima de dos cifras que
    # dicen lo consumido es la misma confusion otra vez, y en el tema
    # escrito precisamente para quien no lee cifras tecnicas.
    "CARGA": "Cuanto lleva gastado",
    "VENTANAS UTILES": "Ratos utiles que quedan",
    "REGISTRO DE TRANSMISION": "Lo que Jarvis ha hecho",
    # --- los ajustes ---
    "TUS PROYECTOS": "Tus carpetas de trabajo",
    "AVISARME POR TELEGRAM": "Avisarme al movil",
    "SERVIDORES MCP": "Programas conectados",
}
"""La copia del tema `despacho`, que es la unica que cambia de PALABRAS.

>>> POR QUE ESTE TEMA NECESITA UNA CAPA DE TEXTO Y LOS OTROS NO <<<
Los otros tres se distinguen por como se ven. `despacho` se distingue por
QUIEN LO USA: gente de administracion que no ha abierto una terminal. Y
media docena de rotulos de esta pantalla no son castellano, son los
nombres de NUESTRO codigo -- "PERIMETRO", "ZONAS SELLADAS", "REGISTRO DE
TRANSMISION". Ya paso una vez con la pagina de zonas, y el usuario lo
dijo en su momento: esa parte de la pantalla no se entendia casi nada.
Lo que fallaba no era el sitio, era el vocabulario.

>>> Y ES UNA CAPA, NO UN RENOMBRADO <<<
En `hacker` y en `nexo` "PERIMETRO" esta bien: ahi el rotulo tecnico es
parte de la identidad, y quien elige esos temas sabe lo que es. Cambiarlo
en los cuatro habria arreglado un tema y aguado los otros tres.

>>> LO QUE NO ENTRA AQUI, Y NO ES UN OLVIDO <<<
Ni una palabra de la PUERTA. Ahi el rotulo tecnico -- la herramienta, la
ruta, la orden cruda -- es el contenido, no el envoltorio: es donde se
CONSIENTE, y suavizarlo seria pedir permiso para otra cosa distinta de
la que se va a ejecutar. Lo que `despacho` le añade a la puerta es
contexto (el rotulo del crudo, la consecuencia de cada boton), nunca
menos verdad.
"""

_PATRONES_TEMA: dict[str, dict[str, re.Pattern[str]]] = {}


def _patrones_tema(tema: str) -> dict[str, re.Pattern[str]]:
    if tema not in _PATRONES_TEMA:
        copia = COPIA_POR_TEMA.get(tema, {})
        _PATRONES_TEMA[tema] = {c: _patron(c) for c in copia if c.strip()}
    return _PATRONES_TEMA[tema]


COPIA_POR_TEMA: dict[str, dict[str, str]] = {"despacho": PANTALLA_DESPACHO}
"""Que temas cambian la copia. Los que no estan aqui no cambian nada, y
`jarvis` no puede estar nunca: es la pantalla que ya estaba aceptada."""


def traducir_tema(html: str, tema: str | None) -> str:
    """El HTML con la copia del tema, si ese tema tiene copia propia.

    >>> CORRE ANTES QUE `traducir_pagina`, Y NO AL REVES <<<
    Las dos usan el mismo mecanismo de sustitucion, asi que el orden
    decide que diccionario hay que mantener. Yendo el tema primero, el
    ingles solo tiene que conocer las frases NUEVAS (estan marcadas en
    `PAGINAS_EN`). Al reves haria falta un diccionario despacho-ingles
    entero y separado, o sea cuatro tablas en vez de dos.
    """
    copia = COPIA_POR_TEMA.get(tema or "", {})
    if not copia:
        return html
    patrones = _patrones_tema(tema or "")
    # De la mas larga a la mas corta, por lo mismo que en
    # `traducir_pagina`: una clave corta que sea prefijo de otra larga se
    # comeria su principio y dejaria la larga sin casar.
    for clave in sorted(patrones, key=len, reverse=True):
        nuevo = copia[clave]

        def cambia(m: re.Match[str], nuevo: str = nuevo) -> str:
            entero = m.group(0)
            # Se respeta el delimitador con el que se encontro.
            return entero[0] + nuevo + entero[-1]

        html = patrones[clave].sub(cambia, html)
    return html


def traducir_pagina(html: str, a: str = "en") -> str:
    """El HTML servido, con su copia en el idioma pedido.

    >>> DE LA MAS LARGA A LA MAS CORTA, Y NO ES UN DETALLE <<<
    "ESTADO" es un prefijo de "ESTADO —/06". Empezando por las cortas, la
    primera se comeria el principio de la segunda y dejaria un
    "STATE —/06" partido en "STATE" + "—/06" que ya no casa con nada.
    """
    if a != "en":
        return html
    for clave in sorted(_patrones(), key=len, reverse=True):
        ingles = PAGINAS_EN[clave]
        patron = _patrones()[clave]

        def cambia(m: re.Match[str], ingles: str = ingles) -> str:
            entero = m.group(0)
            # Se respeta el delimitador con el que se encontro: `>...<`,
            # comillas dobles o simples. Cambiarlo romperia el HTML o el JS.
            return entero[0] + ingles + entero[-1]

        html = patron.sub(cambia, html)
    return html


def traducir_catalogo(ajustes: list[Any], config_dir: Path | None = None) -> list[Any]:
    """Los `Ajuste` con sus textos en el idioma de la pantalla.

    Se hace AQUI y no en `nucleo/ajustes.py` para que aquel archivo siga
    leyendose como lo que es: el catalogo con el porque medido de cada
    numero, en el idioma en que se penso. Un `t(...)` alrededor de cada
    cadena habria enterrado ese razonamiento entre llamadas.

    >>> LOS NOMBRES DE DISPOSITIVO NO SE TRADUCEN <<< "un enrutador de audio virtual Out
    A1" lo escribio el fabricante del aparato: es contenido observado,
    y traducirlo dejaria al usuario buscando en la lista
    de Windows un nombre que Windows no usa. Solo se traduce el alias
    nuestro, el de "el que tenga Windows puesto".
    """
    if idioma(config_dir) != "en":
        return ajustes

    from dataclasses import replace

    fuera = []
    for a in ajustes:
        cambios: dict[str, Any] = {}
        for campo in ("etiqueta", "ayuda", "aviso"):
            actual = getattr(a, campo)
            if not actual:
                continue
            traducido = AJUSTES_EN.get(f"{a.clave}.{campo}")
            if traducido:
                cambios[campo] = traducido
        if a.unidad:
            unidad = AJUSTES_EN.get(f"unidad.{a.unidad}")
            if unidad:
                cambios["unidad"] = unidad
        if a.opciones:
            cambios["opciones"] = [
                {**o, "etiqueta": _opcion(a.clave, o)} for o in a.opciones
            ]
        fuera.append(replace(a, **cambios) if cambios else a)
    return fuera


def _opcion(clave: str, opcion: dict[str, str]) -> str:
    """La etiqueta de una opcion, si es NUESTRA. Ver `traducir_catalogo`."""
    propia = AJUSTES_EN.get(f"{clave}.opcion.{opcion.get('valor', '')}")
    if propia:
        return propia
    etiqueta = opcion.get("etiqueta", "")
    # El alias del dispositivo del sistema: "El que tenga Windows puesto
    # (ahora: X)". Se traduce la frase y se deja X tal cual.
    marca = re.match(r"El que tenga Windows puesto \(ahora: (.*)\)$", etiqueta)
    if marca:
        return AJUSTES_EN["audio.el_de_windows"].format(marca.group(1))
    return etiqueta
