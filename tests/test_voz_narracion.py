"""Lo que Claude Code cuenta mientras trabaja, filtrado para un oido.

>>> LAS ENTRADAS SALEN DE SESIONES REALES, NO DE MI CABEZA <<<
Las frases de aqui estan copiadas literalmente de los registros crudos de
`logs/puente/*.jsonl` y `eval/trazas_claude_code/*.jsonl`, y se pueden
volver a sacar con `python -m eval.mirar_narracion`. Eso importa mas de
lo normal en este modulo: un filtro probado contra ejemplos inventados
mide lo bien que imagino yo lo que dice Claude Code, que es exactamente
lo que una sonda no debe hacer.

Lo que el corpus enseño, y no era lo que yo supuse al empezar: NINGUNA de
las 23 narraciones reales es un comando suelto. Claude Code narra en
prosa. El problema real son los trozos tecnicos DENTRO de la prosa.
"""

from __future__ import annotations

import pytest

from voz.narracion import (LIMITE_NARRADO, Veredicto, para_un_oido,
                           por_que_no_se_dice, sin_el_parentesis_tecnico)

# --- 1. LO QUE SE DICE ----------------------------------------------------

# Literales del corpus. Son prosa entera y tienen que pasar limpias.
PROSA_REAL = [
    "Voy a intentar abrir Spotify en tu PC.",
    "Voy a revisar la informacion de tu PC: SO, hardware, disco y memoria.",
    "Ahora arranco un monitor para detectar en cuanto el Agent Service y "
    "Ollama respondan, sin bloquear.",
    "El archivo existe. Procedo a borrarlo.",
    "Ahora creo resumen.txt con el contenido leido.",
]


@pytest.mark.parametrize("texto", PROSA_REAL)
def test_la_prosa_real_se_locuta_entera(texto):
    narracion = para_un_oido(texto)
    assert narracion.se_dice, narracion.motivos
    assert narracion.hablado == texto
    assert narracion.frases_caidas == 0


def test_procedo_a_borrarlo_es_una_frase():
    """>>> LO ENCONTRO LA MEDICION, NO YO <<<

    Con el minimo en tres palabras, "Procedo a borrarlo" se caia -- y es
    prosa perfecta, y ademas la mitad informativa del comentario. Dos
    palabras bastan; lo que se sigue cayendo es "Ubicado.", que es una
    etiqueta y no una frase.
    """
    assert por_que_no_se_dice("Procedo a borrarlo") is None
    assert por_que_no_se_dice("Ubicado.") == "no llega a frase"


# --- 2. LO QUE NO PUEDE LLEGAR AL TTS -------------------------------------

# >>> LO QUE PIDIO EL USUARIO, CON SUS PALABRAS (2026-08-27) <<<
# Pidio no meter comandos al TTS, solo texto: si no, el sintetizador se
# confunde y acaba leyendo en alto cosas como una ruta con dos puntos y
# comas, que no tienen nada que ver con un comentario. Cada caso de aqui
# es una forma en
# que eso volveria a pasar.
@pytest.mark.parametrize("frase,motivo", [
    ("Voy a mirar C:\\proyectos\\nebula ahora mismo", "ruta con unidad"),
    ("bash:c:/proyectos/alert.py :,=", "ruta con unidad"),
    ("Lanzo el D4 con submission 2000d4720205e2ad09640ba48aeb7bd9 ahora",
     "identificador"),
    ("Voy a correr nvidia-smi --query-gpu=utilization ahora mismo",
     "opcion de comando"),
    ("Arranco con OLLAMA_HOST=127.0.0.1 puesto y lo miro", "asignacion"),
    ("El servicio contesta bien en el puerto :8765 desde hace rato", "puerto"),
    ("Apunto al servidor 127.0.0.1 para que responda ya", "direccion IP"),
    ("Lo mando con cat fichero | grep cosa y luego miro", "simbolo de shell"),
])
def test_lo_impronunciable_no_se_locuta(frase, motivo):
    assert por_que_no_se_dice(frase) == motivo


def test_el_hexadecimal_de_32_del_corpus_no_llega_al_tts():
    """La peor frase real que hay, entera y tal cual se registro.

    Son 32 caracteres de hexadecimal, y ademas un puerto. Locutarla es
    justo lo que el usuario pidio que no pasara. Lo que se dice tiene que
    seguir siendo una frase, no un muñon.
    """
    real = ("Todo listo: Agent Service, Ollama (:11435, GTX 1660 Super "
            "detectado) y `training.db` confirmados. Lanzo el reanalisis "
            "A/B del D4 (submission `2000d4720205e2ad09640ba48aeb7bd9`).")
    narracion = para_un_oido(real)
    assert narracion.se_dice
    assert "2000d4720205e2ad09640ba48aeb7bd9" not in narracion.hablado
    assert ":11435" not in narracion.hablado
    # Las DOS frases sobreviven: lo unico que se fue son los dos incisos
    # entre parentesis, que son los que llevaban el puerto y el hexadecimal.
    # Eso es lo que se buscaba -- no mutilar, quitar el inciso.
    assert narracion.hablado == ("Todo listo: Agent Service, Ollama y "
                                 "training.db confirmados. "
                                 "Lanzo el reanalisis A/B del D4.")
    assert narracion.frases_caidas == 0


def test_un_bloque_de_codigo_no_deja_nada_que_decir():
    narracion = para_un_oido("```python\nprint('hola')\n```")
    assert narracion.veredicto is Veredicto.NADA_QUE_DECIR


# --- 3. EL PARENTESIS TECNICO ---------------------------------------------


def test_un_inciso_tecnico_se_quita_sin_tirar_la_frase():
    """>>> LA LINEA ENTRE QUITAR Y INVENTAR <<<

    Un inciso entre parentesis es gramaticalmente opcional: quitarlo deja
    una frase entera y correcta, y eso NO es inventar como se pronuncia
    nada. Sustituir el token por una palabra nuestra si lo seria, y es lo
    que `voz/resumen.py` se niega a hacer a ciegas.

    Lo pidio el corpus: la frase se caia entera por un numero de puerto
    metido en un inciso, y lo de fuera era bueno.
    """
    frase = "El Agent Service ya esta arriba (:8765 health OK), pero falta"
    assert sin_el_parentesis_tecnico(frase) == (
        "El Agent Service ya esta arriba, pero falta")


def test_un_inciso_NORMAL_no_se_toca():
    """Solo se quita el que lleva algo impronunciable. Quitarlos todos
    seria empobrecer la narracion por si acaso."""
    frase = "Rust ya compilo (3.1s, incremental)."
    assert sin_el_parentesis_tecnico(frase) == frase
    assert para_un_oido(frase).hablado == frase


@pytest.mark.parametrize("frase", [
    "Voy a esperar 15-30 min a que termine el trabajo",   # rango, no codigo
    "La GPU esta al 3% de uso ahora mismo",               # porcentaje
    "Tarda ~15 minutos en total segun la medida",         # aproximado
])
def test_lo_que_PARECE_tecnico_y_no_lo_es_sigue_diciendose(frase):
    """Tres formas que la primera version tiraba y son prosa corriente.
    Un filtro que se pasa de listo deja a Jarvis mudo, que es el fallo
    contrario y se nota igual."""
    assert por_que_no_se_dice(frase) is None


# --- 4. EL RECORTE --------------------------------------------------------


def test_se_corta_por_frase_entera_y_nunca_a_mitad():
    """Media frase locutada suena a que el asistente se colgo."""
    larga = " ".join(f"Esta es la frase numero {n} y va entera." for n in
                     ("uno", "dos", "tres", "cuatro", "cinco", "seis"))
    narracion = para_un_oido(larga)
    assert narracion.recortado
    assert len(narracion.hablado) <= LIMITE_NARRADO
    assert narracion.hablado.endswith(".")


def test_las_magnitudes_son_continuas_y_no_una_bandera():
    """Continuas, no banderas: `frases_caidas` distingue haber tirado una
    coletilla de haber tirado el comentario entero."""
    narracion = para_un_oido(
        "Encontre el proyecto en C:\\proyectos\\nebula, no en carpetadepruebas. "
        "Voy a revisar su estado actual.")
    assert narracion.se_dice
    assert narracion.frases_dichas == 1
    assert narracion.frases_caidas == 1
    assert "ruta con unidad" in narracion.motivos
    assert narracion.largo_original > len(narracion.hablado)


# --- 5. CONTRA EL CORPUS ENTERO -------------------------------------------


def test_el_filtro_no_amordaza_a_jarvis():
    """>>> LA CIFRA QUE DICE SI ESTO SIRVE <<<

    Un filtro que se calla el 80 % de las veces cumple "no meter comandos
    al TTS" y no da ninguna vividez, que era el objetivo. Medido el
    2026-08-27 contra las 23 narraciones reales: **22 se locutan**.

    Si este test empieza a fallar, la respuesta NO es bajarle el numero:
    es mirar con `-m eval.mirar_narracion` que se esta cayendo y por que.
    """
    corpus = pytest.importorskip("eval.mirar_narracion")
    muestras = corpus.narraciones()
    if len(muestras) < 20:
        pytest.skip(f"no hay corpus suficiente en disco ({len(muestras)})")
    dichas = sum(1 for _, texto in muestras if para_un_oido(texto).se_dice)
    assert dichas / len(muestras) >= 0.85, (
        f"el filtro solo deja pasar {dichas} de {len(muestras)}")


def test_ninguna_narracion_real_cuela_una_ruta_al_tts():
    """La otra mitad, y es la que pidio el usuario: de lo que SI se
    locuta, nada puede llevar una ruta ni un identificador dentro."""
    corpus = pytest.importorskip("eval.mirar_narracion")
    muestras = corpus.narraciones()
    if not muestras:
        pytest.skip("no hay corpus en disco")
    for _, texto in muestras:
        narracion = para_un_oido(texto)
        if not narracion.se_dice:
            continue
        assert por_que_no_se_dice(narracion.hablado) is None, narracion.hablado
