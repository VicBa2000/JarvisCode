@echo off
setlocal
rem ===================================================================
rem  Deja un acceso directo a Jarvis en el Escritorio.
rem
rem  El `.lnk` lo escribe `escritorio/inicio.py`, que es quien ya sabe
rem  hacerlo para el arranque de Windows. UN SOLO SITIO: lo delicado de
rem  un acceso directo no es crearlo, es a que apunta -- al interprete
rem  SIN consola y con el directorio de trabajo puesto --, y eso escrito
rem  dos veces acaba divergiendo.
rem
rem  Sin tildes a proposito: ver la cabecera de `instalar.bat`.
rem ===================================================================

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo   [FALTA] el entorno .venv.
  echo           Ejecuta primero  instalar.bat
  echo.
  pause
  exit /b 1
)

.venv\Scripts\python.exe -m escritorio.inicio escritorio
if errorlevel 1 (
  echo.
  echo   No se pudo crear. El motivo esta arriba.
  echo   Mientras tanto, Jarvis arranca igual con  jarvis.bat
  echo.
)
echo.
pause
exit /b 0
