"""Tests del cableado del suelo (JC-0007) al puente.

Lo que se comprueba aqui es que el suelo LLEGA a la linea de comandos y
que el puente se niega a arrancar cuando no esta en condiciones. Que las
reglas MUERDAN no se puede comprobar sin el binario: eso es
`verificar_con_senuelo`, y su test vive en la suite `lento`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from puente.consola import Consola
from puente.sesion import Sesion
from puente.suelo import (
    EstadoSuelo,
    Senuelo,
    Suelo,
    huella,
    preparar,
    sellar,
    verificar_con_senuelo,
    zona_para_senuelo,
)
from puente.politica import Veredicto, decidir
from puente.protocolo import Puerta
from nucleo.configuracion import ConfigError
from seguridad.zonas import (
    Eje, Zona, detectar, guardar_eleccion, leer_eleccion, reglas_deny,
    validar_reglas,
)

# No es un mock del suelo: es la version del binario, que estos casos no
# miden y que cuesta 1,1 s preguntarla (medido).
VERSION_FALSA = "2.1.241-en-pruebas"


# --------------------------------------------------------------------
# El suelo llega a la linea de comandos
# --------------------------------------------------------------------

class TestLineaDeComandos:
    def test_el_suelo_viaja_como_settings(self, tmp_path):
        ajustes = tmp_path / "suelo.json"
        sesion = Sesion(tmp_path, ajustes=ajustes)
        orden = sesion.orden
        assert "--settings" in orden
        assert orden[orden.index("--settings") + 1] == str(ajustes)

    def test_sin_suelo_no_se_inventa_ningun_flag(self, tmp_path):
        """Una ausencia se declara, no se simula. Una sesion sin
        suelo tiene que VERSE en la linea, no traer un archivo vacio."""
        orden = Sesion(tmp_path).orden
        assert "--settings" not in orden

    def test_el_suelo_va_antes_de_lo_que_se_pase_a_mano(self, tmp_path):
        """Si `extra` pudiera colarse delante, un flag suelto taparia el
        suelo y la linea no lo delataria."""
        sesion = Sesion(tmp_path, ajustes=tmp_path / "s.json",
                        extra=("--add-dir", "C:\\otra"))
        orden = sesion.orden
        assert orden.index("--settings") < orden.index("--add-dir")

    def test_la_puerta_sigue_puesta_con_suelo(self, tmp_path):
        """El suelo es OTRA capa, no un sustituto: sin la puerta no hay
        consentimiento, y sin el suelo no hay nada aguas arriba."""
        orden = Sesion(tmp_path, ajustes=tmp_path / "s.json").orden
        assert "--permission-prompt-tool" in orden
        assert orden[orden.index("--permission-mode") + 1] == "default"


# --------------------------------------------------------------------
# Preparar: tres estados, y el archivo que se escribe
# --------------------------------------------------------------------

class TestPreparar:
    def test_escribe_un_json_con_solo_denegaciones_de_escritura(self, tmp_path):
        suelo = preparar(tmp_path / "suelo.json", version=VERSION_FALSA)
        datos = json.loads(suelo.archivo.read_text(encoding="utf-8"))
        reglas = datos["permissions"]["deny"]
        assert reglas
        assert all(r.startswith(("Write(", "Edit(")) for r in reglas)
        assert not any(r.startswith("Read(") for r in reglas), (
            "el eje 1 permite LEER: un Read aqui rompe el caso del driver cuda")

    def test_sin_sello_queda_SIN_VERIFICAR_no_LISTO(self, tmp_path):
        """El estado por defecto de unas reglas recien escritas es
        'nadie ha probado que muerdan', y ese es el punto del modulo."""
        suelo = preparar(tmp_path / "suelo.json", sello=tmp_path / "sello", version=VERSION_FALSA)
        assert suelo.estado is EstadoSuelo.SIN_VERIFICAR
        assert suelo.estado.se_puede_arrancar

    def test_un_sello_de_la_misma_huella_lo_deja_LISTO(self, tmp_path):
        sello = tmp_path / "sello"
        primero = preparar(tmp_path / "suelo.json", sello=sello, version=VERSION_FALSA)
        sellar(sello, primero.huella)
        segundo = preparar(tmp_path / "suelo.json", sello=sello, version=VERSION_FALSA)
        assert segundo.estado is EstadoSuelo.LISTO

    def test_un_sello_de_otra_huella_no_vale(self, tmp_path):
        sello = tmp_path / "sello"
        sellar(sello, "0000000000000000")
        suelo = preparar(tmp_path / "suelo.json", sello=sello, version=VERSION_FALSA)
        assert suelo.estado is EstadoSuelo.SIN_VERIFICAR

    def test_cambiar_el_binario_invalida_el_sello(self):
        """JC-0003 ya caduco una vez asi: el binario paso de 2.1.239 a
        2.1.241 sin avisar. Un sello eterno es peor que ninguno."""
        reglas = ["Write(C:\\Windows\\**)"]
        assert huella(reglas, "2.1.239") != huella(reglas, "2.1.241")

    def test_cambiar_las_zonas_invalida_el_sello(self):
        assert (huella(["Write(C:\\Windows\\**)"], "2.1.241")
                != huella(["Write(C:\\Windows\\**)", "Write(E:\\Windows\\**)"],
                          "2.1.241"))

    def test_una_version_ilegible_no_se_trata_como_da_igual(self):
        assert huella([], "desconocida") != huella([], "2.1.241")


class TestInseguro:
    def _suelo_roto(self, motivo: str) -> Suelo:
        return Suelo(estado=EstadoSuelo.INSEGURO, motivo=motivo)

    def test_inseguro_no_arranca(self):
        assert not self._suelo_roto("las letras cambiaron").estado.se_puede_arrancar

    def test_los_otros_dos_si_arrancan(self):
        assert EstadoSuelo.LISTO.se_puede_arrancar
        assert EstadoSuelo.SIN_VERIFICAR.se_puede_arrancar

    def test_un_suelo_inseguro_no_deja_archivo_que_parezca_bueno(self, tmp_path):
        """Si dejara el JSON escrito, alguien podria lanzarlo a mano
        creyendo que vale."""
        assert self._suelo_roto("lo que sea").archivo is None


# --------------------------------------------------------------------
# El senuelo
# --------------------------------------------------------------------

class TestSenuelo:
    def test_elige_una_zona_de_verdad_no_una_carpeta_comoda(self, tmp_path):
        """El senuelo tiene que probar que el patron cubre SU objetivo.
        En una carpeta temporal solo probaria que la forma del patron
        funciona, que ya se sabe y es otra pregunta."""
        casa = tmp_path / ".claude"
        casa.mkdir()
        zonas = (Zona(str(tmp_path / "otra"), "cualquiera", obligatoria=True),
                 Zona(str(casa), "la config", obligatoria=True))
        elegida = zona_para_senuelo(zonas)
        assert elegida is not None and elegida.ruta == str(casa)

    def test_si_no_hay_donde_plantarlo_lo_dice_en_vez_de_aprobar(self, tmp_path):
        suelo = Suelo(estado=EstadoSuelo.SIN_VERIFICAR, motivo="",
                      archivo=tmp_path / "s.json", zonas=())
        veredicto, motivo = verificar_con_senuelo(sesion=None, suelo=suelo)
        # NO_SE_SABE y no NO_MUERDE: sin sitio donde plantarlo no se ha
        # probado nada, que no es lo mismo que haber probado y fallado.
        assert veredicto is Senuelo.NO_SE_SABE
        assert not veredicto.se_puede_arrancar
        assert "no se puede demostrar" in motivo

    def test_no_hay_zona_para_senuelo_devuelve_None(self, tmp_path):
        assert zona_para_senuelo(()) is None


# --------------------------------------------------------------------
# El lanzador se planta. Es la diferencia entre `Sesion` y `-m puente`.
# --------------------------------------------------------------------

class TestElLanzadorSePlanta:
    """El camino INSEGURO no se puede provocar de verdad sin cambiar las
    letras de unidad de la maquina, asi que se comprueba aqui: que el
    lanzador MIRA el estado y se planta, y que no llega a abrir nada.
    """

    def _puerto_libre(self, lanzador, monkeypatch):
        """El cerrojo de JC-0010 mira el puerto DE VERDAD, y estos tests
        no van de eso.

        Se descubrio el 2026-08-25 con el Jarvis del usuario corriendo en
        el 8731: los dos tests de aqui empezaron a fallar con "ya hay un
        Jarvis escuchando", que es el cerrojo haciendo su trabajo. Un
        test que depende de si la maquina tiene algo abierto no mide lo
        que dice medir. El cerrojo tiene los suyos en
        `tests/test_puente_cerrojo.py`.
        """
        from puente.suelo import QuienTieneElPuerto

        monkeypatch.setattr(
            lanzador, "quien_tiene_el_puerto",
            lambda _p: (QuienTieneElPuerto.LIBRE, "libre"))

    def test_con_el_suelo_inseguro_no_abre_sesion_ninguna(self, tmp_path, monkeypatch):
        import puente.__main__ as lanzador

        self._puerto_libre(lanzador, monkeypatch)
        abiertas = []
        monkeypatch.setattr(lanzador, "preparar", lambda **_: Suelo(
            estado=EstadoSuelo.INSEGURO,
            motivo="las letras de unidad ya no son las mismas"))
        monkeypatch.setattr(lanzador, "Sesion",
                            lambda *a, **k: abiertas.append(1))
        monkeypatch.setattr("sys.argv", ["puente", str(tmp_path)])

        assert lanzador.main() == 3
        assert not abiertas, "se abrio una sesion con el suelo roto"

    def test_no_abre_ninguna_sesion_al_arrancar(self, tmp_path, monkeypatch):
        """EL PUENTE ARRANCA MUDO, y es la propiedad que hace que esto
        pueda vivir en el inicio de Windows: mientras nadie pide nada, no
        hay proceso de 337 MB, no se paga ningun turno, y NO HA SALIDO
        NADA DE LA MAQUINA."""
        import puente.__main__ as lanzador

        self._puerto_libre(lanzador, monkeypatch)
        abiertas = []

        class SesionFalsa:
            def __init__(self, *a, **k):
                self.viva = False
            def abrir(self):
                abiertas.append(1)
            def cerrar(self):
                pass

        class ConsolaFalsa:
            def __init__(self, *a, **k):
                self.al_primer_turno = None
                self.suelo = None
            def servir(self, **_):
                raise KeyboardInterrupt   # corta el bucle de espera
            def parar(self):
                pass

        monkeypatch.setattr(lanzador, "preparar", lambda **_: Suelo(
            estado=EstadoSuelo.SIN_VERIFICAR, motivo="recien generado",
            archivo=tmp_path / "s.json"))
        monkeypatch.setattr(lanzador, "Sesion", SesionFalsa)
        monkeypatch.setattr(lanzador, "Consola", ConsolaFalsa)
        monkeypatch.setattr("sys.argv", ["puente", str(tmp_path)])

        with pytest.raises(KeyboardInterrupt):
            lanzador.main()
        assert not abiertas, (
            "se abrio Claude Code al arrancar: eso es un binario de 337 MB "
            "vivo todo el dia sin que nadie haya pedido nada")


class TestLaPrimeraOrden:
    """Donde el asistente deja de ser local, y donde se paga el senuelo.

    Antes esto pasaba al arrancar. Se movio aqui para que la app pueda
    estar en el inicio de Windows sin gastar un turno en cada boot
    posterior a una autoactualizacion de `claude`.
    """

    def test_sin_nadie_que_sepa_abrirla_se_dice_en_vez_de_fingir(self, tmp_path):
        """La tercera salida: no es "abierta" ni "se abrio", es
        "no se pudo". Colapsarla contra las otras dos mandaria el turno a
        una sesion muerta."""
        consola = Consola(Sesion(tmp_path))
        listo, porque = consola.asegurar_sesion()
        assert listo is False
        assert "nadie sabe abrirla" in porque

    def test_la_abre_una_sola_vez(self, tmp_path):
        consola = Consola(Sesion(tmp_path))
        llamadas = []
        consola.al_primer_turno = lambda: (llamadas.append(1), (True, "ok"))[1]

        assert consola.asegurar_sesion() == (True, "ok")
        assert len(llamadas) == 1

    def test_si_ya_estaba_viva_no_se_vuelve_a_abrir(self, tmp_path):
        """Abrir dos veces dejaria un proceso huerfano con la puerta
        colgando: nadie contestaria sus aprobaciones y esperaria para
        siempre (JC-0003 midio que una puerta sin contestar no vence)."""
        class SesionViva(Sesion):
            @property
            def viva(self):
                return True

        consola = Consola(SesionViva(tmp_path))
        consola.al_primer_turno = lambda: pytest.fail(
            "no se puede reabrir una sesion que ya esta viva")
        listo, _ = consola.asegurar_sesion()
        assert listo

    def test_si_el_suelo_no_muerde_el_turno_NO_se_manda(self, tmp_path):
        """El caso que antes mataba el arranque. Ahora el usuario tiene la
        consola delante, escribe, y se le dice que no en vez de dejar
        correr la orden con un suelo que no protege."""
        mandados = []

        class SesionFalsa(Sesion):
            def mandar(self, texto):
                mandados.append(texto)

        consola = Consola(SesionFalsa(tmp_path))
        consola.al_primer_turno = lambda: (False, "las reglas no hacen nada")
        listo, porque = consola.asegurar_sesion()
        assert listo is False
        assert not mandados
        assert "no hacen nada" in porque


# --------------------------------------------------------------------
# Que se vea. Un suelo invisible no se distingue de no tenerlo.
# --------------------------------------------------------------------

class TestLoQueVeLaConsola:
    def test_sin_suelo_la_pagina_lo_DICE(self, tmp_path):
        consola = Consola(Sesion(tmp_path))
        estado = consola.estado()["suelo"]
        assert estado["estado"] == "sin_suelo"
        assert estado["zonas"] == 0

    def test_con_suelo_se_ve_el_estado_y_cuantas_zonas(self, tmp_path):
        suelo = preparar(tmp_path / "suelo.json", version=VERSION_FALSA)
        consola = Consola(Sesion(tmp_path, ajustes=suelo.archivo), suelo=suelo)
        estado = consola.estado()["suelo"]
        assert estado["estado"] == suelo.estado.value
        assert estado["zonas"] == len(suelo.zonas) > 0
        assert estado["motivo"]

    def test_el_estado_sigue_siendo_serializable(self, tmp_path):
        suelo = preparar(tmp_path / "suelo.json", version=VERSION_FALSA)
        consola = Consola(Sesion(tmp_path, ajustes=suelo.archivo), suelo=suelo)
        json.dumps(consola.estado())


# --------------------------------------------------------------------
# DENEGAR: el suelo aplicado tambien en nuestro lado
# --------------------------------------------------------------------

class TestZonasEnLaPolitica:
    """El suelo se aplica aqui ademas de en `--settings`, y no sobra.

    Medido el 2026-08-24: hay configuraciones en las que una regla
    `Write(<absoluta>)` de `permissions.deny` NO bloquea. Se reprodujo
    cinco veces contra el binario, y CUAL ES LA VARIABLE QUE LO GOBIERNA
    QUEDO SIN AISLAR -- la primera hipotesis (la barra de la ruta) se
    comprobo y era falsa. Mientras siga sin saberse, esta capa es la
    unica que se puede razonar, porque decide sobre la ruta normalizada
    y su codigo esta aqui.
    """

    def _puerta(self, herramienta, ruta):
        return Puerta(id_peticion="x", herramienta=herramienta,
                      entrada={"file_path": ruta}, descripcion="", id_uso="u")

    def _zona_sistema(self):
        return (Zona(r"C:\Windows", "el sistema", obligatoria=True),)

    def _zona_privada(self):
        return (Zona(r"C:\Users\alguien\Documents", "tus documentos",
                     obligatoria=False, eje=Eje.PRIVADA),)

    @pytest.mark.parametrize("ruta", [
        r"C:\Windows\System32\hosts",
        "C:/Windows/System32/hosts",
        "C:/Windows/../Windows/System32/hosts",
        r"c:\windows\system32\hosts",
    ])
    def test_escribir_en_sistema_se_deniega_escriba_como_escriba(self, ruta):
        """Las cuatro formas nombran el mismo archivo. Si alguna se colara,
        el suelo protegeria segun como le diera por escribirla al modelo,
        que es un fallo abierto INTERMITENTE: peor que uno constante,
        porque una prueba puede salir bien y el caso real salir mal."""
        decision = decidir(self._puerta("Write", ruta), r"C:\proyectos",
                           zonas=self._zona_sistema())
        assert decision.veredicto is Veredicto.DENEGAR, ruta
        assert decision.regla == "zona_de_sistema"

    def test_leer_el_sistema_sigue_permitido(self):
        """Es medio producto: "que version de driver cuda tengo" escanea
        archivos de sistema, y leerlos no rompe nada."""
        decision = decidir(
            self._puerta("Read", "C:/Windows/System32/drivers/x.sys"),
            r"C:\proyectos", zonas=self._zona_sistema())
        assert decision.veredicto is Veredicto.PERMITIR

    @pytest.mark.parametrize("herramienta", ["Read", "Write", "Edit"])
    def test_en_zona_privada_ni_leer(self, herramienta):
        """El eje 2 no protege la maquina: protege que el contenido no
        VIAJE. Permitir la lectura lo vaciaria de sentido."""
        decision = decidir(
            self._puerta(herramienta, "C:/Users/alguien/Documents/secreto.pdf"),
            r"C:\proyectos", zonas=self._zona_privada())
        assert decision.veredicto is Veredicto.DENEGAR
        assert decision.regla == "zona_privada"

    def test_denegar_no_pregunta(self):
        """El suelo es FIJO. Preguntar seria ofrecer un "si" que no existe,
        y ensenaria al usuario que el suelo se negocia."""
        assert not Veredicto.DENEGAR.hay_que_preguntar
        assert Veredicto.ENDURECER.hay_que_preguntar
        assert Veredicto.NO_SE_SABE.hay_que_preguntar

    def test_sin_zonas_no_cambia_nada(self):
        """Las sesiones sin zonas -- decenas, en los tests -- no deben
        empezar a denegar por sorpresa."""
        decision = decidir(self._puerta("Write", r"C:\Windows\System32\hosts"),
                           r"C:\proyectos")
        assert decision.veredicto is not Veredicto.DENEGAR

    def test_fuera_de_toda_zona_se_decide_como_siempre(self):
        decision = decidir(
            self._puerta("Write", r"C:\proyectos\JarvisCode\x.py"),
            r"C:\proyectos\JarvisCode", zonas=self._zona_sistema())
        assert decision.veredicto is Veredicto.PERMITIR


# --------------------------------------------------------------------
# La regla inerte. Media sesion de sondas costo descubrirla.
# --------------------------------------------------------------------

class TestLaReglaQueDeVerdadMuerde:
    """`Edit(...)` gobierna la escritura; `Write(...)` sola es INERTE.

    A/B medido el 2026-08-24 contra `claude 2.1.241`, mismo destino, misma
    sesion, cambiando solo el conjunto de reglas:

        solo Write(...)          la puerta salta y EL ARCHIVO SE ESCRIBE
        solo Edit(...)           BLOQUEADO, sin puerta
        Write(...) + Edit(...)   BLOQUEADO, sin puerta

    Es la peor forma posible de fallo: no da error, no avisa, y el JSON se
    lee perfectamente valido. Estos tests estan para que nadie vuelva a
    generar un suelo decorativo por simplificar la lista de reglas.
    """

    def test_toda_zona_lleva_su_Edit(self):
        zonas = [Zona(r"C:\Windows", "el sistema", obligatoria=True)]
        reglas = reglas_deny(zonas)
        assert r"Edit(C:\Windows\**)" in reglas

    def test_quitar_los_Edit_deja_el_suelo_invalido(self):
        """Si esto pasara, el suelo se generaria sin nada que lo delate."""
        zonas = [Zona(r"C:\Windows", "el sistema", obligatoria=True)]
        solo_write = [r for r in reglas_deny(zonas) if not r.startswith("Edit(")]
        vale, motivo = validar_reglas(zonas, solo_write)
        assert vale is False
        assert "Edit" in motivo

    def test_una_zona_privada_sin_Read_es_invalida(self):
        """Se ofreceria como 'ni leer ni escribir' permitiendo la lectura,
        que es justo lo que el eje 2 existe para impedir."""
        zonas = [Zona(r"C:\Users\alguien\Documents", "tus documentos",
                      obligatoria=False, eje=Eje.PRIVADA)]
        sin_read = [r for r in reglas_deny(zonas) if not r.startswith("Read(")]
        vale, motivo = validar_reglas(zonas, sin_read)
        assert vale is False
        assert "Read" in motivo

    def test_las_reglas_de_produccion_son_validas(self):
        obligatorias, _ = detectar()
        vale, motivo = validar_reglas(obligatorias, reglas_deny(obligatorias))
        assert vale, motivo

    def test_preparar_se_niega_si_las_reglas_no_protegen(self, tmp_path, monkeypatch):
        """El suelo INSEGURO no es solo para las letras de unidad: unas
        reglas que no pueden hacer nada tampoco arrancan."""
        import puente.suelo as suelo_mod
        monkeypatch.setattr(suelo_mod, "validar_reglas",
                            lambda *_: (False, "sin Edit(...)"))
        suelo = suelo_mod.preparar(tmp_path / "suelo.json", version=VERSION_FALSA)
        assert suelo.estado is EstadoSuelo.INSEGURO
        assert not suelo.estado.se_puede_arrancar
        assert suelo.archivo is None, (
            "un suelo que no protege no debe dejar un JSON que parezca bueno")


# --------------------------------------------------------------------
# La eleccion del usuario: lo que se guarda y lo que NO se supone
# --------------------------------------------------------------------

class TestEleccionDelUsuario:
    def test_sin_archivo_no_hay_ninguna_aceptada(self, tmp_path):
        """Un archivo que no existe significa "ninguna", nunca "todas".

        Leer una config ausente como consentimiento es como acaba
        bloqueada la carpeta Documentos de alguien que no marco nada.
        """
        assert leer_eleccion(config_dir=tmp_path) == set()

    def test_ida_y_vuelta(self, tmp_path):
        guardar_eleccion([r"C:\ProgramData"], config_dir=tmp_path)
        assert leer_eleccion(config_dir=tmp_path) == {
            os.path.normcase(os.path.normpath(r"C:\ProgramData"))}

    def test_desmarcar_borra_de_verdad(self, tmp_path):
        """El archivo ES la eleccion. Si se fusionara en vez de
        reescribirse, desmarcar seria imposible y nadie lo notaria."""
        guardar_eleccion([r"C:\ProgramData", r"C:\Otra"], config_dir=tmp_path)
        guardar_eleccion([r"C:\Otra"], config_dir=tmp_path)
        assert leer_eleccion(config_dir=tmp_path) == {
            os.path.normcase(os.path.normpath(r"C:\Otra"))}

    def test_una_lista_vacia_se_guarda_como_vacia(self, tmp_path):
        guardar_eleccion([r"C:\ProgramData"], config_dir=tmp_path)
        guardar_eleccion([], config_dir=tmp_path)
        assert leer_eleccion(config_dir=tmp_path) == set()

    def test_un_archivo_malformado_no_se_ignora(self, tmp_path):
        """Arrancar con un suelo distinto del que el usuario configuro, y
        callarselo, es peor que no arrancar."""
        (tmp_path / "zonas.yaml").write_text(
            "opcionales_aceptadas: C:\\ProgramData\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            leer_eleccion(config_dir=tmp_path)

    def test_lo_aceptado_entra_en_el_suelo_con_sus_reglas(self, tmp_path):
        antes = preparar(tmp_path / "s.json", config_dir=tmp_path,
                         version=VERSION_FALSA)
        opcional = next((z for z in antes.opcionales), None)
        if opcional is None:
            pytest.skip("esta maquina no ofrece ninguna zona opcional")
        guardar_eleccion([opcional.ruta], config_dir=tmp_path)
        despues = preparar(tmp_path / "s.json", config_dir=tmp_path,
                           version=VERSION_FALSA)
        assert len(despues.zonas) == len(antes.zonas) + 1
        assert any(opcional.ruta in r for r in despues.reglas)

    def test_lo_ofrecido_y_no_aceptado_no_genera_nada(self, tmp_path):
        """Una zona ofrecida no es una zona. Si generara reglas, marcar la
        casilla no cambiaria nada y desmarcarla tampoco."""
        suelo = preparar(tmp_path / "s.json", config_dir=tmp_path,
                         version=VERSION_FALSA)
        for zona in suelo.opcionales:
            assert not any(zona.ruta in r for r in suelo.reglas)


# --------------------------------------------------------------------
# La UI: lo que se ve, y lo que se promete al guardar
# --------------------------------------------------------------------

class TestPanelDeZonas:
    def _consola(self, tmp_path):
        suelo = preparar(tmp_path / "s.json", config_dir=tmp_path,
                         version=VERSION_FALSA)
        sesion = Sesion(tmp_path, ajustes=suelo.archivo, zonas=suelo.zonas)
        return Consola(sesion, suelo=suelo), sesion

    def test_se_ven_tambien_las_obligatorias(self, tmp_path):
        """No se pueden desmarcar, pero el usuario tiene derecho a ver de
        que se le protege: un suelo que no se puede inspeccionar se parece
        demasiado a uno que no existe."""
        consola, _ = self._consola(tmp_path)
        datos = consola.zonas()
        assert datos["hay_suelo"]
        assert len(datos["obligatorias"]) > 0

    def test_toda_opcional_llega_con_su_coste_y_su_eje(self, tmp_path):
        """El coste tiene que poder pintarse ANTES de marcar la casilla.
        Y el eje decide si Jarvis puede seguir leyendo ahi, asi que no es
        decoracion."""
        consola, _ = self._consola(tmp_path)
        for zona in consola.zonas()["opcionales"]:
            assert zona["coste"].strip(), zona["ruta"]
            assert zona["eje"] in ("sistema", "privada")
            assert "aceptada" in zona

    def test_sin_suelo_el_panel_lo_dice(self, tmp_path):
        consola = Consola(Sesion(tmp_path))
        assert consola.zonas()["hay_suelo"] is False

    def test_marcar_llega_a_la_puerta_en_el_acto(self, tmp_path):
        """`politica.py` es nuestra y `sesion.zonas` se actualiza ya. NO
        cubre las lecturas -- `Read` no dispara la puerta --, por eso la
        pantalla pide reabrir igualmente."""
        consola, sesion = self._consola(tmp_path)
        opcional = next((z for z in consola.suelo.opcionales), None)
        if opcional is None:
            pytest.skip("esta maquina no ofrece ninguna zona opcional")

        antes = len(sesion.zonas)
        respuesta = consola.guardar_zonas([opcional.ruta], config_dir=tmp_path,
                                     version=VERSION_FALSA)
        assert respuesta["anadidas"] == [opcional.ruta]
        assert respuesta["ya_en_la_puerta"] == [opcional.ruta]
        assert respuesta["hace_falta_reabrir"] is True, (
            "marcar tampoco queda aplicado del todo hasta reabrir: `Read` no "
            "pasa por la puerta, asi que la segunda capa no cubre la lectura")
        assert len(sesion.zonas) == antes + 1, (
            "la sesion viva tiene que empezar a denegarla en la puerta ya")

    def test_cualquier_cambio_pide_reabrir(self, tmp_path):
        """Medido el 2026-08-24: se desmarco una zona con la sesion viva y
        la lectura SIGUIO denegada. Decir "listo" con la zona todavia
        cerrada seria mentir en la pantalla donde el usuario consiente."""
        consola, _ = self._consola(tmp_path)
        opcional = next((z for z in consola.suelo.opcionales), None)
        if opcional is None:
            pytest.skip("esta maquina no ofrece ninguna zona opcional")

        consola.guardar_zonas([opcional.ruta], config_dir=tmp_path,
                                     version=VERSION_FALSA)
        respuesta = consola.guardar_zonas([], config_dir=tmp_path,
                                     version=VERSION_FALSA)
        assert respuesta["soltadas"] == [opcional.ruta]
        assert respuesta["anadidas"] == []
        assert respuesta["hace_falta_reabrir"] is True

    def test_guardar_deja_el_suelo_valido(self, tmp_path):
        consola, _ = self._consola(tmp_path)
        opcional = next((z for z in consola.suelo.opcionales), None)
        if opcional is None:
            pytest.skip("esta maquina no ofrece ninguna zona opcional")
        respuesta = consola.guardar_zonas([opcional.ruta], config_dir=tmp_path,
                                     version=VERSION_FALSA)
        assert respuesta["ok"]
        vale, motivo = validar_reglas(list(consola.suelo.zonas),
                                      list(consola.suelo.reglas))
        assert vale, motivo

    def test_una_zona_privada_aceptada_bloquea_tambien_la_lectura(self, tmp_path):
        """Es la razon de ser del eje 2: lo que se lee VIAJA."""
        consola, sesion = self._consola(tmp_path)
        privada = next((z for z in consola.suelo.opcionales
                        if z.eje is Eje.PRIVADA), None)
        if privada is None:
            pytest.skip("esta maquina no ofrece ninguna zona privada")

        consola.guardar_zonas([privada.ruta], config_dir=tmp_path,
                              version=VERSION_FALSA)
        assert any(r.startswith("Read(") for r in consola.suelo.reglas)

        puerta = Puerta(id_peticion="x", herramienta="Read",
                        entrada={"file_path": privada.ruta + "\\algo.txt"},
                        descripcion="", id_uso="u")
        decision = decidir(puerta, str(tmp_path), zonas=sesion.zonas)
        assert decision.veredicto is Veredicto.DENEGAR


# --------------------------------------------------------------------
# EL VERDE EN FALSO (2026-08-27). Las tres salidas del senuelo.
# --------------------------------------------------------------------

class _SesionDeMentira:
    """Una sesion que entrega los eventos que se le digan y nada mas.

    >>> LA ENTRADA NO ES INVENTADA, ES LA QUE SE REGISTRO <<<
    La secuencia de `test_un_turno_que_no_cierra...` es la del arranque
    real del usuario (`logs/puente/sesion_20260827_163905.jsonl`): un
    `Write` a la carpeta personal, una puerta, y NADA mas -- ni `Fin` ni
    error. Ese log es el que destapo el fallo.
    """

    def __init__(self, *eventos, escribe_en=None):
        self._eventos = list(eventos)
        self.escribe_en = escribe_en
        self.mandados: list[str] = []
        self.respondidas: list[tuple[str, bool]] = []

    def mandar(self, texto: str) -> None:
        self.mandados.append(texto)
        # El senuelo "cuela" cuando el suelo NO muerde.
        if self.escribe_en is not None:
            self.escribe_en.write_text("colado", encoding="utf-8")

    def eventos(self, timeout=None):
        # Se agota como la de verdad: se acaban los eventos y VUELVE, sin
        # `Fin` y sin error. Ese silencio es el fallo.
        yield from self._eventos

    def responder(self, id_peticion: str, permitir: bool, motivo: str = "",
                  respuestas=None) -> bool:
        self.respondidas.append((id_peticion, permitir))
        return True


def _zona_senuelo(tmp_path):
    casa = tmp_path / ".claude"
    casa.mkdir(exist_ok=True)
    return Suelo(estado=EstadoSuelo.SIN_VERIFICAR, motivo="",
                 archivo=tmp_path / "s.json",
                 zonas=(Zona(str(casa), "la config", obligatoria=True),),
                 huella="abc123")


def _fin():
    from puente.protocolo import Fin

    return Fin(session_id="s", subtipo="success", es_error=False, texto="",
               coste_usd=0.0, duracion_ms=1, num_turnos=1)


def _puerta():
    from puente.protocolo import Puerta

    return Puerta(id_peticion="req-1", herramienta="Write",
                  entrada={"file_path": "C:/Users/alguien/x.txt"},
                  descripcion="", id_uso="u1")


class TestElVerdeEnFalso:
    """>>> LO QUE PASO DE VERDAD, Y POR QUE HAY TRES SALIDAS <<<

    Arranque real del usuario, 2026-08-27 16:39. El senuelo se pide en
    `~/.claude`, el suelo lo bloquea, y el modelo REINTENTA en la carpeta
    personal -- que no es zona obligatoria, asi que `permissions.deny` no
    lo para y la peticion llega a NUESTRA puerta. Nadie contesta (nadie
    esta mirando: es el arranque), el turno se queda colgado, y la
    version de dos salidas leia el senuelo intacto, concluia "el suelo
    muerde" **y sellaba**.

    El senuelo estaba intacto porque el turno seguia colgado, no porque
    el suelo mordiese.
    """

    def test_un_turno_que_no_cierra_NO_es_un_suelo_que_muerde(self, tmp_path):
        suelo = _zona_senuelo(tmp_path)
        sello = tmp_path / "suelo.sello"
        sesion = _SesionDeMentira(_puerta())      # puerta y nada mas: sin `Fin`

        veredicto, motivo = verificar_con_senuelo(
            sesion, suelo, sello=sello, timeout=0.05)

        assert veredicto is Senuelo.NO_SE_SABE, motivo
        assert not veredicto.se_puede_arrancar
        assert "no termino" in motivo
        # >>> Y SOBRE TODO: NO SE SELLA <<< Un sello dice "esto ya se
        # probo", y aqui no se probo nada. Firmarlo esconde el problema
        # hasta el siguiente cambio de version.
        assert not sello.exists()

    def test_las_puertas_del_senuelo_se_deniegan_solas(self, tmp_path):
        """Nadie esta mirando en el arranque, asi que esperar a una
        persona cuelga la comprobacion hasta el timeout -- que es como se
        llegaba al verde en falso. Y denegar es lo correcto: al senuelo
        se le pidio UNA via, cualquier puerta aqui es un reintento."""
        suelo = _zona_senuelo(tmp_path)
        sesion = _SesionDeMentira(_puerta(), _fin())

        veredicto, motivo = verificar_con_senuelo(
            sesion, suelo, sello=tmp_path / "s.sello", timeout=0.05)

        assert sesion.respondidas == [("req-1", False)]
        assert veredicto is Senuelo.MUERDE
        assert "reintentos" in motivo   # y se DICE cuantos hubo

    def test_un_turno_que_cierra_con_el_senuelo_intacto_SI_muerde(self, tmp_path):
        suelo = _zona_senuelo(tmp_path)
        sello = tmp_path / "suelo.sello"
        sesion = _SesionDeMentira(_fin())

        veredicto, _ = verificar_con_senuelo(
            sesion, suelo, sello=sello, timeout=0.05)

        assert veredicto is Senuelo.MUERDE
        assert veredicto.se_puede_arrancar
        assert sello.read_text(encoding="utf-8").strip() == "abc123"

    def test_si_el_senuelo_se_escribe_el_suelo_NO_muerde(self, tmp_path):
        """La otra mala, y no se dice igual que la de "no lo se": aqui SI
        se probo, y salio que las reglas no hacen nada."""
        suelo = _zona_senuelo(tmp_path)
        sello = tmp_path / "suelo.sello"
        senuelo = tmp_path / ".claude" / "jarvis_senuelo_de_arranque.txt"
        sesion = _SesionDeMentira(_fin(), escribe_en=senuelo)

        veredicto, motivo = verificar_con_senuelo(
            sesion, suelo, sello=sello, timeout=0.05)

        assert veredicto is Senuelo.NO_MUERDE
        assert "NO MUERDE" in motivo
        assert not sello.exists()

    def test_las_tres_salidas_son_distintas_y_solo_una_arranca(self):
        """Tres salidas. Si alguien vuelve a colapsar esto en un bool, el
        colapso natural es "no lo se" contra "si", que es el que costo el
        sello firmado sin probar nada."""
        assert len(set(Senuelo)) == 3
        arrancan = [s for s in Senuelo if s.se_puede_arrancar]
        assert arrancan == [Senuelo.MUERDE]


class TestElSenueloNoEntraEnTuProyecto:
    """>>> LO QUE VIO EL USUARIO (2026-08-27) <<<

    Dijo "continua con el proyecto redactor", ADR-0029 movio la sesion a
    `C:/proyectos/Delta`, y lo PRIMERO que se mando alli fue el senuelo.
    Registrado:

        INIT cwd = C:/proyectos/Delta
        Write    {'file_path': '.../.claude/jarvis_senuelo_de_arranque.txt'}

    Dos daños, y el segundo es el que importa: se comio el turno del
    ritual ("hola, en que nos quedamos?"), y dejo una escritura de
    comprobacion nuestra dentro de la transcripcion de SU proyecto.

    La comprobacion es del suelo de la MAQUINA. No pinta nada en la
    conversacion de nadie.
    """

    def test_la_comprobacion_abre_su_propia_sesion(self):
        import inspect

        import puente.__main__ as lanzador

        fuente = inspect.getsource(lanzador.main)
        cuerpo = fuente[fuente.index("def abrir_de_verdad"):]
        cuerpo = cuerpo[:cuerpo.index("consola.al_primer_turno")]
        # Se le pasa una sesion APARTE, no la que el usuario esta usando.
        assert "aparte = Sesion(" in cuerpo
        assert "verificar_con_senuelo(\n                aparte" in cuerpo
        assert "aparte.cerrar()" in cuerpo, "la sesion del senuelo se cierra"
        assert "verificar_con_senuelo(sesion" not in cuerpo

    def test_no_se_abre_la_sesion_del_usuario_si_el_suelo_no_se_prueba(self):
        """Si la comprobacion no sale bien, la sesion del usuario ni
        siquiera llega a abrirse: `sesion.abrir()` va DESPUES."""
        import inspect

        import puente.__main__ as lanzador

        fuente = inspect.getsource(lanzador.main)
        cuerpo = fuente[fuente.index("def abrir_de_verdad"):]
        cuerpo = cuerpo[:cuerpo.index("consola.al_primer_turno")]
        planta = cuerpo.index("Senuelo.NO_SE_SABE")
        abre = cuerpo.rindex("sesion.abrir()")
        assert planta < abre, (
            "la sesion del usuario se abre antes de saber si el suelo muerde")
