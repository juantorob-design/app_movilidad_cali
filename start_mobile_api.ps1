#!/usr/bin/env pwsh
# Inicia el API local usando credenciales y datos configurados fuera del repositorio.

$env:PYTHONPATH = $PSScriptRoot
$env:SISTEMA_GOOGLE_WEB_CLIENT_ID = if ($env:SISTEMA_GOOGLE_WEB_CLIENT_ID) {
    $env:SISTEMA_GOOGLE_WEB_CLIENT_ID
} else {
    '1019857870350-ccrqd53kcl0c6k799f0om2p5fnloviij.apps.googleusercontent.com'
}
$env:SISTEMA_WEB_OWNER_EMAIL = if ($env:SISTEMA_WEB_OWNER_EMAIL) {
    $env:SISTEMA_WEB_OWNER_EMAIL
} else {
    'juan.torob@cun.edu.co'
}
if ([string]::IsNullOrWhiteSpace($env:SISTEMA_GOOGLE_TOKEN_FILE)) {
    $env:SISTEMA_GOOGLE_TOKEN_FILE = Join-Path $PSScriptRoot 'token.json'
}
if ([string]::IsNullOrWhiteSpace($env:SISTEMA_SPREADSHEET_ID)) {
    $env:SISTEMA_SPREADSHEET_ID = '1oQ5GnxSj4_gGA-p2NjlN3o0uDOLaIELZu4gpohLK6Uo'
}

foreach ($name in @(
    'SISTEMA_GOOGLE_WEB_CLIENT_ID',
    'SISTEMA_WEB_OWNER_EMAIL',
    'SISTEMA_GOOGLE_TOKEN_FILE'
)) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "Falta configurar la variable de entorno requerida: $name"
    }
}

$python = Join-Path $PSScriptRoot 'venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'No se encontró el runtime Python 3.12 del OCR en venv\Scripts\python.exe.'
}
if (!(Test-Path -LiteralPath $env:SISTEMA_GOOGLE_TOKEN_FILE -PathType Leaf)) {
    throw 'SISTEMA_GOOGLE_TOKEN_FILE no apunta al token OAuth autorizado del programa.'
}

$host_ip = '127.0.0.1'
$port = 8000

Write-Host "Iniciando API móvil..."
Write-Host "URL: http://${host_ip}:$port"
Write-Host ""

& $python -m uvicorn mobile_api.main:app --host $host_ip --port $port --reload
