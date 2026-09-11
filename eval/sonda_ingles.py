"""El canal ingles esta CABLEADO. No dice que funcione bien.

    .venv\\Scripts\\python.exe -m eval.sonda_ingles

>>> PARA QUE EXISTE, Y PARA QUE NO <<<
JC-0018 dejo el ingles construido y SIN BANCO. Antes de que nadie se
siente a dictar 30 frases -- que son 15 minutos suyos y no se pueden
pedir dos veces --, esto comprueba que el camino ingles
llega entero al final. La primera vez que se corrio encontro un cable
suelto de verdad: `voz/stt.py` tenia `idioma: str = "es"` clavado y
`escuchar()` no le pasaba nunca el configurado, o sea que elegir
"English" en AJUSTES dejaba a Whisper decodificando en español.

>>> ESTO NO ES UN BANCO, Y LA DIFERENCIA NO ES DE MATIZ <<<
El audio de aqui lo sintetiza Piper, o sea que es una entrada
FABRICADA, y ya se sabe lo que vale eso: *"una sonda que construye
su propia entrada mide la sonda"*. Y no es una advertencia teorica --
esta medido en esta misma casa:

    wake word con voz sintetica    0,994-0,998   (umbral 0,5)
    wake word con la voz del autor 20/20 en silencio, 14/20 con
                                   musica, 9/20 TECLEANDO
    STT con voz sintetica          5 de 6 con WER 0,0 %
    STT con la voz del autor (es)  WER 2,4 %, 27/30

El sintetico se pega al techo en las dos cosas: **sale mas facil que el
español real**. Un banco sacado de aqui daria 20/20 y 0 % en todas las
condiciones y no habria medido nada, y ademas seria circular en el wake
word, porque los modelos de openWakeWord se entrenan con voz
sintetizada. El banco lo dicta una persona, con su voz y su sala:

    .venv\\Scripts\\python.exe -m eval.stt_bench --grabar --idioma en
    .venv\\Scripts\\python.exe -m eval.wake_bench --activaciones 20 --con-voz

LO QUE SI SE MIDE AQUI DE VERDAD es el paso 4: el lexico de parada
ingles se juzga sobre TEXTO, asi que no necesita ninguna voz. Ese
numero es real y cierra la mitad textual de JC-0018; lo que queda
abierto es la mitad acustica -- si esas frases se OYEN al decirlas.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.stt_bench import (  # noqa: E402
    ORDENES_EN,
    ORDENES_QUE_EMPIEZAN_COMO_PARADA_EN,
    PARADAS_EN,
    wer,
)
from voz.idioma import ANCLA, VOCES, lexico_de_parada  # noqa: E402

# Las que se sintetizan para el paso 3. Pocas y variadas: esto no es un
# banco, es un pulso. Se eligen una con extension, una con orden de
# consola y la unica parada inequivoca del ingles.
FRASES_DE_PULSO = [
    "run git status in the project folder",
    "delete the file report.pdf from Downloads",
    "take a screenshot and save it in Pictures",
    "nevermind",
]


def _config(idioma: str) -> Path:
    carpeta = Path(tempfile.mkdtemp(prefix=f"sonda_{idioma}_"))
    (carpeta / "jarvis.yaml").write_text(
        yaml.safe_dump({"voz": {"idioma": idioma, "stt": {"modelo": "small"}}}),
        encoding="utf-8")
    return carpeta


def _a_16k(audio: np.ndarray, sr: int) -> np.ndarray:
    n = int(len(audio) * 16000 / sr)
    return np.interp(np.linspace(0, len(audio) - 1, n),
                     np.arange(len(audio)), audio).astype("float32")


def main() -> int:
    print(__doc__.split(">>>")[0].strip())
    print()
    fallos: list[str] = []

    # --- 1. la voz ----------------------------------------------------
    print("1. LA VOZ INGLESA EN DISCO")
    from voz.tts import voces_disponibles

    hay = voces_disponibles()
    eleccion = next((v for v in VOCES["en"] if v in hay), None)
    if eleccion is None:
        print(f"   NO hay ninguna de {VOCES['en']}.")
        print("   Sin voz inglesa Jarvis no puede contestar en ingles, y esta")
        print("   sonda no puede sintetizar. Se baja con:")
        print(f"     python -m piper.download_voices {VOCES['en'][0]} "
              f"--download-dir modelos/piper")
        return 1
    print(f"   ok  {eleccion}")

    # --- 2. el canal --------------------------------------------------
    print("\n2. EL CANAL CAMBIA AL ELEGIRLO EN AJUSTES")
    from voz.stt import STT

    for idioma in ("es", "en"):
        carpeta = _config(idioma)
        resuelto = STT._idioma(carpeta)
        ancla = STT._ancla_configurada(carpeta)
        cuadra = resuelto == idioma and ancla == ANCLA[idioma]
        print(f"   {'ok ' if cuadra else 'NO '} voz.idioma={idioma!r}  ->  "
              f"canal={resuelto!r}  ancla={'ingles' if ancla == ANCLA['en'] else 'español'}")
        if not cuadra:
            fallos.append(f"el canal no sigue a voz.idioma={idioma}")
    print("   (el ancla va PEGADA al idioma: ancla inglesa decodificando en")
    print("    español no da error, da una transcripcion peor sin decir por que)")

    # --- 3. el pulso, con audio FABRICADO -----------------------------
    print("\n3. PULSO DE EXTREMO A EXTREMO  (audio SINTETICO: no es calidad)")
    from voz.tts import TTS

    tts = TTS(voz=eleccion)
    stt = STT(idioma="en", ancla=ANCLA["en"])
    for frase in FRASES_DE_PULSO:
        audio = np.concatenate([np.asarray(t, dtype="float32").reshape(-1)
                                for t in tts.sintetizar(frase)])
        t = stt.transcribir(_a_16k(audio, tts.sample_rate))
        marca = "ok " if t.idioma == "en" else "NO "
        if t.idioma != "en":
            fallos.append("la transcripcion no dice que se pidio en ingles")
        print(f"   {marca} {t.texto.strip()!r}")
        print(f"       idioma={t.idioma}  WER={wer(frase, t.texto):.0%}  "
              f"(contra el texto que se le mando decir)")
    print("   RECORDATORIO: un WER de 0 % aqui NO dice nada. El sintetico sale")
    print("   mas facil que el español REAL, que da 2,4 %. Ver la cabecera.")

    # --- 4. lo unico que aqui se mide de verdad -----------------------
    print("\n4. EL LEXICO DE PARADA INGLES, SOBRE EL CORPUS ENTERO")
    print("   Esto NO necesita voz: es texto, y por eso el numero es real.")
    from voz.parada import mirar

    lex = lexico_de_parada("en")
    aciertos, errores = 0, []
    for indice, frase in enumerate(ORDENES_EN, start=1):
        debe_parar = indice in PARADAS_EN
        para = mirar(frase, idioma="en").para
        if para == debe_parar:
            aciertos += 1
        else:
            errores.append((indice, frase, debe_parar, para))
    print(f"   {aciertos}/{len(ORDENES_EN)} clasificadas bien "
          f"(ventana de {lex.palabras_max} palabras, "
          f"medido={lex.medido})")
    for indice, frase, debia, hizo in errores:
        print(f"   NO  {indice:2d} {frase!r}: debia "
              f"{'PARAR' if debia else 'SEGUIR'} y "
              f"{'paro' if hizo else 'siguio'}")
        fallos.append(f"parada mal clasificada: {frase!r}")
    print("   LAS QUE DECIDEN LA VENTANA (ordenes que empiezan como parada):")
    for indice in sorted(ORDENES_QUE_EMPIEZAN_COMO_PARADA_EN):
        frase = ORDENES_EN[indice - 1]
        para = mirar(frase, idioma="en").para
        print(f"     {'NO ' if para else 'ok '} {frase!r} -> "
              f"{'para' if para else 'sigue'}")

    # --- veredicto ----------------------------------------------------
    print("\n" + "=" * 62)
    if fallos:
        print("EL CANAL INGLES TIENE UN CABLE SUELTO:")
        for f in dict.fromkeys(fallos):
            print(f"  - {f}")
        return 1
    print("EL CANAL INGLES ESTA CABLEADO. Lo que NO dice esta sonda:")
    print("  - si el wake word te oye a TI diciendo 'hey jarvis' en ingles")
    print("  - cual es el WER de TU ingles (el sintetico sale mas facil)")
    print("  - si la ventana de 2 palabras aguanta HABLADA, que es lo que")
    print("    `LexicoDeParada.medido = False` esta diciendo desde JC-0018")
    print("Eso lo cierra el banco, y lo dictas tu:")
    print("  -m eval.stt_bench --grabar --idioma en")
    print("  -m eval.wake_bench --activaciones 20 --con-voz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
