param(
    [string]$ApiBaseUrl = "https://sistema-desvinculaciones-api.onrender.com/",
    [string]$GoogleWebClientId = "1019857870350-ccrqd53kcl0c6k799f0om2p5fnloviij.apps.googleusercontent.com"
)

$ErrorActionPreference = "Stop"

$signingDirectory = Join-Path $env:LOCALAPPDATA "SistemaDesvinculaciones\release-signing"
$keystorePath = Join-Path $signingDirectory "release-key.p12"
$passwordPath = Join-Path $signingDirectory "release-password.dpapi"

if (-not $env:ANDROID_HOME) {
    $defaultSdkPath = Join-Path $env:LOCALAPPDATA "Android\Sdk"
    if (Test-Path $defaultSdkPath -PathType Container) {
        $env:ANDROID_HOME = $defaultSdkPath
        $env:ANDROID_SDK_ROOT = $defaultSdkPath
    }
}

if (-not (Test-Path $keystorePath -PathType Leaf)) {
    throw "Release keystore not found: $keystorePath"
}

if (-not (Test-Path $passwordPath -PathType Leaf)) {
    throw "Protected signing password not found: $passwordPath"
}

$securePassword = ConvertTo-SecureString -String (Get-Content $passwordPath -Raw).Trim()
$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)

try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    $env:ANDROID_RELEASE_STORE_FILE = $keystorePath
    $env:ANDROID_RELEASE_KEY_ALIAS = "mobile-release"
    $env:ANDROID_RELEASE_STORE_PASSWORD = $password
    $env:ANDROID_RELEASE_KEY_PASSWORD = $password

    Push-Location $PSScriptRoot
    try {
        & .\gradlew.bat assembleRelease `
            "-PAPI_BASE_URL=$ApiBaseUrl" `
            "-PGOOGLE_WEB_CLIENT_ID=$GoogleWebClientId"
        if ($LASTEXITCODE -ne 0) {
            throw "Gradle release build failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    $password = $null
    Remove-Item Env:ANDROID_RELEASE_STORE_FILE -ErrorAction SilentlyContinue
    Remove-Item Env:ANDROID_RELEASE_KEY_ALIAS -ErrorAction SilentlyContinue
    Remove-Item Env:ANDROID_RELEASE_STORE_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:ANDROID_RELEASE_KEY_PASSWORD -ErrorAction SilentlyContinue
}
