param(
    [switch]$ListenOnNetwork
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot "venv\Scripts\python.exe"
$secretsFile = Join-Path $projectRoot ".streamlit\secrets.toml"

if (-not (Test-Path $python)) {
    throw "No existe el entorno Python: $python"
}
if (-not (Test-Path $secretsFile)) {
    throw "Configura .streamlit\secrets.toml usando web-secrets.example.toml antes de abrir el modo web."
}

$address = "127.0.0.1"
if ($ListenOnNetwork) {
    $address = "0.0.0.0"
    Write-Warning "El acceso por red sin proxy HTTPS solo debe usarse en una red privada de confianza."
}

$env:SISTEMA_WEB_MODE = "1"
if (-not $env:SISTEMA_DATA_DIR) {
    $env:SISTEMA_DATA_DIR = Join-Path $projectRoot "web-data"
}
if (-not $env:SISTEMA_GOOGLE_TOKEN_FILE) {
    $env:SISTEMA_GOOGLE_TOKEN_FILE = Join-Path $projectRoot "token.json"
}
if (-not $env:SISTEMA_GOOGLE_CREDENTIALS) {
    $env:SISTEMA_GOOGLE_CREDENTIALS = Join-Path $projectRoot "credentials.json"
}

Push-Location $projectRoot
try {
    & $python -m streamlit run web_app.py `
        --server.address=$address `
        --server.port=8501 `
        --server.enableCORS=true `
        --server.enableXsrfProtection=true `
        --server.maxUploadSize=200 `
        --browser.gatherUsageStats=false `
        --global.developmentMode=false
    if ($LASTEXITCODE -ne 0) {
        throw "Streamlit web terminó con código $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
