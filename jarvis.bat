@echo off
setlocal
rem ===================================================================
rem  Arranca Jarvis: ventana propia, icono en la bandeja, escuchando.
rem
rem  >>> POR QUE ESTE ARCHIVO COMPRUEBA ANTES DE LANZAR <<<
rem  Lanza `pythonw.exe`, que NO tiene consola: es lo que evita una
rem  ventana negra abierta todo el dia detras de Jarvis. El precio es
rem  que si algo falla ahi dentro no se ve nada -- medido y escrito en
rem  `escritorio/salida.py`: con `pythonw`, `sys.stdout` es None y un
rem  `print` no hace absolutamente nada.
rem  Asi que lo que se puede mirar ANTES se mira aqui, donde todavia
rem  hay consola para decirlo. Lo de despues va al diario que abre
rem  `escritorio/salida.py`.
rem
rem  Sin tildes a proposito: ver la cabecera de `instalar.bat`.
rem ===================================================================

cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo.
  echo   [FALTA] el entorno .venv.
  echo           Ejecuta primero  instalar.bat
  echo.
  pause
  exit /b 1
)

rem La carpeta puede venir por aqui o estar guardada en AJUSTES. Se pasa
rem tal cual: `escritorio` la acepta opcional y, si no hay ninguna de las
rem dos, ENSEnA UNA VENTANA diciendolo -- no muere en silencio.
rem
rem `start ""` para que la consola se cierre y no se quede una ventana
rem colgada de la que Jarvis depende; el primer "" es el TITULO, y sin
rem el, `start` se come la ruta entre comillas creyendo que es eso.
start "" ".venv\Scripts\pythonw.exe" -m escritorio %* --voz
exit /b 0
