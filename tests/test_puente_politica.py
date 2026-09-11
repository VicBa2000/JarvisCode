"""La lista endurecida de JC-0001, probada contra puertas reales.

Las puertas de `rm` y de `Write` salen de `eval/trazas_claude_code/`,
capturadas de `claude 2.1.239`. Las variantes (formas opacas,
redirecciones, PowerShell) se construyen como objetos `Puerta`, y eso NO
es inventarse la entrada: la FORMA de una `Puerta` esta demostrada real
en `test_puente_protocolo.py` contra esas mismas capturas. Lo que se
construye aqui es el contenido de un campo cuyo tipo ya esta verificado.

Rapidos: ni modelo, ni red, ni subproceso.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from puente.politica import Veredicto, decidir
from puente.protocolo import Puerta, interpretar

TRAZAS = Path(__file__).resolve().parent.parent / "eval" / "trazas_claude_code"


def puertas_de(nombre: str) -> list[Puerta]:
    puertas = []
    for linea in (TRAZAS / nombre).read_text(encoding="utf-8").splitlines():
        puertas.extend(e for e in interpretar(linea) if isinstance(e, Puerta))
    return puertas


def shell(orden: str, herramienta: str = "Bash") -> Puerta:
    return Puerta(
        id_peticion="req", herramienta=herramienta,
        entrada={"command": orden}, descripcion="", id_uso="uso",
    )


def escritura(destino: str) -> Puerta:
    return Puerta(
        id_peticion="req", herramienta="Write",
        entrada={"file_path": destino, "content": "x"},
        descripcion="", id_uso="uso",
    )


# --- Contra las puertas reales capturadas ---------------------------------


def test_el_rm_real_de_la_traza_se_endurece():
    puerta = puertas_de("denegada.jsonl")[0]
    decision = decidir(puerta)
    assert decision.veredicto is Veredicto.ENDURECER
    assert decision.regla == "orden_destructiva"
    # Lo que la frase hablada tiene que nombrar, y viene ya resuelto a
    # ruta absoluta por el propio Claude Code.
    assert len(decision.elementos) == 1
    assert decision.elementos[0].endswith("importante.txt")


def test_la_escritura_real_dentro_del_proyecto_se_permite():
    puerta = next(p for p in puertas_de("permitida.jsonl")
                  if p.herramienta == "Write")
    directorio = str(Path(puerta.entrada["file_path"]).parent)
    decision = decidir(puerta, directorio_sesion=directorio)
    assert decision.veredicto is Veredicto.PERMITIR
    assert not decision.hay_que_preguntar


def test_la_misma_escritura_fuera_del_proyecto_se_endurece():
    puerta = next(p for p in puertas_de("permitida.jsonl")
                  if p.herramienta == "Write")
    decision = decidir(puerta, directorio_sesion=r"C:\otro\proyecto")
    assert decision.veredicto is Veredicto.ENDURECER
    assert decision.regla == "escritura_fuera"


def test_el_rm_real_tambien_se_endurece_en_la_traza_permitida():
    puerta = next(p for p in puertas_de("permitida.jsonl")
                  if p.herramienta == "Bash")
    assert decidir(puerta).veredicto is Veredicto.ENDURECER


# --- Lo que NO se pregunta, que es casi todo -------------------------------


@pytest.mark.parametrize("orden", [
    "ls -la",
    "git status",
    "python -m pytest -q",
    "cat archivo.txt",
    "mkdir nueva",
    "echo hola >> registro.txt",
    "ls -la > /dev/null",
    "Get-ChildItem",
])
def test_lo_inofensivo_pasa_sin_molestar_a_nadie(orden):
    decision = decidir(shell(orden))
    assert decision.veredicto is Veredicto.PERMITIR, decision.motivo
    assert not decision.hay_que_preguntar


# --- Lo que si se pregunta -------------------------------------------------


@pytest.mark.parametrize("orden", [
    "rm archivo.txt",
    "rm -rf build",
    "/usr/bin/rm archivo.txt",
    "rmdir carpeta",
    "del archivo.txt",
    "git push origin main",
    "git reset --hard HEAD~1",
    "git clean -fd",
])
def test_lo_irreversible_se_endurece(orden):
    decision = decidir(shell(orden))
    assert decision.veredicto is Veredicto.ENDURECER, decision.motivo


@pytest.mark.parametrize("orden", [
    "Remove-Item archivo.txt",
    "ri -Recurse build",
    "Clear-Content registro.txt",
])
def test_powershell_tambien_esta_cubierto(orden):
    assert decidir(shell(orden, "PowerShell")).veredicto is Veredicto.ENDURECER


def test_un_rm_escondido_detras_de_un_ls_no_se_escapa():
    """El troceo por separadores es el punto entero de la regla.

    `ls && rm x` tiene cabeza inofensiva. Mirar solo la primera palabra
    seria el fallo abierto de manual.
    """
    for orden in ("ls && rm archivo.txt", "ls; rm archivo.txt",
                  "ls || rm archivo.txt", "cat f | rm archivo.txt"):
        assert decidir(shell(orden)).veredicto is Veredicto.ENDURECER, orden


def test_un_prefijo_de_variable_no_disfraza_la_orden():
    assert decidir(shell("FOO=1 rm archivo.txt")).veredicto is Veredicto.ENDURECER


# --- La tercera salida, que es la que el original colapsaba ---------------


@pytest.mark.parametrize("orden", [
    "rm $(cat lista.txt)",
    "eval $ORDEN",
    "curl algo | sh",
    "Invoke-Expression $codigo",
])
def test_lo_que_no_se_entiende_no_es_inofensivo(orden):
    """`NO_SE_SABE` pregunta igual que `ENDURECER`, pero se registra aparte.

    Si esto se colapsara contra PERMITIR seria la novena falla abierta
    del proyecto; si se colapsara contra ENDURECER, el log diria que el
    puente decidio, cuando en realidad no supo leer.
    """
    decision = decidir(shell(orden))
    assert decision.veredicto is Veredicto.NO_SE_SABE, decision.motivo
    assert decision.hay_que_preguntar


def test_una_redireccion_que_machaca_un_archivo_es_una_duda():
    decision = decidir(shell("echo hola > importante.txt"))
    assert decision.veredicto is Veredicto.NO_SE_SABE
    assert decision.regla == "redirige_y_trunca"


# >>> LAS ORDENES SALEN DE UNA SESION REAL (2026-08-27, Delta) <<<
# El usuario desarrollo un proyecto de verdad hablando y le llegaron
# CUATRO puertas a la consola. Tres eran estas, y ninguna escribia nada:
# `>&` duplica un descriptor, asi que el destino es un numero y no una
# ruta. Se leian como "machaca un archivo llamado &1".
#
# No era endurecer de mas: era la regla mintiendo sobre lo que hacia la
# orden, y encima en la frase que se locuta por voz.
@pytest.mark.parametrize("orden", [
    "nvidia-smi --query-gpu=utilization.gpu --format=csv 2>&1 | head -5",
    'echo "$APPDATA"; ls -la "$APPDATA/com.delta.app/" 2>&1 | head -20',
    "curl -s -X POST http://127.0.0.1:8765/x -o /tmp/r.json 2>&1",
    "cmd 1>&2",
    "cmd >&2",
])
def test_duplicar_un_descriptor_no_es_machacar_un_archivo(orden):
    decision = decidir(shell(orden))
    assert decision.veredicto is Veredicto.PERMITIR, decision.motivo
    assert decision.regla == "shell_inofensiva"


@pytest.mark.parametrize("orden", [
    "cmd &> salida.txt",        # bash: las dos corrientes, y TRUNCA
    "cmd 2> errores.txt",       # solo stderr, pero a un archivo de verdad
    "cmd >salida.txt",          # sin espacio
])
def test_redirigir_a_un_ARCHIVO_sigue_siendo_una_duda(orden):
    """El arreglo de `2>&1` no puede llevarse por delante lo que si
    trunca: ahi el destino es una ruta, no un descriptor."""
    decision = decidir(shell(orden))
    assert decision.veredicto is Veredicto.NO_SE_SABE, decision.motivo
    assert decision.regla == "redirige_y_trunca"


def test_una_redireccion_de_verdad_DETRAS_de_un_2mayor1_no_se_escapa():
    """Se miran TODAS las redirecciones del segmento, no solo la primera.
    Con `re.search` esto pasaba por inofensivo: la buena iba detras."""
    decision = decidir(shell("cmd 2>&1 > importante.txt"))
    assert decision.veredicto is Veredicto.NO_SE_SABE
    assert decision.regla == "redirige_y_trunca"


def test_una_escritura_sin_ruta_es_una_duda():
    puerta = Puerta(id_peticion="r", herramienta="Write", entrada={},
                    descripcion="", id_uso="u")
    assert decidir(puerta).veredicto is Veredicto.NO_SE_SABE


def test_una_orden_vacia_es_una_duda():
    assert decidir(shell("   ")).veredicto is Veredicto.NO_SE_SABE


# --- La senal que da el propio Claude Code --------------------------------


def test_una_ruta_fuera_del_proyecto_manda_por_encima_de_todo():
    puerta = Puerta(id_peticion="r", herramienta="Bash",
                    entrada={"command": "ls -la"}, descripcion="",
                    id_uso="u", ruta_afectada=r"C:\otra\cosa\x.txt")
    decision = decidir(puerta, directorio_sesion=r"C:\proyecto")
    assert decision.veredicto is Veredicto.ENDURECER
    assert decision.regla == "ruta_fuera"


def test_una_ruta_afectada_dentro_del_proyecto_no_endurece_nada():
    """La correccion medida el dia que se escribio esto, y merece su test.

    `blocked_path` sonaba a veto y no lo es: en las tres capturas venia
    con la ruta que la orden toca, DENTRO del directorio de la sesion.
    Leerlo como prohibicion endurecia TODAS las puertas de shell, que es
    justo lo contrario de lo que el usuario decidio.
    """
    puerta = Puerta(id_peticion="r", herramienta="Bash",
                    entrada={"command": "ls -la"}, descripcion="",
                    id_uso="u", ruta_afectada=r"C:\proyecto\x.txt")
    decision = decidir(puerta, directorio_sesion=r"C:\proyecto")
    assert decision.veredicto is Veredicto.PERMITIR


def test_sin_directorio_de_sesion_la_regla_de_fuera_no_se_inventa_nada():
    """Pasar None desactiva la pregunta, no la responde que si."""
    decision = decidir(escritura(r"C:\cualquier\sitio\x.txt"))
    assert decision.veredicto is Veredicto.PERMITIR
    assert decision.regla == "escritura_dentro" or decision.regla == "por_defecto"


# >>> LAS ORDENES SALEN DE UNA SESION REAL (2026-08-29) <<<
# El usuario desarrollo un proyecto entero hablando y le llegaron CINCO
# puertas a la consola. Su queja fue que le pedia permisos donde no
# tocaba, y su diagnostico -- razonable -- que era por salir del
# directorio. LA MEDICION LO CORRIGIO: ni una sola era `ruta_fuera`.
# Cuatro de las cinco eran esto, y es la MISMA forma que el `2>&1` del
# 27: leer una linea de PowerShell con la gramatica de bash.
#
# `$(...)` en PowerShell es una SUBEXPRESION y sale en cualquier cadena
# con formato; el acento grave es el caracter de ESCAPE, no sustitucion.
# La quinta puerta era un `Remove-Item` de verdad y sigue preguntando.

class TestLoQueUnaSesionRealDestapo:

    @pytest.mark.parametrize("orden", [
        'try { $r = Invoke-WebRequest -Uri http://localhost:11434/api/tags '
        '-UseBasicParsing -TimeoutSec 5; "OLLAMA OK $($r.StatusCode)" } '
        'catch { "OLLAMA DOWN: $($_.Exception.Message)" }',
        'Start-Process -FilePath "ollama" -ArgumentList "serve" '
        '-WindowStyle Hidden; Start-Sleep -Seconds 4; '
        '"OK $($r.StatusCode)"',
    ])
    def test_interpolar_un_campo_no_es_construir_una_orden(self, orden):
        """Las dos puertas que mas molestaron, y no hacian nada."""
        decision = decidir(shell(orden, herramienta="PowerShell"))
        assert decision.veredicto is Veredicto.PERMITIR, decision.motivo
        assert decision.regla == "shell_inofensiva"

    def test_el_acento_grave_de_powershell_es_un_escape_no_una_orden(self):
        """En bash `cmd` ejecuta; en PowerShell `n es un salto de linea."""
        orden = 'Write-Output "linea uno`nlinea dos"'
        assert decidir(shell(orden, herramienta="PowerShell")).veredicto \
            is Veredicto.PERMITIR

    def test_en_BASH_el_acento_grave_sigue_siendo_opaco(self):
        """La otra mitad: aflojar PowerShell no puede aflojar bash."""
        decision = decidir(shell("echo `whoami`", herramienta="Bash"))
        assert decision.veredicto is Veredicto.NO_SE_SABE
        assert decision.regla == "shell_opaca"

    def test_un_commit_local_no_para_la_sesion(self):
        """`git push` esta en la lista y `git commit` no, a proposito:
        uno es irreversible y el otro se deshace."""
        orden = ('git add -A && git commit -q -m "$(cat <<\'EOF\'\n'
                 'add memory module\nEOF\n)"')
        assert decidir(shell(orden)).veredicto is Veredicto.PERMITIR

    def test_la_QUINTA_puerta_era_un_borrado_de_verdad_y_sigue_parando(self):
        """La unica de las cinco que estaba bien, y no se toca."""
        orden = ("Remove-Item probe_umbral.py -Confirm:$false; "
                 r".venv\Scripts\python.exe -m pytest tests -q")
        decision = decidir(shell(orden, herramienta="PowerShell"))
        assert decision.veredicto is Veredicto.ENDURECER
        assert decision.regla == "orden_destructiva"
        assert "probe_umbral.py" in decision.elementos


class TestSeMiraDENTRODeLaSustitucion:
    """Leer dentro no puede anadir puertas -- antes preguntaba SIEMPRE --,
    solo quitarlas. Estos tests son la mitad que no se puede perder."""

    @pytest.mark.parametrize("orden", [
        "echo $(rm -rf /tmp/cosas)",
        "echo `rm -rf /tmp/cosas`",
        "VAR=$(git push origin main) echo hecho",
    ])
    def test_lo_escondido_dentro_de_una_sustitucion_sigue_cayendo(self, orden):
        assert decidir(shell(orden)).hay_que_preguntar, orden

    def test_una_sustitucion_anidada_se_lee_entera(self):
        """Con una expresion regular en vez de un contador de parentesis,
        `$(a $(b) c)` se cerraria en el parentesis equivocado y el resto
        de la linea se leeria descuadrado."""
        decision = decidir(shell("echo $(dirname $(which rm))"))
        assert decision.veredicto is Veredicto.PERMITIR, decision.motivo

    def test_una_sustitucion_sin_cerrar_no_se_da_por_leida(self):
        """Se prefiere preguntar antes que leer media linea."""
        decision = decidir(shell("echo $(rm -rf /tmp"))
        assert decision.veredicto is Veredicto.NO_SE_SABE
        assert decision.regla == "sustitucion_sin_cerrar"

    def test_borrar_lo_que_diga_otra_orden_es_una_DUDA_no_un_borrado(self):
        """>>> TRES SALIDAS, Y AQUI SE VE POR QUE <<<
        La orden se entiende -- borra -- pero el OBJETIVO no se lee. La
        frase hablada de JC-0002 tiene que decir cuantos y cuales, y
        decir "borra tres archivos" sin saberlo seria inventar la
        peticion en la que el usuario consiente.
        """
        decision = decidir(shell("rm $(cat lista.txt)"))
        assert decision.veredicto is Veredicto.NO_SE_SABE
        assert decision.regla == "borrado_sin_objetivo"

    def test_un_borrado_con_objetivo_legible_sigue_siendo_ENDURECER(self):
        decision = decidir(shell("rm informe.pdf"))
        assert decision.veredicto is Veredicto.ENDURECER
        assert decision.regla == "orden_destructiva"


class TestUnBorradoDentroDelProyectoYaNoPregunta:
    """DECISION DEL USUARIO (2026-08-29): dentro del proyecto NO se pregunta.

    Su sesion real paro en un `Remove-Item probe_umbral.py` -- un temporal
    que la propia sesion habia creado dos minutos antes, dentro de la
    carpeta de trabajo. Preguntar por eso es el "si" reflejo que avisa D8:
    se contesta que si sin leer, y entonces la puerta deja de significar
    nada el dia que la respuesta importe.

    OJO AL ALCANCE: esto solo se ve en sesiones CON freno -- la carpeta
    base y los proyectos con `auto: false` --, porque en auto mode la
    puerta no llega nunca (JC-0017).
    """

    PROYECTO = r"C:\proyectos\TorreAzul"

    def _decidir(self, orden, herramienta="PowerShell"):
        return decidir(shell(orden, herramienta=herramienta),
                       directorio_sesion=self.PROYECTO)

    @pytest.mark.parametrize("orden", [
        "Remove-Item probe_umbral.py -Confirm:$false",
        "rm core/memory/db.py",
        "rm -rf build",
        r"rm C:\proyectos\TorreAzul\tmp.txt",
    ])
    def test_lo_de_dentro_pasa_solo(self, orden):
        decision = self._decidir(orden)
        assert decision.veredicto is Veredicto.PERMITIR, decision.motivo
        assert decision.regla == "borrado_dentro"

    @pytest.mark.parametrize("orden", [
        r"rm C:\proyectos\otro\importante.txt",
        "rm tmp.txt ../../secreto.txt",
    ])
    def test_lo_de_fuera_sigue_parando(self, orden):
        """Y basta con que UNO se salga: `rm a ../b` no es medio
        permitido."""
        assert self._decidir(orden).veredicto is Veredicto.ENDURECER

    @pytest.mark.parametrize("orden", [
        "rm -rf .",
        "rm -rf ./",
        "rm -rf ..",
        r"rm -rf C:\proyectos\TorreAzul",
    ])
    def test_borrar_EL_PROYECTO_ENTERO_no_es_borrar_dentro(self, orden):
        """>>> ESTO NO ESTABA EN LA DECISION, ESTA PUESTO APARTE <<<
        "Un archivo dentro del proyecto" y "el proyecto entero" no son la
        misma frase, aunque `is_relative_to` diga que si para las dos.
        Un `rm -rf .` borra el trabajo del que se venia hablando.

        `rm -rf .` fue el que lo destapo: salia PERMITIR porque comparar
        un `.` crudo contra la ruta de la sesion no casa nunca.
        """
        decision = self._decidir(orden)
        assert decision.veredicto is Veredicto.ENDURECER, decision.motivo
        assert decision.regla == "orden_destructiva"

    def test_sin_directorio_de_sesion_no_se_da_nada_por_dentro(self):
        """Sin nada contra lo que comparar, se pregunta. `None` no puede
        significar "todo vale"."""
        decision = decidir(shell("rm tmp.txt"))
        assert decision.veredicto is Veredicto.ENDURECER

    def test_un_borrado_sin_objetivo_legible_sigue_siendo_una_duda(self):
        """No se puede comprobar que este dentro lo que no se lee."""
        assert self._decidir("rm $(cat lista.txt)", "Bash").veredicto \
            is Veredicto.NO_SE_SABE

    def test_git_push_NO_pasa_por_esta_regla(self):
        """No es una ruta: no hay "dentro" que valga. Sigue preguntando
        aunque el repositorio sea el del proyecto."""
        decision = self._decidir("git push origin main", "Bash")
        assert decision.veredicto is Veredicto.ENDURECER
        assert decision.regla == "forma_destructiva"

    def test_una_zona_del_SUELO_sigue_ganando(self):
        """El orden importa: el suelo va antes que todo. Si esta regla
        se colara delante, un borrado en zona de sistema desde una sesion
        acotada ahi pasaria solo."""
        from seguridad.zonas import Zona

        zona = Zona(ruta=r"C:\Windows", motivo="zona de sistema",
                    obligatoria=True)
        decision = decidir(
            shell("rm x.txt"), directorio_sesion=r"C:\Windows",
            zonas=(zona,))
        assert decision.veredicto is not Veredicto.PERMITIR
