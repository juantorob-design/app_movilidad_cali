# ==============================================================================
# 0. Iniciar Registro Temporal de la Terminal
# ==============================================================================
$logFile = "$PSScriptRoot\compilacion_log.txt"
Start-Transcript -Path $logFile -Force

try {
    Write-Host "--------------------------------------------------" -ForegroundColor Cyan
    Write-Host " 1. Analizando el entorno de trabajo y código..." -ForegroundColor Cyan
    Write-Host "--------------------------------------------------" -ForegroundColor Cyan

    $archivosRequeridos = @(
        "run_app.py",
        "app_6.py",
        "updater.py",
        "run_app.spec",
        "requirements.txt",
        "images",
        "respaldo"
    )

    $faltantes = @()
    foreach ($archivo in $archivosRequeridos) {
        if (-Not (Test-Path "$PSScriptRoot\$archivo")) {
            $faltantes += $archivo
        }
    }

    if ($faltantes.Count -gt 0) {
        Write-Host "ERROR: Faltan archivos esenciales en el directorio:" -ForegroundColor Red
        $faltantes | ForEach-Object { Write-Host " - $_" -ForegroundColor Red }
        return
    } else {
        Write-Host "Todos los archivos de código fuente requeridos están presentes." -ForegroundColor Green
    }

    # Definir la ruta explícita al Python del entorno virtual venv
    $pythonVenv = "$PSScriptRoot\venv\Scripts\python.exe"

    if (-Not (Test-Path $pythonVenv)) {
        Write-Host "ERROR: No se encontró el entorno virtual en '$pythonVenv'. Ejecuta 'py -3.12 -m venv venv' primero." -ForegroundColor Red
        return
    }

    # ==============================================================================
    # 2. LIMPIEZA PRIMERO: Detener procesos y eliminar temporales antiguas
    # ==============================================================================
    Write-Host "`n--------------------------------------------------" -ForegroundColor Cyan
    Write-Host " 2. Limpiando procesos y residuos antiguos..." -ForegroundColor Cyan
    Write-Host "--------------------------------------------------" -ForegroundColor Cyan

    Write-Host "Deteniendo procesos previos en ejecución..." -ForegroundColor Yellow
    Get-Process "SistemaDesvinculaciones" -ErrorAction SilentlyContinue | Stop-Process -Force

    $carpetasLimpiar = @("build", "dist", "__pycache__")
    foreach ($carpeta in $carpetasLimpiar) {
        $rutaCarpeta = "$PSScriptRoot\$carpeta"
        if (Test-Path $rutaCarpeta) {
            Write-Host "Eliminando carpeta '$carpeta'..." -ForegroundColor Yellow
            try {
                Remove-Item -Recurse -Force $rutaCarpeta -ErrorAction Stop
            } catch {
                Write-Host "Advertencia: No se pudo eliminar completamente '$carpeta'. Continuando..." -ForegroundColor Warning
            }
        }
    }

    Get-ChildItem -Path $PSScriptRoot -Recurse -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

    # ==============================================================================
    # 3. CARGA Y PREPARACIÓN: Verificación e instalación de dependencias en VENV
    # ==============================================================================
    Write-Host "`n--------------------------------------------------" -ForegroundColor Cyan
    Write-Host " 3. Verificando e instalando librerías necesarias en VENV..." -ForegroundColor Cyan
    Write-Host "--------------------------------------------------" -ForegroundColor Cyan

    if (Test-Path "$PSScriptRoot\requirements.txt") {
        Write-Host "Instalando/actualizando paquetes desde 'requirements.txt'..." -ForegroundColor Yellow
        & $pythonVenv -m pip install --upgrade pip
        & $pythonVenv -m pip install -r "$PSScriptRoot\requirements.txt"
        & $pythonVenv -m pip install pyinstaller
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: Ocurrió un fallo al instalar las librerías." -ForegroundColor Red
            return
        }
        Write-Host "Librerías verificadas e instaladas correctamente." -ForegroundColor Green
    }

    # ==============================================================================
    # 4. COMPILACIÓN: Proceso con PyInstaller usando python -m PyInstaller
    # ==============================================================================
    Write-Host "`n--------------------------------------------------" -ForegroundColor Cyan
    Write-Host " 4. Ejecutando compilación con PyInstaller..." -ForegroundColor Cyan
    Write-Host "--------------------------------------------------" -ForegroundColor Cyan

    & $pythonVenv -m PyInstaller --noconfirm "$PSScriptRoot\run_app.spec"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: PyInstaller falló durante la generación de los archivos." -ForegroundColor Red
        return
    }

    # ==============================================================================
    # 5. VERIFICACIÓN FINAL
    # ==============================================================================
    $exeGenerado = "$PSScriptRoot\dist\SistemaDesvinculaciones\SistemaDesvinculaciones.exe"

    if (Test-Path $exeGenerado) {
        Write-Host "`n==================================================" -ForegroundColor Green
        Write-Host " ¡Proceso completado exitosamente!" -ForegroundColor Green
        Write-Host " Ejecutable listo en: $exeGenerado" -ForegroundColor White
        Write-Host "==================================================" -ForegroundColor Green
    } else {
        Write-Host "`n==================================================" -ForegroundColor Red
        Write-Host " Ocurrió un error: No se encontró el archivo generado en $exeGenerado" -ForegroundColor Red
        return
    }
}
finally {
    try { Stop-Transcript } catch { }
}