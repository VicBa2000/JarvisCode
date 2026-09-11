"""Cuando se escala un aviso a otro canal (JC-0006 + JC-0009).

    consola   si estas delante
    voz       si no
    Telegram  si tampoco contestas por voz en N minutos

Este modulo es solo el ultimo escalon: decide **si ya toca** avisar por
Telegram de algo que lleva un rato esperando a una persona.

>>> Y SON DOS COSAS, NO UNA (2026-08-29) <<<
Una PUERTA deja la sesion bloqueada y vive en `Sesion.pendientes`. Una
pregunta en PROSA cierra el turno y no deja nada ahi -- son el 42 % de
los turnos reales (`-m eval.mirar_preguntas`) y hasta esta fecha no
llegaban a Telegram por ningun sitio. No es que se filtraran: es que
`pendientes` llegaba vacio y aqui no habia nada que mandar. Lo destapo
el usuario probando el escalado. Entra por `abierta=`, aparte, porque no
se avisa igual ni se contesta igual.

>>> LA REGLA QUE HACE ESTO SEGURO, Y ES DE JC-0009 <<<

    la presencia silencia el ESCALADO, nunca la PREGUNTA

Estar delante cambia POR DONDE se avisa, no SI se avisa. La puerta ya se
ha pedido por voz y se esta pintando en la consola antes de que este
modulo mire nada; lo unico que decide aqui es si ademas se manda un
mensaje al movil.

Por eso el falso presente -- el error malo de JC-0009, el usuario jugando
a pantalla completa con entrada constante -- solo cuesta un Telegram que
no se manda, y NO una puerta que se queda sin avisar por ningun sitio.

>>> DOS CONDICIONES, Y LAS DOS TIENEN QUE CUMPLIRSE <<<

    1. la puerta lleva esperando mas de `tras_minutos`
    2. la presencia dice que se puede escalar (ausente o no se sabe)

La segunda usa `Estado.hay_que_escalar`, que trata "no lo se" como
ausente: la direccion segura es avisar de mas, porque un aviso sobrante
se ignora y uno que no se manda no se recupera.

>>> UNA PUERTA SE AVISA UNA VEZ <<<
No se insiste cada vuelta. Un canal que repite el mismo aviso cada
minuto se silencia en el movil, y entonces deja de ser un canal. Se
recuerda por `id_peticion`, que es lo unico estable que tiene una puerta.

>>> Y EL MENSAJE DICE LO MISMO QUE LA VOZ Y QUE LA CONSOLA <<<
Se construye con `voz/permiso.py::pedir`, o sea desde la misma
`Decision`. La regla de JC-0002 no cambia porque cambie el canal: si las
formas divergen, se aprueba una cosa y se ejecuta otra. Lo unico que se
le anade es de donde viene y que hay que ir a contestarlo, porque **por
Telegram no se puede autorizar** (un mensaje entrante es
contenido observado, jamas una instruccion).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from nucleo.presencia import Presencia

# Cuanto se espera antes de perseguir al usuario por el movil. CINCO
# MINUTOS ES UN PUNTO DE PARTIDA: lo bastante para que una respuesta por
# voz o un paso por la consola lleguen antes, y lo bastante poco para que
# la sesion no se pase media hora parada esperando a nadie.
TRAS_MINUTOS = 5.0


@dataclass
class Escalado:
    """Vigila las puertas pendientes y avisa cuando toca.

    No tiene hilo propio: alguien lo llama cada tanto (`revisar`). Asi es
    trivial de probar -- se le pasa el reloj -- y no anade otro hilo a un
    proceso que ya tiene tres.
    """

    canal: Any
    """Cualquiera que sepa `mandar(texto) -> bool` y tenga
    `disponible`. Hoy `canales/telegram.py`; manana lo que sea."""

    presencia: Presencia = field(default_factory=Presencia)
    tras_minutos: float = TRAS_MINUTOS
    directorio: str | None = None

    avisadas: set = field(default_factory=set)
    """Puertas ya avisadas, por `id_peticion`. Una puerta se avisa UNA
    vez: un canal que insiste cada minuto se silencia en el movil."""

    enviados: int = 0
    abiertas_avisadas: int = 0
    """De los `enviados`, cuantos eran una pregunta en PROSA y no una
    puerta. Va aparte porque son cosas distintas: una puerta tiene la
    sesion bloqueada esperando, una pregunta abierta no. Si este numero
    es el grueso del total, lo que hay que afinar es el minutaje de las
    preguntas, no el de los permisos."""
    callados_por_presencia: int = 0
    """Veces que tocaba escalar y no se hizo porque el usuario estaba
    delante. Va aparte porque si este numero es enorme, es que
    se esta preguntando cuando el usuario SI esta, y entonces lo que hay
    que mirar es otra cosa."""

    def revisar(self, pendientes: tuple, ahora: float | None = None,
                abierta=None) -> int:
        """Mira lo que espera a una persona y manda lo que toque.

        Devuelve cuantos avisos se mandaron. Cero es lo normal.

        >>> `abierta` NO ES UNA PUERTA MAS, Y POR ESO VIENE APARTE <<<
        Es la pregunta en prosa que cerro el turno
        (`Sesion.pregunta_abierta`). Son el 42 % de los turnos y hasta el
        2026-08-29 no llegaban aqui por ningun sitio: `pendientes` solo
        lleva lo que dejo un `control_request`, y una pregunta en prosa
        no deja ninguno. No es que se filtrara, es que no existia.
        """
        if not pendientes and abierta is None:
            # Sin nada esperando, se olvida lo avisado: el conjunto no
            # crece durante toda la vida del proceso.
            self.avisadas.clear()
            return 0
        if not getattr(self.canal, "disponible", False):
            return 0

        momento = time.time() if ahora is None else ahora
        limite = self.tras_minutos * 60.0
        mandados = 0
        for pendiente in pendientes:
            evento = getattr(pendiente, "evento", None)
            id_peticion = getattr(evento, "id_peticion", None)
            if not id_peticion or id_peticion in self.avisadas:
                continue
            if momento - getattr(pendiente, "pedido_en", momento) < limite:
                continue

            # La presencia se mira AQUI y no antes: solo cuando ya toca.
            # Preguntarla en cada vuelta gastaria dos llamadas al sistema
            # por segundo para nada.
            if not self.presencia.mirar(momento).estado.hay_que_escalar:
                self.callados_por_presencia += 1
                continue

            if self.canal.mandar(self.mensaje(pendiente)):
                self.avisadas.add(id_peticion)
                self.enviados += 1
                mandados += 1

        if abierta is not None:
            mandados += self._revisar_abierta(abierta, momento)
        return mandados

    def mensaje(self, pendiente) -> str:
        """Lo mismo que dice la voz, mas donde contestarlo.

        Se construye desde la misma `Decision` que la voz y la consola
        (JC-0002). Lo que cambia entre canales es el envoltorio, nunca
        QUE se esta pidiendo.
        """
        from voz.permiso import pedir

        evento = pendiente.evento

        # >>> UNA PREGUNTA NO ES UNA PUERTA, Y NO SE ESCRIBE IGUAL <<<
        # Hasta JC-0016 todo salia de aqui como "necesito permiso para
        # usar X", incluida una eleccion de diseño -- que no pide permiso
        # para nada. Y ahora ademas importa que se distingan: una si se
        # puede contestar desde el movil y la otra NO, asi que el mensaje
        # que las mezclara estaria invitando a contestar lo que se va a
        # rechazar.
        if getattr(pendiente, "es_pregunta", False):
            return self._mensaje_de_pregunta(evento, pendiente)

        decision = getattr(pendiente, "decision", None)
        if decision is None:
            cuerpo = f"Necesito permiso para usar {getattr(evento, 'herramienta', 'algo')}."
        else:
            # `pedir` termina en "¿Lo autorizo? Contesta si o no", que por
            # aqui no vale: por Telegram NO se puede contestar. Se cambia
            # la ultima frase, no el resto.
            frase = pedir(evento, decision, directorio=self.directorio).frase
            cuerpo = frase.split("¿Lo autorizo?")[0].strip()

        pedido_en = getattr(pendiente, "pedido_en", None)
        if pedido_en:
            minutos = (time.time() - pedido_en) / 60.0
            cuerpo = f"{cuerpo}\nLleva {minutos:.0f} min esperando."

        return (
            "Jarvis te esta esperando.\n\n"
            f"{cuerpo}\n\n"
            "Contesta en la consola o diciendoselo en voz alta: "
            "por aqui no puedo autorizar nada."
        )

    def _mensaje_de_pregunta(self, evento, pendiente) -> str:
        """Una eleccion, con sus opciones numeradas si se puede contestar.

        EL CIERRE CAMBIA SEGUN EL INTERRUPTOR, y tiene que cambiar: decir
        "contesta con el numero" cuando `responde` esta apagado seria
        pedirle al usuario que hable con una pared.
        """
        from canales.respuestas import Buzon

        enunciados = getattr(evento, "enunciados", ()) or ()
        cuerpo = enunciados[0] if enunciados else "Me falta que decidas algo."

        pedido_en = getattr(pendiente, "pedido_en", None)
        if pedido_en:
            minutos = (time.time() - pedido_en) / 60.0
            cuerpo = f"{cuerpo}\nLleva {minutos:.0f} min esperando."

        contestable = bool(getattr(getattr(self.canal, "ajustes", None),
                                   "responde", False))
        if not contestable:
            return ("Jarvis te esta esperando.\n\n"
                    f"{cuerpo}\n\n"
                    "Contesta en la consola o diciendoselo en voz alta.")

        opciones = Buzon.opciones_de(evento)
        if not opciones:
            # Sin opciones no hay numero que mandar, y aceptar texto libre
            # aqui seria justo lo que JC-0016 no acepta.
            return ("Jarvis te esta esperando.\n\n"
                    f"{cuerpo}\n\n"
                    "Esta no lleva opciones: contestala en la consola.")

        lista = "\n".join(f"{i}. {o}" for i, o in enumerate(opciones, start=1))
        return ("Jarvis te esta esperando.\n\n"
                f"{cuerpo}\n\n"
                f"{lista}\n\n"
                "Contesta con el numero. (Los permisos no: esos se "
                "autorizan delante del ordenador.)")

    def _mensaje_de_abierta(self, abierta) -> str:
        """Una pregunta en prosa, con sus opciones si se pueden numerar.

        >>> TRES CIERRES, Y CADA UNO DICE LA VERDAD DE SU CASO <<<
        Decirle "contesta con el numero" a quien tiene el interruptor
        apagado es mandarle hablar con una pared; ofrecerle numeros a una
        pregunta que no los tiene es peor, porque se los inventaria.
        """
        cuerpo = abierta.enunciado or abierta.pregunta
        minutos = abierta.segundos_esperando / 60.0
        if minutos >= 1:
            cuerpo = f"{cuerpo}\nLleva {minutos:.0f} min esperando."

        contestable = bool(getattr(getattr(self.canal, "ajustes", None),
                                   "responde", False))
        if not contestable or not abierta.contestable:
            return ("Jarvis te ha preguntado algo.\n\n"
                    f"{cuerpo}\n\n"
                    "Contestala en la consola o diciendoselo en voz alta.")

        lista = "\n".join(f"{i}. {e}"
                          for i, e in enumerate(abierta.etiquetas, start=1))
        return ("Jarvis te ha preguntado algo.\n\n"
                f"{cuerpo}\n\n"
                f"{lista}\n\n"
                "Contesta con el numero. (Solo estas opciones: por aqui "
                "no se mandan ordenes nuevas ni se autoriza nada.)")

    def _revisar_abierta(self, abierta, momento: float) -> int:
        """El mismo escalon, para la pregunta que cerro el turno.

        Mismas dos condiciones que una puerta -- lleva esperando y el
        usuario no esta delante --, porque el motivo es el mismo: si
        estas delante ya la tienes en la consola y ya te la dijo en voz
        alta. Lo que cambia es que aqui la sesion NO esta bloqueada, o
        sea que no hay nada que se quede colgado; lo que se pierde si no
        se avisa es que te quedes esperando una respuesta que nunca
        pediste bien.
        """
        if abierta.id in self.avisadas:
            return 0
        if momento - abierta.abierta_en < self.tras_minutos * 60.0:
            return 0
        if not self.presencia.mirar(momento).estado.hay_que_escalar:
            self.callados_por_presencia += 1
            return 0
        if not self.canal.mandar(self._mensaje_de_abierta(abierta)):
            return 0
        self.avisadas.add(abierta.id)
        self.enviados += 1
        self.abiertas_avisadas += 1
        return 1
