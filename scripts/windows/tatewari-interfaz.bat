@echo off
setlocal EnableExtensions

rem ===================================================================
rem  Tatewari - abre la interfaz grafica
rem
rem  Comprueba que el entorno y Ollama esten listos, abre la interfaz en
rem  el navegador y carga el modelo local en la tarjeta. Esta ventana
rem  es el servidor: al cerrarla, la interfaz se apaga.
rem
rem  CRLF y sin acentos, igual que tatewari.bat.
rem ===================================================================

pushd "%~dp0..\.." || goto :sin_carpeta
set "RAIZ=%CD%"
set "PY_VENV=%RAIZ%\.venv\Scripts\python.exe"
set "ESPERA=0"

title Tatewari - interfaz

if not exist "%PY_VENV%" goto :sin_entorno

rem -------------------------------------------------------------------
rem  Ollama: si esta instalado pero cerrado, se abre.
rem -------------------------------------------------------------------
"%PY_VENV%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:11434/api/version', timeout=2)" >nul 2>&1
if not errorlevel 1 goto :ollama_listo

set "OLLAMA_APP=%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
if exist "%OLLAMA_APP%" (
    echo Ollama no estaba abierto. Abriendolo...
    start "" "%OLLAMA_APP%"
    set "ESPERA=45"
) else (
    echo AVISO: Ollama no responde y no se encuentra instalado.
    echo        La interfaz abre igual, pero sin modelo no se procesan
    echo        documentos. Instalalo desde https://ollama.com
    echo.
)

:ollama_listo
chcp 65001 >nul
"%PY_VENV%" -m tatewari interfaz --esperar-ollama %ESPERA%
popd
goto :fin

:sin_carpeta
echo ERROR: no se pudo entrar en la carpeta del proyecto.
echo        Este archivo tiene que quedarse en scripts\windows\.
pause
exit /b 1

:sin_entorno
echo.
echo Todavia no esta instalado el entorno de Tatewari.
echo Abre una vez scripts\windows\tatewari.bat: crea el entorno e
echo instala todo. Despues vuelve a abrir este.
echo.
popd
pause
exit /b 1

:fin
endlocal
