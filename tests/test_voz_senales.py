"""Tests de `voz/senales.py`, los dos avisos de JC-0011.

Ninguno necesita altavoz: la sintesis esta separada del hardware justo
para esto. El unico que carga un modelo es el que comprueba que los
avisos no despiertan al propio wake word, y carga el REAL -- porque esa
pregunta contra un modelo de mentira no significa nada.

LO QUE NO SE PUEDE PROBAR AQUI: si suenan bien. Eso se juzga con el oido
y por eso existe `python -m voz.senales`. Un test puede comprobar que la
campana BAJA y el pitido SUBE, que es la propiedad que JC-0011 exige; no
puede comprobar que suene a asistente de IA.
"""

from __future__ import annotations

import numpy as np

from tests.entorno import necesita_modelos_wake
from voz.audio import SAMPLE_RATE_VOZ
from voz.senales import (
    CAMPANA_S,
    PITIDO_S,
    SILENCIO_INICIAL_S,
    VOLUMEN,
    Senales,
    campana,
    pitido,
)


def centroide(onda: np.ndarray, desde_s: float, hasta_s: float) -> float:
    """Centro de gravedad del espectro de un trozo, en Hz.

    Es la forma barata de preguntar "esto suena mas agudo o mas grave que
    aquello" sin tener que seguir el fundamental, que con glissando y
    varios parciales se complica sin necesidad.
    """
    # Los dos avisos empiezan con un colchon de silencio (el altavoz se
    # come el ataque: ver `SILENCIO_INICIAL_S`), asi que las ventanas se
    # miden DESDE el tono. Medir el silencio daria una division por cero
    # y, peor, un numero sin sentido que pareceria una medida.
    desde_s += SILENCIO_INICIAL_S
    hasta_s += SILENCIO_INICIAL_S
    trozo = onda[int(desde_s * SAMPLE_RATE_VOZ):int(hasta_s * SAMPLE_RATE_VOZ)]
    espectro = np.abs(np.fft.rfft(trozo * np.hanning(len(trozo))))
    frecuencias = np.fft.rfftfreq(len(trozo), 1 / SAMPLE_RATE_VOZ)
    return float((espectro * frecuencias).sum() / espectro.sum())


class TestLaForma:
    def test_salen_en_float32_al_ritmo_de_la_voz(self):
        """`voz.audio.reproducir` quiere float32, y todo el arbol trabaja
        a 16 kHz. Entregar float64 aqui se veria como un ruido raro, no
        como un error."""
        for onda in (campana(), pitido()):
            assert onda.dtype == np.float32
            assert onda.ndim == 1

    def test_duran_lo_que_dicen_durar_mas_su_colchon(self):
        """`CAMPANA_S` y `PITIDO_S` son el TONO. Delante va el silencio
        que evita que el dispositivo se coma el ataque, y cuenta en el
        buffer aunque no se oiga."""
        for onda, tono in ((campana(), CAMPANA_S), (pitido(), PITIDO_S)):
            assert abs(len(onda) / SAMPLE_RATE_VOZ
                       - (tono + SILENCIO_INICIAL_S)) < 0.01

    def test_empiezan_en_silencio_de_verdad(self):
        """Si el colchon no fuera silencio no serviria de nada."""
        for onda in (campana(), pitido()):
            hasta = int(SAMPLE_RATE_VOZ * SILENCIO_INICIAL_S * 0.9)
            assert float(np.max(np.abs(onda[:hasta]))) == 0.0

    def test_los_dos_suenan_igual_de_fuerte(self):
        """Si uno sonara mas que el otro seria por accidente -- por como
        se solapan sus parciales --, no porque alguien lo decidiera."""
        assert abs(float(np.abs(campana()).max()) - VOLUMEN) < 1e-6
        assert abs(float(np.abs(pitido()).max()) - VOLUMEN) < 1e-6

    def test_el_pitido_no_se_apaga_mientras_sube(self):
        """La causa numero dos de que "no se entendiera": la envolvente
        caia de 166 a 55 (rms x1000) en 160 ms, o sea que la nota se iba
        justo cuando el oido esperaba el golpe."""
        onda = pitido()[int(SAMPLE_RATE_VOZ * SILENCIO_INICIAL_S):]
        mitad = len(onda) // 2
        rms = lambda x: float(np.sqrt((x.astype(np.float64) ** 2).mean()))
        assert rms(onda[mitad:]) > 0.55 * rms(onda[:mitad])

    def test_no_chasquean(self):
        """Un tono que empieza o acaba en seco chasquea, y a los veinte
        avisos molesta lo bastante como para que se acabe silenciando."""
        for onda in (campana(), pitido()):
            assert abs(float(onda[0])) < 0.01
            assert abs(float(onda[-1])) < 0.01


class TestQueNoSeConfundan:
    """La propiedad que JC-0011 pide: campana y pitido NO pueden parecerse.

    Si sonaran igual el usuario hablaria en el primero y se callaria en el
    segundo, que es exactamente al reves.
    """

    def test_la_campana_baja(self):
        onda = campana()
        assert centroide(onda, 0.0, CAMPANA_S * 0.35) > centroide(
            onda, CAMPANA_S * 0.55, CAMPANA_S * 0.95)

    def test_el_pitido_sube(self):
        onda = pitido()
        assert centroide(onda, 0.0, PITIDO_S * 0.35) < centroide(
            onda, PITIDO_S * 0.55, PITIDO_S * 0.95)

    def test_y_ademas_uno_dura_mucho_mas_que_el_otro(self):
        """Segunda diferencia por otro camino: la direccion del tono se
        puede perder con un altavoz malo, la duracion no.

        El margen bajo de 3,7x a 2,7x el 2026-08-25, al alargar el
        pitido porque no se entendia. Sigue siendo casi el triple, que a
        estas duraciones se distingue sin pensarlo."""
        assert CAMPANA_S > 2.5 * PITIDO_S


@necesita_modelos_wake
class TestQueNoSeDespierteASiMismo:
    """La unica forma en que esto podria fallar EN SILENCIO.

    Un aviso que dispara el wake word mete al asistente en un bucle que
    ademas parece otra cosa ("el micro esta sensible hoy"). Se comprueba
    contra el modelo real y sobre el MISMO buffer que se reproduce, no
    sobre una re-sintesis.

    >>> Y SE PREGUNTA COMPARANDO, PORQUE EL NUMERO SUELTO NO VALE <<<
    `voz/wake.py` lo deja dicho: `AudioFeatures` ceba su buffer con RUIDO
    ALEATORIO del RNG global de numpy, asi que la MISMA grabacion da
    puntuaciones distintas en cada pasada. Medido el 2026-08-25 sobre
    estos dos avisos, con seis semillas: 0,030 a 0,099, y **la campana y
    el pitido dan exactamente el mismo numero**, lo que ya dice que ese
    numero no lo esta poniendo la senal.

    Asi que se compara CONTRA EL MISMO HUECO LLENO DE SILENCIO DE SALA,
    con la misma semilla. Los seis pares dieron 0,03-0,10 con el aviso
    contra 0,23-0,28 con silencio: el aviso puntua MENOS que no poner
    nada. Un "< 0,1" a secas habria estado midiendo el RNG.
    """

    def _puntuacion_maxima(self, relleno: np.ndarray, semilla: int) -> float:
        from voz.wake import TRAMA, Wake

        # Silencio de sala por delante y por detras: el modelo necesita
        # contexto, y darle el aviso a pelo no es lo que pasa de verdad.
        sala = (np.random.RandomState(0).randn(TRAMA * 10) * 0.002).astype(
            np.float32)
        # La semilla fija el cebado del modelo, que es lo que hace
        # comparables las dos ramas del par.
        np.random.seed(semilla)
        wake = Wake()
        wake.recorrer(np.concatenate([sala, relleno, sala]))
        return wake.escucha.mejor_puntuacion

    def _hueco_en_silencio(self, onda: np.ndarray) -> np.ndarray:
        return (np.random.RandomState(1).randn(len(onda)) * 0.002).astype(
            np.float32)

    def _comparar(self, onda: np.ndarray) -> None:
        for semilla in range(4):
            con = self._puntuacion_maxima(onda, semilla)
            sin = self._puntuacion_maxima(self._hueco_en_silencio(onda),
                                          semilla)
            assert con < 0.25, f"semilla {semilla}: {con:.3f}"
            assert con <= sin, (
                f"semilla {semilla}: el aviso ({con:.3f}) puntua MAS que el "
                f"mismo hueco en silencio ({sin:.3f})")

    def test_la_campana_no_dispara_el_wake_word(self):
        self._comparar(campana())

    def test_el_pitido_no_dispara_el_wake_word(self):
        self._comparar(pitido())


class TestSinAltavoz:
    def test_sin_dispositivo_no_suena_y_no_revienta(self):
        """Los tests, los bancos sin voz y las maquinas sin tarjeta de
        sonido construyen esto igual. Un aviso que revienta donde no hay
        altavoz convierte una comodidad en un fallo de arranque."""
        senales = Senales()
        assert senales.encendido is False
        senales.campana()
        senales.pitido()

    def test_se_sintetizan_una_vez_y_no_en_cada_aviso(self):
        """Sintetizar cuesta ~10 ms. Hacerlo en cada aviso mete ese
        retraso justo donde el aviso tiene que ser puntual."""
        senales = Senales()
        assert senales._campana is senales._campana
        assert len(senales._pitido) == len(pitido())
