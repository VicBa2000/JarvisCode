"""Tests de `voz/ciclo.py`: cuando Jarvis escucha y que acepta (JC-0011).

Nada de esto necesita microfono, altavoz ni modelo: la maquina de estados
es la mitad que decide, y decide sobre texto. Los avisos se espian con
una `Senales` sin dispositivo -- que es la de verdad, sintetiza de
verdad, y simplemente no reproduce.

LO QUE ESTOS TESTS PROTEGEN, que es lo que se rompe sin que se note:

  * que un "cancela" dicho a media orden NO se mande a Claude Code COMO
    orden;
  * que estando TRABAJANDO no salga nunca una orden nueva, pase lo que
    pase;
  * que estando TRABAJANDO si salga una parada;
  * que la campana suene ANTES del pitido y con la espera en medio.
"""

from __future__ import annotations

import pytest

from voz.ciclo import RESPIRO_S, Ciclo, CicloError, Estado, Reaccion
from voz.senales import Senales
from voz.stt import Transcripcion


class SenalesEspia(Senales):
    """La `Senales` de verdad, sin altavoz, apuntando lo que sono.

    Se hereda en vez de simularse: asi lo que se prueba es el
    orden en que el ciclo llama a los avisos REALES, no el orden en que
    llama a un doble que podria haber divergido.
    """

    def __post_init__(self) -> None:
        super().__post_init__()
        self.sonaron: list[str] = []

    def campana(self) -> None:
        self.sonaron.append("campana")

    def pitido(self) -> None:
        self.sonaron.append("pitido")


def orden(texto: str, *, hay_habla_vad: bool | None = True) -> Transcripcion:
    """Una transcripcion como la que entrega `voz/stt.py` de verdad."""
    return Transcripcion(
        texto=texto, latencia_s=0.5, duracion_audio_s=2.0,
        prob_sin_habla=0.05, idioma="es", modelo="small",
        hay_habla_vad=hay_habla_vad,
    )


@pytest.fixture
def ciclo() -> Ciclo:
    return Ciclo(senales=SenalesEspia())


def hasta_escuchando(ciclo: Ciclo) -> None:
    ciclo.desperto()
    ciclo.preparar_escucha(dormir=lambda _s: None)


class TestElAviso:
    """UN solo sonido desde el 2026-08-25, y lo cambio el uso.

    JC-0011 habia decidido campana + 2 s + pitido. Usandolo, el veredicto
    del usuario fue que el segundo sobra: con el primero ya se entiende
    que Jarvis te oyo y que escuchara cuando termine de sonar.
    """

    def test_suena_UNO_y_no_dos(self, ciclo):
        ciclo.desperto()
        ciclo.preparar_escucha(dormir=lambda _s: None)
        assert ciclo.senales.sonaron == ["campana"]

    def test_y_se_espera_DESPUES_antes_de_grabar(self, ciclo):
        """`eval/wake_bench.py` ya lo sabia: "si se solapan, la cola del
        aviso entra en el audio". Al montar el ciclo no se copio, y con
        ~380 ms de latencia medidos en el altavoz, cuando `reproducir`
        vuelve el sonido TODAVIA SE ESTA OYENDO: sin este respiro,
        Whisper recibe un tono pegado a la primera silaba."""
        momentos = []
        ciclo.senales.campana = lambda: momentos.append("campana")
        ciclo.desperto()
        ciclo.preparar_escucha(dormir=lambda s: momentos.append(("espera", s)))
        assert momentos == ["campana", ("espera", RESPIRO_S)]

    def test_antes_de_hablar_JARVIS_no_suena_nada(self, ciclo):
        """Con un solo aviso, la campana significa "habla tu". Sonarla
        justo antes de que hable Jarvis invitaria al usuario a hablar
        encima, que es el error que JC-0011 queria evitar cuando pedia
        dos sonidos distintos. Su voz es su propio aviso."""
        hasta_escuchando(ciclo)
        ciclo.oido(orden("abre el bloc de notas"))
        ciclo.senales.sonaron.clear()
        ciclo.preparar_respuesta()
        assert ciclo.senales.sonaron == []
        assert ciclo.estado is Estado.HABLANDO

    def test_el_aviso_no_suena_fuera_de_su_sitio(self, ciclo):
        """Un aviso que puede sonar desde cualquier estado es un aviso
        que acaba sonando solo."""
        with pytest.raises(CicloError):
            ciclo.preparar_escucha(dormir=lambda _s: None)
        with pytest.raises(CicloError):
            ciclo.preparar_respuesta()
        assert ciclo.senales.sonaron == []


class TestCuandoPreguntaJarvis:
    """Lo que pidio el usuario tras usarlo: si el pregunta, la escucha se
    abre sola. Tener que decir "hey jarvis" para contestar convierte una
    conversacion en un formulario."""

    def _preguntando(self, ciclo):
        hasta_escuchando(ciclo)
        ciclo.oido(orden("renombra los archivos de descargas"))
        ciclo.pregunto()
        return ciclo

    def test_se_acepta_habla_SIN_palabra_de_activacion(self, ciclo):
        self._preguntando(ciclo)
        assert ciclo.espera_respuesta is True
        assert ciclo.escucha_la_palabra is False
        assert ciclo.oido(orden("minusculas")) is Reaccion.RESPUESTA
        assert ciclo.cuenta.respuestas == 1

    def test_lo_que_se_dice_ahi_NO_es_una_orden_nueva(self, ciclo):
        """Aunque suene a orden. La sesion ya esta a mitad de un turno y
        lo unico que cabe es contestar lo que se acaba de preguntar."""
        self._preguntando(ciclo)
        assert ciclo.oido(orden("abre el bloc de notas")) is Reaccion.RESPUESTA
        assert ciclo.cuenta.ordenes == 1     # la de antes, no esta

    def test_pero_un_para_sigue_parando(self, ciclo):
        self._preguntando(ciclo)
        assert ciclo.oido(orden("cancela")) is Reaccion.PARAR
        assert ciclo.estado is Estado.DORMIDO

    def test_una_respuesta_que_no_se_entiende_se_cuenta_APARTE(self, ciclo):
        """Un "no te he oido" cuando hablas tu se repite y ya esta; uno
        cuando pregunta Jarvis deja un turno colgado esperando."""
        self._preguntando(ciclo)
        assert ciclo.oido(orden("", hay_habla_vad=False)) is Reaccion.IGNORAR
        assert ciclo.cuenta.sin_responder == 1
        assert ciclo.cuenta.ignorados == 0

    def test_contestada_la_pregunta_el_turno_sigue(self, ciclo):
        self._preguntando(ciclo)
        ciclo.oido(orden("minusculas"))
        ciclo.volver_al_trabajo()
        assert ciclo.estado is Estado.TRABAJANDO
        assert ciclo.escucha_paradas is True

    def test_no_se_puede_preguntar_si_no_hay_turno(self, ciclo):
        """Una escucha abierta sin palabra de activacion solo se
        justifica DENTRO de un turno que el usuario pidio."""
        with pytest.raises(CicloError):
            ciclo.pregunto()

    def test_mientras_espera_respuesta_el_otro_hilo_NO_graba(self, ciclo):
        """Dos grabadores sobre el mismo microfono no son una escucha mas
        atenta: son audio partido en dos."""
        self._preguntando(ciclo)
        assert ciclo.escucha_paradas is False


class TestQueEstaEncendidoEnCadaEstado:
    def test_la_palabra_solo_cuenta_estando_dormido(self, ciclo):
        assert ciclo.escucha_la_palabra is True
        hasta_escuchando(ciclo)
        assert ciclo.escucha_la_palabra is False

    def test_mientras_trabaja_y_mientras_habla_sigue_oyendo_paradas(self, ciclo):
        """Esta es la mitad de JC-0011 que, si falla, falla en silencio y
        con las manos en la masa."""
        hasta_escuchando(ciclo)
        ciclo.oido(orden("borra los temporales de descargas"))
        assert ciclo.estado is Estado.TRABAJANDO
        assert ciclo.escucha_paradas is True
        assert ciclo.acepta_ordenes is False

        ciclo.preparar_respuesta()
        assert ciclo.escucha_paradas is True

    def test_dormido_no_escucha_paradas_porque_no_hay_nada_que_parar(self, ciclo):
        assert ciclo.escucha_paradas is False


class TestLaEscuchaApagada:
    """"Apagada" es apagada para ORDENES NUEVAS, no apagada del todo."""

    def test_trabajando_una_frase_normal_se_tira(self, ciclo):
        hasta_escuchando(ciclo)
        ciclo.oido(orden("organiza mi carpeta de descargas"))
        assert ciclo.oido(orden("abre la calculadora")) is Reaccion.IGNORAR
        assert ciclo.estado is Estado.TRABAJANDO
        assert ciclo.cuenta.ordenes == 1

    def test_trabajando_una_parada_SI_para(self, ciclo):
        hasta_escuchando(ciclo)
        ciclo.oido(orden("borra los archivos temporales de descargas"))
        assert ciclo.oido(orden("para")) is Reaccion.PARAR
        assert ciclo.estado is Estado.DORMIDO
        assert ciclo.cuenta.paradas == 1

    def test_hablando_tambien_se_puede_parar(self, ciclo):
        hasta_escuchando(ciclo)
        ciclo.oido(orden("dime que archivos pdf tengo"))
        ciclo.preparar_respuesta()
        assert ciclo.oido(orden("cancela")) is Reaccion.PARAR

    def test_lo_que_dice_el_propio_jarvis_no_le_para(self, ciclo):
        """El audio mas cercano al microfono mientras habla es su propia
        voz, y su propia voz esta llena de "para" preposicion."""
        hasta_escuchando(ciclo)
        ciclo.oido(orden("crea una carpeta de facturas"))
        ciclo.preparar_respuesta()
        eco = orden("he creado la carpeta para tus facturas en documentos")
        assert ciclo.oido(eco) is Reaccion.IGNORAR
        assert ciclo.estado is Estado.HABLANDO


class TestElOrdenDeLasComprobaciones:
    def test_una_parada_dicha_a_media_orden_NO_se_manda_al_puente(self, ciclo):
        """Si la orden se mirara primero, "cancela" viajaria a Claude
        Code como si fuera lo que el usuario quiere que haga."""
        hasta_escuchando(ciclo)
        assert ciclo.oido(orden("cancela")) is Reaccion.PARAR
        assert ciclo.cuenta.ordenes == 0
        assert ciclo.estado is Estado.DORMIDO

    def test_una_orden_sin_habla_fiable_no_sale(self, ciclo):
        """Falla CERRADO, y en la direccion contraria a la parada:
        `small` se inventa texto ante el silencio 12 de 12 veces
        (medido), y lo que se invente viajaria a un agente que actua."""
        hasta_escuchando(ciclo)
        inventada = orden("abre el explorador de archivos", hay_habla_vad=False)
        assert inventada.sin_habla is True
        assert ciclo.oido(inventada) is Reaccion.IGNORAR
        assert ciclo.cuenta.ordenes == 0
        assert ciclo.estado is Estado.ESCUCHANDO


class TestLaDuda:
    """Las dos direcciones de la asimetria, que es lo que se decide aqui."""

    def test_una_parada_dudosa_para_igual(self, ciclo):
        hasta_escuchando(ciclo)
        ciclo.oido(orden("borra la carpeta de temporales"))
        dudosa = orden("para", hay_habla_vad=False)
        assert dudosa.sin_habla is True
        assert ciclo.oido(dudosa) is Reaccion.PARAR
        assert ciclo.estado is Estado.DORMIDO

    def test_y_se_cuenta_aparte_para_poder_verla_crecer(self, ciclo):
        """Si `dudosas` sube, el filtro esta mal calibrado; si sube
        `paradas` sin dudosas, es que el usuario para mucho. Sumadas, las
        dos cosas se ven igual y no se puede arreglar ninguna."""
        hasta_escuchando(ciclo)
        ciclo.oido(orden("borra la carpeta de temporales"))
        ciclo.oido(orden("para", hay_habla_vad=False))
        assert ciclo.cuenta.paradas == 1
        assert ciclo.cuenta.dudosas == 1


class TestElCicloEntero:
    def test_una_vuelta_completa(self, ciclo):
        assert ciclo.estado is Estado.DORMIDO
        ciclo.desperto()
        assert ciclo.estado is Estado.AVISANDO
        ciclo.preparar_escucha(dormir=lambda _s: None)
        assert ciclo.estado is Estado.ESCUCHANDO
        assert ciclo.oido(orden("que hora es")) is Reaccion.ORDEN
        assert ciclo.estado is Estado.TRABAJANDO
        ciclo.preparar_respuesta()
        assert ciclo.estado is Estado.HABLANDO
        ciclo.termino()
        assert ciclo.estado is Estado.DORMIDO
        assert ciclo.cuenta.ciclos == 1
        assert ciclo.cuenta.ordenes == 1

    def test_un_falso_positivo_del_wake_a_media_orden_no_reinicia_nada(self, ciclo):
        """El wake word no deberia ni estar mirando, pero si algo llega,
        reiniciar un ciclo a mitad seria peor que ignorarlo."""
        hasta_escuchando(ciclo)
        ciclo.desperto()
        assert ciclo.estado is Estado.ESCUCHANDO
        assert ciclo.cuenta.ciclos == 1

    def test_una_parada_estando_dormido_no_cuenta_como_parada(self, ciclo):
        """No hay nada que parar. Contarla ensuciaria la unica cifra que
        dice si el filtro esta bien calibrado."""
        assert ciclo.oido(orden("para")) is Reaccion.IGNORAR
        assert ciclo.cuenta.paradas == 0
        assert ciclo.cuenta.ignorados == 1
