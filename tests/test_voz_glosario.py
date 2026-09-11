"""El glosario no puede mentir sobre lo que Jarvis reconoce.

>>> POR QUE ESTE ARCHIVO ES LA MITAD DEL GLOSARIO <<<
Una lista de palabras clave escrita a mano es prosa, y la prosa envejece
sin avisar -- la regla de este arbol existe porque ya se ha cobrado
varias. El peligro concreto: alguien afina una expresion regular en
`voz/ventana.py`, la frase deja de reconocerse, y el panel sigue
enseñandola como si funcionara. El usuario la dice, no pasa nada, y no
hay ningun error en ningun sitio.

Asi que cada entrada trae su FRASE DE EJEMPLO y aqui se pasa por el
interprete de VERDAD. Si dejan de casar, esto falla y hay que venir a
decir cual es la buena.

Lo que este archivo NO prueba, y conviene no leerlo de mas: que la
explicacion en castellano sea correcta. Eso no vive en ningun sitio del
que sacarlo y no hay forma de comprobarlo con codigo.
"""

from __future__ import annotations

import pytest

from voz.glosario import glosario


def entradas():
    return glosario()


# >>> SE BUSCA POR POSICION Y NO POR LA CADENA <<<
# La frase cambia con el idioma, asi que un `== "abrete"` ataria estos
# tests al español y fallarian con la voz en ingles -- justo cuando el
# codigo estaria bien.
MOSTRAR, ESCONDER, APAGAR, PROYECTO, PARAR, CANCELAR = range(6)


def una(cual: int, idioma: str = "es"):
    return glosario(idioma=idioma)[cual]


# --- 1. CADA FRASE SE RECONOCE DE VERDAD --------------------------------


CASOS = [(idi, e.frase)
         for idi in ("es", "en")
         for e in glosario(idioma=idi)]


@pytest.mark.parametrize("idioma,frase", CASOS)
def test_cada_frase_del_glosario_la_reconoce_QUIEN_INTERCEPTA(
        idioma, frase) -> None:
    """El nucleo del archivo, y va por LOS DOS IDIOMAS.

    En ingles las frases NO son las españolas traducidas -- son
    `show yourself`, `hide yourself`, `shut yourself down`, raras a
    proposito porque el ingles no marca el imperativo (JC-0018) --, asi
    que una traduccion ingenua enseñaria frases que Jarvis no reconoce.
    Aqui se pasa cada una por el interprete de SU idioma.
    """
    from voz.parada import Veredicto as VeredictoParada
    from voz.parada import mirar as parar
    from voz.proyecto import Veredicto as VeredictoProyecto
    from voz.proyecto import interpretar as proyecto
    from voz.ventana import Veredicto as VeredictoVentana
    from voz.ventana import interpretar as ventana

    reconocida = (
        ventana(frase, idioma).veredicto is not VeredictoVentana.NO_ES
        # >>> EL IDIOMA SE LE PASA, Y HASTA EL 2026-09-09 NO <<<
        # Este mismo docstring promete "el interprete de SU idioma" y a
        # `proyecto` se le llamaba pelado, o sea que resolvia el idioma
        # de la configuracion y miraba la frase inglesa con los patrones
        # españoles. La prosa vieja cobrandose el archivo que existe para
        # cobrarla.
        #
        # Y NO VALE `is not NO_ES`: `SIN_NOMBRE` tambien es "no es
        # NO_ES" y significa que Jarvis entendio la orden pero no saco
        # el nombre -- que es exactamente lo que hacia la frase inglesa
        # del glosario, con el nombre en el sitio español. El hueco `{}`
        # lo rellena `_un_proyecto_tuyo` con un proyecto TUYO de verdad,
        # asi que aqui siempre hay un nombre que sacar: si no sale, el
        # ejemplo esta mal escrito. (`VARIOS` no vive aqui: es de
        # `resolver`, que es el paso siguiente y mira el registro.)
        or proyecto(frase, idioma).veredicto is VeredictoProyecto.CAMBIAR
        # `voz.parada` no tiene NO_ES: sus tres salidas son
        # PARA / SIGUE / DUDOSA. La que cuenta como "Jarvis se
        # la queda" es PARA -- DUDOSA para el turno pero es
        # la duda, no un reconocimiento, y no la ensena el
        # glosario como palabra clave.
        or parar(frase, idioma).veredicto is VeredictoParada.PARA
    )
    # >>> SE COMPRUEBA EN LAS DOS DIRECCIONES <<<
    # `canales=()` significa "todavia por ningun canal", y hoy lo lleva
    # el cambio de proyecto en ingles: `voz/proyecto.py` solo tiene
    # patrones españoles. Si alguien los añade y no toca el glosario,
    # esto falla y viene a decirlo -- que es lo contrario de que la
    # pantalla se quede diciendo "todavia no" para siempre.
    entrada = next(e for e in glosario(idioma=idioma) if e.frase == frase)
    if entrada.canales:
        assert reconocida, (
            f"el glosario dice que Jarvis se queda '{frase}' y ningun "
            f"interprete la reconoce. O se afino un patron sin actualizar "
            f"la lista, o la lista se escribio de memoria.")
    else:
        assert not reconocida, (
            f"el glosario dice que '{frase}' NO se intercepta todavia y "
            f"resulta que si. Si se ha añadido el idioma, hay que ponerle "
            f"sus canales.")


# --- 2. LOS CANALES QUE DECLARA SON LOS QUE SON -------------------------


class TestLosCanales:
    def test_las_de_ventana_valen_en_LOS_DOS(self) -> None:
        """Desde el 2026-09-05, y lo reporto el usuario: escritas se iban
        al cerebro."""
        for cual in (MOSTRAR, ESCONDER, APAGAR):
            assert una(cual).canales == ("voz", "consola")

    def test_el_cambio_de_proyecto_tambien(self) -> None:
        """Desde el 2026-09-03, y tambien lo reporto el usuario."""
        assert set(una(PROYECTO).canales) == {"voz", "consola"}

    def test_y_EN_INGLES_TAMBIEN_desde_que_hay_patrones(self) -> None:
        """>>> ESTE TEST DECIA LO CONTRARIO, Y ERA CIERTO HASTA HOY <<<

        Se llamaba `test_pero_EN_INGLES_TODAVIA_NO_y_la_lista_lo_dice` y
        exigia `canales == ()` mas un "NOT AVAILABLE IN ENGLISH" en la
        prosa. Lo era: los patrones estaban compilados en español dentro
        de `voz/proyecto.py`. Dejo de serlo en el commit `f5be1fb` del
        2026-09-09, cuando se mudaron a `voz.idioma.PROYECTO` -- y esta
        entrada del glosario es lo que el usuario LEE para decidir si la
        frase le sirve, asi que un "todavia no" que ya no es verdad
        esconde una funcion que si existe.

        Se cambia el test y no la produccion, que es la direccion que
        toca: lo que cambio fue el mundo, no la regla. La regla sigue
        siendo la misma -- el glosario no puede mentir sobre lo que
        Jarvis reconoce --, y ahora miente en la otra direccion.
        """
        assert set(una(PROYECTO, "en").canales) == {"voz", "consola"}
        assert "ENGLISH" not in una(PROYECTO, "en").hace.upper()

    def test_las_de_PARAR_son_solo_de_VOZ_y_es_una_decision(self) -> None:
        """>>> "SE NOS OLVIDO" Y "SE DECIDIO QUE NO" SE VEN IGUAL <<<

        Escrita, "para" es una preposicion normal. La consola tiene Esc,
        que corta lo mismo y esta rotulado. Si algun dia se cambia, lo
        que se cambia es la decision -- y este test.
        """
        for cual in (PARAR, CANCELAR):
            assert una(cual).canales == ("voz",)
        assert "Esc" in una(PARAR).aviso


# --- 3. EL ESTADO QUE ENSEÑA ES EL DE VERDAD ----------------------------


class TestElEstado:
    def test_el_de_proyectos_SE_LEE_del_registro(self, tmp_path,
                                                 monkeypatch) -> None:
        """Un glosario que dijera "encendido" con el interruptor apagado
        mandaria a alguien a probar una frase que hoy no hace nada."""
        from nucleo.proyectos import CLAVE_INTERCEPTA

        for puesto in (True, False):
            (tmp_path / "proyectos.yaml").write_text(
                f"{CLAVE_INTERCEPTA}: {str(puesto).lower()}\nproyectos: []\n",
                encoding="utf-8")
            monkeypatch.setattr("nucleo.proyectos.CONFIG_DIR", tmp_path)
            assert glosario(tmp_path)[PROYECTO].encendida is puesto

    def test_las_demas_NO_tienen_interruptor_y_se_dice(self) -> None:
        """`None` no es "encendida": es "no lo lleva". Colapsarlo dejaria
        al usuario buscando un interruptor que no existe."""
        for cual in (MOSTRAR, ESCONDER, APAGAR, PARAR, CANCELAR):
            assert una(cual).encendida is None


# --- 4. LO QUE CUESTA, DICHO DONDE SE LEE -------------------------------


def test_apagate_avisa_de_lo_que_NO_mata() -> None:
    """Es la unica de la lista que no se puede deshacer, y lo que deja
    vivo detras sorprende: un `docker compose up` que arranco Claude Code
    sigue corriendo. Vale mas dicho aqui que descubierto luego."""
    assert "turno" in una(APAGAR).aviso
    assert "docker" in una(APAGAR).aviso
    assert "docker" in una(APAGAR, "en").aviso


def test_no_hay_entradas_repetidas() -> None:
    for idioma in ("es", "en"):
        frases = [e.frase for e in glosario(idioma=idioma)]
        assert len(frases) == len(set(frases)), idioma


def test_las_frases_inglesas_NO_son_las_espanolas(_=None) -> None:
    """>>> NO SE TRADUCEN, SE SUSTITUYEN <<< En ingles son de tres
    palabras y raras a proposito: el idioma no marca el imperativo, asi
    que "stop the server" y "close it" son ordenes normales. Una
    traduccion ingenua daria frases que Jarvis no reconoce Y se comeria
    trabajo de verdad."""
    es = [e.frase for e in glosario(idioma="es")]
    en = [e.frase for e in glosario(idioma="en")]
    assert not (set(es) & set(en))
