"""Los ajustes, en su propia pagina y escritos para la primera vez.

DE DONDE SALE (2026-08-26, usandolo): el usuario pidio que los ajustes
abrieran en una PESTANA aparte y no en un desplegable sobre la pantalla
principal, y que el panel entero fuera bastante mas facil de entender --
lo veia complejo --, con el encuadre que decide todo lo demas: escribirlo
para la primera vez que alguien descarga, instala y abre Jarvis.

LO QUE SE PRUEBA AQUI, y son las tres cosas que se rompen sin ruido:

  1. que el desplegable viejo NO haya quedado a medias en la consola.
     Un `getElementById` que devuelve null revienta el script ENTERO de
     esa pagina, y la consola se quedaria en blanco -- sin error visible,
     porque el error se queda en la consola del navegador.
  2. que la pagina de ajustes se sirva CON su ficha. Sin ella, todas sus
     peticiones darian 403 y el panel saldria vacio.
  3. que guardar Telegram con el token en blanco NO borre el que hay. Es
     lo que pidio el usuario -- "obio que a mi no me borres ni me
     desconfigures nada" -- y ademas es lo que la propia pagina hace en
     cada guardado, porque nunca rellena ese campo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONSOLA = PROJECT_ROOT / "puente" / "consola.html"
AJUSTES = PROJECT_ROOT / "puente" / "ajustes.html"


@pytest.fixture(scope="module")
def consola() -> str:
    return CONSOLA.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pagina() -> str:
    return AJUSTES.read_text(encoding="utf-8")


# --- 1. EL DESPLEGABLE VIEJO SE FUE ENTERO ------------------------------


def test_la_consola_ya_no_lleva_el_panel_dentro(consola: str) -> None:
    assert "panelAjustes" not in consola
    assert "cargaAjustes" not in consola
    assert "listaAjustes" not in consola


def test_no_quedan_referencias_a_nada_que_ya_no_exista(consola: str) -> None:
    """>>> EL FALLO QUE DEJA LA PAGINA EN BLANCO <<<

    `document.getElementById("x").addEventListener(...)` sobre un id que
    ya no esta lanza y **corta el script entero**: la consola se quedaria
    muerta y el error solo se veria abriendo las herramientas del
    navegador. Se comprueba que cada id que el script busca existe en el
    marcado.
    """
    import re

    buscados = set(re.findall(r'getElementById\("([^"]+)"\)', consola))
    presentes = set(re.findall(r'id="([^"]+)"', consola))
    huerfanos = sorted(buscados - presentes)
    assert not huerfanos, f"el script busca ids que no existen: {huerfanos}"


def test_los_ajustes_son_una_PESTAÑA_y_no_otra_ventana(consola: str) -> None:
    """>>> LA CORRECCION DEL USUARIO, EN UNA LINEA <<<

    La primera version abria una ventana aparte. Lo que habia pedido era
    una pestana dentro del mismo aplicativo, en la misma ventana de
    Jarvis. Una ventana, dos vistas: es lo que hace una aplicacion.
    """
    assert 'id="pestanaAjustes"' in consola
    assert 'id="pestanaConsola"' in consola
    assert "window.open" not in consola, "todavia abre otra ventana"


def test_la_vista_de_ajustes_se_monta_al_entrar_y_no_antes(consola: str) -> None:
    """Montar una pagina entera que quiza nadie abra es tiempo de arranque
    regalado, y este proceso vive en el inicio de Windows."""
    assert "if (!vistaAjustes.firstChild)" in consola


def test_al_cambiar_de_vista_se_esconde_TODO_lo_de_la_consola(
    consola: str,
) -> None:
    """Una tarjeta de permiso flotando sobre los ajustes seria una puerta
    que parece de esa pantalla y no lo es."""
    for cual in ("nucleo", "pendientes", "cuerpo"):
        assert f'getElementById("{cual}")' in consola, cual


def test_las_carpetas_protegidas_se_MUDARON_a_ajustes(consola: str,
                                                      pagina: str) -> None:
    """>>> LO MOVIO EL USUARIO, Y TENIA RAZON <<<

    El apartado del PERIMETRO estaba en la pantalla principal y el
    usuario lo mando a ajustes. Es configuracion, no vigilancia: la
    pantalla principal es para mirar que hace Jarvis AHORA.
    """
    assert "panelZonas" not in consola, "quedo el panel viejo en la consola"
    assert "cargaZonas" not in consola, "quedo su codigo en la consola"
    assert 'id="seccionZonas"' in pagina


def test_el_indicador_de_la_cabecera_lleva_a_los_ajustes(consola: str) -> None:
    """Es donde el usuario espera encontrarlas despues de habituarse a
    que estuvieran ahi. Dejarlo muerto seria un boton que no hace nada."""
    assert 'getElementById("suelo")' in consola
    assert "indicadorSuelo.addEventListener" in consola


def test_la_bandeja_tambien_puede_traerte_a_los_ajustes(consola: str) -> None:
    """El menu del icono llama a esto con `evaluate_js`. Sin el, la
    entrada "Ajustes" de la bandeja abriria la ventana y te dejaria en la
    consola sin decir por que."""
    assert "window.jarvisVerAjustes" in consola


# --- 2. LA PAGINA NUEVA -------------------------------------------------


def test_la_pagina_de_ajustes_pide_su_ficha(pagina: str) -> None:
    """Sin ficha, cada peticion suya daria 403 y el panel saldria vacio
    sin decir por que."""
    assert '__FICHA__' in pagina
    assert "X-Jarvis-Ficha" in pagina


def test_se_sirve_desde_el_servidor_y_no_es_la_consola() -> None:
    from puente.consola import PAGINA, PAGINA_AJUSTES

    assert PAGINA_AJUSTES.is_file()
    assert PAGINA_AJUSTES != PAGINA


def test_lo_avanzado_nace_PLEGADO(pagina: str) -> None:
    """Trece cosas a la vez es lo que hacia que se sintiera complejo. Lo
    que hace falta para empezar cabe en dos secciones; el resto se pide."""
    assert "MOSTRAR AJUSTES AVANZADOS" in pagina
    assert "caja.hidden = true" in pagina


def test_el_porque_de_cada_numero_va_plegado(pagina: str) -> None:
    """La medicion detras de cada valor salva a quien la busca y abrume a
    quien acaba de instalar el programa. Va detras de un "¿por que?"."""
    assert "¿POR QUE?" in pagina
    assert "details" in pagina


def test_la_pagina_pinta_con_textContent_y_nunca_con_innerHTML(pagina: str) -> None:
    """Aqui entran nombres de dispositivos de audio, que los escribe el
    fabricante del aparato: contenido observado como cualquier otro."""
    assert "innerHTML" not in pagina


def test_telegram_tiene_por_fin_donde_poner_el_token(pagina: str) -> None:
    """Era lo que faltaba: el backend estaba entero desde el 25 y la UI
    solo tenia un LED que decia SIN PONER."""
    assert 'id="tgToken"' in pagina
    assert 'id="tgChat"' in pagina
    assert 'type="password"' in pagina, "el token no se enseña"


def test_la_pagina_dice_que_telegram_NO_autoriza(pagina: str) -> None:
    """No es un detalle de esta pantalla: es la decision de fondo, y quien
    configure esto tiene que verlo aqui y no en un ADR."""
    texto = pagina.lower()
    assert "solo avisa" in texto and "no obedece" in texto


def test_el_campo_del_token_nunca_se_rellena(pagina: str) -> None:
    """No lo tenemos: el servidor solo manda sus cuatro ultimos
    caracteres. Rellenarlo con algo seria enseñar una credencial falsa."""
    assert 'tgToken.value = "";' in pagina


# --- 3. LA CONFIGURACION DEL USUARIO NO SE PIERDE -----------------------


def test_guardar_sin_token_conserva_el_que_habia(tmp_path, monkeypatch) -> None:
    """>>> LO QUE EL USUARIO PIDIO EXPRESAMENTE <<<

    La pagina NUNCA rellena el campo del token, asi que manda vacio en
    CADA guardado -- cambiar el chat, o solo apagar los avisos, pasa por
    aqui. Si un vacio borrase, tocar cualquier cosa de Telegram te
    dejaria sin canal de avisos y no te enterarias hasta el dia que
    hiciera falta.
    """
    from canales import telegram as canal

    archivo = tmp_path / "telegram.yaml"
    monkeypatch.setattr(canal, "ARCHIVO", archivo, raising=False)
    monkeypatch.setattr(canal, "ruta", lambda *a, **k: archivo, raising=False)

    canal.guardar(canal.Ajustes(activo=True, token="SECRETO:123",
                                chat_id="42"))
    assert canal.leer().token == "SECRETO:123"

    # Lo que hace `Consola.guardar_telegram` con un token vacio.
    actuales = canal.leer()
    token = "".strip() or actuales.token
    canal.guardar(canal.Ajustes(activo=False, token=token, chat_id="99"))

    despues = canal.leer()
    assert despues.token == "SECRETO:123", "se borro el token al guardar"
    assert despues.chat_id == "99"
    assert despues.activo is False


def test_el_token_no_sale_nunca_entero_a_la_UI() -> None:
    from canales.telegram import Ajustes

    limpio = Ajustes(activo=True, token="SECRETO:1234", chat_id="1").sin_secretos()
    assert "SECRETO" not in str(limpio)
    assert limpio["token_acaba_en"] == "1234"
    assert limpio["hay_token"] is True


# --- 4. EL ORDEN ES EL DE QUIEN ACABA DE INSTALAR -----------------------


def test_las_secciones_van_en_el_orden_de_las_preguntas() -> None:
    """No por subsistema -- "voz", "stt", "tiempos" --, que es el mapa de
    nuestro codigo. Por lo que uno quiere hacer, y en ese orden."""
    from nucleo.ajustes import por_grupos

    claves = [g["clave"] for g in por_grupos()]
    # `pantalla` va delante de `empezar` desde el 2026-08-28, y rompe la
    # regla a proposito: el selector de idioma es el unico ajuste que
    # tiene que encontrar alguien que NO PUEDE LEER la pagina. Arriba se
    # localiza sin leer nada; entre lo avanzado haria falta entender el
    # idioma que justamente no se entiende.
    assert claves == ["pantalla", "empezar", "oir", "avanzado"]


def test_lo_de_empezar_cabe_en_la_cabeza() -> None:
    """Si "para empezar" tuviera ocho cosas, no seria un comienzo."""
    from nucleo.ajustes import por_grupos

    empezar = next(g for g in por_grupos() if g["clave"] == "empezar")
    assert len(empezar["ajustes"]) <= 3


def test_las_etiquetas_no_hablan_en_jerga() -> None:
    """"Umbral del wake word" es exacto y no significa nada la primera
    vez. El nombre tecnico sigue en la clave y en el "¿por que?"."""
    from nucleo.ajustes import catalogo

    jerga = ("umbral", "wake word", "ancla", "vad", "stt", "endpoint")
    malas = [a.etiqueta for a in catalogo()
             if any(j in a.etiqueta.lower() for j in jerga)]
    assert not malas, f"etiquetas en jerga: {malas}"


# --- 5. EL PANEL DE MCP (JC-0015) ---------------------------------------


def test_el_panel_dice_que_es_una_lista_BLANCA(pagina: str) -> None:
    """Quien lo lea tiene que entender por que su servidor no funciona
    ANTES de pelearse con el: lo que no este, no pasa."""
    texto = pagina.lower()
    assert "lista blanca" in texto
    assert "no se ejecuta" in texto or "no pasa" in texto


def test_se_autoriza_al_SERVIDOR_y_la_pagina_lo_dice(pagina: str) -> None:
    """Un servidor decide solo que herramientas ofrece y puede cambiarlas.
    Dejar creer que se autoriza herramienta a herramienta seria vender un
    control que no existe."""
    assert "el servidor entero" in pagina


def test_los_vistos_hacen_la_lista_ABIERTA(pagina: str) -> None:
    """>>> LO QUE SEPARA UNA LISTA BLANCA DE UN MURO <<<

    Denegar sin decir QUE se denego obliga a leer el registro para
    enterarse. Con los vistos, enterarse y autorizar es un clic.
    """
    assert 'id="vistosMcp"' in pagina
    assert 'id="filaVistos"' in pagina


def test_hay_donde_anadir_uno_a_mano(pagina: str) -> None:
    assert 'id="mcpNuevo"' in pagina
    assert 'id="mcpAnadir"' in pagina


def test_el_panel_pinta_lo_que_hace_cada_politica(pagina: str) -> None:
    """"confirmar" no significa nada; "te pregunta cada vez" si."""
    assert "te pregunta cada vez" in pagina
    assert "sus herramientas pasan solas" in pagina


# --- 6. LOS INTERRUPTORES, QUE NO ENCENDIAN NADA ------------------------


def test_la_pista_del_interruptor_NO_se_come_los_clics(pagina: str) -> None:
    """>>> EL FALLO MUDO QUE REPORTO EL USUARIO <<<

    Ningun interruptor de la pagina se dejaba activar ni desactivar:
    se pulsaban y no pasaba absolutamente nada.

    Y no era JavaScript: `.pista` va DESPUES del input en el marcado y
    tambien es `position:absolute; inset:0`, asi que se pintaba encima y
    se comia todos los clics. El checkbox quedaba debajo, invisible, sin
    enterarse. Se ve bien, no da error, y no hace nada -- que es la forma
    de fallo que este proyecto persigue desde el primer dia.

    Se comprueban LAS DOS defensas: cualquiera de ellas sola basta
    mientras nadie toque la otra, y ese "mientras" es justo lo que un
    test tiene que cubrir.
    """
    import re

    bloque = re.search(r"\.palanca input \{[^}]*\}", pagina)
    assert bloque, "no se encontro el estilo del interruptor"
    assert "z-index" in bloque.group(0), "el input no esta por encima"

    pista = re.search(r"\.palanca \.pista \{[^}]*\}", pagina)
    assert pista, "no se encontro el estilo de la pista"
    assert "pointer-events: none" in pista.group(0), "la pista sigue tapando"


def test_todos_los_interruptores_usan_la_misma_palanca(pagina: str) -> None:
    """Si alguno se pintara a mano, el arreglo de arriba no le llegaria y
    volveriamos a tener uno que no enciende."""
    for cual in ("tgActivo", "tgResponde", "proyPorVoz"):
        assert f'id="{cual}"' in pagina, cual
    # Y los del catalogo se construyen con la misma funcion.
    assert 'caja.className = "palanca"' in pagina


# --- 7. EL PERIMETRO, EN CASTELLANO -------------------------------------


def test_el_perimetro_NO_habla_en_jerga_nuestra(pagina: str) -> None:
    """El usuario no entendia casi nada de esa parte de la pagina. Lo que
    fallaba no era el sitio sino el vocabulario: decia "PERIMETRO",
    "SUELO FIJO" y "eje", que son los nombres de NUESTRO codigo."""
    trozo = pagina[pagina.index('id="seccionZonas"'):]
    trozo = trozo[:trozo.index("</section>")]
    for jerga in ("SUELO FIJO", "PERIMETRO", "eje"):
        assert jerga not in trozo, f"sigue diciendo '{jerga}'"


def test_dice_QUE_PUEDE_HACER_en_cada_carpeta(pagina: str) -> None:
    """"eje: sistema" no significa nada. "Puede mirar, no cambiar" si."""
    assert "PUEDE MIRAR, NO CAMBIAR" in pagina
    assert "NI MIRAR" in pagina


def test_explica_por_que_una_privada_es_distinta(pagina: str) -> None:
    """El riesgo de una zona privada no es romper nada: es que el
    contenido VIAJE. Sin eso, "ni mirar" parece una exageracion."""
    assert "viaje" in pagina
    assert "manda a Claude" in pagina


def test_el_coste_va_antes_de_marcar_nada(pagina: str) -> None:
    """Una casilla sin su coste es una casilla que se marca sin
    entenderla. Es la misma regla que ya tenia el panel viejo."""
    assert "Si la bloqueas: " in pagina


def test_las_fijas_se_VEN_aunque_no_se_toquen(pagina: str) -> None:
    """Una proteccion que no se puede mirar se parece demasiado a una que
    no existe."""
    assert 'id="detalleFijas"' in pagina
    assert "derecho a ver de que se te protege" in pagina


def test_al_guardar_se_dice_LO_MEDIDO_y_no_un_listo_generico(pagina: str) -> None:
    """Medido el 2026-08-24: un cambio no se aplica del todo hasta
    reiniciar, EN LAS DOS DIRECCIONES -- la puerta ya deniega lo escrito,
    pero LEER no pasa por esa comprobacion."""
    assert "hace_falta_reabrir" in pagina
    assert "LEER no pasa por" in pagina
