"""El ritual lo escribe el usuario, no nosotros (2026-09-05).

>>> LO PIDIO EL USUARIO AL CERRAR LA SESION DEL 09-04 <<<
La frase del ritual -- "hola, en que nos quedamos?" -- la elegi yo
copiando el flujo del usuario, y el pidio que fuera suya: que cada quien
decida que se le manda a Claude Code cuando dice "continua con el
proyecto x" o "ve al proyecto x".

LAS CUATRO DECISIONES QUE LO ACOTAN, y las tomo el usuario:
  1. UNA sola frase; "continua con X" y "ve a X" siguen siendo la misma
     cosa, o sea que `atender` NO reconoce un verbo nuevo.
  2. GLOBAL, con excepcion POR PROYECTO.
  3. La frase del usuario PISA EL IDIOMA. Es una cadena; la de fabrica
     sigue teniendo una por idioma.
  4. VACIO = no mandar nada, como salida explicita.

>>> LO QUE ESTE ARCHIVO EXISTE PARA IMPEDIR, Y SON DOS COSAS <<<

(a) QUE "HEREDA" Y "NO MANDES NADA" SE COLAPSEN. Son las dos respuestas
    contrarias que caben en una caja vacia: una manda un turno entero y
    la otra no manda ninguno. Colapsarlas es el error por defecto de este
    arbol y aqui no daria error -- solo un Jarvis que abre el
    proyecto y se queda callado, o uno que habla cuando le dijiste que
    no.

(b) QUE LOS DOS CANALES VUELVAN A RESOLVERLO CADA UNO. Es literalmente
    el fallo del 2026-09-03, y la forma de evitarlo es la misma: la
    resolucion entera vive en `voz.proyecto.primera_pregunta` y los dos
    canales la LLAMAN. Hay un test que barre el codigo por eso.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nucleo.proyectos import (CLAVE_INTERCEPTA, Proyecto, guardar, leer,
                              manda_la_global)
from voz.proyecto import PRIMERA_PREGUNTA, primera_pregunta, ritual_elegido

RAIZ = Path(__file__).resolve().parent.parent


def pon_ajuste(config: Path, texto: str) -> None:
    """Escribe `proyectos.ritual` como lo escribe el panel: clave plana."""
    (config / "ajustes.yaml").write_text(
        "proyectos.ritual: " + repr(texto) + "\n", encoding="utf-8")


# --- 1. LAS TRES FUENTES, Y EL ORDEN ------------------------------------


class TestDeDondeSaleLaFrase:
    def test_sin_nada_escrito_manda_la_de_FABRICA(self, tmp_path) -> None:
        """Nadie ha tocado el ajuste: Jarvis sigue haciendo lo de siempre.

        Es el caso que mas veces se da y el que no puede romperse: la
        funcion cambio de forma, no de comportamiento por defecto.
        """
        assert primera_pregunta(config_dir=tmp_path) == PRIMERA_PREGUNTA

    def test_la_frase_del_panel_pisa_la_de_fabrica(self, tmp_path) -> None:
        pon_ajuste(tmp_path, "dime que toca hoy")
        assert primera_pregunta(config_dir=tmp_path) == "dime que toca hoy"

    def test_la_del_PROYECTO_pisa_la_del_panel(self, tmp_path) -> None:
        pon_ajuste(tmp_path, "dime que toca hoy")
        suyo = Proyecto("faro", str(tmp_path), ritual="mirate el roadmap")
        assert primera_pregunta(proyecto=suyo,
                                config_dir=tmp_path) == "mirate el roadmap"

    def test_un_proyecto_SIN_ritual_hereda_el_del_panel(self, tmp_path) -> None:
        """`None` es "no me has dicho nada de este", no "callate"."""
        pon_ajuste(tmp_path, "dime que toca hoy")
        suyo = Proyecto("faro", str(tmp_path))
        assert suyo.ritual is None
        assert primera_pregunta(proyecto=suyo,
                                config_dir=tmp_path) == "dime que toca hoy"


# --- 2. LA TERCERA SALIDA: VACIO ES UNA RESPUESTA -----------------------


class TestVacioSignificaCallarse:
    def test_el_panel_vacio_no_manda_nada(self, tmp_path) -> None:
        """Y NO cae a la de fabrica, que es el fallo facil: se comprueba
        `is not None`, no la verdad de la cadena."""
        pon_ajuste(tmp_path, "")
        assert ritual_elegido(tmp_path) == ""
        assert primera_pregunta(config_dir=tmp_path) == ""

    def test_un_proyecto_vacio_CALLA_aunque_el_panel_tenga_frase(
            self, tmp_path) -> None:
        """>>> ESTE ES EL CASO QUE SE PIERDE SI ALGUIEN SIMPLIFICA <<<

        Con `propia or elegida or fabrica` -- que es como se escribe sin
        pensarlo -- un proyecto puesto a "no me preguntes nada" heredaria
        la frase global y Jarvis hablaria igual. Sin error y sin sintoma
        hasta que lo oyes.
        """
        pon_ajuste(tmp_path, "dime que toca hoy")
        callado = Proyecto("faro", str(tmp_path), ritual="")
        assert primera_pregunta(proyecto=callado, config_dir=tmp_path) == ""

    def test_solo_espacios_cuenta_como_vacio(self, tmp_path) -> None:
        """En pantalla se ve una caja vacia, asi que tiene que significar
        lo mismo que una caja vacia. Si no, Jarvis mandaria un turno
        entero -- con su coste -- por tres espacios que nadie ve."""
        pon_ajuste(tmp_path, "   ")
        assert primera_pregunta(config_dir=tmp_path) == ""


# --- 3. LA FRASE DEL USUARIO PISA EL IDIOMA (decision 3) ----------------


class TestElIdioma:
    def test_la_de_fabrica_SI_tiene_una_por_idioma(self) -> None:
        from voz.idioma import ritual

        assert ritual("es") == PRIMERA_PREGUNTA
        assert ritual("en") == "hi, where did we leave off?"

    def test_la_tuya_se_manda_TAL_CUAL_en_los_dos(self, tmp_path) -> None:
        """Lo eligio el usuario entre pedir una frase por idioma. Es una
        cadena, asi que con la voz en ingles se manda como la escribiste;
        la etiqueta del panel lo dice, que es lo que lo hace honesto en
        vez de sorprendente."""
        pon_ajuste(tmp_path, "dime que toca hoy")
        assert primera_pregunta("es", config_dir=tmp_path) == "dime que toca hoy"
        assert primera_pregunta("en", config_dir=tmp_path) == "dime que toca hoy"


# --- 4. EL ARCHIVO: TRES ESTADOS QUE SOBREVIVEN AL VIAJE ----------------


class TestElYamlDelProyecto:
    def test_la_clave_ausente_se_lee_como_HEREDA(self, tmp_path) -> None:
        (tmp_path / "proyectos.yaml").write_text(
            CLAVE_INTERCEPTA + ": true\nproyectos:\n"
            "- alias: x\n  carpeta: " + str(tmp_path) + "\n",
            encoding="utf-8")
        assert leer(tmp_path)[0].ritual is None

    def test_la_clave_VACIA_se_lee_como_CALLATE(self, tmp_path) -> None:
        (tmp_path / "proyectos.yaml").write_text(
            CLAVE_INTERCEPTA + ": true\nproyectos:\n"
            "- alias: x\n  carpeta: " + str(tmp_path) + "\n  ritual: ''\n",
            encoding="utf-8")
        assert leer(tmp_path)[0].ritual == ""

    def test_guardar_NO_escribe_la_clave_de_quien_hereda(self, tmp_path) -> None:
        """Escribir `ritual: null` en cada fila haria que heredar y
        callarse se parecieran en el archivo, que es la distincion que
        este campo existe para mantener. Y el archivo se edita a mano."""
        guardar((Proyecto("x", str(tmp_path)),), config_dir=tmp_path)
        # >>> SE MIRA LA FILA, NO EL ARCHIVO ENTERO <<< La primera
        # version buscaba "ritual" en cualquier linea de datos y empezo a
        # fallar al llegar `ritual_manda:` a la cabecera -- un test que
        # se rompe por una clave vecina no estaba mirando lo que decia
        # mirar. Lo que importa es que la FILA no la lleve.
        import yaml

        crudo = yaml.safe_load(
            (tmp_path / "proyectos.yaml").read_text(encoding="utf-8"))
        assert "ritual" not in crudo["proyectos"][0]

    def test_la_vuelta_entera_conserva_los_tres(self, tmp_path) -> None:
        guardar((Proyecto("hereda", str(tmp_path)),
                 Proyecto("calla", str(tmp_path), ritual=""),
                 Proyecto("suya", str(tmp_path), ritual="mira el roadmap")),
                config_dir=tmp_path)
        de_vuelta = {p.alias: p.ritual for p in leer(tmp_path)}
        assert de_vuelta == {"hereda": None, "calla": "",
                             "suya": "mira el roadmap"}

    def test_un_ritual_que_no_es_texto_LEVANTA(self, tmp_path) -> None:
        from nucleo.proyectos import ProyectosError

        (tmp_path / "proyectos.yaml").write_text(
            "proyectos:\n- alias: x\n  carpeta: " + str(tmp_path) +
            "\n  ritual: 3\n", encoding="utf-8")
        with pytest.raises(ProyectosError):
            leer(tmp_path)


# --- 5. UN DECISOR, DOS CANALES (el pariente del test del 09-03) --------


class TestLosDosCanalesPreguntanAlMismoSitio:
    def test_ninguno_construye_la_frase_por_su_cuenta(self) -> None:
        """>>> ES LA MISMA REGLA QUE EL BARRIDO DE `cambiar_a` <<<

        Si un canal resolviera el ritual por su cuenta -- leyendo el
        ajuste, o cayendo a la constante --, volveriamos al 2026-09-03
        con otra forma: la misma frase mandando cosas distintas dicha que
        escrita. Los dos tienen que LLAMAR a `primera_pregunta`.
        """
        for archivo in ("voz/bucle.py", "puente/consola.py"):
            fuente = (RAIZ / archivo).read_text(encoding="utf-8")
            assert "primera_pregunta(proyecto=r.proyecto)" in fuente, archivo
            assert "PRIMERA_PREGUNTA" not in fuente, (
                archivo + " usa la constante en vez de la funcion")
            assert 'valor_de("proyectos.ritual"' not in fuente, (
                archivo + " lee el ajuste por su cuenta")

    def test_los_dos_se_CALLAN_con_la_frase_vacia(self) -> None:
        """No basta con resolverla igual: hay que no mandar el turno.

        En la voz ademas hay que CERRAR el turno de palabra, porque sin
        `Fin` el ciclo se quedaria en TRABAJANDO para siempre y el wake
        word no volveria a abrir nada -- sordera total, sin sintoma.
        """
        bucle = (RAIZ / "voz" / "bucle.py").read_text(encoding="utf-8")
        trozo = bucle[bucle.index("primera_pregunta(proyecto=r.proyecto)"):]
        trozo = trozo[:trozo.index("def _anunciar")]
        assert "if ritual:" in trozo
        assert "self.ciclo.termino()" in trozo, (
            "sin ritual no hay turno, asi que hay que cerrar el ciclo")

        consola = (RAIZ / "puente" / "consola.py").read_text(encoding="utf-8")
        trozo = consola[consola.index("def cambiar_de_proyecto"):
                        consola.index("def avisa")]
        assert "if ritual:" in trozo
        assert trozo.rstrip().endswith('return "", ""')


# --- 6. EL PANEL: QUE LO LEE ALGUIEN, Y QUE DICE LO QUE CUESTA ----------


class TestElAjuste:
    def _ajuste(self, config_dir):
        from nucleo.ajustes import catalogo

        return next(a for a in catalogo(config_dir)
                    if a.clave == "proyectos.ritual")

    def test_es_un_PARRAFO_y_no_una_linea(self, tmp_path) -> None:
        """Un prompt cabe en varias lineas, y un `input` esconde el final
        de lo que escribiste."""
        assert self._ajuste(tmp_path).tipo == "parrafo"

    def test_se_aplica_YA(self, tmp_path) -> None:
        """>>> Y ESTO SE COMPROBO MIRANDO QUIEN LO LEE, NO SUPONIENDOLO
            <<< `primera_pregunta` lo pide en cada cambio de proyecto y
        `valor_de` relee el archivo cada vez -- no hay cache --, asi que
        el valor nuevo llega al siguiente cambio de carpeta. Prometer
        `reiniciar` seria mandar a reiniciar para nada; prometer
        `reabrir` seria peor, porque ese valor se quito el 09-03 por
        mentir.
        """
        assert self._ajuste(tmp_path).aplica == "ya"

    def test_ensena_la_de_fabrica_cuando_no_hay_nada_escrito(
            self, tmp_path) -> None:
        """Una caja vacia mentiria: el ritual SI se manda hoy."""
        assert self._ajuste(tmp_path).valor == PRIMERA_PREGUNTA

    def test_ensena_LO_TUYO_cuando_lo_hay_vacio_incluido(self, tmp_path):
        pon_ajuste(tmp_path, "")
        assert self._ajuste(tmp_path).valor == ""

    def test_el_aviso_dice_QUE_CUESTA_por_nombre(self, tmp_path) -> None:
        """>>> ES LO QUE OBLIGA A REESCRIBIR ADR-0029 <<<

        Aquel justificaba que Jarvis mande este turno solo porque la
        frase era fija y de solo lectura. Editable, lo que la sostiene es
        que el texto lo pone el usuario -- no hay autoridad nueva --,
        pero SI hay algo que antes no podia pasar: esa frase ya no es una
        pregunta, puede pedir cualquier cosa, y con `auto` puesto en ese
        proyecto no pasa por ninguna puerta. Eso se dice donde se
        escribe, en el idioma de quien lo lee y sin abstracciones.
        """
        aviso = self._ajuste(tmp_path).aviso.lower()
        assert "auto mode" in aviso
        assert "puerta" in aviso
        assert "borra" in aviso, "el ejemplo concreto, no 'acciones'"

    def test_tiene_su_version_inglesa(self) -> None:
        from nucleo.textos import AJUSTES_EN

        for sufijo in ("etiqueta", "ayuda", "aviso"):
            assert "proyectos.ritual." + sufijo in AJUSTES_EN


# --- 7. EL PANEL SOLO CAMBIA LO QUE ENSENA ------------------------------


class TestGuardarDesdeElPanel:
    """>>> Y AQUI SE ARREGLO UN FALLO QUE YA ESTABA (2026-09-05) <<<

    `guardar_proyectos` rehacia los `Proyecto` desde el formulario --
    `Proyecto(alias, carpeta)` -- y el formulario no conoce `auto`. Como
    `guardar` reescribe el archivo ENTERO y `auto` nace en True, un
    proyecto puesto a `auto: false` a mano volvia a `true` la primera vez
    que alguien anadiera o quitara otro: un freno bajado por la puerta de
    atras, sin un error y sin un aviso.

    Es EXACTAMENTE la forma del fallo de `guardar_mcp` con `lanzar`
    (2026-09-01), y aparecio buscando donde meter el ritual -- que es
    buscar la misma forma en los demas sitios, funcionando.
    """

    @pytest.fixture
    def consola(self, tmp_path, monkeypatch):
        from puente.consola import Consola
        from puente.sesion import Sesion

        monkeypatch.setattr("nucleo.proyectos.CONFIG_DIR", tmp_path)
        monkeypatch.setattr("nucleo.ajustes.CONFIG_DIR", tmp_path)
        frenado = tmp_path / "frenado"
        frenado.mkdir()
        guardar((Proyecto("frenado", str(frenado), auto=False,
                          ritual="mira el roadmap"),),
                activo=True, config_dir=tmp_path)
        return Consola(Sesion(tmp_path), puerto=8797), frenado

    def test_el_panel_NO_puede_devolver_auto_a_true(self, consola) -> None:
        """La pagina no ensena `auto`, asi que la pagina no lo escribe."""
        c, frenado = consola
        otra = Path(str(frenado)).parent / "otra"
        otra.mkdir()
        r = c.guardar_proyectos({"intercepta": True, "proyectos": [
            {"alias": "frenado", "carpeta": str(frenado)},
            {"alias": "otra", "carpeta": str(otra)}]})
        assert r["ok"], r.get("motivo")
        de_disco = {p.alias: p.auto for p in leer(Path(str(frenado)).parent)}
        assert de_disco["frenado"] is False, (
            "el panel ha bajado un freno que el usuario habia puesto")
        assert de_disco["otra"] is True, "uno nuevo nace como nace en el YAML"

    def test_el_ritual_SI_se_edita_desde_la_pagina(self, consola) -> None:
        """Porque ahi SI se ensena. Es la otra mitad de la misma regla."""
        c, frenado = consola
        r = c.guardar_proyectos({"intercepta": True, "proyectos": [
            {"alias": "frenado", "carpeta": str(frenado), "ritual": ""}]})
        assert r["ok"], r.get("motivo")
        assert leer(Path(str(frenado)).parent)[0].ritual == ""

    def test_una_pagina_que_no_manda_la_clave_no_borra_el_ritual(
            self, consola) -> None:
        """La clave AUSENTE es "no me toques esto"; `null` SI es heredar.

        Sin esta distincion, una pestana de ajustes abierta desde antes
        de este cambio borraria el ritual de cada proyecto al guardar
        cualquier otra cosa.
        """
        c, frenado = consola
        r = c.guardar_proyectos({"intercepta": True, "proyectos": [
            {"alias": "frenado", "carpeta": str(frenado)}]})
        assert r["ok"], r.get("motivo")
        assert leer(Path(str(frenado)).parent)[0].ritual == "mira el roadmap"

    def test_null_SI_devuelve_a_heredar(self, consola) -> None:
        c, frenado = consola
        r = c.guardar_proyectos({"intercepta": True, "proyectos": [
            {"alias": "frenado", "carpeta": str(frenado), "ritual": None}]})
        assert r["ok"], r.get("motivo")
        assert leer(Path(str(frenado)).parent)[0].ritual is None

    def test_la_global_viaja_con_la_lista(self, consola) -> None:
        """Para que cada fila pueda decir QUE hereda sin subir a
        Avanzado a averiguarlo."""
        c, _ = consola
        assert c.proyectos()["ritual_global"] == PRIMERA_PREGUNTA


# --- 8. LA GLOBAL PUEDE MANDAR, SI TU LO DICES -------------------------


class TestElOverride:
    """>>> LO PREGUNTO EL USUARIO NADA MAS VERLO FUNCIONANDO <<<

    Nada mas verlo funcionando pregunto si la frase era global o por
    proyecto, y propuso una global opcional que pisara a las de cada
    proyecto -- a decision suya y avisando de lo que hace.

    NACE APAGADO. El orden natural es que lo concreto gane a lo general
    -- es lo que hace `modo_para` con las carpetas -- y encender esto
    deja escritas unas frases que dejan de usarse. Eso es un fallo mudo
    si no se ve, y por eso el interruptor vive EN LA SECCION DE
    PROYECTOS, junto a las filas que apaga, y cada fila pisada lo dice.
    """

    def registro(self, tmp_path, manda, ritual="mira el roadmap"):
        guardar((Proyecto("faro", str(tmp_path), ritual=ritual),),
                activo=True, config_dir=tmp_path, ritual_manda=manda)
        return leer(tmp_path)[0]

    def test_apagado_gana_la_del_proyecto(self, tmp_path) -> None:
        pon_ajuste(tmp_path, "dime que toca hoy")
        suyo = self.registro(tmp_path, False)
        assert primera_pregunta(proyecto=suyo,
                                config_dir=tmp_path) == "mira el roadmap"

    def test_encendido_gana_la_GLOBAL(self, tmp_path) -> None:
        pon_ajuste(tmp_path, "dime que toca hoy")
        suyo = self.registro(tmp_path, True)
        assert primera_pregunta(proyecto=suyo,
                                config_dir=tmp_path) == "dime que toca hoy"

    def test_encendido_y_la_global_VACIA_callan_a_todos(self, tmp_path):
        """Es coherente -- manda la global y la global es "callate" -- y
        hay que poder llegar ahi. Lo que no se puede es tropezarse con
        ello: el aviso del panel lo dice con todas las letras."""
        pon_ajuste(tmp_path, "")
        suyo = self.registro(tmp_path, True)
        assert primera_pregunta(proyecto=suyo, config_dir=tmp_path) == ""

    def test_encendido_SIN_global_escrita_manda_la_de_fabrica(self, tmp_path):
        """No es un caso raro: es lo que ve quien enciende esto sin haber
        escrito nada. Y coincide con lo que el panel ENSENA en la caja
        -- la de fabrica --, que es lo que lo hace predecible."""
        suyo = self.registro(tmp_path, True)
        assert primera_pregunta(proyecto=suyo,
                                config_dir=tmp_path) == PRIMERA_PREGUNTA

    def test_ausente_significa_APAGADO(self, tmp_path) -> None:
        """Misma regla que `intercepta_proyectos`: un archivo escrito a
        mano sin la clave no puede estrenar un override."""
        (tmp_path / "proyectos.yaml").write_text(
            CLAVE_INTERCEPTA + ": true\nproyectos:\n"
            "- alias: x\n  carpeta: " + str(tmp_path) + "\n",
            encoding="utf-8")
        assert manda_la_global(tmp_path) is False

    def test_un_archivo_que_no_se_puede_leer_NO_lo_enciende(self, tmp_path):
        """Ante la duda, no pisar lo que el usuario escribio. El motivo
        de un YAML roto lo grita `leer()`, que es quien lee de verdad."""
        (tmp_path / "proyectos.yaml").write_text("[[[", encoding="utf-8")
        assert manda_la_global(tmp_path) is False

    def test_NO_toca_las_frases_que_ya_escribiste(self, tmp_path) -> None:
        """>>> ES LA MITAD DEL DISENO <<< Encender esto SILENCIA, no
        borra: apagarlo tiene que devolverte lo que tenias. Un override
        que se lleve por delante el texto seria irreversible con un
        clic."""
        suyo = self.registro(tmp_path, True)
        assert suyo.ritual == "mira el roadmap"
        guardar((suyo,), activo=True, config_dir=tmp_path, ritual_manda=False)
        de_vuelta = leer(tmp_path)[0]
        assert de_vuelta.ritual == "mira el roadmap"
        pon_ajuste(tmp_path, "dime que toca hoy")
        assert primera_pregunta(proyecto=de_vuelta,
                                config_dir=tmp_path) == "mira el roadmap"


class TestElOverrideSeVE:
    """Un override que no se ve donde muerde es una pantalla que miente.

    Es literalmente el fallo de la barra de la cuota del 09-04: ni un
    numero mal y la pantalla diciendo lo contrario de lo que pasaba. Aqui
    seria leer "mira el roadmap" en la fila de un proyecto mientras
    Jarvis manda otra cosa.
    """

    def test_viaja_con_la_lista_para_que_las_filas_lo_digan(
            self, tmp_path, monkeypatch) -> None:
        from puente.consola import Consola
        from puente.sesion import Sesion

        monkeypatch.setattr("nucleo.proyectos.CONFIG_DIR", tmp_path)
        monkeypatch.setattr("nucleo.ajustes.CONFIG_DIR", tmp_path)
        carpeta = tmp_path / "faro"
        carpeta.mkdir()
        guardar((Proyecto("faro", str(carpeta), ritual="mira el roadmap"),),
                activo=True, config_dir=tmp_path, ritual_manda=True)
        c = Consola(Sesion(tmp_path), puerto=8795)
        assert c.proyectos()["ritual_manda"] is True

    def test_la_pagina_avisa_SOLO_en_las_filas_que_pisa(self) -> None:
        """En una fila que hereda no cambia nada, y un aviso ahi seria
        ruido justo donde el ruido tapa lo que importa."""
        pagina = (RAIZ / "puente" / "ajustes.html").read_text(encoding="utf-8")
        assert "Ahora no se usa: manda la frase de arriba." in pagina
        assert ("if (ritualManda && pr.ritual !== null "
                "&& pr.ritual !== undefined)") in pagina

    def test_la_lista_se_repinta_AL_TOCAR_el_interruptor(self) -> None:
        """Y no al guardar: entre una cosa y otra la pantalla diria que
        esas frases se usan cuando ya no. Es el motivo por el que el
        interruptor vive aqui y no en Avanzado."""
        pagina = (RAIZ / "puente" / "ajustes.html").read_text(encoding="utf-8")
        trozo = pagina[pagina.index("proyRitualManda.addEventListener"):]
        trozo = trozo[:trozo.index("});")]
        assert "ritualManda = proyRitualManda.checked;" in trozo, (
            "sin esto la lista se repinta con el valor de antes")
        assert "pintaProyectos()" in trozo

    def test_el_panel_no_puede_apagarlo_por_no_conocerlo(
            self, tmp_path, monkeypatch) -> None:
        """Misma regla que `auto`: clave ausente = no me toques esto. Una
        pestana abierta desde antes no puede apagar un override que se
        encendio despues."""
        from puente.consola import Consola
        from puente.sesion import Sesion

        monkeypatch.setattr("nucleo.proyectos.CONFIG_DIR", tmp_path)
        monkeypatch.setattr("nucleo.ajustes.CONFIG_DIR", tmp_path)
        carpeta = tmp_path / "faro"
        carpeta.mkdir()
        guardar((Proyecto("faro", str(carpeta)),), activo=True,
                config_dir=tmp_path, ritual_manda=True)
        c = Consola(Sesion(tmp_path), puerto=8796)
        r = c.guardar_proyectos({"intercepta": True, "proyectos": [
            {"alias": "faro", "carpeta": str(carpeta)}]})
        assert r["ok"], r.get("motivo")
        assert manda_la_global(tmp_path) is True


# --- 9. LA FRASE GLOBAL SE VE DONDE SE LA NOMBRA ------------------------


class TestDondeSePintaLaGlobal:
    """>>> LO REPORTO EL USUARIO MIRANDO EL PANEL (2026-09-05) <<<

    Con "Usar la de arriba en todos" encendido no habia ningun campo
    donde escribir esa frase global: no aparecia por ningun lado.

    Y no aparecia donde hacia falta: el ajuste vivia en el grupo
    `avanzado`, que NACE PLEGADO y queda media pantalla mas arriba,
    mientras el interruptor de la seccion de proyectos decia "la de
    arriba" y "la de Ajustes". O sea que la unica pista para encontrarlo
    apuntaba a algo que no se ve.

    Es el MISMO error de forma que ya me habia hecho poner el
    INTERRUPTOR en la seccion de proyectos en vez de en Avanzado -- lo
    que gobierna estas filas tiene que verse junto a estas filas --, y lo
    aplique al interruptor y no al campo que el interruptor gobierna.

    NO HAY DOS AJUSTES. Sigue habiendo uno en `nucleo/ajustes.py`; lo que
    cambia es donde se pinta su fila, con el mismo `filaDe()`. Por eso
    conserva su "¿por que?", su traduccion y su linea en
    `test_ajustes_con_lector.py`. Una copia a mano habria sido un segundo
    sitio donde mirar y un valor que se desincroniza solo.
    """

    def pagina(self):
        return (RAIZ / "puente" / "ajustes.html").read_text(encoding="utf-8")

    def test_el_hueco_esta_DENTRO_de_la_seccion_de_proyectos(self) -> None:
        pagina = self.pagina()
        seccion = pagina[pagina.index('id="seccionProyectos"'):]
        seccion = seccion[:seccion.index("</section>")]
        assert 'id="filaRitualGlobal"' in seccion, (
            "la frase global no se pinta en TUS PROYECTOS")

    def test_y_va_ENCIMA_del_interruptor_que_la_nombra(self) -> None:
        """El interruptor dice "la de arriba". Debajo, eso seria mentira
        otra vez, solo que en la otra direccion."""
        pagina = self.pagina()
        assert (pagina.index('id="filaRitualGlobal"')
                < pagina.index('id="proyRitualManda"'))

    def test_NO_se_pinta_ademas_en_su_grupo(self) -> None:
        """Pintarla en los dos sitios serian dos cajas para un valor: la
        que editas y la que no, sin forma de saber cual estas mirando."""
        pagina = self.pagina()
        assert 'if (aj.clave === CLAVE_RITUAL) continue;' in pagina

    def test_sigue_siendo_UN_ajuste_del_catalogo(self) -> None:
        """La mudanza es de sitio, no de dueño. Si alguien la sacara del
        catalogo perderia el aviso, la traduccion y el test de quien la
        lee -- las tres cosas que la hacen segura."""
        from nucleo.ajustes import catalogo

        claves = [a.clave for a in catalogo()]
        assert claves.count("proyectos.ritual") == 1

    def test_los_textos_ya_NO_mandan_a_Avanzado(self) -> None:
        """Los dos envejecieron en el mismo cambio que los dejo obsoletos:
        el aviso decia "ahi abajo en TUS PROYECTOS" estando ya dentro, y
        el interruptor decia "la de Ajustes" con el campo a un dedo."""
        from nucleo.ajustes import catalogo

        aviso = next(a for a in catalogo()
                     if a.clave == "proyectos.ritual").aviso
        assert "TUS PROYECTOS" not in aviso
        pagina = self.pagina()
        seccion = pagina[pagina.index('id="seccionProyectos"'):]
        seccion = seccion[:seccion.index("</section>")]
        assert "la de Ajustes" not in seccion
        assert "esta en Avanzado" not in seccion
