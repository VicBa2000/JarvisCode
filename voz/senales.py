"""Los dos sonidos con los que Jarvis coordina el turno de palabra.

>>> POR QUE HAY DOS Y NO UNO, QUE ES LO QUE DECIDE JC-0011 <<<

    campana    "voy a escuchar dentro de un momento: baja el ruido"
    pitido     "habla ya"

Si sonaran parecido el usuario hablaria en el primero y se callaria en el
segundo, que es exactamente al reves de lo que hace falta. Por eso el
contraste NO se deja al timbre, que es lo primero que se le ocurre a
cualquiera y lo que peor se distingue a tres metros y con musica:

    campana    DOS notas, DESCENDENTE (1174 -> 880 Hz), ~0,6 s, con cola
    pitido     UNA nota,  ASCENDENTE  ( 740 -> 990 Hz), ~0,16 s, seca

La direccion del tono es la diferencia mas robusta que hay: sobrevive a
un altavoz malo, a la distancia y al ruido de fondo, y no depende de que
el usuario recuerde cual era "el agudo". El numero de notas y la duracion
la refuerzan por dos caminos mas.

>>> SON SINTETICOS A PROPOSITO: NO SUENAN A CAMPANA DE VERDAD <<<
La referencia es un asistente de IA -- Jarvis --, no una puerta de casa.
Un sonido acustico (campana de metal, madera, agua) suena a objeto; lo
que se busca aqui suena a maquina que responde. Los tres ingredientes,
que son los que dan ese caracter y no son decoracion:

  * **Osciladores detunados 2,5 Hz.** Dos senos casi iguales baten entre
    si y producen ese ondular electronico. Un seno solo suena a prueba de
    audiometria.
  * **Un parcial inarmonico a 2,76x.** La razon clasica de las barras
    metalicas: NO es un armonico, asi que el oido no lo funde con el
    fundamental y lo lee como brillo de cristal en vez de como nota.
  * **Glissando.** La frecuencia se mueve DENTRO de cada nota. Nada
    acustico de este tamano hace eso; los sintetizadores si.

>>> EL SONIDO NO PUEDE DESPERTAR AL PROPIO WAKE WORD <<<
Suena a obviedad y es la unica forma en que esto podria fallar en
silencio: un aviso que se activa a si mismo mete al asistente en un bucle
que ademas parece "el micro esta sensible hoy". `eval/wake_bench.py` ya
evitaba a mano decir la palabra en sus avisos por lo mismo. Aqui no se
evita a mano: se COMPRUEBA contra el modelo real en
`tests/test_voz_senales.py`, sobre el MISMO buffer que se reproduce.

Y se pregunta COMPARANDO, que es lo que costo un rato entender: el
modelo ceba su buffer con ruido aleatorio (ver `voz/wake.py`), asi que
una puntuacion suelta mide sobre todo el RNG -- de hecho campana y
pitido dan EXACTAMENTE el mismo numero, que ya dice que no lo esta
poniendo la senal. Con la misma semilla, y contra el mismo hueco lleno
de silencio de sala (2026-08-25, umbral de disparo 0,5):

    con el aviso           0,03 - 0,10
    el hueco en silencio   0,23 - 0,28   <- MAS, en los seis pares

O sea que poner el aviso se parece MENOS a la palabra de activacion que
no poner nada.

>>> POR QUE SE SINTETIZAN A 16 kHz Y NO A 44,1 <<<
Podrian sonar algo mejor a 44,1 kHz, pero entonces el test de arriba
tendria que RE-sintetizarlos a 16 kHz para dar de comer al wake word, y
estaria comprobando un buffer que no es el que se reproduce (una
sonda que construye su propia entrada mide la sonda). Todos los parciales
viven por debajo de 3,3 kHz, muy lejos de los 8 kHz de Nyquist, asi que
lo unico que se pierde es aire que aqui no hay.

QUIEN LOS USA: `voz/ciclo.py`, que es quien sabe CUANDO suena cada uno, y
`eval/wake_bench.py`, que se lo pide prestado para sus tandas. El pitido
nacio alli dentro (880 Hz planos) y se trajo aqui para que no haya dos
pitidos que puedan divergir sin que nadie se entere.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from voz.audio import SAMPLE_RATE_VOZ, Dispositivo

# Cuanto suena cada cosa. La campana ES larga a proposito -- tiene que
# poder oirse por encima de musica y teclado, que es la situacion para la
# que existe -- y el pitido corto, porque llega justo antes de hablar y
# alargarlo solo retrasa al usuario.
#
# EL PITIDO SE ALARGO DE 0,16 A 0,22 s EL 2026-08-25, con el usuario
# diciendo que "queda raro y no se entiende bien". Ver `pitido()`.
CAMPANA_S = 0.60
PITIDO_S = 0.22

# >>> SILENCIO POR DELANTE, Y NO ES RELLENO: ESTA MEDIDO <<<
# `reproducir` tarda ~540 ms en soltar un buffer de 160 ms por este
# altavoz (cuatro tomas: 532-559 ms). O sea que el dispositivo mete ~380
# ms de latencia ARRANCANDO el stream, y lo que se come es el principio.
# Con un sonido largo da igual; con un pitido de 160 ms se lleva por
# delante el ataque, que es justo lo que hace que un tono se reconozca.
# Estos 120 ms de silencio dan tiempo a que el stream este corriendo
# ANTES de que empiece el tono.
SILENCIO_INICIAL_S = 0.12

# Pico de la senal. 0,3 deja sitio de sobra antes de recortar y ya es
# claramente audible; el banco de wake venia usando 0,35 con el mismo
# altavoz. No se sube mas: un aviso que sobresalta se acaba silenciando,
# y un aviso silenciado no avisa.
VOLUMEN = 0.30

# El batido. 2,5 Hz es el ondular; por debajo de ~1 Hz no se percibe
# dentro de una nota tan corta y por encima de ~8 empieza a sonar a
# averia en vez de a maquina.
DETUNE_HZ = 2.5

# La razon inarmonica de las barras metalicas. Que NO sea un armonico
# entero es justo el punto: el oido no lo funde con el fundamental.
METALICO = 2.76

# Sin esto los tonos empiezan y acaban en seco y chasquean. 5 ms bastan y
# no se oyen como tal.
RAMPA_S = 0.005


class SenalError(RuntimeError):
    """No se pudo hacer sonar un aviso."""


# --------------------------------------------------------------------
# La sintesis: sin hardware, para que se pueda medir y probar
# --------------------------------------------------------------------

def _parcial(f_inicial: float, f_final: float, duracion_s: float,
             amplitud: float, caida: float, detune_hz: float,
             sample_rate: int) -> np.ndarray:
    """One gliding, detuned, decaying sine partial.

    El glissando obliga a integrar la frecuencia para sacar la fase
    (`cumsum`): calcularla como `2*pi*f*t` con `f` variable es el error
    clasico y produce un barrido que no es el que se pidio.
    """
    n = max(1, int(round(sample_rate * duracion_s)))
    t = np.arange(n, dtype=np.float64) / sample_rate
    recorrido = t / duracion_s if duracion_s else np.zeros(n)
    frecuencia = f_inicial + (f_final - f_inicial) * recorrido
    fase = 2.0 * np.pi * np.cumsum(frecuencia) / sample_rate

    onda = np.sin(fase)
    if detune_hz:
        # El segundo oscilador va desplazado en FRECUENCIA, no en fase:
        # es la diferencia entre batir y sonar igual pero mas fuerte.
        onda = 0.5 * (onda + np.sin(fase + 2.0 * np.pi * detune_hz * t))

    return amplitud * onda * np.exp(-caida * t)


def _rampas(onda: np.ndarray, sample_rate: int) -> np.ndarray:
    """Anti-chasquido. Solo hace falta a la entrada y a la salida."""
    n = int(sample_rate * RAMPA_S)
    if n < 2 or len(onda) < 2 * n:
        return onda
    onda = onda.copy()
    onda[:n] *= np.linspace(0.0, 1.0, n)
    onda[-n:] *= np.linspace(1.0, 0.0, n)
    return onda


def _con_silencio_delante(onda: np.ndarray, sample_rate: int) -> np.ndarray:
    """Pega el colchon de `SILENCIO_INICIAL_S`. Ver alli el porque."""
    hueco = np.zeros(int(round(sample_rate * SILENCIO_INICIAL_S)),
                     dtype=onda.dtype)
    return np.concatenate([hueco, onda])


def _normalizar(onda: np.ndarray, volumen: float) -> np.ndarray:
    """Deja el pico donde se pidio, en float32.

    Se normaliza en vez de confiar en la suma de amplitudes porque los
    parciales se solapan de forma distinta en cada senal: sin esto una
    sonaria bastante mas fuerte que la otra sin que nadie lo hubiera
    decidido.
    """
    pico = float(np.max(np.abs(onda))) if len(onda) else 0.0
    if pico > 0:
        onda = onda * (volumen / pico)
    return np.ascontiguousarray(onda.astype(np.float32))


def campana(sample_rate: int = SAMPLE_RATE_VOZ) -> np.ndarray:
    """"Voy a escuchar dentro de un momento: baja el ruido."

    Dos notas DESCENDENTES que se solapan. El solape importa: encadenadas
    sin cola suenan a dos pitidos seguidos, y con ella suenan a una sola
    figura, que es lo que hace que se reconozca sin escucharla entera.
    """
    n_total = int(round(sample_rate * CAMPANA_S))
    salida = np.zeros(n_total, dtype=np.float64)

    # D6 -> A5. Cada nota ademas cae un poco DENTRO de si misma (el -18
    # Hz), que es lo que la aleja de un tono de prueba.
    for retardo_s, f0, amplitud in ((0.00, 1174.7, 1.00), (0.16, 880.0, 0.85)):
        inicio = int(round(sample_rate * retardo_s))
        dur = (n_total - inicio) / sample_rate
        nota = (
            _parcial(f0, f0 - 18.0, dur, 1.00, 5.5, DETUNE_HZ, sample_rate)
            + _parcial(2 * f0, 2 * f0, dur, 0.22, 8.0, DETUNE_HZ, sample_rate)
            + _parcial(METALICO * f0, METALICO * f0, dur, 0.10, 11.0, 0.0,
                       sample_rate)
        )
        salida[inicio:inicio + len(nota)] += amplitud * nota

    return _con_silencio_delante(
        _normalizar(_rampas(salida, sample_rate), VOLUMEN), sample_rate)


def pitido(sample_rate: int = SAMPLE_RATE_VOZ) -> np.ndarray:
    """"Habla ya."

    Una nota ASCENDENTE y seca. La quinta (1,5x) es lo que le da el filo
    sintetico sin ensuciarlo: un fundamental solo suena a despertador.

    >>> REHECHO EL 2026-08-25: "QUEDA RARO Y NO SE ENTIENDE BIEN" <<<
    Lo dijo el usuario usandolo, que es la unica prueba que vale para un
    sonido. Tres causas, y las tres eran mias:

      * **El detune no cabia aqui.** Dos osciladores a 2,5 Hz de
        distancia tardan 400 ms en completar UN batido, y este tono
        duraba 160: no daba tiempo a que ondulara, solo a que se
        cancelara a medias. Lo que en la campana es brillo, aqui era un
        tono hueco. Fuera: el batido se queda donde tiene sitio.
      * **Se apagaba mientras subia.** La envolvente caia de 166 a 55
        (rms x1000) en esos 160 ms, o sea que la nota se iba justo
        cuando el oido esperaba el golpe. Ahora la caida es la mitad y
        la nota se sostiene.
      * **El dispositivo se comia el ataque.** Ver `SILENCIO_INICIAL_S`:
        ~380 ms de latencia arrancando el stream, medidos.

    Sustituye al tono plano de 880 Hz que vivia en `eval/wake_bench.py`.
    Las tandas de wake anteriores al 2026-08-25 se midieron con AQUEL, y
    conviene saberlo antes de comparar: el aviso es parte del
    instrumento, y ya se cambio una vez por esto mismo (la voz que decia
    "ahora" salia tan rapido que no se entendia y falseo tres intentos).
    """
    dur = PITIDO_S
    # Sin detune (ver arriba) y con un glissando mas corto: 760 -> 950 en
    # vez de 740 -> 990. Lo que se busca es que SUBA, no que barra.
    onda = (
        _parcial(760.0, 950.0, dur, 1.00, 1.0, 0.0, sample_rate)
        + _parcial(1140.0, 1425.0, dur, 0.28, 1.6, 0.0, sample_rate)
        + _parcial(1520.0, 1900.0, dur, 0.10, 3.0, 0.0, sample_rate)
    )
    return _con_silencio_delante(
        _normalizar(_rampas(onda, sample_rate), VOLUMEN), sample_rate)


# --------------------------------------------------------------------
# El altavoz de verdad
# --------------------------------------------------------------------

@dataclass
class Senales:
    """Los avisos, ya con altavoz.

    Se puede construir SIN dispositivo, y entonces no suena nada. Los
    tests, los bancos sin voz y cualquier sitio sin tarjeta de sonido lo
    construyen igual: un aviso que revienta donde no hay altavoz
    convierte una comodidad en un fallo de arranque.
    """

    dispositivo: Dispositivo | None = None
    sample_rate: int = SAMPLE_RATE_VOZ

    def __post_init__(self) -> None:
        # Se sintetizan una vez. Son ~10 ms de trabajo, pero hacerlo en
        # cada aviso mete ese retraso justo donde el aviso tiene que ser
        # puntual.
        self._campana = campana(self.sample_rate)
        self._pitido = pitido(self.sample_rate)

    @property
    def encendido(self) -> bool:
        return self.dispositivo is not None

    def campana(self) -> None:
        """"Baja el ruido, voy a escuchar." Suena ANTES, no a la vez."""
        self._sonar(self._campana)

    def pitido(self) -> None:
        """"Habla ya"."""
        self._sonar(self._pitido)

    def _sonar(self, onda: np.ndarray) -> None:
        if self.dispositivo is None:
            return
        from voz.audio import AudioError, reproducir
        try:
            reproducir(onda, self.sample_rate, self.dispositivo)
        except AudioError as exc:
            raise SenalError(f"No se pudo hacer sonar el aviso: {exc}") from exc


def _demo() -> int:
    """`python -m voz.senales`: los dos sonidos, para juzgarlos con el oido.

    Existe porque esto NO se decide leyendo un docstring. Lo unico que
    contesta "suena a asistente de IA o suena a microondas" es oirlo.
    """
    import time

    from voz.audio import ConfigAudio

    altavoz = ConfigAudio.desde_config().altavoz()
    print(f"Altavoz: {altavoz}\n")
    senales = Senales(altavoz)

    print("  campana  -- 'voy a escuchar, baja el ruido'")
    senales.campana()
    time.sleep(1.2)
    print("  pitido   -- 'habla ya'")
    senales.pitido()
    time.sleep(1.2)
    print("\n  y ahora seguidos, como se oiran de verdad:")
    print("  campana ... (2 s para callarse) ... pitido")
    senales.campana()
    time.sleep(2.0)
    senales.pitido()
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
