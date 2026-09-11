"""La carcasa: que cerrar no sea salir, y que un arranque mudo no exista.

QUE SE PRUEBA AQUI Y QUE NO. **No se prueba que la ventana aparezca**:
eso necesita un escritorio interactivo y lo tiene que ver una persona
(es el pariente de quien dicta — hay cosas que no las contesta un test).
Lo que si se prueba es todo lo que decidiria mal en silencio:

  * que la X **esconda** en vez de matar el proceso. Si eso se rompe,
    Jarvis se muere cada vez que alguien quita una ventana de en medio y
    el usuario se entera hablandole a un asistente que ya no esta;
  * que el diario recoja lo que `print` se traga cuando no hay consola.
    Medido el 2026-08-26 con DETACHED_PROCESS: `sys.stdout` vale None y
    `print` NO revienta, simplemente no hace nada. Ese silencio es el
    modo de fallo que la carcasa tiene que impedir;
  * que el icono NO diga "escuchando" cuando algo esta roto.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from escritorio import icono as mod_icono
from escritorio import salida as mod_salida


# --- 1. LA X ESCONDE, NO MATA -------------------------------------------


class _VentanaPostiza:
    def __init__(self) -> None:
        self.escondida = 0
        self.mostrada = 0
        self.destruida = 0

    def hide(self) -> None:
        self.escondida += 1

    def show(self) -> None:
        self.mostrada += 1

    def restore(self) -> None:
        pass

    def destroy(self) -> None:
        self.destruida += 1


class _IconoPostizo:
    def __init__(self) -> None:
        self.parado = 0
        self.icon = None

    def stop(self) -> None:
        self.parado += 1


class _MontajePostizo:
    def __init__(self, viva: bool = False) -> None:
        self.puerto = 8799
        self.sesion = type("S", (), {"viva": viva})()
        self.latidos = 0

    def latir(self) -> None:
        self.latidos += 1


@pytest.fixture
def carcasa():
    from escritorio.__main__ import Carcasa

    c = Carcasa(_MontajePostizo(), carpeta=Path(r"C:\proyectos\carpetadepruebas"),
                con_voz=False, oculto=False, diario=None)
    c.ventana = _VentanaPostiza()
    c.icono = _IconoPostizo()
    return c


def test_cerrar_la_ventana_esconde_y_NO_cierra(carcasa) -> None:
    """>>> LA DECISION DE PRODUCTO, EN UNA LINEA <<<

    Devolver False cancela el cierre. Si esto devolviera True, cerrar la
    ventana mataria el proceso: Jarvis dejaria de escuchar y no habria
    forma de notarlo hasta hablarle.
    """
    assert carcasa._al_cerrar() is False
    assert carcasa.ventana.escondida == 1
    assert carcasa.ventana.destruida == 0
    assert carcasa.icono.parado == 0


def test_salir_por_la_bandeja_SI_cierra(carcasa) -> None:
    """La unica puerta de salida. Y despues, el cierre ya no se cancela:
    si no, `webview.start()` no volveria nunca y el proceso quedaria
    vivo sin bandeja ni ventana -- imposible de matar sin el
    Administrador de tareas."""
    carcasa._salir()
    assert carcasa.icono.parado == 1
    assert carcasa.ventana.destruida == 1
    assert carcasa._al_cerrar() is True


def test_esconder_dos_veces_no_rompe_nada(carcasa) -> None:
    carcasa._al_cerrar()
    carcasa._al_cerrar()
    assert carcasa.ventana.escondida == 2


def test_una_ventana_que_ya_no_esta_no_tumba_el_cierre(carcasa) -> None:
    """Salir no puede fallar por lo que le pase a la ventana."""

    def revienta() -> None:
        raise RuntimeError("la ventana ya no existe")

    carcasa.ventana.destroy = revienta
    carcasa._salir()   # no levanta
    assert carcasa.icono.parado == 1


# --- 2. EL ICONO NO MIENTE ----------------------------------------------


def test_roto_gana_a_escuchando() -> None:
    """Un Jarvis que oye pero cuyo suelo no muerde NO es 'escuchando'.

    Pintarlo de verde seria la pantalla mintiendo sobre lo unico que no
    puede mentir, y en la bandeja el icono es la UNICA superficie que
    queda cuando no hay ventana ni terminal.
    """
    class SinSesion:
        sesion = None

    assert mod_icono.estado_de(SinSesion(), voz_encendida=True) == "roto"


def test_el_icono_distingue_oir_de_solo_estar() -> None:
    parado = _MontajePostizo(viva=False)
    assert mod_icono.estado_de(parado, voz_encendida=True) == "escucha"
    assert mod_icono.estado_de(parado, voz_encendida=False) == "listo"
    assert mod_icono.estado_de(_MontajePostizo(viva=True), True) == "trabajando"


def test_cada_estado_tiene_su_color_y_ninguno_se_repite() -> None:
    """Cuatro colores para cuatro estados: si dos coincidieran, el icono
    tendria menos que decir de lo que promete."""
    assert len(set(mod_icono.COLORES.values())) == len(mod_icono.COLORES)


def test_el_icono_se_dibuja_para_todos_los_estados() -> None:
    for estado in mod_icono.COLORES:
        imagen = mod_icono.dibujar(estado)
        assert imagen.size == (mod_icono.LADO, mod_icono.LADO)
        assert imagen.mode == "RGBA"


# --- 3. EL ARRANQUE NO PUEDE SER MUDO -----------------------------------


def test_el_diario_escribe_a_disco_y_recuerda(tmp_path) -> None:
    diario = mod_salida.Diario(tmp_path / "a.log", tambien_a=None)
    print("primera", file=diario)
    print("segunda", file=diario)
    diario.flush()

    assert list(diario.ultimas) == ["primera", "segunda"]
    assert "segunda" in (tmp_path / "a.log").read_text(encoding="utf-8")


def test_el_diario_funciona_con_stdout_a_None(tmp_path) -> None:
    """>>> EL CASO QUE MOTIVA TODO ESTO <<<

    Con `pythonw.exe` y sin consola, `sys.stdout` es None. El diario tiene
    que ser el sitio donde cae la salida, no un envoltorio de algo que no
    existe.
    """
    diario = mod_salida.Diario(tmp_path / "b.log", tambien_a=None)
    print("el suelo no esta en condiciones", file=diario)
    diario.flush()
    assert "el suelo" in (tmp_path / "b.log").read_text(encoding="utf-8")


def test_una_consola_que_desaparece_no_se_lleva_el_log(tmp_path) -> None:
    """Lanzado desde una terminal que luego se cierra, lo importante es
    que siga habiendo registro."""

    class ConsolaQueMuere:
        def write(self, _t):
            raise OSError("el descriptor se fue")

        def flush(self):
            raise OSError("idem")

    diario = mod_salida.Diario(tmp_path / "c.log", tambien_a=ConsolaQueMuere())
    print("sigo escribiendo", file=diario)
    diario.flush()
    assert "sigo escribiendo" in (tmp_path / "c.log").read_text(encoding="utf-8")


def test_el_diario_escribe_en_utf8_y_no_en_cp1252(tmp_path) -> None:
    """La salida con consola sale en cp1252 y este proyecto habla español.
    Es la misma leccion de JC-0003: si se rompe la codificacion, el TTS
    acaba diciendo "canci?n"."""
    diario = mod_salida.Diario(tmp_path / "d.log", tambien_a=None)
    print("configuración señal áéíóú", file=diario)
    diario.flush()
    assert "configuración señal áéíóú" in (
        tmp_path / "d.log").read_text(encoding="utf-8")


def test_solo_se_recuerdan_las_ultimas(tmp_path) -> None:
    """El cuadro de dialogo enseña la ultima linea util; la memoria esta
    acotada para que un proceso de dias no se coma la RAM."""
    diario = mod_salida.Diario(tmp_path / "e.log", tambien_a=None)
    for i in range(mod_salida.COLA + 50):
        print(f"linea {i}", file=diario)
    assert len(diario.ultimas) == mod_salida.COLA
    assert diario.ultimas[-1] == f"linea {mod_salida.COLA + 49}"


def test_las_lineas_en_blanco_no_cuentan_como_ultimo_motivo(tmp_path) -> None:
    """`__main__` coge la ultima linea util para el cuadro de dialogo. Si
    las vacias contasen, el usuario veria una caja sin texto justo cuando
    mas necesita saber que paso."""
    diario = mod_salida.Diario(tmp_path / "f.log", tambien_a=None)
    print("el suelo no muerde", file=diario)
    print("", file=diario)
    print("   ", file=diario)
    assert diario.ultimas[-1] == "el suelo no muerde"


# --- 4. LO QUE EL ACCESO DIRECTO LE PIDE A LA CARCASA -------------------


def test_el_arranque_de_windows_pide_la_ventana_OCULTA() -> None:
    """Nadie quiere una ventana abriendosele en cada boot.

    Y `--oculto` tiene que existir de verdad en el lanzador: si el
    acceso directo lo pasara y `escritorio` no lo conociera, el arranque
    fallaria con un error de argumentos... en un proceso sin consola, o
    sea en silencio.
    """
    from escritorio.inicio import argumentos_para

    assert "--oculto" in argumentos_para(Path(r"C:\proyectos\carpetadepruebas"))


def test_oculto_es_un_argumento_que_el_lanzador_conoce() -> None:
    import escritorio.__main__ as carcasa_mod

    fuente = Path(carcasa_mod.__file__).read_text(encoding="utf-8")
    assert '"--oculto"' in fuente


# --- 5. EL MARCO DE LA VENTANA ------------------------------------------


def test_el_marco_se_oscurece_sin_quitar_el_marco() -> None:
    """>>> LO QUE EL USUARIO VIO (2026-08-26) <<<

    La ventana de Jarvis tenia los bordes completamente blancos, los
    tipicos de un programa de Windows antiguo. Y era verdad: una cabina
    azul oscuro dentro de un marco blanco de Windows, porque el marco NO
    es parte de la pagina.
    blanco de Windows, porque el marco NO es parte de la pagina.

    LA SALIDA ES OSCURECERLO, NO QUITARLO. Quitarlo (`frameless`) deja la
    ventana sin barra de la que arrastrar, sin cerrar y sin
    redimensionar: ya se probo con la transparencia y fue parte de lo que
    la hizo inservible.
    """
    from escritorio import __main__ as carcasa

    fuente = Path(carcasa.__file__).read_text(encoding="utf-8")
    # Se mira la LLAMADA, no el texto: la palabra aparece en el comentario
    # que explica por que no se usa, y un test que fallara por eso estaria
    # prohibiendo escribir el motivo.
    assert "frameless=" not in fuente, "el marco se oscurece, no se quita"
    assert "DwmSetWindowAttribute" in fuente


def test_se_prueban_los_dos_numeros_del_atributo() -> None:
    """Microsoft cambio el numero a mitad de Windows 10: 19 desde la
    build 17763 y 20 desde la 18985. Se prueban los dos en vez de mirar
    la build, que es un numero mas que se puede leer mal."""
    from escritorio.__main__ import DWMWA_OSCURO_NUEVO, DWMWA_OSCURO_VIEJO

    assert (DWMWA_OSCURO_NUEVO, DWMWA_OSCURO_VIEJO) == (20, 19)


def test_un_marco_que_no_se_puede_oscurecer_no_tumba_nada() -> None:
    """Es un color. Si Windows no acepta, se queda claro -- feo y
    funcionando --, pero la aplicacion arranca igual."""
    from escritorio.__main__ import marco_oscuro

    assert marco_oscuro(0) is False   # HWND invalido: contesta, no levanta


def test_se_pide_ANTES_de_enseñar_la_ventana() -> None:
    """Puesto ya visible, el marco no se repinta solo: habria que
    esconder y volver a enseñar la ventana, o sea un parpadeo por un
    color. `before_show` evita eso."""
    from escritorio import __main__ as carcasa

    fuente = Path(carcasa.__file__).read_text(encoding="utf-8")
    assert "events.before_show += self._oscurecer_el_marco" in fuente


# --- 6. EL ICONO DE LA VENTANA ------------------------------------------


def _fotogramas(crudo: bytes) -> list[tuple[int, int, str]]:
    """Los fotogramas de un `.ico`: lado, bits y como esta codificado."""
    import struct

    cuantos = struct.unpack("<H", crudo[4:6])[0]
    salida = []
    sitio = 6
    for _ in range(cuantos):
        ancho, _alto, _col, _res, _pl, bits, _tam, donde = struct.unpack(
            "<BBBBHHII", crudo[sitio:sitio + 16])
        png = crudo[donde:donde + 8] == b"\x89PNG\r\n\x1a\x0a"
        salida.append((ancho, bits, "png" if png else "dib"))
        sitio += 16
    return salida


def test_el_ico_va_en_DIB_y_no_en_PNG() -> None:
    """>>> LA TRAMPA MEDIDA (2026-08-27) <<<

    Pillow codifica CADA fotograma como PNG si no se le dice otra cosa, y
    aunque Windows entiende iconos PNG desde Vista, `System.Drawing` no
    del todo: leer de vuelta ese `.ico` devolvia pixeles basura -- el
    centro del disco salia (122, 33, 20) donde el color de "listo" es
    (86, 214, 255).

    Falla si alguien quita `bitmap_format="bmp"`, que es un cambio de una
    palabra y no rompe nada visible: el icono se seguiria viendo bien en
    la barra, y lo que se caeria es cualquier camino que vuelva a leerlo.
    """
    crudo = mod_icono.a_ico(mod_icono.dibujar("listo"))
    formatos = {f for _, _, f in _fotogramas(crudo)}
    assert formatos == {"dib"}, f"hay fotogramas que no son DIB: {formatos}"


def test_el_ico_lleva_todos_los_tamaños_que_windows_pide() -> None:
    """La barra de tareas pide 32, la barra de titulo 16 y Alt+Tab 48.
    Con un solo tamaño Windows escala, y escalar hacia arriba ensucia."""
    crudo = mod_icono.a_ico(mod_icono.dibujar("listo"))
    lados = sorted(ancho for ancho, _, _ in _fotogramas(crudo))
    assert lados == sorted(a for a, _ in mod_icono.TAMANOS)
    assert all(bits == 32 for _, bits, _ in _fotogramas(crudo)), (
        "32 bits o el alfa se pierde y el icono sale con fondo")


def test_el_color_del_estado_sobrevive_al_ico() -> None:
    """Un `.ico` que se genera pero pierde el color diria el estado que
    no es, que es peor que no decir ninguno."""
    import io

    from PIL import Image

    for estado, color in mod_icono.COLORES.items():
        crudo = mod_icono.a_ico(mod_icono.dibujar(estado))
        leido = Image.open(io.BytesIO(crudo)).convert("RGBA")
        centro = leido.getpixel((leido.width // 2, leido.height // 2))
        assert centro[:3] == color, f"{estado}: {centro[:3]} != {color}"
        assert leido.getpixel((0, 0))[3] == 0, (
            f"{estado}: la esquina tiene que ser transparente")


def test_la_ventana_se_viste_ANTES_de_enseñarse() -> None:
    """Puesto ya visible, la barra de tareas ya dibujo el boton con el
    icono de Python y no lo repinta. Mismo motivo que el marco oscuro."""
    from escritorio import __main__ as carcasa

    fuente = Path(carcasa.__file__).read_text(encoding="utf-8")
    assert "events.before_show += self._poner_el_icono" in fuente


def test_el_proceso_se_declara_jarvis_y_no_python() -> None:
    """>>> LO QUE EL USUARIO VIO (2026-08-27) <<<

    En la ventana del programa corriendo solo salia el icono de Python.
    La barra de tareas NO agrupa por ventana sino por
    AppUserModelID, y sin uno declarado Windows lo deduce del ejecutable
    -- que aqui es `pythonw.exe`. Poner el icono en la ventana sin esto
    deja el boton de la barra siendo "Python".

    Se comprueba leyendolo DE VUELTA, no dando por bueno que la llamada
    no levantase: `windll` no lanza sola cuando el HRESULT es de fallo.
    """
    import ctypes

    from escritorio.__main__ import ID_EN_LA_BARRA, identidad_propia

    assert identidad_propia() is True

    puesto = ctypes.c_wchar_p()
    hr = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(
        ctypes.byref(puesto))
    assert hr == 0
    assert puesto.value == ID_EN_LA_BARRA


@pytest.mark.skipif(sys.platform != "win32", reason="es WinForms")
def test_el_icono_llega_al_Form_de_verdad(monkeypatch) -> None:
    """El unico que toca .NET: que `Form.Icon` acabe con el color del
    estado Y DEL TEMA. Lo demas de este bloque mira el `.ico`; esto mira
    el camino entero, que es donde aparecio la trampa del PNG.

    >>> ESTE TEST DEPENDIA DE LOS AJUSTES DEL USUARIO, Y FALLO POR ESO <<<
    Hasta el 2026-08-29 comparaba contra `mod_icono.COLORES`, que es la
    paleta de `jarvis` a secas, mientras que el camino real pasa por
    `tema_elegido()` -- o sea que leia `config/ajustes.yaml`. Verde
    mientras el usuario tuviera el tema de siempre puesto, rojo en
    cuanto eligiera otro. Y fallo asi: el usuario se puso `hacker` para
    mirarlo y la suite se cayo sola, sin que nadie hubiera tocado nada.
    **Un test cuya premisa sale de la configuracion personal de quien lo
    corre no esta midiendo el codigo.** Ahora el tema se FIJA, y de paso
    se prueban los cuatro en vez de uno.
    """
    import types

    clr = pytest.importorskip("clr")
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import Form

    from escritorio.__main__ import Carcasa

    ventana = Form()
    _ = ventana.Handle           # como en before_show: el handle ya existe
    postiza = types.SimpleNamespace(
        ventana=types.SimpleNamespace(native=ventana),
        montaje=_MontajePostizo(),
        con_voz=True,
        _iconos_de_ventana={},
    )
    postiza._icono_de_ventana = types.MethodType(
        Carcasa._icono_de_ventana, postiza)
    poner = types.MethodType(Carcasa._poner_el_icono, postiza)

    estados = [e for e in mod_icono.PALETAS["jarvis"] if e != "fondo"]
    for tema, paleta in mod_icono.PALETAS.items():
        monkeypatch.setattr(mod_icono, "tema_elegido", lambda t=tema: t)
        for estado in estados:
            poner(estado)
            mapa = ventana.Icon.ToBitmap()
            punto = mapa.GetPixel(mapa.Width // 2, mapa.Height // 2)
            assert (punto.R, punto.G, punto.B) == paleta[estado], (tema, estado)

    # Un handle de GDI por estado Y TEMA, no uno por repintado: el latido
    # llama a esto cada vez que cambia, y fabricar uno nuevo los iria
    # soltando. La clave lleva el tema desde el 2026-08-28.
    monkeypatch.setattr(mod_icono, "tema_elegido", lambda: "jarvis")
    poner("roto")
    assert len(postiza._iconos_de_ventana) == len(estados) * len(mod_icono.PALETAS)


# --- 7. EL BOTON DE REINICIAR (2026-08-28) ------------------------------
# Lo que se prueba aqui es el ORDEN, que es lo unico que puede fallar
# callado: **primero se muere y luego se nace**. Si alguien invierte eso
# algun dia, el Jarvis nuevo se encuentra el puerto en manos del viejo
# (JC-0010, `allow_reuse_address = False`) y muere con un WinError 10048
# que el usuario leeria como "el boton esta roto".


def test_reiniciar_sale_por_la_MISMA_puerta_que_salir(carcasa) -> None:
    carcasa.reiniciar()
    assert carcasa.pidio_reinicio is True
    # Exactamente lo mismo que `_salir`: no hay una segunda forma de
    # cerrar la sesion de Claude Code, y no puede haberla.
    assert carcasa.icono.parado == 1
    assert carcasa.ventana.destruida == 1


def test_una_carcasa_recien_hecha_NO_pide_reinicio(carcasa) -> None:
    """La bandera nace en False: salir por la bandeja no debe renacer."""
    carcasa._salir()
    assert carcasa.pidio_reinicio is False


def test_no_se_relanza_contra_el_cerrojo(monkeypatch, tmp_path) -> None:
    """Si el puerto sigue ocupado, NO se lanza nada. Tres salidas.

    Lanzar un Jarvis contra el cerrojo lo mata al instante y deja al
    usuario sin ninguno de los dos: peor que no reiniciar. Se dice y se
    para.
    """
    import socket

    from escritorio import __main__ as mod

    avisos: list[str] = []
    monkeypatch.setattr(mod, "avisar_de_que_no_arranco",
                        lambda motivo, log: avisos.append(motivo))
    lanzados: list[list[str]] = []
    monkeypatch.setattr(mod.subprocess, "Popen",
                        lambda orden, **kw: lanzados.append(orden))
    # Sin espera: el test no puede pagar el margen real de 10 s.
    monkeypatch.setattr(mod, "ESPERA_MAXIMA_S", 0.1)

    with socket.socket() as ocupado:
        ocupado.bind(("127.0.0.1", 0))
        ocupado.listen(1)
        puerto = ocupado.getsockname()[1]
        diario = type("D", (), {"archivo": tmp_path / "log.txt"})()
        assert mod.volver_a_nacer([str(tmp_path), "--voz"],
                                  puerto, diario) is False

    assert lanzados == []
    assert avisos and "No se reinicio" in avisos[0]


def test_se_relanza_con_LOS_MISMOS_argumentos(monkeypatch, tmp_path) -> None:
    """>>> Y POR `-m escritorio`, NO POR LA RUTA DEL ARCHIVO <<<

    `sys.argv[0]` es la ruta de `escritorio/__main__.py`: relanzar por
    ahi pondria `escritorio/` en `sys.path` en vez de la raiz, y el
    primer `from escritorio.salida import encender` reventaria.
    """
    import socket

    from escritorio import __main__ as mod

    lanzados: list[tuple] = []
    monkeypatch.setattr(mod.subprocess, "Popen",
                        lambda orden, **kw: lanzados.append((orden, kw)))
    monkeypatch.setattr(mod, "avisar_de_que_no_arranco",
                        lambda motivo, log: pytest.fail(f"aviso: {motivo}"))

    # Un puerto que se sabe libre: se bindea y se suelta.
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]

    diario = type("D", (), {"archivo": tmp_path / "log.txt"})()
    assert mod.volver_a_nacer([r"C:\proyectos\carpetadepruebas", "--voz"],
                              puerto, diario) is True

    (orden, kw), = lanzados
    assert orden[0] == sys.executable
    assert orden[1:3] == ["-m", "escritorio"]
    assert orden[3:] == [r"C:\proyectos\carpetadepruebas", "--voz"]
    # Desde la raiz, o `-m escritorio` no encuentra el paquete.
    assert Path(kw["cwd"]) == mod.PROJECT_ROOT
    # Sin esto el hijo colgaria de un padre que esta muriendose.
    assert kw["creationflags"] & mod.subprocess.DETACHED_PROCESS
