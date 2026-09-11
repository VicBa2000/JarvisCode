"""Reconocer "continua con el desarrollo del proyecto nebula".

>>> POR QUE ESTO SE INTERCEPTA Y NO VA AL CEREBRO <<<
La regla del proyecto es tajante: **TODO pasa por Claude Code, no hay
local**, y una via local para ordenes triviales necesitaria su propio
ADR. Esto NO es esa via, y la diferencia es estructural, no de grado:

    "abre el bloc de notas"      es una tarea PARA el cerebro
    "cambia al proyecto X"       es una orden SOBRE Jarvis

Claude Code no puede cambiar el directorio de su propia sesion: la sesion
es el proceso que hay que cerrar y volver a abrir en otro sitio. Mandarle
esa frase seria pedirle a alguien que se mude a si mismo de casa. Quien
puede hacerlo es el puente, y por eso lo mira el puente.

EL PRECEDENTE ES "PARA" (JC-0011), y nadie lo llamo hibrido: tambien se
intercepta antes del cerebro, tambien por la misma razon -- es una orden
sobre el asistente, no para el. La regla que sale de aqui, y conviene
tenerla escrita antes de que alguien quiera meter "sube el volumen":
**se intercepta lo que el cerebro no PUEDE hacer, jamas lo que seria mas
rapido hacer aqui.**

>>> TRES VEREDICTOS, NO DOS <<<

    CAMBIAR   se pidio un proyecto y se dijo cual
    SIN_NOMBRE  se pidio cambiar y no se entendio de cual  -> se pregunta
    NO_ES     no iba de esto; sigue su camino al cerebro

SIN_NOMBRE no es adorno. "abre el proyecto" a secas, o un nombre que el
STT se comio, no puede caer en NO_ES: se iria al cerebro como una orden
cualquiera y Claude Code haria lo que le pareciera con ella. Y tampoco
puede caer en CAMBIAR sin nombre. Es su propia salida y se pregunta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

# >>> LAS FORMAS SE FUERON A `voz/idioma.py` (2026-09-09) <<<
# Vivian aqui, compiladas y en español, y por eso el canal ingles no
# interceptaba nada: se dijo "Carry on with Project X" en ingles, el
# STT lo transcribio perfecto, y la frase se fue entera
# al cerebro -- la sesion se quedo en la carpeta base y Claude Code se
# puso a mirar el disco a ver que era eso.
# Ahora las pide `voz.idioma.formas_de_proyecto()`, que es donde vive
# todo lo que cambia con `voz.idioma`. Lo de aqui abajo -- normalizar,
# el mapa de indices, el corte por puntuacion y las tres salidas -- NO
# depende del idioma y se queda: es la parte que ya costo tres tandas.

# >>> Y LA PUNTUACION CORTA ANTES QUE NINGUN CONECTOR (2026-09-03) <<<
# Lo reporto el usuario, y su frase entera es el caso:
#
#     "Continua con el proyecto Faro, checate el documento que esta
#      ahi y generame un documento nuevo llamado Ideas.md..."
#
# Contestaba "no tengo ningun proyecto llamado X checate el documento".
# El nombre se comia media frase porque el primer CONECTOR
# es el "que" de "el documento QUE esta ahi", o sea nueve palabras mas
# adelante; y la cola arrancaba en "esta ahi", a mitad de oracion.
#
# LA COMA YA DECIA DONDE ACABABA EL NOMBRE: el STT la habia transcrito
# correctamente. La tirabamos nosotros, porque
# `normalizar_con_mapa` convierte toda la puntuacion en espacios antes de
# que nadie la mire. **Tercera vez este mes con la misma forma**: el dato
# esta en el texto ORIGINAL y se pierde en el normalizado -- paso con
# "estado.md" el 1 (por eso existe el mapa de indices) y con el
# CamelCase esta misma manana.
#
# DOS CLASES, Y NO UNA, porque no se comportan igual:
#   * `CIERRES` cortan SIEMPRE. Una coma, un punto y coma o dos puntos
#     dentro del nombre de un proyecto no existen.
#   * `FINALES` cortan solo si detras hay un espacio o se acaba la frase.
#     Es lo que distingue el punto de "Faro. Checate..." del de
#     "Ideas.md", que es justo el archivo que pedia esta frase: con la
#     regla ingenua, el nombre del documento se habria partido en dos.
CIERRES = ",;:"
FINALES = ".!?"


def _cortes_duros(texto: str, indices: list[int]) -> set[int]:
    """Las posiciones del NORMALIZADO que vienen de un signo que separa.

    Se mira el caracter ORIGINAL, no el normalizado: en el normalizado
    una coma ya es un espacio y es indistinguible de un espacio de
    verdad. Ese es el dato que se estaba perdiendo.
    """
    duros: set[int] = set()
    for posicion, origen in enumerate(indices):
        signo = texto[origen]
        if signo in CIERRES:
            duros.add(posicion)
        elif signo in FINALES:
            siguiente = texto[origen + 1:origen + 2]
            if not siguiente or siguiente.isspace():
                duros.add(posicion)
    return duros



class Veredicto(str, Enum):
    CAMBIAR = "cambiar"
    SIN_NOMBRE = "sin_nombre"
    NO_ES = "no_es"


@dataclass(frozen=True)
class Peticion:
    veredicto: Veredicto
    nombre: str = ""
    dicho: str = ""
    cola: str = ""
    """Lo que se pidio ADEMAS de cambiar de proyecto, tal cual se dijo.

    >>> HASTA EL 2026-09-01 ESTO SE TIRABA, Y CALLANDO <<<
    Se reporto usandolo: iba al proyecto y preguntaba el ritual, o sea que
    hacia lo primero que se le pedia al nombrar un proyecto registrado --
    pero se saltaba entera la segunda instruccion de la misma frase.
    El nombre se cortaba en el primer conector y lo de detras no iba a
    ninguna parte, porque `Peticion` no tenia donde guardarlo: la frase
    entera se convertia en un cambio de carpeta mas el ritual.

    Y es el peor fallo que puede tener esta capa: **una orden dictada que
    desaparece sin dejar rastro**. No hay error, no hay linea en el log, y
    Jarvis contesta algo perfectamente razonable a otra pregunta.

    >>> VIENE DEL TEXTO ORIGINAL, NUNCA DEL NORMALIZADO <<<
    Normalizado, "guardalo como estado.md" es "guardalo como estado md":
    el punto se vuelve un espacio y el nombre del archivo deja de serlo.
    Mandar eso seria pedirle al cerebro que cree un archivo que no
    dijiste. Por eso `voz.parada.normalizar_con_mapa` dice de donde vino
    cada caracter.
    """

    @property
    def es_cambio(self) -> bool:
        return self.veredicto is not Veredicto.NO_ES


def interpretar(texto: str, idioma: str | None = None,
                config_dir: Path | None = None) -> Peticion:
    """Si esta frase pide cambiar de proyecto, y a cual.

    >>> SE COMPARA SIN TILDES, Y ESTO COSTO LA PRIMERA PRUEBA REAL <<<
    El 2026-08-27, con todo bien configurado, "continua con el proyecto X"
    se fue entera al cerebro sin interceptarse. El
    motivo: el STT escribe **"continúa"** con tilde -- que es como se
    escribe en español -- y el patron decia `continua`. `re.I` baja las
    mayusculas y NO toca los acentos, asi que no casaba.

    Se reutiliza `voz.parada.normalizar`, que ya quita tildes, mayusculas
    y puntuacion, y esta medido contra lo que devuelve `small` de verdad.
    NO se escribe otro normalizador aqui: ya habia tres en el arbol
    (parada, proyectos, ventana) y esa es la forma en que acaban
    divergiendo.

    El nombre se saca del texto YA NORMALIZADO, y da igual: `resolver`
    normaliza los dos lados de todas formas.
    """
    from voz.parada import normalizar_con_mapa

    # Se busca sobre el normalizado SIN colapsar espacios, para que cada
    # caracter conserve su sitio en el original y la cola se pueda sacar
    # de alli. `limpio` -- el colapsado de siempre -- se queda solo para
    # `dicho`, que es lo que se lee en la consola.
    crudo, indices = normalizar_con_mapa(texto or "")
    limpio = " ".join(crudo.split())
    if not limpio:
        return Peticion(Veredicto.NO_ES, dicho=(texto or "").strip())
    duros = _cortes_duros(texto or "", indices)

    # UNA resolucion para las tres, y no una por regla: unas formas
    # inglesas cortando por conectores españoles no darian error --
    # dejarian el nombre con media orden pegada detras.
    from voz.idioma import formas_de_proyecto

    del_idioma = formas_de_proyecto(idioma, config_dir)
    for forma in del_idioma.formas:
        casa = forma.search(crudo)
        if not casa:
            continue
        bruto = casa.group("nombre") or ""

        # >>> UNA COMA PEGADA A "PROYECTO" DEJA EL NOMBRE VACIO <<<
        # "ve al proyecto, mira el readme": el `\s*` del patron se come la
        # coma -- en el normalizado ya es un espacio, indistinguible de
        # uno de verdad -- y el nombre pasaba a ser "mira el readme". No
        # abre la carpeta equivocada, pero contesta "no tengo ningun
        # proyecto llamado mira el readme" en vez de preguntar CUAL, que
        # es la tercera salida. Lo destapo el test de esta misma tanda.
        # Se mira hacia atras solo sobre BLANCOS, que es exactamente lo
        # que pudo comerse el `\s*`.
        hueco = casa.start("nombre") - 1
        while hueco >= 0 and crudo[hueco].isspace():
            if hueco in duros:
                return Peticion(Veredicto.SIN_NOMBRE, dicho=limpio)
            hueco -= 1

        # Lo que se comen `lstrip` y `COLGANTES` por delante mueve el
        # origen del nombre. Sin contarlo, la cola saldria descolocada
        # unas letras, que es peor que no tenerla: llegaria una orden
        # cortada a mitad de palabra.
        sin_blancos = bruto.lstrip()
        desplazado = len(bruto) - len(sin_blancos)
        recortado = del_idioma.colgantes.sub("", sin_blancos)
        desplazado += len(sin_blancos) - len(recortado)
        base = casa.start("nombre") + desplazado

        # >>> DOS SITIOS DONDE PUEDE ACABAR EL NOMBRE, Y GANA EL PRIMERO
        # <<< Un signo de puntuacion y un conector dicen lo mismo -- "el
        # nombre se acaba aqui" --, pero el signo es MUCHO mas fiable: el
        # conector es una palabra que puede aparecer dentro de la orden de
        # detras ("el documento QUE esta ahi"), y una coma no aparece
        # nunca dentro del nombre de un proyecto. Quedarse con el mas
        # temprano de los dos es lo que arregla la frase del usuario, en
        # la que el conector estaba nueve palabras mas alla que la coma.
        duro = next((p for p in range(len(recortado)) if base + p in duros),
                    None)
        conector = del_idioma.conector.search(recortado)

        nombre, cola = recortado, ""
        if duro is not None and (conector is None or duro <= conector.start()):
            nombre = recortado[:duro]
            # La cola arranca DETRAS del signo, en el texto original: es
            # una orden y tiene que llegar al cerebro tal cual se dijo,
            # con sus tildes y sus puntos (el "Ideas.md" de esta misma
            # frase deja de ser un nombre de archivo en el normalizado).
            despues = indices[base + duro] + 1
            cola = (texto or "")[despues:].strip(" .,;:")
        elif conector is not None:
            arranca = base + conector.end()
            if arranca < len(indices):
                cola = texto[indices[arranca]:].strip(" .,;:")
            nombre = recortado[:conector.start()]
        nombre = " ".join(nombre.split())
        if not nombre:
            return Peticion(Veredicto.SIN_NOMBRE, dicho=limpio)
        return Peticion(Veredicto.CAMBIAR, nombre=nombre, dicho=limpio,
                        cola=cola)

    return Peticion(Veredicto.NO_ES, dicho=limpio)


# La frase de FABRICA con la que arranca cada proyecto. Ya no es la
# unica posible: desde el 2026-09-05 el usuario escribe la suya (ver
# `primera_pregunta`). Se queda como el suelo -- lo que Jarvis manda si
# nadie ha dicho otra cosa -- y como la que se ensena en el panel.
PRIMERA_PREGUNTA = "hola, en que nos quedamos?"


def ritual_elegido(config_dir: "Path | None" = None) -> str | None:
    """La frase que el usuario escribio en Ajustes. TRES salidas.

        None   no ha escrito ninguna -> manda la de fabrica
        ""     la borro a proposito  -> abre la carpeta y no mandes nada
        texto  esa

    >>> POR QUE NO VALE UN `valor_de(..., "")` <<<
    Porque colapsaria las dos primeras, y son respuestas contrarias: una
    dice "manda la de siempre" y la otra "no mandes nada". Con "" de
    defecto, un usuario que no ha tocado el ajuste se quedaria SIN ritual
    y sin un solo error -- el fallo mudo de siempre, y encima en el turno
    que abre el proyecto. Por eso se pasa el centinela `SIN_ELEGIR`.

    ESTE ES EL LECTOR de `proyectos.ritual`, el que declara
    `tests/test_ajustes_con_lector.py`. El panel no lee su propia clave:
    pregunta aqui.
    """
    from nucleo.ajustes import SIN_ELEGIR, valor_de

    crudo = valor_de("proyectos.ritual", SIN_ELEGIR, config_dir=config_dir)
    if crudo is SIN_ELEGIR or crudo is None:
        return None
    return str(crudo).strip()


def primera_pregunta(idioma: str | None = None,
                     proyecto: Any = None,
                     config_dir: "Path | None" = None) -> str:
    """Que se manda al abrir un proyecto. Cadena VACIA = no mandes nada.

    >>> ESTO DEJO DE SER UNA CONSTANTE EL 2026-09-05, Y HAY QUE DECIRLO
        PORQUE TOCA EL ARGUMENTO DE ADR-0029 <<<
    Aquel llama a este turno "la unica excepcion" a que Jarvis nunca
    escriba nada por su cuenta, y lo justificaba diciendo que la frase es
    fija y de solo lectura. Ya no lo es. Lo que sostiene la excepcion
    ahora es otra cosa, y es mas fuerte, no mas debil: **el texto lo
    escribe el usuario**. Jarvis no redacta nada suyo; repite lo que se
    le dejo escrito, igual que repetia lo que le habiamos dejado escrito
    nosotros. No hay autoridad nueva -- el turno ya corria con la del
    usuario --, lo que hay es un autor distinto, y el correcto.
    LO QUE SI CAMBIA, y por eso el panel lleva aviso: antes esta frase no
    podia hacer nada (era una pregunta), y ahora puede decir cualquier
    cosa. Con `auto` puesto en ese proyecto (JC-0017) no pasa por ninguna
    puerta. Eso se avisa donde se escribe, no aqui.

    TRES FUENTES, y la primera que conteste manda:
      1. la del PROYECTO, si ese proyecto tiene la suya;
      2. la GLOBAL del panel, si el usuario escribio una;
      3. la de FABRICA, por idioma (JC-0018).
    Y en 1 y 2, una cadena vacia es una respuesta -- "abre y no digas
    nada" --, no una fuente que se calla y deja pasar a la siguiente. Por
    eso se comprueba `is not None` y no la verdad de la cadena.

    >>> Y EL ORDEN SE PUEDE INVERTIR, A MANO (2026-09-05, mismo dia) <<<
    La pregunta salio nada mas verlo funcionando: si puede haber una frase
    global opcional que pise a las de cada proyecto. Con `ritual_manda`
    puesto en `config/proyectos.yaml`, el
    paso 1 SE SALTA y gana la global.
    NACE APAGADO porque lo normal es que lo concreto gane a lo general
    -- es lo que hace `modo_para` con las carpetas --, y porque
    encenderlo deja escritas unas frases que dejan de usarse. Eso es un
    fallo mudo si no se ve, asi que el panel lo marca EN CADA FILA que
    pisa. Aqui no se decide nada de eso: aqui solo se pregunta.

    >>> LA FRASE DEL USUARIO PISA EL IDIOMA, Y ES DELIBERADO <<<
    Es UNA cadena, asi que con la voz en ingles se manda igual como se
    escribio. Lo eligio el usuario entre pedir una por idioma; la
    etiqueta del panel lo dice, que es lo que lo hace honesto en vez de
    sorprendente. La de FABRICA si sigue teniendo una por idioma.
    """
    from nucleo.proyectos import manda_la_global

    # El interruptor se mira ANTES que la frase del proyecto, y ese orden
    # importa por lo mismo que en `atender`: mirarla primero y descartarla
    # despues deja el mismo resultado hoy y una trampa en cuanto alguien
    # anada un efecto lateral aqui.
    if proyecto is not None and not manda_la_global(config_dir):
        propia = getattr(proyecto, "ritual", None)
        if propia is not None:
            return propia.strip()

    elegida = ritual_elegido(config_dir)
    if elegida is not None:
        return elegida

    from voz.idioma import ritual

    return ritual(idioma, config_dir)


# ======================================================================
#  EL DECISOR, Y LO LLAMAN LOS DOS CANALES
# ======================================================================
# >>> POR QUE ESTO EXISTE (2026-09-03) <<<
# Se reporto probandolo: la instruccion por consola y la instruccion por
# voz producian resultados diferentes. Y era exacto --
# la MISMA frase, "continua con el proyecto Faro, checa que avance
# tiene y hazme un roadmap.md":
#
#     por voz      -> Sesion abierta en C:\proyectos\faro
#     por consola  -> Sesion abierta en C:\proyectos\carpetadepruebas
#                     y Claude Code buscando `**/*faro*` ahi dentro
#
# La interceptacion de ADR-0029 vivia SOLO en `voz/bucle.py`, y
# `Sesion.cambiar_a` tenia un unico llamador en todo el arbol.
#
# >>> Y NO ERA UNA DECISION, ERA UN HUECO <<<
# El razonamiento de la cabecera de este archivo -- *"Claude Code no
# puede cambiar el directorio de su propia sesion"* -- habla de la
# NATURALEZA de la orden, no del canal por el que entra. Tecleada sigue
# siendo una orden SOBRE Jarvis, y el cerebro sigue sin poder cumplirla.
#
# El fallo era ademas de los caros: no da error. Claude Code es capaz,
# asi que hace algo plausible -- buscar el proyecto en la carpeta que no
# es, y escribir el documento alli.
#
# >>> UN SOLO SITIO DECIDE, Y CADA CANAL LO CUENTA A SU MANERA <<<
# Es la regla de `nucleo.proyectos.modo_para`, escrita alli: *"un solo
# sitio lo decide, porque lo necesitan el arranque y el cambio de
# proyecto hablando: escrito dos veces, un proyecto abriria con freno al
# arrancar y sin freno al cambiarse a el"*. Aqui igual: escrito dos
# veces, la voz y la consola acabarian resolviendo el mismo nombre de
# dos maneras.
#
# Asi que este modulo decide y EJECUTA, y devuelve QUE PASO. Hablar es de
# la voz (`self.decir`) y pintar es de la consola (`avisa`): las dos
# cosas que no se pueden compartir, porque una suena y la otra se lee.
#
# >>> Y VIVE BAJO `voz/` AUNQUE LO LLAME LA CONSOLA <<<
# El nombre viene de que nacio cuando solo se hablaba. Lo que reconoce es
# una FRASE, y las frases llegan por los dos sitios. Mover el archivo
# costaria tocar sus 15 tests para no arreglar nada: `puente/` ya importa
# de `voz/` en cuatro sitios, y esta comprobado que traerse esto cuesta
# 0,09 s y NO arrastra un solo modulo pesado -- ni whisper, ni
# onnxruntime, ni sounddevice. El puente sigue siendo stdlib pura en
# marcha.


class Cambio(Enum):
    """Que ha pasado con la frase. Uno por cada final posible."""

    NO_ES = "no_es"
    """No iba de proyectos. Sigue su camino al cerebro, intacta."""
    APAGADO = "apagado"
    """El interruptor esta apagado, asi que ni se ha mirado la frase."""
    SIN_NOMBRE = "sin_nombre"
    """Se pidio cambiar y no se entendio de cual. Se PREGUNTA."""
    DESCONOCIDO = "desconocido"
    """Ningun proyecto registrado con ese nombre."""
    VARIOS = "varios"
    """Mas de uno casa. No se elige por el usuario."""
    SIN_CARPETA = "sin_carpeta"
    """Esta registrado y su carpeta ya no esta en el disco."""
    ROTO = "roto"
    """El registro no se pudo leer, o `cambiar_a` fallo."""
    ABIERTO = "abierto"
    """Se ha cambiado de carpeta. Falta mandar la cola o el ritual."""


@dataclass(frozen=True)
class Resultado:
    """Lo que paso, con lo que cada canal necesita para contarlo."""

    cambio: Cambio
    nombre: str = ""
    """Lo que se entendio como nombre. Para el "no tengo ninguno asi"."""
    proyecto: Any = None
    """El `Proyecto` abierto, cuando `cambio is ABIERTO`."""
    candidatos: tuple = ()
    """Los alias que casaban, cuando `cambio is VARIOS`."""
    cola: str = ""
    """Lo que dijiste DESPUES del nombre. Sustituye al ritual."""
    error: str = ""
    """El detalle tecnico, para el registro. Nunca se locuta."""

    @property
    def se_ocupo(self) -> bool:
        """Si la frase ya esta atendida y NO debe ir al cerebro."""
        return self.cambio not in (Cambio.NO_ES, Cambio.APAGADO)


def atender(texto: str, sesion: Any,
            config_dir: "Path | None" = None) -> Resultado:
    """Mira la frase y, si pide un proyecto registrado, mueve la sesion.

    NO manda ningun turno y NO dice nada: eso es del canal. Devuelve que
    paso para que la voz lo locute y la consola lo pinte, con las mismas
    palabras saliendo del mismo sitio.

    NO SE ABRE NADA SIN DECIR QUE CARPETA -- condicion 1 de ADR-0029 --,
    pero decirlo es del canal: aqui se DEVUELVE el proyecto entero,
    carpeta incluida, para que ninguno de los dos pueda omitirla.
    """
    from nucleo.proyectos import Cuantas, ProyectosError, intercepta, resolver

    # >>> APAGADO, NI SE MIRA <<< Y ese orden importa: si se mirase
    # primero la frase y luego el interruptor, una orden normal que
    # sonara a esto se quedaria por el camino con el flujo apagado.
    if not intercepta(config_dir):
        return Resultado(Cambio.APAGADO)

    peticion = interpretar(texto)
    if peticion.veredicto is Veredicto.NO_ES:
        return Resultado(Cambio.NO_ES)
    if peticion.veredicto is Veredicto.SIN_NOMBRE:
        return Resultado(Cambio.SIN_NOMBRE)

    try:
        r = resolver(peticion.nombre, config_dir=config_dir)
    except ProyectosError as exc:
        return Resultado(Cambio.ROTO, nombre=peticion.nombre, error=str(exc))

    if r.cuantas is Cuantas.NINGUNO:
        # NO se busca por el disco a ver si suena. ADR-0029: abrir la
        # carpeta equivocada aqui lanza un agente sobre codigo que no
        # era, y lo que llega es una TRANSCRIPCION.
        return Resultado(Cambio.DESCONOCIDO, nombre=peticion.nombre,
                         cola=peticion.cola)
    if r.cuantas is Cuantas.VARIOS:
        # "Ante varias candidatas, se pregunta" -- del propio ADR.
        return Resultado(Cambio.VARIOS, nombre=peticion.nombre,
                         candidatos=tuple(c.alias for c in r.candidatos),
                         cola=peticion.cola)

    proyecto = r.proyecto
    if not proyecto.existe:
        return Resultado(Cambio.SIN_CARPETA, nombre=peticion.nombre,
                         proyecto=proyecto, cola=peticion.cola)

    try:
        # El modo viaja con la carpeta (JC-0017): un proyecto registrado
        # lleva su auto mode, y quedarse con el del anterior seria
        # estrenar -- o perder -- permisos por pedir un cambio de carpeta.
        sesion.cambiar_a(proyecto.carpeta,
                         modo_permisos=proyecto.modo_permisos)
    except Exception as exc:  # noqa: BLE001
        return Resultado(Cambio.ROTO, nombre=peticion.nombre,
                         proyecto=proyecto, error=str(exc))

    return Resultado(Cambio.ABIERTO, nombre=peticion.nombre,
                     proyecto=proyecto, cola=peticion.cola)
