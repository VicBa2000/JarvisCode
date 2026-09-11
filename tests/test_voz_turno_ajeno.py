"""Un turno que NO abrio la voz tambien se locuta (2026-08-29).

>>> EL FALLO QUE ESTOS TESTS CIERRAN, Y COMO SE VIO <<<
Lo reporto el usuario probando JC-0016: contesto una pregunta desde el
movil, Claude Code respondio *"Entendido, no arranco con core/memory/"*,
y NO sono. Sono despues, cuando el ya estaba hablando de otra cosa -- o
sea que no llegaba solo tarde, llegaba FUERA DE ORDEN.

La causa no estaba en Telegram: al ciclo de JC-0011 solo se llegaba a
TRABAJANDO por el camino de la voz, asi que un turno lanzado desde el
movil o desde la consola dejaba el ciclo en DORMIDO y
`preparar_respuesta()` -- que EXIGE TRABAJANDO -- moria con un
`CicloError` que `_atender_buzon` se tragaba con un `continue` sin
contador y sin log.

>>> POR QUE LA SUITE LLEVABA VERDE CON ESTO <<<
Porque los tests de la puerta y de la respuesta ponian el estado A MANO
(`bucle.ciclo.estado = Estado.TRABAJANDO`) antes de llamar a
`_reaccionar`, que es lo que hace la voz y NO lo que hace un turno ajeno.
Aqui NO se toca el estado: se deja DORMIDO, que es como llega de verdad.
Pariente de la leccion de las capturas del 29 -- una suite verde no dice
que la pantalla este bien, y tampoco que el altavoz suene.

Los eventos salen de `eval/trazas_claude_code/*.jsonl`.
"""

from __future__ import annotations

import time

import pytest

from puente.protocolo import Pregunta, Puerta, UsoHerramienta, interpretar
from voz.ciclo import Estado


# --------------------------------------------------------------------
# El mismo montaje que `test_voz_bucle`: postizo solo lo que toca el mundo
# --------------------------------------------------------------------

@pytest.fixture
def bucle():
    from tests.test_voz_bucle import (Ciclo, Senales, SesionPostiza,
                                      STTPostizo, TTSPostizo)
    from voz.bucle import Bucle

    b = Bucle(sesion=SesionPostiza(), ciclo=Ciclo(senales=Senales()),
              tts=TTSPostizo(), stt=STTPostizo(), micro=object(),
              altavoz=None)
    b.ciclo.respiro_s = 0.0
    return b


def eventos_de(project_root, nombre: str):
    ruta = project_root / "eval" / "trazas_claude_code" / f"{nombre}.jsonl"
    if not ruta.is_file():
        pytest.skip(f"falta la traza {nombre}.jsonl")
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        yield from interpretar(linea)


def fin_de(project_root, nombre: str):
    from puente.protocolo import Fin

    fines = [e for e in eventos_de(project_root, nombre)
             if isinstance(e, Fin)]
    assert fines, f"la traza {nombre} tenia que cerrar con un Fin"
    return fines[0]


def dicho(texto: str):
    from tests.test_voz_bucle import oido

    return oido(texto)


def primer_texto_de(project_root, nombre: str):
    """El primer `Texto` de una traza real, que es lo primero que llega.

    Antes que cualquier herramienta y antes que el `Fin`: es el evento
    con el que la pantalla puede dejar de decir DORMIDO.
    """
    from puente.protocolo import Texto

    textos = [e for e in eventos_de(project_root, nombre)
              if isinstance(e, Texto)]
    assert textos, f"la traza {nombre} tenia que traer algun Texto"
    return textos[0]


def con_puerta(project_root, bucle):
    """La puerta REAL con su `Decision` REAL, como la monta la sesion."""
    from puente.politica import decidir
    from puente.sesion import Pendiente

    puertas = [e for e in eventos_de(project_root, "denegada")
               if isinstance(e, Puerta)]
    assert puertas, "la traza tenia que traer al menos una puerta"
    puerta = puertas[0]
    decision = decidir(puerta, directorio_sesion=bucle.sesion.directorio)
    bucle.sesion.pendientes = (
        Pendiente(evento=puerta, decision=decision, pedido_en=0.0),)
    return puerta


# --------------------------------------------------------------------

class TestLaRespuestaDeUnTurnoAjenoSeLocuta:
    """Lo que el usuario no oyo. Contra las trazas de disco."""

    def test_el_ciclo_estaba_DORMIDO_y_asi_es_como_llega(self, bucle):
        """La premisa, dicha en un test: nadie llamo a `desperto()`.

        Si esto dejara de ser verdad, el resto del archivo estaria
        probando el camino de la voz otra vez y no se notaria.
        """
        assert bucle.ciclo.estado is Estado.DORMIDO

    @pytest.mark.parametrize("traza", [
        "denegada", "permitida", "pregunta", "pregunta_con_cierre",
        "pregunta_en_prosa", "respuesta_larga",
    ])
    def test_se_dice_la_respuesta_de_un_turno_que_no_abrio_la_voz(
            self, project_root, bucle, traza):
        """SEIS DE LAS OCHO TRAZAS NO DECIAN NADA antes de esto.

        Las otras dos no estan aqui porque su silencio es CORRECTO, y se
        prueban aparte: un turno parado ya dijo "vale, paro", y uno sin
        red vuelve ANTES de pedirle el estado al ciclo -- que es
        exactamente por lo que aquel si se oia y la respuesta buena no.
        """
        bucle.seguimiento = False
        bucle.recibir(fin_de(project_root, traza))
        bucle._atender_buzon()

        assert bucle.tts.dicho, "la respuesta se perdio en silencio"
        assert bucle.cuenta.respuestas_locutadas == 1
        assert bucle.cuenta.eventos_tirados == 0

    def test_un_turno_ajeno_se_cuenta_aparte_del_de_la_voz(self, project_root,
                                                           bucle):
        """`ordenes_mandadas` cuenta lo que se pidio hablando; esto, lo
        que entro desde fuera. Una sola cifra no distinguiria "no se usa
        Telegram" de "Telegram no llega al altavoz"."""
        bucle.seguimiento = False
        bucle.recibir(fin_de(project_root, "permitida"))
        bucle._atender_buzon()

        assert bucle.cuenta.turnos_ajenos == 1
        assert bucle.ciclo.cuenta.ajenos == 1
        assert bucle.cuenta.ordenes_mandadas == 0
        assert bucle.ciclo.cuenta.ciclos == 0, (
            "un turno ajeno no dice la palabra de activacion: contarlo "
            "como ciclo diluiria la tasa del wake word")

    def test_un_turno_ajeno_PARADO_sigue_sin_decir_nada(self, project_root,
                                                        bucle):
        """El silencio correcto: ya se dijo "vale, paro" al pararlo."""
        bucle.recibir(fin_de(project_root, "parada"))
        bucle._atender_buzon()

        assert bucle.tts.dicho == []
        assert bucle.ciclo.estado is Estado.DORMIDO


class TestElMicrofonoDuranteUnTurnoAjeno:
    """Adoptar el turno mueve el microfono, y eso hay que decirlo."""

    def test_mientras_corre_un_turno_ajeno_se_oyen_las_PARADAS(
            self, project_root, bucle):
        """>>> ES LA MITAD QUE MAS IMPORTA DE ADOPTAR EL TURNO <<<
        Un turno lanzado desde el movil actua sobre la MISMA PC. Con el
        ciclo DORMIDO, `escucha_paradas` esta apagado y "para" no se
        oiria mientras un agente capaz borra algo.
        """
        herramientas = [e for e in eventos_de(project_root, "permitida")
                        if isinstance(e, UsoHerramienta)]
        assert herramientas, "la traza tenia que traer una herramienta"
        assert not bucle.ciclo.escucha_paradas

        bucle.recibir(herramientas[0])
        bucle._atender_buzon()

        assert bucle.ciclo.estado is Estado.TRABAJANDO
        assert bucle.ciclo.escucha_paradas
        assert not bucle.ciclo.escucha_la_palabra

    def test_una_PUERTA_de_un_turno_ajeno_abre_el_microfono(self,
                                                            project_root,
                                                            bucle):
        """>>> NO ERA SOLO LA RESPUESTA: ERA TAMBIEN LA PUERTA <<<
        `Ciclo.pregunto()` exige TRABAJANDO igual que
        `preparar_respuesta()`, y `_anunciar_puerta` se traga esa
        excepcion y vuelve. O sea que una puerta de un turno ajeno se
        locutaba y despues NO escuchaba: el usuario oia "¿lo autorizo?"
        y le hablaba a un sordo. Y es el sitio donde se CONSIENTE.
        """
        from tests.test_voz_bucle import STTPostizo

        puerta = con_puerta(project_root, bucle)
        bucle.stt = STTPostizo(dicho("si"))

        bucle.recibir(puerta)
        bucle._atender_buzon()

        assert bucle.stt.turnos == 1, "no llego a escuchar la respuesta"
        assert bucle.sesion.respondidas == [(puerta.id_peticion, True, {})]
        assert bucle.cuenta.permisos_dados == 1

    def test_una_PREGUNTA_de_un_turno_ajeno_abre_el_microfono(self,
                                                              project_root,
                                                              bucle):
        from tests.test_voz_bucle import STTPostizo

        preguntas = [e for e in eventos_de(project_root, "pregunta")
                     if isinstance(e, Pregunta)]
        assert preguntas, "la traza tenia que traer una pregunta"
        pregunta = preguntas[0]
        opciones = bucle._opciones_de(pregunta)
        assert opciones, "sin opciones esto no probaria lo que dice"
        bucle.stt = STTPostizo(dicho(opciones[0]))

        bucle.recibir(pregunta)
        bucle._atender_buzon()

        assert bucle.stt.turnos == 1, "no llego a escuchar la respuesta"
        assert bucle.cuenta.preguntas_contestadas == 1


class TestLoQueSeTragaElBuzonSeCuenta:
    """(a) del plan: sin contador, el proximo fallo tambien sera mudo."""

    def test_una_reaccion_rota_se_cuenta_y_deja_rastro(self, project_root,
                                                       bucle):
        """Hasta el 2026-08-29 esto era un `continue` a secas, y por ahi
        se colo el fallo entero sin dejar una sola linea."""
        def revienta(_evento):
            raise RuntimeError("el altavoz se fue")

        bucle._reaccionar = revienta
        bucle.recibir(fin_de(project_root, "permitida"))
        bucle._atender_buzon()

        assert bucle.cuenta.eventos_tirados == 1
        assert "Fin" in bucle.ultimo_fallo
        assert "el altavoz se fue" in bucle.ultimo_fallo

    def test_un_fallo_locutando_no_se_lleva_el_bucle_por_delante(
            self, project_root, bucle):
        """Lo que el `except` protegia de verdad, y sigue protegiendo: el
        usuario se quedaria sin voz Y sin saberlo."""
        primero = fin_de(project_root, "permitida")
        segundo = fin_de(project_root, "denegada")
        real = bucle._reaccionar

        def a_veces(evento):
            if evento is primero:
                raise RuntimeError("boom")
            return real(evento)

        bucle.seguimiento = False
        bucle._reaccionar = a_veces
        bucle.recibir(primero)
        bucle.recibir(segundo)
        bucle._atender_buzon()

        assert bucle.cuenta.eventos_tirados == 1
        assert bucle.tts.dicho, "el segundo evento tenia que atenderse igual"


class TestElBuzonSeDrenaSinEsperarLaRondaDelWake:
    """(c) del plan: la ronda del wake dura 30 s y ahi nadie drenaba."""

    def test_recibir_avisa_al_hilo_de_la_voz(self, project_root, bucle):
        assert not bucle._hay_correo.is_set()
        bucle.recibir(fin_de(project_root, "permitida"))
        assert bucle._hay_correo.is_set()

    def test_la_ronda_de_la_palabra_se_suelta_si_hay_correo(self,
                                                            project_root,
                                                            bucle):
        """>>> LA RONDA SON 30 s Y NO SE BAJAN <<<
        Ese numero lo fija que abrir y cerrar el `InputStream` cuesta
        44 ms medidos, y en ese hueco Jarvis es sordo. Asi que la ronda
        se SUELTA, que es el mismo patron que JC-0014 con el microfono.
        """
        class WakePostizo:
            """Como el de verdad: mira `cancelar` en cada vuelta.

            Un doble que vuelve al instante no tendria nunca una ronda EN
            VUELO, que es justo lo que hay que atravesar -- es la leccion
            de `TTSQuePolea` del 29.
            """

            def __init__(self) -> None:
                self.rondas = 0
                self.soltadas = 0

            def escuchar(self, dispositivo, limite_s=None, cancelar=None):
                self.rondas += 1
                fin = time.monotonic() + 1.0
                while time.monotonic() < fin:
                    if cancelar is not None and cancelar.is_set():
                        self.soltadas += 1
                        return
                    time.sleep(0.005)
                return
                yield  # pragma: no cover - el generador nunca activa

        bucle.wake = WakePostizo()
        bucle.recibir(fin_de(project_root, "permitida"))

        empezo = time.monotonic()
        bucle._esperar_la_palabra()
        tardo = time.monotonic() - empezo

        assert bucle.wake.soltadas == 1
        assert tardo < 0.5, f"la ronda no se solto: tardo {tardo:.2f} s"

    def test_la_bandera_se_limpia_al_EMPEZAR_a_drenar(self, project_root,
                                                      bucle):
        """Al reves se perderia el aviso de lo que llega DURANTE el
        drenaje, y ese evento esperaria la ronda entera."""
        fin = fin_de(project_root, "permitida")
        visto = []

        def y_llega_otro(evento):
            if not visto:
                visto.append(evento)
                bucle.recibir(fin)   # llega mientras se esta drenando

        bucle._reaccionar = y_llega_otro
        bucle.recibir(fin)
        bucle._atender_buzon()

        assert bucle._hay_correo.is_set(), (
            "el evento que llego durante el drenaje se quedo sin avisar")


class TestUnFinViejoNoSeLocutaEnMitadDeOtroTurno:
    """(d) del plan, y es una DECISION: se tira, y se cuenta."""

    def test_abrir_un_turno_hablando_tira_lo_que_quedaba(self, project_root,
                                                         bucle):
        bucle.recibir(fin_de(project_root, "respuesta_larga"))
        bucle._mandar("y ahora mirame otra cosa")

        assert bucle.cuenta.tirado_al_abrir_turno == 1
        assert bucle.sesion.mandados == ["y ahora mirame otra cosa"]

        bucle._atender_buzon()
        assert bucle.tts.dicho == [], (
            "se dijo la respuesta de hace dos turnos encima del nuevo")

    def test_la_ventana_de_seguimiento_tambien_lo_tira(self, project_root,
                                                       bucle):
        """>>> ESTE CAMINO NO PASA POR `_mandar` <<<
        Es el mismo sitio que ya se escapo el 2026-08-27 con el anuncio
        del turno, y es el camino MAS COMUN de la conversacion (JC-0012).
        """
        from tests.test_voz_bucle import STTPostizo

        bucle.stt = STTPostizo(dicho("pues mira el otro archivo"))
        bucle.ciclo.estado = Estado.HABLANDO
        bucle.recibir(fin_de(project_root, "respuesta_larga"))

        bucle._ventana_de_seguimiento(tras_pregunta=True)

        assert bucle.cuenta.tirado_al_abrir_turno == 1
        assert bucle.sesion.mandados == ["pues mira el otro archivo"]

    def test_contestar_una_puerta_NO_tira_nada(self, project_root, bucle):
        """Una puerta se contesta con `responder` y el turno SIGUE VIVO:
        lo que haya en el buzon es de ese mismo turno, no de uno viejo.
        Tirarlo ahi seria comerse la narracion de lo que se acaba de
        autorizar."""
        from tests.test_voz_bucle import STTPostizo

        puerta = con_puerta(project_root, bucle)
        bucle.stt = STTPostizo(dicho("si"))
        bucle.ciclo.estado = Estado.TRABAJANDO

        bucle._anunciar_puerta(puerta)

        assert bucle.cuenta.tirado_al_abrir_turno == 0


class TestLaGuardaDeTrabajoAjeno:
    """El False de `trabajo_ajeno`: no robarle el estado a quien dicta."""

    @pytest.mark.parametrize("estado", [Estado.AVISANDO, Estado.ESCUCHANDO])
    def test_no_se_adopta_mientras_el_usuario_dicta(self, project_root,
                                                    bucle, estado):
        bucle.ciclo.estado = estado
        bucle.recibir(fin_de(project_root, "permitida"))
        bucle._atender_buzon()

        assert bucle.ciclo.estado is estado
        assert bucle.cuenta.eventos_fuera_de_turno == 1
        assert bucle.tts.dicho == []

    @pytest.mark.parametrize("estado", [Estado.TRABAJANDO, Estado.HABLANDO,
                                        Estado.PREGUNTANDO])
    def test_un_turno_que_ya_era_nuestro_no_se_recuenta(self, bucle, estado):
        bucle.ciclo.estado = estado

        assert bucle.ciclo.trabajo_ajeno() is True
        assert bucle.ciclo.estado is estado
        assert bucle.ciclo.cuenta.ajenos == 0


class TestAdoptarNoPuedeDEJARColgadoElCiclo:
    """El hueco que aparecio construyendo, y es el peor de los posibles.

    >>> UN CICLO ATASCADO EN TRABAJANDO ES SORDERA TOTAL Y MUDA <<<
    Con el ciclo en TRABAJANDO, `escucha_la_palabra` esta apagado: el
    wake word no vuelve a abrir nada NUNCA, y no hay ningun sintoma. La
    primera version de `_reaccionar` adoptaba con cualquier evento, y un
    `Limite` o un `Reintento` que llegue DETRAS de un `Fin` -- o sea con
    el ciclo ya devuelto a DORMIDO -- lo habria dejado asi para siempre.
    """

    def test_un_LIMITE_suelto_no_deja_el_ciclo_trabajando(self, bucle):
        from puente.protocolo import Limite

        agotado = Limite(estado="rejected", tipo="seven_day",
                         utilizacion=1.0)
        assert agotado.agotado, "el doble tenia que estar agotado"
        bucle._reaccionar(agotado)

        assert bucle.ciclo.estado is Estado.DORMIDO, (
            "un evento que no abre turno dejo el ciclo trabajando: el wake "
            "word ya no vuelve a abrir nada")
        assert bucle.tts.dicho, "y aun asi el aviso tiene que decirse"

    def test_un_REINTENTO_suelto_tampoco(self, bucle):
        from puente.protocolo import Reintento

        bucle._reaccionar(Reintento(intento=1, intentos_maximos=10,
                                    espera_ms=523))

        assert bucle.ciclo.estado is Estado.DORMIDO
        assert bucle.tts.dicho

    def test_despues_de_un_FIN_el_ciclo_vuelve_a_oir_la_palabra(
            self, project_root, bucle):
        """La otra mitad: los cuatro que SI adoptan tienen quien los
        cierre. `_al_terminar` llama a `termino()` en sus cinco salidas."""
        bucle.seguimiento = False
        bucle.recibir(fin_de(project_root, "permitida"))
        bucle._atender_buzon()

        assert bucle.ciclo.estado is Estado.DORMIDO
        assert bucle.ciclo.escucha_la_palabra


class TestElEstadoDespiertaConElPRIMERTexto:
    """El sintoma del 2026-09-04, reportado por el usuario.

    >>> Dando la instruccion escrita, el estado seguia diciendo DORMIDO
    con Jarvis ya trabajando. <<<

    La causa: la adopcion miraba `UsoHerramienta` como primer evento, y
    HAY TURNOS QUE NO GASTAN NI UNA HERRAMIENTA. Medido sobre los 134
    turnos reales de `logs/puente/`: **58 (43 %) no usan ninguna**, o sea
    que casi la mitad de lo que se escribe en la consola enseñaba DORMIDO
    de principio a fin, mintiendo sobre lo unico que esa casilla existe
    para decir. Con `Texto` dentro bajan a 6 (4 %) -- los que no dicen
    nada en absoluto, y a esos los adopta el `Fin`.

    `respuesta_larga` es justo ese caso en disco: 1 Texto, 0 usos.
    """

    def test_un_TEXTO_solo_ya_despierta_el_ciclo(self, project_root, bucle):
        """El test que falla sin el arreglo.

        Antes del 2026-09-04 `_reaccionar` devolvia con el `Texto` ANTES
        de llegar al bloque de adopcion, asi que esto se quedaba DORMIDO.
        """
        assert bucle.ciclo.estado is Estado.DORMIDO, "la premisa"

        bucle.recibir(primer_texto_de(project_root, "respuesta_larga"))
        bucle._atender_buzon()

        assert bucle.ciclo.estado is Estado.TRABAJANDO, (
            "llego texto de Claude Code y la pantalla seguia diciendo "
            "DORMIDO: es el sintoma que reporto el usuario")
        assert bucle.cuenta.turnos_ajenos == 1
        assert bucle.cuenta.eventos_tirados == 0

    def test_y_el_TEXTO_sigue_sin_locutarse_al_llegar(self, project_root,
                                                      bucle):
        """Despierta y calla, que son dos cosas distintas.

        Un `Texto` no se juzga al llegar -- es narracion si detras viene
        una herramienta y es LA RESPUESTA si detras viene `Fin` --, asi
        que decirlo aqui diria la respuesta DOS VECES. Lo unico que
        aporta es que la pantalla deje de mentir mientras se decide.
        """
        bucle.recibir(primer_texto_de(project_root, "respuesta_larga"))
        bucle._atender_buzon()

        assert bucle.tts.dicho == [], (
            "el texto se locuto al llegar: la respuesta se dira dos veces")

    def test_un_turno_SIN_herramientas_no_pasa_entero_en_DORMIDO(
            self, project_root, bucle):
        """El turno completo, en el orden en que llega de verdad.

        Es el 43 % de los turnos reales, y era el caso que no se veia:
        entre el Enter y el `Fin` la casilla no cambiaba nunca.
        """
        bucle.seguimiento = False
        bucle.recibir(primer_texto_de(project_root, "respuesta_larga"))
        bucle._atender_buzon()
        durante = bucle.ciclo.estado

        bucle.recibir(fin_de(project_root, "respuesta_larga"))
        bucle._atender_buzon()

        assert durante is Estado.TRABAJANDO, "durante el turno"
        assert bucle.ciclo.estado is Estado.DORMIDO, "y al acabar, cerrado"
        assert bucle.ciclo.escucha_la_palabra, (
            "adoptar con el texto dejo el ciclo colgado: sordera total")
        assert bucle.cuenta.turnos_ajenos == 1, (
            "el turno se conto dos veces: una por el texto y otra por el Fin")
        assert bucle.tts.dicho, "y la respuesta se dijo una vez"

    def test_el_TEXTO_no_le_roba_el_turno_a_quien_dicta(self, project_root,
                                                        bucle):
        """La guarda de `trabajo_ajeno`, tambien para el camino nuevo.

        En ESCUCHANDO el usuario esta dictando: un texto que llegue ahi
        no puede adoptar nada, y se cuenta en vez de darse por imposible.
        """
        bucle.ciclo.estado = Estado.ESCUCHANDO

        bucle.recibir(primer_texto_de(project_root, "respuesta_larga"))
        bucle._atender_buzon()

        assert bucle.ciclo.estado is Estado.ESCUCHANDO
        assert bucle.cuenta.eventos_fuera_de_turno == 1
        assert bucle.cuenta.turnos_ajenos == 0
