"""Lo unico que Jarvis sigue escuchando mientras trabaja: "para".

>>> POR QUE ESTO EXISTE, Y POR QUE NO ES UN DETALLE DE IMPLEMENTACION <<<
JC-0011 apaga la escucha mientras Jarvis trabaja, y esa decision tiene un
filo: una escucha apagada del todo es una escucha que no oye "para"
mientras el cerebro de la nube esta actuando sobre la PC. Quedo escrito
antes de que existiera nada de esto:

    "un 'para' que no se oye es MAS caro que antes, no menos"

Asi que apagada significa **apagada para ORDENES NUEVAS**. El mismo audio
sigue entrando y transcribiendose; lo que cambia es QUE se acepta, y este
modulo es ese filtro.

>>> TRES VEREDICTOS, NO DOS <<<

    PARA     se para: se dijo una palabra de parada y se dijo como tal
    SIGUE    no era para nosotros
    DUDOSA   sono a parada pero la transcripcion no se sostiene

DUDOSA no es adorno. Existe el caso real en el que el texto dice "para" y
el resto de la tuberia dice que ahi no hablo nadie (`sin_habla`): el
modelo y el VAD se contradicen, y colapsar eso contra "sigue" es
exactamente el fallo abierto de siempre. Quien decide que
hacer con la duda es `voz/ciclo.py`, y la para -- ver alli el porque.

>>> EL PROBLEMA DE VERDAD: "para" ES UNA PREPOSICION <<<
"cancela" casi no aparece en una conversacion; "para" aparece cada tres
frases, y encima aparece **en lo que dice el propio Jarvis** ("he creado
la carpeta para tus facturas"), que es justo el audio que mas cerca esta
del microfono mientras habla. Un reconocedor que pare con cualquier
"para" no es un asistente prudente, es uno que no puede trabajar.

Por eso el lexico esta partido en dos y no en uno:

  * **Inequivocas** (`cancela`, `detente`, `basta`...): valen aparezcan
    donde aparezcan. Nadie las suelta por casualidad.
  * **Ambiguas** (`para`, `no`, `alto`, `espera`): solo valen si ABREN la
    frase, y solo si la frase es corta. Una parada se dice sola y se dice
    ya; una preposicion va enterrada en mitad de una oracion larga.

>>> LO QUE ESTA MEDIDO Y LO QUE NO, DICHO DE FRENTE <<<
MEDIDO (2026-08-25, las 30 ordenes reales de `eval/audio_ordenes/` con el
STT de produccion -- `small` con ancla; traza en
`eval/trazas_voz/ordenes_small_ancla.json`): las tres paradas del corpus
salen limpias y este modulo las caza, y las otras 27 no disparan ninguna.

    26  "cancela"      -> 'Cancela'      PARA
    27  "para"         -> 'para.'        PARA
    29  "no, ese no"   -> 'No, ese no.'  PARA
    otras 27                             SIGUE, ninguna dudosa

NO MEDIDO, y es el agujero que hay que saber: **ninguna de las 30
grabaciones contiene "para" como preposicion**, asi que el corpus NO
prueba la regla de la palabra enterrada. Esa regla esta RAZONADA, no
medida. Lo que la probaria es una tanda hablando cerca del microfono
mientras Jarvis trabaja, contando cuantas veces se para sin que nadie se
lo pidiera; hasta que exista, esto es una hipotesis con forma de codigo.

NO HACE FALTA (y por eso no esta): correccion difusa de la transcripcion.
`tiny` destroza estas palabras ('cancela' -> 'Cancella', 'para' ->
'Vara') y `base` tropieza, pero produccion corre `small` y con `small`
salen exactas. Anadir tolerancia a errores que el modelo elegido NO
comete solo compra paradas falsas.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum

from voz.stt import Transcripcion

# >>> EL LEXICO SE MUDO A `voz/idioma.py` EL 2026-08-28 (JC-0018) <<<
# No por orden: porque en ingles ESTA PARTICION ES OTRA. En español
# "stop" es un extranjerismo que nadie suelta sin querer y por eso era
# inequivoco; en ingles es el verbo de "stop the server", o sea una orden
# legitima, asi que alli es AMBIGUO y ademas con una ventana mas corta.
# Traducir las listas habria convertido media docena de ordenes normales
# en paradas, y eso no se ve hasta que te para a mitad de trabajo.
#
# Estos tres nombres se conservan para que el codigo -- y los tests que
# miden el español -- sigan leyendose igual. Son el lexico del ESPAÑOL.
from voz.idioma import PARADA as _PARADA

PALABRAS_DE_UNA_PARADA = _PARADA["es"].palabras_max
INEQUIVOCAS = _PARADA["es"].inequivocas
AMBIGUAS = _PARADA["es"].ambiguas


class Veredicto(Enum):
    """Que hacer con lo que se acaba de oir mientras Jarvis trabaja."""

    PARA = "para"
    SIGUE = "sigue"
    DUDOSA = "dudosa"


@dataclass(frozen=True)
class Juicio:
    """El veredicto y POR QUE, que es lo que se puede leer en la consola.

    Lleva `palabras` a proposito: es la magnitud continua que hace falta.
    Un "PARA" de una frase de 1 palabra y otro de una de 4 no valen lo
    mismo cuando alguien vaya a revisar por que se paro solo, y una
    bandera sola no deja distinguirlos.
    """

    veredicto: Veredicto
    disparador: str = ""
    """La palabra que lo causo. Vacia si no hubo ninguna."""

    palabras: int = 0
    texto: str = ""

    @property
    def para(self) -> bool:
        """Atajo para el caso comun. La duda NO se cuela aqui: quien
        decide que hacer con ella es el ciclo, y tiene que verla."""
        return self.veredicto is Veredicto.PARA

    def describe(self) -> str:
        if self.veredicto is Veredicto.SIGUE:
            return f"sigue ({self.texto.strip()!r})"
        return (f"{self.veredicto.value.upper()} por {self.disparador!r} "
                f"en {self.palabras} palabra(s): {self.texto.strip()!r}")


def normalizar_con_mapa(texto: str) -> tuple[str, list[int]]:
    """Lo mismo que `normalizar`, pero SIN partir y sabiendo de donde
    viene cada caracter.

    >>> PARA QUE HACE FALTA SABER DE DONDE VIENE <<<
    `voz/proyecto.py` tiene que devolver la COLA de la frase -- lo que se
    pidio ademas de cambiar de proyecto -- y esa cola hay que sacarla del
    texto ORIGINAL, no de aqui. Normalizado, "guardalo como estado.md" se
    convierte en "guardalo como estado md": el punto se vuelve un espacio
    y el nombre del archivo deja de serlo. Mandar eso al cerebro es
    pedirle que cree un archivo que no es el que dijiste.

    `indices[i]` es la posicion en `texto` del caracter que produjo
    `salida[i]`. Se construye caracter a caracter porque `lower()` y la
    descomposicion NFD pueden dar mas de uno, y entonces los dos apuntan
    al mismo sitio del original, que es lo correcto.
    """
    salida: list[str] = []
    indices: list[int] = []
    for posicion, caracter in enumerate(texto):
        for trozo in unicodedata.normalize("NFD", caracter.lower()):
            if unicodedata.category(trozo) == "Mn":
                continue
            salida.append(trozo if (trozo.isalnum() or trozo.isspace()) else " ")
            indices.append(posicion)
    return "".join(salida), indices


def normalizar(texto: str) -> list[str]:
    """Lowercase, sin tildes, sin puntuacion, en palabras.

    Las tres cosas hacen falta contra lo que el STT entrega de verdad, y
    no son suposiciones: el corpus da 'Cancela' (mayuscula, sin punto),
    'para.' (minuscula, con punto) y 'No, ese no.' (coma en medio).

    NO reimplementa la limpieza: la comparte con `normalizar_con_mapa`.
    Este archivo ya avisa en otro sitio de que en el arbol llego a haber
    TRES normalizadores y de como acaban divergiendo.
    """
    return normalizar_con_mapa(texto)[0].split()


def mirar(oido: str | Transcripcion, idioma: str | None = None) -> Juicio:
    """Decide si lo que se acaba de oir es una orden de parar.

    Acepta el texto suelto o la `Transcripcion` entera. Con la
    transcripcion sabe ademas si el resto de la tuberia se cree que ahi
    hablo alguien, y es lo que separa un PARA de una DUDOSA; con el texto
    solo, esa pregunta no se ha hecho y no se puede fingir que si.

    `idioma` es None por defecto y entonces se pregunta al ajuste. Se
    puede forzar, y los tests lo hacen: medir el lexico español con el
    ingles puesto no diria nada de ninguno de los dos.
    """
    from voz.idioma import lexico_de_parada

    lexico = lexico_de_parada(idioma)

    if isinstance(oido, str):
        texto, sin_habla = oido, False
    else:
        texto, sin_habla = oido.texto, oido.sin_habla

    palabras = normalizar(texto)
    if not palabras:
        return Juicio(Veredicto.SIGUE, texto=texto)

    disparador = ""
    for palabra in palabras:
        if palabra in lexico.inequivocas:
            disparador = palabra
            break
    else:
        # Ambigua: solo si ABRE la frase y la frase es corta. Las dos
        # condiciones juntas, no una: "para" abriendo una frase de doce
        # palabras es una preposicion.
        if (palabras[0] in lexico.ambiguas
                and len(palabras) <= lexico.palabras_max):
            disparador = palabras[0]

    if not disparador:
        return Juicio(Veredicto.SIGUE, palabras=len(palabras), texto=texto)

    # Sono a parada. La ultima pregunta es si creerse la transcripcion:
    # si el resto de la tuberia dice que ahi no hablo nadie, el texto y
    # las senales se contradicen, y eso es la tercera salida, no un no.
    veredicto = Veredicto.DUDOSA if sin_habla else Veredicto.PARA
    return Juicio(veredicto, disparador=disparador,
                  palabras=len(palabras), texto=texto)
