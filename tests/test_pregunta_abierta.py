"""La pregunta EN PROSA que cierra un turno: se apunta, se avisa y se
contesta acotada (2026-08-29).

>>> DE DONDE SALE ESTO <<<
El usuario probando el escalado de Telegram: las preguntas con opciones
(`AskUserQuestion`) llegaban al movil y se contestaban bien, y las
abiertas -- las que Claude escribe en prosa al cerrar el turno -- no
llegaban. No era un filtro: una pregunta en prosa no deja nada en
`Sesion.pendientes`, que es lo unico que miraba el escalado, asi que
Telegram no la descartaba, es que no la veia.

Son el 42 % de los turnos reales (`python -m eval.mirar_preguntas`, 42
sesiones en `logs/puente/`), o sea el camino principal y no el raro.

>>> Y LA MITAD DELICADA ES CONTESTARLA <<<
Una `AskUserQuestion` se contesta con `Sesion.responder`: el turno sigue
vivo esperando en el canal de control y la respuesta rellena un hueco
acotado. Una pregunta en prosa CERRO el turno, asi que contestarla es
`Sesion.mandar` -- UN TURNO NUEVO --, que es exactamente lo que JC-0016
prohibio. Lo unico que la mantiene dentro de la acotacion es que el
texto que viaja no lo escriba quien manda el mensaje.
"""

from __future__ import annotations

import time

import pytest

from canales.escalado import Escalado
from canales.respuestas import Buzon
from canales.telegram import Ajustes, Entrante
from nucleo.presencia import Estado, Lectura, Presencia
from puente.protocolo import Fin
from puente.sesion import PreguntaAbierta, Sesion


def fin(texto: str, **extra) -> Fin:
    campos = dict(session_id="s1", subtipo="success", es_error=False,
                  texto=texto, coste_usd=0.01, duracion_ms=100,
                  num_turnos=1)
    campos.update(extra)
    return Fin(**campos)


@pytest.fixture
def sesion(tmp_path):
    """Una sesion SIN proceso: aqui no se lanza `claude`.

    Todo lo que se prueba pasa en el hilo lector, que es puro y no
    necesita el binario.
    """
    return Sesion(tmp_path)


# --- 1. QUE LA SESION SE ENTERE ----------------------------------------


class TestLaSesionSeEntera:
    def test_un_turno_que_cierra_preguntando_deja_la_pregunta(self, sesion):
        sesion._anotar_abierta(fin(
            "He mirado el changelog.\n\n¿Arranco con la verificación de "
            "verde, o prefieres que antes registre la decisión?"))
        abierta = sesion.pregunta_abierta
        assert abierta is not None
        assert abierta.contestable
        assert len(abierta.etiquetas) == 2

    def test_un_turno_que_NO_pregunta_no_deja_nada(self, sesion):
        sesion._anotar_abierta(fin("Listo. Los 126 tests pasan."))
        assert sesion.pregunta_abierta is None

    def test_una_PARADA_no_deja_pregunta(self, sesion):
        """>>> Y SE MIRA ANTES QUE EL ERROR, COMO SIEMPRE <<<
        Una parada llega disfrazada de error (`is_error: true`). Quien
        mire solo esa bandera se pierde el caso; quien no mire ninguna
        avisaria por el movil de una pregunta de un turno que el usuario
        acababa de mandar callar.
        """
        sesion._anotar_abierta(fin("¿Sigo con el paso A o con el B?",
                                   es_error=True,
                                   razon_terminal="aborted_streaming"))
        assert sesion.pregunta_abierta is None

    def test_un_turno_que_FALLO_tampoco(self, sesion):
        sesion._anotar_abierta(fin("API Error: ¿reintento o lo dejo?",
                                   es_error=True,
                                   razon_terminal="api_error"))
        assert sesion.pregunta_abierta is None

    def test_NO_se_mete_en_pendientes(self, sesion):
        """>>> LA SEPARACION QUE PROTEGE A TODO LO DEMAS <<<
        `pendientes` significa "la sesion esta BLOQUEADA esperando, hay
        un id_peticion vivo y se contesta con responder". La consola lo
        pinta asi, el buzon lo recorre asi y `Caida` cuenta las que se
        pierden. Meter aqui algo que no bloquea nada cambiaria esos tres
        sitios a la vez sin que saltara un test.
        """
        sesion._anotar_abierta(fin("¿Sigo con A, o prefieres B?"))
        assert sesion.pendientes == ()
        assert sesion.pregunta_abierta is not None


class TestUnTurnoNuevoLaBorra:
    def test_mandar_olvida_la_pregunta_anterior(self, sesion, monkeypatch):
        sesion._anotar_abierta(fin("¿Sigo con A, o prefieres B?"))
        monkeypatch.setattr(sesion, "_escribir", lambda *a, **k: None)

        sesion.mandar("otra cosa distinta")

        assert sesion.pregunta_abierta is None, (
            "se sigue pudiendo contestar una pregunta de hace dos turnos")


class TestPrimeraRespuestaGana:
    """>>> ESTO NO EXISTIA PARA `mandar`, Y HACIA FALTA <<<

    `responder` ya lo tenia: dos canales compitiendo por la misma puerta
    es normal y el que pierde tiene que enterarse. Con `mandar` no habia
    nada, asi que contestar por voz y por el movil a la vez habria
    mandado DOS turnos -- y el segundo contestando a una pregunta que el
    modelo ya no tenia delante.
    """

    def test_el_segundo_canal_pierde(self, sesion, monkeypatch):
        mandados = []
        monkeypatch.setattr(sesion, "_escribir",
                            lambda carga: mandados.append(carga))
        sesion._anotar_abierta(fin("¿Sigo con A, o prefieres B?"))
        abierta = sesion.pregunta_abierta

        assert sesion.contestar_abierta(abierta.id, "Sigo con A") is True
        assert sesion.contestar_abierta(abierta.id, "prefieres B") is False
        assert len(mandados) == 1

    def test_contestar_por_VOZ_tambien_la_reclama(self, sesion, monkeypatch):
        """La voz y la consola no llaman a `contestar_abierta`: llaman a
        `mandar`. Y eso ya la reclama, que es lo que cierra la carrera
        sin que ninguno de los dos tenga que saber que existe."""
        monkeypatch.setattr(sesion, "_escribir", lambda *a, **k: None)
        sesion._anotar_abierta(fin("¿Sigo con A, o prefieres B?"))
        abierta = sesion.pregunta_abierta

        sesion.mandar("hazlo por A")  # <- la voz

        assert sesion.contestar_abierta(abierta.id, "prefieres B") is False

    def test_un_id_viejo_no_contesta_la_pregunta_NUEVA(self, sesion,
                                                       monkeypatch):
        """Entre que Telegram lee un mensaje y lo enruta puede haber
        cerrado un turno y abierto otra pregunta. El numero que mando el
        usuario ya no significa lo que el creia."""
        monkeypatch.setattr(sesion, "_escribir", lambda *a, **k: None)
        sesion._anotar_abierta(fin("¿Sigo con A, o prefieres B?"))
        vieja = sesion.pregunta_abierta
        sesion.mandar("otra cosa")
        sesion._anotar_abierta(fin("¿Borro el log, o lo dejo?"))

        assert sesion.contestar_abierta(vieja.id, "Borro el log") is False


# --- 2. QUE SE AVISE POR EL MOVIL --------------------------------------


class CanalPostizo:
    def __init__(self, disponible=True, funciona=True, responde=False):
        self.disponible = disponible
        self.funciona = funciona
        self.mandados: list[str] = []
        self.ajustes = Ajustes(activo=True, token="x", chat_id="1",
                               responde=responde)

    def mandar(self, texto: str) -> bool:
        self.mandados.append(texto)
        return self.funciona


class PresenciaFija(Presencia):
    def __init__(self, estado: Estado) -> None:
        super().__init__()
        self._fijo = estado

    def mirar(self, ahora=None) -> Lectura:
        return Lectura(estado=self._fijo, inactivo_s=999.0,
                       escritorio_accesible=True, momento=ahora or 0.0)


def abierta(etiquetas=("Sigo con A", "prefieres B"), hace_minutos=60.0,
            enunciado="¿Sigo con A, o prefieres B?"):
    return PreguntaAbierta(
        id="abierta-1", pregunta=enunciado, enunciado=enunciado,
        etiquetas=tuple(etiquetas), forma="disyuntiva",
        abierta_en=time.time() - hace_minutos * 60.0)


def escalado(canal, estado=Estado.AUSENTE) -> Escalado:
    return Escalado(canal=canal, presencia=PresenciaFija(estado))


class TestCuandoSeAvisa:
    def test_ausente_y_pasado_el_rato_SE_MANDA(self):
        """El fallo que reporto el usuario, en una linea."""
        canal = CanalPostizo()
        assert escalado(canal).revisar((), abierta=abierta()) == 1
        assert len(canal.mandados) == 1

    def test_ESTANDO_DELANTE_no_se_manda(self):
        """JC-0009 no cambia porque cambie lo que se avisa: si estas
        delante ya la tienes en la consola y ya te la dijo en voz alta."""
        canal = CanalPostizo()
        esc = escalado(canal, Estado.PRESENTE)
        assert esc.revisar((), abierta=abierta()) == 0
        assert esc.callados_por_presencia == 1

    def test_recien_preguntada_todavia_no(self):
        canal = CanalPostizo()
        assert escalado(canal).revisar(
            (), abierta=abierta(hace_minutos=0.5)) == 0

    def test_se_avisa_UNA_vez(self):
        canal = CanalPostizo()
        esc = escalado(canal)
        una = abierta()
        assert esc.revisar((), abierta=una) == 1
        assert esc.revisar((), abierta=una) == 0
        assert len(canal.mandados) == 1

    def test_si_el_envio_falla_NO_se_da_por_avisada(self):
        canal = CanalPostizo(funciona=False)
        esc = escalado(canal)
        assert esc.revisar((), abierta=abierta()) == 0
        assert esc.avisadas == set()

    def test_sin_nada_pendiente_NI_abierta_se_olvida_lo_avisado(self):
        """El conjunto no puede crecer durante toda la vida del proceso.
        Pero limpiarlo mientras la pregunta sigue abierta la volveria a
        avisar cada vuelta, y un canal que insiste se silencia."""
        canal = CanalPostizo()
        esc = escalado(canal)
        una = abierta()
        esc.revisar((), abierta=una)
        assert esc.avisadas
        esc.revisar((), abierta=una)
        assert esc.avisadas, "se olvido mientras la pregunta seguia abierta"
        esc.revisar(())
        assert esc.avisadas == set()

    def test_se_cuenta_aparte_de_las_puertas(self):
        canal = CanalPostizo()
        esc = escalado(canal)
        esc.revisar((), abierta=abierta())
        assert esc.abiertas_avisadas == 1
        assert esc.enviados == 1


class TestQueDiceElMensaje:
    def test_con_el_interruptor_APAGADO_no_invita_a_contestar(self):
        """`responde` apagado significa que el buzon ni siquiera lee. Un
        mensaje que dijera "contesta con el numero" mandaria al usuario a
        hablar con una pared."""
        canal = CanalPostizo(responde=False)
        escalado(canal).revisar((), abierta=abierta())
        dicho = canal.mandados[0]
        assert "consola" in dicho
        assert "numero" not in dicho.lower()

    def test_con_el_interruptor_ENCENDIDO_van_numeradas(self):
        canal = CanalPostizo(responde=True)
        escalado(canal).revisar((), abierta=abierta())
        dicho = canal.mandados[0]
        assert "1. Sigo con A" in dicho
        assert "2. prefieres B" in dicho

    def test_sin_opciones_NO_se_ofrece_numero_aunque_este_encendido(self):
        """>>> LA DIRECCION SEGURA, Y ES LA MITAD DE LA DECISION <<<
        Una pregunta abierta de verdad ("¿en que te gustaria trabajar
        hoy?") no tiene opciones que recortar. Se avisa igual -- eso era
        lo que faltaba -- pero se contesta en la consola.
        """
        canal = CanalPostizo(responde=True)
        escalado(canal).revisar(
            (), abierta=abierta(etiquetas=(),
                                enunciado="¿En qué te gustaría trabajar?"))
        dicho = canal.mandados[0]
        assert "¿En qué te gustaría trabajar?" in dicho
        assert "consola" in dicho
        assert "1." not in dicho

    def test_dice_que_por_ahi_NO_se_mandan_ordenes(self):
        canal = CanalPostizo(responde=True)
        escalado(canal).revisar((), abierta=abierta())
        assert "ordenes nuevas" in canal.mandados[0]

    def test_dice_cuanto_lleva_esperando(self):
        canal = CanalPostizo()
        escalado(canal).revisar((), abierta=abierta(hace_minutos=12.0))
        assert "12 min" in canal.mandados[0]


# --- 3. QUE SE CONTESTE, Y SOLO LO ACOTADO -----------------------------


class EntradaPostiza:
    def __init__(self, *textos, disponible=True) -> None:
        self._textos = list(textos)
        self.disponible = disponible

    def recibir(self):
        salida = tuple(Entrante(id_update=i, chat_id="1", texto=t)
                       for i, t in enumerate(self._textos))
        self._textos = []
        return salida


class SesionPostiza:
    """Una sesion que solo sabe de la pregunta abierta."""

    def __init__(self, pregunta_abierta=None, contesta=True) -> None:
        self.pendientes = ()
        self.pregunta_abierta = pregunta_abierta
        self.contesta = contesta
        self.mandados: list[tuple[str, str]] = []

    def contestar_abierta(self, id_abierta, texto):
        self.mandados.append((id_abierta, texto))
        return self.contesta


class CanalDeAcuse:
    def __init__(self) -> None:
        self.dicho: list[str] = []

    def mandar(self, texto):
        self.dicho.append(texto)
        return True


def buzon(sesion, *textos):
    return Buzon(entrada=EntradaPostiza(*textos), sesion=sesion,
                 canal=CanalDeAcuse())


class TestLoQueSePuedeContestar:
    def test_un_numero_manda_la_ETIQUETA_de_claude(self):
        """>>> EL TEST QUE SOSTIENE LA ACOTACION <<<
        Lo que viaja no es lo que escribio quien manda el mensaje: es la
        etiqueta, que es un recorte literal de lo que escribio Claude.
        """
        sesion = SesionPostiza(abierta())
        b = buzon(sesion, "2")
        b.revisar(ahora=1000.0)

        assert sesion.mandados == [("abierta-1", "prefieres B")]
        assert b.abiertas_contestadas == 1

    def test_TEXTO_LIBRE_no_se_manda_JAMAS(self):
        """>>> Y ESTE ES EL QUE NO SE PUEDE AFLOJAR <<<
        Si esto cae, Telegram deja de contestar preguntas y pasa a
        CONDUCIR Claude Code sobre la PC, que es lo que JC-0016 cerro.
        """
        sesion = SesionPostiza(abierta())
        b = buzon(sesion, "mejor borra la carpeta entera")
        b.revisar(ahora=1000.0)

        assert sesion.mandados == [], "viajo texto libre al cerebro"
        assert b.no_entendidas == 1
        assert "numero" in " ".join(b.canal.dicho).lower()

    def test_un_numero_FUERA_de_rango_tampoco(self):
        sesion = SesionPostiza(abierta())
        b = buzon(sesion, "7")
        b.revisar(ahora=1000.0)
        assert sesion.mandados == []

    def test_SIN_opciones_no_se_puede_contestar_nada(self):
        """Una pregunta abierta de verdad se avisa pero no se contesta
        por aqui: sin etiquetas no hay numero, y aceptar texto libre
        seria justo lo prohibido."""
        sesion = SesionPostiza(abierta(etiquetas=()))
        b = buzon(sesion, "que sigamos con el refactor")
        b.revisar(ahora=1000.0)

        assert sesion.mandados == []
        assert b.descartadas_sin_pregunta == 1

    def test_una_PUERTA_pendiente_gana_y_se_rechaza(self):
        """Si hay un permiso esperando, lo que toca es rechazar -- no
        buscar otra cosa que contestar. La puerta no se autoriza desde el
        movil ni aunque ademas haya una pregunta abierta."""
        class ConPuerta(SesionPostiza):
            pass

        sesion = ConPuerta(abierta())
        sesion.pendientes = (type("P", (), {"es_pregunta": False,
                                            "evento": None})(),)
        b = buzon(sesion, "1")
        b.revisar(ahora=1000.0)

        assert sesion.mandados == []
        assert b.descartadas_por_ser_puerta == 1

    def test_si_ya_la_contestaron_se_dice_y_no_se_manda_otro_turno(self):
        sesion = SesionPostiza(abierta(), contesta=False)
        b = buzon(sesion, "1")
        b.revisar(ahora=1000.0)

        assert b.abiertas_contestadas == 0
        assert "ya no esta esperando" in " ".join(b.canal.dicho)

    def test_no_se_contradice_a_si_mismo(self):
        """Con dos salidas en vez de tres, un numero mal puesto recibia
        "no te he entendido" Y a continuacion "no tengo ninguna pregunta
        esperando", que se desmienten en el mismo segundo."""
        sesion = SesionPostiza(abierta())
        b = buzon(sesion, "9")
        b.revisar(ahora=1000.0)

        assert len(b.canal.dicho) == 1
        assert b.descartadas_sin_pregunta == 0
