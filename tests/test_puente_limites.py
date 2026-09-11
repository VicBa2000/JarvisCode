"""Los dos finales malos: sin cuota y sin servidor.

Contra capturas reales de `claude 2.1.239`:

  `permitida.jsonl`   trae un `rate_limit_event` que salio SOLO, a mitad
                      de sesion, con el semanal al 86 %.
  `sin_conexion.jsonl` es el CLI apuntado a una direccion muerta. No es
                      un mock: es el binario de verdad fallando de verdad,
                      generado ejecutando.

Rapidos: leen archivos, no llaman a nadie.
"""

from __future__ import annotations

from pathlib import Path

from puente.protocolo import Fin, Limite, Reintento, interpretar

TRAZAS = Path(__file__).resolve().parent.parent / "eval" / "trazas_claude_code"


def eventos_de(nombre: str) -> list:
    eventos = []
    for linea in (TRAZAS / nombre).read_text(encoding="utf-8").splitlines():
        eventos.extend(interpretar(linea))
    return eventos


def solo(eventos: list, clase: type) -> list:
    return [e for e in eventos if isinstance(e, clase)]


# --- La cuota --------------------------------------------------------------


def test_el_aviso_de_cuota_llega_solo_y_trae_su_reloj():
    """Nadie lo pidio: aparecio en mitad de una sesion normal."""
    limites = solo(eventos_de("permitida.jsonl"), Limite)
    assert len(limites) == 1
    limite = limites[0]
    assert limite.estado == "allowed_warning"
    assert limite.es_semanal
    assert limite.porcentaje == 86
    # Lo que hay que poder decir en voz alta: cuando vuelve.
    assert limite.reinicia_en and limite.reinicia_en > 1_700_000_000
    assert limite.umbral_superado == 0.75
    assert not limite.en_exceso


class TestLosDosRelojes:
    """>>> EL FALLO MUDO QUE TUVO LA CONSOLA ENSENANDO 0 % <<<

    Lo reporto el usuario el 2026-09-03: la cuota que ensenabamos no era
    la real, y ademas parecia venir siempre a 0, cosa que no era. El
    conteo sobre los 195 `rate_limit_event` de `logs/puente/` le dio la
    razon: **en 120 de ellos (61 %) el campo `utilization` de arriba ya
    no viene**, y los numeros de verdad se mudaron a `unifiedWindows`.
    `float(info.get("utilization") or 0.0)` no da error con la clave
    ausente: da un cero, que es un valor creible para una cuota.

    Las dos lineas de `cuota_dos_relojes.jsonl` estan COPIADAS de
    `logs/puente/` y son las dos formas que existen en disco:
    la nueva -- sin `utilization` arriba -- y la vieja, que lo trae y
    ademas ya traia las dos ventanas.
    """

    def test_la_forma_NUEVA_no_se_lee_como_un_cero(self):
        cruda = (TRAZAS / "cuota_dos_relojes.jsonl").read_text(
            encoding="utf-8").splitlines()[0]
        assert '"utilization"' not in cruda.split('"unifiedWindows"')[0], (
            "esta linea tiene que ser la forma SIN utilization arriba; si "
            "no, este test no prueba nada")
        nuevo = solo(eventos_de("cuota_dos_relojes.jsonl"), Limite)[0]
        assert nuevo.sesion is not None and nuevo.sesion.porcentaje == 30
        assert nuevo.semana is not None and nuevo.semana.porcentaje == 37
        # Y lo que la consola ensenaba: el reloj propio, que ya no es 0.
        assert nuevo.porcentaje == 30, "volvio el cero mudo"

    def test_las_dos_ventanas_vienen_en_EL_MISMO_evento(self):
        """Por eso la pantalla puede ensenar las dos siempre, en vez del
        reloj que trajera el ultimo aviso -- que no lo elige nadie."""
        for limite in solo(eventos_de("cuota_dos_relojes.jsonl"), Limite):
            assert limite.sesion is not None
            assert limite.semana is not None
            assert limite.sesion.reinicia_en != limite.semana.reinicia_en

    def test_las_DOS_ventanas_dicen_lo_GASTADO(self):
        """>>> Y EL 2026-09-04 ESTO ERA AL REVES EN LA SESION <<<

        Se ensenaba `queda` y el usuario se quedo sin cuota mirandolo:
        la barra marcaba un 3 % y se veia casi vacia, cuando lo que
        pasaba es que estaba al 97 % y se le agoto. Las dos cifras eran
        correctas; lo que no lo era es que una barra casi vacia se lee
        como "queda sitio" aunque encima ponga QUEDA.
        Ahora las dos ventanas contestan la misma pregunta y las dos
        barras se llenan, que es lo que pidio: cuanto porcentaje llevamos
        gastado, no cuanto queda.
        """
        limite = solo(eventos_de("cuota_dos_relojes.jsonl"), Limite)[0]
        assert limite.sesion.porcentaje == 30
        assert limite.semana.porcentaje == 37
        assert not hasattr(limite.sesion, "queda"), (
            "`queda` volvio, y no lo pinta nadie: es un calculo en el "
            "vacio, la forma de fallo que este arbol lleva persiguiendo")


class TestUnaVentanaQueYaSeREINICIONoTieneCifra:
    """El segundo sintoma del 2026-09-04, y lo reporto usandolo.

    >>> Al agotarse la sesion basta con esperar a que la ventana se
    reinicie para seguir trabajando, pero las cuotas de la pantalla no se
    actualizaban hasta reiniciar Jarvis entero. <<<

    `Sesion.limite` guarda el ULTIMO evento y nadie lo caducaba:
    `reinicia_en` solo servia para escribir "vuelve a las 02:10". Asi que
    una ventana agotada a las 21:00 y reiniciada a la 01:20 seguia
    diciendo 97 % a las 03:00 -- una cifra correcta de una ventana que ya
    no existe. Y el momento en que se lee es el peor: al agotarse la
    cuota se deja de trabajar, o sea que no llega ningun evento nuevo que
    la pise, y lo unico que la movia era reiniciar Jarvis.
    """

    def test_antes_de_su_hora_la_cifra_VALE(self):
        from puente.protocolo import Ventana
        v = Ventana(utilizacion=0.97, reinicia_en=1_000)
        assert v.caducada(ahora=999) is False

    def test_pasada_su_hora_la_cifra_ES_DE_OTRA_VENTANA(self):
        from puente.protocolo import Ventana
        v = Ventana(utilizacion=0.97, reinicia_en=1_000)
        assert v.caducada(ahora=1_001) is True

    def test_sin_hora_de_vuelta_la_respuesta_es_NO_SE_SABE(self):
        """>>> LA TERCERA SALIDA, Y AQUI NO SE PUEDE COLAPSAR <<<

        Sin `reinicia_en` no hay forma de saber si esa cifra sigue viva.
        Decir `False` ("esta al dia") es el error por defecto: dejaria
        una cifra vieja en pantalla con aplomo, que es justo el sintoma.
        Decir `True` la borraria cada vez que el evento no traiga la
        hora. Se contesta `None` y lo decide quien pinta.
        """
        from puente.protocolo import Ventana
        assert Ventana(utilizacion=0.97).caducada(ahora=9_999) is None

    def test_las_ventanas_REALES_de_la_traza_traen_su_hora(self):
        """Sin esto lo de arriba seria una funcion que nunca se dispara:
        si los eventos de verdad no trajeran `resetsAt`, la respuesta
        seria siempre `None` y la cuota se quedaria clavada igual."""
        limite = solo(eventos_de("cuota_dos_relojes.jsonl"), Limite)[0]
        assert limite.sesion.caducada(ahora=0) is False
        assert limite.semana.caducada(ahora=0) is False
        assert limite.sesion.caducada(ahora=4_000_000_000) is True
        assert limite.semana.caducada(ahora=4_000_000_000) is True

    def test_la_forma_VIEJA_sigue_leyendose_igual(self):
        """La que trae `utilization` arriba. Sigue en disco, y una sesion
        que la reciba tiene que dar el mismo numero que daba antes."""
        viejo = solo(eventos_de("cuota_dos_relojes.jsonl"), Limite)[1]
        assert viejo.porcentaje == 93
        assert viejo.sesion.porcentaje == 93
        assert viejo.semana.porcentaje == 15

    def test_una_ventana_QUE_NO_VIENE_es_None_y_no_cero(self):
        """>>> LA TERCERA SALIDA, Y ES LO QUE FALLO <<< Un cero se lee como "no
        ha gastado nada" y un `None` no se puede leer como nada: obliga a
        la pantalla a escribir "?"."""
        crudo = ('{"type":"rate_limit_event","rate_limit_info":'
                 '{"status":"allowed","rateLimitType":"five_hour"}}')
        limite = interpretar(crudo)[0]
        assert isinstance(limite, Limite)
        assert limite.sesion is None
        assert limite.semana is None

    def test_una_ventana_con_basura_dentro_tampoco_inventa_un_numero(self):
        """Y sobre todo no LEVANTA: esto se interpreta en el hilo lector
        de la sesion, que es un hilo daemon y muere callado (paso una
        tarde entera el 2026-09-02)."""
        crudo = ('{"type":"rate_limit_event","rate_limit_info":'
                 '{"status":"allowed","rateLimitType":"five_hour",'
                 '"unifiedWindows":{"five_hour":{"utilization":"mucho"},'
                 '"seven_day":[]}}}')
        limite = interpretar(crudo)[0]
        assert limite.sesion is None
        assert limite.semana is None


def test_un_aviso_no_es_un_agotamiento():
    """`allowed_warning` deja seguir. Confundirlo seria apagarse de mas."""
    limite = solo(eventos_de("permitida.jsonl"), Limite)[0]
    assert not limite.agotado


def test_cualquier_estado_que_no_permita_cuenta_como_agotado():
    """La inferencia declarada en el docstring de `Limite`.

    NO ESTA MEDIDA: forzar un agotamiento real gasta la cuota del
    usuario. Se inclina a avisar de mas, que es el lado barato del
    error, y `estado` se guarda crudo para poder corregir esta linea el
    dia que un log ensene el valor de verdad.
    """
    crudo = ('{"type":"rate_limit_event","rate_limit_info":'
             '{"status":"rejected","rateLimitType":"seven_day",'
             '"utilization":1.0,"resetsAt":1787619600}}')
    limite = interpretar(crudo)[0]
    assert isinstance(limite, Limite)
    assert limite.agotado
    assert limite.porcentaje == 100


# --- El servidor -----------------------------------------------------------


def test_sin_servidor_la_sesion_se_calla_casi_tres_minutos():
    """El hallazgo entero de esta tanda.

    Con el CLI apuntado a una direccion muerta no hay error inmediato, no
    hay salida y no hay `result`: emite `init` y enmudece mientras
    reintenta. Lo unico que lo delata durante todo ese rato son los
    `api_retry`. Un puente que espere un mensaje de error se queda
    callado delante del usuario casi tres minutos.
    """
    eventos = eventos_de("sin_conexion.jsonl")
    assert solo(eventos, Reintento), "lo unico que lo delata a tiempo"
    fin = solo(eventos, Fin)[0]
    assert fin.duracion_ms > 120_000, f"tardo {fin.duracion_ms} ms en rendirse"


def test_el_subtipo_dice_success_sobre_un_fallo_total():
    """LA TRAMPA. Medida, no supuesta.

    Si el puente leyera `subtipo == "success"` daria por buena una
    respuesta que no existe, y el asistente le diria al usuario que todo
    fue bien cuando no llego a hablar con nadie.
    """
    fin = solo(eventos_de("sin_conexion.jsonl"), Fin)[0]
    assert fin.subtipo == "success"      # <- lo que dice
    assert fin.es_error                  # <- lo que pasa
    assert fin.razon_terminal == "api_error"
    assert fin.fue_mal
    assert fin.sin_servidor
    assert "Connection refused" in fin.texto


def test_un_turno_bueno_no_se_confunde_con_uno_malo():
    """El control: la otra rama, en la misma tanda."""
    fin = solo(eventos_de("permitida.jsonl"), Fin)[0]
    assert not fin.fue_mal
    assert not fin.sin_servidor
    assert fin.razon_terminal == "completed"


def test_los_reintentos_dicen_por_donde_van_y_cuanto_falta():
    reintentos = solo(eventos_de("sin_conexion.jsonl"), Reintento)
    assert [r.intento for r in reintentos] == list(range(1, 11))
    assert all(r.intentos_maximos == 10 for r in reintentos)
    assert not reintentos[0].es_el_ultimo
    assert reintentos[-1].es_el_ultimo


def test_el_silencio_antes_de_rendirse_es_de_minutos_no_de_segundos():
    """La cifra que obliga a avisar en el PRIMER reintento.

    Si el puente esperase a que se agoten los intentos para decir algo,
    el usuario tendria tres minutos de nada despues de hablar.
    """
    reintentos = solo(eventos_de("sin_conexion.jsonl"), Reintento)
    total_s = sum(r.espera_s for r in reintentos)
    assert total_s > 120, f"medido {total_s:.0f} s"
    # Y el primero llega enseguida, que es lo que lo hace util.
    assert reintentos[0].espera_s < 2.0


# --- Cuando la ventana se pasa del 100 % ----------------------------------
# >>> EL 107 NO ES NUESTRO, Y NO SE RECORTA <<< Lo reporto el usuario el
# 2026-09-05: la ventana llego al 100 %, espero a que volviera, hablo de
# nuevo y entonces subio al 107 %. La traza es la de esa ventana, copiada
# literal de `logs/puente/`, con los tres eventos que hacen
# falta para verlo: el 0.94 de antes, el 1.07 del rechazo y el primero
# de despues del reinicio -- sin el primero no se ve el salto y sin el
# tercero no se ve que la ventana SI se reinicia sola.


def test_la_cuota_puede_pasar_del_cien_y_se_dice_entera():
    """Recortar la cifra a 100 esconderia que el servidor dice que te
    pasaste, y eso es un dato, no un artefacto: medido sobre los 295
    saltos reales de la ventana de 5 h, un solo turno gasta hasta el
    21 %, asi que desde un 0,94 se aterriza por encima del 100 sin que
    nadie haya contado nada dos veces.
    """
    limites = solo(eventos_de("cuota_pasada_de_cien.jsonl"), Limite)
    pasado = [l for l in limites if l.sesion and l.sesion.porcentaje > 100]
    assert len(pasado) == 1
    assert pasado[0].sesion.porcentaje == 107
    assert pasado[0].estado == "rejected"


def test_pasarse_del_cien_no_es_estar_en_exceso():
    """`isUsingOverage` es otra cosa y no se confunden.

    El evento dice a la vez que se paso del 100 % y que NO esta usando
    exceso (`overageDisabledReason: org_level_disabled`), o sea: no habia
    bolsa de exceso donde meter lo que sobro, y por eso se RECHAZO. Leer
    el 107 como "esta tirando de exceso" seria justo al reves.
    """
    limites = solo(eventos_de("cuota_pasada_de_cien.jsonl"), Limite)
    pasado = [l for l in limites if l.sesion and l.sesion.porcentaje > 100][0]
    assert pasado.en_exceso is False


def test_la_ventana_se_reinicia_sola_despues_del_rechazo():
    """El tercer evento de la traza, y es el que contesta la pregunta 2.

    Lo que se recuerda es "volvio y SUBIO a 107". Lo que hay en disco es
    que el 1.07 llega CON el rechazo y que el evento siguiente ya trae la
    ventana a cero y su `resetsAt` cinco horas mas alla. O sea que la
    cifra no sigue creciendo pasado el reinicio.
    """
    limites = solo(eventos_de("cuota_pasada_de_cien.jsonl"), Limite)
    assert [l.sesion.porcentaje for l in limites] == [94, 107, 0]
    antes = limites[1].sesion.reinicia_en
    despues = limites[2].sesion.reinicia_en
    assert despues > antes, "la ventana de despues no es la misma"
