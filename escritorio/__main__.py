"""Jarvis como aplicacion de escritorio: bandeja, ventana y nada de terminal.

    .venv\\Scripts\\pythonw.exe -m escritorio <carpeta> [--voz] [--oculto]

QUE ES Y QUE NO ES. **No hay UI nueva**: `puente/consola.html` ya es la
interfaz, esta probada y es la que el usuario rediseño. Esto la mete en
una ventana propia y pone un icono en la bandeja para que Jarvis deje de
depender de una terminal abierta. Decidido asi el 2026-08-24, y por eso
se descartaron Electron y Tauri: cadena de herramientas nueva para
duplicar una UI que ya funciona.

>>> EL HILO PRINCIPAL ES DE LA VENTANA, Y ESO MANDA EN TODO EL DISEÑO <<<
pywebview no arranca en otro sitio. Por eso `puente/__main__.py` acepta
un `esperar`: lo que en la terminal es un bucle de espera, aqui es
`webview.start()`. El montaje del puente — suelo, sesion, consola, voz,
escalado — NO se copia: se reutiliza entero, que es lo unico que impide
que la comprobacion del suelo de JC-0007 acabe viviendo en dos sitios
que se van separando.

>>> CERRAR LA VENTANA NO ES SALIR <<<
Es la diferencia entre una pagina y una aplicacion. La X esconde; se sale
por la bandeja. Si cerrar matase el proceso, Jarvis dejaria de escuchar
cada vez que alguien quita una ventana de en medio, y no habria forma de
notarlo hasta que le hablases.

>>> Y SI NO ARRANCA, TIENE QUE VERSE <<<
Sin consola, `print` no escribe en ningun sitio (medido: `sys.stdout` es
None y `print` es un no-op silencioso). La salida se redirige a
`logs/escritorio/` ANTES de montar nada, y un fallo que impide arrancar
se enseña ademas en un cuadro de dialogo: un Jarvis que no arranco es
indistinguible de uno que arranco y no te oye, y esa confusion es la que
este proyecto lleva veinte dias pagando.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Cada cuanto se le pregunta al escalado y se repinta el icono. Es el
# mismo medio segundo que usaba el bucle de la terminal.
LATIDO_S = 0.5

# Cuanto se le da al puerto para que se suelte antes de dar por fallido
# un reinicio. `montaje.cerrar()` ya ha corrido cuando esto se mira, asi
# que lo normal es que la primera pasada lo encuentre libre; el margen
# esta para el cierre que se atraganta, no para el caso bueno.
ESPERA_MAXIMA_S = 10.0


def avisar_de_que_no_arranco(motivo: str, log: Path | None) -> None:
    """Un cuadro de dialogo, que es la unica superficie que queda.

    `MessageBoxW` por `ctypes` y no una libreria: esto tiene que poder
    salir cuando lo que ha fallado es, precisamente, el montaje.
    """
    # El idioma se pide con red debajo: este cuadro sale precisamente
    # cuando algo del montaje ha reventado, y leer los ajustes es una de
    # las cosas que pueden haber reventado. Un aviso en español se lee;
    # un aviso que no sale, no.
    try:
        from nucleo.textos import texto as _t
    except Exception:  # noqa: BLE001
        def _t(_clave, defecto):  # type: ignore[misc]
            return defecto

    texto = motivo
    if log is not None:
        texto += "\n\n" + _t("carcasa.mira_el_log", "El detalle esta en:")
        texto += f"\n{log}"
    try:
        ctypes.windll.user32.MessageBoxW(
            None, texto,
            _t("carcasa.no_arranco", "Jarvis no ha podido arrancar"), 0x10)
    except Exception:  # noqa: BLE001
        print(f"NO ARRANCO: {motivo}")


# El marco de la ventana lo pinta Windows, no nosotros. Estas dos
# constantes son la forma soportada de pedirle que lo pinte oscuro.
#
# >>> POR QUE DOS Y NO UNA <<< Microsoft cambio el numero del atributo a
# mitad de Windows 10: 19 desde la build 17763 y 20 desde la 18985. Se
# prueban las dos y se queda la que conteste bien, en vez de mirar la
# build -- que es un numero mas que se puede leer mal.
DWMWA_OSCURO_NUEVO = 20
DWMWA_OSCURO_VIEJO = 19


def marco_oscuro(hwnd: int) -> bool:
    """Pide a Windows que pinte el marco de esa ventana en oscuro.

    DE DONDE SALE (2026-08-26, el usuario mirandolo): la ventana de
    Jarvis tenia los bordes completamente blancos, los tipicos de un
    programa de Windows antiguo. Y era
    verdad: la aplicacion es una cabina azul oscuro dentro de un marco
    blanco de Windows, porque el marco NO es parte de la pagina.

    NO SE QUITA EL MARCO, SE OSCURECE. Quitarlo (`frameless`) deja la
    ventana sin barra de la que arrastrar, sin boton de cerrar y sin
    redimensionar -- se probo con la transparencia y fue parte de lo que
    la hizo inservible. Un marco oscuro es lo que hace cualquier
    aplicacion con tema oscuro, y no se lleva por delante nada.

    Devuelve si Windows acepto. Que no acepte NO es un fallo que pare
    nada: se queda el marco claro, que es feo y funciona.
    """
    import ctypes
    from ctypes import wintypes

    encendido = ctypes.c_int(1)
    for atributo in (DWMWA_OSCURO_NUEVO, DWMWA_OSCURO_VIEJO):
        try:
            resultado = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), ctypes.c_uint(atributo),
                ctypes.byref(encendido), ctypes.sizeof(encendido))
        except Exception as exc:  # noqa: BLE001
            print(f"  (no se pudo oscurecer el marco: {exc})")
            return False
        if resultado == 0:
            return True
    return False


# Como se llama este proceso para la barra de tareas de Windows.
#
# >>> SIN ESTO, EL ICONO DE LA VENTANA NO BASTA <<< La barra de tareas no
# agrupa por ventana sino por AppUserModelID, y cuando nadie declara uno
# Windows lo deduce del EJECUTABLE -- que aqui es `pythonw.exe`. Por eso
# se veia el icono de Python: la ventana ya podia llevar el suyo, que el
# boton de la barra seguia siendo "Python". Se declara antes de crear
# ninguna ventana, porque Windows lo lee una sola vez.
ID_EN_LA_BARRA = "Jarvis.Voz.ClaudeCode"


def identidad_propia() -> bool:
    """Que la barra de tareas nos cuente como Jarvis y no como Python.

    Devuelve si Windows lo acepto. Que no lo acepte NO para nada: se
    vuelve al icono de Python, que es feo y funciona.
    """
    try:
        # Devuelve un HRESULT, y se MIRA: `windll` no levanta sola cuando
        # falla, asi que darlo por bueno seria decir que se puso cuando
        # puede no haberse puesto. S_OK es 0.
        hr = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            ID_EN_LA_BARRA)
    except Exception as exc:  # noqa: BLE001
        print(f"  (no se pudo declarar la identidad en la barra: {exc})")
        return False
    if hr != 0:
        print(f"  (Windows no acepto la identidad en la barra: HRESULT {hr:#x})")
        return False
    return True


def abrir_en_el_explorador(ruta: Path) -> None:
    try:
        os.startfile(str(ruta))  # noqa: S606 - es una ruta nuestra
    except Exception as exc:  # noqa: BLE001
        print(f"  (no se pudo abrir {ruta}: {exc})")


class Carcasa:
    """La bandeja y la ventana, alrededor de un puente ya montado."""

    def __init__(self, montaje, carpeta: Path, con_voz: bool,
                 oculto: bool, diario) -> None:
        self.montaje = montaje
        self.carpeta = carpeta
        self.con_voz = con_voz
        self.oculto = oculto
        self.diario = diario
        self.ventana = None
        self.icono = None
        # Un `System.Drawing.Icon` por estado, y se REUTILIZAN. Cada uno
        # es un handle de GDI: fabricar uno nuevo en cada repintado los
        # va dejando sueltos, y no se pueden soltar a mano porque la
        # ventana puede estar usando el anterior. Cuatro estados, cuatro
        # handles, y ahi se acaba.
        self._iconos_de_ventana: dict[tuple[str, str], object] = {}
        self._parar = threading.Event()
        self._url = f"http://127.0.0.1:{montaje.puerto}/"
        self.pidio_reinicio = False
        """Si el que sale quiere que nazca otro. Lo lee `main()`.

        Se guarda como bandera en vez de relanzar aqui mismo PORQUE EL
        ORDEN IMPORTA: ver `Carcasa.reiniciar`.
        """

    # --- la vista de ajustes ---------------------------------------------

    def abrir_ajustes(self, _icono=None, _item=None) -> None:
        """Trae la ventana y la pone en la pestaña de ajustes.

        >>> UNA VENTANA, DOS VISTAS -- Y NO DOS VENTANAS <<<
        La primera version abria una ventana aparte y el usuario la
        corrigio nada mas verla: queria una pestana dentro del mismo
        aplicativo, en la misma ventana de Jarvis. Tiene
        razon y ademas es lo que hace una aplicacion de escritorio: la
        ventana es el programa, las pestañas son sus vistas.

        Asi que aqui no se crea nada: se enseña la ventana que ya hay y
        se le dice a la pagina que cambie de pestaña. Si el JS no
        estuviera cargado todavia, `evaluate_js` falla y lo unico que
        pasa es que la ventana se abre en la consola -- que es un sitio
        razonable donde quedarse.
        """
        self._mostrar()
        if self.ventana is None:
            return
        try:
            self.ventana.evaluate_js(
                "window.jarvisVerAjustes && window.jarvisVerAjustes()")
        except Exception as exc:  # noqa: BLE001
            print(f"  (no se pudo cambiar a la pestaña de ajustes: {exc})")

    # --- el latido: escalado + color del icono ---------------------------

    def _latir(self) -> None:
        """El hilo de fondo. Hace lo que hacia el bucle de la terminal, y
        ademas repinta el icono cuando cambia el estado."""
        from escritorio import icono as mod_icono

        # >>> DOS COSAS PINTAN EL ICONO, NO UNA <<< El ESTADO, que es
        # para lo que nacio este latido, y desde el 2026-08-28 tambien el
        # TEMA. Vigilar solo el estado dejaria la bandeja con el color
        # viejo hasta que Jarvis cambiara de estado por su cuenta: el
        # usuario elegiria "despacho", veria la pagina en cafe y el icono
        # seguiria cian sin nada roto que arreglar.
        ultimo = None
        ultimo_tema = None
        while not self._parar.is_set():
            time.sleep(LATIDO_S)
            self.montaje.latir()
            try:
                ahora = mod_icono.estado_de(self.montaje, self.con_voz)
                tema = mod_icono.tema_elegido()
                if (ahora, tema) != (ultimo, ultimo_tema) and self.icono is not None:
                    self.icono.icon = mod_icono.dibujar(ahora, tema)
                    # La ventana lleva el MISMO color que la bandeja: son
                    # el mismo estado, y dos superficies que lo cuentan
                    # distinto es peor que una sola.
                    self._poner_el_icono(ahora)
                    ultimo, ultimo_tema = ahora, tema
            except Exception as exc:  # noqa: BLE001
                # Repintar un icono no puede tumbar el asistente.
                print(f"  (no se pudo repintar el icono: {exc})")

    # --- la bandeja -------------------------------------------------------

    def _menu(self):
        import pystray

        from escritorio import inicio as mod_inicio

        def arranca_con_windows(_item) -> bool:
            return mod_inicio.estado(self.carpeta, voz=self.con_voz).arranca

        def alternar_inicio(_icono, _item) -> None:
            actual = mod_inicio.estado(self.carpeta, voz=self.con_voz)
            if actual.arranca:
                resultado = mod_inicio.quitar()
            else:
                resultado = mod_inicio.poner(self.carpeta, voz=self.con_voz)
            print(f"  inicio con Windows: {mod_inicio.describe(resultado)}")

        # >>> EL MENU SE CONSTRUYE AL MONTAR EL ICONO <<< `pystray` lo
        # pide una vez, asi que el idioma que coja es el de ESE momento.
        # Cambiar el idioma en el panel traduce la pantalla ya y la
        # bandeja al reabrir; prometer las dos cosas seria mentir en la
        # mitad, y por eso el ajuste dice "de la pantalla".
        from nucleo.textos import texto as _t

        return pystray.Menu(
            pystray.MenuItem(_t("bandeja.abrir", "Abrir Jarvis"),
                             self._mostrar, default=True),
            pystray.MenuItem(_t("bandeja.ajustes", "Ajustes"),
                             self.abrir_ajustes),
            pystray.MenuItem(_t("bandeja.navegador", "Abrir en el navegador"),
                             self._al_navegador),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(_t("bandeja.inicio", "Arrancar con Windows"),
                             alternar_inicio, checked=arranca_con_windows),
            pystray.MenuItem(_t("bandeja.log", "Ver el registro de arranque"),
                             self._ver_log),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(_t("bandeja.salir", "Salir"), self._salir),
        )

    def _mostrar(self, _icono=None, _item=None) -> None:
        if self.ventana is not None:
            try:
                self.ventana.show()
                self.ventana.restore()
            except Exception as exc:  # noqa: BLE001
                print(f"  (no se pudo enseñar la ventana: {exc})")

    def _esconder(self, _icono=None, _item=None) -> None:
        """A la bandeja. Lo MISMO que hace la X, y por eso llama alli:
        dos formas de esconder que se separasen serian dos formas de
        dejarse algo."""
        if self.ventana is not None:
            try:
                self.ventana.hide()
            except Exception as exc:  # noqa: BLE001
                print(f"  (no se pudo esconder la ventana: {exc})")

    def _al_navegador(self, _icono=None, _item=None) -> None:
        import webbrowser

        webbrowser.open(self._url)

    def _ver_log(self, _icono=None, _item=None) -> None:
        from escritorio.salida import ultimo_log

        ruta = ultimo_log()
        if ruta is not None:
            abrir_en_el_explorador(ruta)

    def reiniciar(self) -> None:
        """Pide morir para que `main()` levante otro con el mismo argv.

        >>> ESTO NO LANZA NADA, Y ES LO IMPORTANTE <<<
        El cerrojo de "un solo Jarvis" (JC-0010) es el PUERTO, y desde
        que se midio que `allow_reuse_address` lo dejaba pasar en
        silencio vale `False`: bindear un puerto ocupado revienta. Si el
        Jarvis nuevo naciera aqui, se encontraria el puerto todavia en
        manos del viejo -- o sea, el cerrojo puesto por su propio cadaver
        -- y moriria con un WinError 10048 que el usuario leeria como
        "el boton de reiniciar esta roto".

        Asi que aqui solo se levanta la bandera y se sale por la puerta
        de siempre. Quien relanza es `main()`, DESPUES de que
        `montaje.cerrar()` haya soltado el puerto de verdad.
        """
        print("Reiniciando a peticion de la pagina.")
        self.pidio_reinicio = True
        self._salir()

    def _salir(self, _icono=None, _item=None) -> None:
        """La UNICA forma de salir. Ver el docstring del modulo."""
        print("Saliendo por la bandeja.")
        self._parar.set()
        if self.icono is not None:
            self.icono.stop()
        if self.ventana is not None:
            try:
                self.ventana.destroy()
            except Exception:  # noqa: BLE001 - puede que ya no exista
                pass

    # --- la ventana -------------------------------------------------------

    def _icono_de_ventana(self, estado: str):
        """El `.ico` de ese estado Y ESE TEMA, fabricado una vez.

        La clave lleva el tema desde el 2026-08-28: con la clave vieja,
        cambiar de tema devolvia el icono guardado del tema ANTERIOR y la
        ventana se quedaba con el color de antes para siempre -- un
        fallo que solo se ve cambiando de tema dos veces. Cuatro estados
        por cuatro temas son 16 handles como mucho, y solo se fabrican
        los que de verdad se usan.
        """
        from escritorio import icono as _tema_de

        clave = (estado, _tema_de.tema_elegido())
        if clave in self._iconos_de_ventana:
            return self._iconos_de_ventana[clave]

        import clr

        clr.AddReference("System.Drawing")
        from System.Drawing import Icon
        from System.IO import MemoryStream

        from escritorio import icono as mod_icono

        crudo = mod_icono.a_ico(mod_icono.dibujar(estado, clave[1]))
        hecho = Icon(MemoryStream(crudo))
        self._iconos_de_ventana[clave] = hecho
        return hecho

    def _poner_el_icono(self, estado: str | None = None) -> None:
        """El icono de la ventana y del boton de la barra de tareas.

        DE DONDE SALE (2026-08-27, el usuario mirandolo): en la ventana
        del programa corriendo solo salia el icono de Python.
        La bandeja ya tenia el suyo desde el 26; la VENTANA no, porque
        `webview.create_window` no lo pide y WinForms se queda con el del
        ejecutable -- `pythonw.exe`.

        >>> Y VA DESDE EL HILO DE LA VENTANA, NO DESDE EL QUE LLAMA <<<
        `Form.Icon` acaba mandando un mensaje a la ventana, y WinForms no
        deja tocar un control desde otro hilo. Aqui importa de verdad:
        quien repinta es `_latir`, que es el hilo de fondo. Sin el
        `Invoke` funcionaria en el arranque -- que va en el hilo bueno --
        y reventaria justo al cambiar de estado, que es cuando nadie mira.
        """
        nativa = getattr(self.ventana, "native", None)
        if nativa is None:
            return
        from escritorio import icono as mod_icono

        if estado is None:
            estado = mod_icono.estado_de(self.montaje, self.con_voz)
        try:
            hecho = self._icono_de_ventana(estado)

            def vestir() -> None:
                nativa.Icon = hecho

            if nativa.InvokeRequired:
                from System import Action

                nativa.BeginInvoke(Action(vestir))
            else:
                vestir()
        except Exception as exc:  # noqa: BLE001
            # Un icono no puede tumbar el asistente. Mismo trato que el
            # marco oscuro: se queda el de Python, que es feo y funciona.
            print(f"  (no se pudo poner el icono de la ventana: {exc})")

    def _oscurecer_el_marco(self) -> None:
        """El marco de Windows, a juego con la cabina que hay dentro."""
        nativa = getattr(self.ventana, "native", None)
        if nativa is None:
            return
        try:
            hwnd = int(nativa.Handle.ToInt64())
        except Exception as exc:  # noqa: BLE001
            print(f"  (no se encontro la ventana nativa: {exc})")
            return
        if not marco_oscuro(hwnd):
            print("  (Windows no acepto el marco oscuro; se queda claro)")

    def _al_cerrar(self) -> bool:
        """La X esconde, no cierra. Devolver False cancela el cierre."""
        if self._parar.is_set():
            return True   # se esta saliendo de verdad, por la bandeja
        try:
            self.ventana.hide()
        except Exception as exc:  # noqa: BLE001
            print(f"  (no se pudo esconder la ventana: {exc})")
        return False

    def correr(self) -> None:
        """Ocupa el hilo principal con la ventana. No vuelve hasta salir."""
        import pystray
        import webview

        from escritorio import icono as mod_icono

        # >>> JARVIS APRENDE A ENSEÑAR SU PROPIA VENTANA <<<
        # Ni el `Bucle` ni la `Consola` conocen la carcasa -- viven en
        # `voz/` y en `puente/` y no saben que existe pywebview --, asi
        # que se les entregan los gestos y ya esta. Lo pidio el usuario:
        # con Jarvis en la bandeja te oye perfectamente y no habia forma
        # de pedirle que se enseñara.
        #
        # >>> Y SE ENCHUFAN AUNQUE NO HAYA VOZ (2026-09-05) <<<
        # Hasta hoy esto vivia dentro de un `if voz is not None`, o sea
        # que con `--voz` apagado no habia a quien pedirle nada -- y ese
        # es justo el modo en el que SOLO existe la consola, que es desde
        # donde el usuario reporto que "apagate" no le hacia caso. Eran
        # dos fallos, uno debajo del otro.
        # Van a UN objeto que comparten la consola y la voz
        # (`nucleo.carcasa.Gestos`): dos juegos de atributos serian dos
        # sitios que enchufar, y olvidarse de uno no da error -- da la
        # misma frase haciendo cosas distintas segun el canal.
        #
        # >>> "APAGATE" SALE POR LA MISMA PUERTA QUE LA BANDEJA <<<
        # `_salir` es la UNICA forma de salir (ver el docstring del
        # modulo), y por ahi se pasa por `montaje.cerrar()`, que es quien
        # cierra la sesion de Claude Code. Un apagado que matase el
        # proceso por otro lado dejaria vivo el hijo `claude`, que es
        # justo lo contrario de lo que se pidio.
        gestos = self.montaje.consola.gestos
        gestos.mostrar = self._mostrar
        gestos.esconder = self._esconder
        gestos.apagar = self._salir

        threading.Thread(target=self._latir, daemon=True,
                         name="latido").start()

        self.icono = pystray.Icon(
            "jarvis",
            icon=mod_icono.dibujar(
                mod_icono.estado_de(self.montaje, self.con_voz),
                mod_icono.tema_elegido()),
            title="Jarvis",
            menu=self._menu(),
        )
        # La bandeja va en un hilo: el principal lo necesita la ventana.
        threading.Thread(target=self.icono.run, daemon=True,
                         name="bandeja").start()

        self.ventana = webview.create_window(
            "Jarvis", self._url, width=1180, height=820,
            hidden=self.oculto, text_select=True,
        )
        # ANTES de enseñarla, no despues: puesto ya visible, el marco no
        # se repinta solo y habria que esconder y volver a enseñar la
        # ventana -- un parpadeo por un color.
        self.ventana.events.before_show += self._oscurecer_el_marco
        # El icono TAMBIEN antes de enseñarla: puesto despues, la barra de
        # tareas ya ha dibujado el boton con el de Python y no lo repinta.
        self.ventana.events.before_show += self._poner_el_icono
        self.ventana.events.closing += self._al_cerrar
        print(f"Carcasa lista. Ventana {'oculta' if self.oculto else 'abierta'}"
              f" sobre {self._url}")
        webview.start()
        print("La ventana se cerro; cerrando el resto.")
        self._parar.set()


def volver_a_nacer(argumentos: list[str], puerto: int,
                   diario) -> bool:
    """Levanta otro Jarvis con los MISMOS argumentos. Solo tras morir.

    >>> SE RECONSTRUYE `-m escritorio`, NO SE REPITE `sys.argv` <<<
    `sys.argv[0]` aqui es la RUTA de `escritorio/__main__.py`, y
    relanzar por ruta pondria `escritorio/` en `sys.path` en vez de la
    raiz: el primer `from escritorio.salida import encender` reventaria.
    Ademas `main()` machaca `sys.argv` entero con el del puente antes de
    ceder el hilo, asi que el original hay que haberlo guardado antes.

    >>> Y SE ESPERA AL PUERTO, QUE ES EL CERROJO <<<
    Tres respuestas y no dos: se solto / no se solto / no se
    sabe. Si a los `ESPERA_MAXIMA_S` el puerto sigue ocupado, NO se
    lanza nada -- un Jarvis que arranca contra el cerrojo muere solo y
    deja al usuario sin ninguno de los dos.
    """
    from puente.suelo import QuienTieneElPuerto, quien_tiene_el_puerto

    plazo = time.monotonic() + ESPERA_MAXIMA_S
    quien, detalle = quien_tiene_el_puerto(puerto)
    while quien is not QuienTieneElPuerto.LIBRE and time.monotonic() < plazo:
        time.sleep(0.2)
        quien, detalle = quien_tiene_el_puerto(puerto)
    if quien is not QuienTieneElPuerto.LIBRE:
        avisar_de_que_no_arranco(
            f"No se reinicio: {detalle}. Jarvis se ha cerrado; abrelo a "
            f"mano cuando el puerto {puerto} quede libre.", diario.archivo)
        return False

    orden = [sys.executable, "-m", "escritorio", *argumentos]
    print(f"Levantando el Jarvis nuevo: {orden}")
    try:
        # DETACHED_PROCESS: el hijo NO puede colgar del padre, que esta
        # a punto de morirse. Y `cwd` en la raiz para que `-m escritorio`
        # encuentre el paquete.
        subprocess.Popen(
            orden, cwd=str(PROJECT_ROOT),
            creationflags=(subprocess.DETACHED_PROCESS
                           | subprocess.CREATE_NEW_PROCESS_GROUP),
            close_fds=True)
    except Exception as exc:  # noqa: BLE001
        avisar_de_que_no_arranco(
            f"No se pudo relanzar Jarvis: {type(exc).__name__}: {exc}",
            diario.archivo)
        return False
    return True


def main() -> int:
    # LO PRIMERO, antes de importar nada pesado: si el montaje revienta,
    # el traceback tiene que caer en el log y no en el vacio.
    from escritorio.salida import encender

    diario = encender()

    # >>> SE GUARDA AHORA O NO SE GUARDA <<<
    # Mas abajo `sys.argv` se machaca ENTERO con el del puente para
    # poder reutilizar su `main()`. El boton de reiniciar necesita los
    # argumentos con los que arranco ESTE Jarvis, y despues de esa linea
    # ya no existen en ningun sitio.
    argumentos_originales = list(sys.argv[1:])

    # Antes de que exista ninguna ventana: Windows lee esto una vez y ya.
    identidad_propia()

    trozos = argparse.ArgumentParser(
        description="Jarvis de escritorio: bandeja y ventana")
    # Opcional: si no se da, se usa la carpeta de los ajustes. Es lo que
    # hace que "carpeta de trabajo" en el panel signifique algo -- si no,
    # seguiria congelada dentro del acceso directo, que es justo lo que la
    # carcasa habia roto.
    trozos.add_argument("directorio", nargs="?")
    trozos.add_argument("--puerto", type=int, default=8731)
    trozos.add_argument("--modelo", default="sonnet")
    trozos.add_argument("--voz", action="store_true")
    trozos.add_argument("--sin-seguimiento", action="store_true")
    trozos.add_argument("--sin-narracion", action="store_true")
    trozos.add_argument("--resumir", action="store_true")
    trozos.add_argument("--sin-preambulo", action="store_true",
                        help="para medir contra el otro lado: sin esto, el "
                             "cerebro no sabe que le hablan por un altavoz")
    trozos.add_argument("--oculto", action="store_true",
                        help="arranca en la bandeja, sin abrir la ventana. Es "
                             "lo que usa el acceso directo del inicio de "
                             "Windows: nadie quiere una ventana en cada boot")
    args = trozos.parse_args()

    # La carcasa lee los ajustes ANTES de delegar en el puente, asi que
    # tiene que sembrar ella tambien. No basta con hacerlo en un sitio:
    # este es el camino por el que arranca casi todo el mundo.
    from nucleo.ajustes import valor_de as _ajuste
    from nucleo.configuracion import sembrar_base

    sembrar_base()

    crudo = args.directorio or str(_ajuste("sesion.carpeta", "") or "")
    if not crudo:
        # >>> Y ESTE MENSAJE MANDABA A EDITAR UN YAML <<< Lo pillo el
        # usuario el 2026-09-05 preparando el codigo abierto: la primera
        # pared con la que se choca alguien nuevo no puede contestarle
        # con el nombre de un archivo y una clave. La carpeta se elige en
        # la pantalla, y hay una forma de llegar a la pantalla sin
        # carpeta: pasarla por la linea de ordenes esta vez.
        avisar_de_que_no_arranco(
            "No hay carpeta de trabajo todavia. Arranca una vez pasandola "
            "detras del comando, y luego dejala puesta en AJUSTES > Para "
            "empezar > Carpeta de trabajo; a partir de ahi ya no hace "
            "falta escribirla.",
            diario.archivo)
        return 2
    carpeta = Path(crudo).expanduser()
    llego_a_montar = threading.Event()

    # La carcasa nace dentro de `esperar` -- es donde hay montaje -- y
    # `main()` necesita preguntarle despues si pidio reiniciar. Una lista
    # y no una variable: `esperar` es un cierre y solo puede MUTAR.
    carcasas: list[Carcasa] = []

    def esperar(montaje) -> None:
        """Aqui el puente ya esta servido y nos cede el hilo principal."""
        llego_a_montar.set()
        carcasa = Carcasa(montaje, carpeta=carpeta, con_voz=args.voz,
                          oculto=args.oculto, diario=diario)
        carcasas.append(carcasa)
        # El boton de reiniciar de la pagina. Sin esta linea la consola
        # lo pinta APAGADO en vez de fallar al pulsarlo -- que es lo que
        # pasa, a proposito, cuando se lanza `-m puente` a mano.
        montaje.consola.al_reiniciar = carcasa.reiniciar
        carcasa.correr()

    import puente.__main__ as lanzador

    # `--sin-navegador` SIEMPRE: la ventana es la ventana. Sin esto se
    # abriria ademas una pestaña del navegador en cada arranque.
    sys.argv = ["puente", str(carpeta), "--puerto", str(args.puerto),
                "--modelo", args.modelo, "--sin-navegador"]
    if args.voz:
        sys.argv.append("--voz")
    if args.sin_seguimiento:
        sys.argv.append("--sin-seguimiento")
    if args.sin_narracion:
        sys.argv.append("--sin-narracion")
    if args.resumir:
        sys.argv.append("--resumir")
    if args.sin_preambulo:
        # El A/B tiene que poder hacerse desde donde de verdad se arranca:
        # el acceso directo pasa por aqui, no por `-m puente`.
        sys.argv.append("--sin-preambulo")

    try:
        codigo = lanzador.main(esperar=esperar)
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        avisar_de_que_no_arranco(
            f"{type(exc).__name__}: {exc}", diario.archivo)
        return 1

    # >>> AQUI YA NO HAY PUERTO NUESTRO <<< `lanzador.main` cierra el
    # montaje en su `finally`, o sea que la consola ya solto el socket.
    # Este es el unico instante en el que se puede nacer sin chocar con
    # el cerrojo de JC-0010.
    if carcasas and carcasas[0].pidio_reinicio:
        volver_a_nacer(argumentos_originales, args.puerto, diario)
        return codigo

    if codigo != 0 and not llego_a_montar.is_set():
        # >>> LA PARTE QUE NO PUEDE QUEDARSE MUDA <<<
        # Los codigos 2/3/5/6/7 del lanzador son cosas que el usuario
        # puede arreglar -- carpeta que no existe, suelo roto, otro
        # Jarvis ya abierto --, y cada uno imprime su motivo. Sin
        # terminal ese motivo se lo lleva el log, asi que la ultima linea
        # util se enseña tambien en un cuadro.
        ultimas = [l for l in diario.ultimas if l.strip()]
        motivo = ultimas[-1] if ultimas else f"el lanzador devolvio {codigo}"
        avisar_de_que_no_arranco(motivo, diario.archivo)
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
