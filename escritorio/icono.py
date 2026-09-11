"""El icono de la bandeja, dibujado en codigo y no cargado de un archivo.

POR QUE DIBUJADO: un `.ico` en disco es una cosa mas que se puede perder
al mover el proyecto, y ademas este icono **cambia de color segun el
estado**, que es lo unico que Jarvis puede decir cuando no hay ventana
abierta ni terminal donde mirar.

LOS COLORES NO SON DECORACION, son los tres estados que importan y se
corresponden con los de la consola:

    listo      hay suelo y la sesion puede abrirse
    escucha    ademas te esta oyendo (--voz)
    roto       algo no esta en condiciones -> mirar el log

>>> Y "ROTO" TIENE QUE VERSE SIN ABRIR NADA <<<
Es la mitad visual del problema que resuelve `escritorio/salida.py`: si
el suelo no muerde, el usuario tiene que enterarse por el icono, porque
en la carpeta Inicio no hay ninguna otra superficie donde mirar.
"""

from __future__ import annotations

# 64 px y no 16: Windows escala hacia abajo mucho mejor que hacia arriba,
# y en pantallas al 150 % un icono de 16 se ve sucio.
LADO = 64

# El mismo lenguaje de color que la consola, y AHORA POR TEMA: desde el
# 2026-08-28 la consola tiene cuatro, y un icono cian sobre una UI color
# cafe es lo primero que canta -- el icono es lo unico de Jarvis que se
# ve cuando la ventana esta cerrada, o sea la unica pieza de la marca que
# no se puede quedar atras.
#
# >>> "ROTO" ES ROJO EN LOS CUATRO, Y NO SE NEGOCIA <<<
# Los otros tres colores son identidad; este es una SEÑAL. Es la mitad
# visual del problema que resuelve `escritorio/salida.py`: con Jarvis en
# la carpeta Inicio, el icono es la unica superficie donde enterarse de
# que el suelo no muerde. Un tema que lo pintara "en su gama" estaria
# eligiendo la estetica por encima de lo unico que no puede mentir.
PALETAS = {
    "jarvis": {
        "listo": (86, 214, 255),       # cian
        "escucha": (128, 255, 190),    # verde neon
        "trabajando": (255, 196, 84),  # ambar
        "roto": (255, 92, 108),
        "fondo": (14, 18, 28),
    },
    "hacker": {
        "listo": (0, 255, 120),
        "escucha": (184, 255, 212),
        "trabajando": (255, 176, 0),
        "roto": (255, 92, 108),
        "fondo": (0, 8, 4),
    },
    "despacho": {
        # >>> "LISTO" ES TINTA, NO CAFE, Y ES POR UNA MEDIDA <<<
        # Hasta el 2026-08-29 era (141,94,54) -- cafe -- y "trabajando"
        # (176,106,26) -- ambar --. Son el mismo tono a distinta
        # luminosidad, y a 16 px en una barra de tareas eso no es una
        # diferencia: es el mismo icono dos veces. Los tres estados
        # tienen que separarse por TONO, no por brillo, porque el icono
        # es lo unico de Jarvis que se ve con la ventana cerrada.
        "listo": (74, 53, 32),         # tinta de documento
        "escucha": (46, 125, 82),      # verde
        "trabajando": (176, 106, 26),  # ambar
        "roto": (255, 92, 108),
        # Claro a proposito: este icono vive en una barra de tareas que
        # casi siempre es oscura, asi que el disco claro es lo que se ve.
        "fondo": (255, 253, 249),
    },
    "nexo": {
        "listo": (20, 26, 34),
        "escucha": (31, 122, 77),
        "trabajando": (194, 120, 18),
        "roto": (255, 92, 108),
        "fondo": (247, 248, 250),
    },
}

# Lo de antes, para quien siga llamando sin decir el tema.
COLORES = {k: v for k, v in PALETAS["jarvis"].items() if k != "fondo"}
FONDO = PALETAS["jarvis"]["fondo"]


def paleta_de(tema: str | None = None) -> dict:
    """Los colores del tema pedido, o los de siempre si no se sabe.

    Un tema desconocido NO es un error que tumbe la bandeja: el icono es
    lo ultimo que puede dejar de dibujarse, porque es donde se lee que
    algo va mal.
    """
    return PALETAS.get(str(tema or "jarvis"), PALETAS["jarvis"])


def tema_elegido() -> str:
    """Que tema hay puesto, preguntandoselo a los ajustes.

    Se lee aqui y no se pasa desde la carcasa porque el icono se
    redibuja en el latido -- cada medio segundo --, o sea que cambiar de
    tema en el panel se nota en la bandeja sin reiniciar nada.
    """
    try:
        from nucleo.ajustes import valor_de

        return str(valor_de("ui.tema", "jarvis") or "jarvis")
    except Exception:  # noqa: BLE001
        return "jarvis"


def dibujar(estado: str = "listo", tema: str | None = None):
    """Un disco con anillo, del color del estado. Devuelve un PIL.Image."""
    from PIL import Image, ImageDraw

    paleta = paleta_de(tema)
    color = paleta.get(estado, paleta["listo"])
    fondo = paleta["fondo"]
    imagen = Image.new("RGBA", (LADO, LADO), (0, 0, 0, 0))
    lapiz = ImageDraw.Draw(imagen)

    borde = 3
    lapiz.ellipse([borde, borde, LADO - borde, LADO - borde],
                  fill=fondo + (255,), outline=color + (255,), width=5)
    # El punto de dentro es lo que se sigue distinguiendo a 16 px, cuando
    # el anillo ya es una linea de un pixel.
    centro = LADO // 2
    radio = LADO // 5
    lapiz.ellipse([centro - radio, centro - radio, centro + radio,
                   centro + radio], fill=color + (255,))
    return imagen


def estado_de(montaje, voz_encendida: bool) -> str:
    """De que color va el icono ahora mismo.

    El orden importa: **roto gana a todo**. Un Jarvis que esta escuchando
    pero cuyo suelo no muerde no es "escuchando", es un problema, y
    pintarlo de verde seria la pantalla mintiendo sobre lo unico que no
    puede mentir.
    """
    sesion = getattr(montaje, "sesion", None)
    if sesion is None:
        return "roto"
    if getattr(sesion, "viva", False):
        return "trabajando"
    return "escucha" if voz_encendida else "listo"


# Los tamaños que Windows saca de un `.ico`. Se meten TODOS en el mismo
# archivo y es el sistema quien elige: la barra de tareas pide 32, la
# barra de titulo 16, y Alt+Tab 48 en pantallas grandes. Dejar solo uno
# obliga a Windows a escalar, y escalar hacia arriba es lo que ensucia.
TAMANOS = ((16, 16), (24, 24), (32, 32), (48, 48), (64, 64))


def a_ico(imagen) -> bytes:
    """El mismo dibujo, en el formato que pide una VENTANA de Windows.

    La bandeja se conforma con un `PIL.Image` (pystray lo convierte solo),
    pero `Form.Icon` quiere un `.ico` de verdad. Se genera en memoria y no
    en disco por la misma razon que `dibujar`: un archivo mas es una cosa
    mas que se puede perder al mover el proyecto, y este cambia de color
    con el estado, asi que habria que reescribirlo igual.

    >>> `bitmap_format="bmp"` NO ES UN DETALLE, Y SE MIDIO <<<
    Por defecto Pillow mete CADA fotograma como PNG, y aunque Windows
    entiende iconos PNG desde Vista, `System.Drawing` no del todo: leer
    de vuelta un `.ico` asi y pedirle la imagen devuelve pixeles basura
    -- medido el 2026-08-27, el centro del disco salia (122, 33, 20)
    donde el color del estado es (86, 214, 255). Con DIB salen los cuatro
    estados exactos. Lo caro habria sido no mirarlo: el icono se ve
    igual de bien en la barra, y el que se rompe es cualquier camino que
    vuelva a leerlo.
    """
    import io

    buf = io.BytesIO()
    imagen.save(buf, format="ICO", sizes=list(TAMANOS), bitmap_format="bmp")
    return buf.getvalue()
