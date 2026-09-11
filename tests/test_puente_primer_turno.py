"""Que la primera orden no deje la pantalla en blanco y muda.

>>> LO REPORTO EL USUARIO EL 2026-09-03 <<<
Escribio una orden en la consola nada mas arrancar, sin sesion previa, le
dio al enter y el texto desaparecio; tardo minutos en verse reflejado y
en empezar. Lo que penso, y es lo que importa, fue que se habia trabado o
estaba roto.

ERAN DOS PIEZAS, UNA A CADA LADO DEL CABLE:

  1. `manda()` hacia `caja.value = ""` ANTES del POST, y `POST /turno` es
     sincrono -- abre la sesion de Claude Code y solo entonces llama a
     `anuncia_turno`, que es lo unico que PINTA lo que escribiste. Entre
     el Enter y el primer pixel no habia nada, y el texto ya no estaba
     para reintentarlo. Medido con `-m eval.mirar_el_primer_turno`:
     **6,65 s con el binario en frio, 0,62 s en caliente, 0,03 s el
     segundo turno**.
  2. `abrir_de_verdad` SI contaba lo que hacia, con `print`. Pero la
     carcasa corre con `pythonw`, donde `sys.stdout` es None y
     `escritorio/salida.py` lo desvia a un archivo: el sistema explicaba
     lo que hacia a un log que nadie mira.

Y un tercer fallo que aparecio en las mismas cinco lineas: `POST /turno`
contesta `{ok: false, motivo: ...}` cuando la sesion no se puede abrir, y
`manda()` se lo tragaba entero -- el texto desaparecia y no se decia por
que.

ESTOS TESTS MIRAN EL ARCHIVO, no un navegador. Es lo mismo que hace
`tests/test_ui_temas.py` y tiene el mismo limite: comprueban que la
regla esta escrita, no que se vea bien. Lo segundo lo dicta el usuario.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONSOLA = RAIZ / "puente" / "consola.html"
PUENTE = RAIZ / "puente" / "__main__.py"


def _manda() -> str:
    """El cuerpo de `async function manda()`, sin comentarios."""
    texto = CONSOLA.read_text(encoding="utf-8")
    inicio = texto.index("async function manda()")
    cuerpo = texto[inicio:texto.index("\ndocument.getElementById(\"mandar\")",
                                      inicio)]
    return re.sub(r"(?m)//[^\n]*", "", cuerpo)


class TestLaCajaNoSeVaciaAntesDeTiempo:
    def test_el_texto_se_borra_DESPUES_del_POST(self) -> None:
        """El orden es el fallo entero: vaciar antes deja al usuario sin
        lo que escribio y sin nada en pantalla durante segundos."""
        cuerpo = _manda()
        assert 'caja.value = ""' in cuerpo, "ya no se vacia nunca?"
        assert cuerpo.index('pide("/turno"') < cuerpo.index('caja.value = ""'), (
            "se vacia la caja ANTES de que el servidor acepte el turno: "
            "es el fallo del 2026-09-03")

    def test_mientras_espera_se_ve_que_esta_mandando(self) -> None:
        """Sin esto, la unica señal de que Enter hizo algo es que no pasa
        nada -- que es indistinguible de estar colgado."""
        cuerpo = _manda()
        assert "caja.disabled = true" in cuerpo
        assert "boton.disabled = true" in cuerpo
        assert "MANDANDO" in cuerpo

    def test_se_devuelve_la_caja_pase_lo_que_pase(self) -> None:
        """>>> EN UN `finally`, Y NO AL FINAL DEL `try` <<<

        Si el POST revienta -- Jarvis cerrado, red local caida -- y la
        caja se queda deshabilitada, la consola se vuelve de solo
        lectura para siempre y hay que recargar. Un fallo al mandar no
        puede costar la unica via de entrada que queda cuando la voz
        tambien esta apagada.
        """
        cuerpo = _manda()
        assert "finally" in cuerpo
        tras = cuerpo[cuerpo.index("finally"):]
        assert "caja.disabled = false" in tras
        assert "boton.disabled = false" in tras

    def test_un_turno_RECHAZADO_se_dice_y_conserva_el_texto(self) -> None:
        """`{ok: false}` significa que NO se mando nada. Tragarselo es el
        fallo mudo que este proyecto persigue desde JC-0007, y encima
        perdia lo escrito."""
        cuerpo = _manda()
        assert "datos.ok === false" in cuerpo, "no se mira el rechazo"
        rechazo = cuerpo.index("datos.ok === false")
        rama = cuerpo[rechazo:cuerpo.index('caja.value = ""')]
        assert "pinta(" in rama, "se rechaza el turno y no se dice nada"
        assert "return" in rama, (
            "sin el `return` se sigue y se vacia la caja igual, o sea que "
            "se pierde el texto de un turno que NO se mando")


class TestElArranqueLoCuentaEnLaPantalla:
    def test_los_dos_avisos_van_a_la_consola_y_no_a_un_print(self) -> None:
        """Es la mitad 2 del fallo: `pythonw` no tiene stdout."""
        texto = PUENTE.read_text(encoding="utf-8")
        trozo = texto[texto.index("def abrir_de_verdad"):
                      texto.index("consola.al_primer_turno")]
        assert trozo.count("consola.avisa(") >= 3, (
            "el arranque tiene que DECIR que esta abriendo la sesion, que "
            "toca senuelo y como acabo")
        # Lo que queda de `print` aqui seria justo lo que nadie ve.
        assert "print(" not in trozo, (
            "un `print` en el arranque se lo come `escritorio/salida.py`: "
            "con pythonw, sys.stdout es None")

    def test_el_aviso_del_senuelo_dice_que_NO_esta_colgado(self) -> None:
        """>>> ES EL UNICO CARO Y APARECE DE REPENTE <<<

        Se paga una vez por actualizacion de `claude`, que se actualiza
        solo. O sea que un dia cualquiera la primera orden tarda minutos
        sin que haya cambiado nada. Decir cuanto cuesta y por que es lo
        unico que lo distingue de un cuelgue.
        """
        texto = PUENTE.read_text(encoding="utf-8")
        assert "No esta colgado." in texto
        assert "cuesta un turno" in texto.lower()

    def test_la_pagina_sabe_pintar_un_Aviso(self) -> None:
        assert 'case "Aviso":' in CONSOLA.read_text(encoding="utf-8")

    def test_el_aviso_viaja_por_un_campo_QUE_SE_TRADUCE(self) -> None:
        """Un campo propio no estaria en `CLAVES_DE_TEXTO`, y el aviso
        saldria en español en mitad de una consola en ingles."""
        from puente.consola import CLAVES_DE_TEXTO

        fuente = (RAIZ / "puente" / "consola.py").read_text(encoding="utf-8")
        # `def _difundir(self` y no `def _difundir`: lo segundo casa
        # antes con `_difundir_producido`, que esta MAS ARRIBA, y el
        # trozo sale vacio -- con lo que el test pasaria mirando nada.
        trozo = fuente[fuente.index("def avisa"):
                       fuente.index("def _difundir(self")]
        assert '"clase": "Aviso"' in trozo
        assert "motivo" in trozo
        assert "motivo" in CLAVES_DE_TEXTO

    def test_los_dos_avisos_estan_traducidos(self) -> None:
        """Se comprueban los textos REALES, sacados del codigo.

        Copiarlos a mano aqui mediria este archivo: bastaria con cambiar
        una coma en `__main__.py` para que la traduccion dejara de casar
        y el test siguiera verde.
        """
        from nucleo.textos import mensaje

        texto = PUENTE.read_text(encoding="utf-8")
        trozo = texto[texto.index("def abrir_de_verdad"):
                      texto.index("consola.al_primer_turno")]
        dichos = [m.group(1) for m in
                  re.finditer(r'consola\.avisa\(\s*((?:"[^"]*"\s*)+)\)', trozo)]
        assert len(dichos) >= 2, f"solo se encontraron {len(dichos)}"
        for crudo in dichos:
            frase = "".join(re.findall(r'"([^"]*)"', crudo))
            assert mensaje(frase, "en") != frase, (
                f"sin traducir al ingles: {frase!r}")
