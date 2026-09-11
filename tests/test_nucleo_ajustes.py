"""Los ajustes de la consola: lo que se puede tocar y lo que no.

LO QUE MAS SE PRUEBA AQUI no es que guardar funcione, sino las tres
cosas que, si se rompen, se rompen EN SILENCIO:

  1. que `config/jarvis.yaml` NO se toque nunca. 420 de sus 512 lineas
     son comentarios -- el porque de cada numero medido en veinte dias --
     y PyYAML no los conserva. Un guardado que reescribiera ese archivo
     los borraria sin un solo error, y no estan en ningun otro sitio.
  2. que la superposicion llegue A TODOS los que leen la config. Si no,
     el panel diria "hace falta reiniciar" sobre ajustes que al
     reiniciar seguirian sin aplicarse: la pantalla mintiendo.
  3. que la combinacion mala del STT NO SE PUEDA EXPRESAR. El umbral de
     "nadie hablo" va atado al ancla de vocabulario y lo elige el codigo;
     dejarlo suelto permitiria "ancla puesta con umbral 0,6", que cuela
     cuatro de los doce silencios COMO ORDENES.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from nucleo import ajustes as mod
from nucleo.ajustes import Ajuste, AjustesError
from nucleo.configuracion import load_general_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def config(tmp_path) -> Path:
    """Una copia de la LINEA BASE, para no tocar la del usuario.

    >>> COPIABA `config/jarvis.yaml` Y ESO SE ROMPIO EL 2026-09-08 <<<
    Ese archivo dejo de viajar en el repositorio al preparar el release:
    es la configuracion DE CADA UNO y ahora esta en `.gitignore`. En un
    clon recien descargado no existe hasta que alguien arranca Jarvis una
    vez, asi que este `shutil.copy` levantaba `FileNotFoundError` y dejaba
    los 17 tests de este archivo EN ERROR.
    Y lo peor no era que fallara: era que fallaba SEGUN EL ORDEN. Otro
    test de la suite siembra la config real como efecto de lo que
    comprueba, o sea que corriendo el archivo suelto pasaba y corriendo la
    suite entera reventaba -- un fallo que se lee como intermitente
    cuando es perfectamente determinista.
    La base es ademas la fuente CORRECTA: es el `jarvis.yaml` que de
    verdad tiene alguien que instala esto, no el del autor.
    """
    destino = tmp_path / "config"
    destino.mkdir()
    shutil.copy(PROJECT_ROOT / "config" / "base" / "jarvis.yaml",
                destino / "jarvis.yaml")
    return destino


# --- 1. EL ARCHIVO BASE NO SE TOCA --------------------------------------


def test_guardar_NO_reescribe_el_archivo_base(config) -> None:
    """>>> LA PERDIDA QUE NO SE PODRIA DESHACER <<<"""
    base = config / "jarvis.yaml"
    antes = base.read_bytes()
    lineas_antes = antes.decode("utf-8").count("\n")

    mod.guardar({"tiempos.telegram_minutos": 9}, config_dir=config)

    assert base.read_bytes() == antes, "se reescribio jarvis.yaml"
    assert lineas_antes > 400, "el banco de comentarios se encogio"


def test_los_comentarios_del_archivo_base_siguen_ahi(config) -> None:
    """No basta con que el tamaño cuadre: se comprueba el contenido."""
    mod.guardar({"voz.wake_word.umbral": 0.55}, config_dir=config)
    texto = (config / "jarvis.yaml").read_text(encoding="utf-8")
    assert texto.count("#") > 400
    # Una frase concreta del razonamiento medido, elegida porque es de
    # las que costaron una tanda entera.
    #
    # >>> Y LA SEÑA TUVO QUE CAMBIAR (2026-09-08) <<< Antes se buscaba
    # "un enrutador de audio virtual", que es EL APARATO DEL AUTOR y por eso
    # el generador de la base lo sustituye a proposito
    # (`test_config_base.DEL_AUTOR` falla si se cuela). O sea que las dos
    # reglas eran incompatibles y la que ganaba dependia de que archivo
    # mirase el fixture. "cable virtual" tampoco vale como seña: en el
    # archivo esa expresion cae partida por un salto de linea con su "# "
    # en medio, asi que la subcadena nunca casa. La que sobrevive a la
    # generacion Y esta entera en un renglon es esta.
    assert "silencio digital" in texto


def test_lo_guardado_va_a_su_propio_archivo(config) -> None:
    mod.guardar({"tiempos.telegram_minutos": 9}, config_dir=config)
    propio = config / "ajustes.yaml"
    assert propio.is_file()
    datos = yaml.safe_load(propio.read_text(encoding="utf-8"))
    assert datos == {"tiempos.telegram_minutos": 9.0}


def test_sin_archivo_de_ajustes_no_hay_nada_cambiado(config) -> None:
    """Ausente significa "no has tocado nada", nunca otra cosa."""
    assert mod.leer(config_dir=config) == {}


def test_un_ajustes_roto_LEVANTA_en_vez_de_ignorarse(config) -> None:
    """Arrancar con unos ajustes distintos de los configurados, y
    callarselo, es peor que no arrancar. Misma regla que zonas.yaml."""
    (config / "ajustes.yaml").write_text("esto: [no cierra\n", encoding="utf-8")
    with pytest.raises(AjustesError):
        mod.leer(config_dir=config)


# --- 2. LA SUPERPOSICION LLEGA A TODOS ----------------------------------


def test_lo_guardado_pisa_al_archivo_base(config) -> None:
    """La clave plana con puntos se expande al arbol que espera el resto.

    Se usa el umbral del wake word y NO el modelo del STT a proposito: el
    modelo esta acotado a lo que hay descargado, asi que un test que le
    pusiera 'base' estaria probando que modelos tiene esta maquina y no
    la superposicion. Una cosa cada vez.
    """
    assert load_general_config(config)["voz"]["wake_word"]["umbral"] == 0.5
    mod.guardar({"voz.wake_word.umbral": 0.55}, config_dir=config)
    assert load_general_config(config)["voz"]["wake_word"]["umbral"] == 0.55


def test_pisar_una_cosa_no_borra_sus_hermanas(config) -> None:
    """El fallo obvio de una superposicion: sustituir el nodo entero.

    >>> LA COBAYA CAMBIO EL 2026-09-03, Y POR UN MOTIVO <<<
    Era `voz.wake_word.umbral`, y su hermana testigo era
    `wake_word.habilitado` -- una clave que no leia NADIE y que decia
    `false` con el wake word andando. Se quito, asi que ese bloque se
    quedo sin hermanas.

    Ahora escribe `voz.stt.ancla_vocabulario` y mira que `voz.stt.modelo`
    sobreviva: las dos las lee `voz/stt.py` de verdad. NO se usa
    `voz.audio`, que era la otra candidata obvia, por lo mismo que el
    docstring de arriba descarta el modelo del STT -- sus opciones se
    construyen ENUMERANDO EL HARDWARE, asi que el test estaria
    comprobando que tarjetas de sonido tiene esta maquina en vez de la
    superposicion. Una lista de texto no depende de nada de eso.
    """
    mod.guardar({"voz.stt.ancla_vocabulario": ["papelera", "Descargas"]},
                config_dir=config)
    bloque = load_general_config(config)["voz"]["stt"]
    assert bloque["ancla_vocabulario"] == ["papelera", "Descargas"]
    assert bloque.get("modelo") == "small", "se llevo por delante el bloque"
    # Y el bloque vecino tampoco se entera.
    assert load_general_config(config)["voz"]["wake_word"]["umbral"] == 0.5


def test_borrar_una_clave_la_devuelve_a_la_base(config) -> None:
    mod.guardar({"voz.wake_word.umbral": 0.55}, config_dir=config)
    (config / "ajustes.yaml").write_text("{}\n", encoding="utf-8")
    assert load_general_config(config)["voz"]["wake_word"]["umbral"] == 0.5


# --- 3. LO QUE NO SE PUEDE EXPRESAR -------------------------------------


def test_el_umbral_de_nadie_hablo_NO_es_configurable() -> None:
    """>>> LA PETICION DEL USUARIO, HECHA IMPOSIBLE Y NO SOLO AVISADA <<<

    Pidio cuidado con el STT y con el ancla de vocabulario: que no se le
    de a nadie la opcion de romperlo todo. La forma de cumplirlo no es un
    aviso en
    rojo: es que la combinacion mala -- ancla puesta con el umbral de sin
    ancla -- no se pueda escribir. `voz/stt.py` elige el umbral solo.
    """
    claves = {a.clave for a in mod.catalogo()}
    assert not any("umbral_sin_habla" in c or "sin_habla" in c for c in claves)


def test_un_ajuste_que_no_existe_se_rechaza(config) -> None:
    with pytest.raises(AjustesError):
        mod.guardar({"voz.stt.umbral_sin_habla": 0.6}, config_dir=config)


def test_o_entran_todos_o_no_entra_ninguno(config) -> None:
    """Una escritura a medias dejaria ajustes que el usuario no eligio."""
    with pytest.raises(AjustesError):
        mod.guardar({"tiempos.telegram_minutos": 9,
                     "voz.wake_word.umbral": 99}, config_dir=config)
    assert not (config / "ajustes.yaml").exists()


# --- 4. LA VALIDACION ---------------------------------------------------


def _numero(minimo=0.0, maximo=1.0) -> Ajuste:
    return Ajuste(clave="x", etiqueta="X", grupo="g", tipo="numero",
                  valor=0.5, por_defecto=0.5, aplica="ya",
                  minimo=minimo, maximo=maximo)


def test_un_numero_fuera_de_rango_no_pasa() -> None:
    with pytest.raises(AjustesError):
        mod.validar(_numero(), 5.0)
    with pytest.raises(AjustesError):
        mod.validar(_numero(), -1.0)
    assert mod.validar(_numero(), "0.7") == 0.7


def test_una_eleccion_de_fuera_de_la_lista_no_pasa() -> None:
    """>>> AQUI SE IMPIDE ROMPERLO DE VERDAD <<<

    Las opciones no son una sugerencia: se construyen mirando que hay en
    la maquina -- que modelos estan descargados, que dispositivos estan
    enchufados --, asi que un valor de fuera es un Jarvis que no arranca.
    """
    aj = Ajuste(clave="x", etiqueta="X", grupo="g", tipo="eleccion",
                valor="a", por_defecto="a", aplica="ya",
                opciones=[{"valor": "a", "etiqueta": "A"}])
    assert mod.validar(aj, "a") == "a"
    with pytest.raises(AjustesError):
        mod.validar(aj, "large-v3-que-no-esta-descargado")


def test_una_lista_acepta_texto_separado_por_comas() -> None:
    aj = Ajuste(clave="x", etiqueta="X", grupo="g", tipo="lista",
                valor=[], por_defecto=[], aplica="ya")
    assert mod.validar(aj, " uno,  dos ,, tres ") == ["uno", "dos", "tres"]


# --- 5. EL CATALOGO SE MIRA, NO SE INVENTA ------------------------------


def test_los_modelos_ofrecidos_son_los_que_hay_en_disco() -> None:
    """Ofrecer `large-v3` sin descargar es ofrecer un Jarvis que no
    arranca, y el fallo llegaria al siguiente arranque, no al guardar."""
    from voz.stt import modelos_descargados

    aj = next(a for a in mod.catalogo() if a.clave == "voz.stt.modelo")
    assert [o["valor"] for o in aj.opciones] == modelos_descargados()


def test_cada_ajuste_dice_CUANDO_se_nota() -> None:
    """Un ajuste que parece aplicado y no lo esta es la pantalla
    mintiendo, y en este panel ya paso una vez con las zonas."""
    for a in mod.catalogo():
        assert a.aplica in ("ya", "reabrir", "reiniciar"), a.clave


def test_los_ajustes_caros_traen_su_coste_escrito() -> None:
    """Los que pueden dejarte sordo o colar silencio como ordenes no
    pueden ir sin aviso. Es la regla del coste de las zonas."""
    caros = {"voz.audio.entrada", "voz.stt.ancla_vocabulario",
             "voz.wake_word.umbral"}
    for a in mod.catalogo():
        if a.clave in caros:
            assert a.aviso, f"{a.clave} se puede tocar sin saber que cuesta"


def test_un_dispositivo_se_normaliza_a_uno_solo() -> None:
    assert mod.uno_solo(["micro USB", "Webcam"]) == "micro USB"
    assert mod.uno_solo("sistema") == "sistema"
    assert mod.uno_solo([], "x") == "x"


# --- 5. LO QUE LA PANTALLA PROMETE AL GUARDAR ---------------------------


def test_lo_que_solo_se_lee_al_arrancar_pide_REINICIAR() -> None:
    """`sesion.modelo` y `sesion.esfuerzo` decian `reabrir`, y era falso.

    >>> POR QUE ESTE TEST EXISTE (2026-09-03) <<<
    Los dos los lee `valor_de` UNA vez, en el arranque del proceso, y van
    a `Sesion.modelo` / `Sesion.esfuerzo`, que es lo que `abrir()` mete
    en la linea de ordenes. `cambiar_a()` cierra y repunta el directorio
    SIN releerlos, y no hay ningun otro sitio que construya una `Sesion`.
    O sea que cambiar de proyecto hablando reabre la sesion con el modelo
    ANTERIOR, sin un solo error, mientras el panel decia "no se nota
    hasta reabrir la sesion".

    El fallo es MUDO en el peor sitio: el usuario pone Opus, la pantalla
    le dice que basta con reabrir, y sigue pagando y esperando lo de
    antes sin ninguna forma de notarlo.
    """
    solo_al_arrancar = {"sesion.modelo", "sesion.esfuerzo"}
    for a in mod.catalogo():
        if a.clave in solo_al_arrancar:
            assert a.aplica == "reiniciar", (
                f"{a.clave} solo se lee al arrancar el proceso: prometer "
                f"'{a.aplica}' es la pantalla mintiendo")


def test_dos_perfiles_del_mismo_nombre_se_distinguen(config) -> None:
    """La lista de voces tenia "Jarvis" dos veces (2026-09-03).

    `jarvis` y `jarvis_en` se llaman los dos Jarvis, y lo unico que los
    separaba en el desplegable era la cadena tecnica de la voz de Piper
    entre parentesis. Elegir el que no cuadra con `voz.idioma` se guarda
    sin protestar -- `validar` solo mira que el valor este en la lista --
    y Jarvis arranca despues SIN VOZ.

    No se filtran por idioma a proposito: ver `_opciones_de_perfil`. Lo
    que se pide aqui es que se puedan distinguir A LA VISTA.
    """
    opciones = mod._opciones_de_perfil(config)
    assert len(opciones) >= 2, "esta prueba necesita el catalogo real"

    etiquetas = [o["etiqueta"] for o in opciones]
    assert len(set(etiquetas)) == len(etiquetas), (
        f"hay dos voces que se leen igual: {etiquetas}")

    por_valor = {o["valor"]: o["etiqueta"] for o in opciones}
    assert "Español" in por_valor["jarvis"], por_valor["jarvis"]
    assert "English" in por_valor["jarvis_en"], por_valor["jarvis_en"]


def test_una_voz_de_idioma_desconocido_no_se_etiqueta(tmp_path) -> None:
    """Tres salidas y no dos: es / en / NO SE SABE.

    `voz/perfil.py` deja pasar una voz cuyo prefijo no reconoce -- podria
    ser una voz propia -- en vez de declararla mala. Aqui hace falta lo
    mismo: inventarle un idioma seria peor que no ponerle ninguno.
    """
    destino = tmp_path / "config"
    destino.mkdir()
    (destino / "jarvis.yaml").write_text(
        "voz:\n"
        "  perfiles:\n"
        "    propia:\n"
        "      nombre: Propia\n"
        "      tts_voz: mi_voz_casera\n",
        encoding="utf-8")
    etiqueta = mod._opciones_de_perfil(destino)[0]["etiqueta"]
    assert etiqueta == "Propia (mi_voz_casera)"
    assert "Español" not in etiqueta and "English" not in etiqueta
