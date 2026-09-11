"""Tests de `voz/bucle.py`: la costura entre la voz y el puente.

>>> LOS EVENTOS SON REALES; EL HARDWARE, NO <<<
Los `Fin`, `Puerta` y demas salen de `eval/trazas_claude_code/*.jsonl`,
que son capturas crudas de sesiones de Claude Code de verdad -- incluido
un turno INTERRUMPIDO (`parada.jsonl`), que es el que descubre el
problema del `is_error`. Eso es lo que manda la regla de las sondas.

El microfono, el altavoz y los modelos si son postizos, y no hay otra:
un test no puede hablar. Se sustituye lo que TOCA EL MUNDO y se prueba
todo lo que DECIDE, que es donde estan los errores caros.

LO QUE ESTOS TESTS PROTEGEN:
  * que un turno interrumpido NO se locute como un fallo;
  * que `recibir` no locute nada (bloquearia el bombeo de la consola);
  * que una orden en la que no se confia NO viaje a Claude Code;
  * que "para" llame a `interrumpir` de verdad.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from nucleo.carcasa import Gestos

from puente.protocolo import Fin, Pregunta, Puerta, Reintento, interpretar
from voz.bucle import Bucle
from voz.ciclo import Ciclo, Estado
from voz.senales import Senales
from voz.stt import Transcripcion


# --------------------------------------------------------------------
# Postizos: solo lo que toca el mundo
# --------------------------------------------------------------------

class SesionPostiza:
    """Lo justo de `Sesion` que usa el bucle, apuntando lo que le piden."""

    directorio = r"C:\proyectos\carpetadepruebas"

    def __init__(self) -> None:
        self.mandados: list[str] = []
        self.respondidas: list[tuple] = []
        self.interrupciones = 0
        self.viva = True
        self.pendientes: tuple = ()
        self.contesta = True
        """False = otro canal llego antes. Es la carrera normal entre la
        voz y la consola, no un fallo."""

    def mandar(self, texto: str) -> None:
        self.mandados.append(texto)

    def interrumpir(self) -> bool:
        self.interrupciones += 1
        return True

    def responder(self, id_peticion, permitir=False, motivo="",
                  respuestas=None) -> bool:
        self.respondidas.append((id_peticion, permitir, respuestas or {}))
        return self.contesta


class TTSPostizo:
    def __init__(self) -> None:
        self.dicho: list[str] = []
        self.cancelables: list[bool] = []

    def hablar(self, texto: str, dispositivo=None, cancelar=None) -> None:
        # Se apunta si le dieron con que callarse: sin eso, el "para"
        # tendria que esperar a que acabase la frase.
        self.cancelables.append(cancelar is not None)
        self.dicho.append(texto)


class STTPostizo:
    """Devuelve transcripciones preparadas, una por escucha."""

    def __init__(self, *transcripciones: Transcripcion,
                 paradas: list[Transcripcion] | None = None) -> None:
        self.pendientes = list(transcripciones)
        self.paradas = list(paradas or [])
        self.duracion_ventana_s = 0.2
        """Lo que tarda una vuelta del oido. En produccion son 3,0 s de
        grabacion mas 1,7-1,9 s de Whisper; aqui basta con que NO sea
        cero, que es lo que hace que el atajo tenga algo que atravesar."""
        """>>> EL OIDO TIENE SU PROPIA COLA, Y NO ES UN DETALLE <<<
        Los dos hilos graban del MISMO microfono pero nunca a la vez, o
        sea que lo que oye cada uno es audio distinto. Con una sola cola,
        el oido le robaba a la voz la respuesta que el usuario acababa de
        dar -- un artefacto del doble que se leia como "la puerta no se
        contesto". `pendientes` es lo que se DICTA; `paradas`, lo que
        sondea el oido, y por defecto no es nada."""
        self.escuchas = 0
        self.fijas = 0
        self.turnos = 0
        self.soltadas = 0
        self.esperas: list[float | None] = []

    def escuchar(self, segundos=4.0, dispositivo=None, cancelar=None, **_):
        """La ventana FIJA. Desde JC-0013 solo la usa el oido, que
        sondea paradas y por eso tiene que volver con lo que haya.

        `cancelar` se honra igual que en el de verdad: si esta puesto al
        entrar, la vuelta se suelta sin grabar ni transcribir.
        """
        self.escuchas += 1
        self.fijas += 1
        # >>> LA VENTANA DEL OIDO DURA, Y AQUI TAMBIEN <<<
        # Un doble que vuelve al instante no tiene nunca una vuelta EN
        # VUELO, que es justo lo que el atajo viene a atravesar: con el,
        # el test pasaba sin ejercitar nada. Asi que este espera, y
        # mientras espera mira si le han pedido soltar -- que es lo que
        # hace `grabar_hasta` en produccion, trozo a trozo.
        fin = time.monotonic() + self.duracion_ventana_s
        while time.monotonic() < fin:
            if cancelar is not None and cancelar.is_set():
                self.soltadas += 1
                return soltada()
            time.sleep(0.005)
        if cancelar is not None and cancelar.is_set():
            self.soltadas += 1
            return soltada()
        if self.paradas:
            return self.paradas.pop(0)
        return oido("")

    def escuchar_turno(self, dispositivo=None, espera_inicio_ms=None, **_):
        """La ventana que cierra el usuario callandose (JC-0013)."""
        self.escuchas += 1
        self.turnos += 1
        self.esperas.append(espera_inicio_ms)
        return self._siguiente()

    def _siguiente(self):
        if self.pendientes:
            return self.pendientes.pop(0)
        return oido("")


def soltada() -> Transcripcion:
    """Lo que devuelve una vuelta que se solto: nadie miro si hubo habla."""
    from voz.vad import Cierre

    return Transcripcion(
        texto="", latencia_s=0.0, duracion_audio_s=0.3,
        prob_sin_habla=1.0, idioma="es", modelo="small",
        hay_habla_vad=None, cierre=Cierre.ABORTADO.value,
    )


def oido(texto: str, *, hay_habla_vad: bool | None = True) -> Transcripcion:
    return Transcripcion(
        texto=texto, latencia_s=0.4, duracion_audio_s=3.0,
        prob_sin_habla=0.05, idioma="es", modelo="small",
        hay_habla_vad=hay_habla_vad,
    )


@pytest.fixture
def bucle() -> Bucle:
    """Un bucle montado a mano: sin audio, sin modelos, sin hilos."""
    b = Bucle(
        sesion=SesionPostiza(),
        ciclo=Ciclo(senales=Senales()),   # la de verdad, sin dispositivo
        tts=TTSPostizo(),
        stt=STTPostizo(),
        micro=object(),
        altavoz=None,
    )
    # El respiro no se espera de verdad en los tests.
    b.ciclo.respiro_s = 0.0
    return b


def eventos_de(project_root, nombre: str):
    ruta = project_root / "eval" / "trazas_claude_code" / f"{nombre}.jsonl"
    if not ruta.is_file():
        pytest.skip(f"falta la traza {nombre}.jsonl")
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        yield from interpretar(linea)


def fin_de(project_root, nombre: str, *, indice: int = 0) -> Fin:
    fines = [e for e in eventos_de(project_root, nombre) if isinstance(e, Fin)]
    return fines[indice]


# --------------------------------------------------------------------

class TestElTurnoInterrumpido:
    """El caso que descubrio la traza real, y el que mas duele fallar."""

    def test_un_turno_parado_llega_marcado_como_error(self, project_root):
        """Contra la captura cruda: asi es como se ve una parada por
        dentro. Si esto cambia, el resto del test miente."""
        fin = fin_de(project_root, "parada")
        assert fin.es_error is True
        assert fin.fue_mal is True
        assert fin.parado is True
        assert fin.razon_terminal == "aborted_streaming"

    def test_y_NO_se_locuta_como_un_fallo(self, project_root, bucle):
        """Decirle "algo ha ido mal" a alguien que acaba de mandarte
        callar es la peor manera de obedecer."""
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle._reaccionar(fin_de(project_root, "parada"))
        assert bucle.tts.dicho == []
        assert bucle.ciclo.estado is Estado.DORMIDO

    def test_lo_que_se_locuta_se_puede_cortar(self, project_root, bucle):
        """Todo lo que dice el bucle va con un `cancelar` puesto. Una
        sola frase sin el seria una frase que hay que aguantar entera
        despues de decir "para"."""
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle._reaccionar(fin_de(project_root, "respuesta_larga"))
        assert bucle.tts.cancelables
        assert all(bucle.tts.cancelables)

    def test_estando_callado_no_se_dice_nada(self, bucle):
        """Si le mandaron callar, ni la coletilla: seria hablar despues
        de un "para"."""
        bucle._callar.set()
        bucle.decir("esto no deberia oirse")
        assert bucle.tts.dicho == []

    def test_parar_llama_a_interrumpir_de_verdad(self, bucle):
        """Un "para" que se contesta con un "vale" y no para nada seria
        el guardia decorativo del que este proyecto ya se libro."""
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle._parar_el_turno()
        assert bucle.sesion.interrupciones == 1
        assert bucle.cuenta.paradas == 1
        assert "paro" in " ".join(bucle.tts.dicho).lower()


class TestLoQueSeLocutaAlTerminar:
    def test_una_respuesta_normal_se_resume_y_se_dice(self, project_root, bucle):
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle._reaccionar(fin_de(project_root, "permitida"))
        assert bucle.tts.dicho
        assert "resumen.txt" in bucle.tts.dicho[0]
        assert bucle.cuenta.respuestas_locutadas == 1
        assert bucle.ciclo.estado is Estado.DORMIDO

    def test_por_defecto_se_dice_la_respuesta_ENTERA(self, project_root, bucle):
        """Decision del usuario del 2026-08-25, contra lo que decidio
        JC-0004: "quiero que diga siempre todo el texto". Son ~145
        segundos hablando para esta respuesta, y aun asi manda el."""
        assert bucle.limite_hablado is None
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle._reaccionar(fin_de(project_root, "respuesta_larga"))
        dicho = " ".join(bucle.tts.dicho)
        assert len(dicho) > 1500
        assert "consola" not in dicho    # no se corto, no hay resto
        assert "**" not in dicho and "`" not in dicho   # markdown fuera

    def test_con_resumir_se_recorta_y_se_dice_donde_esta_el_resto(
            self, project_root, bucle):
        """El interruptor de vuelta: `--voz --resumir`."""
        from voz.resumen import LIMITE_HABLADO

        bucle.limite_hablado = LIMITE_HABLADO
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle._reaccionar(fin_de(project_root, "respuesta_larga"))
        dicho = " ".join(bucle.tts.dicho)
        assert "10 puntos" in dicho
        assert "consola" in dicho
        assert len(dicho) < 400

    def test_sin_servidor_se_dice_eso_y_no_otra_cosa(self, project_root, bucle):
        """`subtipo` MIENTE en el fallo de red (dice "success"), asi que
        esto se prueba contra la captura real de una sesion sin red."""
        fin = fin_de(project_root, "sin_conexion")
        assert fin.sin_servidor is True
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle._reaccionar(fin)
        assert "servidor" in " ".join(bucle.tts.dicho)

    def test_antes_de_hablar_NO_suena_nada(self, project_root, bucle):
        """Desde el 2026-08-25 hay UN solo aviso y significa "habla tu".
        Sonarlo justo antes de que hable Jarvis invitaria al usuario a
        hablar encima, que es justo lo que JC-0011 queria evitar cuando
        pedia dos sonidos distintos. Su voz es su propio aviso.

        El aviso que SI suena despues es el de la ventana de seguimiento
        (JC-0012), y ese llega cuando Jarvis ya ha terminado de hablar.
        """
        sonaron: list[str] = []
        bucle.seguimiento = False      # aqui se mide el aviso de HABLAR
        bucle.ciclo.senales.campana = lambda: sonaron.append("campana")
        bucle.ciclo.senales.pitido = lambda: sonaron.append("pitido")
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle._reaccionar(fin_de(project_root, "permitida"))
        assert sonaron == []


class TestCuandoLaRESPUESTAAcabaPreguntando:
    """El caso que de verdad ocurre, y el que fallo en el primer uso.

    >>> `AskUserQuestion` NO ES POR DONDE PASA ESTO <<<
    La traza es un turno REAL capturado contra el binario
    (`pregunta_en_prosa.jsonl`): la pregunta llego en el TEXTO de la
    respuesta y el turno cerro. En todo el turno hay **cero**
    `control_request`. Un asistente que solo abre el microfono cuando
    llega la herramienta se queda callado justo despues de preguntarte
    algo -- que es lo que se vio y se reporto usandolo.
    """

    def _fin(self, project_root) -> Fin:
        return fin_de(project_root, "pregunta_en_prosa")

    def test_la_traza_es_una_pregunta_sin_herramienta(self, project_root):
        """Si esto cambia, el resto de la clase esta midiendo otra cosa."""
        eventos = list(eventos_de(project_root, "pregunta_en_prosa"))
        assert not any(isinstance(e, Pregunta) for e in eventos)
        fin = self._fin(project_root)
        assert not fin.fue_mal
        assert fin.texto.rstrip().endswith("?")

    def test_se_queda_escuchando_sin_pedir_la_palabra(self, project_root, bucle):
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle.stt = STTPostizo(oido("mejor hablemos de otra cosa"))
        bucle._reaccionar(self._fin(project_root))
        assert bucle.stt.escuchas == 1, "no abrio el microfono"

    def test_y_lo_que_contestas_viaja_como_TURNO_NUEVO(self, project_root, bucle):
        """El turno ya habia cerrado, asi que no hay puerta que contestar:
        se manda como turno. La sesion es la misma y el contexto tambien."""
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle.stt = STTPostizo(oido("mejor hablemos de otra cosa"))
        bucle._reaccionar(self._fin(project_root))
        assert bucle.sesion.mandados == ["mejor hablemos de otra cosa"]
        assert bucle.sesion.respondidas == []
        assert bucle.cuenta.respuestas_habladas == 1
        assert bucle.ciclo.estado is Estado.TRABAJANDO

    def test_suena_el_aviso_antes_de_escuchar(self, project_root, bucle):
        """Sin el, el usuario no sabe que le toca hablar."""
        sonaron = []
        bucle.ciclo.senales.campana = lambda: sonaron.append("aviso")
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle.stt = STTPostizo(oido("cuentame"))
        bucle._reaccionar(self._fin(project_root))
        assert sonaron == ["aviso"]

    def test_si_no_contestas_se_calla_y_se_va(self, project_root, bucle):
        """Sin "no te he oido": una pregunta que decides no contestar no
        deberia dar la lata."""
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle.stt = STTPostizo(oido("", hay_habla_vad=False))
        bucle._reaccionar(self._fin(project_root))
        dicho = " ".join(bucle.tts.dicho).lower()
        assert "no te he oido" not in dicho
        assert bucle.sesion.mandados == []
        assert bucle.ciclo.estado is Estado.DORMIDO

    def test_un_para_ahi_tambien_para(self, project_root, bucle):
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle.stt = STTPostizo(oido("cancela"))
        bucle._reaccionar(self._fin(project_root))
        assert bucle.sesion.interrupciones == 1
        assert bucle.sesion.mandados == []

    def test_tambien_con_un_cierre_amable_detras(self, project_root, bucle):
        """El caso real que fallo en la segunda prueba de uso: la
        pregunta va en medio y detras una frase de animo ("¡Vamos a
        dejar ese escritorio como los chorros del oro!")."""
        bucle.ciclo.estado = Estado.TRABAJANDO
        # OJO con la frase: "dejalo" es palabra de PARADA, y con ella
        # este test comprobaria la parada en vez de la respuesta.
        bucle.stt = STTPostizo(oido("prefiero hablar de otra cosa"))
        bucle._reaccionar(fin_de(project_root, "pregunta_con_cierre"))
        assert bucle.stt.escuchas == 1, "no abrio el microfono"
        assert bucle.sesion.mandados == ["prefiero hablar de otra cosa"]

    def test_sin_modo_conversacion_solo_abre_tras_una_PREGUNTA(
            self, project_root, bucle):
        """JC-0011 no depende del ajuste de JC-0012: si Jarvis pregunta,
        escucha, se ponga el modo conversacion como se ponga."""
        bucle.seguimiento = False
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle._reaccionar(fin_de(project_root, "permitida"))
        assert bucle.stt.escuchas == 0
        assert bucle.ciclo.estado is Estado.DORMIDO

        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle.stt = STTPostizo(oido("cuentame"))
        bucle._reaccionar(fin_de(project_root, "pregunta_en_prosa"))
        assert bucle.stt.escuchas == 1


class TestElModoConversacion:
    """JC-0012. La regla entera cabe en una linea: **la conversacion se
    encadena mientras hables y una sola ventana vacia la termina.**

    Lo caro que arregla: reactivar por voz no es fiable (14/20 con
    musica, 9/20 tecleando), asi que cada "hey jarvis" forzado es una
    tirada de esa moneda. Lo caro que crea: una ventana abierta
    transcribe a quien pase, y eso puede viajar como una orden que nadie
    dio. Por eso `ventanas_abiertas` y `ventanas_con_habla` se cuentan
    por separado: son la medida que dice si esto vale la pena.
    """

    def test_tras_una_respuesta_normal_se_sigue_escuchando(self, project_root,
                                                           bucle):
        assert bucle.seguimiento is True
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle.stt = STTPostizo(oido("y ahora abre la calculadora"))
        bucle._reaccionar(fin_de(project_root, "permitida"))
        assert bucle.sesion.mandados == ["y ahora abre la calculadora"]
        assert bucle.ciclo.estado is Estado.TRABAJANDO

    def test_UNA_VENTANA_VACIA_TERMINA_LA_CONVERSACION(self, project_root,
                                                       bucle):
        """No hay que decir "gracias" ni "para": te callas y se calla."""
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle.stt = STTPostizo(oido("", hay_habla_vad=False))
        bucle._reaccionar(fin_de(project_root, "permitida"))
        assert bucle.sesion.mandados == []
        assert bucle.ciclo.estado is Estado.DORMIDO
        assert bucle.cuenta.ventanas_abiertas == 1
        assert bucle.cuenta.ventanas_con_habla == 0

    def test_la_charla_se_encadena_sola(self, project_root, bucle):
        """Cada respuesta abre otra ventana. Tres vueltas seguidas sin
        que nadie diga la palabra de activacion ni una sola vez."""
        bucle.stt = STTPostizo(oido("una"), oido("dos"),
                               oido("", hay_habla_vad=False))
        for _ in range(3):
            bucle.ciclo.estado = Estado.TRABAJANDO
            bucle._reaccionar(fin_de(project_root, "permitida"))
        assert bucle.sesion.mandados == ["una", "dos"]
        assert bucle.cuenta.ventanas_abiertas == 3
        assert bucle.cuenta.ventanas_con_habla == 2
        assert bucle.ciclo.estado is Estado.DORMIDO

    def test_la_fraccion_util_es_la_medida_de_si_esto_vale(self, project_root,
                                                           bucle):
        """El par, no una bandera. Si la fraccion es baja, se
        esta abriendo el microfono para nada casi siempre."""
        bucle.stt = STTPostizo(oido("sigue"), oido("", hay_habla_vad=False))
        for _ in range(2):
            bucle.ciclo.estado = Estado.TRABAJANDO
            bucle._reaccionar(fin_de(project_root, "permitida"))
        assert bucle.cuenta.fraccion_de_ventanas_utiles == 0.5

    def test_tras_una_PARADA_no_se_escucha(self, project_root, bucle):
        """Acaba de pedir silencio. Abrirle el microfono seria no
        haberle hecho caso."""
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle._reaccionar(fin_de(project_root, "parada"))
        assert bucle.stt.escuchas == 0
        assert bucle.cuenta.ventanas_abiertas == 0

    def test_tras_un_FALLO_tampoco(self, project_root, bucle):
        """La ventana sigue a una RESPUESTA, no a un fallo. Abrir el
        microfono despues de "no llego al servidor" seria pedir que le
        hables a algo que no funciona."""
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle._reaccionar(fin_de(project_root, "sin_conexion"))
        assert bucle.stt.escuchas == 0
        assert bucle.cuenta.ventanas_abiertas == 0

    def test_un_para_en_la_ventana_para(self, project_root, bucle):
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle.stt = STTPostizo(oido("cancela"))
        bucle._reaccionar(fin_de(project_root, "permitida"))
        assert bucle.sesion.interrupciones == 1
        assert bucle.sesion.mandados == []
        assert bucle.cuenta.ventanas_con_habla == 1

    def test_la_ventana_de_seguimiento_es_MAS_LARGA_que_la_de_una_orden(self):
        """En una orden ya has decidido hablar; aqui tienes que decidir
        si sigues la conversacion."""
        from voz.bucle import ESPERA_ORDEN_S, ESPERA_SEGUIMIENTO_S
        assert ESPERA_SEGUIMIENTO_S > ESPERA_ORDEN_S

    def test_si_el_resumen_corto_la_pregunta_se_dice_igual(self, bucle):
        """El microfono no puede abrirse por una pregunta que el usuario
        no ha llegado a oir."""
        largo = "Hecho. " + ("He revisado muchas cosas. " * 30)
        fin = Fin(session_id="s", subtipo="success", es_error=False,
                  texto=largo + "¿Sigo con el resto?", coste_usd=0.0,
                  duracion_ms=1, num_turnos=1, razon_terminal="completed")
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle.stt = STTPostizo(oido("si, sigue"))
        bucle._reaccionar(fin)
        assert any("Sigo con el resto" in d for d in bucle.tts.dicho)


class TestLaPuertaSePideYSeContestaHablando:
    """JC-0002. Es el sitio donde el usuario CONSIENTE, asi que lo que se
    prueba aqui no es que "funcione": es que la frase salga de la misma
    `Decision` que pinta la consola, y que el silencio no se convierta en
    un no.
    """

    def _con_puerta(self, project_root, bucle, dicho: str | None):
        """Monta la puerta REAL con su decision REAL, como la sesion."""
        from puente.politica import decidir
        from puente.sesion import Pendiente

        puertas = [e for e in eventos_de(project_root, "denegada")
                   if isinstance(e, Puerta)]
        assert puertas, "la traza tenia que traer al menos una puerta"
        puerta = puertas[0]
        decision = decidir(puerta, directorio_sesion=bucle.sesion.directorio)
        bucle.sesion.pendientes = (
            Pendiente(evento=puerta, decision=decision, pedido_en=0.0),)
        if dicho is None:
            bucle.stt = STTPostizo(oido("si", hay_habla_vad=False))
        else:
            bucle.stt = STTPostizo(oido(dicho))
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle._reaccionar(puerta)
        return puerta, decision

    def test_la_frase_nombra_lo_MISMO_que_la_consola(self, project_root,
                                                     bucle):
        """Si divergieran, se aprobaria una cosa y se ejecutaria otra."""
        _puerta, decision = self._con_puerta(project_root, bucle, "no")
        dicho = " ".join(bucle.tts.dicho)
        assert decision.motivo in dicho
        import os
        assert os.path.basename(decision.elementos[0]) in dicho

    def test_un_SI_hablado_autoriza_la_puerta(self, project_root, bucle):
        puerta, _ = self._con_puerta(project_root, bucle, "si")
        assert bucle.sesion.respondidas == [(puerta.id_peticion, True, {})]
        assert bucle.cuenta.permisos_dados == 1
        assert "utorizado" in " ".join(bucle.tts.dicho)

    def test_un_NO_hablado_la_deniega(self, project_root, bucle):
        puerta, _ = self._con_puerta(project_root, bucle, "no")
        assert bucle.sesion.respondidas == [(puerta.id_peticion, False, {})]
        assert bucle.cuenta.permisos_denegados == 1

    def test_EL_SILENCIO_NO_ES_UN_NO(self, project_root, bucle):
        """La puerta se queda pendiente: la sesion espera indefinidamente
        (medido) y la puede contestar la consola, o Telegram cuando
        exista. Denegar por silencio convertiria "no estaba delante" en
        "dijo que no"."""
        self._con_puerta(project_root, bucle, None)
        assert bucle.sesion.respondidas == []
        assert bucle.cuenta.permisos_sin_respuesta == 1
        assert "pendiente" in " ".join(bucle.tts.dicho)

    def test_si_otro_canal_contesto_antes_la_voz_se_calla(self, project_root,
                                                          bucle):
        """La carrera entre la voz y la consola es normal. El que pierde
        no puede anunciar algo que ya no es verdad."""
        bucle.sesion.contesta = False
        self._con_puerta(project_root, bucle, "si")
        dicho = " ".join(bucle.tts.dicho)
        assert "utorizado" not in dicho
        assert bucle.cuenta.permisos_dados == 0

    def test_al_acabar_vuelve_a_TRABAJANDO(self, project_root, bucle):
        """El turno no habia terminado: sigue donde estaba, y el hilo del
        oido vuelve a escuchar paradas."""
        self._con_puerta(project_root, bucle, "si")
        assert bucle.ciclo.estado is Estado.TRABAJANDO

    def test_sin_decision_no_se_inventa_la_peticion(self, project_root,
                                                    bucle):
        """Sin `Decision` no hay motivo ni elementos. Antes que inventar
        la frase en la que el usuario consiente, se manda a la consola."""
        puertas = [e for e in eventos_de(project_root, "denegada")
                   if isinstance(e, Puerta)]
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle._reaccionar(puertas[0])          # sin pendientes
        assert bucle.sesion.respondidas == []
        assert "consola" in " ".join(bucle.tts.dicho)
        assert bucle.stt.escuchas == 0

    def test_una_pregunta_SIN_enunciado_se_manda_a_la_consola(self, bucle):
        """No se puede locutar lo que no tiene texto, y no se inventa."""
        bucle._reaccionar(Pregunta(id_peticion="p1", id_uso="u1",
                                   preguntas=()))
        assert "consola" in " ".join(bucle.tts.dicho)


class TestCuandoJarvisPregunta:
    """Lo que pidio el usuario tras usarlo: si Jarvis pregunta, la
    escucha se abre SOLA. Tener que decir "hey jarvis" para contestarle
    convierte una conversacion en un formulario.

    La pregunta es la REAL, sacada de `pregunta.jsonl`: enunciado, dos
    opciones con etiqueta y descripcion. Una escrita a mano no habria
    tenido `options` y el emparejado no se habria probado.
    """

    def _pregunta(self, project_root) -> Pregunta:
        preguntas = [e for e in eventos_de(project_root, "pregunta")
                     if isinstance(e, Pregunta)]
        assert preguntas, "la traza tenia que traer una pregunta"
        return preguntas[0]

    def _trabajando(self, bucle):
        bucle.ciclo.estado = Estado.TRABAJANDO
        return bucle

    def test_locuta_el_enunciado_y_las_opciones(self, project_root, bucle):
        """Sin las opciones, el usuario no sabe que puede decir."""
        self._trabajando(bucle)
        bucle.stt = STTPostizo(oido("minusculas"))
        bucle._reaccionar(self._pregunta(project_root))
        dicho = " ".join(bucle.tts.dicho).lower()
        assert "may" in dicho and "min" in dicho
        assert "puedes decir" in dicho

    def test_contesta_con_la_ETIQUETA_de_la_opcion(self, project_root, bucle):
        """Medido el 2026-08-25: la respuesta viaja en
        `updatedInput.answers`, emparejando enunciado con etiqueta."""
        self._trabajando(bucle)
        bucle.stt = STTPostizo(oido("pues en minusculas mejor"))
        pregunta = self._pregunta(project_root)
        bucle._reaccionar(pregunta)

        assert bucle.sesion.respondidas, "no se contesto la pregunta"
        id_peticion, permitir, respuestas = bucle.sesion.respondidas[0]
        assert id_peticion == pregunta.id_peticion
        assert permitir is True
        assert list(respuestas.values())[0].lower().startswith("min")
        assert bucle.cuenta.preguntas_contestadas == 1

    def test_si_no_dice_ninguna_opcion_se_manda_LO_QUE_DIJO(self, project_root,
                                                            bucle):
        """Elegir por el la opcion "mas parecida" seria peor que pasarle
        la frase a un modelo que sabe leerla."""
        self._trabajando(bucle)
        bucle.stt = STTPostizo(oido("me da igual, decide tu"))
        bucle._reaccionar(self._pregunta(project_root))
        _id, _permitir, respuestas = bucle.sesion.respondidas[0]
        assert "decide" in list(respuestas.values())[0]

    def test_no_se_contesta_lo_que_no_se_entendio(self, project_root, bucle):
        """La pregunta se queda abierta y se dice. Contestar a medias
        seria poner en boca del usuario algo que no dijo."""
        self._trabajando(bucle)
        bucle.stt = STTPostizo(oido("", hay_habla_vad=False))
        bucle._reaccionar(self._pregunta(project_root))
        assert bucle.sesion.respondidas == []
        assert "consola" in " ".join(bucle.tts.dicho)
        assert bucle.ciclo.estado is Estado.TRABAJANDO

    def test_un_para_mientras_pregunta_para(self, project_root, bucle):
        self._trabajando(bucle)
        bucle.stt = STTPostizo(oido("cancela"))
        bucle._reaccionar(self._pregunta(project_root))
        assert bucle.sesion.interrupciones == 1
        assert bucle.sesion.respondidas == []

    def test_al_contestar_se_vuelve_a_TRABAJANDO(self, project_root, bucle):
        """El turno no habia terminado: sigue donde estaba."""
        self._trabajando(bucle)
        bucle.stt = STTPostizo(oido("minusculas"))
        bucle._reaccionar(self._pregunta(project_root))
        assert bucle.ciclo.estado is Estado.TRABAJANDO


class TestElAvisoDeRed:
    """Trampa medida: una sesion sin red se calla ~180 s y por dentro se
    parece a una que esta pensando. Se avisa en el PRIMER reintento."""

    def _reintento(self, numero: int) -> Reintento:
        return Reintento(intento=numero, intentos_maximos=10, espera_ms=1000)

    def test_se_avisa_una_vez_y_no_en_cada_reintento(self, bucle):
        for numero in (1, 2, 3):
            bucle._reaccionar(self._reintento(numero))
        assert len(bucle.tts.dicho) == 1

    def test_y_vuelve_a_armarse_cuando_la_red_funciona(self, project_root, bucle):
        """Sin esto el aviso se da UNA vez en la vida del proceso y el
        segundo apagon pasa en silencio."""
        bucle._reaccionar(self._reintento(1))
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle._reaccionar(fin_de(project_root, "permitida"))
        bucle.tts.dicho.clear()
        bucle._reaccionar(self._reintento(1))
        assert bucle.tts.dicho


class TestElCaminoDeLaOrden:
    def test_una_orden_buena_viaja_a_claude_code(self, bucle):
        bucle.stt = STTPostizo(oido("abre el bloc de notas"))
        bucle._al_despertar(activacion=None)
        assert bucle.sesion.mandados == ["abre el bloc de notas"]
        assert bucle.ciclo.estado is Estado.TRABAJANDO

    def test_una_orden_en_la_que_no_se_confia_NO_viaja(self, bucle):
        """Falla cerrado: `small` se inventa texto ante el silencio 12 de
        12 veces, y lo que se invente lo ejecutaria un agente capaz."""
        bucle.stt = STTPostizo(oido("abre la calculadora", hay_habla_vad=False))
        bucle._al_despertar(activacion=None)
        assert bucle.sesion.mandados == []
        assert bucle.cuenta.no_te_he_oido == 1
        assert "oido" in " ".join(bucle.tts.dicho)
        assert bucle.ciclo.estado is Estado.DORMIDO

    def test_si_la_sesion_no_abre_no_se_manda_nada(self, bucle):
        """El puente arranca mudo y la sesion se abre con la primera
        orden; si el suelo de JC-0007 no esta, no se manda igualmente."""
        bucle.abrir_sesion = lambda: (False, "el suelo no muerde")
        bucle.stt = STTPostizo(oido("borra los temporales"))
        bucle._al_despertar(activacion=None)
        assert bucle.sesion.mandados == []
        assert bucle.ciclo.estado is Estado.DORMIDO

    def test_un_cancela_nada_mas_despertar_no_se_manda_como_orden(self, bucle):
        bucle.stt = STTPostizo(oido("cancela"))
        bucle._al_despertar(activacion=None)
        assert bucle.sesion.mandados == []


class TestElOidoSueltaElMicrofono:
    """El hallazgo del 2026-08-26: contestar una puerta llegaba tarde.

    Contando lo que le pasaba, dudaba entre dos causas: que no le hubiera
    entendido, o haber contestado demasiado pronto. Era lo segundo, y el
    hueco no estaba anunciado: la
    vuelta EN VUELO del hilo del oido son 3,0 s de grabacion mas 1,7-1,9 s
    de Whisper -- medidos, no supuestos --, y hasta que no termina, quien
    quiere preguntar no tiene microfono.

    Y no era intermitente: era seguro justo detras de una puerta, porque
    el oido graba MIENTRAS Jarvis habla y su ventana viene llena de la voz
    del propio Jarvis. Con la sala callada el VAD la despacha en 0,02 s y
    el hueco no se nota.
    """

    def test_pedir_el_microfono_avisa_al_oido_antes_de_esperar(self, bucle):
        """El orden importa: primero se avisa, LUEGO se pide el cerrojo.

        Al reves no serviria de nada -- se estaria esperando la vuelta
        entera con la bandera puesta detras del cerrojo, que es justo el
        hueco que se venia a quitar. Y con el microfono ya en la mano la
        bandera tiene que estar limpia: solo sirve para atravesar la
        espera, no para dejar al oido apagado.
        """
        dentro = []
        with bucle._con_el_microfono():
            dentro.append(bucle._suelta_el_micro.is_set())
        assert dentro == [False]
        assert not bucle._suelta_el_micro.is_set()

    def test_la_bandera_se_limpia_aunque_lo_de_dentro_reviente(self, bucle):
        """Si se quedara puesta, el oido soltaria TODAS sus vueltas a
        partir de ahi y Jarvis dejaria de oir las paradas -- que es lo
        unico que no puede dejar de oir mientras trabaja."""
        with pytest.raises(RuntimeError):
            with bucle._con_el_microfono():
                raise RuntimeError("algo se rompio locutando")
        assert not bucle._suelta_el_micro.is_set()

    def test_una_vuelta_soltada_no_se_enruta_ni_para_el_turno(self, bucle):
        """>>> LO QUE NO PUEDE PASAR <<<

        Una vuelta soltada NO dice si hubo habla: nadie la miro. Enrutarla
        la convertiria en "no dijo nada", y por el mismo camino un turno
        podria pararse por audio que nadie llego a transcribir.
        """
        bucle.ciclo.estado = Estado.TRABAJANDO
        assert bucle.ciclo.escucha_paradas

        bucle._suelta_el_micro.set()
        bucle._parar.clear()
        hilo = threading.Thread(target=bucle._oido, daemon=True)
        hilo.start()
        time.sleep(0.3)
        bucle._parar.set()
        hilo.join(timeout=2)

        assert bucle.stt.soltadas >= 1, "el oido no solto ninguna vuelta"
        assert bucle.cuenta.vueltas_del_oido_soltadas >= 1
        assert bucle.sesion.interrupciones == 0, (
            "una vuelta soltada paro el turno: se enruto audio sin mirar"
        )

    def test_contestar_una_puerta_con_el_oido_dando_vueltas(self, project_root,
                                                            bucle):
        """De punta a punta, en el camino que fallaba.

        La puerta es la REAL de una traza capturada, con su `Decision`
        real. Lo que se anade es el hilo del oido corriendo de
        verdad al mismo tiempo, que es lo que en produccion se comia los
        segundos.
        """
        from puente.politica import decidir
        from puente.sesion import Pendiente

        puertas = [e for e in eventos_de(project_root, "denegada")
                   if isinstance(e, Puerta)]
        assert puertas, "la traza tenia que traer al menos una puerta"
        puerta = puertas[0]
        bucle.sesion.pendientes = (
            Pendiente(evento=puerta,
                      decision=decidir(puerta,
                                       directorio_sesion=bucle.sesion.directorio),
                      pedido_en=0.0),)
        bucle.stt = STTPostizo(oido("no"))
        bucle.ciclo.estado = Estado.TRABAJANDO

        bucle._parar.clear()
        hilo = threading.Thread(target=bucle._oido, daemon=True)
        hilo.start()
        try:
            bucle._reaccionar(puerta)
        finally:
            bucle._parar.set()
            hilo.join(timeout=3)

        assert [r[:2] for r in bucle.sesion.respondidas] == [
            (puerta.id_peticion, False)
        ], "la puerta no se contesto: la voz se quedo sin microfono"
        assert bucle.cuenta.permisos_denegados == 1
        # Y EL ATAJO SE TOMO DE VERDAD: sin esto, el test
        # pasaria igual con el oido parado, o sea sin haber ejercitado
        # nada de lo que se vino a arreglar.
        assert bucle.cuenta.vueltas_del_oido_soltadas >= 1, (
            "el oido nunca llego a tener una vuelta en vuelo: este test no"
            " esta probando el atajo"
        )


class TestElBuzon:
    def test_recibir_NO_locuta_nada(self, project_root, bucle):
        """Locutar en `recibir` bloquearia el hilo que bombea la sesion:
        mientras Jarvis habla, la consola dejaria de pintar y las puertas
        dejarian de llegar."""
        bucle.recibir(fin_de(project_root, "permitida"))
        assert bucle.tts.dicho == []

    def test_y_el_bucle_lo_atiende_despues(self, project_root, bucle):
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle.recibir(fin_de(project_root, "permitida"))
        bucle._atender_buzon()
        assert bucle.tts.dicho

    def test_un_fallo_locutando_no_se_lleva_el_bucle(self, project_root, bucle):
        """El usuario se quedaria sin voz Y sin saber por que."""
        def reventar(*_a, **_k):
            raise RuntimeError("el altavoz se fue")
        bucle.tts.hablar = reventar
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle.recibir(fin_de(project_root, "permitida"))
        bucle._atender_buzon()   # no revienta


class TestCambiarDeProyecto:
    """ADR-0029, pasos 1, 2 y 6, en el bucle de verdad.

    Los tests de forma (que frase es que) estan en
    `tests/test_voz_proyecto.py`. Aqui se prueba lo unico que no se puede
    probar alli: **que la orden no llegue al cerebro**, que es la
    excepcion a "TODO pasa por Claude Code" y por tanto lo que hay que
    vigilar.
    """

    def _con_registro(self, bucle, monkeypatch, tmp_path, alias="nebula"):
        from nucleo import proyectos as mod

        carpeta = tmp_path / alias
        carpeta.mkdir()
        monkeypatch.setattr(
            mod, "leer",
            lambda config_dir=None: (mod.Proyecto(alias, str(carpeta)),))
        # El flujo nace APAGADO: hay que encenderlo para probarlo, igual
        # que tiene que hacer el usuario.
        # >>> SE PARCHEA `intercepta` Y NO `por_voz` (2026-09-03) <<<
        # El interruptor cambio de nombre al empezar a gobernar
        # tambien la consola. `por_voz` sigue existiendo como alias,
        # pero parchearlo NO haria nada: quien lo consulta es
        # `voz.proyecto.atender`, y llama al nuevo.
        monkeypatch.setattr(mod, "intercepta", lambda config_dir=None: True)
        movidas = []
        # >>> EL DOBLE RECOGE TAMBIEN EL MODO, Y NO ES DECORADO <<<
        # Desde JC-0017 el auto mode viaja CON la carpeta. Un doble que
        # solo aceptara la ruta pasaria por verde mientras el modo se
        # queda en el del proyecto anterior, que es un fallo mudo en las
        # dos direcciones: o te empieza a preguntar sin motivo, o deja de
        # preguntarte sin que nadie lo pidiera.
        bucle.sesion.cambiar_a = (
            lambda ruta, modo_permisos=None:
            movidas.append((str(ruta), modo_permisos)))
        return carpeta, movidas

    def test_APAGADO_ni_se_mira_la_frase(self, bucle, monkeypatch, tmp_path):
        """>>> EL INTERRUPTOR, Y POR QUE SE MIRA EL PRIMERO <<<

        Apagado, `interpretar` no llega a correr: la frase va intacta al
        cerebro. Si se mirase la frase antes que el interruptor, una
        orden que sonara a esto se quedaria por el camino con el flujo
        apagado -- interceptada por un mecanismo que el usuario no ha
        encendido.
        """
        from nucleo import proyectos as mod

        carpeta = tmp_path / "nebula"
        carpeta.mkdir()
        monkeypatch.setattr(
            mod, "leer",
            lambda config_dir=None: (mod.Proyecto("nebula", str(carpeta)),))
        monkeypatch.setattr(mod, "intercepta", lambda config_dir=None: False)
        movidas = []
        bucle.sesion.cambiar_a = lambda r: movidas.append(str(r))

        assert bucle._cambiar_de_proyecto("abre el proyecto nebula") is False
        assert movidas == []
        assert bucle.sesion.mandados == []

    def test_nace_apagado(self, tmp_path):
        """Encenderlo es aceptar que una frase tuya deje de llegar al
        cerebro. Eso no se da por hecho: se pide."""
        from nucleo.proyectos import Proyecto, guardar, intercepta, por_voz

        assert intercepta(config_dir=tmp_path) is False
        guardar((Proyecto("x", str(tmp_path)),), config_dir=tmp_path)
        assert intercepta(config_dir=tmp_path) is False, (
            "guardar no lo enciende")
        guardar((Proyecto("x", str(tmp_path)),), activo=True,
                config_dir=tmp_path)
        assert intercepta(config_dir=tmp_path) is True
        # El alias viejo tiene que seguir contestando lo mismo: hay
        # `config/proyectos.yaml` por ahi con la clave antigua.
        assert por_voz(config_dir=tmp_path) is True

    def test_cambiar_de_proyecto_NO_llega_al_cerebro(self, bucle, monkeypatch,
                                                     tmp_path):
        """>>> LA EXCEPCION, Y SU LIMITE <<<

        Claude Code no puede mover el directorio de su propia sesion, asi
        que esta frase no es para el. Lo que SI tiene que llegarle es la
        primera pregunta del ritual, y nada mas.
        """
        carpeta, movidas = self._con_registro(bucle, monkeypatch, tmp_path)
        bucle.ciclo.desperto()
        bucle.ciclo.oido(oido("abre el proyecto nebula"))
        bucle._cambiar_de_proyecto("abre el proyecto nebula")

        assert movidas == [(str(carpeta), "auto")]
        assert bucle.sesion.mandados == ["hola, en que nos quedamos?"]
        assert bucle.cuenta.proyectos_abiertos == 1

    def test_se_dice_la_CARPETA_y_no_solo_el_alias(self, bucle, monkeypatch,
                                                   tmp_path):
        """Condicion 1 de ADR-0029: la peticion nombra la ruta. Dos
        proyectos con nombres parecidos es donde esto se equivoca caro."""
        carpeta, _ = self._con_registro(bucle, monkeypatch, tmp_path)
        bucle._cambiar_de_proyecto("abre el proyecto nebula")
        dicho = " ".join(bucle.tts.dicho)
        assert str(carpeta) in dicho

    def test_una_orden_normal_SI_llega_al_cerebro(self, bucle, monkeypatch):
        """El no-regresion que importa: si la interceptacion se pasa de
        lista, ordenes buenas dejan de funcionar y el usuario solo ve que
        Jarvis no hace nada. Se prueba con el flujo ENCENDIDO, que es
        cuando puede pasar."""
        from nucleo import proyectos as mod

        # >>> SE PARCHEA `intercepta` Y NO `por_voz` (2026-09-03) <<<
        # El interruptor cambio de nombre al empezar a gobernar
        # tambien la consola. `por_voz` sigue existiendo como alias,
        # pero parchearlo NO haria nada: quien lo consulta es
        # `voz.proyecto.atender`, y llama al nuevo.
        monkeypatch.setattr(mod, "intercepta", lambda config_dir=None: True)
        assert bucle._cambiar_de_proyecto("borra la carpeta de descargas") is False
        assert bucle.sesion.mandados == []

    def test_un_proyecto_que_no_esta_registrado_no_mueve_nada(self, bucle,
                                                              monkeypatch,
                                                              tmp_path):
        """No se busca por el disco a ver si suena parecido."""
        _, movidas = self._con_registro(bucle, monkeypatch, tmp_path)
        assert bucle._cambiar_de_proyecto("abre el proyecto tienda") is True
        assert movidas == []
        assert bucle.sesion.mandados == []
        assert "tienda" in " ".join(bucle.tts.dicho)

    def test_varias_candidatas_no_abren_ninguna(self, bucle, monkeypatch,
                                                tmp_path):
        """*"Ante varias candidatas, se pregunta"* -- del propio ADR."""
        from nucleo import proyectos as mod

        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        monkeypatch.setattr(mod, "leer", lambda config_dir=None: (
            mod.Proyecto("nebula", str(tmp_path / "a")),
            mod.Proyecto("otro", str(tmp_path / "nebula")),
        ))
        # >>> SE PARCHEA `intercepta` Y NO `por_voz` (2026-09-03) <<<
        # El interruptor cambio de nombre al empezar a gobernar
        # tambien la consola. `por_voz` sigue existiendo como alias,
        # pero parchearlo NO haria nada: quien lo consulta es
        # `voz.proyecto.atender`, y llama al nuevo.
        monkeypatch.setattr(mod, "intercepta", lambda config_dir=None: True)
        movidas = []
        bucle.sesion.cambiar_a = lambda r: movidas.append(str(r))
        assert bucle._cambiar_de_proyecto("abre el proyecto nebula") is True
        assert movidas == [], "eligio por el usuario"
        assert bucle.sesion.mandados == []

    def test_pedirlo_sin_nombre_pregunta_y_no_manda_nada(self, bucle,
                                                          monkeypatch):
        from nucleo import proyectos as mod

        # >>> SE PARCHEA `intercepta` Y NO `por_voz` (2026-09-03) <<<
        # El interruptor cambio de nombre al empezar a gobernar
        # tambien la consola. `por_voz` sigue existiendo como alias,
        # pero parchearlo NO haria nada: quien lo consulta es
        # `voz.proyecto.atender`, y llama al nuevo.
        monkeypatch.setattr(mod, "intercepta", lambda config_dir=None: True)
        assert bucle._cambiar_de_proyecto("abre el proyecto") is True
        assert bucle.sesion.mandados == []
        assert "proyecto" in " ".join(bucle.tts.dicho).lower()


# --- LA NARRACION MIENTRAS TRABAJA (2026-08-27) ---------------------------


def _texto(t: str):
    from puente.protocolo import Texto

    return Texto(texto=t)


def _herramienta():
    from puente.protocolo import UsoHerramienta

    return UsoHerramienta(id_uso="u1", herramienta="Bash", entrada={})


def test_un_texto_SEGUIDO_de_herramienta_se_locuta(bucle):
    """>>> LO QUE PIDIO EL USUARIO (2026-08-27) <<<

    Lo que pidio el usuario: que los comentarios que Claude va soltando
    mientras trabaja -- del tipo "ahora verifico el dato contra el
    codigo" -- salgan tambien por el TTS. El motivo que dio es que asi se
    nota que trabaja de verdad.
    """
    bucle._reaccionar(_texto("Ahora verifico el dato contra el codigo."))
    assert bucle.tts.dicho == []          # todavia no se sabe que era
    bucle._reaccionar(_herramienta())
    assert bucle.tts.dicho == ["Ahora verifico el dato contra el codigo."]
    assert bucle.cuenta.narraciones_dichas == 1


def test_un_texto_SEGUIDO_de_Fin_NO_se_locuta_aqui(bucle):
    """>>> SI NO, LA RESPUESTA SE DIRIA DOS VECES <<<

    El ultimo `Texto` de un turno es la RESPUESTA, y esa la locuta
    `_al_terminar` desde el 2026-08-25. Un `Texto` solo es narracion si
    detras viene una herramienta, y por eso no se puede juzgar al
    recibirlo: hay que esperar al evento siguiente.
    """
    bucle.ciclo.estado = Estado.TRABAJANDO
    bucle.seguimiento = False
    bucle._reaccionar(_texto("Ya esta todo listo."))
    bucle._reaccionar(Fin(session_id="s", subtipo="success",
                          es_error=False,
                          texto="Ya esta todo listo.",
                          coste_usd=0.0, duracion_ms=10,
                          num_turnos=1))
    assert bucle.cuenta.narraciones_dichas == 0
    # Lo dijo UNA vez, y por el camino de la respuesta.
    assert bucle.tts.dicho.count("Ya esta todo listo.") == 1


def test_una_puerta_borra_el_comentario_pendiente(bucle):
    """Una puerta es una pregunta que hay que contestar. Locutar antes la
    charla de al lado retrasa la pregunta y se pisan."""
    bucle._reaccionar(_texto("Voy a mirar una cosa."))
    bucle._reaccionar(next(p for p in [
        Puerta(id_peticion="r", herramienta="Bash",
               entrada={"command": "ls"}, descripcion="", id_uso="u")]))
    assert bucle.cuenta.narraciones_dichas == 0
    assert "Voy a mirar una cosa." not in bucle.tts.dicho


def test_un_comentario_que_llega_TARDE_no_se_dice(bucle):
    """>>> `decir` BLOQUEA, Y ESO MANDA <<<

    Si mientras hablabamos el trabajo siguio, "ahora voy a mirar el
    codigo" se locutaria cuando ya lo miro y ademas hizo otras tres
    cosas. Eso no da vividez: da la sensacion de que Jarvis va por detras
    de si mismo. Se cuenta aparte para poder verlo.
    """
    bucle._reaccionar(_texto("Ahora miro el codigo."))
    bucle._buzon.put(_herramienta())      # ya hay mas trabajo esperando
    bucle._reaccionar(_herramienta())
    assert bucle.tts.dicho == []
    assert bucle.cuenta.narraciones_tarde == 1
    assert bucle.cuenta.narraciones_dichas == 0


def test_apagado_no_narra_nada(bucle):
    """`--voz --sin-narracion`, o el interruptor del panel."""
    bucle.narrar = False
    bucle._reaccionar(_texto("Ahora verifico el dato."))
    bucle._reaccionar(_herramienta())
    assert bucle.tts.dicho == []
    assert bucle.cuenta.narraciones_dichas == 0


def test_un_comentario_con_una_ruta_no_llega_al_tts(bucle):
    """La otra mitad de lo que pidio el usuario: por el TTS solo el texto,
    nunca los comandos. Se cuenta como mudo, no como dicho."""
    bucle._reaccionar(_texto(r"Voy a mirar C:\proyectos\nebula."))
    bucle._reaccionar(_herramienta())
    assert bucle.tts.dicho == []
    assert bucle.cuenta.narraciones_mudas == 1


def test_tras_un_para_no_se_narra(bucle):
    """Quien dijo "para" quiere silencio, tambien de la charla."""
    bucle._callar.set()
    bucle._reaccionar(_texto("Ahora verifico el dato."))
    bucle._reaccionar(_herramienta())
    assert bucle.tts.dicho == []
    assert bucle.cuenta.narraciones_dichas == 0


# --- "APAGATE" Y LA TAREA EN PANTALLA (2026-08-27) ------------------------


class TestApagate:
    """>>> LO QUE PIDIO EL USUARIO <<< una palabra mas, "apagate", que
    mate del todo a Jarvis y a sus procesos, al lado de las dos que ya
    habia: "abrete" y "cierrate".

    Cabe en la misma regla que las otras dos -- reflexiva, no significa
    nada mas, no se le puede decir a Claude Code sobre un archivo --, pero
    su asimetria es distinta: equivocarse con "cierrate" esconde una
    ventana y se arregla con un clic; equivocarse con "apagate" mata el
    asistente Y el turno en marcha.
    """

    def test_apagate_llama_a_la_carcasa(self, bucle):
        apagados = []
        bucle.gestos = Gestos(apagar=lambda: apagados.append(1))
        assert bucle._de_la_ventana("apagate") is True
        assert apagados == [1]
        assert bucle.cuenta.apagados == 1

    def test_se_DESPIDE_antes_de_morir(self, bucle):
        """Las otras dos se ven: la ventana aparece o desaparece delante.
        Esta no -- lo que se ve es que Jarvis deja de contestar, que es
        identico a un cuelgue. Sin despedida, un "apagate" oido por error
        y un Jarvis roto son indistinguibles."""
        bucle.gestos = Gestos(apagar=lambda: None)
        bucle._de_la_ventana("apagate")
        assert bucle.tts.dicho, "se apago sin decir nada"
        assert "apago" in " ".join(bucle.tts.dicho).lower()

    def test_corta_el_turno_antes_de_apagarse(self, bucle):
        """Matar el puente a secas deja a Claude Code a mitad de una
        secuencia de herramientas. `interrumpir` esta medido (JC-0011):
        corta en centesimas y corta las herramientas de verdad."""
        bucle.sesion.viva = True
        bucle.gestos = Gestos(apagar=lambda: None)
        bucle._de_la_ventana("apagate")
        assert bucle.sesion.interrupciones == 1

    def test_sin_carcasa_lo_DICE_en_vez_de_matar_a_lo_bruto(self, bucle):
        """Tercera salida. Lanzado con `-m puente` desde una
        terminal no hay carcasa, y matar el proceso desde aqui dejaria la
        sesion de Claude Code sin cerrar -- lo contrario de lo pedido."""
        bucle.gestos = Gestos()   # sin carcasa que apagar
        assert bucle._de_la_ventana("apagate") is True
        assert bucle.cuenta.apagados == 0
        assert "terminal" in " ".join(bucle.tts.dicho).lower()

    def test_apagate_NO_llega_al_cerebro(self, bucle):
        bucle.gestos = Gestos(apagar=lambda: None)
        bucle._de_la_ventana("apagate")
        assert bucle.sesion.mandados == []


class TestLoQueDijeSeVe:
    """>>> LO QUE PIDIO EL USUARIO (2026-08-27) <<< ver escrito en la
    consola el texto de la instruccion que acaba de dar por voz, para
    saber si le llego bien.

    No es adorno: es la unica forma de comprobar que el STT te entendio.
    Sin eso, una orden mal transcrita se ejecuta y lo primero que ves es
    a Claude Code haciendo algo que no pediste.

    >>> Y ESTOS TESTS APUNTABAN AL SITIO EQUIVOCADO <<<
    La primera version probaba `_mandar`, y por eso pasaban en verde con
    la funcion mal puesta: se anunciaba lo que SE MANDA en vez de lo que
    SE DIJO, y ademas dos de los tres caminos reales ni pasan por ahi.
    Ahora se entra por donde entra la voz de verdad.
    """

    def _espia(self, bucle):
        anunciados = []
        bucle.anunciar_turno = lambda texto, origen: anunciados.append(
            (texto, origen))
        return anunciados

    def test_una_orden_hablada_se_anuncia_literal(self, bucle):
        anunciados = self._espia(bucle)
        bucle.stt = STTPostizo(oido("evalua las semanas de progreso"))
        bucle._al_despertar(activacion=None)
        assert anunciados == [("evalua las semanas de progreso", "voz")]
        assert bucle.tarea.tarea == "evalua las semanas de progreso"
        assert bucle.tarea.origen == "voz"

    def test_lo_que_CONTESTAS_en_la_ventana_tambien_se_ve(self, bucle):
        """>>> ESTE CAMINO NO PASABA POR `_mandar` <<< y por eso no se
        veia NADA. Lo vio el usuario contestando a una pregunta de Claude
        Code, que es el camino mas comun de toda la conversacion."""
        anunciados = self._espia(bucle)
        bucle.ciclo.estado = Estado.TRABAJANDO
        bucle.stt = STTPostizo(oido("si, sigue por el paso b"))
        bucle._ventana_de_seguimiento(tras_pregunta=True)
        assert anunciados == [("si, sigue por el paso b", "voz")]
        assert bucle.sesion.mandados == ["si, sigue por el paso b"]

    def test_una_orden_SOBRE_jarvis_tambien_se_ve(self, bucle):
        """"abrete" y "apagate" no llegan a mandarse nunca, y son justo
        donde una mala transcripcion se nota mas: el 27 se dijo "abrete"
        y llego "abritin". Anunciar solo lo que se manda las dejaba
        invisibles."""
        anunciados = self._espia(bucle)
        bucle.gestos = Gestos(mostrar=lambda: None)
        bucle.stt = STTPostizo(oido("abrete"))
        bucle._al_despertar(activacion=None)
        assert anunciados == [("abrete", "voz")]
        assert bucle.sesion.mandados == []

    def test_el_RITUAL_no_se_pinta_como_tuyo(self, bucle, monkeypatch, tmp_path):
        """>>> LO CORRIGIO EL USUARIO VIENDOLO (2026-08-27) <<<
        El flujo le parecio el correcto; lo que no cuadraba es que la
        frase del ritual salia atribuida a el. Dijo "continua con el
        proyecto redactor" y en pantalla salio "tu (voz): hola, en que
        nos quedamos?".

        El ritual se manda igual -- eso no cambia --, pero se anuncia con
        su propio origen y NO mueve la barra de TAREA: la barra existe
        para comprobar que se te entendio, y una frase nuestra ahi no
        comprueba nada.
        """
        import nucleo.proyectos as mod
        from voz.proyecto import PRIMERA_PREGUNTA

        carpeta = tmp_path / "Delta"
        carpeta.mkdir()
        # >>> SE PARCHEA `intercepta` Y NO `por_voz` (2026-09-03) <<<
        # El interruptor cambio de nombre al empezar a gobernar
        # tambien la consola. `por_voz` sigue existiendo como alias,
        # pero parchearlo NO haria nada: quien lo consulta es
        # `voz.proyecto.atender`, y llama al nuevo.
        monkeypatch.setattr(mod, "intercepta", lambda config_dir=None: True)
        monkeypatch.setattr(
            mod, "leer",
            lambda config_dir=None: (mod.Proyecto("redactor", str(carpeta)),))

        anunciados = self._espia(bucle)
        bucle.sesion.cambiar_a = lambda r, modo_permisos=None: None
        bucle.stt = STTPostizo(oido("continua con el proyecto redactor"))
        bucle._al_despertar(activacion=None)

        assert anunciados == [
            ("continua con el proyecto redactor", "voz"),
            (PRIMERA_PREGUNTA, "ritual"),
        ]
        # La barra se queda con LO QUE DIJO EL USUARIO, no con el ritual.
        assert bucle.tarea.tarea == "continua con el proyecto redactor"
        assert bucle.sesion.mandados == [PRIMERA_PREGUNTA]

    def test_una_consola_que_falla_no_impide_hablarle(self, bucle):
        def revienta(_t, _o):
            raise RuntimeError("la pagina se fue")

        bucle.anunciar_turno = revienta
        bucle.stt = STTPostizo(oido("sigue con lo tuyo"))
        bucle._al_despertar(activacion=None)
        assert bucle.sesion.mandados == ["sigue con lo tuyo"]

    def test_no_se_anuncia_lo_que_no_se_entendio(self, bucle):
        """Falla cerrado: si no hay orden de la que fiarse, tampoco se
        pinta como si la hubieras dado."""
        anunciados = self._espia(bucle)
        bucle.stt = STTPostizo(oido("ruido", hay_habla_vad=False))
        bucle._al_despertar(activacion=None)
        assert anunciados == []


# --- EL "PARA" TIENE QUE CALLAR LA VOZ (2026-08-29) ----------------------
#
# >>> LO REPORTO EL USUARIO USANDOLO <<<
#     dijo que al pedir "para" a veces la voz se quedaba recitando
#     aunque el trabajo ya se hubiera detenido
#
# Y no era "a veces": la cancelacion NO FUNCIONABA NUNCA. Medido con
# `python -m eval.sonda_parar_la_voz`:
#
#     la bandera de callar vivia     0,0082 ms  (mediana de 200)
#     el callback de PortAudio mira  cada ~90 ms
#     probabilidad de que la viera   ~0,009 %
#
# El codigo era `_callar.set()` / `interrumpir()` / `_callar.clear()`, e
# `interrumpir` solo escribe una linea en la tuberia y vuelve -- no
# espera el ack. O sea que la bandera se ponia y se quitaba dentro del
# mismo microsegundo, y quien la mira mientras suena el audio es el
# callback de audio. El turno se paraba de verdad; la voz llegaba entera
# hasta el final.
#
# >>> Y POR QUE LA SUITE ESTUVO VERDE CON ESTO DENTRO DESDE EL 25 <<<
# Porque `TTSPostizo` vuelve AL INSTANTE y solo apunta si le pasaron un
# `cancelar`. Un doble que no tarda no puede ver una bandera que dura
# microsegundos: comprobaba que existe el cable, no que corte. De ahi el
# doble de abajo, que POLEA como el de verdad.


class TTSQuePolea:
    """Un TTS que mira `cancelar` cada tanto, como el de produccion.

    >>> ESTE ES EL PUNTO DEL DOBLE, Y NO ES UN DETALLE <<<
    `voz/tts.py` mira la bandera en el callback de PortAudio y entre
    trozo y trozo de sintesis, o sea CADA TANTO y no continuamente. Un
    doble instantaneo convierte cualquier `set()`/`clear()` en una
    cancelacion perfecta y deja pasar justo el fallo que hubo.
    """

    PERIODO_S = 0.01
    """Mas fino que los ~90 ms reales para que el test sea rapido. Lo
    que importa no es el valor: es que NO sea cero."""

    def __init__(self, duracion_s: float = 0.25) -> None:
        self.duracion_s = duracion_s
        self.empezadas: list[str] = []
        self.cortadas: list[str] = []
        self.completas: list[str] = []

    @property
    def dicho(self) -> list[str]:
        return self.empezadas

    def hablar(self, texto: str, dispositivo=None, cancelar=None) -> None:
        self.empezadas.append(texto)
        fin = time.monotonic() + self.duracion_s
        while time.monotonic() < fin:
            if cancelar is not None and cancelar.is_set():
                self.cortadas.append(texto)
                return
            time.sleep(self.PERIODO_S)
        self.completas.append(texto)


def _hablando(tts: TTSQuePolea, cuantas: int = 1, limite: float = 2.0) -> None:
    """Espera a que la frase haya EMPEZADO a sonar de verdad."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        if len(tts.empezadas) >= cuantas:
            return
        time.sleep(0.005)
    raise AssertionError("la frase no llego a empezar")


@pytest.fixture
def bucle_que_suena(bucle) -> Bucle:
    bucle.tts = TTSQuePolea()
    return bucle


class TestElParaCallaLaVozQueYaSuena:
    """>>> LA MITAD QUE FALTABA DEL "PARA" <<<

    JC-0011 dice que parar tiene que cortar la frase A MITAD, porque es
    la forma mas visible que tiene un asistente por voz de obedecer.
    """

    def test_la_frase_en_curso_SE_CORTA(self, bucle_que_suena):
        """El fallo que reporto el usuario, en un test.

        Con el codigo de antes esto se queda en `completas`: la bandera
        se quitaba antes de que el que reproduce llegara a mirarla.
        """
        b = bucle_que_suena
        hilo = threading.Thread(
            target=b.decir, args=("una respuesta larguisima",), daemon=True)
        hilo.start()
        _hablando(b.tts)

        b._parar_el_turno()
        hilo.join(timeout=3.0)

        assert "una respuesta larguisima" in b.tts.cortadas
        assert "una respuesta larguisima" not in b.tts.completas

    def test_la_bandera_se_SUSTITUYE_y_no_se_limpia(self, bucle_que_suena):
        """La que se quedo cancelando la frase vieja tiene que seguir
        puesta PARA SIEMPRE: si se limpiara, el que reproduce podria
        mirarla despues y no ver nada, que es lo que pasaba."""
        b = bucle_que_suena
        vieja = b._callar
        b._parar_el_turno()

        assert vieja.is_set(), "la bandera vieja dejo de cancelar"
        assert b._callar is not vieja, "no se estreno bandera"
        assert not b._callar.is_set(), "la nueva nace puesta y calla todo"


class TestElParaCallaLoQueVENIA:
    """Cortar la frase en curso, solo, no basta: adelanta la siguiente."""

    def test_lo_que_quedaba_en_el_buzon_SE_TIRA(self, bucle_que_suena):
        """Al parar puede haber varios eventos ya encolados. Sin tirarlos,
        Jarvis sigue narrando un trabajo que ya no existe."""
        b = bucle_que_suena
        b._buzon.put(_herramienta())
        b._buzon.put(_herramienta())

        b._parar_el_turno()

        assert b._buzon.empty()
        assert b.cuenta.tirado_al_parar == 2

    def test_despues_de_parar_NO_se_dice_nada_mas_del_turno(
            self, bucle_que_suena):
        """La guarda vive en `decir`, que es por donde pasan los siete
        caminos que hablan. En cada sitio por separado, basta con que uno
        se olvide."""
        b = bucle_que_suena
        b._parar_el_turno()
        dichas = len(b.tts.empezadas)

        b.decir("el resto de la respuesta")
        b.decir("y la coletilla")

        assert len(b.tts.empezadas) == dichas
        assert b.cuenta.callado_por_parada == 2

    def test_la_narracion_tampoco(self, bucle_que_suena):
        b = bucle_que_suena
        b._parar_el_turno()
        dichas = len(b.tts.empezadas)

        b._reaccionar(_texto("Ahora verifico el dato."))
        b._reaccionar(_herramienta())

        assert len(b.tts.empezadas) == dichas


class TestLoQueSISeDice:
    def test_la_confirmacion_se_dice_PESE_a_la_parada(self, bucle_que_suena):
        """Un "para" mudo y un cuelgue se oyen igual. Es lo UNICO que se
        dice de un turno parado, y por eso lleva permiso explicito."""
        b = bucle_que_suena
        b._parar_el_turno()
        assert "paro" in " ".join(b.tts.empezadas).lower()

    def test_un_SEGUNDO_para_corta_tambien_la_confirmacion(
            self, bucle_que_suena):
        """La confirmacion sale con la bandera NUEVA, no sin bandera: si
        saliera sin ella, seria la unica frase del sistema que no se
        puede callar."""
        b = bucle_que_suena
        hilo = threading.Thread(target=b._parar_el_turno, daemon=True)
        hilo.start()
        _hablando(b.tts)

        b._callar.set()          # el segundo "para"
        hilo.join(timeout=3.0)

        assert b.tts.cortadas, "la confirmacion no se pudo cortar"


class TestVolverAHablar:
    """El silencio de una parada dura hasta que el usuario vuelve a
    hablar. Ni menos -- se colaba la respuesta -- ni mas, que dejaria a
    Jarvis mudo para siempre."""

    def test_una_orden_nueva_levanta_el_silencio(self, bucle_que_suena):
        b = bucle_que_suena
        b._parar_el_turno()
        assert b._parado.is_set()

        b._anunciar("mira otra vez el changelog", "voz")

        assert not b._parado.is_set()
        b.decir("vale, lo miro")
        assert "vale, lo miro" in b.tts.empezadas

    def test_tambien_por_la_VENTANA_DE_SEGUIMIENTO(self, bucle_que_suena):
        """>>> EL CAMINO QUE YA SE ESCAPO UNA VEZ, EL 27 <<<
        Contestar sin decir "hey jarvis" NO pasa por `_mandar`. Poner ahi
        el reseteo habria dejado a Jarvis mudo justo en el camino mas
        comun de la conversacion (JC-0012). Por eso vive en `_anunciar`,
        que es el punto que comparten los tres.
        """
        b = bucle_que_suena
        b._parar_el_turno()
        b._anunciar("mejor haz lo otro", "voz")   # lo que hace esa ventana
        assert not b._parado.is_set()

    def test_una_frase_VACIA_no_levanta_el_silencio(self, bucle_que_suena):
        """`_anunciar` se llama tambien cuando no se entendio nada, y una
        ventana vacia no es haber vuelto a hablar."""
        b = bucle_que_suena
        b._parar_el_turno()
        b._anunciar("   ", "voz")
        assert b._parado.is_set()


class TestLoQueDejoSeDiceEnAltoPeroSoloUnaVez:
    """>>> LA MITAD HABLADA DEL PANEL, Y SU FILTRO <<<

    El usuario pidio el 2026-09-01 que la voz mencionara lo que dejo, no
    solo que lo pintara la pantalla. Pero Claude ya suele decir "he
    creado resumen.md" el solo -- y con el preambulo puesto lo hace mas
    --, asi que anadir "te he dejado resumen.md" detras seria decirlo dos
    veces seguidas. En una pantalla eso se perdona; en un altavoz se nota
    muchisimo, porque no puedes saltartelo con la vista.
    """

    def _con_piezas(self, bucle, nombres, imagen=False):
        from puente.producido import Producido
        from puente.protocolo import Imagen, ResultadoHerramienta, UsoHerramienta

        p = Producido()
        for i, nombre in enumerate(nombres):
            p.ve(UsoHerramienta(id_uso=f"u{i}", herramienta="Write",
                                entrada={"file_path": f"C:/x/{nombre}"}))
            p.ve(ResultadoHerramienta(id_uso=f"u{i}", contenido="",
                                      es_error=False))
        if imagen:
            import base64
            datos = base64.b64encode(b"bytes").decode()
            p.ve(ResultadoHerramienta(id_uso="ui", contenido="", es_error=False,
                                      imagenes=(Imagen(tipo="image/png",
                                                       datos=datos),)))
        # La consola alimenta esto ANTES de avisar a la voz, asi que
        # cuando la voz habla el turno ya cerro: `turno - 1`.
        p.turno = 1
        bucle.producido = p
        return p

    def test_lo_menciona(self, bucle):
        self._con_piezas(bucle, ["resumen.md"])
        bucle._menciona_lo_que_dejo("Ya esta hecho.")
        assert any("resumen.md" in d for d in bucle.tts.dicho)
        assert bucle.cuenta.piezas_mencionadas == 1

    def test_NO_lo_repite_si_la_respuesta_ya_lo_nombro(self, bucle):
        """El filtro. Sin el, el usuario oye el nombre dos veces."""
        self._con_piezas(bucle, ["resumen.md"])
        bucle._menciona_lo_que_dejo("He creado resumen.md con el resumen.")
        assert bucle.tts.dicho == []
        assert bucle.cuenta.piezas_mencionadas == 0

    def test_con_varios_dice_cuantos_y_uno(self, bucle):
        """Recitar ocho nombres de archivo en alto no informa a nadie. Es
        la misma regla que `voz/resumen.py` aplica a una lista."""
        self._con_piezas(bucle, ["a.md", "b.py", "c.json"])
        bucle._menciona_lo_que_dejo("Listo.")
        dicho = " ".join(bucle.tts.dicho)
        assert "3" in dicho and "a.md" in dicho
        assert "b.py" not in dicho

    def test_una_imagen_no_se_nombra_por_su_archivo(self, bucle):
        """Vive en memoria y su nombre es inventado por nosotros
        (`vista_1.png`). Decirlo en alto seria dar un dato falso: no hay
        ningun archivo que buscar con ese nombre."""
        self._con_piezas(bucle, [], imagen=True)
        bucle._menciona_lo_que_dejo("Ya lo tienes.")
        dicho = " ".join(bucle.tts.dicho)
        assert dicho and "vista_" not in dicho

    def test_tras_un_para_no_dice_nada(self, bucle):
        """Hablar despues de un "para" es exactamente lo que JC-0011
        paso tres fugas arreglando."""
        self._con_piezas(bucle, ["resumen.md"])
        bucle._callar.set()
        bucle._menciona_lo_que_dejo("Ya esta.")
        assert bucle.tts.dicho == []

    def test_sin_panel_no_menciona_nada(self, bucle):
        """`None` es una sesion montada a mano, sin consola."""
        bucle.producido = None
        bucle._menciona_lo_que_dejo("Ya esta.")
        assert bucle.tts.dicho == []
