@echo off
setlocal EnableDelayedExpansion
rem ===================================================================
rem  Jarvis - instalacion en un doble clic.
rem
rem  SIN TILDES A PROPOSITO: la consola de Windows arranca en la pagina
rem  de codigos del sistema (850 o 437 aqui), no en UTF-8, y un acento
rem  en un `.bat` sale como basura. No es cosmetico: la mitad de este
rem  archivo son mensajes de error, y un mensaje ilegible es un mensaje
rem  que no existe.
rem
rem  LO QUE ESTO **NO** HACE, y esta dicho arriba del todo porque es lo
rem  que decide si Jarvis te sirve:
rem    * no instala Claude Code. Hace falta, con TU cuenta.
rem    * no instala Python. Hace falta 3.11.
rem  Un instalador que se calla lo que falta te deja descubriendolo
rem  cuando ya creias haber terminado.
rem ===================================================================

cd /d "%~dp0"
echo.
echo   ================================================
echo    JARVIS - instalacion
echo   ================================================
echo.

rem --- 1. Python 3.11 -------------------------------------------------
rem Se prueba el lanzador `py` primero, que es como se elige version en
rem Windows. Si no esta, se mira el `python` del PATH y se COMPRUEBA su
rem version en vez de confiar: con 3.13 el `.venv` se crea sin error y
rem las ruedas de la voz no existen para esa version. El fallo llegaria
rem quince pasos mas tarde y sin relacion aparente.
set "PY="
py -3.11 --version >nul 2>&1 && set "PY=py -3.11"
if not defined PY (
  for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "VER=%%v"
  if defined VER (
    echo !VER! | findstr /b "3.11." >nul && set "PY=python"
  )
)
if not defined PY (
  echo   [FALTA] Python 3.11.
  echo.
  echo   Jarvis necesita 3.11 en concreto: la capa de voz
  echo   ^(faster-whisper, onnxruntime, piper^) no tiene ruedas para
  echo   las versiones mas nuevas, y con otra el entorno se crea
  echo   igual y falla despues, sin decir por que.
  echo.
  echo   Se baja en   https://www.python.org/downloads/release/python-3119/
  echo   Marca "Add python.exe to PATH" al instalarlo.
  echo.
  goto :fin_error
)
for /f "delims=" %%v in ('%PY% --version 2^>^&1') do echo   [OK]    %%v

rem --- 2. el entorno virtual -----------------------------------------
if exist ".venv\Scripts\python.exe" (
  echo   [OK]    el entorno .venv ya existe
) else (
  echo   [...]   creando el entorno .venv
  %PY% -m venv .venv
  if errorlevel 1 (
    echo   [ERROR] no se pudo crear .venv
    goto :fin_error
  )
  echo   [OK]    entorno creado
)
set "VPY=.venv\Scripts\python.exe"

rem --- 3. las dependencias -------------------------------------------
rem >>> Y AQUI HAY DOS INTENTOS, NO UNO, POR UNA RAZON MEDIDA <<<
rem En esta maquina el primero FALLA: Avast intercepta HTTPS y presenta
rem su propio certificado, que `certifi` -- el almacen que trae pip --
rem no conoce. Sale `CERTIFICATE_VERIFY_FAILED` y `pip` no baja nada.
rem No es raro: Avast, Kaspersky, ESET y cualquier proxy corporativo
rem hacen lo mismo, o sea que le pasaria a mucha gente en su primer
rem doble clic.
rem
rem LA SALIDA **NO** ES `--trusted-host`, y esto no se negocia: eso apaga
rem la verificacion del certificado en un programa cuya premisa entera es
rem la seguridad. Lo que se hace es `--use-feature=truststore`, que le
rem dice a pip que use el ALMACEN DE WINDOWS en vez del suyo -- y ahi la
rem CA del antivirus ya esta instalada y el sistema ya la considera
rem fiable, porque la puso el propio antivirus al instalarse. Se verifica
rem igual; lo que cambia es contra que lista.
rem Medido el 2026-09-09 en la maquina del autor: sin el, falla; con el,
rem instala entero.
echo   [...]   instalando dependencias ^(tarda unos minutos la primera vez^)
"%VPY%" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if not errorlevel 1 goto :deps_ok

echo   [...]   fallo al primer intento. Probando con el almacen de
echo           certificados de Windows ^(por si un antivirus intercepta^)
"%VPY%" -m pip install --quiet --disable-pip-version-check ^
        --use-feature=truststore -r requirements.txt
if not errorlevel 1 (
  echo   [OK]    instalado usando el almacen de Windows
  goto :deps_ok
)

echo.
echo   [ERROR] fallo `pip install`, en los dos intentos.
echo.
echo   SI PONE CERTIFICATE_VERIFY_FAILED: hay algo interceptando tu
echo   HTTPS ^(un antivirus, o un proxy de empresa^). Ya se ha probado
echo   con el almacen de Windows y tampoco. Lo que queda es exportar
echo   ese certificado y apuntar pip a el con un `pip.ini` dentro de
echo   .venv.
echo   NO uses `--trusted-host`: apaga la verificacion, y este
echo   programa va sobre tu maquina entera.
echo.
echo   SI PONE OTRA COSA: probablemente sea la red. Vuelve a intentarlo.
echo.
goto :fin_error

:deps_ok
echo   [OK]    dependencias instaladas

rem --- 4. los modelos ------------------------------------------------
rem Son DOS descargas en sitios distintos y lo sabe UN SOLO SITIO:
rem `scripts/bajar_modelos.py`. Aqui no van dos `-c` con Python dentro,
rem y no es gusto: esas descargas necesitan verificar contra el almacen
rem de Windows ANTES de empezar ^(ver la cabecera de ese archivo^), y eso
rem un `.bat` no lo puede hacer por delante de un `-m`.
echo   [...]   modelos de voz y escucha ^(unos 80 MB la primera vez^)
"%VPY%" scripts\bajar_modelos.py
if errorlevel 1 set "FALTAN_MODELOS=1"

rem --- 5. lo que no podemos instalar por ti ---------------------------
echo.
where claude >nul 2>&1
if errorlevel 1 (
  echo   [FALTA] Claude Code.
  echo           Jarvis no piensa: le habla a Claude Code, que corre con
  echo           TU cuenta y TU cupo. Sin el no hay asistente.
  echo           Instrucciones en  https://claude.com/claude-code
) else (
  for /f "delims=" %%v in ('claude --version 2^>^&1') do echo   [OK]    Claude Code %%v
)

rem --- 6. el veredicto, que NO puede decir "listo" a medias -----------
rem >>> ESTO ESTABA MAL EN LA PRIMERA VERSION Y SE VIO PROBANDO <<<
rem (2026-09-09.) El resumen decia "Listo. Arrancalo con jarvis.bat"
rem aunque las dos descargas hubieran fallado tres lineas mas arriba.
rem Un instalador que se felicita encima de sus propios avisos es la
rem misma forma que la barra de la cuota: ni un dato mal y la pantalla
rem diciendo lo contrario.
echo.
if defined FALTAN_MODELOS (
  echo   ================================================
  echo    INSTALADO A MEDIAS.
  echo.
  echo    Lo demas esta puesto, pero faltan modelos: mira
  echo    los [FALLO] de arriba. Jarvis arranca con
  echo    jarvis.bat y la CONSOLA funciona; lo que no va
  echo    es la voz.
  echo.
  echo    Se reintenta volviendo a ejecutar este archivo:
  echo    lo que ya estuviera hecho no se repite.
  echo   ================================================
  echo.
  pause
  exit /b 1
)
echo   ================================================
echo    Listo. Arrancalo con   jarvis.bat
echo.
echo    La primera vez te pedira la carpeta de trabajo:
echo    la carpeta sobre la que Jarvis puede trabajar.
echo   ================================================
echo.
echo   Recuerda lo que esto hace: manda tus ordenes y el
echo   contenido de los archivos que lea a la nube, gasta
echo   TU cupo de Claude, y actua sobre tu PC de verdad.
echo   Esta explicado entero en README.md.
echo.
pause
exit /b 0

:fin_error
echo   ================================================
echo    NO se completo. Arregla lo de arriba y vuelve a
echo    ejecutar este archivo: lo que ya estuviera hecho
echo    no se repite.
echo   ================================================
echo.
pause
exit /b 1
