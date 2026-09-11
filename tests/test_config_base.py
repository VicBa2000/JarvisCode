"""Lo que se publica arranca solo y no lleva nada del autor.

>>> LA PREGUNTA QUE LO ORIGINA (2026-09-05) <<<
La pregunta del usuario preparando el codigo abierto: por que seguia sin
estar listo para el release, si quien lo instale no deberia configurar a
mano ningun YAML para empezar.

Se midio en vez de opinarlo (`-m eval.mirar_la_instalacion`), y la
respuesta es corta: **se publica UN archivo**, `config/jarvis.yaml`, que
es obligatorio -- sin el, `load_general_config` levanta. Los otros cinco
nacen AUSENTES y eso ya significa "nada declarado", asi que no hay que
crearlos ni copiarlos.

Lo que queda por decidir en una instalacion nueva son cuatro ajustes, y
ninguno se edita: se ELIGEN en la pantalla, dos de ellos con boton de
probar al lado. Editar un YAML y elegir en un desplegable no son lo
mismo, y este archivo existe para que la diferencia no se pierda.

>>> POR QUE LA BASE SE GENERA Y AQUI SE COMPRUEBA <<<
`config/jarvis.yaml` son 512 lineas de las que 420 son el razonamiento
medido de cada numero. Una copia a mano se queda vieja en la primera
tanda que ajuste un umbral, y el release saldria con la linea base de
agosto. Se genera con una herramienta de mantenimiento que no viaja en
el repositorio publicado, y aqui se comprueba que no ha quedado por
detras: si alguien toca el real y no regenera, esto falla.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
BASE = RAIZ / "config" / "base"

# >>> LA LISTA YA NO SE ESCRIBE AQUI <<<
# (2026-09-09.) Estaba puesta a mano y enumeraba, por su nombre, los
# proyectos, los aparatos y el apellido de quien desarrolla esto -- o
# sea que el test escrito para impedir que sus datos viajaran era el
# que los publicaba. Ahora salen de `config/privado.txt`, que esta en
# `.gitignore`, y esto SALTA donde no exista. Ver `tests/privado.py`.
from tests.privado import cuela, necesita_la_lista


def test_la_base_existe_y_es_UN_solo_archivo() -> None:
    """Y que sea uno no es casualidad: es lo unico obligatorio.

    Publicar tambien `proyectos.yaml` o `mcp.yaml` vacios seria dar a
    entender que hacen falta, y ademas pisaria la regla que ya tienen
    escrita -- "un archivo ausente significa NINGUNO, nunca todas".
    """
    assert BASE.is_dir(), (
        f"no hay {BASE}, que es la linea base de `config/jarvis.yaml` y "
        f"viaja con el repositorio: si falta, el clon esta incompleto.")
    archivos = sorted(p.name for p in BASE.iterdir() if p.is_file())
    assert archivos == ["jarvis.yaml"], (
        f"la base tiene {archivos}. Si se añade uno, hay que poder decir "
        f"por que hace falta: los demas nacen ausentes y eso ya funciona.")


@necesita_la_lista
def test_la_base_NO_lleva_datos_del_autor() -> None:
    texto = (BASE / "jarvis.yaml").read_text(encoding="utf-8").lower()
    colados = cuela(texto)
    assert not colados, (
        f"la base publica cosas del autor: {colados}. Un aparato suyo aqui "
        f"se instala en la maquina de otro, que pedira un microfono que no "
        f"tiene.")


def test_los_aparatos_de_audio_nacen_SIN_ELEGIR() -> None:
    """>>> VACIO ES LA RESPUESTA CORRECTA, NO UN HUECO POR RELLENAR <<<

    No se puede adivinar que microfono tienes, y poner el de otra maquina
    es peor que no poner ninguno. `voz/audio.py` se niega a adivinar la
    ENTRADA a proposito: 16 de los 23 endpoints medidos entregan silencio
    digital SIN dar error, asi que caer en uno por defecto seria escuchar
    para siempre sin oir nada. La SALIDA si puede seguir al sistema, y es
    asimetrico a proposito: si el audio sale por donde no es, te enteras
    al segundo.
    """
    import yaml

    datos = yaml.safe_load((BASE / "jarvis.yaml").read_text(encoding="utf-8"))
    audio = datos["voz"]["audio"]
    assert audio["entrada"] == []
    assert audio["salida"] == ["sistema"]


def test_una_instalacion_SOLO_CON_LA_BASE_levanta(tmp_path) -> None:
    """El caso de quien acaba de descargarlo. Si esto se cae, no hay
    pantalla desde la que arreglarlo -- y el catalogo ES esa pantalla."""
    from nucleo.ajustes import catalogo
    from nucleo.configuracion import load_general_config
    from nucleo.mcp import leer as mcp_leer
    from nucleo.proyectos import leer as proy_leer

    destino = tmp_path / "config"
    shutil.copytree(BASE, destino)

    assert load_general_config(destino)
    assert len(catalogo(destino)) > 0
    # Ausente significa NINGUNO, y aqui se comprueba que de verdad lo es.
    assert proy_leer(destino) == ()
    assert mcp_leer(destino) == ()


def test_lo_que_queda_por_elegir_se_ELIGE_no_se_edita(tmp_path) -> None:
    """>>> ES LA PETICION DEL USUARIO, HECHA COMPROBABLE <<<

    Los ajustes que salen vacios en una instalacion nueva tienen que
    estar TODOS en el panel, con su ayuda. Que queden por decidir no es
    el problema -- la carpeta de trabajo no se puede adivinar --; el
    problema seria que hubiera que abrir un editor de texto.
    """
    from nucleo.ajustes import catalogo

    destino = tmp_path / "config"
    shutil.copytree(BASE, destino)

    sin_elegir = [a for a in catalogo(destino) if a.valor in ("", [], None)]
    assert sin_elegir, "algo ha cambiado: antes quedaban cuatro"
    for ajuste in sin_elegir:
        assert ajuste.etiqueta, f"{ajuste.clave} sale sin rotulo"
        assert ajuste.ayuda, (
            f"{ajuste.clave} queda por elegir y no explica que es. Sin "
            f"ayuda, elegirlo en la pantalla no es mejor que editarlo a "
            f"mano.")


def test_la_base_NO_se_ha_quedado_por_detras_del_real() -> None:
    """Se regenera en una copia y se compara. Si alguien toco
    `config/jarvis.yaml` -- que es donde vive el razonamiento medido -- y
    no regenero, el release saldria con la linea base vieja."""
    # >>> Y EL GENERADOR TAMPOCO VIAJA, DESDE EL 2026-09-08 <<<
    # Salio del arbol publicado el mismo dia por su propia razon: para
    # encontrar los aparatos del autor tiene que llevarlos escritos
    # dentro, o sea que publicarlo publica lo que existe para quitar.
    # Pero este `assert` se quedo, y un archivo que no viaja no es un
    # fallo del clon: es su estado normal. **Medido el 2026-09-10**
    # extrayendo el arbol publicable a un directorio limpio y corriendo
    # la suite alli: 1 rojo, este, contra 1459 verdes. O sea que el
    # release salia con un rojo de fabrica y aqui todo estaba verde,
    # porque aqui el archivo si esta.
    # Es la misma tercera salida que la de abajo, y por el mismo motivo:
    # "no hay con que comparar" no es "la base se quedo por detras".
    guion = RAIZ / "scripts" / "generar_config_base.py"
    if not guion.is_file():
        pytest.skip(
            "no hay `scripts/generar_config_base.py`: es una herramienta "
            "de quien mantiene esto y no viaja en el repositorio "
            "publicado, porque para limpiar los aparatos del autor tiene "
            "que llevarlos escritos dentro. Sin el no hay con que "
            "regenerar la base, que es lo unico que compara esta guarda.")

    # >>> ESTA COMPROBACION ES DEL AUTOR, NO DE QUIEN INSTALA (2026-09-08)
    # `config/jarvis.yaml` dejo de viajar en el repositorio, asi que en un
    # clon ese archivo es una COPIA DE LA BASE que sembro el primer
    # arranque. Regenerar la base a partir de la base no compara nada: el
    # generador busca los bloques del hardware del autor, no los
    # encuentra y revienta en su primer `assert`. Eso salia como un rojo
    # que decia "la base se quedo por detras", que es justo lo contrario
    # de lo que pasa.
    # Tres salidas y no dos: al dia / por detras / **no hay con
    # que compararla**. La señal es un aparato del autor, porque es
    # exactamente lo que el generador sustituye: si esta, el archivo es el
    # original; si no, es la base sembrada.
    real = RAIZ / "config" / "jarvis.yaml"
    # La señal sale de `config/privado.txt`: si el archivo contiene
    # algo de esa lista, es el original del autor; si no, es la base
    # sembrada. Antes la señal era un aparato escrito aqui, y al
    # quitarlo esta guarda se puso a saltar en la maquina donde SI
    # tiene que correr -- que es la forma silenciosa de perderla.
    if not real.is_file() or not cuela(real.read_text(encoding="utf-8")):
        pytest.skip(
            "no hay un `config/jarvis.yaml` del autor con que comparar: "
            "en un clon ese archivo es la base ya sembrada. Esta guarda "
            "solo puede correr donde vive el original.")

    with tempfile.TemporaryDirectory(prefix="base_") as tmp:
        copia = Path(tmp) / "arbol"
        (copia / "config" / "base").mkdir(parents=True)
        shutil.copy2(RAIZ / "config" / "jarvis.yaml", copia / "config")
        shutil.copy2(guion, copia)
        r = subprocess.run([sys.executable, "generar_config_base.py"],
                           cwd=copia, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        recien = (copia / "config" / "base" / "jarvis.yaml").read_text(
            encoding="utf-8")

    assert recien == (BASE / "jarvis.yaml").read_text(encoding="utf-8"), (
        "`config/base/jarvis.yaml` no coincide con lo que sale de "
        "`config/jarvis.yaml`. Corre `python scripts/generar_config_base.py`.")


# --- LA SIEMBRA: nadie tiene que copiar un archivo a mano --------------


class TestSembrarLaBase:
    """>>> COPIAR A MANO ES EDITAR A MANO CON OTRO NOMBRE <<<

    `jarvis.yaml` es el unico obligatorio, y quien acaba de descargar
    esto no lo tiene. Sin sembrarlo, el primer arranque de una copia
    limpia muere con un `ConfigError` y la unica salida seria ir a
    buscar `config/base/` y copiar.
    """

    def test_la_primera_vez_la_crea_y_arranca(self, tmp_path) -> None:
        from nucleo.configuracion import load_general_config, sembrar_base

        destino = tmp_path / "config"
        assert sembrar_base(destino) == "sembrada"
        assert (destino / "jarvis.yaml").is_file()
        assert load_general_config(destino)

    def test_la_segunda_no_hace_nada(self, tmp_path) -> None:
        from nucleo.configuracion import sembrar_base

        destino = tmp_path / "config"
        sembrar_base(destino)
        assert sembrar_base(destino) == "ya_estaba"

    def test_JAMAS_pisa_el_que_ya_hay(self, tmp_path) -> None:
        """Ese archivo es la linea base MEDIDA y alguien puede haberlo
        tocado. Machacarlo al arrancar seria perder ajustes sin decir
        nada, y encima donde viven los umbrales de la voz."""
        from nucleo.configuracion import sembrar_base

        destino = tmp_path / "config"
        destino.mkdir()
        mio = "general: {esto_es_mio: si}\n"
        (destino / "jarvis.yaml").write_text(mio, encoding="utf-8")
        sembrar_base(destino)
        assert (destino / "jarvis.yaml").read_text(encoding="utf-8") == mio

    def test_sin_base_lo_DICE_en_vez_de_callarse(self, tmp_path,
                                                 monkeypatch) -> None:
        """Tercera salida: un arbol al que le falta
        `config/base/` no es un arranque limpio, es un arbol roto. Y el
        sintoma sin esto seria un `ConfigError` tres funciones mas
        abajo."""
        import nucleo.configuracion as cfg

        monkeypatch.setattr(cfg, "BASE_DIR", tmp_path / "no_existe")
        assert cfg.sembrar_base(tmp_path / "config") == "sin_base"

    def test_LOS_DOS_arranques_siembran(self) -> None:
        """La carcasa lee los ajustes ANTES de delegar en el puente, asi
        que hacerlo en un solo sitio deja fuera el camino por el que
        arranca casi todo el mundo. Es la misma forma que el `apagate`
        del 09-05: una cosa cableada en un canal y no en el otro."""
        for archivo in ("puente/__main__.py", "escritorio/__main__.py"):
            fuente = (RAIZ / archivo).read_text(encoding="utf-8")
            assert "sembrar_base()" in fuente, archivo


def test_ningun_mensaje_manda_a_EDITAR_un_yaml() -> None:
    """>>> LA PETICION, HECHA COMPROBABLE <<<

    La peticion era que quien instale esto no configure a mano ningun
    YAML para empezar. La primera pared con la que se choca alguien nuevo no
    puede contestarle con el nombre de un archivo y una clave dentro --
    y eso es exactamente lo que decia el error de "no hay carpeta de
    trabajo" hasta el 2026-09-05.

    Se miran los mensajes que se le ENSEÑAN, no los comentarios: ahi
    nombrar el archivo es correcto y hace falta.
    """
    import re

    sospechosos = []
    for archivo in ("escritorio/__main__.py", "puente/__main__.py",
                    "puente/consola.py"):
        for linea in (RAIZ / archivo).read_text(encoding="utf-8").splitlines():
            limpia = linea.strip()
            if limpia.startswith("#"):
                continue
            # Una cadena que nombre un .yaml Y una clave con puntos es la
            # firma de "abre este archivo y escribe esto dentro".
            if re.search(r'"[^"]*\.yaml[^"]*clave', limpia):
                sospechosos.append(f"{archivo}: {limpia[:70]}")
    assert not sospechosos, (
        f"estos mensajes mandan a editar un YAML: {sospechosos}")

def test_el_instalador_baja_LA_VOZ_QUE_LA_BASE_VA_A_USAR() -> None:
    """Tres sitios que dicen el mismo nombre, y tienen que coincidir.

    (2026-09-09, al construir `instalar.bat`.) El instalador baja UNA
    voz -- las cinco son 300 MB y nadie necesita cinco para empezar --,
    y `config/base/jarvis.yaml` nace con un perfil activo que usa una
    voz por su nombre. Si esos dos nombres se separan, el primer
    arranque de quien acaba de instalar esto se encuentra un perfil
    apuntando a un modelo que no esta: `voz/perfil.py` se niega a
    arrancar la voz, correctamente, y el usuario ve un Jarvis mudo
    recien instalado sin saber por que.

    El tercero es `tests/entorno.py`, que decide si esta instalacion
    es 'recien hecha' comparando lo que hay en disco contra ese mismo
    nombre. Desalinearlo dejaria la guarda mirando una voz que nadie
    baja, o sea sin dispararse nunca.
    """
    import yaml

    from scripts.bajar_modelos import VOZ_POR_DEFECTO
    from tests.entorno import VOZ_DE_FABRICA

    datos = yaml.safe_load(
        (BASE / "jarvis.yaml").read_text(encoding="utf-8"))
    voz = datos["voz"]
    activo = voz["perfiles"][voz["perfil"]]["tts_voz"]

    assert VOZ_POR_DEFECTO == activo, (
        f"el instalador baja {VOZ_POR_DEFECTO} y el perfil de fabrica "
        f"usa {activo}: quien instale esto tendra un Jarvis mudo")
    assert VOZ_DE_FABRICA == activo, (
        f"`tests/entorno.py` cree que la voz de fabrica es "
        f"{VOZ_DE_FABRICA} y es {activo}: la guarda de "
        "`necesita_todas_las_voces` no se disparara donde debe")
