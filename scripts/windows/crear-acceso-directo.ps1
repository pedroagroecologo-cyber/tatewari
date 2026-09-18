# ===================================================================
#  Tatewari - crea el acceso directo en el Escritorio
#
#  Apunta a scripts\windows\tatewari.bat y deja como carpeta de
#  trabajo la raiz del proyecto, que es lo que hace que las rutas
#  relativas de las ordenes (protocolos\humedales.json) funcionen.
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
$lanzador = Join-Path $carpetaScript 'tatewari.bat'

if (-not (Test-Path -LiteralPath $lanzador)) {
    Write-Host ''
    Write-Host 'ERROR: no se encuentra tatewari.bat junto a este script.' -ForegroundColor Red
    Write-Host "       Se buscaba en: $lanzador"
    Write-Host '       Los dos archivos tienen que estar en scripts\windows\.'
    exit 1
}

# El Escritorio se pregunta al sistema y no se compone a mano: con
# OneDrive activado no esta en %USERPROFILE%\Desktop.
$escritorio = [Environment]::GetFolderPath('Desktop')
if (-not $escritorio -or -not (Test-Path -LiteralPath $escritorio)) {
    Write-Host ''
    Write-Host 'ERROR: no se pudo encontrar la carpeta del Escritorio.' -ForegroundColor Red
    exit 1
}

$destino = Join-Path $escritorio 'Tatewari.lnk'

# --- El acceso directo -----------------------------------------------
if (Test-Path -LiteralPath $destino) {
    Write-Host "Ya existe un acceso directo en: $destino"
    $respuesta = Read-Host 'Se va a reemplazar. Continuar? (s/N)'
    if ($respuesta -notmatch '^[sS]') {
        Write-Host 'Cancelado. No se ha tocado nada.'
        exit 0
    }
}

try {
    $shell = New-Object -ComObject WScript.Shell
    $atajo = $shell.CreateShortcut($destino)
    $atajo.TargetPath = $lanzador
    # La carpeta de trabajo es la raiz del proyecto: sin esto, las
    # rutas relativas de las ordenes no encuentran nada.
    $atajo.WorkingDirectory = $raiz
    $atajo.Description = 'Tatewari - agente local de revision sistematica de literatura'
    $atajo.IconLocation = "$env:SystemRoot\System32\cmd.exe,0"
    $atajo.Save()
}
catch {
    Write-Host ''
    Write-Host 'ERROR: no se pudo crear el acceso directo.' -ForegroundColor Red
    Write-Host "       $($_.Exception.Message)"
    Write-Host ''
    Write-Host 'Puedes crearlo a mano: clic derecho en el Escritorio,'
    Write-Host 'Nuevo > Acceso directo, y pega esta ruta:'
    Write-Host "  $lanzador"
    exit 1
}

Write-Host ''
Write-Host 'Acceso directo creado.' -ForegroundColor Green
Write-Host "  Escritorio      : $destino"
Write-Host "  Abre            : $lanzador"
Write-Host "  Carpeta de trabajo: $raiz"
Write-Host ''
Write-Host 'La primera vez que lo abras, creara el entorno virtual e'
Write-Host 'instalara las dependencias. Puede tardar un par de minutos.'
Write-Host ''
