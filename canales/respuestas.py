"""JC-0016: contestar PREGUNTAS desde Telegram. Nunca permisos.

>>> QUE CAMBIA, Y POR QUE NO ES UN AJUSTE MAS <<<
Hasta hoy Telegram era un canal de SALIDA (JC-0006: avisa, no autoriza).
Aceptar respuestas lo convierte en un canal de ENTRADA a un agente que
actua sobre esta PC con la autoridad entera del usuario. ADR-0029 ya lo
decia sin rodeos:

    "quien escriba en ese chat conduce a Claude Code sobre la PC"

El fork lo habia cerrado del todo. El usuario pidio reabrirlo
**acotado**, y esta es la acotacion, decidida con el delante:

    SI  contestar un `AskUserQuestion` -- una pregunta de diseño, una
        eleccion entre opciones que Claude Code plantea.
    SI  contestar la pregunta EN PROSA que cierra un turno, pero SOLO
        eligiendo una de las alternativas que el propio Claude escribio.
        Ver abajo, porque es la que necesita la acotacion.
    NO  contestar una PUERTA. Un borrado, un `git push`, salir del
        directorio: eso se autoriza delante del ordenador y punto.
    NO  mandar ordenes nuevas. El canal de ordenes es la voz, y eso
        tambien lo escribio ADR-0029: *"un mensaje de Telegram solo
        puede ser respuesta a una pregunta pendiente concreta"*.

LO QUE SE PIERDE SI TE ROBAN EL TOKEN queda asi acotado a que alguien
conteste una pregunta de diseño en tu nombre. No a que te borre nada. Esa
frase es toda la justificacion de este modulo, y si algun dia alguien
quiere ampliar lo que se acepta, es la frase que deja de ser verdad.

>>> LA PREGUNTA EN PROSA ES OTRA COSA, Y HAY QUE DECIRLO (2026-08-29) <<<
El usuario la vio faltando al probar el escalado: las preguntas con
opciones llegaban al movil y se contestaban bien, y las abiertas ni
aparecian. Son el 42 % de los turnos (`-m eval.mirar_preguntas`).

    `AskUserQuestion`     el turno SIGUE VIVO esperando en el canal de
                          control. Se contesta con `Sesion.responder`, y
                          la respuesta rellena un hueco acotado.
    pregunta en prosa     el turno YA CERRO. Contestarla es
                          `Sesion.contestar_abierta`, que por dentro es
                          `mandar`: UN TURNO NUEVO.

O sea que la segunda toca justo lo que la lista de arriba prohibe. Lo
unico que la mantiene dentro es que **el texto que viaja no lo escribe
quien manda el mensaje**: `voz.resumen.opciones_de_pregunta` recorta las
alternativas del propio texto de Claude, y solo se acepta elegir una.
Sin etiquetas que recortar no se ofrece contestar: se avisa y se
contesta en la consola.

Si algun dia alguien quiere aceptar aqui texto libre, eso NO es aflojar
un detalle: es borrar la frase de arriba. Se reabre JC-0016.

>>> SE CONTESTA CON UN NUMERO <<<
Y no por comodidad: emparejar texto libre contra etiquetas obligaria a
decidir cual se parece mas, por un canal donde no hay forma de repreguntar
en el momento. Un numero no se parece a nada. Las etiquetas se aceptan
tambien, pero exactas.
"""

from __future__ import annotations

import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# Cada cuanto se le pregunta a Telegram. Se llama desde el mismo latido
# que atiende el escalado (medio segundo), asi que hace falta un freno:
# una peticion de red cada 500 ms seria maltratar la API por nada. Una
# respuesta a una pregunta no es urgente.
CADA_S = 3.0


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto.strip().lower())
    return "".join(c for c in sin_tildes if not unicodedata.combining(c))


@dataclass
class Buzon:
    """Recoge lo que llega por Telegram y lo enruta. O lo tira.

    NO TIENE HILO PROPIO, igual que el escalado: se le pregunta desde
    quien ocupa el hilo principal. Un hilo mas seria un sitio mas donde
    algo puede quedarse colgado sin que nadie lo mire.
    """

    entrada: Any
    sesion: Any
    canal: Any = None
    """Para acusar recibo. Sin el, una respuesta que no se entiende se
    traga en silencio y el usuario se queda mirando el movil."""

    contestadas: int = 0
    descartadas_sin_pregunta: int = 0
    descartadas_por_ser_puerta: int = 0
    """>>> ESTE ES EL CONTADOR QUE HAY QUE VIGILAR <<<
    Son intentos de autorizar algo desde el movil. Que crezca no es un
    fallo -- se han rechazado --, pero dice que alguien lo esta
    intentando, y si no eras tu, es la señal de que el token corre."""
    no_entendidas: int = 0
    abiertas_contestadas: int = 0
    """De las `contestadas`, cuantas eran una pregunta en PROSA.
    Va aparte porque no se contestan por el mismo sitio: una
    `AskUserQuestion` rellena un hueco que la sesion tenia abierto
    (`responder`), y una pregunta en prosa abre UN TURNO NUEVO
    (`contestar_abierta`). Si esta creciendo, esta creciendo la
    superficie que JC-0016 acoto."""
    ultimo: str = ""
    _visto_en: float = field(default=0.0, repr=False)

    # --- lo que se puede contestar ---------------------------------------

    @staticmethod
    def opciones_de(pregunta) -> list[str]:
        """Las etiquetas de la primera pregunta, en orden."""
        primera = pregunta.preguntas[0] if pregunta.preguntas else {}
        return [str(o.get("label", "")).strip()
                for o in (primera.get("options") or [])
                if str(o.get("label", "")).strip()]

    @staticmethod
    def enunciado_de(pregunta) -> str:
        enunciados = pregunta.enunciados
        return enunciados[0] if enunciados else ""

    def _pendiente_contestable(self):
        """La pregunta que espera, si la hay. Nunca una puerta.

        Devuelve tambien SI habia una puerta, porque no es lo mismo "no
        hay nada esperando" que "hay algo esperando y no se contesta por
        aqui": la segunda merece una respuesta distinta.
        """
        pregunta = None
        habia_puerta = False
        for p in getattr(self.sesion, "pendientes", ()) or ():
            if getattr(p, "es_pregunta", False):
                if pregunta is None:
                    pregunta = p
            else:
                habia_puerta = True
        return pregunta, habia_puerta

    def _elegir(self, texto: str, opciones: list[str]) -> str | None:
        """Del texto del mensaje a una etiqueta. None si no se sabe."""
        limpio = texto.strip()
        if limpio.isdigit():
            indice = int(limpio) - 1
            if 0 <= indice < len(opciones):
                return opciones[indice]
            return None
        plano = _plano(limpio)
        for etiqueta in opciones:
            if _plano(etiqueta) == plano:
                return etiqueta
        return None

    # --- el latido --------------------------------------------------------

    def revisar(self, ahora: float | None = None) -> int:
        """Mira si hay mensajes y los enruta. Devuelve cuantos contesto.

        NO LEVANTA. Lo llama el mismo latido que el escalado, y un fallo
        de red no puede llevarse por delante lo que si funciona.
        """
        momento = time.time() if ahora is None else ahora
        if momento - self._visto_en < CADA_S:
            return 0
        self._visto_en = momento
        if not getattr(self.entrada, "disponible", False):
            return 0

        try:
            mensajes = self.entrada.recibir()
        except Exception as exc:  # noqa: BLE001
            self.ultimo = f"{type(exc).__name__}: {exc}"
            return 0

        hechas = 0
        for mensaje in mensajes:
            if self._atender(mensaje):
                hechas += 1
        return hechas

    def _decir(self, texto: str) -> None:
        if self.canal is not None:
            try:
                self.canal.mandar(texto)
            except Exception:  # noqa: BLE001
                pass

    def _atender(self, mensaje) -> bool:
        pregunta, habia_puerta = self._pendiente_contestable()

        if pregunta is None and not habia_puerta:
            # >>> LA PREGUNTA QUE CERRO EL TURNO (2026-08-29) <<<
            # Va DESPUES de la puerta a proposito: si hay un permiso
            # esperando, lo que toca es rechazar, no buscar otra cosa
            # que contestar. Y solo se intenta si trae etiquetas: sin
            # ellas no hay numero que mandar, y aceptar texto libre
            # seria convertir esto en un canal de ordenes.
            hecho = self._atender_abierta(mensaje)
            if hecho is not None:
                return hecho

        if pregunta is None:
            # >>> AQUI SE CIERRA LA PUERTA DE VERDAD <<<
            # Un mensaje sin pregunta pendiente NO se convierte en una
            # orden. Es lo que separa "contestar" de "conducir".
            if habia_puerta:
                self.descartadas_por_ser_puerta += 1
                self.ultimo = "llego una respuesta y lo que espera es un permiso"
                self._decir(
                    "Lo que estoy esperando es un PERMISO, y eso no se "
                    "autoriza desde aqui. Diselo en voz alta o en la consola.")
            else:
                self.descartadas_sin_pregunta += 1
                self.ultimo = "llego un mensaje sin pregunta pendiente"
                self._decir(
                    "No tengo ninguna pregunta esperando. Por aqui solo "
                    "puedo recoger respuestas; las ordenes van por voz.")
            return False

        evento = pregunta.evento
        opciones = self.opciones_de(evento)
        elegida = self._elegir(mensaje.texto, opciones)
        if elegida is None:
            self.no_entendidas += 1
            self.ultimo = f"no se entendio: {mensaje.texto[:40]}"
            self._decir("No te he entendido. Contesta con el numero:\n"
                        + self.opciones_numeradas(evento))
            return False

        respuestas = {self.enunciado_de(evento): elegida}
        try:
            fue = self.sesion.responder(evento.id_peticion, permitir=True,
                                        respuestas=respuestas)
        except Exception as exc:  # noqa: BLE001
            self.ultimo = f"no se pudo contestar: {exc}"
            return False
        if not fue:
            # Otro canal llego antes. No es un fallo: es la carrera normal
            # entre la voz, la consola y esto.
            self.ultimo = "alguien contesto antes"
            self._decir("Ya estaba contestada.")
            return False

        self.contestadas += 1
        self.ultimo = f"contestado: {elegida}"
        self._decir(f"Hecho: {elegida}")
        return True

    # --- lo que se manda al preguntar ------------------------------------

    def opciones_numeradas(self, pregunta) -> str:
        opciones = self.opciones_de(pregunta)
        if not opciones:
            return "(sin opciones)"
        return "\n".join(f"{i}. {o}" for i, o in enumerate(opciones, start=1))

    def _atender_abierta(self, mensaje) -> bool | None:
        """Contesta la pregunta en prosa que cerro el turno.

        >>> TRES SALIDAS, Y LA DEL MEDIO ES LA QUE HACIA FALTA <<<
            None   no hay ninguna pregunta abierta que se pueda contestar
                   por aqui. Que siga el flujo de siempre.
            True   contestada.
            False  la habia y el mensaje no era ninguna de sus opciones.
                   YA se le ha dicho al usuario, asi que no sigue: con
                   dos salidas, el flujo de fuera le mandaria ademas un
                   "no tengo ninguna pregunta esperando" que le
                   contradice en el mismo segundo.

        >>> Y AQUI ES DONDE SE ACOTA, QUE ES TODO EL ASUNTO <<<
        Contestar esto es `mandar`, o sea UN TURNO NUEVO, que es
        exactamente lo que la cabecera de este modulo prohibe. Lo que lo
        mantiene dentro de la acotacion es que **el texto que viaja no lo
        escribe quien manda el mensaje**: es una de las etiquetas, y esas
        son recortes literales de lo que Claude acaba de escribir. Quien
        tenga el token elige entre N frases del propio modelo; no puede
        colar una palabra suya.
        Y si la frase elegida acaba disparando algo irreversible, se para
        igual en la PUERTA, que sigue sin poder contestarse desde aqui.
        """
        abierta = getattr(self.sesion, "pregunta_abierta", None)
        if abierta is None or not getattr(abierta, "contestable", False):
            return None

        opciones = list(abierta.etiquetas)
        elegida = self._elegir(mensaje.texto, opciones)
        if elegida is None:
            self.no_entendidas += 1
            self.ultimo = f"no se entendio (abierta): {mensaje.texto[:40]}"
            lista = "\n".join(f"{i}. {o}"
                              for i, o in enumerate(opciones, start=1))
            self._decir("No te he entendido. Contesta con el numero:\n"
                        + lista)
            return False

        try:
            fue = self.sesion.contestar_abierta(abierta.id, elegida)
        except Exception as exc:  # noqa: BLE001
            self.ultimo = f"no se pudo contestar la abierta: {exc}"
            return False
        if not fue:
            # La perdio contra otro canal, o el turno ya siguio por su
            # cuenta. No es un fallo: es la carrera normal entre la voz,
            # la consola y esto -- y con `mandar` no existia hasta hoy.
            self.ultimo = "la pregunta abierta ya no estaba"
            self._decir("Esa pregunta ya no esta esperando.")
            return False

        self.contestadas += 1
        self.abiertas_contestadas += 1
        self.ultimo = f"contestado (abierta): {elegida}"
        self._decir(f"Hecho: {elegida}")
        return True
