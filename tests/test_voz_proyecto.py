"""Cambiar de proyecto hablando (ADR-0029, pasos 1, 2 y 6).

>>> LO QUE MAS SE PRUEBA AQUI ES QUE **NO** SE INTERCEPTE DE MAS <<<
Esta es la primera vez que el fork mira una orden hablada ANTES de
mandarla al cerebro, y la regla del proyecto es tajante: TODO pasa por
Claude Code, no hay camino rapido local. La excepcion se sostiene solo
porque cambiar el directorio de la sesion es algo que el cerebro **no
puede hacer** -- la sesion es el proceso que hay que cerrar y reabrir --,
igual que "para" (JC-0011).

Asi que el test que de verdad protege esto no es "reconoce el cambio de
proyecto": es que *"continua con el informe de ventas"* siga llegando a
Claude Code. Una interceptacion que se pase de lista se come ordenes
buenas y el usuario solo ve que Jarvis "no hace nada".

Y la segunda mitad: **no abrir la carpeta equivocada**. Lo que llega es
una TRANSCRIPCION, y el propio ADR lo dice -- "abrir la carpeta
equivocada aqui significa lanzar un agente con auto mode sobre codigo que
no era".
"""

from __future__ import annotations

import pytest

from nucleo.proyectos import (
    Cuantas,
    Proyecto,
    ProyectosError,
    guardar,
    leer,
    normalizar,
    resolver,
)
from voz.proyecto import PRIMERA_PREGUNTA, Veredicto, interpretar

REGISTRO = (
    Proyecto("nebula", r"C:\proyectos\nebula"),
    Proyecto("jarvis", r"C:\proyectos\JarvisCode"),
    Proyecto("la tienda", r"C:\proyectos\tienda-online"),
)


# --- 1. NO INTERCEPTAR DE MAS -------------------------------------------


@pytest.mark.parametrize("frase", [
    "continua con el informe de ventas",
    "borra la carpeta de descargas",
    "abre el bloc de notas y escribe informe listo",
    "cambia el nombre del archivo",
    "sigue con lo que estabas haciendo",
    "trabaja un poco mas en esto",
])
def test_una_orden_normal_LLEGA_al_cerebro(frase: str) -> None:
    """>>> EL TEST QUE PROTEGE ESA REGLA <<<

    Si esto se rompe, ordenes perfectamente buenas dejan de llegar a
    Claude Code y el usuario solo ve que Jarvis no hace nada. Por eso la
    deteccion exige el verbo **Y** la palabra "proyecto": sin ella,
    "continua con el informe" se interceptaria.
    """
    assert interpretar(frase).veredicto is Veredicto.NO_ES


@pytest.mark.parametrize("frase,nombre", [
    ("continua con el desarrollo del proyecto nebula", "nebula"),
    ("abre el proyecto jarvis", "jarvis"),
    ("cambia al proyecto nebula", "nebula"),
    # El "la" se quita al extraer, y da igual: `resolver` normaliza los
    # dos lados y "tienda" casa con el alias "la tienda". Lo comprueba el
    # test de abajo, que es lo que de verdad importa.
    ("trabajemos en el proyecto la tienda", "tienda"),
    ("vete al proyecto nebula", "nebula"),
])
def test_se_reconoce_la_peticion_y_el_nombre(frase: str, nombre: str) -> None:
    p = interpretar(frase)
    assert p.veredicto is Veredicto.CAMBIAR
    assert p.nombre == nombre


def test_un_alias_con_articulo_se_encuentra_igual() -> None:
    """Se dice "el proyecto LA tienda" y el articulo se pierde al
    extraer el nombre. No importa: `resolver` normaliza los dos lados y
    el relleno no distingue nada. Lo que se prueba es que se ABRE, no
    como quedo la cadena por el camino."""
    p = interpretar("trabajemos en el proyecto la tienda")
    r = resolver(p.nombre, proyectos=REGISTRO)
    assert r.cuantas is Cuantas.UNO
    assert r.proyecto.alias == "la tienda"


def test_una_orden_pegada_detras_no_se_cuela_en_el_nombre() -> None:
    """"abre el proyecto nebula y dime en que quedamos": el nombre es
    lo de delante. Si no se cortara, se buscaria un proyecto llamado
    "nebula y dime en que quedamos" y no habria ninguno."""
    p = interpretar("abre el proyecto nebula y dime en que quedamos")
    assert p.nombre == "nebula"


def test_pedir_cambiar_sin_decir_cual_es_SU_PROPIA_salida() -> None:
    """>>> LA TERCERA RESPUESTA <<<

    "abre el proyecto" a secas no puede caer en NO_ES: se iria al cerebro
    como una orden cualquiera y Claude Code haria lo que le pareciera con
    ella. Y tampoco en CAMBIAR sin nombre. Se pregunta.
    """
    p = interpretar("abre el proyecto")
    assert p.veredicto is Veredicto.SIN_NOMBRE
    assert p.veredicto is not Veredicto.NO_ES
    assert not p.nombre


# --- 2. NO ABRIR LA CARPETA EQUIVOCADA ----------------------------------


def test_un_nombre_a_medias_NO_abre_nada() -> None:
    """"auto" no abre "nebula". La mitad de un nombre es justo el caso
    en el que dos proyectos empiezan igual, y ahi la respuesta correcta
    es no hacer nada, no adivinar."""
    assert resolver("auto", proyectos=REGISTRO).cuantas is Cuantas.NINGUNO


def test_lo_que_no_esta_registrado_no_se_busca_por_el_disco() -> None:
    assert resolver("tienda-online-v2", proyectos=REGISTRO).cuantas is (
        Cuantas.NINGUNO)


def test_varias_candidatas_NO_se_resuelven_por_el_usuario() -> None:
    """Del propio ADR-0029: *"ante varias candidatas, se pregunta"*.
    Quedarse con la primera seria elegir justo donde equivocarse cuesta
    lanzar un agente sobre el codigo que no era."""
    registro = REGISTRO + (Proyecto("el viejo", r"C:\viejo\nebula"),)
    r = resolver("nebula", proyectos=registro)
    assert r.cuantas is Cuantas.VARIOS
    assert r.proyecto is None, "no puede haber un elegido"
    assert len(r.candidatos) == 2


def test_se_resuelve_por_el_alias_y_por_el_nombre_de_la_carpeta() -> None:
    """Uno dice el nombre de la carpeta sin pensar; registrar un alias no
    deberia obligar a repetirlo."""
    assert resolver("jarvis", proyectos=REGISTRO).proyecto.alias == "jarvis"
    assert resolver("JarvisCode", proyectos=REGISTRO).proyecto.alias == "jarvis"


def test_las_tildes_no_pierden_un_proyecto() -> None:
    """El STT escribe "informática" con tilde y un alias a mano puede no
    llevarla. Sin normalizar, el proyecto "no existe" por un acento."""
    registro = (Proyecto("informatica", r"C:\p\informatica"),)
    assert resolver("informática", proyectos=registro).cuantas is Cuantas.UNO


class TestElEspacioTampocoDistingueNada:
    """Lo reporto el usuario el 2026-09-03, y con una causa equivocada:
    creia que fallaba por la mayuscula inicial -- que el nombre del
    proyecto le llega a veces con ella y a veces sin ella, y que bastaba
    esa diferencia para que no lo encontrara.

    >>> LA MAYUSCULA NO ERA LA CAUSA, Y ESO SE MIDIO PRIMERO <<<
    `normalizar` baja el texto desde el primer dia. Lo que rompia era lo
    que va PEGADO a la mayuscula: el STT parte un nombre en CamelCase en
    dos palabras ("TorreAzul" -> "Torre Azul") y la comparacion
    llevaba los espacios dentro. El primer test de esta clase es el que
    impide que alguien "arregle" otra vez la mayuscula."""

    def test_la_MAYUSCULA_nunca_fue_el_problema(self) -> None:
        for dicho in ("nebula", "Nebula", "NEBULA", "NeBuLa"):
            assert resolver(dicho, proyectos=REGISTRO).proyecto.alias == (
                "nebula"), dicho

    def test_un_nombre_partido_en_dos_encuentra_su_proyecto(self) -> None:
        """"ne bula", "Ne Bula" y "ne-bula" son la misma carpeta:
        el guion ya lo vuelve espacio `normalizar`."""
        for dicho in ("ne bula", "Ne Bula", "ne-bula"):
            assert resolver(dicho, proyectos=REGISTRO).proyecto.alias == (
                "nebula"), dicho

    def test_y_al_reves_tambien(self) -> None:
        """La direccion contraria: el registro lo lleva partido y el STT
        lo entrega pegado. Pasa con los nombres que se ESCRIBEN juntos y
        se DICEN separados."""
        registro = (Proyecto("torre azul", r"C:\p\TorreAzul"),)
        assert resolver("TorreAzul", proyectos=registro).cuantas is (
            Cuantas.UNO)

    def test_pegar_los_espacios_NO_es_coincidencia_parcial(self) -> None:
        """>>> ESTE ES EL QUE PROTEGE ADR-0029 <<< La segunda pasada sigue
        siendo igualdad de la cadena ENTERA. Si algun dia esto pasa a
        `startswith` o a una distancia de edicion, deja de ser "o esta o
        no esta" y vuelve la busqueda difusa que el ADR descarto."""
        for dicho in ("auto", "autome", "meta", "jarvis co"):
            assert resolver(dicho, proyectos=REGISTRO).cuantas is (
                Cuantas.NINGUNO), dicho

    def test_la_pasada_EXACTA_manda_sobre_la_pegada(self) -> None:
        """Si uno casa letra por letra, ese es -- no se le suman los que
        solo casan pegados, que convertiria un UNO limpio en un VARIOS."""
        registro = REGISTRO + (Proyecto("ne bula", r"C:\otro\sitio"),)
        r = resolver("ne bula", proyectos=registro)
        assert r.cuantas is Cuantas.UNO
        assert r.proyecto.carpeta == r"C:\otro\sitio"

    def test_si_al_pegar_casan_dos_se_PREGUNTA(self) -> None:
        """La duda no se resuelve por el usuario, ni siquiera aqui. Los
        dos alias se separan por donde cae un espacio, o sea justo por lo
        unico que esta segunda pasada ignora: al pegarlos son el mismo
        nombre y ninguno casa exacto."""
        registro = (Proyecto("ne bula", r"C:\a\primero"),
                    Proyecto("neb ula", r"C:\b\segundo"))
        r = resolver("nebula", proyectos=registro)
        assert r.cuantas is Cuantas.VARIOS
        assert r.proyecto is None
        assert len(r.candidatos) == 2


def test_el_relleno_no_distingue_nada() -> None:
    assert normalizar("el proyecto de nebula") == "nebula"
    assert resolver("el proyecto nebula", proyectos=REGISTRO).cuantas is (
        Cuantas.UNO)


# --- 3. EL REGISTRO -----------------------------------------------------


def test_sin_archivo_no_hay_ningun_proyecto(tmp_path) -> None:
    """Ausente significa NINGUNO, nunca "todas las carpetas del disco"."""
    assert leer(config_dir=tmp_path) == ()


def test_ida_y_vuelta(tmp_path) -> None:
    guardar(REGISTRO, config_dir=tmp_path)
    assert [p.alias for p in leer(config_dir=tmp_path)] == [
        p.alias for p in REGISTRO]


def test_una_entrada_sin_carpeta_LEVANTA(tmp_path) -> None:
    """Un registro a medias abriria un agente sobre una ruta vacia."""
    (tmp_path / "proyectos.yaml").write_text(
        "proyectos:\n  - alias: x\n", encoding="utf-8")
    with pytest.raises(ProyectosError):
        leer(config_dir=tmp_path)


def test_una_carpeta_que_ya_no_esta_se_ve_HOY(tmp_path) -> None:
    """`existe` se calcula al pedirlo y no se guarda: un disco
    desconectado tiene que verse ahora, no cuando se escribio el YAML."""
    p = Proyecto("x", str(tmp_path / "no-existe"))
    assert p.existe is False
    assert p.a_json()["existe"] is False


def test_descubrir_carpetas_NO_las_registra(tmp_path) -> None:
    """Descubrir es barato; abrir una que nadie declaro es lo que no se
    hace. `candidatas_bajo` solo rellena una lista para el panel."""
    from nucleo.proyectos import candidatas_bajo

    (tmp_path / "uno").mkdir()
    (tmp_path / "dos").mkdir()
    (tmp_path / ".oculto").mkdir()
    halladas = candidatas_bajo(tmp_path)
    assert len(halladas) == 2
    assert leer(config_dir=tmp_path) == (), "descubrir no puede registrar"


# --- 4. EL RITUAL -------------------------------------------------------


def test_la_frase_de_fabrica_sigue_siendo_LA_MISMA() -> None:
    """>>> DEJO DE SER LA UNICA POSIBLE EL 2026-09-05, NO DE EXISTIR <<<

    ADR-0029 llamaba a este turno "la unica excepcion" a que Jarvis no
    escriba nada por su cuenta, y lo justificaba diciendo que la frase es
    fija y de solo lectura. Ya no lo es: la escribe el usuario. Lo que
    sostiene la excepcion ahora es MAS fuerte, no mas debil -- el texto
    lo pone el, asi que Jarvis sigue sin redactar nada suyo --, y esta
    constante se queda como el SUELO: lo que se manda si nadie ha dicho
    otra cosa, y lo que el panel ensena en la caja vacia.

    Que no cambie importa por una razon concreta: es lo que ya arranca
    todas las conversaciones del usuario, y moverla cambiaria en silencio
    como abre cada proyecto de quien no ha tocado el ajuste.
    """
    assert PRIMERA_PREGUNTA == "hola, en que nos quedamos?"


# --- 5. CAMBIAR LA SESION DE SITIO --------------------------------------


def test_cambiar_de_proyecto_conserva_el_objeto_sesion(tmp_path) -> None:
    """>>> POR QUE NO SE CREA OTRA SESION <<<

    La consola, la voz y el escalado tienen una referencia a ESTA. Crear
    otra obligaria a re-cablear las tres, y la que se olvidase seguiria
    hablando con la sesion vieja sin dar un solo error -- mirando un
    proyecto que ya nadie usa.
    """
    from puente.sesion import Sesion

    otra = tmp_path / "otro-proyecto"
    otra.mkdir()
    s = Sesion(tmp_path)
    antes = id(s)
    s.cambiar_a(otra)
    assert id(s) == antes
    assert s.directorio == str(otra)


def test_cambiar_de_proyecto_NO_arrastra_la_conversacion(tmp_path) -> None:
    """Es otro proyecto: arrastrar el contexto del anterior seria peor
    que empezar de cero."""
    from puente.sesion import Sesion

    otra = tmp_path / "otro"
    otra.mkdir()
    s = Sesion(tmp_path)
    s.session_id = "abc-123"
    s.cambiar_a(otra)
    assert s.session_id is None


def test_no_se_cambia_a_una_carpeta_que_no_existe(tmp_path) -> None:
    from puente.sesion import PuenteError, Sesion

    s = Sesion(tmp_path)
    with pytest.raises(PuenteError):
        s.cambiar_a(tmp_path / "esto-no-esta")
    assert s.directorio == str(tmp_path), "no puede quedarse a medias"


def test_cambiar_de_proyecto_NO_estrena_permisos(tmp_path) -> None:
    """El suelo y los MCP son de la MAQUINA y del usuario, no del
    proyecto. Si se limpiaran al cambiar de carpeta, cambiar de proyecto
    seria una forma de empezar sin proteccion."""
    from nucleo.mcp import Politica, Servidor
    from puente.sesion import Sesion

    otra = tmp_path / "otro"
    otra.mkdir()
    zonas = ("una-zona",)
    mcp = (Servidor("archivos", Politica.AUTO),)
    s = Sesion(tmp_path, zonas=zonas, servidores_mcp=mcp)
    s.cambiar_a(otra)
    assert s.zonas == zonas
    assert s.servidores_mcp == mcp


# --- 6. LO QUE FALLO EN LA PRIMERA PRUEBA REAL --------------------------


@pytest.mark.parametrize("frase", [
    "continúa con el proyecto nebula",
    "Continúa con el desarrollo del proyecto Nebula.",
    "hey jarvis continúa con el proyecto nebula",
    "sigue con el proyecto Nebula",
])
def test_con_TILDES_tambien(frase: str) -> None:
    """>>> EL FALLO QUE TUMBO ADR-0029 EN SU PRIMERA PRUEBA REAL <<<

    2026-08-27. El usuario lo configuro todo bien, dijo *"continua con el
    proyecto nebula"* y la frase se fue entera al cerebro: Claude Code
    contesto que no encontraba nada sobre Nebula en `carpetadepruebas`.

    El motivo: el STT escribe **"continúa"** con tilde -- que es como se
    escribe en español -- y el patron decia `continua`. `re.I` baja las
    mayusculas y NO toca los acentos.

    Y lo peor es que era un fallo YA CONOCIDO: se habia arreglado el dia
    antes en `voz/ventana.py` y no se barrio el resto. Este
    test existe para que el barrido quede hecho.
    """
    p = interpretar(frase)
    assert p.veredicto is Veredicto.CAMBIAR
    assert p.nombre == "nebula"


def test_hay_UN_normalizador_en_el_arbol_y_no_tres() -> None:
    """Tres formas de quitar tildes es como acaban divergiendo, y ya
    paso: `parada` normalizaba, `proyectos` normalizaba, `ventana` tenia
    su propia copia... y `proyecto` no normalizaba nada."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    propios = []
    for archivo in (raiz / "voz").glob("*.py"):
        texto = archivo.read_text(encoding="utf-8")
        # `parada.py` ES el normalizador; los demas lo importan.
        if archivo.name != "parada.py" and "unicodedata.normalize" in texto:
            propios.append(archivo.name)
    assert not propios, f"tienen su propio normalizador: {propios}"


class TestLaPuntuacionDiceDondeAcabaElNombre:
    """>>> LA FRASE ENTERA DEL USUARIO, 2026-09-03 <<<

    *"Continúa con el proyecto Faro, checate el documento que está ahí
    y generame un documento nuevo llamado Ideas.md donde metas las
    mecánicas generales del proyecto."*

    Contestaba *"no tengo ningun proyecto llamado faro checate el
    documento"*. El primer CONECTOR de esa frase es el "que" de "el
    documento QUE esta ahi", nueve palabras despues del nombre, asi que
    el nombre se comia media orden y la cola arrancaba en "esta ahi".

    Y la senal estaba en su propio reporte: el reconocedor SI habia
    transcrito la coma, y eramos nosotros quienes la tirabamos al
    normalizar. Es la MISMA forma que el "estado.md" del 1 --
    el dato vive en el texto original -- y por eso el mapa de indices ya
    """

    FRASE = ("Continúa con el proyecto Faro, checate el documento que "
             "está ahí y generame un documento nuevo llamado Ideas.md "
             "donde metas las mecánicas generales del proyecto.")

    def test_la_coma_cierra_el_nombre(self) -> None:
        assert interpretar(self.FRASE).nombre == "faro"

    def test_y_el_proyecto_se_encuentra(self) -> None:
        registro = (Proyecto("Faro", r"C:\proyectos\faro"),)
        r = resolver(interpretar(self.FRASE).nombre, proyectos=registro)
        assert r.cuantas is Cuantas.UNO

    def test_la_cola_arranca_donde_empieza_LA_ORDEN(self) -> None:
        """No a mitad de oracion. Lo que va detras de la coma es lo que
        se pidio, y llega al cerebro entero."""
        cola = interpretar(self.FRASE).cola
        assert cola.startswith("checate el documento")
        assert cola.endswith("mecánicas generales del proyecto")

    def test_la_cola_conserva_TILDES_Y_PUNTOS(self) -> None:
        """Sale del texto ORIGINAL. En el normalizado "Ideas.md" es
        "ideas md", o sea un archivo que el usuario no pidio."""
        cola = interpretar(self.FRASE).cola
        assert "Ideas.md" in cola
        assert "está ahí" in cola

    def test_UN_PUNTO_TAMBIEN_CIERRA(self) -> None:
        p = interpretar("ve al proyecto faro. checate el documento")
        assert p.nombre == "faro"
        assert p.cola == "checate el documento"

    def test_PERO_EL_PUNTO_DE_UN_ARCHIVO_NO(self) -> None:
        """>>> EL QUE SEPARA LAS DOS CLASES DE SIGNO <<< Un `.` solo
        corta si detras hay un espacio o se acaba la frase. Con la regla
        ingenua, "guardalo como estado.md" partiria el nombre del archivo
        en dos y llegaria una orden que nadie dicto."""
        p = interpretar("ve al proyecto nebula y guardalo como estado.md")
        assert p.nombre == "nebula"
        assert p.cola == "guardalo como estado.md"

    def test_el_punto_y_coma_y_los_dos_puntos_tambien_cierran(self) -> None:
        for frase, cola in (
            ("ve al proyecto faro; mira el readme", "mira el readme"),
            ("ve al proyecto faro: mira el readme", "mira el readme"),
        ):
            p = interpretar(frase)
            assert p.nombre == "faro", frase
            assert p.cola == cola, frase

    def test_gana_el_corte_MAS_TEMPRANO_de_los_dos(self) -> None:
        """Si el conector va ANTES que el signo, sigue mandando el
        conector: el que cierra el nombre es el primero que aparece, no
        una clase de corte por encima de la otra."""
        p = interpretar("ve al proyecto nebula y arregla el readme, "
                        "que esta viejo")
        assert p.nombre == "nebula"
        assert p.cola.startswith("arregla el readme")

    def test_una_coma_PEGADA_al_verbo_no_deja_el_nombre_vacio(self) -> None:
        """Sin nombre se PREGUNTA: no se abre nada y tampoco se
        manda la frase al cerebro como si no fuera un cambio."""
        p = interpretar("ve al proyecto, mira el readme")
        assert p.veredicto is Veredicto.SIN_NOMBRE


class TestLaColaDeLaFraseYaNoSeTira:
    """>>> LA ORDEN DICTADA QUE DESAPARECIA SIN DEJAR RASTRO <<<

    Lo reporto el usuario el 2026-09-01: la frase SI abrio el proyecto y
    despues Jarvis pregunto el ritual, o sea que atendio lo primero que
    le dijo y se salto entera la segunda instruccion de la misma frase.

    `interpretar` cortaba el nombre en el primer conector y lo de detras
    no iba a ninguna parte: `Peticion` no tenia donde guardarlo. La frase
    entera se convertia en un cambio de carpeta mas el ritual. Sin error,
    sin linea en el log, y con Jarvis contestando algo razonable a otra
    pregunta -- que es la peor forma que puede tener un fallo en esta
    capa, porque parece que funciona.
    """

    def test_la_frase_del_usuario_entera(self) -> None:
        p = interpretar("Ve al proyecto Epsilon y escribeme un documento "
                        "que resuma en que punto esta y guardalo como "
                        "estado.md")
        assert p.nombre == "epsilon"
        assert p.cola.startswith("escribeme un documento")
        assert p.cola.endswith("estado.md")

    def test_EL_PUNTO_DEL_NOMBRE_DE_ARCHIVO_SOBREVIVE(self) -> None:
        """>>> POR ESTO LA COLA SALE DEL ORIGINAL Y NO DEL NORMALIZADO <<<

        `normalizar` cambia la puntuacion por espacios, asi que ahi
        "estado.md" es "estado md". Mandar eso al cerebro es pedirle que
        cree un archivo que el usuario no dijo, y el usuario lo
        descubriria buscando un archivo que no existe.
        """
        p = interpretar("abre el proyecto nebula y guardalo como notas.md")
        assert "notas.md" in p.cola
        assert "notas md" not in p.cola

    def test_las_mayusculas_y_las_tildes_tambien(self) -> None:
        """Lo que viaja es lo que dijiste, no una version aplanada."""
        p = interpretar("ve al proyecto Redactor y dime qué falta en la "
                        "Fase 2")
        assert "qué falta" in p.cola
        assert "Fase 2" in p.cola

    def test_sin_cola_no_hay_cola(self) -> None:
        """El caso que YA funcionaba, y que no puede romperse: la frase
        literal sin nada detras sigue disparando el ritual."""
        for frase in ("continua con el proyecto nebula",
                      "continua con el desarrollo del proyecto nebula",
                      "cambiate al proyecto redactor"):
            assert interpretar(frase).cola == ""

    @pytest.mark.parametrize("conector", ["y", "luego", "despues", "para",
                                          "que"])
    def test_todos_los_conectores(self, conector) -> None:
        p = interpretar(f"abre el proyecto nebula {conector} dime la hora")
        assert p.nombre == "nebula"
        assert p.cola == "dime la hora"

    def test_el_nombre_no_se_lleva_la_cola_por_delante(self) -> None:
        """El desplazamiento importa: `COLGANTES` se come "el"/"del" por
        delante, y sin contar esas letras la cola saldria cortada a mitad
        de palabra -- que es peor que no tenerla, porque viajaria."""
        p = interpretar("ve al proyecto del epsilon y crea un informe")
        assert p.nombre == "epsilon"
        assert p.cola == "crea un informe"
