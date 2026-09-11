"""Arranca el puente con su consola.

    .venv\\Scripts\\python.exe -m puente <directorio> [--puerto 8731]
                                        [--modelo sonnet] [--sin-navegador]

Abre UNA sesion de Claude Code acotada a ese directorio, levanta la
consola en 127.0.0.1 y se queda ahi. Ctrl+C para salir.

El primer turno lo escribe el usuario en la consola: `system/init` no
llega hasta que hay un turno en marcha, asi que hasta entonces la sesion
esta lanzada pero muda, y la comprobacion de la puerta todavia no se ha
podido hacer. Es exactamente lo que dice el estado "callada".

SALVO cuando el suelo de JC-0007 esta SIN_VERIFICAR: entonces el primer
turno lo gasta el propio puente en plantar un senuelo dentro de una zona
obligatoria y comprobar CONTRA DISCO que la escritura se rechaza. Ese
turno tambien trae el `system/init`, asi que de paso verifica la puerta
antes de que el usuario pueda pedir nada.

AQUI EL SUELO ES OBLIGATORIO, y es la diferencia con `Sesion`, que
admite arrancar sin el. Un lanzador que siguiera adelante con el suelo
roto daria un asistente que parece protegido y no lo esta.

UN SOLO JARVIS A LA VEZ, y UNA SOLA SESION de Claude Code por Jarvis.
Lo primero se comprueba mirando quien tiene el puerto, con tres
respuestas: ya hay un Jarvis / lo tiene otro programa / no se sabe. Lo
segundo es una decision de producto: llevar varias sesiones a la vez
seria mas potente, pero abre el problema de a CUAL va una orden hablada,
asi que queda como ajuste experimental y tendra su ADR.

ARRANCA MUDO. La sesion de Claude Code NO se abre aqui: se abre con la
primera orden de verdad. Pensado para que esto viva en el inicio de
Windows, donde abrir el binario de 337 MB en cada boot -- y pagar un
turno de senuelo cada vez que se autoactualiza -- seria gasto puro.
Y tiene una propiedad que conviene no perder: mientras nadie pide nada,
NO HA SALIDO NADA DE LA MAQUINA.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from puente.consola import Consola
from puente.sesion import ESFUERZOS, Sesion
from puente.suelo import (
    EstadoSuelo,
    QuienTieneElPuerto,
    preparar,
    primer_puerto_libre,
    quien_tiene_el_puerto,
    Senuelo,
    verificar_con_senuelo,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Montaje:
    """Lo que queda en pie cuando el puente ya esta servido.

    Existe para una sola cosa: que el HILO PRINCIPAL se pueda ceder. En
    la terminal lo ocupa un bucle de espera; con la carcasa de escritorio
    lo tiene que ocupar la ventana, porque pywebview no arranca en otro
    sitio. Sin esta costura, `escritorio/` habria tenido que copiarse los
    120 lineas de montaje de aqui -- y entonces el suelo de JC-0007 se
    comprobaria en dos sitios que se irian separando.
    """

    sesion: Any
    consola: Any
    voz: Any
    escalado: Any
    carpeta: Path
    puerto: int
    buzon: Any = None
    """JC-0016: lo que RECOGE de Telegram, si esta encendido."""

    def latir(self) -> None:
        """Un tick del tercer canal. Barato: mira una tupla en memoria.

        Un fallo del escalado NO puede tumbar el proceso -- se llevaria
        por delante la consola y la voz, que si funcionan --, asi que se
        dice y se sigue.
        """
        try:
            self.escalado.revisar(
                self.sesion.pendientes,
                abierta=self.sesion.pregunta_abierta)
        except Exception as exc:  # noqa: BLE001
            print(f"  (fallo escalando: {type(exc).__name__}: {exc})")
        if self.buzon is not None:
            # Se pregunta desde aqui y no desde un hilo propio, igual que
            # el escalado: un hilo mas seria un sitio mas donde algo puede
            # quedarse colgado sin que nadie lo mire. El freno de los
            # segundos lo lleva el propio buzon.
            try:
                self.buzon.revisar()
            except Exception as exc:  # noqa: BLE001
                print(f"  (fallo recogiendo de Telegram: "
                      f"{type(exc).__name__}: {exc})")

    def cerrar(self) -> None:
        if self.voz is not None:
            self.voz.parar()
        self.consola.parar()
        self.sesion.cerrar()


# >>> "NO HAY VOZ" SON DOS COSAS, Y HASTA EL 2026-09-10 ERAN UNA <<<
# Lo reporto el usuario probando: paso la voz al español, el perfil se
# quedo en `jarvis_en`, `voz/perfil.py` se nego a arrancar -- que es lo
# correcto -- y el resumen del arranque le contesto "usa --voz para
# encenderla" a alguien que acababa de arrancar con `--voz`. No solo no
# ayuda: CONTRADICE el aviso de doce lineas mas arriba, asi que quien
# lea el final se lleva que la voz esta apagada porque no la pidio.
# Viven fuera de `main` para que se puedan probar las tres salidas, que
# es lo que no se podia hacer cuando esto era un `if/else` de dos ramas
# a mitad de una funcion de 400 lineas.


def resumen_sin_voz(fallo: str | None) -> str:
    """La linea del arranque cuando NO hay voz. `None` = no se pidio."""
    if fallo is None:
        return "Voz apagada (usa --voz para encenderla)."
    return ("Voz PEDIDA y NO encendida; el motivo, unas lineas mas arriba "
            "y en la consola.")


def aviso_de_voz_caida(fallo: str) -> str:
    """Lo que va a la PANTALLA cuando la voz no arranca.

    Solo la primera linea del fallo, que es la accionable: la de
    `TTSError` trae debajo dos renglones de explicacion que en el diario
    valen y en una tarjeta de la consola solo estorban. El detalle entero
    sigue yendo al log, que es donde se mira despues.
    """
    return (f"NO SE PUDO ENCENDER LA VOZ: {fallo.splitlines()[0]} "
            "La consola sigue funcionando; la escucha, no.")


def _esperar_en_la_terminal(montaje: "Montaje") -> None:
    """Lo que hace el hilo principal cuando se lanza desde una consola."""
    while True:
        time.sleep(0.5)
        montaje.latir()


def main(esperar: "Callable[[Montaje], None] | None" = None) -> int:
    trozos = argparse.ArgumentParser(description="Puente a Claude Code")
    trozos.add_argument("directorio", help="carpeta a la que se acota la sesion")
    trozos.add_argument("--puerto", type=int, default=8731)
    trozos.add_argument("--modelo", default="sonnet")
    trozos.add_argument("--sin-navegador", action="store_true")
    trozos.add_argument("--voz", action="store_true",
                        help="enciende la escucha: wake word, orden hablada y "
                             "respuesta locutada (JC-0011)")
    trozos.add_argument("--sin-seguimiento", action="store_true",
                        help="JC-0012: NO sigue escuchando tras cada "
                             "respuesta. La escucha se abrira igualmente "
                             "cuando Jarvis te pregunte algo")
    trozos.add_argument("--sin-narracion", action="store_true",
                        help="NO locuta lo que Claude Code va contando "
                             "mientras trabaja. Por defecto SI se locuta, "
                             "filtrado para que no lleguen rutas ni comandos "
                             "al TTS")
    trozos.add_argument("--sin-preambulo", action="store_true",
                        help="NO le dice a Claude Code que le hablan por un "
                             "altavoz. Solo para medir contra el otro lado: "
                             "sin esto, escribe para una pantalla y su "
                             "respuesta se locuta entera igual")
    trozos.add_argument("--resumir", action="store_true",
                        help="locuta solo una o dos frases y deja el detalle "
                             "en la consola (JC-0004). Por defecto se dice la "
                             "respuesta ENTERA, que es lo que pidio el usuario")
    args = trozos.parse_args()

    # >>> LOS AJUSTES DE LA CONSOLA MANDAN, LA LINEA DE ORDENES GANA <<<
    # La carcasa de escritorio arranca de un acceso directo, asi que las
    # opciones que antes se escribian a mano quedaron congeladas dentro
    # de un `.lnk`. Se leen de `config/ajustes.yaml` para que el panel
    # sirva de algo; una opcion puesta EXPLICITAMENTE en la linea de
    # ordenes sigue pesando mas, porque quien la escribe la esta pidiendo
    # para esta vez.
    from nucleo.ajustes import valor_de
    from nucleo.configuracion import sembrar_base

    # >>> LO PRIMERO DE TODO: QUE HAYA CONFIGURACION <<<
    # Va antes de la primera lectura porque `jarvis.yaml` es el unico
    # archivo obligatorio, y quien acaba de descargar esto no lo tiene.
    # Sin esta linea, el primer arranque de una copia limpia muere con un
    # `ConfigError` y la unica salida seria copiar un archivo a mano.
    sembrado = sembrar_base()
    if sembrado == "sembrada":
        print("  Primera vez: configuracion creada en config/jarvis.yaml a "
              "partir de la base. No hace falta tocarla: todo se ajusta "
              "desde la pestaña AJUSTES.")
    elif sembrado == "sin_base":
        # Tercera salida. No es un arranque limpio: es un arbol
        # al que le falta algo, y decirlo aqui ahorra buscar el
        # `ConfigError` que viene detras.
        print("  (no hay config/base/jarvis.yaml: si tampoco tienes "
              "config/jarvis.yaml, esto no va a arrancar)")

    con_voz = args.voz or bool(valor_de("voz.encendida", False))
    seguimiento = (not args.sin_seguimiento) and bool(
        valor_de("voz.seguimiento", True))
    resumir = args.resumir or bool(valor_de("voz.resumir", False))
    narrar = (not args.sin_narracion) and bool(
        valor_de("voz.narrar", True))

    # >>> SOLO CON LA VOZ ENCENDIDA, Y NO ES UNA OPTIMIZACION <<<
    # El preambulo le dice al cerebro que le leen en alto. Sin altavoz eso
    # es falso de cabo a rabo, y ademas le pediria prosa corta a cambio de
    # tablas -- o sea que empeoraria la consola, que sin voz es la unica
    # salida que hay. Se compone AQUI porque este es el unico sitio que
    # sabe si hay voz, igual que pasa con `modo_permisos`.
    preambulo = None
    if con_voz and not args.sin_preambulo:
        from voz.preambulo import preambulo as texto_del_preambulo

        # `resumido` sale del MISMO `resumir` que recibe el bucle de voz,
        # y no de una segunda lectura del ajuste: si discreparan, se le
        # estaria diciendo al modelo que se locuta entera mientras el TTS
        # la corta a 240 caracteres -- o al reves. Ninguna de las dos deja
        # rastro, porque la respuesta suena igual de bien en ambos casos.
        preambulo = texto_del_preambulo(resumido=resumir)
    if args.modelo == "sonnet":   # o sea: no lo pidio a mano
        args.modelo = str(valor_de("sesion.modelo", "sonnet"))

    # >>> `--effort`, Y SE VALIDA AQUI PORQUE EL BINARIO NO LO HACE <<<
    # Medido el 2026-09-01: `--effort disparate` no da error, se IGNORA
    # con un aviso por stderr -- que en este montaje llega como
    # `LineaIlegible`, o sea que no se ve. El panel ofrece una lista, asi
    # que un valor malo solo puede venir de editar el YAML a mano: se
    # dice en voz alta y se arranca SIN el flag, en vez de arrancar
    # creyendo que esta puesto.
    esfuerzo = str(valor_de("sesion.esfuerzo", "") or "").strip() or None
    if esfuerzo is not None and esfuerzo not in ESFUERZOS:
        print(f"AVISO: sesion.esfuerzo = '{esfuerzo}' no vale. Hay: "
              f"{', '.join(ESFUERZOS)}. Se arranca sin el.")
        esfuerzo = None

    carpeta = Path(args.directorio).expanduser()
    if not carpeta.is_dir():
        print(f"No existe la carpeta: {carpeta}")
        return 2

    # UN SOLO JARVIS, y se comprueba ANTES de preparar nada. Dos serian
    # dos micros escuchando la misma sala y dos politicas sobre la misma
    # PC -- que es lo que rechazo ADR-0018. Ojo: una sesion de Claude Code
    # por Jarvis, no varias; el multi-sesion queda como ajuste
    # experimental futuro y tendra su propio ADR.
    quien, detalle = quien_tiene_el_puerto(args.puerto)
    if quien is QuienTieneElPuerto.OTRO_JARVIS:
        print(f"{detalle}.")
        print("No se arranca otro: abre el que ya hay en "
              f"http://127.0.0.1:{args.puerto}/")
        return 5
    if quien is QuienTieneElPuerto.OTRO_PROGRAMA:
        print(f"{detalle}.")
        libre = primer_puerto_libre(args.puerto)
        if libre is not None:
            print(f"Prueba con otro: -m puente <carpeta> --puerto {libre}")
        else:
            print("Y no se encontro ninguno libre cerca; elige uno a mano.")
        return 6
    if quien is QuienTieneElPuerto.NO_SE_SABE:
        # Tercera salida de verdad: no se finge que esta libre.
        print(f"{detalle}.")
        print("No se arranca a ciegas sobre un puerto que no se sabe de quien es.")
        return 7

    # El registro crudo es la materia prima de la auditoria: se guarda
    # el flujo ENTERO, no solo lo que se decidio.
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    registro = PROJECT_ROOT / "logs" / "puente" / f"sesion_{marca}.jsonl"

    # El suelo de JC-0007, ANTES de lanzar nada. Es barato -- disco y
    # comprobaciones locales -- y `comprobar_vigencia` solo protege si de
    # verdad corre en cada arranque.
    suelo = preparar(
        destino=PROJECT_ROOT / "logs" / "puente" / "suelo.json",
        sello=PROJECT_ROOT / "logs" / "puente" / "suelo.sello",
    )
    print(suelo.resumen)
    if not suelo.estado.se_puede_arrancar:
        print("\nNO SE ARRANCA. El suelo no esta en condiciones, y una sesion "
              "sin suelo no avisa de que no lo tiene:")
        print(f"  {suelo.motivo}")
        return 3

    # La lista blanca de MCP (JC-0015). Se lee AQUI y se le entrega a la
    # sesion: si el archivo no existe la tupla sale vacia, y vacia
    # significa "ninguno declarado", que es lo que hace que un servidor
    # nuevo no actue el dia que alguien lo instale sin avisar.
    from nucleo.mcp import leer as leer_mcp

    servidores_mcp = leer_mcp()

    # >>> Y LOS QUE JARVIS ARRANCA EL MISMO (2026-09-01) <<<
    # La lista de arriba es PERMISO; esto es EXISTENCIA. Hasta hoy solo
    # habia lo primero, o sea una lista blanca gobernando una puerta que
    # no llevaba a ningun sitio: comprobado que en esta maquina no hay ni
    # un servidor MCP configurado en ningun sitio.
    # El archivo va a `logs/` y no a `config/` porque es GENERADO -- igual
    # que el suelo -- y porque puede llevar dentro un token ya resuelto:
    # `logs/*` esta en el `.gitignore` y `config/mcp.yaml` no.
    from nucleo.mcp import configuracion_para_claude

    mcp_config = None
    lanzables = configuracion_para_claude(servidores_mcp)["mcpServers"]
    if lanzables:
        mcp_config = PROJECT_ROOT / "logs" / "puente" / "mcp.json"
        mcp_config.parent.mkdir(parents=True, exist_ok=True)
        mcp_config.write_text(
            json.dumps({"mcpServers": lanzables}, indent=2, ensure_ascii=False),
            encoding="utf-8")
    mcp_estricto = bool(valor_de("mcp.estricto", False))
    # Se DICE, y no solo se escribe: cada uno de estos es un PROCESO que
    # se arranca con la sesion, no una regla en un archivo.
    if lanzables or servidores_mcp:
        print(f"MCP: {len(lanzables)} servidor(es) que arranca Jarvis, "
              f"{len(servidores_mcp)} declarado(s) en la lista blanca"
              + (" (estricto: ninguno mas)" if mcp_estricto else ""))

    # >>> EN QUE MODO ABRE ESTA CARPETA (JC-0017) <<<
    # Lo decide `nucleo.proyectos.modo_para` y no este archivo, porque el
    # cambio de proyecto hablando tiene que llegar a la MISMA respuesta:
    # dos sitios calculandolo darian un proyecto que abre con freno al
    # arrancar y sin freno al cambiarse a el, sin un solo error.
    from nucleo.proyectos import modo_para

    modo = modo_para(carpeta)
    sesion = Sesion(carpeta, modelo=args.modelo, registro=registro,
                    ajustes=suelo.archivo, zonas=suelo.zonas,
                    servidores_mcp=servidores_mcp, modo_permisos=modo,
                    preambulo=preambulo, mcp_config=mcp_config,
                    mcp_estricto=mcp_estricto, esfuerzo=esfuerzo)
    if modo != "default":
        # Se DICE en el arranque, y no solo se pinta: es la unica sesion
        # en la que un borrado no va a preguntar, y enterarse de eso
        # leyendo el registro despues es enterarse tarde.
        print(f"  auto mode ON ({modo}): no se preguntara por borrados, "
              f"`git push` ni MCP sin autorizar.")
        print("  Siguen en pie las zonas selladas del sistema, y la consola "
              "ensena cada herramienta.")
    consola = Consola(sesion, puerto=args.puerto, suelo=suelo)

    def abrir_de_verdad() -> tuple[bool, str]:
        r"""Lo que ocurre la PRIMERA vez que llega una orden.

        Aqui es donde el asistente deja de ser local: hasta este momento
        no ha salido nada de la maquina. Por eso la comprobacion del
        suelo va JUSTO aqui y no antes -- se paga cuando de verdad se va
        a usar, con la sesion recien abierta y no a mitad de una orden.

        El senuelo solo se paga si cambiaron las reglas o el binario. Con
        la app en el inicio de Windows eso importa: sin esto, cada
        actualizacion automatica de `claude` costaria un turno en el
        siguiente arranque, lo pidiera el usuario o no.

        >>> Y EL SENUELO VA EN SU PROPIA SESION, NO EN LA DEL USUARIO <<<
        Lo vio el usuario el 2026-08-27: dijo "continua con el proyecto
        redactor", ADR-0029 movio la sesion a `C:\proyectos\Delta`
        y lo PRIMERO que se mando alli fue el senuelo -- que se comio el
        turno del ritual ("hola, en que nos quedamos?") y dejo una
        escritura de comprobacion en la transcripcion de su proyecto.

        La comprobacion es del suelo de la MAQUINA, no del proyecto: no
        pinta nada dentro de la conversacion de nadie, ni gastandole el
        primer turno ni metiendose en su contexto. Se abre una sesion
        aparte, en la carpeta base, se gasta el turno alli y se cierra.
        Cuesta un arranque en frio (~3,5 s, medido en JC-0003) y se paga
        una vez por actualizacion de `claude`.
        """
        nonlocal suelo
        # >>> SE DICE EN LA PANTALLA, NO SOLO EN EL LOG (2026-09-03) <<<
        # Estos avisos existian como `print` y se los comia
        # `escritorio/salida.py`, porque con `pythonw` no hay consola. El
        # usuario se quedaba mirando una caja vacia sin saber si se habia
        # colgado. Medido ese dia: **6,65 s con el binario en frio** solo
        # para abrir, y minutos si ademas toca senuelo. Ver
        # `-m eval.mirar_el_primer_turno`.
        if suelo.estado is not EstadoSuelo.SIN_VERIFICAR:
            consola.avisa("Primera orden: abriendo la sesion de Claude Code. "
                          "Tarda unos segundos la primera vez.")
            sesion.abrir()
            return True, "sesion abierta"

        # Este es el caro, y es el que el usuario nunca supo que existia:
        # se paga UNA VEZ POR ACTUALIZACION de `claude` -- que se
        # actualiza solo --, asi que aparece de repente un dia
        # cualquiera. Decir cuanto cuesta y por que es lo que lo
        # distingue de estar colgado.
        consola.avisa(
            "Primera orden: `claude` cambio de version, asi que hay que "
            "volver a comprobar que el suelo muerde. Cuesta un turno "
            "entero en una sesion aparte y puede tardar. No esta colgado.")
        aparte = Sesion(carpeta, modelo=args.modelo, registro=registro,
                        ajustes=suelo.archivo, zonas=suelo.zonas,
                        servidores_mcp=servidores_mcp)
        try:
            aparte.abrir()
            veredicto, detalle = verificar_con_senuelo(
                aparte, suelo,
                sello=PROJECT_ROOT / "logs" / "puente" / "suelo.sello")
        finally:
            aparte.cerrar()
        consola.avisa(detalle)

        # >>> TRES SALIDAS, Y LAS DOS MALAS NO SE DICEN IGUAL <<<
        # "no muerde" es un suelo roto; "no se sabe" es un suelo sin
        # probar. Los dos impiden arrancar -- JC-0007 no da por bueno lo
        # que no se ha demostrado --, pero quien lea el aviso tiene que
        # poder distinguirlos, porque no se arreglan igual.
        if veredicto is Senuelo.NO_MUERDE:
            return False, ("las reglas estan puestas y no hacen nada, que es "
                           "peor que no tenerlas porque parece que si")
        if veredicto is Senuelo.NO_SE_SABE:
            return False, (f"no se ha podido comprobar que el suelo muerda "
                           f"({detalle}). No se arranca sobre un suelo sin "
                           f"probar: vuelve a intentarlo")

        sesion.abrir()
        # El objeto se creo ANTES de la comprobacion, asi que hay que
        # ponerlo al dia o la consola enseñaria "sin_verificar" para
        # siempre, con el suelo ya demostrado. Un aviso que no se apaga
        # nunca es un aviso que se aprende a ignorar.
        suelo = replace(suelo, estado=EstadoSuelo.LISTO, motivo=detalle)
        consola.suelo = suelo
        return True, detalle

    consola.al_primer_turno = abrir_de_verdad

    # El tercer canal (JC-0006 + JC-0009). Se monta SIEMPRE, tambien sin
    # configurar: `Telegram.disponible` es False y el escalado no hace
    # nada, pero la consola puede enseñar el estado y dejar ponerlo. Un
    # ajuste que no se ve no existe.
    from canales.escalado import Escalado
    from canales.telegram import Telegram

    canal_telegram = Telegram()
    escalado = Escalado(canal=canal_telegram, directorio=str(carpeta),
                        tras_minutos=float(
                            valor_de("tiempos.telegram_minutos", 5.0)))
    escalado.presencia.ausente_tras_s = float(
        valor_de("tiempos.ausente_minutos", 5.0)) * 60.0
    consola.escalado = escalado

    # JC-0016: la mitad que ESCUCHA. Se monta siempre; si el interruptor
    # `responde` esta apagado, `disponible` es False y no toca la red.
    from canales.respuestas import Buzon
    from canales.telegram import TelegramEntrada
    from canales.telegram import leer as leer_telegram

    entrada_telegram = TelegramEntrada(leer_telegram())
    # Lo pendiente de antes de arrancar se TIRA sin contestarlo: un
    # mensaje escrito con Jarvis apagado no puede contestar la primera
    # pregunta que aparezca al encenderlo.
    entrada_telegram.ponerse_al_dia()
    buzon = Buzon(entrada=entrada_telegram, sesion=sesion,
                  canal=canal_telegram)
    consola.buzon = buzon

    # La voz, si se pide. Se monta ANTES de servir para no perderse
    # eventos del primer turno, y se importa aqui dentro a proposito: sin
    # --voz, arrancar el puente no debe cargar Whisper ni piper ni tocar
    # la tarjeta de sonido.
    voz = None
    # >>> POR QUE NO BASTA CON `voz is None` <<<
    # (2026-09-10.) "No hay voz" son DOS cosas: no la pediste, o la
    # pediste y no arranco. Colapsadas en una sola comprobacion, el
    # resumen del final le dice "usa --voz" a quien acaba de usarlo.
    fallo_de_voz: str | None = None
    if con_voz:
        from voz import bucle as mod_bucle
        from voz.bucle import Bucle
        from voz.resumen import LIMITE_HABLADO

        # La ventana de seguimiento es una constante del modulo porque es
        # un numero de diseno, no un parametro; se ajusta aqui para que el
        # panel de ajustes no prometa un cambio que no llega.
        mod_bucle.ESPERA_SEGUIMIENTO_S = float(
            valor_de("tiempos.seguimiento_s", mod_bucle.ESPERA_SEGUIMIENTO_S))
        # El MISMO registro que pinta la consola, no una cuenta propia:
        # dos analizadores del mismo flujo se separan, y el dia que la
        # pantalla y la voz discrepen no habria forma de saber cual miente.
        voz = Bucle(sesion, abrir_sesion=consola.asegurar_sesion,
                    producido=consola.producido,
                    anunciar_turno=consola.anuncia_turno,
                    # >>> EL MISMO OBJETO QUE LA CONSOLA, NO UNA COPIA <<<
                    # Es lo que hace que "apagate" signifique lo mismo
                    # dicho que escrito. Con dos juegos de atributos,
                    # enchufar uno y olvidar el otro no da ningun error:
                    # da el fallo del 09-05.
                    gestos=consola.gestos,
                    seguimiento=seguimiento, narrar=narrar,
                    limite_hablado=LIMITE_HABLADO if resumir else None)
        try:
            voz.preparar()
        except Exception as exc:  # noqa: BLE001
            # No se arranca "a medias y en silencio": o hay voz, o se
            # dice que no la hay. Un asistente que no oye y no lo avisa
            # es indistinguible de uno que te esta ignorando.
            #
            # >>> Y HASTA EL 2026-09-10 ESTO SOLO LO VEIA UN LOG <<<
            # Lo reporto el usuario al pasar la voz al español: el perfil
            # se quedo en `jarvis_en`, `voz/perfil.py` se nego a arrancar
            # -- que es lo CORRECTO -- y el arranque lo explico aqui con
            # todas las letras. Pero la carcasa corre con `pythonw`, o
            # sea que `escritorio/salida.py` se lleva estos `print` a un
            # archivo: la ventana no decia NADA, y un asistente que no
            # oye y no lo dice es indistinguible de uno que te ignora.
            # Mismo silencio que destapo `Consola.avisa` el 09-03, en el
            # sitio donde quedaba. A la PANTALLA va la primera linea,
            # que es la accionable; el detalle entero, al diario.
            fallo_de_voz = f"{type(exc).__name__}: {exc}"
            print(f"\nNO SE PUDO ENCENDER LA VOZ: {fallo_de_voz}")
            print("La consola sigue funcionando; la escucha, no.")
            consola.avisa(aviso_de_voz_caida(fallo_de_voz))
            voz = None
        else:
            consola.oyentes.append(voz.recibir)
            # Para que la pantalla pueda decir si te esta escuchando.
            consola.voz = voz

    consola.servir(abrir_navegador=not args.sin_navegador)
    if voz is not None:
        voz.arrancar()

    print(f"Consola en http://127.0.0.1:{args.puerto}/")
    print(f"Sesion acotada a {carpeta}")
    print(f"Suelo: {len(suelo.zonas)} zonas obligatorias, "
          f"{len(suelo.reglas)} reglas ({suelo.archivo})")
    print(f"Registro crudo en {registro}")
    print("La sesion de Claude Code se abre con la PRIMERA ORDEN, no ahora: "
          "hasta entonces no sale nada de esta maquina.")
    if voz is not None:
        print(f"Voz ENCENDIDA. Micro: {voz.micro}")
        print("Di 'hey jarvis' con la J INGLESA (\"jei YAR-vis\"): a la "
              "española no llega al umbral, esta medido.")
        print("Suena un aviso: cuando TERMINA, hablas. Mientras trabaja solo "
              "escucha 'para'. Si te pregunta algo, la escucha se abre sola.")
        print("Sigue escuchando tras cada respuesta; te callas y se calla."
              if voz.seguimiento else
              "Solo vuelve a escuchar si te pregunta algo.")
        print("Locuta la respuesta ENTERA"
              if voz.limite_hablado is None else
              "Locuta un resumen; el detalle, en la consola.")
    else:
        print(resumen_sin_voz(fallo_de_voz))
    if escalado.canal.disponible:
        print(f"Telegram ENCENDIDO: aviso a los {escalado.tras_minutos:.0f} min "
              "si no contestas y no estas delante (avisa, no autoriza).")
    else:
        print("Telegram apagado. Se configura en la consola.")
    print("Ctrl+C para salir.")

    # El escalado no tiene hilo propio: se le pregunta desde quien ocupe
    # el hilo principal. Ver `Montaje.latir`.
    montaje = Montaje(sesion=sesion, consola=consola, voz=voz,
                      escalado=escalado, carpeta=carpeta, puerto=args.puerto,
                      buzon=buzon)
    try:
        (esperar or _esperar_en_la_terminal)(montaje)
    except KeyboardInterrupt:
        print("\nCerrando.")
    finally:
        montaje.cerrar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
