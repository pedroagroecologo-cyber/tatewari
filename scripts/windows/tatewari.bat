@echo off
setlocal EnableExtensions

rem ===================================================================
rem  Tatewari - lanzador para Windows
rem
rem  Comprueba Python, crea el entorno virtual e instala las
rem  dependencias la primera vez, y deja una consola lista para usar
rem  el agente.
rem
rem  Este archivo tiene que estar guardado con finales de linea CRLF.
rem  El .gitattributes del repositorio lo fuerza: cmd.exe no interpreta
rem  bien un bloque if o for con finales de linea de Unix y se rompe
rem  con un "was unexpected at this time" que no dice nada.
rem
rem  Sin acentos a proposito: la consola de Windows arranca con la
rem  pagina de codigos local y los destrozaria.
rem ===================================================================

rem La raiz del proyecto son dos carpetas por encima de esta.
pushd "%~dp0..\.." || goto :sin_carpeta
set "RAIZ=%CD%"
set "VENV=%RAIZ%\.venv"
set "PY_VENV=%VENV%\Scripts\python.exe"

title Tatewari - %RAIZ%

echo ===================================================================
echo  Tatewari - agente local de revision sistematica
echo  Carpeta: %RAIZ%
echo ===================================================================
echo.

rem -------------------------------------------------------------------
rem  1. El entorno virtual
rem -------------------------------------------------------------------
if exist "%PY_VENV%" goto :entorno_listo

echo [1/3] No hay entorno virtual todavia. Buscando Python 3.12...

rem py.exe es el lanzador oficial y sabe que versiones hay instaladas.
set "PY_BASE="
where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY_BASE=py -3.12"
)

rem Sin py, se prueba con el python del PATH, comprobando la version.
if not defined PY_BASE (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1
        if not errorlevel 1 set "PY_BASE=python"
    )
)

if not defined PY_BASE goto :sin_python

echo       Usando: %PY_BASE%
echo [2/3] Creando el entorno virtual en .venv...
%PY_BASE% -m venv "%VENV%"
if errorlevel 1 goto :venv_fallido

echo [3/3] Instalando Tatewari y sus dependencias...
"%PY_VENV%" -m pip install --upgrade pip >nul
"%PY_VENV%" -m pip install -e ".[dev]"
if errorlevel 1 goto :pip_fallido

echo.
echo Entorno listo.
echo.

:entorno_listo

rem -------------------------------------------------------------------
rem  2. El archivo .env
rem -------------------------------------------------------------------
if not exist "%RAIZ%\.env" (
    if exist "%RAIZ%\.env.example" (
        copy /Y "%RAIZ%\.env.example" "%RAIZ%\.env" >nul
        echo AVISO: se ha creado .env a partir de .env.example.
        echo        Abrelo y pon tu correo en TATEWARI_MAILTO antes de
        echo        cosechar: Unpaywall lo exige y OpenAlex lo premia.
        echo.
    )
)

rem -------------------------------------------------------------------
rem  3. Ollama
rem -------------------------------------------------------------------
where ollama >nul 2>&1
if errorlevel 1 (
    echo AVISO: no se encuentra Ollama en el PATH. El cribado determinista
    echo        funciona igual; para --modelo-local y la busqueda por
    echo        parecido hace falta instalarlo desde https://ollama.com
    echo.
)

rem -------------------------------------------------------------------
rem  4. La consola
rem -------------------------------------------------------------------
rem chcp 65001 pone la consola en UTF-8, que es lo que evita que los
rem acentos de la salida salgan como signos raros.
chcp 65001 >nul

echo Consola lista. El entorno virtual esta activado.
echo.
echo Ordenes para empezar:
echo.
echo   tatewari --help
echo   tatewari protocolo validar protocolos\humedales.json
echo   tatewari cosechar demo --protocolo protocolos\humedales.json --seco
echo   tatewari estado demo
echo.
echo El recorrido completo esta en README.md.
echo Escribe "exit" para cerrar.
echo.

rem cmd /k deja la consola abierta con el entorno activado.
call "%VENV%\Scripts\activate.bat"
cmd /k
popd
goto :fin

rem -------------------------------------------------------------------
rem  Errores
rem -------------------------------------------------------------------
:sin_carpeta
echo ERROR: no se pudo entrar en la carpeta del proyecto.
echo        Este archivo tiene que quedarse en scripts\windows\.
pause
exit /b 1

:sin_python
echo.
echo ERROR: hace falta Python 3.12 o superior y no se ha encontrado.
echo.
echo   1. Descargalo de https://www.python.org/downloads/
echo   2. En el instalador, marca "Add python.exe to PATH".
echo   3. Cierra esta ventana y vuelve a abrir el lanzador.
echo.
echo Si ya lo tienes instalado, comprueba en otra consola:
echo   py -3.12 --version
echo.
popd
pause
exit /b 1

:venv_fallido
echo.
echo ERROR: no se pudo crear el entorno virtual en:
echo   %VENV%
echo.
echo Suele ser por permisos o porque la carpeta esta sincronizada con
echo OneDrive y tiene un archivo bloqueado. Prueba a cerrar los
echo programas que usen esa carpeta y vuelve a lanzarlo.
echo.
popd
pause
exit /b 1

:pip_fallido
echo.
echo ERROR: fallo la instalacion de las dependencias.
echo.
echo Lee el mensaje de pip que ha quedado arriba. Lo mas comun es no
echo tener conexion a internet la primera vez: hace falta para
echo descargar "requests" y "pytest".
echo.
popd
pause
exit /b 1

:fin
endlocal
