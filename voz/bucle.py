"""El bucle: la voz conectada al puente. La costura del fork.

    wake -> aviso -> VAD -> STT -> Sesion.mandar()
                                        |
    TTS <- para un oido <- Fin <---------+
                            |
                            +-- y vuelve a escuchar SIN pedir la palabra
                                (JC-0012). Si no dices nada, se acabo la
                                conversacion y se duerme.

Hasta ahora `voz/` y `puente/` existian sin hablarse. Esto es lo que los
une, y es el momento en el que Jarvis deja de ser dos mitades.

>>> ESTE MODULO NO CONSUME `sesion.eventos()`, Y NO ES UN CAPRICHO <<<
`Sesion.eventos()` es UNA cola con UN consumidor: quien saca un evento se
lo lleva. La consola ya bombea de ahi (`Consola.bombear`), asi que si la
voz tirase tambien, cada evento caeria en uno de los dos AL AZAR -- la
consola pintaria la mitad de las respuestas y la voz locutaria la otra
mitad, y por fuera pareceria un problema de red. Por eso la voz es un
OYENTE: la consola le pasa el evento ya tipado y sigue con lo suyo.

>>> DOS HILOS, Y CADA UNO TIENE SU RAZON <<<
    "la voz"     wake, orden, y locutar lo que vuelve.
    "el oido"    SOLO paradas, y solo mientras Jarvis trabaja o habla.
Podrian ser uno, y entonces el "para" tendria que esperar a que acabase
de hablar para ser escuchado -- justo cuando mas falta hace (JC-0011).
Que sean dos es lo que hace verdad la frase "apagada para ordenes
nuevas, nunca para parar".

Los dos comparten el STT con un cerrojo: por estado nunca lo quieren a
la vez, pero "nunca" sin cerrojo es "casi nunca" en cuanto alguien toque
el ciclo.

>>> CUANTO SE LOCUTA: TODO, POR DECISION DEL USUARIO <<<
JC-0004 decidio locutar una o dos frases y dejar el detalle en la
consola. Usandolo, el usuario pidio lo contrario -- "quiero que diga
siempre todo el texto" --, y manda el usuario. `limite_hablado=None` es
el defecto; `-m puente ... --voz --resumir` vuelve al resumen.
Lo unico que no se locuta ni asi son los bloques de codigo: se dice que
estan y donde mirarlos. `voz/resumen.py` sigue haciendo la limpieza de
markdown, que es ruido puro para un oido.

>>> Y SI LA RESPUESTA ACABA PREGUNTANDO, SE SIGUE ESCUCHANDO <<<
Sin pedir otra vez la palabra de activacion. El disparador NO es
`AskUserQuestion` -- se midio que casi nunca llega: Claude Code pregunta
en prosa y cierra el turno --, sino que la respuesta deje una pregunta
en pie. Ver `voz/resumen.py::pregunta_final`.

>>> LA PUERTA SE PIDE Y SE CONTESTA HABLANDO (JC-0002) <<<
La frase sale de `voz/permiso.py`, derivada de la MISMA `Decision` que
pinta la consola: si las dos formas divergieran, se aprobaria una cosa y
se ejecutaria otra. Y el silencio NO es un no -- la puerta se queda
pendiente, porque la sesion espera indefinidamente (medido) y sobre esa
espera se construye el escalado de JC-0006.
"""

from __future__ import annotations

import contextlib
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from puente.protocolo import (
    Evento,
    Fin,
    Limite,
    Pregunta,
    Puerta,
    Reintento,
    SeguidorDeTarea,
    Texto,
    UsoHerramienta,
)
from voz.ciclo import Ciclo, Estado, Reaccion
# >>> TODO LO QUE JARVIS DICE PASA POR AQUI (JC-0018) <<<
# El alias es corto porque aparece treinta veces: `self.decir(_f("vale"))`
# se lee igual de bien que la cadena que habia, y ademas dice DONDE esta
# el texto. Una clave que no exista revienta al llamarla, que es lo que
# se quiere: una frase muda no se distingue de un cuelgue.
from voz.idioma import frase as _f
from voz.vad import Cierre
# Se importa con nombre propio: `voz.resumen` y `voz.narracion` tienen
# los dos un `para_un_oido` y NO hacen lo mismo -- uno resume una
# respuesta, el otro filtra un comentario al margen. Dejarlos con el
# mismo nombre aqui seria pedir que alguien llame al que no es.
from voz.narracion import para_un_oido as narrar_para_un_oido
from voz.resumen import para_un_oido, pregunta_final
from voz.senales import Senales

# >>> JC-0013 CAMBIO QUE MIDE ESTE NUMERO, Y POR ESO CAMBIO DE NOMBRE <<<
# Antes era VENTANA_ORDEN_S: lo que duraba la grabacion, fija. Con una
# ventana fija, hablar mas de esos segundos te cortaba a mitad de frase
# SIEMPRE -- no a veces, y por eso pasaba tambien sin ruido de fondo.
# Ahora la grabacion la cierra el usuario callandose
# (`voz/vad.py::FinDeTurno`), y lo unico que queda por fijar es la
# PACIENCIA: cuanto se espera a que empieces antes de darlo por vacio.
# Cuatro segundos porque es lo que se venia dando de hecho.
ESPERA_ORDEN_S = 4.0

# Cuanto se graba de una vez mientras se escuchan paradas. Corta a
# proposito: es el retraso maximo entre decir "para" y que se mire, y
# `small` tarda ~1,7 s en transcribir, asi que bajarla mas no acelera
# nada -- solo transcribe mas veces lo mismo.
#
# >>> ESTA SE QUEDA FIJA, Y NO ES UN OLVIDO DE JC-0013. <<<
# El oido no dicta: SONDEA. Tiene que volver una y otra vez con lo que
# haya, diga algo el usuario o no. Cerrar "cuando deje de hablar" aqui
# significaria quedarse escuchando mientras nadie habla, que es justo lo
# contrario de lo que hace falta -- y ademas convertiria la ventana de
# una parada en indefinida, cuando su valor entero es que es corta.
VENTANA_PARADA_S = 3.0

# Cuanto se espera DESPUES de una respuesta (JC-0012). Mas larga que la
# de una orden a proposito: ahi ya has decidido hablar, y aqui tienes que
# decidir si sigues la conversacion. Seis segundos son el punto de
# partida y esta escrito que lo son -- lo que decide el numero es cuanto
# tardas de verdad en arrancar cuando SI quieres seguir, y eso solo se
# sabe usandolo.
# JC-0013 lo deja MAS limpio que antes: estos seis segundos ya solo son
# la espera a que arranques. Si arrancas, hablas lo que quieras; si no,
# la ventana se cierra sola y no se comio seis segundos de reloj.
ESPERA_SEGUIMIENTO_S = 6.0

# Cada cuanto el wake word suelta el microfono para mirar si le han
# pedido parar. NO es la latencia de la palabra -- esa la da el modelo,
# trama a trama -- sino cada cuanto hay un hueco.
#
# >>> Y HAY HUECO, ESTA MEDIDO: 44 ms POR VUELTA <<<
# Abrir y cerrar el `InputStream` del microfono USB cuesta 44 ms de mediana
# (2026-08-25, seis tomas: 35-63 ms). Durante ese rato NO SE OYE NADA, y
# una "hey jarvis" que caiga justo ahi se pierde entera y en silencio,
# que es la forma de fallo que este proyecto persigue desde el principio.
#     vuelta de  1 s  ->  4,4 % del tiempo sordo
#     vuelta de 30 s  ->  0,15 %
# Por eso 30 y no 1. Lo que se paga a cambio es que `parar()` puede
# tardar hasta media vuelta en que el hilo se entere; como es demonio, no
# retrasa el cierre del proceso.
VUELTA_WAKE_S = 30.0


@dataclass
class Cuenta:
    """Lo que ha pasado, en cifras que se puedan leer despues."""

    ordenes_mandadas: int = 0
    piezas_mencionadas: int = 0
    """Cuantas veces la voz ha dicho "te he dejado ...".

    En CERO despues de un turno que escribio archivos significa una de
    dos, y las dos importan: o la respuesta ya los nombraba todos --
    bien, el filtro hace su trabajo -- o el panel no se esta enterando de
    lo que produce la sesion. Se distinguen mirando la pantalla.
    """
    proyectos_abiertos: int = 0
    colas_atendidas: int = 0
    """Cuantas veces un cambio de proyecto traia ademas una orden.

    En CERO despues de decir "ve al proyecto X y haz Y" significa que la
    cola se volvio a perder, y el sintoma en pantalla es el de siempre:
    Jarvis abre la carpeta y pregunta "hola, en que nos quedamos?".
    """
    apagados: int = 0
    """Veces que se apago hablando. Si esto sube y el usuario no lo
    pidio, "apagate" se esta oyendo donde no toca -- y es la unica de
    las tres palabras cuyo falso positivo no se deshace solo."""
    ventana_movida: int = 0
    """Veces que se enseño o escondio la ventana hablando."""
    """Veces que se cambio de proyecto hablando (ADR-0029)."""
    paradas: int = 0
    paradas_ajenas: int = 0
    """De las paradas, cuantas NO vinieron de la voz (hoy: la tecla Esc).

    Separado a proposito: si el usuario acaba parando siempre con Esc, es
    que el "para" hablado no le esta funcionando, y ese numero es lo
    unico que lo distingue de que simplemente prefiera el teclado.
    """
    tirado_al_parar: int = 0
    """Eventos que quedaban en el buzon al parar y se tiraron sin
    locutar. Si sube mucho, es que la narracion va por detras de lo que
    de verdad esta pasando -- mirar `narraciones_tarde` tambien."""
    callado_por_parada: int = 0
    """Frases que NO se dijeron porque el turno estaba parado. En cero
    despues de usar el "para" significaria que la guarda no se dispara,
    o sea que algo volvio a hablar por otro camino."""
    respuestas_locutadas: int = 0
    turnos_ajenos: int = 0
    """Turnos que llegaron sin abrirlos la voz: Telegram o la consola.

    Es el par de `ordenes_mandadas` (los que si abrio la voz), y van
    separados porque la pregunta que contestan es distinta: uno dice
    cuanto se usa Jarvis hablando, este cuanto se usa desde fuera. Si
    este sube y `respuestas_locutadas` no le sigue, es que se han vuelto
    a perder por el camino -- que es el fallo del 2026-08-29."""
    eventos_tirados: int = 0
    """Eventos cuya reaccion se rompio y se tiraron. LLEVABA SIN EXISTIR
    HASTA EL 2026-08-29, y esa ausencia es lo que hizo invisible el fallo
    de los turnos ajenos: `_atender_buzon` se tragaba el `CicloError` con
    un `continue` a secas. Las dos cosas -- "no se pudo locutar"
    no es "no habia nada que locutar", y una bandera no lo distinguiria
    de un turno tranquilo."""
    eventos_fuera_de_turno: int = 0
    """Eventos que llegaron con el ciclo dictando una orden nueva. Es la
    guarda de `Ciclo.trabajo_ajeno`, y deberia quedarse en cero: el hilo
    de la voz es uno solo. Si sube, hay dos hilos drenando el buzon."""
    tirado_al_abrir_turno: int = 0
    """Lo que quedaba del turno ANTERIOR cuando la voz abrio uno nuevo.

    Es la decision (d) del 2026-08-29: locutar la respuesta de hace dos
    turnos en mitad de otro es peor que no locutarla. Con el drenaje
    arreglado esto deberia ser raro -- el buzon se atiende en menos de un
    segundo --, asi que si crece es que algo lo esta volviendo a bloquear."""
    puertas_anunciadas: int = 0
    permisos_dados: int = 0
    permisos_denegados: int = 0
    permisos_sin_respuesta: int = 0
    """Los tres por separado, y el tercero es el que hay que vigilar: son las
    puertas que la voz dejo abiertas porque nadie
    contesto. Si ese numero crece, es que se esta preguntando cuando el
    usuario no esta delante -- que es justo lo que JC-0009 y JC-0006
    vienen a resolver."""
    preguntas_hechas: int = 0
    preguntas_contestadas: int = 0
    ventanas_abiertas: int = 0
    ventanas_con_habla: int = 0
    """>>> ESTOS DOS SON LA MEDIDA DE JC-0012, Y POR ESO VAN JUNTOS <<<
    La pregunta que decide si el modo conversacion vale la pena es
    "¿cuantas veces la ventana capta algo que no era para Jarvis?", y no
    se puede contestar con una bandera: hace falta el par. Una
    fraccion baja quiere decir que se esta abriendo el microfono para
    nada la mayor parte de las veces; una alta, que la conversacion
    sigue de verdad."""

    narraciones_dichas: int = 0
    narraciones_mudas: int = 0
    narraciones_tarde: int = 0
    """>>> LAS TRES POR SEPARADO, Y LA TERCERA ES LA QUE AVISA <<<
    `mudas` son comentarios de los que no quedo nada locutable tras el
    filtro; `tarde` son los que se saltaron porque el trabajo ya habia
    seguido. Si `mudas` crece mucho, el filtro esta demasiado apretado y
    hay que mirarlo con `-m eval.mirar_narracion`. Si crece `tarde`, es
    que Jarvis narra mas despacio de lo que Claude Code trabaja, y
    entonces lo que sobra es narracion, no filtro. Una sola cifra no
    distinguiria las dos cosas."""

    respuestas_habladas: int = 0
    """Veces que contestaste a una pregunta hecha EN PROSA, sin volver a
    decir la palabra de activacion. Es el camino comun; `preguntas_*` son
    el de la herramienta, y la resta entre esas dos son las que se
    quedaron colgadas esperando a que alguien mirase la pantalla."""
    vueltas_del_oido_soltadas: int = 0
    """Veces que el oido abandono su vuelta porque la voz necesitaba el
    microfono. Es la cifra de que `_con_el_microfono` esta trabajando: si
    se queda en cero mientras se contestan puertas por voz, el atajo no se
    esta tomando y el hueco de ~4,7 s sigue ahi."""
    no_te_he_oido: int = 0
    caracteres_locutados: int = 0
    caracteres_escritos: int = 0

    @property
    def fraccion_de_ventanas_utiles(self) -> float:
        """Que parte de las ventanas de seguimiento cazaron habla."""
        if not self.ventanas_abiertas:
            return 0.0
        return self.ventanas_con_habla / self.ventanas_abiertas

    @property
    def fraccion_locutada(self) -> float:
        """Que parte de lo que Claude Code escribio se llego a decir.

        Es la medida de si JC-0004 esta bien calibrado: cerca de 1 quiere
        decir que se esta locutando casi todo (y entonces sobra el
        resumen), y cerca de 0 que se dice tan poco que el usuario tiene
        que ir a la pantalla siempre.
        """
        if not self.caracteres_escritos:
            return 0.0
        return self.caracteres_locutados / self.caracteres_escritos


@dataclass
class Bucle:
    """La voz, conectada a una sesion del puente.

    `abrir_sesion` es lo que hace `Consola.asegurar_sesion`: el puente
    ARRANCA MUDO y la sesion no se abre hasta que hay una orden de
    verdad. La voz no puede saltarselo, porque es justo la propiedad que
    hace que hasta ese momento no haya salido nada de la maquina.
    """

    sesion: Any
    abrir_sesion: Callable[[], tuple[bool, str]] | None = None
    ciclo: Ciclo | None = None
    micro: Any = None
    altavoz: Any = None
    stt: Any = None
    tts: Any = None
    wake: Any = None
    seguimiento: bool = True
    """JC-0012: si tras CADA respuesta se sigue escuchando un rato.

    Con `False`, la escucha solo se abre cuando la respuesta deja una
    pregunta en pie -- que es JC-0011 y no depende de este ajuste: si
    Jarvis pregunta, escucha, se ponga esto como se ponga.
    """

    producido: Any = None
    """El registro de lo que la sesion deja detras (`puente.producido`).

    >>> ES EL MISMO OBJETO QUE PINTA LA CONSOLA, Y TIENE QUE SERLO <<<
    Llevar aqui una cuenta propia de los archivos escritos seria un
    SEGUNDO analizador del mismo flujo, y esos se separan: la pantalla
    diria una cosa y la voz otra, y el dia que discrepen no habria forma
    de saber cual miente. `None` significa que no hay panel -- una
    `Sesion` montada a mano en un test --, y entonces no se menciona
    nada, que es lo honesto.
    """

    narrar: bool = True
    """Si se locuta lo que Claude Code va contando mientras trabaja.

    Pedido el 2026-08-27: le da vividez, porque se nota que trabaja de
    verdad en vez de quedarse callado hasta el final.

    NACE ENCENDIDO, y es a proposito aunque el patron del proyecto sea el
    contrario. Los interruptores que nacen apagados son los que cambian
    lo que SALE de la maquina o lo que se hace en ella (proyectos por
    voz, Telegram, arrancar con Windows). Esto no manda nada, no escribe
    nada y no decide nada: solo dice en alto algo que ya estaba en la
    consola. Es el caso de "abrete", no el de proyectos. Se apaga con
    `--voz --sin-narracion`.
    """

    limite_hablado: int | None = None
    """Cuanto se locuta de cada respuesta. `None` = TODO.

    Es la decision del usuario del 2026-08-25, y va contra lo que decidio
    JC-0004 ("una o dos frases, el detalle en la consola"). Manda el
    usuario, pero la cifra que hay que tener delante es esta: la
    respuesta larga de las trazas son 2035 caracteres, ~145 segundos
    hablando. Se vuelve al resumen con `-m puente ... --voz --resumir`.
    """
    cuenta: Cuenta = field(default_factory=Cuenta)

    gestos: Any = None
    """Los tres gestos de la carcasa, en UN objeto: `nucleo.carcasa.Gestos`.

    >>> ERAN TRES CAMPOS AQUI, Y ESO ERA MEDIO FALLO (2026-09-05) <<<
    Los pone `escritorio/`, y los necesitan DOS consumidores: esta voz y
    la consola. Con un juego de atributos por consumidor, enchufar uno y
    olvidarse del otro da exactamente el fallo que reporto el usuario --
    "apagate" apagando dicho y yendose al cerebro escrito --, y sin un
    solo error. Un objeto por referencia: o los tienen los dos, o
    ninguno.

    >>> `None` NO SIGNIFICA "NO PUEDES PEDIRLO" <<<
    Significa que no hay carcasa: es lo que pasa lanzando `-m puente`
    desde una terminal. Y entonces Jarvis lo DICE, en vez de callarse
    como si no te hubiera oido -- que es la diferencia entre un asistente
    que no puede y uno que parece roto. Tampoco mata el proceso por su
    cuenta: hacerlo a lo bruto desde aqui dejaria la sesion de Claude
    Code sin cerrar, que es justo lo que "apagate" viene a evitar.
    """

    anunciar_turno: Callable[[str, str], None] | None = None
    """Como se le enseña al usuario lo que acaba de decir. Lo pone la
    consola (`Consola.anuncia_turno`). `None` = nadie esta pintando."""

    def __post_init__(self) -> None:
        self._buzon: queue.Queue[Evento] = queue.Queue()
        self.tarea = SeguidorDeTarea()
        """Que se esta haciendo ahora, y de paso que texto era narracion.

        La regla ("un `Texto` es narracion si DESPUES viene una
        herramienta") vive en `puente/protocolo.py` y no aqui, porque la
        necesitan dos: esto para locutarla y la consola para su barra de
        TAREA. Escrita dos veces acabarian divergiendo, y el sintoma
        seria que la barra dice una cosa y el altavoz otra."""
        self._parar = threading.Event()
        self._hay_correo = threading.Event()
        """Puesto, hay algo en el buzon y la ronda del wake se suelta.

        >>> ES LA MITAD (c) DEL FALLO DEL 2026-08-29 <<<
        `_vivir` drena el buzon y despues se mete 30 s en la ronda de la
        palabra de activacion; ahi dentro nadie drena, asi que una
        respuesta de un turno del movil esperaba hasta medio minuto al
        altavoz. No se arregla bajando los 30 s -- ese numero lo fija que
        abrir el `InputStream` cuesta 44 ms y en ese hueco se es sordo --
        sino soltando la ronda cuando de verdad hay algo que decir.

        SE LIMPIA AL EMPEZAR A DRENAR, NO AL ACABAR: si llega un evento
        mientras se drena, la bandera se vuelve a poner y la siguiente
        ronda se suelta enseguida. Al reves se perderia justo ese aviso y
        el evento esperaria la ronda entera."""
        self._callar = threading.Event()
        """Puesto, corta lo que se este locutando AHORA (ver `decir`).

        >>> SE SUSTITUYE AL PARAR, NO SE LIMPIA <<< Ver `_parar_el_turno`:
        limpiarlo dejaba sin efecto la cancelacion de la frase que ya
        estaba sonando, porque quien la mira es el callback de PortAudio
        y no se le puede pedir que mire justo en ese milisegundo."""
        self._parado = threading.Event()
        """Puesto, el turno lo paro el usuario y NO se dice nada mas de el.

        >>> NO ES LO MISMO QUE `_callar`, Y CONFUNDIRLOS ERA MEDIA FUGA <<<
        `_callar` corta la frase que suena AHORA. Esto calla lo que venga
        DESPUES: la narracion que quedaba en el buzon, el resto de la
        respuesta, la coletilla. Sin esto, cortar la frase en curso solo
        adelantaba la siguiente.

        Se limpia en `_anunciar`, o sea en cuanto el usuario vuelve a
        decir algo. Ese es el punto que comparten los TRES caminos que
        abren turno (wake, ritual y ventana de seguimiento): ponerlo en
        `_mandar` habria dejado fuera el de la ventana, que es el mas
        comun de la conversacion y el que ya se escapo una vez el 27."""
        self._stt_en_uso = threading.Lock()
        self._suelta_el_micro = threading.Event()
        """Puesto, el hilo del oido abandona su vuelta SIN terminarla.

        Existe porque el cerrojo de arriba solo reparte el microfono: no
        acorta la espera. Ver `_con_el_microfono`.
        """
        self._hilos: list[threading.Thread] = []
        self._aviso_de_red_dado = False
        self.ultimo_fallo: str = ""
        """Lo ultimo que se rompio, para que la consola pueda ensenarlo.

        Un asistente por voz que falla en silencio es indistinguible de
        uno que no te oye, y este proyecto ya sabe lo que cuesta esa
        confusion: 16 de los 23 endpoints de audio de esta maquina
        entregan silencio perfecto sin dar un solo error.
        """

    # --- montaje ----------------------------------------------------------

    def preparar(self) -> None:
        """Carga lo que falte. Separado de `arrancar` a proposito.

        Los modelos tardan segundos en cargar y aqui se ve donde se paga.
        Ademas deja construir un `Bucle` en un test sin tocar audio ni
        cargar Whisper: se le pasan las piezas ya hechas y esto no toca
        nada.
        """
        from voz.audio import ConfigAudio

        config = ConfigAudio.desde_config()
        if self.micro is None:
            self.micro = config.microfono()
        if self.altavoz is None:
            self.altavoz = config.altavoz()
        if self.ciclo is None:
            self.ciclo = Ciclo(senales=Senales(self.altavoz))
        if self.stt is None:
            from voz.stt import STT
            self.stt = STT()
        if self.tts is None:
            from voz.tts import TTS
            self.tts = TTS()
        if self.wake is None:
            from voz.wake import Wake
            self.wake = Wake()

    def arrancar(self, avisar_del_ruido: bool = True) -> None:
        """Dos hilos: la voz y el oido. Vuelve enseguida."""
        if self._hilos:
            raise RuntimeError("el bucle ya estaba arrancado")
        self.preparar()
        if avisar_del_ruido:
            # Decision 1 de JC-0011: un aviso honesto y UNA vez. No es
            # cortesia -- es lo unico que se puede hacer con un 9/20
            # tecleando que no sea prometer lo que no se cumple.
            # Se resuelve AL DECIRLO, no al importar: si no, arrancar
            # en un idioma y cambiar al otro dejaria este aviso -- el
            # primero que se oye -- congelado en el de antes.
            self.decir(_f("consejo_ruido"))
        for nombre, tarea in (("voz", self._vivir), ("oido", self._oido)):
            hilo = threading.Thread(target=tarea, name=f"jarvis-{nombre}",
                                    daemon=True)
            hilo.start()
            self._hilos.append(hilo)

    def parar(self, espera_s: float = 5.0) -> bool:
        """Pide a los dos hilos que se vayan. Devuelve si lo hicieron.

        Puede devolver False y no pasa nada: los hilos son DEMONIOS, asi
        que un `escuchar` a medias no retrasa el cierre del proceso. Se
        devuelve en vez de fingir que se paro todo, porque quien llame a
        esto para REARRANCAR la voz si necesita saberlo -- dos hilos
        escuchando el mismo microfono es un problema distinto y peor.
        """
        self._parar.set()
        for hilo in self._hilos:
            hilo.join(timeout=espera_s)
        vivos = [h for h in self._hilos if h.is_alive()]
        self._hilos = vivos
        return not vivos

    # --- lo que llega del puente ------------------------------------------

    def recibir(self, evento: Evento) -> None:
        """Lo llama la consola con el evento YA TIPADO.

        Solo encola. Locutar aqui bloquearia el hilo que bombea la sesion
        -- o sea que mientras Jarvis habla, la consola dejaria de pintar
        y las puertas dejarian de llegar. Un asistente que se queda sordo
        mientras habla es exactamente lo que JC-0011 vino a evitar.
        """
        self._buzon.put(evento)
        # Y se avisa al hilo de la voz, que puede estar a mitad de una
        # ronda de 30 s escuchando la palabra de activacion.
        self._hay_correo.set()

    # --- el hilo de la voz -------------------------------------------------

    def _vivir(self) -> None:
        while not self._parar.is_set():
            self._atender_buzon()
            if self.ciclo.escucha_la_palabra:
                self._esperar_la_palabra()
            else:
                time.sleep(0.1)

    def _esperar_la_palabra(self) -> None:
        """Escucha hasta que alguien la diga, y entonces abre el turno.

        La ronda se suelta antes de tiempo si llega algo al buzon: ver
        `_hay_correo`. Sin eso, un turno lanzado desde el movil o desde
        la consola espera hasta VUELTA_WAKE_S para llegar al altavoz.
        """
        try:
            for activacion in self.wake.escuchar(self.micro,
                                                 limite_s=VUELTA_WAKE_S,
                                                 cancelar=self._hay_correo):
                self._al_despertar(activacion)
                return
        except Exception as exc:  # noqa: BLE001
            # Un microfono que desaparece no puede tumbar el asistente en
            # silencio: se dice y se sigue intentando.
            self.ultimo_fallo = str(exc)
            self.decir(_f("perdi_microfono"))
            time.sleep(2.0)

    def _al_despertar(self, activacion: Any) -> None:
        self.ciclo.desperto()
        # Campana, los segundos para bajar el ruido, y pitido. Es el
        # corazon de JC-0011 y por eso lo hace el ciclo, no esto.
        with self._con_el_microfono():
            # >>> EL AVISO SUENA CON EL MICROFONO YA COGIDO <<<
            # Antes sonaba antes de pedir el cerrojo, y eso es decirle al
            # usuario "habla ya" mientras el microfono es de otro. Es el
            # mismo orden que ya seguian los otros tres sitios; este se
            # quedo atras y lo destapo el hallazgo de la puerta.
            self.ciclo.preparar_escucha()
            transcripcion = self.stt.escuchar_turno(
                espera_inicio_ms=ESPERA_ORDEN_S * 1000,
                dispositivo=self.micro)
        reaccion = self.ciclo.oido(transcripcion)

        if reaccion is Reaccion.ORDEN:
            dicho = transcripcion.texto.strip()
            # >>> LO PRIMERO, ANTES DE DECIDIR NADA: ENSEÑARLO <<<
            # Aqui, y no mas abajo, porque "abrete" y "apagate" no llegan
            # a mandarse y son justo donde una mala transcripcion se nota
            # mas. Ver `_anunciar`.
            self._anunciar(dicho, "voz")
            # Antes de mandarla: ¿es una orden SOBRE Jarvis? Las dos que
            # hay se miran de la mas barata a la mas cara. No colisionan
            # -- una exige nombrar la ventana y la otra la palabra
            # "proyecto" --, pero el orden lo deja fijado en vez de
            # depender de que siga siendo asi.
            if self._de_la_ventana(dicho):
                pass
            elif not self._cambiar_de_proyecto(dicho):
                self._mandar(dicho)
        elif reaccion is Reaccion.PARAR:
            # Se desperto y lo primero que dijo fue "cancela". No hay nada
            # que parar todavia, asi que solo se cierra el turno.
            self.decir(_f("vale"))
        else:
            # Tercera salida: se desperto, se grabo, y no habia
            # una orden de la que fiarse. Decirlo es lo que separa "no te
            # he oido" de que el asistente se quede callado y el usuario
            # no sepa si esta escuchando.
            self.cuenta.no_te_he_oido += 1
            self.decir(_f("no_te_oi_bien"))
            self.ciclo.termino()

    def _de_la_ventana(self, texto: str) -> bool:
        """Enseñar, esconder o APAGAR. Devuelve si se ocupo de la frase.

        >>> LO QUE DECIDE YA NO VIVE AQUI (2026-09-05) <<<
        Vive en `voz.ventana.atender`, y lo llaman la voz Y LA CONSOLA.
        Lo destapo el uso: las ordenes como "apagate" se interceptaban
        bien dichas y escritas se le pasaban directas a Claude.
        Es el hueco del 09-03 con otra forma, y se
        arregla igual: aqui se queda lo unico que no se puede compartir
        -- HABLAR --, y el cierre del turno de palabra, que tambien es de
        la voz. `_apagarse` se fue con esto: lo que hacia de mecanica
        (cortar el turno, mirar si hay carcasa) esta en el decisor, y lo
        que hacia de voz esta aqui abajo.
        """
        from voz.ventana import Hecho, atender

        r = atender(texto, self.gestos,
                    interrumpir=(self.sesion.interrumpir
                                 if self.sesion.viva else None))
        if not r.se_ocupo:
            return False

        if r.hecho is Hecho.SIN_CARCASA:
            # Tercera salida: no hay ventana ni carcasa. Se
            # dice; callarse pareceria que no te ha oido. Y son dos
            # frases distintas porque no se arreglan igual.
            self.decir(_f("no_puedo_apagarme") if r.es_el_final
                       else _f("sin_ventana"))
            self.ciclo.termino()
            return True

        if r.hecho is Hecho.ROTO:
            self.ultimo_fallo = r.error
            self.decir(_f("no_pude_mover_ventana"))
            self.ciclo.termino()
            return True

        if r.hecho is Hecho.APAGANDO:
            # >>> ESTA SE DESPIDE, Y LAS OTRAS DOS NO <<<
            # A "abrete" y "cierrate" se les contesta corto porque el
            # resultado se VE: la ventana aparece o desaparece delante.
            # Esta no se ve -- lo que se ve es que Jarvis deja de
            # contestar, que es identico a como se ve un cuelgue --, asi
            # que sin la despedida un "apagate" oido por error y un
            # Jarvis roto son indistinguibles.
            # El turno ya lo corto el decisor; aqui solo queda hablar, y
            # hablar ANTES de morir, que es todo el motivo de que
            # `atender` devuelva en vez de apagar el mismo.
            self.cuenta.apagados += 1
            self.decir(_f("hasta_luego"))
            self.ciclo.termino()
            try:
                self.gestos.apagar()
            except Exception as exc:  # noqa: BLE001
                self.ultimo_fallo = str(exc)
                self.decir(_f("no_pude_apagarme"))
            return True

        self.cuenta.ventana_movida += 1
        # Corto a proposito: es una accion que ya se ve. Un "he abierto
        # la ventana" mientras la ventana aparece delante es el asistente
        # contandote lo que estas mirando.
        self.decir(_f("aqui_estoy") if r.hecho is Hecho.MOSTRADA
                   else _f("vale"))
        self.ciclo.termino()
        return True

    def _cambiar_de_proyecto(self, texto: str) -> bool:
        """ADR-0029, pasos 1, 2 y 6. Devuelve si se ha ocupado de la frase.

        >>> LO QUE DECIDE YA NO VIVE AQUI (2026-09-03) <<<
        Vive en `voz.proyecto.atender`, y lo llaman la voz Y LA CONSOLA.
        Lo destapo el usuario: la misma frase daba resultados distintos
        dicha que escrita, porque la interceptacion estaba solo en este
        metodo. Aqui se queda lo unico que no se puede compartir --
        HABLAR --, y de paso el cierre del ciclo, que tambien es de la
        voz: la consola no tiene turno de palabra que cerrar.

        NO SE ABRE NADA SIN DECIR QUE CARPETA. Es la condicion 1 de
        ADR-0029 -- *"la puerta se cruza al ABRIR la sesion, y dice que
        proyecto y que carpeta"* --, y se cumple aqui abajo, diciendola
        en voz alta: `atender` devuelve el proyecto entero para que
        ningun canal pueda quedarse solo con el alias.
        """
        from voz.proyecto import Cambio, atender, primera_pregunta

        r = atender(texto, self.sesion)
        if not r.se_ocupo:
            return False

        if r.cambio is Cambio.SIN_NOMBRE:
            self.decir(_f("que_proyecto"))
        elif r.cambio is Cambio.DESCONOCIDO:
            self.decir(_f("proyecto_desconocido", r.nombre))
        elif r.cambio is Cambio.VARIOS:
            self.decir(_f("proyectos_varios", len(r.candidatos),
                          ", ".join(r.candidatos)))
        elif r.cambio is Cambio.SIN_CARPETA:
            self.decir(_f("proyecto_sin_carpeta", r.proyecto.alias))
        elif r.cambio is Cambio.ROTO:
            self.ultimo_fallo = r.error
            # Dos frases distintas para dos averias distintas: el
            # registro ilegible no se arregla como una sesion que no se
            # deja mover, y quien lo oiga tiene que poder distinguirlas.
            self.decir(_f("no_pude_cambiar_proyecto") if r.proyecto
                       else _f("proyectos_mal"))
        else:
            self.cuenta.proyectos_abiertos += 1
            # Se dice la CARPETA, no solo el alias: dos proyectos con
            # nombres parecidos es exactamente donde esto se equivoca
            # caro.
            self.decir(_f("abro_proyecto", r.proyecto.alias,
                          r.proyecto.carpeta))
            # >>> SI DIJISTE ALGO MAS, ESO MANDA (2026-09-01) <<<
            # La cola SUSTITUYE al ritual, no va delante: mandar las dos
            # serian dos turnos, y el segundo seria preguntarte "en que
            # nos quedamos" justo despues de haber hecho lo que pediste.
            # Y la cola SI es una frase tuya, asi que se anuncia como
            # tal -- al reves que el ritual, que se pinta como de Jarvis
            # porque lo escribimos nosotros.
            if r.cola:
                self.cuenta.colas_atendidas += 1
                self._anunciar(r.cola, "voz")
                self._mandar(r.cola)
                return True
            # Paso 6 del ritual: la primera pregunta.
            # El ritual NO es una frase del usuario EN EL SENTIDO DE LA
            # PANTALLA: se pinta como de Jarvis y no mueve la barra de
            # TAREA, porque esa barra existe para que compruebes que se
            # te entendio y aqui no hay nada que comprobar. Ponerlo como
            # "tu (voz)" fue el fallo de la primera version, y lo
            # corrigio el usuario mirandolo el 2026-08-27.
            #
            # >>> Y VA EN EL IDIOMA DE LA VOZ DESDE EL 2026-09-03 <<<
            # Aqui se mandaba la CONSTANTE, o sea "hola, en que nos
            # quedamos?" en español siempre. `primera_pregunta()` -- la
            # que mira `voz.idioma`, añadida con JC-0018 -- no la
            # llamaba NADIE: otro mando girando en el vacio, encontrado
            # el mismo dia que el umbral del wake word y de la misma
            # forma (existe la funcion buena y se sigue usando la de
            # antes). Con la voz en ingles, Jarvis abria un proyecto y
            # se preguntaba a si mismo en español.
            #
            # >>> Y DESDE EL 2026-09-05 LA ESCRIBE EL USUARIO <<<
            # Se le pasa el PROYECTO porque cada uno puede tener la suya;
            # la resolucion entera (proyecto / global / fabrica) vive en
            # `primera_pregunta` y NO se reparte entre los dos canales,
            # que es la leccion del 09-03.
            ritual = primera_pregunta(proyecto=r.proyecto)
            if ritual:
                self._anunciar(ritual, "ritual")
                self._mandar(ritual)
                return True
            # >>> VACIO ES UNA RESPUESTA: "abre y no digas nada" <<<
            # Y entonces NO hay turno, asi que hay que cerrar el turno de
            # palabra aqui mismo. Sin esto el ciclo se quedaria en
            # TRABAJANDO esperando un `Fin` que no va a llegar nunca, y
            # con el ciclo atascado el wake word no vuelve a abrir nada:
            # sordera total y sin un solo sintoma. Es el mismo fallo del
            # que avisa la lista acotada de `trabajo_ajeno` (JC-0011).
            self.ciclo.termino()
            return True

        self.ciclo.termino()
        return True

    def _anunciar(self, texto: str, origen: str) -> None:
        """Enseña en pantalla algo que acaba de pasar por la voz.

        >>> SE ANUNCIA LO QUE DIJISTE, NO LO QUE SE MANDA <<<
        Y no son lo mismo, que es lo que fallo en la primera version
        (2026-08-27, mirandolo): se dijo "continua con el proyecto X",
        ADR-0029 lo intercepto, y en pantalla
        aparecio **"tu (voz): hola, en que nos quedamos?"** -- el ritual,
        que es lo que se manda, y no su frase, que es lo unico que el
        anuncio venia a enseñar. Anunciar en `_mandar` era anunciar en el
        sitio equivocado: hay frases que se mandan sin decirse (el
        ritual) y frases que se dicen sin mandarse ("abrete", "apagate").

        Asi que se anuncia donde nace: en cuanto hay TRANSCRIPCION y
        antes de decidir que se hace con ella. De paso, eso cubre las
        ordenes SOBRE Jarvis, que es justo donde una mala transcripcion
        se nota mas -- el "abritin" del 27 se habria visto al instante.

        `origen` no es decorativo: solo `voz` mueve la barra de TAREA,
        porque la barra existe para que compruebes que se te entendio, y
        una frase nuestra ahi no comprueba nada.
        """
        if not texto.strip():
            return
        # >>> AQUI SE LEVANTA EL SILENCIO DE UNA PARADA <<<
        # Y aqui y no en `_mandar` porque este es el punto que comparten
        # los TRES caminos que abren turno; `_mandar` deja fuera el de la
        # ventana de seguimiento, que es el mas comun de la conversacion.
        # Semanticamente es lo que toca: has vuelto a hablar, o sea que
        # ya no estamos en el turno que mandaste parar.
        self._parado.clear()
        if origen == "voz":
            self.tarea.orden(texto, origen=origen)
        if self.anunciar_turno is None:
            return
        try:
            self.anunciar_turno(texto, origen)
        except Exception as exc:  # noqa: BLE001
            # Que la consola no pinte no puede impedir hablarle.
            print(f"  (no se pudo anunciar el turno: {exc})")

    def _mandar(self, texto: str) -> None:
        """Manda un turno. Anunciar es de quien tiene la frase original."""
        self._tirar_lo_viejo()
        if self.abrir_sesion is not None:
            abierta, detalle = self.abrir_sesion()
            if not abierta:
                # No se manda igualmente. Un asistente que sigue adelante
                # con el suelo roto parece protegido y no lo esta.
                self.decir(_f("no_pude_abrir_sesion"))
                self.ciclo.termino()
                return
        self.sesion.mandar(texto)
        self.cuenta.ordenes_mandadas += 1

    @contextlib.contextmanager
    def _con_el_microfono(self):
        """Coge el microfono AHORA, sin esperar a que el oido acabe.

        >>> EL CERROJO REPARTE EL MICROFONO; ESTO ACORTA LA ESPERA <<<
        No son lo mismo, y confundirlos costo el hallazgo del 2026-08-26:
        el usuario contestaba una puerta y no se le oia. La causa no era
        el reconocedor -- esperando al aviso entiende "no" a la primera --
        sino que entre que Jarvis callaba y el microfono se abria pasaban
        hasta ~4,7 s, MEDIDOS: la vuelta del oido son 3,0 s de grabacion
        mas 1,7-1,9 s de Whisper.

        Y NO ERA INTERMITENTE, era seguro para una puerta: el oido graba
        mientras Jarvis habla, o sea que su ventana viene llena de la voz
        del propio Jarvis. Con la sala callada el VAD la despacha en
        0,02 s y no se nota; justo detras de una peticion de permiso,
        SIEMPRE hay habla dentro y siempre se pagan los dos segundos de
        Whisper.

        Lo que hace esto es avisar al oido de que suelte la vuelta antes
        de pedir el cerrojo. La bandera se limpia en cuanto se tiene el
        microfono: solo sirve para atravesar la espera, no para dejar al
        oido apagado.
        """
        self._suelta_el_micro.set()
        try:
            with self._stt_en_uso:
                self._suelta_el_micro.clear()
                yield
        finally:
            self._suelta_el_micro.clear()

    # --- el hilo del oido: SOLO paradas ------------------------------------

    def _oido(self) -> None:
        """Lo unico que sigue encendido mientras Jarvis trabaja y habla.

        No manda ordenes: `ciclo.oido()` no devuelve ORDEN fuera de
        ESCUCHANDO, pase lo que pase por el microfono.
        """
        while not self._parar.is_set():
            if not self.ciclo.escucha_paradas:
                time.sleep(0.1)
                continue
            with self._stt_en_uso:
                if not self.ciclo.escucha_paradas:
                    # Cambio de estado mientras se esperaba el cerrojo.
                    continue
                # `cancelar` es lo que convierte esta vuelta en algo que se
                # puede abandonar. Sin el, quien necesite el microfono
                # espera a que termine: 3,0 s de grabacion mas 1,7-1,9 s de
                # Whisper, medidos. Ver `_con_el_microfono`.
                transcripcion = self.stt.escuchar(
                    segundos=VENTANA_PARADA_S,
                    dispositivo=self.micro,
                    cancelar=self._suelta_el_micro)
            if transcripcion.cierre == Cierre.ABORTADO.value:
                # La vuelta se solto a medias porque otro necesitaba el
                # microfono. NO se enruta: nadie ha mirado si habia habla
                # ahi dentro, asi que tratarlo como "no dijo nada" seria
                # inventarse la respuesta. Se vuelve a empezar.
                self.cuenta.vueltas_del_oido_soltadas += 1
                # Un respiro antes de volver a por el cerrojo. Sin el, si
                # el estado todavia dice "escucha paradas" mientras la voz
                # va a por el microfono, este bucle gira en vacio cogiendo
                # y soltando el cerrojo -- y le disputaria al hilo de la
                # voz justo lo que se le acaba de ceder.
                time.sleep(0.05)
                continue
            if self.ciclo.espera_respuesta:
                # >>> ESTO SE TIRA, Y HAY QUE TIRARLO <<<
                # Mientras se grababa, Jarvis termino de hablar y paso a
                # esperar TU respuesta. Este audio es de ANTES: en el
                # mejor caso es su propia voz. Enrutarlo ahora lo
                # contaria como respuesta tuya -- y en PREGUNTANDO
                # `oido()` devuelve RESPUESTA --, o sea que Jarvis se
                # habria contestado a si mismo.
                continue
            if self.ciclo.oido(transcripcion) is Reaccion.PARAR:
                self._parar_el_turno()

    def parar_el_turno(self, origen: str = "voz") -> bool:
        """Parar desde fuera de la voz. Hoy, la tecla Esc de la consola.

        >>> SE LLAMABA `parar` Y ESTABA SOMBREANDO AL OTRO `parar` <<<
        (Arreglado el 2026-09-02: al salir, Jarvis decia siempre "dale,
        paro", que es la frase de haber parado un turno con Esc y no la
        de apagarse.)
        `Bucle.parar(espera_s)` -- unas lineas mas arriba -- es APAGAR
        LOS HILOS, y lo llama `Montaje.cerrar()` al salir. Python se
        queda con la ultima definicion, asi que este de aqui la tapaba y
        salir de Jarvis hacia tres cosas mal a la vez: contaba una
        parada, cortaba el turno y **decia "Vale, paro"** en la cara del
        usuario... y NO paraba los hilos, que era lo unico que se le
        habia pedido.
        Es exactamente la colision que `Consola.parar_el_turno` ya tenia
        documentada desde el 2026-09-01 -- y ahi esta la leccion de
        siempre: se arreglo en un sitio y no se busco la misma forma en
        los demas. Se busca ahora, y con un test que barre el arbol
        entero por AST.

        >>> Y TIENE QUE PASAR POR AQUI, NO POR `sesion.interrumpir` <<<
        Esa llamada corta el TURNO y nada mas. El 2026-08-29 se descubrio
        que parar de verdad son CUATRO cosas -- callar la frase que ya
        suena, no decir lo que venia detras, vaciar el buzon de narracion
        y cortar el turno --, y que hacer solo la ultima deja a Jarvis
        recitando la respuesta de un trabajo que ya no existe. Quien
        aprieta Esc mientras habla espera exactamente lo contrario.

        Devuelve si habia algo vivo que parar. `False` no es un fallo: es
        que no habia turno en marcha.
        """
        self.cuenta.paradas_ajenas += origen != "voz"
        return self._parar_el_turno()

    def _parar_el_turno(self) -> bool:
        """El "para" de JC-0011, ya con dientes.

        `interrumpir` esta medido contra el binario (ver `Sesion`): el
        turno cierra en centesimas, la secuencia de herramientas se corta
        de verdad y la SESION SOBREVIVE con su contexto. O sea que parar
        no cuesta la conversacion.
        """
        self.cuenta.paradas += 1

        # >>> EL ORDEN IMPORTA: PRIMERO CALLARSE <<<
        # Lo que el usuario esta oyendo AHORA es la voz, y seguir
        # recitando la respuesta de algo que ya se ha parado es la peor
        # manera de decir que has obedecido.
        #
        # >>> Y HASTA EL 2026-08-29 ESTO NO CALLABA NADA <<<
        # Se reporto usandolo: al decir "para", a veces la voz seguia
        # sonando aunque el turno ya se hubiera parado. La version anterior
        # era `set()` / `interrumpir()` / `clear()`, y `interrumpir` solo
        # escribe una linea en la tuberia y vuelve -- no espera el ack --,
        # o sea que la bandera vivia MENOS DE UN MILISEGUNDO. Quien la
        # mira mientras suena el audio es el callback de PortAudio, que
        # corre cada 10-50 ms: casi nunca coincidia, y entonces el turno
        # se paraba pero la frase llegaba entera hasta el final. Encima
        # `decir` no esta serializado, asi que el "vale, paro" del hilo
        # del OIDO se solapaba con la respuesta que seguia recitando el
        # hilo de la voz. Eso es exactamente lo que se oia.
        #
        # La bandera no se limpia: se SUSTITUYE. Asi lo que ya estaba
        # sonando se queda cancelado para siempre -- por muy tarde que el
        # callback llegue a mirarla -- y lo que se diga a partir de ahora
        # estrena una limpia.
        self._parado.set()
        self._callar.set()
        habia = self.sesion.interrumpir()
        self.cuenta.tirado_al_parar += self._vaciar_buzon()
        self._callar = threading.Event()

        # La confirmacion es lo UNICO que se dice de un turno parado, y
        # por eso lleva el permiso explicito. Con la bandera nueva, un
        # segundo "para" tambien la corta a ella.
        self.decir(_f("vale_paro"), aunque_este_parado=True)
        return habia

    def _vaciar_buzon(self) -> int:
        """Tira lo que quedaba por locutar del turno que se acaba de parar.

        >>> LA TERCERA FUGA, Y ERA LA MENOS VISIBLE <<<
        El hilo de la voz va sacando eventos del buzon y narrando lo que
        Claude Code cuenta mientras trabaja. Al parar, ahi dentro puede
        haber varios `UsoHerramienta` YA encolados: cortar la frase en
        curso solo hacia que empezara la siguiente, y Jarvis seguia
        narrando un trabajo que ya no existe.

        Devuelve cuantos se tiraron, y se cuenta: si el numero
        es alto, es que se esta narrando por detras de lo que pasa.
        """
        tirados = 0
        while True:
            try:
                self._buzon.get_nowait()
            except queue.Empty:
                return tirados
            tirados += 1

    def _tirar_lo_viejo(self) -> None:
        """La voz abre un turno nuevo: lo que quedaba del anterior se tira.

        >>> ES LA DECISION (d) DEL 2026-08-29, Y ES UNA DECISION <<<
        Lo que el usuario oyo aquella noche no fue solo que la respuesta
        llegara TARDE: llego FUERA DE ORDEN, en mitad de otra cosa. Con
        el buzon drenandose ya en menos de un segundo esto deberia ser
        raro, pero cuando pase hay que elegir, y se elige tirar:

            locutarla   la respuesta de hace dos turnos se dice encima
                        del turno que acabas de pedir. Suena a que el
                        asistente se ha ido por su cuenta.
            tirarla     se pierde una respuesta que ya esta ENTERA en la
                        consola y que ademas se mando desde el movil, o
                        sea desde una pantalla donde tambien se lee.

        Se cuenta (`tirado_al_abrir_turno`) porque tirar en silencio es
        como nacio el fallo que esto arregla.

        Va en los DOS sitios que mandan un turno hablado -- este y la
        ventana de seguimiento, que no pasa por `_mandar` --, que es la
        regla: al arreglar una forma, buscar los demas sitios con esa
        forma. NO va en `_anunciar`, aunque sea el punto que comparten
        los tres caminos, porque por ahi pasan tambien "abrete" y
        "apagate", que NO abren turno: tirarian el buzon de un turno que
        sigue vivo.
        """
        self.cuenta.tirado_al_abrir_turno += self._vaciar_buzon()

    # --- lo que se dice ----------------------------------------------------

    def decir(self, texto: str, aunque_este_parado: bool = False) -> None:
        """Habla, salvo que le hayan mandado callar.

        El `cancelar` no es cortesia: cortar la frase A MITAD es la forma
        mas visible que tiene un asistente por voz de obedecer. Quien
        dice "para" mientras le hablas encima quiere silencio AHORA, no
        cuando termine el parrafo.
        """
        if not texto.strip() or self.tts is None:
            return
        if self._parado.is_set() and not aunque_este_parado:
            # >>> LA GUARDA VA AQUI Y NO EN CADA SITIO QUE HABLA <<<
            # Son siete caminos distintos (narracion, respuesta,
            # coletilla, puerta, pregunta, limite, reintento) y basta con
            # que uno se olvide para que Jarvis siga hablando de un turno
            # que el usuario mando parar. La regla: se tapa donde no se
            # puede olvidar.
            self.cuenta.callado_por_parada += 1
            return
        # Se coge la bandera UNA vez: `_parar_el_turno` la sustituye, y
        # leerla dos veces podria comprobar con una y cancelar con otra.
        bandera = self._callar
        if bandera.is_set():
            return
        self.cuenta.caracteres_locutados += len(texto)
        self.tts.hablar(texto, dispositivo=self.altavoz, cancelar=bandera)

    def _atender_buzon(self) -> None:
        """Saca del buzon todo lo que haya y reacciona a cada cosa.

        >>> ESTE `except` ES LO QUE HIZO INVISIBLE EL FALLO DEL 29 <<<
        Hasta ese dia era un `continue` a secas, sin contador y sin una
        linea. Y por ahi se colaba, en TODOS los turnos que no abrio la
        voz, el `CicloError` de `preparar_respuesta()`: la respuesta se
        tiraba y no quedaba rastro de que hubiera existido. El camino
        feliz -- el de la voz -- seguia funcionando, asi que la suite
        seguia verde y nadie miraba.
        Sigue sin poder llevarse el bucle por delante (un fallo locutando
        dejaria al usuario sin voz Y sin saberlo), pero ahora se CUENTA y
        se DICE: "no se pudo" no es "no habia nada".
        """
        # Antes de drenar, no despues: ver `_hay_correo`.
        self._hay_correo.clear()
        while True:
            try:
                evento = self._buzon.get_nowait()
            except queue.Empty:
                return
            try:
                self._reaccionar(evento)
            except Exception as exc:  # noqa: BLE001
                self.cuenta.eventos_tirados += 1
                self.ultimo_fallo = (
                    f"no se pudo atender {type(evento).__name__}: {exc}")
                print(f"  ({self.ultimo_fallo})")
                continue

    def _reaccionar(self, evento: Evento) -> None:
        # >>> UN `Texto` NO SE JUZGA AL LLEGAR <<< Es narracion si detras
        # viene una herramienta, y es LA RESPUESTA si detras viene `Fin`.
        # Locutarlo al recibirlo diria la respuesta dos veces.
        narracion = self.tarea.ve(evento)

        # >>> UN TURNO QUE NO ABRIO LA VOZ TAMBIEN ES UN TURNO <<<
        # Telegram y la consola mandan turnos igual de reales, y hasta el
        # 2026-08-29 el ciclo no sabia llegar a TRABAJANDO por ahi: se
        # quedaba DORMIDO y `preparar_respuesta()` moria. Se adopta AQUI,
        # antes de repartir, porque no lo necesita solo la respuesta --
        # `pregunto()` exige lo mismo, o sea que una puerta y una
        # pregunta de un turno ajeno tampoco abrian el microfono.
        #
        # >>> Y SOLO CON ESTOS CINCO, QUE NO ES UN DETALLE <<<
        # Adoptar con CUALQUIER evento dejaria el ciclo en TRABAJANDO sin
        # nadie que lo cierre: un `Limite` o un `Reintento` sueltos -- que
        # pueden llegar detras de un `Fin` que ya devolvio el ciclo a
        # DORMIDO -- lo dejarian trabajando para siempre, y con el ciclo
        # atascado el wake word NO VUELVE A ABRIR NADA. Sordera total y
        # muda, que es la forma de fallo que este proyecto persigue desde
        # el principio.
        # Los cinco de aqui son los que solo existen DENTRO de un turno
        # que termina en `Fin`, y `_al_terminar` cierra el ciclo en sus
        # cinco salidas. Los otros dos no tocan el ciclo para nada: solo
        # hablan, y hablar no necesita estado.
        #
        # >>> `Texto` ENTRO EL 2026-09-04, Y LO PIDIO EL SINTOMA <<<
        # Se reporto usandolo: dando la instruccion escrita, el estado
        # seguia en "dormido" con Jarvis ya trabajando.
        # Con los cuatro de antes, el ciclo no despertaba
        # hasta la PRIMERA HERRAMIENTA -- y hay turnos que no gastan
        # ninguna. Medido sobre los 134 turnos reales de `logs/puente/`:
        # **58 (43 %) no usan una sola herramienta**, o sea que casi la
        # mitad de lo que escribes en la consola enseñaba DORMIDO de
        # principio a fin. Con `Texto` dentro, los que se quedan cortos
        # bajan a **6 (4 %)** -- los que no dicen nada en absoluto, y
        # esos los adopta el `Fin` que sigue.
        # Y CUMPLE LA MISMA REGLA que los otros cuatro, que es lo unico
        # que autoriza a ensancharla: un `assistant` solo existe dentro
        # de un turno, y ese turno termina en `Fin`. No es el caso de
        # `Limite` ni de `Reintento`, y por eso siguen fuera (hay dos
        # tests que lo comprueban).
        if isinstance(evento, (Texto, UsoHerramienta, Fin, Puerta, Pregunta)):
            ajeno = self.ciclo.estado is Estado.DORMIDO
            if not self.ciclo.trabajo_ajeno():
                # El usuario esta dictando una orden nueva. No deberia
                # verse (el hilo de la voz es uno solo), y por eso se
                # cuenta en vez de darlo por imposible.
                self.cuenta.eventos_fuera_de_turno += 1
                return
            if ajeno:
                self.cuenta.turnos_ajenos += 1

        # >>> UN `Texto` NO SE JUZGA AL LLEGAR <<< Es narracion si detras
        # viene una herramienta, y es LA RESPUESTA si detras viene `Fin`.
        # Locutarlo al recibirlo diria la respuesta dos veces. O sea que
        # despierta el ciclo -- arriba -- y no dice nada: lo unico que
        # aporta es que la pantalla deje de mentir mientras se decide
        # que era.
        if isinstance(evento, Texto):
            return

        if isinstance(evento, UsoHerramienta):
            self._narrar(narracion)
            return
        if isinstance(evento, Fin):
            # Era la respuesta: la locuta `_al_terminar`, no esto.
            self._al_terminar(evento)
        elif isinstance(evento, Puerta):
            # Una puerta se anuncia SOLA: el comentario de antes es
            # charla y la puerta es una pregunta que hay que contestar.
            # De tirar lo pendiente ya se encargo `tarea.ve`.
            self._anunciar_puerta(evento)
        elif isinstance(evento, Pregunta):
            self._atender_pregunta(evento)
        elif isinstance(evento, Reintento):
            self._al_reintentar(evento)
        elif isinstance(evento, Limite) and evento.agotado:
            self.decir(_f("limite_agotado"))

    def _narrar(self, pendiente: str | None) -> None:
        """Locuta el comentario que Claude Code dejo antes de trabajar.

        >>> UN COMENTARIO QUE LLEGA TARDE NO SE DICE <<<
        Si ya hay mas eventos esperando en el buzon, el trabajo siguio
        mientras nosotros hablabamos, y "ahora voy a mirar el codigo" se
        locutaria cuando ya lo miro y ademas hizo otras tres cosas. Eso
        no da vividez: da la sensacion de que Jarvis va por detras de si
        mismo. `decir` BLOQUEA hasta terminar la frase, asi que sin esta
        regla un turno con diez comentarios son diez frases seguidas y
        Jarvis narrando un trabajo que ya acabo.

        Se cuenta aparte (`narraciones_tarde`) en vez de tragarselo: si
        ese numero se dispara, lo que sobra es la narracion, no el filtro.
        """
        if pendiente is None or not self.narrar or self._callar.is_set():
            return
        if not self._buzon.empty():
            self.cuenta.narraciones_tarde += 1
            return

        narracion = narrar_para_un_oido(pendiente)
        if not narracion.se_dice:
            self.cuenta.narraciones_mudas += 1
            return
        self.cuenta.narraciones_dichas += 1
        self.decir(narracion.hablado)

    def _al_terminar(self, fin: Fin) -> None:
        """El turno cerro. Cual de las cuatro formas importa mucho.

        >>> `parado` SE MIRA ANTES QUE `fue_mal`, Y ESTA MEDIDO <<<
        Un turno interrumpido llega con `is_error: true`. Quien mire solo
        `fue_mal` le dira "algo ha ido mal" a alguien que acaba de
        mandarle callar. El orden de estos `if` es la diferencia entre
        obedecer y contestar.
        """
        if fin.parado:
            # Ya se dijo "vale, paro" al pararlo. Insistir es hablar
            # encima de alguien que pidio silencio.
            self.ciclo.termino()
            return

        # La red volvio a funcionar: el proximo corte se avisa otra vez.
        # Sin esto, el aviso se da UNA vez en toda la vida del proceso y
        # el segundo apagon pasa en silencio.
        self._aviso_de_red_dado = False

        if fin.sin_servidor:
            self.ciclo.termino()
            self.decir(_f("sin_servidor"))
            return

        if fin.fue_mal:
            self.ciclo.termino()
            self.decir(_f("turno_mal"))
            return

        resumen = para_un_oido(fin.texto, limite=self.limite_hablado)
        self.cuenta.caracteres_escritos += resumen.largo_original
        if not resumen.hablado:
            self.ciclo.termino()
            return

        self.ciclo.preparar_respuesta()
        self.decir(resumen.hablado)
        self._menciona_lo_que_dejo(resumen.hablado)

        # >>> SI LA RESPUESTA ACABA PREGUNTANDO, SE SIGUE ESCUCHANDO <<<
        # Y este es el camino que de verdad se usa: `AskUserQuestion` es
        # para elegir entre opciones dentro de una tarea, pero preguntar
        # EN PROSA y cerrar el turno es lo que hace Claude Code la mayor
        # parte de las veces. Medido en una sesion real del usuario: tres
        # turnos, el ultimo acabo en "¿quieres contarme que esta
        # pasando?", y CERO `control_request` en todo el log.
        pregunta = pregunta_final(fin.texto)
        if pregunta and pregunta not in resumen.hablado:
            # El resumen pudo cortar justo la pregunta. Sin esto, el
            # microfono se abriria sin que al usuario le hayan preguntado
            # nada que haya oido.
            self.decir(pregunta)
        elif resumen.recortado and not self._callar.is_set():
            # Si le mandaron callar a mitad de la respuesta, la coletilla
            # tampoco se dice: seria hablar despues de un "para".
            self.decir(_f("resto_en_consola"))
        self.cuenta.respuestas_locutadas += 1

        # >>> JC-0012: LA CONVERSACION SIGUE MIENTRAS HABLES <<<
        # Tras una pregunta se escucha SIEMPRE (eso es JC-0011). Tras una
        # respuesta normal, solo con el modo conversacion puesto.
        if (pregunta or self.seguimiento) and not self._callar.is_set():
            self._ventana_de_seguimiento(tras_pregunta=bool(pregunta))
            return
        self.ciclo.termino()

    def _menciona_lo_que_dejo(self, ya_dicho: str) -> None:
        """Dice en alto que hay algo nuevo en el panel. Pedido el 09-01.

        >>> SOLO LO QUE LA RESPUESTA NO HAYA NOMBRADO YA <<<
        Claude suele decir "he creado resumen.md" el solo, y con el
        preambulo puesto lo hace mas. Anadir "te he dejado resumen.md"
        detras seria decirlo dos veces seguidas, que en una pantalla se
        perdona y en un altavoz se nota muchisimo. Asi que se filtra
        contra lo que se acaba de locutar.

        VA ANTES DE LA PREGUNTA a proposito. Si la respuesta acaba
        preguntando, esa pregunta es lo ultimo que se oye porque detras
        se abre el microfono; colar un aviso despues dejaria al usuario
        contestando a lo que no era.

        Y NO SE DICE LA RUTA, solo el nombre: una ruta leida en alto no
        se entiende, que es la misma razon por la que `voz/narracion.py`
        las deja fuera.
        """
        if self.producido is None or self._callar.is_set():
            return
        piezas = self.producido.piezas_del_turno(self.producido.turno - 1)
        nuevas = [p for p in piezas if p.nombre not in ya_dicho]
        if not nuevas:
            return
        self.cuenta.piezas_mencionadas += len(nuevas)
        if len(nuevas) == 1:
            unica = nuevas[0]
            if unica.datos is not None:
                self.decir(_f("te_deje_una_imagen"))
            else:
                self.decir(_f("te_deje_uno", unica.nombre))
            return
        self.decir(_f("te_deje_varios", len(nuevas), nuevas[0].nombre))

    def _ventana_de_seguimiento(self, tras_pregunta: bool = False) -> None:
        """Abre la escucha sin palabra de activacion y manda lo que digas.

        DIFERENCIA CON `_atender_pregunta`, y es la que decide el codigo:
        alli el turno sigue vivo esperando en la puerta de control, asi
        que se contesta CON `responder`. Aqui el turno YA CERRO -- la
        pregunta venia en su texto --, asi que no hay nada que contestar:
        lo que se dice es un TURNO NUEVO. La sesion es la misma y el
        contexto tambien, asi que el modelo lo lee como lo que es, la
        respuesta a lo que acaba de preguntar.

        SI NO CONTESTAS, SE CALLA Y SE VA. Sin "no te he oido": una
        pregunta que decides no contestar no deberia dar la lata. La
        distincion la hace `Transcripcion.sin_habla`, que ya sabe
        separar "no hablo nadie" de "no se entendio".

        >>> Y ESA ES LA REGLA DE CIERRE DE TODA LA CONVERSACION <<<
        No hace falta decir "gracias", ni "para", ni nada: **una sola
        ventana vacia la termina**. Mientras contestes, cada respuesta
        abre otra ventana y la charla se encadena sola; en cuanto te
        callas, vuelve a dormir hasta el proximo "hey jarvis". Eso es lo
        que hace barato el modo conversacion: no hay que acordarse de
        cerrarlo.
        """
        try:
            self.ciclo.pregunto()
        except Exception:  # noqa: BLE001 - el estado cambio por medio
            self.ciclo.termino()
            return

        # >>> AQUI SE ESPERA, Y CONVIENE SABER CUANTO <<<
        # Mientras Jarvis hablaba, el hilo del oido estaba grabando por
        # si decias "para". `pregunto()` (arriba) impide que empiece otra
        # ventana, pero la que estuviera a medias hay que dejarla acabar:
        # en el peor caso son VENTANA_PARADA_S mas lo que tarde el STT,
        # o sea ~4,7 s antes de que suene el aviso. El aviso suena
        # DESPUES de coger el cerrojo justamente por eso -- si sonara
        # antes, te estaria diciendo "habla" con el microfono cogido.
        espera = (ESPERA_ORDEN_S if tras_pregunta
                  else ESPERA_SEGUIMIENTO_S)
        self.cuenta.ventanas_abiertas += 1
        with self._con_el_microfono():
            self.ciclo.avisar_de_que_escucha()
            transcripcion = self.stt.escuchar_turno(
                espera_inicio_ms=espera * 1000,
                dispositivo=self.micro)
        reaccion = self.ciclo.oido(transcripcion)

        if reaccion is Reaccion.PARAR:
            self.cuenta.ventanas_con_habla += 1
            self._parar_el_turno()
            return
        if reaccion is not Reaccion.RESPUESTA:
            self.ciclo.termino()
            return

        self.cuenta.ventanas_con_habla += 1
        # >>> ESTE CAMINO NO PASA POR `_mandar`, Y POR ESO NO SE VEIA <<<
        # Lo vio el usuario el 2026-08-27: contesto a una pregunta de
        # Claude Code -- o sea por esta ventana, sin decir "hey jarvis" --
        # y en la consola no aparecio NADA de lo que dijo. Es el camino
        # mas comun de toda la conversacion (JC-0012) y era el unico
        # que mandaba a `sesion.mandar` a pelo.
        dicho = transcripcion.texto.strip()
        self._anunciar(dicho, "voz")
        self._tirar_lo_viejo()
        self.sesion.mandar(dicho)
        self.cuenta.respuestas_habladas += 1
        self.ciclo.volver_al_trabajo()

    def _atender_pregunta(self, pregunta: Pregunta) -> None:
        """Jarvis pregunta, y la escucha se abre SOLA. Sin "hey jarvis".

        >>> POR QUE ESTO NO ES UNA COMODIDAD, DICHO POR EL USUARIO <<<
        "siempre que jarvis me pida informacion para yo responderle
        deberia estar la escucha activa sin que yo tenga que activarlo de
        nuevo". Tiene razon y ademas se nota al primer uso: obligar a
        decir la palabra para contestar una pregunta convierte una
        conversacion en un formulario.

        Y no relaja nada: la sesion ya esta trabajando en una orden que
        acaba de dar el usuario, y aqui solo se acepta la RESPUESTA a lo
        que se acaba de preguntar (ver `Ciclo.pregunto`).

        LO QUE SE LOCUTA son el enunciado y las opciones, porque sin las
        opciones el usuario no sabe que puede decir; y se dicen DESPUES
        de la pregunta, que es el orden en que hacen falta.
        """
        self.cuenta.preguntas_hechas += 1
        enunciados = pregunta.enunciados
        if not enunciados:
            # Una pregunta sin enunciado no se puede locutar; que la
            # conteste quien mira la pantalla.
            self.decir(_f("te_pregunta"))
            return

        opciones = self._opciones_de(pregunta)
        self.decir(enunciados[0])
        if opciones:
            self.decir(_f("puedes_decir") + _f("o_bien").join(opciones) + ".")

        try:
            self.ciclo.pregunto()
        except Exception:  # noqa: BLE001 - llego fuera de tiempo
            return

        with self._con_el_microfono():
            self.ciclo.avisar_de_que_escucha()
            transcripcion = self.stt.escuchar_turno(
                espera_inicio_ms=ESPERA_ORDEN_S * 1000,
                dispositivo=self.micro)
        reaccion = self.ciclo.oido(transcripcion)

        if reaccion is Reaccion.PARAR:
            self._parar_el_turno()
            return
        if reaccion is not Reaccion.RESPUESTA:
            # No se entendio. NO se contesta a medias: se deja pendiente
            # y se dice, que es lo unico honesto -- la pregunta sigue
            # abierta en la consola y la sesion sigue esperando, que es
            # su comportamiento medido.
            self.decir(_f("no_te_oi_consola"))
            self.ciclo.volver_al_trabajo()
            return

        elegida = self._opcion_mas_parecida(transcripcion.texto, opciones)
        self.sesion.responder(
            pregunta.id_peticion, permitir=True,
            respuestas={enunciados[0]: elegida or transcripcion.texto.strip()},
        )
        self.cuenta.preguntas_contestadas += 1
        self.ciclo.volver_al_trabajo()

    @staticmethod
    def _opciones_de(pregunta: Pregunta) -> list[str]:
        primera = pregunta.preguntas[0] if pregunta.preguntas else {}
        opciones = primera.get("options") or []
        return [str(o.get("label", "")).strip() for o in opciones
                if str(o.get("label", "")).strip()]

    @staticmethod
    def _opcion_mas_parecida(dicho: str, opciones: list[str]) -> str | None:
        """La etiqueta que el usuario quiso decir, o None.

        Se busca la etiqueta DENTRO de lo que dijo y no al reves: la
        gente contesta "pues minusculas" o "en minusculas, mejor", no la
        etiqueta a pelo. Sin tildes y en minusculas porque el STT las
        pone donde quiere.

        None no es un fallo: significa "dijo algo que no es ninguna de
        las opciones", y entonces se manda lo que dijo TAL CUAL. Forzar
        la opcion mas parecida seria elegir por el, que es peor que
        pasarle una frase suelta a un modelo que sabe leerla.
        """
        from voz.parada import normalizar

        palabras = set(normalizar(dicho))
        if not palabras:
            return None
        mejor, mejor_puntuacion = None, 0
        for opcion in opciones:
            trozos = set(normalizar(opcion))
            comunes = len(palabras & trozos)
            if trozos and comunes > mejor_puntuacion:
                mejor, mejor_puntuacion = opcion, comunes
        return mejor

    def _anunciar_puerta(self, puerta: Puerta) -> None:
        """Pide permiso HABLANDO y contesta la puerta (JC-0002).

        >>> LAS DOS FORMAS NOMBRAN LO MISMO, Y POR CONSTRUCCION <<<
        La frase sale de `voz/permiso.py::pedir`, que la deriva de la
        MISMA `Decision` que la consola pinta. No hay una redaccion
        hablada por un lado y una tarjeta por otro: si divergieran, se
        aprobaria una cosa y se ejecutaria otra.

        >>> Y EL SILENCIO NO ES UN NO <<<
        Si nadie contesta, la puerta se queda PENDIENTE: la sesion espera
        indefinidamente (medido) y la puede contestar la consola, o
        Telegram cuando exista (JC-0006). Denegar por silencio cerraria
        esa via y convertiria "no estaba delante" en "dijo que no".
        """
        from voz.permiso import Respuesta, interpretar, pedir

        self.cuenta.puertas_anunciadas += 1
        decision = self._decision_de(puerta)
        if decision is None:
            # Sin decision no hay ni motivo ni elementos, o sea que no hay
            # frase que se pueda construir sin inventarla. Antes que
            # inventar la peticion en la que el usuario consiente, se
            # manda a la consola.
            self.decir(_f("necesito_permiso"))
            return

        peticion = pedir(puerta, decision,
                         directorio=getattr(self.sesion, "directorio", None))
        self.decir(peticion.frase)

        try:
            self.ciclo.pregunto()
        except Exception:  # noqa: BLE001 - el estado cambio por medio
            return

        with self._con_el_microfono():
            self.ciclo.avisar_de_que_escucha()
            oido = self.stt.escuchar_turno(
                espera_inicio_ms=ESPERA_ORDEN_S * 1000,
                dispositivo=self.micro)
        self.ciclo.volver_al_trabajo()

        respuesta = interpretar(oido)
        if respuesta is Respuesta.SIN_RESPUESTA:
            self.cuenta.permisos_sin_respuesta += 1
            self.decir(_f("pendiente_consola"))
            return

        permitir = respuesta is Respuesta.SI
        # `responder` devuelve False si otro canal llego antes. No es un
        # fallo: es la carrera normal entre la voz y la consola, y el que
        # pierde tiene que callarse en vez de anunciar algo que ya no es
        # verdad.
        if not self.sesion.responder(
                puerta.id_peticion, permitir=permitir,
                motivo="" if permitir else "El usuario dijo que no."):
            return
        if permitir:
            self.cuenta.permisos_dados += 1
            self.decir(_f("autorizado"))
        else:
            self.cuenta.permisos_denegados += 1
            self.decir(_f("no_autorizo"))

    def _decision_de(self, puerta: Puerta):
        """La misma `Decision` que la consola tiene para esa puerta.

        Se PIDE a la sesion en vez de recalcularla: recalcular seria
        volver a pasar la puerta por la politica y quedarse con lo que
        salga, y si por lo que fuera saliera distinto de lo que la
        consola ya esta enseñando, la voz nombraria otra cosa. Se busca
        entre las pendientes, que es donde la sesion la guardo cuando
        decidio no contestarla sola.
        """
        for pendiente in getattr(self.sesion, "pendientes", ()):  # tupla
            if pendiente.evento is puerta or getattr(
                    pendiente.evento, "id_peticion", None) == puerta.id_peticion:
                return pendiente.decision
        return None

    def _al_reintentar(self, reintento: Reintento) -> None:
        """Se avisa en el PRIMER reintento, no en el ultimo.

        Medido (JC-0003): una sesion sin red no da error, ni salida, ni
        `result` -- se calla ~180 s antes de rendirse, y por dentro se
        parece exactamente a una que esta pensando. Tres minutos de
        silencio delante de un asistente por voz son tres minutos en los
        que el usuario cree que no le ha oido.
        """
        if self._aviso_de_red_dado:
            return
        self._aviso_de_red_dado = True
        self.decir(_f("problemas_servidor"))
