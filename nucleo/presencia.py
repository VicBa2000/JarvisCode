"""Si el usuario esta delante de la maquina (JC-0009).

Sirve para UNA cosa y conviene no ampliarla: decidir **por donde** se
avisa. No decide si se avisa.

>>> LA TRAMPA, MEDIDA Y NO IMAGINADA <<<
Mientras se escribia el ADR, con el usuario SENTADO DELANTE y en plena
conversacion, `GetLastInputInfo` devolvio **265 segundos** de
inactividad. Estaba leyendo.

    "No hay entrada" NO significa "no esta".
    "Hay entrada" NO significa que este mirando ESTO.

Los dos errores duelen, y en direcciones opuestas:

  * **Falso ausente** (el caso medido): el usuario esta leyendo la
    consola, se le da por ausente y se le empieza a hablar en voz alta y
    a mandar Telegrams. Molesto, pero VISIBLE, y se corrige solo en
    cuanto toca una tecla.
  * **Falso presente**: esta jugando, en una llamada o con otra ventana
    a pantalla completa. Hay entrada constante, asi que se callarian voz
    y Telegram, y una peticion de aprobacion se quedaria esperando en
    una ventana que nadie mira. JC-0003 midio que la sesion espera
    INDEFINIDAMENTE: no hay timeout que la rescate. Este es el malo,
    porque es silencioso y puede durar horas.

La regla que hace inofensivos a los dos vive en quien llama, no aqui:
**la presencia silencia el ESCALADO, nunca la PREGUNTA.** Estar delante
cambia por donde se avisa; nunca hace que no se avise por ningun sitio.

>>> TRES ESTADOS, Y "NO LO SE" NO ES "PRESENTE" <<<

    PRESENTE     entrada reciente Y escritorio accesible
    AUSENTE      sin entrada durante la ventana Y escritorio accesible
    NO_SE_SABE   `OpenInputDesktop` devuelve 0 (sesion bloqueada, RDP,
                 escritorio seguro) o `GetLastInputInfo` falla

"No lo se" se trata como AUSENTE por quien decide, y se REGISTRA como lo
que es. Las dos mitades importan: la direccion segura es avisar de mas
-- un aviso sobrante se ignora, uno que no se manda no se recupera --,
pero si el 90 % de las sesiones cayeran en "no se sabe", el mecanismo no
estaria funcionando y hay que poder enterarse mirando, no por sorpresa.

>>> HISTERESIS, NO UN UMBRAL SECO <<<
Con un umbral, un golpe de raton al pasar haria parpadear los canales.

    a PRESENTE   con UNA entrada. Inmediato, que es lo que uno espera
                 al sentarse.
    a AUSENTE    solo tras N segundos CONTINUADOS sin entrada.

Y N no se elige a ojo: el dato de arriba dice que 60 s marcarian ausente
a alguien que esta leyendo.

TODO LOCAL Y SIN TELEMETRIA: dos llamadas de Windows por `ctypes`,
sin dependencias nuevas y sin que salga nada de la maquina.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

# Cuanto se aguanta sin entrada antes de dar a alguien por ausente.
# CINCO MINUTOS ES UN PUNTO DE PARTIDA, NO UNA MEDIDA, y el numero que
# lo justifica es el de arriba: 265 s leyendo. Un minuto habria dado por
# ausente al usuario mientras leia la consola.
AUSENTE_TRAS_S = 300.0

# Constante de Windows: DESKTOP_SWITCHDESKTOP. Es el permiso mas barato
# que sirve para preguntar "hay un escritorio de entrada accesible".
_DESKTOP_SWITCHDESKTOP = 0x0100


class Estado(Enum):
    """Donde esta el usuario, hasta donde se puede saber."""

    PRESENTE = "presente"
    AUSENTE = "ausente"
    NO_SE_SABE = "no_se_sabe"

    @property
    def hay_que_escalar(self) -> bool:
        """Si se puede perseguir al usuario por otros canales.

        NO_SE_SABE cuenta como ausente, que es la direccion segura. Se
        pregunta asi -- y no `estado is AUSENTE` -- para que ese colapso
        ocurra en UN sitio y este escrito, en vez de repetido en cada
        llamante con la posibilidad de que uno lo haga al reves.
        """
        return self is not Estado.PRESENTE


@dataclass(frozen=True)
class Lectura:
    """Una consulta, con lo que la sostiene.

    `inactivo_s` viaja con el estado a proposito: "ausente" es
    una bandera y no deja distinguir a alguien que acaba de irse de
    alguien que lleva tres horas fuera, que es justo lo que hace falta
    para decidir si se insiste.
    """

    estado: Estado
    inactivo_s: float | None
    escritorio_accesible: bool | None
    momento: float

    @property
    def presente(self) -> bool:
        return self.estado is Estado.PRESENTE

    def describe(self) -> str:
        if self.inactivo_s is None:
            return f"{self.estado.value} (no se pudo leer la inactividad)"
        return (f"{self.estado.value} · {self.inactivo_s:.0f} s sin entrada"
                f"{'' if self.escritorio_accesible else ' · escritorio no accesible'}")


def _inactividad_s() -> float | None:
    """Segundos desde la ultima tecla o raton. None si no se pudo saber.

    None es la tercera salida y NO es un cero: un fallo de la llamada no
    puede parecerse a "acaba de teclear".
    """
    try:
        import ctypes
        from ctypes import wintypes

        class _UltimaEntrada(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = _UltimaEntrada()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        ahora = ctypes.windll.kernel32.GetTickCount()
        # `GetTickCount` da la vuelta a los 49,7 dias. Si eso pasa entre
        # las dos lecturas sale un negativo, y un negativo aqui se leeria
        # como "entrada del futuro" -> presente para siempre.
        transcurrido = (ahora - info.dwTime) / 1000.0
        return transcurrido if transcurrido >= 0 else None
    except Exception:  # noqa: BLE001 - no es Windows, o ctypes fallo
        return None


def _escritorio_accesible() -> bool | None:
    """Si hay un escritorio de entrada al que mirar.

    Devuelve False con la sesion bloqueada, en RDP o en el escritorio
    seguro. None si ni siquiera se pudo preguntar.
    """
    try:
        import ctypes

        user32 = ctypes.windll.user32
        handle = user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
        if not handle:
            return False
        user32.CloseDesktop(handle)
        return True
    except Exception:  # noqa: BLE001
        return None


@dataclass
class Presencia:
    """El estado, con su histeresis. Se consulta cuantas veces haga falta.

    Guarda estado entre llamadas porque la histeresis lo necesita: hasta
    que no se lleva la ventana entera sin entrada, no se pasa a ausente.
    """

    ausente_tras_s: float = AUSENTE_TRAS_S
    estado: Estado = Estado.PRESENTE
    """Se nace PRESENTE a proposito: quien acaba de arrancar Jarvis
    estaba delante para arrancarlo."""

    ultima: Lectura | None = None
    _veces: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # Cuantas veces se ha visto cada estado. Es lo que deja saber si
        # el mecanismo funciona: un 90 % de "no se sabe" es un mecanismo
        # roto, y sin contarlo no se ve.
        self._veces = {estado: 0 for estado in Estado}

    @property
    def veces(self) -> dict:
        return dict(self._veces)

    def mirar(self, ahora: float | None = None) -> Lectura:
        """Consulta el sistema y aplica la histeresis."""
        momento = time.time() if ahora is None else ahora
        accesible = _escritorio_accesible()
        inactivo = _inactividad_s()

        if accesible is not True or inactivo is None:
            # Sesion bloqueada, RDP, o la llamada fallo. No se sabe, y no
            # se disfraza de otra cosa.
            estado = Estado.NO_SE_SABE
        elif inactivo < self.ausente_tras_s:
            # A presente con UNA entrada: inmediato, sin esperar.
            estado = Estado.PRESENTE
        else:
            estado = Estado.AUSENTE

        self.estado = estado
        self._veces[estado] += 1
        self.ultima = Lectura(estado=estado, inactivo_s=inactivo,
                              escritorio_accesible=accesible, momento=momento)
        return self.ultima
