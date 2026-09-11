"""La caja donde se escribe una orden crece con lo que escribes.

>>> LO REPORTO EL USUARIO EL 2026-09-03 <<<
Escribiendo en la consola, la caja de texto no crecia: solo se desplazaba
su scroll interno, de modo que con bastante texto se veia un unico
renglon, cortado.

Un `<textarea rows="1">` no crece solo: se queda a un renglon y hace
scroll dentro. Y en este programa la caja larga es el caso NORMAL --
las ordenes reales que se dictan son de dos y tres lineas --, asi que no poder
releer lo que has escrito antes de mandarlo se paga en cada turno.

>>> Y EL RIESGO DE VOLVER A ROMPERLO ES CONOCIDO Y TIENE NOMBRE <<<
El 2026-09-02 tres temas de cuatro APLASTARON la tira poniendo
`button { height }` sobre una tarjeta que es un `<button>`. La suite
estaba en verde con 1211 tests, porque el test de temas miraba que nadie
la ESCONDIERA y aquello no la escondia: la aplastaba. Aqui puede pasar
exactamente lo mismo -- un `#texto { height: 34px }` en un tema deja el
JS moviendo un numero que no manda, sin un solo error --, asi que hay un
test que lo prohibe por escrito.

LO QUE ESTOS TESTS NO PRUEBAN: que se VEA bien. Miran el archivo, no un
navegador. Lo segundo lo dicta el usuario.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
CONSOLA = RAIZ / "puente" / "consola.html"
TEMAS = sorted((RAIZ / "puente" / "temas").glob("*.css"))


def _fuente() -> str:
    return CONSOLA.read_text(encoding="utf-8")


def _sin_comentarios(texto: str) -> str:
    texto = re.sub(r"/\*.*?\*/", " ", texto, flags=re.DOTALL)
    return re.sub(r"(?m)//[^\n]*", " ", texto)


def _funcion(nombre: str) -> str:
    """El cuerpo de una funcion del script, sin comentarios."""
    texto = _fuente()
    i = texto.index(f"function {nombre}(")
    j = texto.index("\n}", i)
    return _sin_comentarios(texto[i:j])


def _reglas_de_texto(hoja: Path) -> list[str]:
    """Las declaraciones de cada regla que apunta a `#texto`."""
    crudo = _sin_comentarios(hoja.read_text(encoding="utf-8"))
    return [decl for sel, decl in re.findall(r"([^{}]+)\{([^{}]*)\}", crudo)
            if "#texto" in sel]


class TestLaAlturaNoEstaClavada:
    def test_la_hoja_base_pone_un_TECHO_y_no_una_altura(self) -> None:
        """`max-height` deja crecer; `height` lo impide.

        El techo hace falta: `#flujo` es `flex-grow:1` con
        `min-height:0`, o sea que sin tope una parrafada pegada se comeria
        el registro entero.
        """
        decl = " ".join(_reglas_de_texto(CONSOLA))
        assert "max-height:" in decl, "sin techo, una parrafada tapa el log"
        # `line-` va en la exclusion ademas de `max-`: `line-height` es
        # el interlineado y no clava nada. Sin esa mitad, el test fallaba
        # sobre codigo CORRECTO, que es la peor clase de test.
        assert not re.search(r"(?<!max-)(?<!line-)height\s*:", decl), (
            "hay una altura fija en la hoja base: la caja no podria crecer")

    @pytest.mark.parametrize("hoja", TEMAS, ids=lambda h: h.stem)
    def test_ningun_TEMA_le_clava_la_altura(self, hoja: Path) -> None:
        """>>> ES LA LECCION DE LA TIRA APLASTADA, LITERAL <<<

        Alli fue `button { height: 28px }` sobre una tarjeta que es un
        `<button>`: no la escondia -- asi que el test de temas pasaba --,
        la dejaba a 28 px con la miniatura dentro a 15. Aqui un
        `#texto { height }` dejaria la caja a un renglon con el JS
        calculando alturas que nadie aplica, y tampoco daria ningun error.
        """
        decl = " ".join(_reglas_de_texto(hoja))
        assert not re.search(r"(?<!max-)(?<!line-)height\s*:", decl), (
            f"{hoja.name} le clava la altura a la caja de texto. Un tema "
            f"puede cambiar la letra, el fondo y el hueco; la altura la "
            f"decide lo que el usuario haya escrito.")


class TestCreceYEncoge:
    def test_se_suelta_la_altura_ANTES_de_medir(self) -> None:
        """Sin esto crece pero NO ENCOGE.

        `scrollHeight` con una altura ya puesta devuelve el alto viejo en
        cuanto el contenido cabe, asi que al borrar texto la caja se
        quedaria grande para siempre. Con `auto` se mide lo que ocupa
        ahora.
        """
        cuerpo = _funcion("ajustaCaja")
        assert 'caja.style.height = "auto"' in cuerpo
        # `caja.scrollHeight` y no `scrollHeight` a secas: el primer
        # `scrollHeight` del cuerpo es el del REGISTRO, en la linea que
        # mide si estaba pegado al final, y comparar contra ese decia que
        # el orden estaba mal cuando estaba bien.
        assert cuerpo.index('"auto"') < cuerpo.index("caja.scrollHeight"), (
            "se mide antes de soltar la altura: la caja no encogeria")

    def test_crece_con_cada_tecla(self) -> None:
        assert 'addEventListener("input", ajustaCaja)' in _fuente()

    def test_encoge_al_mandar(self) -> None:
        """Vaciar el valor NO dispara `input`, asi que hay que decirlo.

        Sin esto queda un hueco enorme y vacio con un cursor dentro.
        """
        cuerpo = _funcion("manda")
        assert "ajustaCaja()" in cuerpo, "la caja se queda grande y vacia"
        assert cuerpo.index('caja.value = ""') < cuerpo.index("ajustaCaja()")

    def test_el_registro_se_vuelve_a_pegar_al_final(self) -> None:
        """El pie que crece ENCOGE `#flujo`, y quien miraba el final se
        queda por encima sin haber tocado nada. Se mide el pegado ANTES
        de mover la altura, que es la misma regla del visor del POV."""
        cuerpo = _funcion("ajustaCaja")
        assert "pegado" in cuerpo
        assert cuerpo.index("pegado") < cuerpo.index('"auto"'), (
            "se mide el pegado DESPUES de mover la altura, o sea que ya "
            "esta falseado: siempre saldria 'no estaba pegado'")
        assert "flujo.scrollTop = flujo.scrollHeight" in cuerpo
