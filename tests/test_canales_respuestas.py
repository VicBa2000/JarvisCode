"""JC-0016: contestar PREGUNTAS desde Telegram. Nunca permisos.

>>> LO QUE ESTE ARCHIVO PROTEGE ES UNA FRASE <<<
Telegram pasa de ser un canal de SALIDA a uno de ENTRADA a un agente que
actua sobre esta PC. Lo unico que hace aceptable ese cambio es esto:

    lo peor que puede pasar si te roban el token es que alguien conteste
    una pregunta de diseño en tu nombre; NO que te borre algo.

Cada test de aqui es una de las formas en que esa frase dejaria de ser
verdad. Si alguno se afloja, hay que reabrir JC-0016 -- no arreglar el
test.
"""

from __future__ import annotations

import pytest

from canales.respuestas import Buzon
from canales.telegram import Ajustes, Entrante, TelegramEntrada
from puente.protocolo import Pregunta, Puerta


def pregunta(opciones=("Sonnet", "Opus"), enunciado="¿Que modelo?"):
    return Pregunta(
        id_peticion="q1", id_uso="u1",
        preguntas=({"question": enunciado,
                    "options": [{"label": o} for o in opciones]},),
    )


def puerta():
    return Puerta(id_peticion="p1", id_uso="u1", herramienta="Bash",
                  entrada={"command": "rm -rf datos"}, descripcion="borrar")


class PendientePostizo:
    def __init__(self, evento, es_pregunta: bool) -> None:
        self.evento = evento
        self.es_pregunta = es_pregunta
        self.pedido_en = 0.0
        self.decision = None


class SesionPostiza:
    def __init__(self, *pendientes) -> None:
        self.pendientes = tuple(pendientes)
        self.respondidas = []
        self.contesta = True

    def responder(self, id_peticion, permitir=False, motivo="",
                  respuestas=None):
        self.respondidas.append((id_peticion, permitir, respuestas or {}))
        return self.contesta


class EntradaPostiza:
    def __init__(self, *textos, disponible=True) -> None:
        self._textos = list(textos)
        self.disponible = disponible
        self.veces = 0

    def recibir(self):
        self.veces += 1
        salida = tuple(Entrante(id_update=i, chat_id="1", texto=t)
                       for i, t in enumerate(self._textos))
        self._textos = []
        return salida


class CanalPostizo:
    def __init__(self) -> None:
        self.dicho = []

    def mandar(self, texto):
        self.dicho.append(texto)
        return True


def buzon(sesion, *textos, disponible=True):
    return Buzon(entrada=EntradaPostiza(*textos, disponible=disponible),
                 sesion=sesion, canal=CanalPostizo())


# --- 1. LO QUE NUNCA SE PUEDE HACER DESDE EL MOVIL ----------------------


def test_una_PUERTA_no_se_autoriza_desde_telegram() -> None:
    """>>> EL TEST QUE SOSTIENE TODA LA DECISION <<<

    Si esto cae, un mensaje desde el movil autoriza un `rm -rf`. Es
    exactamente lo que JC-0006 cerro y lo que JC-0016 NO reabre.
    """
    sesion = SesionPostiza(PendientePostizo(puerta(), es_pregunta=False))
    b = buzon(sesion, "si")
    b.revisar(ahora=1000.0)

    assert sesion.respondidas == [], "se autorizo una puerta desde el movil"
    assert b.descartadas_por_ser_puerta == 1
    assert "PERMISO" in " ".join(b.canal.dicho)


def test_un_mensaje_suelto_NO_es_una_orden_nueva() -> None:
    """Del propio ADR-0029: *"un mensaje de Telegram solo puede ser
    respuesta a una pregunta pendiente concreta, nunca una orden nueva.
    El canal de ordenes es la voz"*. Sin esto, "borra los logs" escrito
    en el chat seria una orden."""
    sesion = SesionPostiza()
    b = buzon(sesion, "borra todos los logs")
    b.revisar(ahora=1000.0)

    assert sesion.respondidas == []
    assert b.descartadas_sin_pregunta == 1
    assert "ordenes van por voz" in " ".join(b.canal.dicho)


def test_con_una_puerta_Y_una_pregunta_solo_se_toca_la_pregunta() -> None:
    """El caso mezclado, que es donde un atajo se cuela: hay dos cosas
    esperando y solo una es contestable."""
    p = pregunta()
    sesion = SesionPostiza(
        PendientePostizo(puerta(), es_pregunta=False),
        PendientePostizo(p, es_pregunta=True),
    )
    b = buzon(sesion, "2")
    b.revisar(ahora=1000.0)

    assert [r[0] for r in sesion.respondidas] == ["q1"]
    assert "p1" not in [r[0] for r in sesion.respondidas]


# --- 2. LO QUE SI SE PUEDE, Y COMO ---------------------------------------


def test_se_contesta_con_el_numero() -> None:
    p = pregunta(("Sonnet", "Opus", "Haiku"))
    sesion = SesionPostiza(PendientePostizo(p, es_pregunta=True))
    b = buzon(sesion, "2")
    assert b.revisar(ahora=1000.0) == 1

    id_peticion, permitir, respuestas = sesion.respondidas[0]
    assert (id_peticion, permitir) == ("q1", True)
    assert respuestas == {"¿Que modelo?": "Opus"}


def test_tambien_vale_la_etiqueta_exacta() -> None:
    p = pregunta(("Sonnet", "Opus"))
    sesion = SesionPostiza(PendientePostizo(p, es_pregunta=True))
    b = buzon(sesion, "opus")
    b.revisar(ahora=1000.0)
    assert sesion.respondidas[0][2] == {"¿Que modelo?": "Opus"}


def test_un_numero_fuera_de_rango_no_elige_nada() -> None:
    """Contestar "9" a dos opciones no puede caer en la ultima."""
    p = pregunta(("Sonnet", "Opus"))
    sesion = SesionPostiza(PendientePostizo(p, es_pregunta=True))
    b = buzon(sesion, "9")
    b.revisar(ahora=1000.0)

    assert sesion.respondidas == []
    assert b.no_entendidas == 1
    assert "1. Sonnet" in " ".join(b.canal.dicho)


def test_lo_que_no_se_entiende_se_dice_y_no_se_adivina() -> None:
    """>>> POR QUE NO HAY COINCIDENCIA PARCIAL <<<

    Emparejar texto libre obligaria a decidir cual se parece mas, por un
    canal donde no se puede repreguntar en el momento. Se vuelve a
    mandar la lista y se espera.
    """
    p = pregunta(("Sonnet", "Opus"))
    sesion = SesionPostiza(PendientePostizo(p, es_pregunta=True))
    b = buzon(sesion, "el primero creo")
    b.revisar(ahora=1000.0)

    assert sesion.respondidas == []
    assert "No te he entendido" in " ".join(b.canal.dicho)


def test_si_otro_canal_llego_antes_no_se_finge_que_se_contesto() -> None:
    """La carrera entre la voz, la consola y esto es normal, no un fallo:
    el que pierde se calla en vez de anunciar algo que ya no es verdad."""
    p = pregunta()
    sesion = SesionPostiza(PendientePostizo(p, es_pregunta=True))
    sesion.contesta = False
    b = buzon(sesion, "1")
    assert b.revisar(ahora=1000.0) == 0
    assert b.contestadas == 0
    assert "Ya estaba contestada" in " ".join(b.canal.dicho)


# --- 3. EL INTERRUPTOR ---------------------------------------------------


def test_apagado_NI_TOCA_LA_RED() -> None:
    """`responde` apagado no es "recibe y descarta": es que no pregunta.
    Lo contrario seria mantener abierto un canal que el usuario cree
    cerrado."""
    sesion = SesionPostiza(PendientePostizo(pregunta(), es_pregunta=True))
    b = buzon(sesion, "1", disponible=False)
    assert b.revisar(ahora=1000.0) == 0
    assert b.entrada.veces == 0


def test_nace_apagado_y_hacen_falta_LOS_DOS_interruptores() -> None:
    """`activo` hace de esto un canal de salida; `responde`, uno de
    ENTRADA. Son decisiones distintas con riesgos distintos, asi que son
    dos interruptores y no uno."""
    completo = Ajustes(activo=True, token="T", chat_id="1", responde=True)
    assert TelegramEntrada(completo).disponible is True
    for ajustes in (
        Ajustes(activo=True, token="T", chat_id="1"),            # sin responde
        Ajustes(activo=False, token="T", chat_id="1", responde=True),
        Ajustes(activo=True, token="", chat_id="1", responde=True),
        Ajustes(activo=True, token="T", chat_id="", responde=True),
    ):
        assert TelegramEntrada(ajustes).disponible is False


def test_no_se_pregunta_a_la_red_en_cada_latido() -> None:
    """El latido corre cada medio segundo. Una peticion de red por latido
    seria maltratar la API por nada, y una respuesta no es urgente."""
    sesion = SesionPostiza()
    b = buzon(sesion)
    b.revisar(ahora=1000.0)
    b.revisar(ahora=1000.4)
    b.revisar(ahora=1000.9)
    assert b.entrada.veces == 1


# --- 4. QUIEN PUEDE ESCRIBIR ---------------------------------------------


def test_solo_cuenta_el_chat_configurado() -> None:
    """>>> ALLOWLIST DE `chat_id`, NO SOLO DEL BOT <<<

    Un bot de Telegram le contesta a cualquiera que le escriba. Sin este
    filtro, quien diera con el nombre del bot podria contestar por ti.
    """
    from canales.telegram import _es_de_quien_debe

    assert _es_de_quien_debe({"chat": {"id": 42}}, "42") is True
    assert _es_de_quien_debe({"chat": {"id": 99}}, "42") is False
    assert _es_de_quien_debe({}, "42") is False


def test_lo_de_otro_chat_se_cuenta_ademas_de_tirarse() -> None:
    """Que ese contador crezca es la señal de que alguien mas conoce el
    bot. Tirarlo en silencio seria perder el aviso."""
    entrada = TelegramEntrada(
        Ajustes(activo=True, token="T", chat_id="42", responde=True))
    assert entrada.descartados_por_origen == 0
    assert hasattr(entrada, "descartados_por_origen")


def test_el_offset_avanza_tambien_con_lo_descartado() -> None:
    """Si no, un mensaje ajeno se volveria a leer para siempre y taparia
    los buenos."""
    import canales.telegram as mod

    entrada = TelegramEntrada(
        Ajustes(activo=True, token="T", chat_id="42", responde=True))

    class Falso:
        def __init__(self, *a, **k):
            pass

        def _consultar(self, metodo):
            return True, [
                {"update_id": 7, "message": {"chat": {"id": 99}, "text": "hola"}},
            ]

    original = mod.Telegram
    mod.Telegram = Falso
    try:
        assert entrada.recibir() == ()
    finally:
        mod.Telegram = original
    assert entrada.offset == 8
    assert entrada.descartados_por_origen == 1


# --- 5. LO QUE SE MANDA AL PREGUNTAR -------------------------------------


def test_el_aviso_de_una_pregunta_no_habla_de_permisos() -> None:
    """Hasta JC-0016 todo salia como "necesito permiso para usar X",
    incluida una eleccion de diseño -- que no pide permiso para nada."""
    from canales.escalado import Escalado

    class CanalConAjustes:
        disponible = True
        ajustes = Ajustes(activo=True, token="T", chat_id="1", responde=True)

        def mandar(self, texto):
            return True

    e = Escalado(canal=CanalConAjustes(), directorio="C:/x")
    texto = e.mensaje(PendientePostizo(pregunta(), es_pregunta=True))
    assert "permiso para usar" not in texto
    assert "1. Sonnet" in texto and "2. Opus" in texto
    assert "numero" in texto


def test_con_el_interruptor_apagado_NO_se_invita_a_contestar() -> None:
    """Decir "contesta con el numero" cuando no se puede seria pedirle al
    usuario que hable con una pared."""
    from canales.escalado import Escalado

    class CanalApagado:
        disponible = True
        ajustes = Ajustes(activo=True, token="T", chat_id="1")

        def mandar(self, texto):
            return True

    e = Escalado(canal=CanalApagado(), directorio="C:/x")
    texto = e.mensaje(PendientePostizo(pregunta(), es_pregunta=True))
    assert "Contesta con el numero" not in texto
    assert "consola" in texto


@pytest.mark.parametrize("opciones", [(), ("Solo una",)])
def test_una_pregunta_sin_opciones_no_se_contesta_por_aqui(opciones) -> None:
    """Sin opciones no hay numero que mandar, y aceptar texto libre seria
    justo lo que esta decision no acepta."""
    from canales.escalado import Escalado

    class Canal:
        disponible = True
        ajustes = Ajustes(activo=True, token="T", chat_id="1", responde=True)

        def mandar(self, texto):
            return True

    e = Escalado(canal=Canal(), directorio="C:/x")
    texto = e.mensaje(PendientePostizo(pregunta(opciones), es_pregunta=True))
    if not opciones:
        assert "contestala en la consola" in texto
