$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root "venv\Scripts\python.exe"
$dashboard = Join-Path $root "presentacion_dashboard.py"
$port = 8510

if (-not (Test-Path -LiteralPath $python)) {
    throw "No se encontró el entorno virtual en $python"
}
if (-not (Test-Path -LiteralPath $dashboard)) {
    throw "No se encontró el dashboard en $dashboard"
}

Start-Process -FilePath $python -ArgumentList @(
    "-m", "streamlit", "run", $dashboard,
    "--server.port=$port",
    "--server.headless=true",
    "--browser.gatherUsageStats=false",
    "--browser.serverAddress=127.0.0.1",
    "--browser.serverPort=$port"
)
Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:$port"
