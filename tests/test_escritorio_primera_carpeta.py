"""El primer doble clic de alguien que acaba de clonar esto.

>>> DE DONDE SALE (2026-09-10) <<<
El usuario miro el acceso directo de su Escritorio -- *"hay uno en mi
desktop y no se si jale"* -- y no jalaba. Lo interesante no fue su
maquina: al medirlo salio que **le pasa igual a cualquiera que clone el
repositorio**.

    sesion.carpeta en una config recien sembrada  ->  ""
    jarvis.bat  ->  start "" ".venv\\Scripts\\pythonw.exe" -m escritorio %* --voz

`%*` son los argumentos que le pases, y en un DOBLE CLIC no hay ninguno.
Ni el `.bat` ni el acceso directo que escribe `escritorio/inicio.py`
pasan carpeta, asi que los dos caian en la misma pared: un cuadro de
"Jarvis no ha podido arrancar", dos parrafos despues de que el README
prometiera que la instalacion son dos dobles clics.

El mensaje decia que hacer, pero lo que decia era *"arranca una vez
pasandola detras del comando"* -- a alguien que acaba de hacer doble
clic, o sea que no tiene ninguna terminal delante. Media leccion: el
2026-09-05 ya se corrigio para que no mandara a editar un YAML, y se
quedo mandando a una consola.

>>> LO QUE ESTOS TESTS FIJAN, Y ES LA FORMA, NO EL SELECTOR <<<
Abrir un dialogo de Windows no se puede probar en una suite. Lo que si se
puede -- y es donde estaba el fallo -- es que `pedir_carpeta` tenga TRES
respuestas y que cada una lleve a un sitio distinto:

    elegiste    -> se guarda y se arranca ahi
    cancelaste  -> no se arranca, y NO se te suelta un parrafo sobre
                   lineas de ordenes: ya dijiste que no
    no se pudo  -> el unico caso que necesita explicar el camino manual

Colapsar las dos ultimas es el error facil, y se nota justo en el momento
en que alguien esta decidiendo si esto le sirve.
"""

from __future__ import annotations

import escritorio.__main__ as mod


def test_son_TRES_salidas_y_se_llaman_distinto() -> None:
    assert len({mod.ELEGIDA, mod.CANCELO, mod.NO_SE_PUDO}) == 3


def test_sin_tkinter_dice_NO_SE_PUDO_y_no_levanta(monkeypatch) -> None:
    """>>> LA RED DEL SELECTOR <<<

    `avisar_de_que_no_arranco` usa `MessageBoxW` por `ctypes` y no una
    libreria, con su motivo escrito: tiene que poder salir cuando lo que
    ha reventado es el montaje. El selector hereda esa regla -- si no se
    puede ni preguntar, se dice, y se cae al camino de antes, que sigue
    existiendo entero.
    """
    import builtins

    real = builtins.__import__

    def sin_tk(nombre, *a, **k):
        if nombre.startswith("tkinter"):
            raise ImportError("no hay tk en esta maquina")
        return real(nombre, *a, **k)

    monkeypatch.setattr(builtins, "__import__", sin_tk)
    que, carpeta = mod.pedir_carpeta()
    assert que == mod.NO_SE_PUDO and carpeta is None


def test_cancelar_no_es_lo_mismo_que_no_poder_preguntar() -> None:
    """La distincion entera de esta tanda, dicha en un assert."""
    assert mod.CANCELO != mod.NO_SE_PUDO


def test_una_carpeta_vacia_se_lee_como_CANCELO(monkeypatch) -> None:
    """>>> `askdirectory` DEVUELVE "" POR DOS CAMINOS <<<

    Cerrar el dialogo por la X y pulsar Cancelar dan lo mismo, y las dos
    son la misma respuesta: dijo que no. Lo que NO puede pasar es que
    salga como una carpeta llamada "" y el arranque intente acotarse a
    ella.
    """
    postizo = _TkPostizo(devuelve="")
    monkeypatch.setitem(__import__("sys").modules, "tkinter", postizo)
    monkeypatch.setitem(__import__("sys").modules, "tkinter.filedialog",
                        postizo.filedialog)
    que, carpeta = mod.pedir_carpeta()
    assert que == mod.CANCELO and carpeta is None


def test_una_carpeta_elegida_vuelve_como_Path(monkeypatch, tmp_path) -> None:
    postizo = _TkPostizo(devuelve=str(tmp_path))
    monkeypatch.setitem(__import__("sys").modules, "tkinter", postizo)
    monkeypatch.setitem(__import__("sys").modules, "tkinter.filedialog",
                        postizo.filedialog)
    que, carpeta = mod.pedir_carpeta()
    assert que == mod.ELEGIDA
    assert carpeta is not None and carpeta.is_dir()


def test_el_selector_sale_DELANTE(monkeypatch, tmp_path) -> None:
    """Un dialogo que nace detras de otra ventana se lee como un cuelgue.

    Nace sin ventana padre, asi que sin `-topmost` Windows lo puede
    dejar tapado -- y entonces el doble clic "no hace nada", que es
    exactamente el sintoma que esta tanda venia a quitar.
    """
    postizo = _TkPostizo(devuelve=str(tmp_path))
    monkeypatch.setitem(__import__("sys").modules, "tkinter", postizo)
    monkeypatch.setitem(__import__("sys").modules, "tkinter.filedialog",
                        postizo.filedialog)
    mod.pedir_carpeta()
    assert ("-topmost", True) in postizo.raiz.atributos


def test_la_ventana_oculta_se_destruye(monkeypatch, tmp_path) -> None:
    """Se crea un `Tk` para poder preguntar; dejarlo vivo cuelga el proceso."""
    postizo = _TkPostizo(devuelve=str(tmp_path))
    monkeypatch.setitem(__import__("sys").modules, "tkinter", postizo)
    monkeypatch.setitem(__import__("sys").modules, "tkinter.filedialog",
                        postizo.filedialog)
    mod.pedir_carpeta()
    assert postizo.raiz.destruida


class _RaizPostiza:
    def __init__(self) -> None:
        self.atributos: list[tuple] = []
        self.destruida = False
        self.escondida = False

    def withdraw(self) -> None:
        self.escondida = True

    def attributes(self, *args) -> None:
        self.atributos.append(args)

    def destroy(self) -> None:
        self.destruida = True


class _TkPostizo:
    """Un `tkinter` de mentira, para poder mirar COMO se pregunta.

    No simula el dialogo -- eso seria un mock de lo que importa (regla
    4) --: lo que devuelve se le dice en el constructor, y lo que este
    doble permite comprobar es lo de alrededor, que es donde estaban los
    fallos posibles (la ventana que no se destruye, el dialogo que nace
    detras).
    """

    def __init__(self, devuelve: str) -> None:
        self.raiz = _RaizPostiza()
        doble = self

        class _FileDialog:
            @staticmethod
            def askdirectory(**_k) -> str:
                return devuelve

        self.filedialog = _FileDialog()
        self._doble = doble

    def Tk(self):  # noqa: N802 - se llama como el de verdad
        return self.raiz
