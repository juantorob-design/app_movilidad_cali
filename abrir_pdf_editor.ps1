$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}
$port = 8510
Start-Process -FilePath $python -ArgumentList @(
    "-m", "streamlit", "run", (Join-Path $root "pdf_editor.py"),
    "--server.headless=true",
    "--browser.gatherUsageStats=false",
    "--browser.serverAddress=127.0.0.1",
    "--server.port=$port"
)
Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:$port"
