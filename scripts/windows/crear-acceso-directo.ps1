# ===================================================================
#  Tatewari - crea los accesos directos en el Escritorio
#
#  Dos accesos directos:
#    Tatewari            -> scripts\windows\tatewari.bat (la consola)
#    Tatewari - interfaz -> scripts\windows\tatewari-interfaz.bat
#                           (la interfaz grafica en el navegador)
#
#  Los dos dejan como carpeta de trabajo la raiz del proyecto, que es lo
#  que hace que las rutas relativas de las ordenes
#  (protocolos\humedales.json) funcionen.
#
#  Uso, desde esta carpeta:
#    powershell -ExecutionPolicy Bypass -File .\crear-acceso-directo.ps1
#
#  Este archivo se guarda con finales de linea CRLF, igual que los
#  .bat: lo fuerza el .gitattributes del repositorio.
# ===================================================================

$ErrorActionPreference = 'Stop'

# --- Rutas -----------------------------------------------------------
# $PSScriptRoot es la carpeta de este script; la raiz esta dos arriba.
$carpetaScript = $PSScriptRoot
if (-not $carpetaScript) {
    $carpetaScript = Split-Path -Parent $MyInvocation.MyCommand.Definition
}

$raiz = (Resolve-Path (Join-Path $carpetaScript '..\..')).Path

# El Escritorio se pregunta al sistema y no se compone a mano: con
# OneDrive activado no esta en %USERPROFILE%\Desktop.
$escritorio = [Environment]::GetFolderPath('Desktop')
if (-not $escritorio -or -not (Test-Path -LiteralPath $escritorio)) {
    Write-Host ''
    Write-Host 'ERROR: no se pudo encontrar la carpeta del Escritorio.' -ForegroundColor Red
    exit 1
}

function Crear-Atajo {
    param([string]$nombre, [string]$lanzador, [string]$descripcion)

    if (-not (Test-Path -LiteralPath $lanzador)) {
        Write-Host ''
        Write-Host "ERROR: no se encuentra $lanzador junto a este script." -ForegroundColor Red
        Write-Host '       Los archivos tienen que estar en scripts\windows\.'
        return $false
    }

    $destino = Join-Path $escritorio "$nombre.lnk"
    if (Test-Path -LiteralPath $destino) {
        Write-Host "Ya existe un acceso directo en: $destino"
        $respuesta = Read-Host 'Se va a reemplazar. Continuar? (s/N)'
        if ($respuesta -notmatch '^[sS]') {
            Write-Host 'No se ha tocado.'
            return $true
        }
    }

    try {
        $shell = New-Object -ComObject WScript.Shell
        $atajo = $shell.CreateShortcut($destino)
        $atajo.TargetPath = $lanzador
        # La carpeta de trabajo es la raiz del proyecto: sin esto, las
        # rutas relativas de las ordenes no encuentran nada.
        $atajo.WorkingDirectory = $raiz
        $atajo.Description = $descripcion
        $atajo.IconLocation = "$env:SystemRoot\System32\cmd.exe,0"
        $atajo.Save()
    }
    catch {
        Write-Host ''
        Write-Host "ERROR: no se pudo crear el acceso directo $nombre." -ForegroundColor Red
        Write-Host "       $($_.Exception.Message)"
        Write-Host ''
        Write-Host 'Puedes crearlo a mano: clic derecho en el Escritorio,'
        Write-Host 'Nuevo > Acceso directo, y pega esta ruta:'
        Write-Host "  $lanzador"
        return $false
    }

    Write-Host ''
    Write-Host "Acceso directo creado: $nombre" -ForegroundColor Green
    Write-Host "  Escritorio        : $destino"
    Write-Host "  Abre              : $lanzador"
    Write-Host "  Carpeta de trabajo: $raiz"
    return $true
}

$consola = Crear-Atajo 'Tatewari' (Join-Path $carpetaScript 'tatewari.bat') 'Tatewari - agente local de revision sistematica de literatura'
$interfaz = Crear-Atajo 'Tatewari - interfaz' (Join-Path $carpetaScript 'tatewari-interfaz.bat') 'Tatewari - interfaz grafica en el navegador'

Write-Host ''
Write-Host 'La primera vez, abre "Tatewari" (la consola): crea el entorno'
Write-Host 'virtual e instala las dependencias. Despues, "Tatewari - interfaz"'
Write-Host 'abre la interfaz grafica y carga el modelo local.'
Write-Host ''

if (-not ($consola -and $interfaz)) { exit 1 }
