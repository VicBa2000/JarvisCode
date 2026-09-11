"""Banco de JC-0013: cuando se deja de grabar, medido sin hablar.

QUE PREGUNTA CONTESTA, y es la unica que importaba al construirlo: con
el umbral de fin de turno elegido, ¿CUANTAS VECES CORTA A MITAD DE
FRASE? El riesgo de cerrar "cuando el usuario deja de hablar" no es
tecnico, es que uno respira, se lo piensa o busca la palabra -- y un
corte ahi manda media orden a un agente que actua sobre la PC.

SE MIDE SOBRE EL CORPUS REAL Y NO SOBRE AUDIO INVENTADO. Las
30 ordenes de `eval/audio_ordenes/` estan dictadas por el usuario y
llevan sus pausas de verdad dentro; los 12 silencios de
`eval/audio_silencio/` son la misma sala callada. Un generador de
silencios y pitidos habria dado un numero bonito sobre el unico caso que
no se parece al problema.

LA VERDAD DE REFERENCIA es el propio VAD en su pasada de siempre
(`VAD.segmentos`), que es la que esta medida -- 30/30 ordenes y 12/12
silencios, 2026-08-21. O sea que esto NO mide "si el VAD encuentra el
habla", que ya se sabe: mide si el detector EN VIVO, que va a ciegas
hacia delante y no puede revisar lo que ya dijo, cierra en el mismo
sitio en el que la pasada completa dice que se acabo de hablar.

TRES VEREDICTOS POR ARCHIVO, no dos:

    CORTA       cerro y DESPUES seguia habiendo habla. Es el fallo.
    CIERRA      cerro despues del final del habla. Es lo que se busca.
    SE ACABO    el archivo se termino sin que cerrara. NO dice nada:
                estas grabaciones son ventanas FIJAS de 4,0 s, asi que
                muchas no tienen silencio al final que enseñarle.
                Contarlo como acierto o como fallo seria inventar el dato.

Y CON MAGNITUD CONTINUA, NO SOLO LA BANDERA: de cada archivo
sale el MARGEN en milisegundos entre donde cerro y donde acaba el habla.
Un banco que solo dijera "0 cortes" esconderia que cerro por los pelos.

    .venv/Scripts/python.exe -m eval.fin_de_turno_bench
    .venv/Scripts/python.exe -m eval.fin_de_turno_bench --barrido
"""

from __future__ import annotations

import argparse
import statistics
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from voz.audio import SAMPLE_RATE_VOZ
from voz.vad import (
    BLOQUE,
    ESPERA_INICIO_MS,
    SILENCIO_FIN_TURNO_MS,
    VAD,
    Cierre,
    FinDeTurno,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIR_ORDENES = PROJECT_ROOT / "eval" / "audio_ordenes"
DIR_SILENCIO = PROJECT_ROOT / "eval" / "audio_silencio"

# La ventana fija que esto sustituye, tal y como estaba en `voz/bucle.py`
# antes de JC-0013. Es el punto de comparacion para la latencia Y para el
# corte: todo archivo cuyo habla pase de aqui es una orden que en
# produccion salia partida.
#
# >>> Y OJO, QUE LA PROSA LO CONTABA MAL <<<
# La prosa decia que los 4,0 s salian de "la ventana con la que se
# grabaron las 30 ordenes". Los .wav de disco duran 6,00 s. Lo que vale
# 4,0 es el DEFAULT de `--segundos` en `eval/stt_bench.py`, que no es lo
# mismo: el corpus se grabo pasandole 6. O sea que el numero de
# produccion nunca estuvo respaldado por como se grabo el banco.
VENTANA_VIEJA_S = 4.0

# Con que trozos se le da de comer al detector. NO cambia el resultado --
# `FinDeTurno` acumula hasta bloques enteros de `BLOQUE` muestras, asi
# que el veredicto cae siempre en las mismas fronteras -- y por eso el
# tamaño se puede elegir por comodidad sin que el banco mida el banco.
TROZO = 1024


@dataclass
class Caso:
    nombre: str
    veredicto: str           # CORTA | CIERRA | SE ACABO | SIN HABLA
    cierre: str              # silencio | sin_habla | (ninguno)
    cerro_en_s: float | None
    fin_del_habla_s: float | None
    margen_ms: float | None  # cerro_en - fin_del_habla. Negativo = corte.
    duracion_s: float
    # Si el detector llego a darse por empezado. Es LA pregunta sobre el
    # silencio: un turno que se abre con el ruido de la sala se queda
    # esperando a que "termines" de hablar algo que nadie dijo.
    abrio_turno: bool = False


def _leer(ruta: Path) -> np.ndarray:
    import soundfile as sf

    audio, sr = sf.read(str(ruta), dtype="float32")
    if sr != SAMPLE_RATE_VOZ:
        raise SystemExit(
            f"{ruta.name} esta a {sr} Hz y el VAD trabaja a {SAMPLE_RATE_VOZ}."
        )
    return np.asarray(audio, dtype="float32").reshape(-1)


def _reproducir(
    vad: VAD, audio: np.ndarray, silencio_fin_ms: float, espera_inicio_ms: float
) -> FinDeTurno:
    """Pasa el audio por el detector como si entrara por el microfono."""
    detector = FinDeTurno(
        vad, silencio_fin_ms=silencio_fin_ms, espera_inicio_ms=espera_inicio_ms
    )
    for inicio in range(0, len(audio), TROZO):
        if detector.empujar(audio[inicio : inicio + TROZO]) is not None:
            break
    return detector


def _fin_del_habla(vad: VAD, audio: np.ndarray) -> float | None:
    """Donde acaba de hablar, segun la pasada completa."""
    spans = vad.segmentos(audio)
    if not spans:
        return None
    # `segmentos` ya devuelve el span con su RELLENO_MS por detras. Se usa
    # tal cual: es el mismo audio que se le entregaria a Whisper, o sea lo
    # que de verdad se perderia al cortar.
    return spans[-1][1] / SAMPLE_RATE_VOZ


def medir(
    rutas: list[Path], vad: VAD, silencio_fin_ms: float, espera_inicio_ms: float
) -> list[Caso]:
    casos = []
    for ruta in rutas:
        audio = _leer(ruta)
        duracion = len(audio) / SAMPLE_RATE_VOZ
        detector = _reproducir(vad, audio, silencio_fin_ms, espera_inicio_ms)
        cierre = detector.cierre
        cerro_en = detector.segundos_vistos if cierre is not None else None
        fin = _fin_del_habla(vad, audio)

        if cierre is None:
            veredicto, margen = "SE ACABO", None
        elif cierre is Cierre.SIN_HABLA or fin is None:
            veredicto, margen = "SIN HABLA", None
        else:
            margen = (cerro_en - fin) * 1000
            # El detector cierra N ms DESPUES del ultimo bloque de habla
            # que vio. Si aun asi queda habla por detras, es que habia una
            # pausa mas larga que el umbral en medio de la frase: eso es
            # cortar a mitad.
            veredicto = "CORTA" if margen < 0 else "CIERRA"

        casos.append(
            Caso(
                nombre=ruta.name,
                veredicto=veredicto,
                cierre=cierre.value if cierre else "(ninguno)",
                cerro_en_s=cerro_en,
                fin_del_habla_s=fin,
                margen_ms=margen,
                duracion_s=duracion,
                abrio_turno=detector.empezo_en_s is not None,
            )
        )
    return casos


def _rutas(directorio: Path) -> list[Path]:
    if not directorio.is_dir():
        return []
    return sorted(directorio.glob("*.wav"))


def _tabla(casos: list[Caso]) -> None:
    print(
        "  {:<10} {:<10} {:>8} {:>10} {:>10}".format(
            "archivo", "veredicto", "cerro", "fin habla", "margen"
        )
    )
    for c in casos:
        cerro = f"{c.cerro_en_s:.2f} s" if c.cerro_en_s is not None else "--"
        fin = (
            f"{c.fin_del_habla_s:.2f} s"
            if c.fin_del_habla_s is not None
            else "--"
        )
        margen = f"{c.margen_ms:+.0f} ms" if c.margen_ms is not None else "--"
        print(
            "  {:<10} {:<10} {:>8} {:>10} {:>10}".format(
                c.nombre, c.veredicto, cerro, fin, margen
            )
        )


def _resumen(casos: list[Caso], titulo: str) -> None:
    corta = [c for c in casos if c.veredicto == "CORTA"]
    cierra = [c for c in casos if c.veredicto == "CIERRA"]
    acabo = [c for c in casos if c.veredicto == "SE ACABO"]
    sin_habla = [c for c in casos if c.veredicto == "SIN HABLA"]
    print(f"\n  {titulo}: {len(casos)} archivos")
    print(f"    CORTA a mitad de frase   {len(corta)}")
    print(f"    CIERRA tras el habla     {len(cierra)}")
    print(f"    SE ACABO sin cerrar      {len(acabo)}")
    print(f"    SIN HABLA                {len(sin_habla)}")

    margenes = [c.margen_ms for c in cierra if c.margen_ms is not None]
    if margenes and len(set(round(m) for m in margenes)) == 1:
        # NO ES UNA MEDICION, ES ARITMETICA, y decirlo evita que alguien
        # lo cite como si fuera un resultado: el detector cierra siempre
        # `umbral` ms despues del ultimo bloque de habla, y `segmentos`
        # marca el final `RELLENO_MS` mas alla de ese mismo bloque. La
        # resta sale constante por construccion. Lo que SI mide este
        # banco es el recuento de CORTA, que no tiene nada de constante.
        print(
            f"    margen: {margenes[0]:+.0f} ms en los {len(margenes)}, y es "
            f"CONSTANTE POR CONSTRUCCION (umbral - RELLENO_MS), no un "
            f"resultado"
        )
    elif margenes:
        print(
            f"    margen sobre el fin del habla: min {min(margenes):+.0f} ms  "
            f"mediana {statistics.median(margenes):+.0f} ms  "
            f"max {max(margenes):+.0f} ms"
        )

    hablados = [c for c in casos if c.veredicto in ("CIERRA", "CORTA")]
    tiempos = [c.cerro_en_s for c in hablados if c.cerro_en_s is not None]
    if tiempos:
        tiempos_ord = sorted(tiempos)
        print(
            f"    cerro en: min {min(tiempos):.2f} s  "
            f"mediana {statistics.median(tiempos):.2f} s  "
            f"max {max(tiempos):.2f} s   "
            f"(la ventana fija eran {VENTANA_VIEJA_S:.1f} s SIEMPRE)"
        )
        del tiempos_ord

    # >>> LA CIFRA QUE JUSTIFICA LA TANDA <<<
    # Cuantas de estas ordenes REALES salian partidas con la ventana
    # fija. No es una simulacion: es el habla que hay en el .wav contra
    # el numero que corria en produccion.
    truncadas = [
        c for c in hablados
        if c.fin_del_habla_s is not None and c.fin_del_habla_s > VENTANA_VIEJA_S
    ]
    if hablados:
        print(
            f"    LA VENTANA FIJA DE {VENTANA_VIEJA_S:.1f} s HABRIA CORTADO "
            f"{len(truncadas)} de {len(hablados)}:"
        )
        for c in truncadas:
            print(
                f"        {c.nombre}: se hablo hasta {c.fin_del_habla_s:.2f} s "
                f"({(c.fin_del_habla_s - VENTANA_VIEJA_S) * 1000:.0f} ms "
                f"perdidos)"
            )
    if corta:
        print("    >>> LOS CORTES:")
        for c in corta:
            print(
                f"        {c.nombre}: cerro en {c.cerro_en_s:.2f} s y el habla "
                f"seguia hasta {c.fin_del_habla_s:.2f} s ({c.margen_ms:+.0f} ms)"
            )


def _sobre_el_silencio(rutas: list[Path], vad: VAD, umbral_ms: float) -> None:
    """Lo que las 12 tomas de sala callada SI pueden contestar, y lo que no.

    LO QUE NO: si la espera a que empieces vence a tiempo. Esas tomas
    duran 3,00 s clavados y la espera son 3000 ms, asi que el detector se
    queda a un bloque de llegar y el archivo se acaba antes. No es un
    fallo del detector ni de la grabacion -- es que ese numero no cabe
    dentro de este corpus, y dar por bueno un "SIN HABLA" que en realidad
    fue "se acabo el fichero" seria justo la clase de resultado sobre
    entrada inventada, que mide la sonda y no el sistema.

    LO QUE SI, Y ES LO QUE IMPORTA: si el ruido de esa sala llega a ABRIR
    un turno. Si `empezo_en_s` se pone sobre silencio, el detector se
    queda esperando el final de un habla que nadie empezo, y entonces lo
    unico que cierra la ventana es el tope duro. Eso se contesta con 3 s
    de sobra.
    """
    duraciones = set()
    abrieron = []
    for ruta in rutas:
        audio = _leer(ruta)
        duraciones.add(round(len(audio) / SAMPLE_RATE_VOZ, 2))
        # Espera generosa a proposito: aqui no se mide la paciencia, se
        # mide si algo del ruido de sala pasa por habla.
        det = _reproducir(vad, audio, umbral_ms, espera_inicio_ms=10_000)
        if det.empezo_en_s is not None:
            abrieron.append((ruta.name, det.empezo_en_s))

    print(f"\n  SILENCIO DE LA MISMA SALA: {len(rutas)} tomas de "
          f"{'/'.join(f'{d:.2f}' for d in sorted(duraciones))} s")
    print(f"    abrieron turno sobre el ruido de fondo   {len(abrieron)}")
    for nombre, cuando in abrieron:
        print(f"        {nombre}: se dio por empezado en {cuando:.2f} s")
    if not abrieron:
        print("    (o sea que la ventana no se queda abierta por la sala;")
        print("     lo que la cierra en ese caso es la espera de "
              f"{ESPERA_INICIO_MS:.0f} ms, que estas tomas de 3,00 s no")
        print("     alcanzan a probar y por eso no se cuenta aqui)")


def barrido(vad: VAD, rutas: list[Path]) -> None:
    """El umbral no se defiende con una cifra suelta, sino con la curva."""
    print("\n=== BARRIDO DEL UMBRAL DE FIN DE TURNO ===")
    print("  Lo que se busca es el menor umbral que sigue dando 0 cortes:")
    print("  cada 100 ms de mas se pagan en CADA orden que se dicta.\n")
    print(
        "  {:>9} {:>6} {:>7} {:>9} {:>12} {:>15}".format(
            "umbral", "corta", "cierra", "se acabo", "margen min", "cierre mediano"
        )
    )
    for ms in (300, 400, 500, 600, 700, 800, 900, 1000, 1200):
        casos = medir(rutas, vad, ms, ESPERA_INICIO_MS)
        corta = [c for c in casos if c.veredicto == "CORTA"]
        cierra = [c for c in casos if c.veredicto == "CIERRA"]
        acabo = [c for c in casos if c.veredicto == "SE ACABO"]
        margenes = [c.margen_ms for c in cierra if c.margen_ms is not None]
        tiempos = [c.cerro_en_s for c in cierra if c.cerro_en_s is not None]
        if ms == 300:
            marca = "  <- MIN_SILENCIO_MS: el numero EQUIVOCADO"
        elif ms == SILENCIO_FIN_TURNO_MS:
            marca = "  <- elegido"
        else:
            marca = ""
        print(
            "  {:>6} ms {:>6} {:>7} {:>9} {:>+9.0f} ms {:>13.2f} s{}".format(
                ms,
                len(corta),
                len(cierra),
                len(acabo),
                min(margenes) if margenes else 0,
                statistics.median(tiempos) if tiempos else 0,
                marca,
            )
        )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--barrido", action="store_true", help="prueba varios umbrales"
    )
    p.add_argument("--detalle", action="store_true", help="una linea por archivo")
    p.add_argument("--umbral-ms", type=float, default=SILENCIO_FIN_TURNO_MS)
    args = p.parse_args()

    ordenes = _rutas(DIR_ORDENES)
    silencios = _rutas(DIR_SILENCIO)
    if not ordenes:
        raise SystemExit(f"No hay grabaciones en {DIR_ORDENES}.")

    vad = VAD()
    print("=== JC-0013: FIN DE TURNO ===")
    print(f"  umbral de fin de turno   {args.umbral_ms:.0f} ms")
    print(f"  espera a que empieces    {ESPERA_INICIO_MS:.0f} ms")
    print(
        f"  resolucion del detector  {BLOQUE * 1000 / SAMPLE_RATE_VOZ:.0f} ms"
    )

    casos = medir(ordenes, vad, args.umbral_ms, ESPERA_INICIO_MS)
    if args.detalle:
        print()
        _tabla(casos)
    _resumen(casos, "ORDENES REALES (dictadas por el usuario)")

    if silencios:
        _sobre_el_silencio(silencios, vad, args.umbral_ms)

    if args.barrido:
        barrido(vad, ordenes)


if __name__ == "__main__":
    main()
