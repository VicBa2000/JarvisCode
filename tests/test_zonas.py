"""Tests de `seguridad/zonas.py` y de la mitad de ordenes de JC-0007.

Los de deteccion corren contra el disco REAL, y es deliberado: un mock de
volumenes mediria el mock. Lo que se afirma sobre esta maquina concreta
esta separado en su propia clase y dice de que maquina habla.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from puente.politica import Veredicto, decidir
from puente.protocolo import Puerta
from seguridad.zonas import (
    Vigencia,
    Zona,
    comprobar_vigencia,
    detectar,
    reglas_deny,
)


def _puerta(orden: str) -> Puerta:
    return Puerta(id_peticion="p", herramienta="Bash",
                  entrada={"command": orden}, descripcion="", id_uso="u")


# --------------------------------------------------------------------
# El patron, que es donde se pierde el suelo sin avisar
# --------------------------------------------------------------------

class TestPatron:
    def test_una_carpeta_cubre_su_contenido(self):
        zona = Zona("C:\\Windows", "el sistema", obligatoria=True)
        assert zona.patron_escritura == "C:\\Windows\\**"

    def test_un_archivo_se_nombra_tal_cual(self):
        zona = Zona("C:\\pagefile.sys", "paginacion", obligatoria=True,
                    directorio=False)
        assert zona.patron_escritura == "C:\\pagefile.sys"

    def test_una_carpeta_con_punto_en_el_nombre_sigue_siendo_carpeta(self):
        """El fallo real que tenia la primera version de este modulo.

        `C:\\Config.Msi` y `C:\\$Windows.~WS` son CARPETAS con punto en el
        nombre. Adivinando por el sufijo se clasificaban como archivos, la
        regla nombraba la carpeta y su contenido quedaba escribible. Y no
        se habria visto nunca: un `deny` que no casa no da ningun error.
        """
        for ruta in ("C:\\Config.Msi", "C:\\$Windows.~WS", "C:\\$WINDOWS.~BT"):
            zona = Zona(ruta, "sistema", obligatoria=True, directorio=True)
            assert zona.patron_escritura == ruta + "\\**"

    def test_las_reglas_son_solo_de_escritura(self):
        """El eje 1 permite LEER. Si aqui apareciera un `Read(...)`,
        "que version de driver cuda tengo" dejaria de funcionar."""
        reglas = reglas_deny([Zona("C:\\Windows", "el sistema", obligatoria=True)])
        assert reglas == ["Write(C:\\Windows\\**)", "Edit(C:\\Windows\\**)"]
        assert not any(r.startswith("Read(") for r in reglas)

    def test_la_forma_del_patron_es_la_medida_y_no_otra(self):
        """Medido el 2026-08-24: `/c/...` y `//C:/...` NO muerden, y no
        dan error al no morder. Solo vale la forma nativa."""
        zona = Zona("C:\\Windows", "el sistema", obligatoria=True)
        patron = zona.patron_escritura
        assert patron.startswith("C:\\")
        assert not patron.startswith("/")
        assert not patron.startswith("//")


# --------------------------------------------------------------------
# La vigencia: tres respuestas, no dos
# --------------------------------------------------------------------

class TestVigencia:
    def test_sin_volumen_apuntado_no_se_puede_desmentir(self):
        zonas = [Zona("C:\\Users\\x\\.claude", "config", obligatoria=True)]
        estado, _ = comprobar_vigencia(zonas)
        assert estado is Vigencia.VIGENTE

    def test_una_letra_que_ya_no_existe_es_CAMBIADA(self):
        zonas = [Zona("Z:\\Windows", "el sistema", obligatoria=True,
                      volumen="\\\\?\\Volume{00000000-0000-0000-0000-000000000000}\\")]
        estado, motivo = comprobar_vigencia(zonas)
        assert estado is Vigencia.CAMBIADA
        assert "Z:" in motivo

    def test_una_letra_que_ahora_es_otro_disco_es_CAMBIADA(self):
        """La trampa que da nombre al modulo: la regla sigue siendo
        sintacticamente valida y ya no protege lo que protegia."""
        raiz = os.environ.get("SystemDrive", "C:")
        zonas = [Zona(f"{raiz}\\Windows", "el sistema", obligatoria=True,
                      volumen="\\\\?\\Volume{deadbeef-0000-0000-0000-000000000000}\\")]
        estado, motivo = comprobar_vigencia(zonas)
        assert estado is Vigencia.CAMBIADA
        assert "ya no protege" in motivo

    def test_no_se_sabe_existe_como_tercera_salida(self):
        assert Vigencia.NO_SE_SABE not in (Vigencia.VIGENTE, Vigencia.CAMBIADA)


# --------------------------------------------------------------------
# La mitad de ordenes: lo que rompe la PC sin tocar ninguna ruta
# --------------------------------------------------------------------

class TestOrdenesQueRompenElSistema:
    @pytest.mark.parametrize("orden", [
        "reg delete HKLM\\SYSTEM\\CurrentControlSet\\Services\\foo /f",
        "reg add HKLM\\SOFTWARE\\Policies /v X /d 1",
        "bcdedit /set {default} safeboot minimal",
        "diskpart /s script.txt",
        "format D: /q",
        "vssadmin delete shadows /all /quiet",
        "sc delete AudioSrv",
        "takeown /f C:\\Windows\\System32 /r",
        "icacls C:\\Windows /grant Todos:F",
        "robocopy C:\\origen D:\\destino /mir",
        "schtasks /delete /tn Jarvis /f",
        "cipher /w:C",
        "net user invitado /delete",
        "Remove-Item HKLM:\\SOFTWARE\\Foo -Recurse",
        "Format-Volume -DriveLetter D",
        "bootrec /fixmbr",
    ])
    def test_se_endurecen(self, orden):
        decision = decidir(_puerta(orden), "C:\\proyectos\\JarvisCode")
        assert decision.veredicto is Veredicto.ENDURECER, orden
        assert decision.regla == "rompe_el_sistema", orden
        assert decision.motivo, "una pregunta hablada sin motivo no se puede locutar"

    @pytest.mark.parametrize("orden", [
        # Leer el sistema es TODO el punto del eje 1: "que version de
        # driver cuda tengo" pasa por aqui.
        "reg query HKLM\\SOFTWARE\\NVIDIA Corporation",
        "dism /online /get-features",
        "icacls C:\\Windows\\System32",
        "mountvol",
        "fsutil fsinfo drives",
        "schtasks /query",
        "net user",
        "robocopy C:\\origen D:\\destino /e",
        "sc query AudioSrv",
        "nvidia-smi",
        "systeminfo",
    ])
    def test_lo_de_solo_leer_no_molesta(self, orden):
        """Si estas preguntaran, el asistente seria un interrogatorio y el
        usuario aprenderia a decir que si sin escuchar (D8)."""
        decision = decidir(_puerta(orden), "C:\\proyectos\\JarvisCode")
        assert decision.veredicto is Veredicto.PERMITIR, orden

    def test_la_lista_sigue_siendo_corta(self):
        """Regla de JC-0001: la lista endurecida solo vale mientras quepa
        en la cabeza. Si crece, se decide a proposito, no por goteo."""
        from puente.politica import FORMAS_QUE_ROMPEN_EL_SISTEMA
        assert len(FORMAS_QUE_ROMPEN_EL_SISTEMA) <= 25


# --------------------------------------------------------------------
# La deteccion, contra el disco de verdad
# --------------------------------------------------------------------

class TestDeteccion:
    def test_detecta_el_windows_que_arranca(self):
        obligatorias, _ = detectar()
        raiz = os.environ.get("SystemRoot", "C:\\Windows")
        assert any(z.ruta.lower() == raiz.lower() for z in obligatorias)

    def test_todo_lo_obligatorio_viene_marcado_como_tal(self):
        obligatorias, opcionales = detectar()
        assert all(z.obligatoria for z in obligatorias)
        assert not any(z.obligatoria for z in opcionales)

    def test_toda_opcional_dice_lo_que_cuesta(self):
        """Una casilla sin su coste es una casilla que se marca sin
        entenderla, que es el mismo reflejo que D8, en una pantalla."""
        _, opcionales = detectar()
        for zona in opcionales:
            assert zona.coste.strip(), f"{zona.ruta} se ofrece sin decir que cuesta"

    def test_el_proyecto_no_cae_dentro_del_suelo(self):
        """Si el suelo tapara el propio arbol, Jarvis no podria ni
        trabajar sobre si mismo y el suelo se acabaria desactivando."""
        obligatorias, _ = detectar()
        proyecto = Path(__file__).resolve().parent.parent
        for zona in obligatorias:
            assert not str(proyecto).lower().startswith(zona.ruta.lower() + "\\")

    def test_protege_los_archivos_que_definen_sus_propios_limites(self):
        """La unica entrada del suelo que no protege la PC: protege a la
        proteccion. Un agente que puede reescribir sus reglas no tiene."""
        obligatorias, _ = detectar()
        rutas = " ".join(z.ruta.lower() for z in obligatorias)
        assert ".claude" in rutas

    def test_no_se_ofrece_AppData_entero(self):
        """Bloquear AppData deja fuera npm, cargo, uv y los caches: el
        asistente queda inutil, y un suelo que estorba tanto se apaga."""
        _, opcionales = detectar()
        for zona in opcionales:
            assert not zona.ruta.lower().rstrip("\\").endswith("appdata")


class TestEstaMaquinaEnConcreto:
    """Afirmaciones sobre la maquina del usuario, medidas el 2026-08-24.

    Van aparte porque son las unicas que otro equipo puede fallar sin que
    haya nada roto. Si fallan aqui, el disco cambio y hay que releer el
    suelo, que es justo lo que quieren avisar.
    """

    def test_el_segundo_windows_de_E_esta_en_el_suelo(self):
        """El hallazgo que justifica que el suelo se DETECTE. Una lista
        escrita a mano habria protegido C:\\Windows y dejado este fuera."""
        if not Path("E:\\Windows\\System32\\ntoskrnl.exe").exists():
            pytest.skip("esta maquina ya no tiene el segundo Windows en E:")
        obligatorias, _ = detectar()
        assert any(z.ruta.lower() == "e:\\windows" for z in obligatorias)

    def test_el_segundo_windows_se_nombra_como_lo_que_es(self):
        if not Path("E:\\Windows\\System32\\ntoskrnl.exe").exists():
            pytest.skip("esta maquina ya no tiene el segundo Windows en E:")
        obligatorias, _ = detectar()
        ajeno = next(z for z in obligatorias if z.ruta.lower() == "e:\\windows")
        assert "NO es el que arranca" in ajeno.motivo

    def test_las_unidades_siguen_siendo_las_que_se_detectaron(self):
        obligatorias, _ = detectar()
        estado, motivo = comprobar_vigencia(obligatorias)
        assert estado is Vigencia.VIGENTE, motivo
