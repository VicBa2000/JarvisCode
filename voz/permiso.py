"""Pedir permiso hablando, y entender la respuesta (JC-0002).

Este es el sitio donde el usuario CONSIENTE, y por eso es el modulo mas
delicado de la capa de voz. Todo lo demas se puede repetir si sale mal;
una aprobacion mal entendida se ejecuta.

>>> LA REGLA QUE MANDA AQUI, Y NO ES NEGOCIABLE <<<
La regla se dejo escrita antes de que existiera este archivo:

    "LAS DOS FORMAS TIENEN QUE NOMBRAR LO MISMO que muestra la consola:
     si divergen, se aprueba una cosa y se ejecuta otra."

Por eso la frase hablada NO se redacta aparte: se DERIVA de la misma
`Decision` que la consola pinta -- su `motivo` y sus `elementos` --, que a
su vez sale de la misma `Puerta`. Escribir aqui una frase bonita a mano
seria abrir justo el hueco que la regla cierra.

>>> Y HEREDA D8, QUE ES EL PROBLEMA DE VERDAD <<<
Una peticion de aprobacion escrita para leerse trae rutas absolutas,
diffs y nombres de herramienta. Locutar eso no informa: agota. Y una
pregunta que no se entiende al oirla degrada el consentimiento a un "si"
reflejo, que es peor que no preguntar, porque parece que se pregunto.

Asi que la frase dice tres cosas y en este orden:

    que va a hacer     el `motivo` de la politica, que ya es una frase
                       humana ("borra archivos")
    CUANTOS y CUALES   "es uno: informe punto pdf" / "son siete, entre
                       ellos a, b y c"
    la pregunta        corta, y siempre la misma

>>> TRES RESPUESTAS, NO DOS, Y LA TERCERA ES LA IMPORTANTE <<<

    SI              se ejecuta
    NO              no se ejecuta
    SIN_RESPUESTA   NADIE HA CONTESTADO. No es un no.

`seguridad/aprobacion.py` trata el silencio como un no, y para una
consola es lo correcto. Aqui NO, y la diferencia es de producto: una
puerta sin contestar deja la sesion ESPERANDO indefinidamente (medido en
JC-0003: 140 s sin timeout ni fallo), y sobre esa espera se construye el
escalado a Telegram de JC-0006. Si la voz denegara por silencio, cerraria
esa puerta antes de que nadie mas pudiera contestarla -- y "no estaba
delante" pasaria a significar "dijo que no".

Lo que si se hereda de aquel modulo, y sin copiarlo, es la
lista de afirmativas: cualquier cosa que no sea un si explicito es un no.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from puente.politica import Decision
from puente.protocolo import Puerta
from seguridad.aprobacion import interpretar_respuesta

# Cuantos elementos se nombran antes de pasar a "entre ellos". Tres es lo
# que cabe en una frase sin que el oyente pierda el hilo; con mas, lo que
# informa es el RECUENTO, no la lista.
NOMBRES_MAXIMOS = 3

# Para que el TTS no lea cifras sueltas en mitad de una frase corta.
_NUMEROS = ("cero", "uno", "dos", "tres", "cuatro", "cinco", "seis",
            "siete", "ocho", "nueve", "diez")
_NUMEROS_EN = ("zero", "one", "two", "three", "four", "five", "six",
               "seven", "eight", "nine", "ten")


class Respuesta(Enum):
    """Que contesto el usuario. La tercera no es un no."""

    SI = "si"
    NO = "no"
    SIN_RESPUESTA = "sin_respuesta"


@dataclass(frozen=True)
class Peticion:
    """Lo que se va a locutar, y de donde ha salido cada parte.

    Se guardan los `elementos` que se nombraron para poder comprobar
    -- en un test y de un vistazo -- que son los MISMOS que la consola
    pinta. Esa comprobacion es la regla de arriba puesta en codigo.
    """

    frase: str
    elementos: tuple[str, ...]
    cuantos: int

    @property
    def se_nombraron_todos(self) -> bool:
        return self.cuantos == len(self.elementos)


def _en_palabras(n: int, idioma: str = "es") -> str:
    cuales = _NUMEROS_EN if idioma == "en" else _NUMEROS
    return cuales[n] if 0 <= n <= 10 else str(n)


def _nombrar(ruta: str, directorio: str | None,
             idioma: str = "es") -> str:
    """El nombre del archivo, y su carpeta SOLO si no es la de la sesion.

    >>> POR QUE NO SE LOCUTA LA RUTA ENTERA <<<
    "ce dos puntos barra proyectos barra jarvis barra informe punto pdf"
    no es una frase: es una cadena de caracteres dictada, y el oyente
    llega al final sin haber entendido nada. Se dice el nombre, que es lo
    que la gente usa para identificar un archivo.

    >>> Y POR QUE LA CARPETA SI, CUANDO ES OTRA <<<
    Porque ahi es donde vive el error caro: dos archivos con el MISMO
    nombre en dos carpetas distintas. Si la accion sale del directorio de
    la sesion, eso es justo lo que hay que oir -- y ademas es lo que la
    politica ya considera digno de preguntar (`ruta_fuera`).
    La consola sigue enseñando la ruta ENTERA, siempre.
    """
    if not ruta:
        return ""
    normal = os.path.normpath(ruta)
    nombre = os.path.basename(normal) or normal
    if not directorio:
        return nombre
    carpeta = os.path.dirname(normal)
    try:
        misma = os.path.normcase(carpeta) == os.path.normcase(
            os.path.normpath(directorio))
    except (TypeError, ValueError):  # pragma: no cover - rutas raras
        misma = False
    if misma or not carpeta:
        return nombre
    from voz.idioma import frase as _f

    return _f("permiso.en_carpeta", nombre,
              os.path.basename(carpeta) or carpeta, idioma=idioma)


def _cuantos_y_cuales(elementos: tuple[str, ...],
                      directorio: str | None,
                      idioma: str = "es") -> tuple[str, int]:
    """"Es uno: informe punto pdf" / "son siete, entre ellos a, b y c"."""
    from voz.idioma import frase as _f

    nombres = [_nombrar(e, directorio, idioma) for e in elementos if e]
    if not nombres:
        return "", 0
    if len(nombres) == 1:
        return _f("permiso.es_uno", nombres[0], idioma=idioma), 1

    mostrados = nombres[:NOMBRES_MAXIMOS]
    lista = ", ".join(mostrados[:-1]) + _f("permiso.y_mas", mostrados[-1],
                                           idioma=idioma)
    cuantos = _en_palabras(len(nombres), idioma)
    if len(nombres) <= NOMBRES_MAXIMOS:
        return (_f("permiso.son_n", cuantos, lista, idioma=idioma),
                len(nombres))
    return (_f("permiso.son_n_entre", cuantos, lista, idioma=idioma),
            len(mostrados))


def pedir(puerta: Puerta, decision: Decision,
          directorio: str | None = None,
          idioma: str | None = None) -> Peticion:
    """La frase con la que se pide permiso por voz.

    Sale ENTERA de `puerta` y `decision`, que son los mismos objetos que
    la consola usa para pintar la tarjeta. Si alguna vez hay que anadir
    algo aqui, el sitio de anadirlo es la `Decision`, no esta funcion.
    """
    from voz.idioma import frase as _f
    from voz.idioma import hablado

    # >>> EL MOTIVO SE TRADUCE AL IDIOMA DE LA VOZ, NO AL DE LA PANTALLA
    # <<< Son dos ajustes distintos y pueden estar cruzados: pantalla en
    # español y voz en ingles es una combinacion legitima. El diccionario
    # es UNO SOLO (`nucleo/textos`), asi que las dos formas nombran la
    # misma accion -- que es lo que JC-0002 exige: si divergen, se
    # aprueba una cosa y se ejecuta otra.
    from nucleo.textos import mensaje as _motivo_en

    idioma = idioma or hablado()
    partes: list[str] = []
    motivo = _motivo_en((decision.motivo or "").strip(), idioma)
    if motivo:
        partes.append(_f("permiso.quiere_hacer", motivo, idioma=idioma))
    else:  # pragma: no cover - la politica siempre pone motivo
        partes.append(_f("permiso.quiere_usar", puerta.herramienta,
                         idioma=idioma))

    cuenta, nombrados = _cuantos_y_cuales(decision.elementos, directorio,
                                          idioma)
    if cuenta:
        partes.append(cuenta)
    elif puerta.orden_shell:
        # Sin elementos que nombrar, lo unico concreto que hay es la
        # orden. Se dice ENTERA y no resumida: es corta, y aqui resumir
        # es justo lo que no se puede hacer.
        partes.append(_f("permiso.la_orden_es", puerta.orden_shell,
                         idioma=idioma))

    # >>> LA PREGUNTA ENSENA LA RESPUESTA, Y ESO NO ES RELLENO <<<
    # Lo que cuenta como "si" es una lista corta y cerrada (ver
    # `interpretar`), asi que un "claro que si" dicho al natural sale NO.
    # Eso es seguro pero desconcierta, y desconcertar al usuario JUSTO en
    # el momento en que consiente es lo que hay que evitar. Decirle que
    # conteste "si o no" cuesta ocho silabas y quita la ambiguedad entera.
    partes.append(_f("permiso.lo_autorizo", idioma=idioma))
    return Peticion(frase=". ".join(partes).replace("..", "."),
                    elementos=tuple(e for e in decision.elementos if e),
                    cuantos=nombrados)


def interpretar(oido) -> Respuesta:
    """Que contesto: si, no, o nadie.

    Acepta el texto suelto o una `Transcripcion`. Con la transcripcion
    puede distinguir la tercera salida, que es la que importa: si la
    tuberia dice que ahi no hablo nadie, esto NO es un no -- es que la
    pregunta sigue abierta, y puede contestarla la consola o, cuando
    exista, Telegram.
    """
    texto = getattr(oido, "texto", oido) or ""
    sin_habla = getattr(oido, "sin_habla", not str(texto).strip())
    if sin_habla:
        return Respuesta.SIN_RESPUESTA

    # La lista de afirmativas vive en `seguridad/aprobacion.py` y se
    # reutiliza en vez de copiarse: dos listas de "que significa si" en
    # dos archivos acaban divergiendo, y esa divergencia se paga en
    # aprobaciones.
    #
    # Se normaliza con `voz.parada.normalizar`, que ya quita tildes y
    # puntuacion, porque el STT entrega "Vale, adelante." con coma y
    # punto -- y sin eso, "vale," no casa con "vale" y una autorizacion
    # clara sale NO. Medido contra lo que devuelve `small` de verdad.
    from voz.parada import normalizar

    palabras = normalizar(str(texto))
    if not palabras:
        return Respuesta.SIN_RESPUESTA
    if interpretar_respuesta(" ".join(palabras)).aprobado:
        return Respuesta.SI
    # "si, adelante" o "vale, hazlo": la afirmativa ABRE la frase. Se
    # mira solo la primera palabra a proposito, y no la ultima: "no, si
    # me lo dijo" acabaria en algo que no es un no, y "yo no diria que
    # si" acaba en "si". La primera palabra es la que lleva la decision.
    if interpretar_respuesta(palabras[0]).aprobado:
        return Respuesta.SI
    # TODO LO DEMAS ES NO, incluido "claro que si". Es incomodo y es a
    # proposito: aqui, inventar deteccion de afirmativas es inventarla en
    # el unico sitio donde equivocarse EJECUTA algo irreversible. Cuesta
    # repetir; la alternativa cuesta un archivo.
    return Respuesta.NO
