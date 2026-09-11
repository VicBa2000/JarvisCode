"""Lo que el usuario puede tocar desde la UI, y lo que le cuesta tocarlo.

>>> POR QUE ESTO NO ESCRIBE EN `config/jarvis.yaml` <<<
Ese archivo tiene 512 lineas y **420 son comentarios**: el 82 % es el
razonamiento medido de veinte dias -- por que el umbral del wake word es
0,5 y no 0,6, por que el host API es DirectSound, que paso las cuatro
veces que se intento otra cosa. PyYAML no conserva comentarios: leerlo y
volver a escribirlo con un valor cambiado **borraria todo eso sin decir
nada**, y seria la peor perdida que este proyecto puede sufrir, porque no
esta en ningun otro sitio.

Asi que la UI escribe en `config/ajustes.yaml`, que contiene SOLO lo que
el usuario ha cambiado, y ese archivo PISA al otro. Es exactamente el
patron que ya usa `config/zonas.yaml` (JC-0007). `jarvis.yaml` se queda
como la linea base medida, editable a mano y con sus comentarios
intactos.

UN ARCHIVO AUSENTE SIGNIFICA "NADA CAMBIADO", nunca "todo por defecto de
otra cosa": sin `ajustes.yaml` rige `jarvis.yaml` tal cual.

>>> TRES RESPUESTAS A "¿CUANDO SE APLICA?", NO DOS <<<
Es la leccion del panel de zonas, que en su primera version dijo
"aplicado ya" apoyandose en como creia que funcionaba el archivo de
`--settings`, y se MIDIO que no se sostenia. Un ajuste puede:

    ya          se nota en el siguiente turno
    reabrir     hace falta reabrir la sesion de Claude Code
    reiniciar   hace falta reiniciar Jarvis entero

Y la pantalla tiene que decir cual, porque un ajuste que parece aplicado
y no lo esta es la pantalla mintiendo.

>>> LO QUE NO SE DEJA TOCAR, Y ES A PROPOSITO <<<
`UMBRAL_SIN_HABLA`. No esta aqui y no va a estar: no es un gusto, es una
CONSECUENCIA del ancla de vocabulario, y `voz/stt.py` ya lo elige solo
segun haya ancla o no. Medido el 2026-08-21 sobre el corpus real:

        sin ancla   habla max 0.219  <  silencio min 0.686   -> 0.6
        con ancla   habla max 0.031  <  silencio min 0.490   -> 0.25

Dejar los dos sueltos permitiria la combinacion "ancla puesta con umbral
0,6", que cuela CUATRO de los doce silencios COMO ORDENES -- texto
inventado por Whisper viajando a un agente que actua sobre la PC. La
peticion del usuario al pedir este panel fue explicita: cuidado con el
STT y con el ancla, que no se le de la opcion de romperlo todo.
La forma de cumplirla no es un aviso en rojo: es que la combinacion mala
no se pueda expresar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from nucleo.configuracion import CONFIG_DIR, load_general_config

# El centinela vive en `voz.audio` -- ahi es donde se resuelve --
# y se importa tarde para que leer ajustes no arrastre PortAudio.
PREDETERMINADO = "sistema"

ARCHIVO = "ajustes.yaml"

# >>> EL ORDEN ES EL DE ALGUIEN QUE ACABA DE INSTALAR ESTO <<<
# No se agrupa por subsistema -- "voz", "stt", "tiempos" -- porque eso es
# el mapa de NUESTRO codigo, no el de las preguntas del usuario. Se
# agrupa por lo que uno quiere hacer, y en el orden en que lo quiere:
# primero echarlo a andar, luego que te oiga, luego lo opcional, y al
# final lo que casi nadie va a tocar.
GRUPOS = (
    # >>> LA PANTALLA VA PRIMERO, Y NO ES POR VANIDAD <<<
    # Rompe la regla de "lo esencial arriba" a proposito: el selector de
    # idioma es el UNICO ajuste que tiene que encontrar alguien que no
    # puede leer la pagina. Puesto arriba se localiza sin leer nada --
    # buscas la palabra "English" y esta en el primer bloque --; puesto
    # entre lo avanzado, para encontrarlo hay que entender el idioma que
    # justamente no entiendes.
    ("pantalla", "La pantalla",
     "Como lo ves y en que idioma. No cambia nada de lo que Jarvis hace."),
    ("empezar", "Para empezar", "Lo minimo para que Jarvis sirva de algo."),
    ("oir", "Oir y hablar",
     "Por donde te escucha y por donde te contesta. Pruebalos: es la "
     "unica forma de saber que has acertado."),
    ("avanzado", "Avanzado",
     "Ya funciona sin tocar nada de esto. Cada uno dice lo que cuesta "
     "cambiarlo."),
)


class AjustesError(RuntimeError):
    """El archivo de ajustes esta malformado o el valor no vale."""


@dataclass(frozen=True)
class Ajuste:
    """Un ajuste, con todo lo que la pantalla necesita para pintarlo."""

    clave: str
    etiqueta: str
    grupo: str
    tipo: str                 # interruptor | eleccion | numero | lista
                              # | texto | parrafo
    valor: Any
    por_defecto: Any
    aplica: str               # ya | reabrir | reiniciar
    ayuda: str = ""
    opciones: list[dict[str, str]] = field(default_factory=list)
    minimo: float | None = None
    maximo: float | None = None
    unidad: str = ""
    prueba: str = ""
    """Si trae boton de probar, que se prueba: "entrada" o "salida"."""
    aviso: str = ""
    """El COSTE de equivocarse, si lo tiene. La pantalla lo pinta
    PLEGADO, detras de un "¿por que?": es informacion que salva a quien
    la busca y abruma a quien acaba de instalar el programa."""

    def a_json(self) -> dict[str, Any]:
        return {
            "clave": self.clave, "etiqueta": self.etiqueta, "grupo": self.grupo,
            "tipo": self.tipo, "valor": self.valor, "por_defecto": self.por_defecto,
            "aplica": self.aplica, "ayuda": self.ayuda, "opciones": self.opciones,
            "minimo": self.minimo, "maximo": self.maximo, "unidad": self.unidad,
            "aviso": self.aviso, "prueba": self.prueba,
        }


# ----------------------------------------------------------------------
#  Leer y escribir la eleccion del usuario
# ----------------------------------------------------------------------


def ruta(config_dir: Path | None = None) -> Path:
    return (config_dir or CONFIG_DIR) / ARCHIVO


def leer(config_dir: Path | None = None) -> dict[str, Any]:
    """Lo que el usuario ha cambiado. `{}` si no ha cambiado nada.

    UN YAML MALFORMADO LEVANTA en vez de ignorarse, igual que en
    `zonas.yaml`: arrancar con unos ajustes distintos de los que el
    usuario configuro, y callarselo, es peor que no arrancar.
    """
    destino = ruta(config_dir)
    if not destino.is_file():
        return {}
    try:
        with destino.open("r", encoding="utf-8") as f:
            datos = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise AjustesError(f"YAML invalido en {destino}: {exc}") from exc
    if datos is None:
        return {}
    if not isinstance(datos, dict):
        raise AjustesError(f"{destino} deberia ser un mapa de clave a valor.")
    return datos


def _en_ruta(datos: dict, clave: str, defecto: Any = None) -> Any:
    """Busca "voz.audio.salida" dentro de un dict anidado."""
    actual: Any = datos
    for parte in clave.split("."):
        if not isinstance(actual, dict) or parte not in actual:
            return defecto
        actual = actual[parte]
    return actual


def valor_de(clave: str, defecto: Any = None,
             config_dir: Path | None = None) -> Any:
    """El valor efectivo: lo del usuario si lo hay, si no lo de la base.

    Es la UNICA funcion que sabe que hay dos archivos. Todo lo demas
    pregunta por aqui y no se entera de la superposicion.
    """
    propios = leer(config_dir)
    if clave in propios:
        return propios[clave]
    try:
        base = load_general_config(config_dir) or {}
    except Exception:  # noqa: BLE001 - sin base, manda el defecto
        return defecto
    encontrado = _en_ruta(base, clave, _AUSENTE)
    return defecto if encontrado is _AUSENTE else encontrado


_AUSENTE = object()


def guardar(cambios: dict[str, Any], config_dir: Path | None = None) -> dict[str, Any]:
    """Escribe los cambios, DESPUES de validarlos todos.

    O entran todos o no entra ninguno: una escritura a medias dejaria
    unos ajustes que el usuario no eligio, y el panel diria que si.
    """
    # >>> EL CATALOGO TRADUCIDO, Y NO EL CRUDO <<<
    # De aqui salen los mensajes de error que el usuario LEE al guardar
    # ("'Como se ve' no es una opcion valida"), y llevan dentro la
    # ETIQUETA del ajuste. Con el catalogo crudo, un error en una
    # pantalla en ingles nombraria el ajuste por su nombre español, o
    # sea por un rotulo que no esta en pantalla: el usuario no sabria
    # cual de los que ve ha fallado.
    from nucleo.textos import traducir_catalogo

    catalogo_actual = {
        a.clave: a for a in traducir_catalogo(catalogo(config_dir), config_dir)
    }
    limpios: dict[str, Any] = {}
    for clave, bruto in cambios.items():
        ajuste = catalogo_actual.get(clave)
        if ajuste is None:
            raise AjustesError(f"No existe el ajuste '{clave}'.")
        limpios[clave] = validar(ajuste, bruto)

    # >>> Y ANTES DE ESCRIBIR, EL PAR DE LA VOZ <<<
    # Va DESPUES de validar y ANTES de mezclar, que es el unico hueco
    # donde se sabe lo que va a quedar y todavia se puede corregir. Lo
    # que anada aqui entra en `limpios`, o sea que se escribe Y se le
    # cuenta al panel como un ajuste mas.
    _emparejar_la_voz(limpios, catalogo_actual, config_dir)

    propios = leer(config_dir)
    propios.update(limpios)
    destino = ruta(config_dir)
    destino.parent.mkdir(parents=True, exist_ok=True)
    cabecera = (
        "# Lo que has cambiado desde la consola de Jarvis.\n"
        "#\n"
        "# ESTE ARCHIVO PISA A `jarvis.yaml`, que se queda como la linea\n"
        "# base medida y con sus comentarios intactos -- 420 de sus 512\n"
        "# lineas son el razonamiento de por que cada numero es el que es,\n"
        "# y reescribirlo desde la UI lo borraria sin avisar.\n"
        "#\n"
        "# Se puede editar a mano. Borrar una clave la devuelve a la base;\n"
        "# borrar el archivo entero devuelve todo a la base.\n"
    )
    with destino.open("w", encoding="utf-8") as f:
        f.write(cabecera)
        yaml.safe_dump(propios, f, allow_unicode=True, sort_keys=True)
    return limpios


def validar(ajuste: Ajuste, bruto: Any) -> Any:
    """Devuelve el valor limpio o levanta. Sin terceras vias."""
    if ajuste.tipo == "interruptor":
        if isinstance(bruto, bool):
            return bruto
        if isinstance(bruto, str) and bruto.lower() in ("true", "false"):
            return bruto.lower() == "true"
        raise AjustesError(f"'{ajuste.etiqueta}' es un si o un no.")

    if ajuste.tipo == "numero":
        try:
            valor = float(bruto)
        except (TypeError, ValueError) as exc:
            raise AjustesError(f"'{ajuste.etiqueta}' tiene que ser un numero.") from exc
        if ajuste.minimo is not None and valor < ajuste.minimo:
            raise AjustesError(
                f"'{ajuste.etiqueta}' no puede bajar de {ajuste.minimo:g}"
                f"{(' ' + ajuste.unidad) if ajuste.unidad else ''}.")
        if ajuste.maximo is not None and valor > ajuste.maximo:
            raise AjustesError(
                f"'{ajuste.etiqueta}' no puede pasar de {ajuste.maximo:g}"
                f"{(' ' + ajuste.unidad) if ajuste.unidad else ''}.")
        return valor

    if ajuste.tipo == "eleccion":
        validos = [o["valor"] for o in ajuste.opciones]
        if bruto not in validos:
            # >>> AQUI SE IMPIDE ROMPERLO <<< Las opciones no son una
            # sugerencia: se construyen mirando QUE HAY DE VERDAD (los
            # modelos en disco, los dispositivos presentes), asi que un
            # valor de fuera de la lista es un Jarvis que no arranca.
            raise AjustesError(
                f"'{bruto}' no es una opcion valida de '{ajuste.etiqueta}'. "
                f"Hay: {', '.join(str(v) for v in validos) or '(ninguna)'}")
        return bruto

    if ajuste.tipo == "parrafo":
        # >>> SE RECORTA, Y ESO ES LO QUE HACE EXISTIR LA TERCERA SALIDA <<<
        # Un campo con tres espacios dentro se ve VACIO en la pantalla. Si
        # no se recortase, "   " seria una frase que Jarvis mandaria de
        # verdad -- un turno entero, con su coste -- mientras el panel
        # ensena una caja vacia. Recortado, vacio significa vacio, que es
        # la salida "abre y no digas nada" que el usuario pidio.
        return str(bruto).strip()

    if ajuste.tipo == "lista":
        if isinstance(bruto, str):
            bruto = [t.strip() for t in bruto.split(",")]
        if not isinstance(bruto, list):
            raise AjustesError(f"'{ajuste.etiqueta}' es una lista.")
        return [str(x).strip() for x in bruto if str(x).strip()]

    return str(bruto)


# ----------------------------------------------------------------------
#  El catalogo: que se puede tocar, y que cuesta tocarlo
# ----------------------------------------------------------------------


def _opciones_de_audio(tipo: str) -> list[dict[str, str]]:
    """Los dispositivos QUE HAY, mas el alias del sistema.

    >>> LA LISTA SE CONSTRUYE MIRANDO, NO ADIVINANDO <<<
    Es la regla que abre `voz/audio.py`: en esta maquina 16 de los 23
    endpoints son cables de audio virtuales que entregan silencio
    digital perfecto sin dar error. Ofrecer una lista escrita a mano
    dejaria elegir uno que no esta, y el fallo no seria un error sino un
    Jarvis sordo para siempre.
    """
    from voz.audio import (
        PREDETERMINADO,
        AudioError,
        listar,
        nombre_del_predeterminado,
    )

    quien = nombre_del_predeterminado(tipo)
    opciones = [{
        "valor": PREDETERMINADO,
        "etiqueta": ("El que tenga Windows puesto"
                     + (f" (ahora: {quien})" if quien else "")),
    }]
    try:
        for d in listar(tipo):
            # >>> EL ALIAS NO SE OFRECE DOS VECES <<<
            # Bajo DirectSound, "Controlador primario de..." no es un
            # aparato: es el mismo predeterminado de arriba con otro
            # nombre. Ponerlo suelto haria que la lista tuviera dos
            # entradas que hacen lo mismo y una de ellas sin explicar.
            if d.nombre.lower().startswith("controlador primario"):
                continue
            opciones.append({"valor": d.nombre, "etiqueta": d.nombre})
    except AudioError:
        # Sin PortAudio no hay lista. NO se inventa una: se queda solo el
        # alias, y el boton de probar dira la verdad.
        pass
    return opciones


def dispositivo_actual(tipo: str, config_dir: Path | None = None) -> str:
    """Por donde habla o escucha AHORA MISMO, resuelto de verdad.

    POR QUE NO VALE LO QUE PONE EN EL ARCHIVO: ahi los nombres son
    PARCIALES a proposito -- pone "micro USB" y el aparato se llama
    "Microfono (marca y modelo)" --, asi que enseñar el archivo tal cual
    dejaria el desplegable con un valor que no esta entre sus opciones, y
    guardar lo rechazaria. Se resuelve como lo resuelve la voz.

    Cadena vacia si no resuelve, y eso YA ES INFORMACION: significa que
    lo configurado no esta presente.
    """
    from voz.audio import PREDETERMINADO as _P
    from voz.audio import AudioError, ConfigAudio

    crudo = valor_de(f"voz.audio.{tipo}", None, config_dir)
    if uno_solo(crudo) == _P:
        return _P
    try:
        config = ConfigAudio.desde_config(config_dir)
        d = config.microfono() if tipo == "entrada" else config.altavoz()
    except (AudioError, Exception):  # noqa: BLE001
        return ""
    return d.nombre


# El idioma de un perfil se lee del PREFIJO de su voz de Piper
# ("es_ES-davefx-medium" -> es). Es la misma fuente que mira
# `voz/perfil.py` para negarse a arrancar con un perfil que no cuadra con
# `voz.idioma`; escribirlo dos veces con dos criterios acabaria diciendo
# la pantalla una cosa y el arranque otra.
_IDIOMA_DE_LA_VOZ = {"es": "Español", "en": "English"}


def _idioma_que_habla(perfil: str, config_dir: Path | None = None) -> str | None:
    """En que idioma habla un perfil, o `None` si NO SE SABE.

    Misma fuente y mismo criterio que `voz.perfil._comprobar_idioma`: el
    PREFIJO de la voz de Piper. Tres salidas, y la tercera no es un
    tecnicismo -- una voz propia puede llamarse como quiera, y declararla
    mala aqui convertiria una voz legitima en un Jarvis que no arranca.
    """
    try:
        base = load_general_config(config_dir) or {}
        perfiles = ((base.get("voz") or {}).get("perfiles") or {})
        voz = str((perfiles.get(perfil) or {}).get("tts_voz", ""))
    except Exception:  # noqa: BLE001
        return None
    prefijo = voz.split("_", 1)[0].lower()
    return prefijo if prefijo in _IDIOMA_DE_LA_VOZ else None


def _perfil_que_hable(idioma: str, config_dir: Path | None = None) -> str | None:
    """El primer perfil declarado que hable `idioma`, o `None` si no hay.

    "El primero" es el orden del YAML, o sea el que escribio quien monto
    la instalacion: para `es` sale `jarvis`, que es el perfil medido.
    Elegir por otro criterio -- alfabetico, el ultimo -- seria igual de
    arbitrario y ademas no se leeria en el archivo.
    """
    try:
        base = load_general_config(config_dir) or {}
        perfiles = ((base.get("voz") or {}).get("perfiles") or {})
    except Exception:  # noqa: BLE001
        return None
    for clave in perfiles:
        if _idioma_que_habla(clave, config_dir) == idioma:
            return clave
    return None


def _emparejar_la_voz(
    limpios: dict[str, Any],
    catalogo_actual: dict[str, "Ajuste"],
    config_dir: Path | None = None,
) -> None:
    """`voz.idioma` y `voz.perfil` viajan JUNTOS. Modifica `limpios`.

    >>> DECISION DEL USUARIO (2026-09-10), Y REVIERTE LA DE ANTES <<<
    Hasta hoy estos dos ajustes eran independientes y lo que los cuidaba
    era `voz/perfil.py`, que se NIEGA a arrancar la voz cuando no
    cuadran. Esa negativa es correcta y se queda: sin ella, Piper leeria
    español con fonetica inglesa y eso no da error, solo suena raro.

    Lo que estaba mal era llegar a ese estado. El usuario lo vivio tres
    veces seguidas, en las dos direcciones -- perfil ingles con idioma
    español, y despues perfil español con idioma ingles --, y cada una
    costaba un reinicio para enterarse:

        NO SE PUDO ENCENDER LA VOZ: TTSError: El perfil activo 'jarvis'
        habla con una voz 'es' pero Jarvis esta puesto en 'en'.

    Sus palabras: *"son dos ajustes que deben ir juntos, o ambos en
    español, o ambos en ingles"*. Asi que el par se cuida AL GUARDAR, que
    es antes de reiniciar y por tanto antes de que duela.

    >>> POR QUE AQUI Y NO EN LA PAGINA <<<
    `guardar` es la unica puerta por la que se escribe `ajustes.yaml`, y
    la cabecera de ese archivo invita a editarlo a mano. Con esto en el
    JS, la pareja quedaria coherente solo para quien use el panel, que es
    el mismo reparto que ya fallo con `guardar_mcp` y con
    `guardar_proyectos`: lo que decide una cosa, en un sitio.

    TRES SALIDAS, y ninguna inventa nada:
      * cuadran, o el perfil habla un idioma que no reconocemos -> nada
      * se cambio UNO -> el otro le sigue, y viaja en `limpios`, o sea
        que la pantalla lo enseña en su lista de "hace falta reiniciar"
        sin que haya que escribir una linea para contarlo
      * se cambiaron LOS DOS y no cuadran -> se levanta. Es lo unico que
        no se puede resolver sin adivinar cual de los dos querias, y
        adivinar aqui deja al usuario con una voz que no eligio.
    """
    toca_idioma = "voz.idioma" in limpios
    toca_perfil = "voz.perfil" in limpios
    if not (toca_idioma or toca_perfil):
        return
    aj_idioma = catalogo_actual.get("voz.idioma")
    aj_perfil = catalogo_actual.get("voz.perfil")
    if aj_idioma is None or aj_perfil is None:
        return

    idioma = str(limpios.get("voz.idioma", aj_idioma.valor))
    perfil = str(limpios.get("voz.perfil", aj_perfil.valor))
    habla = _idioma_que_habla(perfil, config_dir)
    if habla is None or habla == idioma:
        return

    nombre_idioma = _IDIOMA_DE_LA_VOZ.get(idioma, idioma)
    nombre_habla = _IDIOMA_DE_LA_VOZ.get(habla, habla)
    if toca_idioma and toca_perfil:
        raise AjustesError(
            f"Esa voz habla {nombre_habla} y has puesto '{aj_idioma.etiqueta}' "
            f"en {nombre_idioma}. Los dos van juntos: elige una voz de ese "
            f"idioma, o cambia solo el idioma y se elige la voz sola.")

    if toca_idioma:
        otro = _perfil_que_hable(idioma, config_dir)
        if otro is None:
            raise AjustesError(
                f"No hay ninguna voz declarada en {nombre_idioma}, asi que "
                f"no se puede cambiar el idioma: la voz que hay habla "
                f"{nombre_habla} y Jarvis no arrancaria. Añade una voz de "
                f"ese idioma en `config/jarvis.yaml`.")
        limpios["voz.perfil"] = validar(aj_perfil, otro)
    else:
        limpios["voz.idioma"] = validar(aj_idioma, habla)


def _opciones_de_perfil(config_dir: Path | None = None) -> list[dict[str, str]]:
    """Los perfiles declarados, DICIENDO EN QUE IDIOMA HABLA CADA UNO.

    >>> HABIA DOS OPCIONES QUE SE LEIAN IGUAL (2026-09-03) <<<
    Esta lista salia como "Jarvis (es_ES-davefx-medium)" y "Jarvis
    (en_US-lessac-medium)": el MISMO nombre dos veces, y lo unico que las
    separaba era una cadena tecnica entre parentesis que no significa
    nada para quien no la haya visto antes. Elegir la que no cuadra con
    `voz.idioma` se guarda sin protestar -- `validar` solo comprueba que
    el valor este en la lista -- y luego `voz/perfil.py` se niega a
    arrancar la voz. El error que sale es bueno y dice exactamente que
    pasa, pero llega DESPUES de reiniciar y no cuesta nada evitarlo
    aqui.

    >>> Y NO SE FILTRAN POR IDIOMA, QUE ERA LA OTRA SALIDA <<<
    Enseñar solo los del idioma puesto habria dejado un callejon: para
    pasarse al ingles hay que cambiar `voz.idioma` Y el perfil, y con la
    lista filtrada el perfil ingles no aparece hasta DESPUES de guardar
    el idioma -- o sea que no se puede guardar lo uno sin lo otro y el
    panel manda los dos cambios juntos. Se enseñan los tres, con el
    idioma delante, y el par se elige a la vista. Ademas el ingles esta
    PENDIENTE de su banco (JC-0018) y esconderlo aqui seria decidirlo por
    la puerta de atras.
    """
    try:
        base = load_general_config(config_dir) or {}
        perfiles = ((base.get("voz") or {}).get("perfiles") or {})
    except Exception:  # noqa: BLE001
        return []
    opciones = []
    for clave, d in perfiles.items():
        datos = d or {}
        voz = str(datos.get("tts_voz", "?"))
        # TRES SALIDAS: español / ingles / NO SE SABE. Una voz
        # propia con otro prefijo no se declara mala -- `voz/perfil.py`
        # tampoco lo hace -- y se queda sin etiqueta de idioma en vez de
        # con una inventada.
        idioma = _IDIOMA_DE_LA_VOZ.get(voz.split("_", 1)[0].lower())
        nombre = datos.get("nombre", clave)
        opciones.append({
            "valor": clave,
            "etiqueta": (f"{nombre} — {idioma} ({voz})" if idioma
                         else f"{nombre} ({voz})"),
        })
    return opciones


def _opciones_de_stt() -> list[dict[str, str]]:
    """SOLO los modelos que estan en disco.

    Ofrecer `large-v3` cuando no esta descargado es ofrecer un Jarvis que
    no arranca. Es la misma regla que la lista de audio: se mira.
    """
    from voz.stt import modelos_descargados

    return [{"valor": m, "etiqueta": m} for m in modelos_descargados()]


def uno_solo(valor: Any, defecto: str = "") -> str:
    """Un dispositivo, para un desplegable.

    EN EL ARCHIVO BASE LOS DISPOSITIVOS SON UNA LISTA ORDENADA, y eso no
    es un capricho: se usa el primero que este PRESENTE, asi que un micro
    USB puede ir delante y usarse solo el dia que se enchufe, cayendo al
    de placa mientras no este. Un desplegable no puede expresar eso.

    LA SALIDA: la UI enseña y escribe UNO -- la cabeza de la lista, que
    es el que manda de verdad -- y la cadena de respaldo sigue siendo
    cosa de editar `jarvis.yaml` a mano. Se prefiere eso a inventarse un
    editor de listas ordenadas que nadie ha pedido, y a fingir que el
    segundo de la lista no existe.
    """
    if isinstance(valor, str):
        return valor
    if isinstance(valor, list) and valor:
        return str(valor[0])
    return defecto


SIN_ELEGIR = object()
"""Centinela: la clave no esta en NINGUNO de los dos archivos.

>>> HACE FALTA PORQUE `valor_de` COLAPSA DOS COSAS <<<
Devuelve el defecto tanto si la clave falta como si vale lo mismo que el
defecto, y para el ritual eso no sirve: una cadena VACIA guardada a
proposito significa "abre y no digas nada", y la clave ausente significa
"no me has dicho nada, manda la de fabrica". Son respuestas distintas y
el codigo necesita tres salidas. Se resuelve pasando esto como
defecto en vez de "".
"""


def ritual_de_fabrica(config_dir: Path | None = None) -> str:
    """La frase que Jarvis manda si nadie ha escrito la suya.

    Sale de `voz/idioma.py`, que es donde vive UNA por idioma, y no se
    copia aqui: dos fuentes para la misma frase es como divergieron los
    tres normalizadores de `voz/`.

    El import es tardio a proposito -- `voz/idioma.py` lee ajustes, asi
    que arriba seria un ciclo -- y es barato: ese modulo son diccionarios
    y expresiones regulares, sin nada de audio detras.
    """
    from voz.idioma import ritual

    return ritual(config_dir=config_dir)


def _ritual_del_panel(config_dir: Path | None = None) -> str:
    """Lo que la caja del panel tiene que ensenar HOY.

    >>> Y LO PREGUNTA A QUIEN LO LEE DE VERDAD, NO A SI MISMO <<<
    La lectura vive en `voz/proyecto.py`, que es quien construye el turno,
    y aqui solo se consulta. Un panel que leyera su propia clave por su
    cuenta volveria a ser un mando girando en el vacio: ensenaria bien el
    valor guardado sin que nadie aguas abajo lo recogiera, que es
    exactamente lo que paso con el umbral del wake word.

    Sin nada elegido ensena la frase de fabrica, que es lo que Jarvis
    manda hoy: una caja vacia mentiria, porque el ritual SI se manda.
    """
    from voz.proyecto import ritual_elegido

    elegida = ritual_elegido(config_dir)
    return ritual_de_fabrica(config_dir) if elegida is None else elegida


def catalogo(config_dir: Path | None = None) -> list[Ajuste]:
    """Todo lo tocable, con su valor de ahora. Es la fuente de la UI.

    LAS ETIQUETAS ESTAN ESCRITAS PARA ALGUIEN QUE ACABA DE INSTALAR
    ESTO, no para quien escribio el codigo. "Umbral del wake word" es
    exacto y no significa nada la primera vez; "que tan facil te oye
    cuando le llamas" dice lo mismo y se entiende sin haber leido un
    ADR. El nombre tecnico sigue estando -- en la clave, en el archivo y
    en el "¿por que?" -- para quien lo necesite.
    """

    def v(clave: str, defecto: Any) -> Any:
        return valor_de(clave, defecto, config_dir)

    return [
        # =============== PARA EMPEZAR ================================
        Ajuste(
            clave="sesion.carpeta", etiqueta="Carpeta de trabajo",
            grupo="empezar", tipo="texto", aplica="reiniciar",
            valor=str(v("sesion.carpeta", "") or ""), por_defecto="",
            ayuda="La carpeta sobre la que Jarvis puede trabajar. Todo lo "
                  "que haga pasa por aqui dentro.",
            aviso="Fuera de esta carpeta Jarvis te PREGUNTA antes de tocar "
                  "nada, y hay zonas del sistema donde no puede escribir "
                  "aunque tu se lo pidas. Eso no depende de este ajuste.",
        ),
        Ajuste(
            clave="ui.idioma", etiqueta="Idioma de la pantalla",
            grupo="pantalla", tipo="eleccion", aplica="ya",
            valor=str(v("ui.idioma", "es") or "es"), por_defecto="es",
            opciones=[
                {"valor": "es", "etiqueta": "Español"},
                {"valor": "en", "etiqueta": "English"},
            ],
            ayuda="Cambia lo que LEES. Lo que Jarvis habla, y lo que "
                  "entiende cuando le hablas, se elige aparte mas abajo.",
            # >>> LA ETIQUETA DICE \"DE LA PANTALLA\" A PROPOSITO <<<
            # Un \"Idioma\" a secas prometeria un Jarvis en ingles entero,
            # y quien lo pusiera se encontraria contestandole en español
            # sin entender por que. La voz es JC-0018 y no se traduce: va
            # medida contra grabaciones en español.
            aviso="No cambia la voz. La palabra para despertarle, la "
                  "transcripcion y la voz con la que contesta estan medidas "
                  "contra grabaciones en español, asi que cambiarlas no "
                  "es traducir: es otro ajuste, con su coste.",
        ),
        Ajuste(
            clave="ui.tema", etiqueta="Como se ve",
            grupo="pantalla", tipo="eleccion", aplica="ya",
            valor=str(v("ui.tema", "jarvis") or "jarvis"),
            por_defecto="jarvis",
            opciones=[
                {"valor": "jarvis",
                 "etiqueta": "Jarvis — cian sobre negro, el de siempre"},
                {"valor": "hacker",
                 "etiqueta": "Terminal — verde sobre negro"},
                {"valor": "despacho",
                 "etiqueta": "Despacho — claro, para trabajar con "
                             "documentos"},
                {"valor": "nexo",
                 "etiqueta": "Nexo — claro y minimalista"},
            ],
            ayuda="Solo cambia los colores y la tipografia. La pantalla "
                  "enseña exactamente lo mismo en los cuatro: lo que "
                  "Jarvis hace, y la pregunta cuando te pide permiso.",
            aviso="Se aplica al momento, sin reiniciar. Lo que NO cambia con "
                  "el tema es QUE se enseña: la peticion de permiso "
                  "dice lo mismo en los cuatro, porque es donde autorizas y "
                  "una version “más simple” de eso sería "
                  "autorizar sin saber qué.",
        ),
        Ajuste(
            clave="voz.encendida", etiqueta="Hablarle en vez de escribirle",
            grupo="empezar", tipo="interruptor", aplica="reiniciar",
            valor=bool(v("voz.encendida", False)), por_defecto=False,
            ayuda="Le dices \u201chey jarvis\u201d y le hablas. Si lo dejas "
                  "apagado, Jarvis funciona igual escribiendo aqui.",
            aviso="Se dice con la J INGLESA, como en \u201cyema\u201d: "
                  "\u201cjei YAR-vis\u201d. Medido con la voz del usuario: a "
                  "la española acierta 1 de 20 veces, a la inglesa 5 de 6. "
                  "Encenderlo suma ~9 s al arranque, que es lo que tardan "
                  "los modelos en cargar.",
        ),
        # =============== OIR Y HABLAR =================================
        Ajuste(
            clave="voz.idioma", etiqueta="Idioma en el que habla y te oye",
            grupo="oir", tipo="eleccion", aplica="reiniciar",
            valor=str(v("voz.idioma", "es") or "es"), por_defecto="es",
            opciones=[
                {"valor": "es", "etiqueta": "Español"},
                {"valor": "en", "etiqueta": "English"},
            ],
            ayuda="El idioma con el que le hablas y con el que te "
                  "contesta. Es distinto del idioma de la pantalla.",
            # >>> ESTE AJUSTE CUESTA, Y HAY QUE DECIRLO ANTES <<<
            # No es el gemelo de `ui.idioma`. Cambiarlo mueve cuatro
            # cosas que estan MEDIDAS contra grabaciones en español, y
            # ninguna de ellas da error al fallar: se nota oyendolo.
            # >>> ESTE AVISO DECIA UNA COSA QUE NO PASA (2026-09-03) <<<
            # Decia "Cambia tambien el perfil de voz al del idioma". No
            # lo cambia: no hay una linea en `guardar` ni en
            # `_aplicar_en_caliente` que toque `voz.perfil`. Lo que hay
            # es `voz/perfil.py` NEGANDOSE a arrancar la voz cuando los
            # dos no cuadran, que es la decision correcta -- ese archivo
            # se niega a elegir perfil por su cuenta a proposito -- pero
            # es lo contrario de lo que el usuario acababa de leer.
            # >>> Y EL 2026-09-10 SE INVIRTIO: AHORA SI LO CAMBIA <<<
            # Aquella correccion arreglo la PROSA -- paso a decir "cambia
            # los dos" -- y dejo el trabajo de hacerlo en manos del
            # usuario. Se lo comio tres veces seguidas y en las DOS
            # direcciones, cada una a cambio de un reinicio para
            # enterarse. Decision suya: *"son dos ajustes que deben ir
            # juntos"*. Lo hace `_emparejar_la_voz` al guardar, o sea
            # antes de reiniciar. La negativa de `voz/perfil.py` se
            # queda: es la red de quien edita el YAML a mano.
            # >>> DECIA "TODAVIA", Y ESA PALABRA MENTIA (2026-09-09) <<<
            # Daba a entender que el banco ingles venia de camino. No
            # viene: el usuario decidio ese dia que no lo graba, y con
            # viene: el usuario decidio ese dia que no lo graba, y con
            # razon -- no quiere grabarlas en ingles porque no lo usa
            # asi, y prefiere que lo hagan quienes hablen ingles. Un
            # pendiente que nadie va a hacer no es un
            # pendiente, es un estado, y en el sitio donde alguien ELIGE
            # el ingles tiene que leerse como lo que es. Ademas convierte
            # el hueco en una invitacion, que es lo unico que puede
            # cerrarlo: las herramientas ya estan construidas.
            aviso="No es lo mismo que el idioma de la pantalla. En "
                  "español, la transcripcion y las palabras para "
                  "PARARLE estan medidas contra 30 grabaciones reales; en "
                  "ingles NO lo estan, y no es un pendiente: quien "
                  "escribio esto no le habla en ingles, asi que ese banco "
                  "solo lo puede grabar alguien que lo use asi. Funciona "
                  "igual; lo que falta es la cifra, y si hablas ingles el "
                  "proyecto trae con que medirla (mira el README). "
                  "AL GUARDAR SE CAMBIA TAMBIEN “voz con la que "
                  "habla”, porque los dos van juntos: una voz "
                  "española leyendo ingles no daria error, solo sonaria "
                  "mal, asi que Jarvis se niega a arrancar con ese par. "
                  "Si prefieres otra voz de ese idioma, eligela aqui "
                  "abajo despues.",
        ),
        Ajuste(
            clave="voz.audio.entrada", etiqueta="Microfono",
            grupo="oir", tipo="eleccion", aplica="reiniciar",
            valor=(dispositivo_actual("entrada", config_dir)
                   or uno_solo(v("voz.audio.entrada", ""))),
            por_defecto=PREDETERMINADO,
            opciones=_opciones_de_audio("entrada"),
            ayuda="Por donde te escucha. Dale a Probar y di algo.",
            prueba="entrada",
            aviso="PRUEBALO SIEMPRE que lo cambies. Esta maquina tiene 16 "
                  "entradas que no son microfonos: son cables internos de "
                  "otros programas. Si eliges uno, Jarvis no da ningun "
                  "error -- simplemente no vuelve a oirte nunca.",
        ),
        Ajuste(
            clave="voz.audio.salida", etiqueta="Altavoz",
            grupo="oir", tipo="eleccion", aplica="reiniciar",
            valor=(dispositivo_actual("salida", config_dir)
                   or uno_solo(v("voz.audio.salida", PREDETERMINADO),
                               PREDETERMINADO)),
            por_defecto=PREDETERMINADO,
            opciones=_opciones_de_audio("salida"),
            ayuda="Por donde te contesta. Dejandolo en el de Windows, "
                  "enchufar unos cascos basta para que le siga.",
            prueba="salida",
        ),
        Ajuste(
            clave="voz.perfil", etiqueta="Voz con la que habla",
            grupo="oir", tipo="eleccion", aplica="reiniciar",
            valor=v("voz.perfil", "jarvis"), por_defecto="jarvis",
            opciones=_opciones_de_perfil(config_dir),
            ayuda="Su nombre y su voz.",
            aviso="Si eliges una voz de otro idioma, al guardar se "
                  "cambia con ella \u201cidioma en el que habla y te oye\u201d: "
                  "van juntos. "
                  "Le sigues llamando \u201chey jarvis\u201d aunque cambies "
                  "el nombre: la palabra con la que despierta es un modelo "
                  "entrenado aparte y no hay otra hecha (ADR-0002).",
        ),
        # =============== AVANZADO =====================================
        # >>> ESTE NO ES UN INTERRUPTOR DE COMODIDAD (JC-0017) <<<
        # Encenderlo no acelera a Jarvis: le quita los frenos. Por eso la
        # etiqueta dice lo que hace y NO "modo rapido", el `aviso` nombra
        # POR NOMBRE lo que deja de mirarse, y vive en Avanzado y no en
        # "Para empezar" -- quien acaba de instalar esto no tiene por que
        # tropezarse con la unica casilla que apaga la puerta.
        # Nace APAGADO aunque los proyectos registrados nazcan encendidos,
        # y no es una contradiccion: alli lo enciende estar en una lista
        # que el usuario escribio a mano, aqui lo encenderia una casilla
        # que aplica a TODO, incluida la carpeta base.
        Ajuste(
            clave="sesion.auto_por_defecto",
            etiqueta="No preguntarme nada, en todas las carpetas",
            grupo="avanzado", tipo="interruptor", aplica="reiniciar",
            valor=bool(v("sesion.auto_por_defecto", False)), por_defecto=False,
            ayuda="Jarvis abre TODAS sus sesiones en el auto mode de Claude "
                  "Code, tambien en carpetas que no sean un proyecto "
                  "registrado. Sin esto, solo lo llevan los proyectos de tu "
                  "lista.",
            aviso="Con esto puesto dejan de preguntarte TRES cosas, y por "
                  "nombre: borrar archivos, `git push`, y las herramientas "
                  "de servidores MCP que no hayas autorizado. No es que "
                  "Jarvis apruebe rapido: es que no se entera de que se lo "
                  "pidieron. Lo que NO cambia, y esta medido contra los "
                  "cinco modos: las zonas selladas del sistema siguen "
                  "bloqueadas, y la consola te sigue ensenando cada "
                  "herramienta que usa. Te deja sin freno, no a oscuras.",
        ),
        Ajuste(
            clave="mcp.estricto",
            etiqueta="Solo los servidores MCP que Jarvis declara",
            grupo="avanzado", tipo="interruptor", aplica="reiniciar",
            valor=bool(v("mcp.estricto", False)), por_defecto=False,
            ayuda="Jarvis arranca unicamente los servidores de su propia "
                  "lista, y no los que tengas puestos en tu Claude Code de "
                  "la terminal. Sin esto arranca los dos.",
            aviso="Lo que NO cambia es lo que se deniega: un servidor que no "
                  "este en tu lista blanca no pasa, con esto y sin esto. Lo "
                  "que cambia es si llega a ARRANCARSE -- cada servidor es "
                  "un proceso, y Jarvis puede estar corriendo todo el dia "
                  "desde el inicio de Windows. El precio de ponerlo: Jarvis "
                  "deja de VER los servidores que anadas por fuera, asi que "
                  "el panel ya no puede ofrecertelos con un boton y hay que "
                  "declararlos aqui a mano.",
        ),
        Ajuste(
            clave="voz.seguimiento", etiqueta="Seguir la conversacion",
            grupo="avanzado", tipo="interruptor", aplica="reiniciar",
            valor=bool(v("voz.seguimiento", True)), por_defecto=True,
            ayuda="Despues de contestarte sigue escuchando un momento, para "
                  "que no tengas que volver a llamarle. Te callas y se calla.",
            aviso="Mientras esa ventana esta abierta transcribe lo que suene "
                  "en la sala, hable quien hable.",
        ),
        Ajuste(
            clave="voz.narrar", etiqueta="Contarte lo que va haciendo",
            grupo="avanzado", tipo="interruptor", aplica="reiniciar",
            valor=bool(v("voz.narrar", True)), por_defecto=True,
            ayuda="Mientras trabaja te va diciendo en alto lo que hace "
                  "(\"ahora reviso el codigo...\"), como si te acompanara. "
                  "El detalle sigue entero en la consola.",
            aviso="Solo se locuta la prosa: las rutas, los comandos y los "
                  "identificadores se quedan fuera, porque leidos en alto no "
                  "se entienden. Se mide con -m eval.mirar_narracion.",
        ),
        Ajuste(
            clave="voz.resumir", etiqueta="Resumir lo que dice",
            grupo="avanzado", tipo="interruptor", aplica="reiniciar",
            valor=bool(v("voz.resumir", False)), por_defecto=False,
            ayuda="Apagado te lee la respuesta entera. Encendido te dice lo "
                  "esencial y deja el detalle escrito en la consola.",
            aviso="Una respuesta larga de verdad son ~145 segundos hablando.",
        ),
        Ajuste(
            clave="voz.wake_word.umbral",
            etiqueta="Que tan facil te oye al llamarle",
            grupo="avanzado", tipo="numero", aplica="reiniciar",
            valor=float(v("voz.wake_word.umbral", 0.5)), por_defecto=0.5,
            minimo=0.2, maximo=0.9,
            ayuda="Mas bajo, te oye con menos esfuerzo pero se despierta "
                  "solo mas a menudo.",
            aviso="0,5 no es un numero puesto a ojo: esta medido con la voz "
                  "del usuario a la distancia a la que habla de verdad, y el "
                  "intento bueno mas flojo quedo en 0,494. Con 0,6 se habria "
                  "perdido.",
        ),
        # >>> ESTOS DOS DECIAN `reabrir` Y ERA MENTIRA (2026-09-03) <<<
        # `sesion.modelo` y `sesion.esfuerzo` los lee `valor_de` UNA sola
        # vez, en el arranque del proceso (`puente/__main__.py`), y van a
        # parar a `Sesion.modelo` / `Sesion.esfuerzo`, que es lo que
        # `abrir()` mete en la linea de ordenes. `cambiar_a()` cierra y
        # repunta el directorio SIN releer ninguno de los dos, y no hay
        # ningun otro sitio que construya una `Sesion` (solo los dos de
        # `__main__.py`). O sea que reabrir la sesion -- cambiando de
        # proyecto hablando, por ejemplo -- la reabre con el modelo
        # ANTERIOR, sin un solo error, mientras el panel decia "no se
        # nota hasta reabrir la sesion". Se paga con `reiniciar`, que es
        # lo que de verdad los recoge y para lo que hay boton.
        Ajuste(
            clave="sesion.esfuerzo", etiqueta="Cuanto se lo piensa antes",
            grupo="avanzado", tipo="eleccion", aplica="reiniciar",
            valor=v("sesion.esfuerzo", ""), por_defecto="",
            opciones=[{"valor": "", "etiqueta": "El de siempre (recomendado)"},
                      {"valor": "high", "etiqueta": "Mas"},
                      {"valor": "max", "etiqueta": "Todo lo que pueda"}],
            ayuda="Cuanto razona antes de contestarte. Lo normal ya va bien "
                  "para casi todo; subirlo es para problemas dificiles.",
            aviso="ESTO SE PAGA EN SEGUNDOS, y esta medido: con \"todo lo "
                  "que pueda\", la misma pregunta paso de 5,4 a 23,7 "
                  "segundos. Hablando, eso son veinticuatro segundos "
                  "callado, y un asistente callado tanto rato no se "
                  "distingue de uno colgado. El dinero sube poco (un 45 %). "
                  "Y no hace falta tocarlo para un caso suelto: pedirle "
                  "\"piensatelo bien\" en la propia orden llega al cerebro "
                  "igual.",
        ),
        Ajuste(
            clave="sesion.modelo", etiqueta="Modelo de Claude Code",
            grupo="avanzado", tipo="eleccion", aplica="reiniciar",
            valor=v("sesion.modelo", "sonnet"), por_defecto="sonnet",
            opciones=[{"valor": "sonnet", "etiqueta": "Sonnet (recomendado)"},
                      {"valor": "opus", "etiqueta": "Opus"},
                      {"valor": "haiku", "etiqueta": "Haiku"}],
            ayuda="El cerebro que piensa y actua.",
        ),
        Ajuste(
            clave="voz.stt.modelo", etiqueta="Modelo que transcribe tu voz",
            grupo="avanzado", tipo="eleccion", aplica="reiniciar",
            valor=v("voz.stt.modelo", "small"), por_defecto="small",
            opciones=_opciones_de_stt(),
            ayuda="Solo aparecen los que ya estan descargados.",
            aviso="Los mas pequeños destrozan las palabras para PARARLE "
                  "(\u201ccancela\u201d sale \u201ccancerlo\u201d), que es "
                  "lo que menos se puede fallar cuando algo esta actuando "
                  "sobre tu PC.",
        ),
        Ajuste(
            clave="voz.stt.ancla_vocabulario",
            etiqueta="Palabras que oye a menudo",
            grupo="avanzado", tipo="lista", aplica="reiniciar",
            valor=v("voz.stt.ancla_vocabulario", []), por_defecto=[],
            ayuda="Nombres de carpetas y programas que sueles nombrar, "
                  "separados por comas. Le ayudan a no confundirlos.",
            aviso="Medido: con esta lista se equivoca la mitad (4,2 % -> "
                  "2,4 %) y deja de oir \u201cblog de notas\u201d. VACIARLO "
                  "NO ES NEUTRO: Jarvis ajusta solo, y a la vez, lo seguro "
                  "que tiene que estar de que alguien hablo. Por eso ese "
                  "segundo numero no se toca desde aqui.",
        ),
        Ajuste(
            clave="tiempos.telegram_minutos",
            etiqueta="Avisarme por Telegram si tardo",
            grupo="avanzado", tipo="numero", aplica="ya",
            valor=float(v("tiempos.telegram_minutos", 5.0)), por_defecto=5.0,
            minimo=1.0, maximo=120.0, unidad="min",
            ayuda="Cuanto espera a que contestes antes de escribirte, y solo "
                  "si no estas delante del ordenador.",
        ),
        Ajuste(
            clave="tiempos.ausente_minutos", etiqueta="Darme por ausente tras",
            grupo="avanzado", tipo="numero", aplica="ya",
            valor=float(v("tiempos.ausente_minutos", 5.0)), por_defecto=5.0,
            minimo=1.0, maximo=60.0, unidad="min",
            ayuda="Sin tocar el teclado ni el raton.",
            aviso="Medido: Windows llego a decir 265 segundos de inactividad "
                  "con el usuario sentado delante, leyendo. Por debajo de "
                  "~5 min te dara por ausente estando ahi.",
        ),
        Ajuste(
            clave="proyectos.raiz", etiqueta="Donde tienes tus proyectos",
            grupo="avanzado", tipo="texto", aplica="ya",
            valor=str(v("proyectos.raiz", "") or ""), por_defecto="",
            ayuda="La carpeta que los contiene. Solo sirve para OFRECERTELOS "
                  "abajo de un clic; Jarvis no abre ninguno que no hayas "
                  "añadido tu.",
        ),
        Ajuste(
            clave="proyectos.ritual",
            etiqueta="Que le pregunta Jarvis al abrir un proyecto",
            grupo="avanzado", tipo="parrafo", aplica="ya",
            valor=_ritual_del_panel(config_dir),
            por_defecto=ritual_de_fabrica(config_dir),
            ayuda="Cuando le dices o le escribes “continua con el "
                  "proyecto X”, Jarvis abre la carpeta y le manda esto "
                  "solo, para tener con que empezar. Dejalo VACIO y abrira "
                  "la carpeta sin decir nada.",
            aviso="ESTO SE MANDA SIN QUE TU ESTES DELANTE, y con la autoridad "
                  "entera de la sesion: si ese proyecto tiene el auto mode "
                  "puesto, lo que escribas aqui no pasa por ninguna puerta. "
                  "Una frase que diga “borra los temporales” se "
                  "ejecuta. Ademas pisa el idioma: se manda tal cual la "
                  "escribas, tambien con la voz en ingles. Y cada proyecto "
                  "de la lista de aqui abajo puede tener la suya, o "
                  "ninguna.",
        ),
        Ajuste(
            clave="tiempos.seguimiento_s",
            etiqueta="Cuanto espera a que sigas hablando",
            grupo="avanzado", tipo="numero", aplica="reiniciar",
            valor=float(v("tiempos.seguimiento_s", 6.0)), por_defecto=6.0,
            minimo=2.0, maximo=20.0, unidad="s",
            ayuda="Solo cuenta si \u201cseguir la conversacion\u201d esta "
                  "encendido.",
        ),
    ]


def por_grupos(config_dir: Path | None = None) -> list[dict[str, Any]]:
    """El catalogo listo para pintar, agrupado, en orden y en su idioma.

    >>> LA TRADUCCION SE APLICA AQUI Y NO EN `catalogo()` <<<
    `catalogo()` es la fuente de la verdad -- valores, limites, `aplica`
    -- y la usan los tests y `guardar()`. Traducir ahi dejaria a un test
    comprobando textos que cambian con un ajuste del usuario. Aqui es
    donde se PINTA, que es el unico sitio donde el idioma significa algo.
    """
    from nucleo.textos import de_ajuste, traducir_catalogo

    todos = traducir_catalogo(catalogo(config_dir), config_dir)
    salida = []
    for clave, titulo, nota in GRUPOS:
        dentro = [a.a_json() for a in todos if a.grupo == clave]
        if dentro:
            salida.append({
                "clave": clave,
                "titulo": de_ajuste(f"grupo.{clave}.titulo", titulo, config_dir),
                "nota": de_ajuste(f"grupo.{clave}.ayuda", nota, config_dir),
                "ajustes": dentro,
            })
    return salida
