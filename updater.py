import os
import re
import shlex
import sys
import requests
import subprocess
import threading
import tempfile
import time
from urllib.parse import urlparse

# Versión actual de la aplicación instalada
CURRENT_VERSION = "1.1.18"

# GitHub Raw será la fuente pública de versiones cuando el repositorio se publique.
DEFAULT_VERSION_CHECK_URL = (
    "https://raw.githubusercontent.com/juantorob-design/"
    "app_movilidad_cali/main/version.json"
)
VERSION_CHECK_URL = os.environ.get(
    "SISTEMA_VERSION_CHECK_URL",
    DEFAULT_VERSION_CHECK_URL,
)

def obtener_ruta_ejecutable():
    """Obtiene la ruta absoluta del ejecutable principal de Windows."""
    if getattr(sys, 'frozen', False):
        # run_app cambia sys.argv para iniciar Streamlit; sys.executable
        # conserva la ruta del ejecutable principal.
        return os.path.abspath(sys.executable)
    return os.path.abspath(__file__)

def is_newer_version(remote_ver, current_ver):
    """Compara dos strings de versión semántica (ej: '1.1.0' > '1.0.0')."""
    def parse_ver(v):
        partes = str(v).strip().lower().lstrip("v").split(".")
        if not partes or any(not parte.isdigit() for parte in partes):
            raise ValueError("Versión inválida")
        return tuple(int(parte) for parte in partes)
    try:
        remoto = parse_ver(remote_ver)
        actual = parse_ver(current_ver)
        longitud = max(len(remoto), len(actual))
        return remoto + (0,) * (longitud - len(remoto)) > actual + (0,) * (longitud - len(actual))
    except (TypeError, ValueError):
        return False


def obtener_actualizacion_disponible():
    """Devuelve los datos de una versión nueva sin iniciar ninguna descarga."""
    if not VERSION_CHECK_URL:
        return None
    try:
        response = requests.get(
            VERSION_CHECK_URL,
            params={"_": str(int(time.time()))},
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        remote_version = data.get("version")
        if not remote_version or not is_newer_version(remote_version, CURRENT_VERSION):
            return None
        return {
            "version": str(remote_version),
            "download_url": data.get("download_url", ""),
            "changelog": data.get("changelog", "Sin notas de versión."),
        }
    except (requests.RequestException, ValueError, TypeError):
        return None


def check_for_updates(callback_notificacion=None):
    """
    Consulta la URL remota para verificar si existe una nueva versión.
    Permite un callback opcional para manejar la UI desde Streamlit.
    """
    if not VERSION_CHECK_URL:
        # Updates are opt-in until the public repository URL is configured.
        return

    actualizacion = obtener_actualizacion_disponible()
    if actualizacion:
        if callback_notificacion:
            callback_notificacion(
                actualizacion["version"],
                actualizacion["download_url"],
                actualizacion["changelog"],
            )
        else:
            prompt_user_to_update(
                actualizacion["version"],
                actualizacion["download_url"],
                actualizacion["changelog"],
            )

def prompt_user_to_update(remote_version, download_url, changelog):
    """Muestra una ventana emergente de confirmación utilizando la API de Windows/Tkinter en hilo seguro."""
    def _mostrar_dialogo():
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            
            msg = f"Nueva versión {remote_version} disponible.\n\nNovedades:\n{changelog}\n\n¿Deseas descargar e instalar la actualización ahora?"
            if messagebox.askyesno("Actualización del Sistema", msg):
                download_and_apply_update(download_url)
            root.destroy()
        except Exception:
            pass

    threading.Thread(target=_mostrar_dialogo, daemon=True).start()


def _literal_powershell(valor):
    """Escapa una ruta para usarla como literal de cadena en PowerShell."""
    return "'" + str(valor).replace("'", "''") + "'"


def _normalizar_uninstall_string(uninstall_string):
    """Normaliza una cadena como 'C:\\ruta\\unins.exe /VERYSILENT' a exe + argumentos."""
    cadena = (uninstall_string or "").strip()
    if not cadena:
        return "", []
    if cadena.startswith('"'):
        partes = shlex.split(cadena, posix=False)
        if partes:
            return partes[0].strip('"'), partes[1:]
        return cadena.strip('"'), []
    match = re.match(r'^("?[^"]+"?)(?:\s+(.*))?$', cadena)
    if not match:
        return cadena, []
    exe = match.group(1).strip('"')
    args_str = (match.group(2) or "").strip()
    args = shlex.split(args_str, posix=False) if args_str else []
    return exe, args


def buscar_desinstalador_instalado():
    """Busca la entrada de desinstalación para la app en HKLM/HKCU."""
    script = r"""
    $roots = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        foreach ($key in Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue) {
            $displayName = $key.GetValue('DisplayName')
            $uninstallString = $key.GetValue('UninstallString')
            if ($null -ne $displayName -and $displayName -match 'Sistema de Desvinculaciones|SistemaDesvinculaciones' -and $uninstallString) {
                $uninstallString | Write-Output
                return
            }
        }
    }
    $installRoot = Join-Path ${env:ProgramFiles} 'SistemaDesvinculaciones'
    $primaryUninstaller = Join-Path $installRoot 'unins000.exe'
    if (Test-Path -LiteralPath $primaryUninstaller) {
        $primaryUninstaller | Write-Output
    }
    """
    try:
        resultado = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if resultado.returncode != 0:
            return ""
        salida = resultado.stdout.strip()
        if not salida:
            return ""
        return salida.splitlines()[0].strip()
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""


def download_and_apply_update(download_url):
    """Actualiza solo {app}; los modelos nativos de Ollama quedan intactos."""
    if not download_url:
        return

    if not getattr(sys, "frozen", False):
        raise RuntimeError("La actualización automática solo está disponible en el instalador de Windows.")
    parsed_url = urlparse(download_url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.netloc.lower() not in {"github.com", "objects.githubusercontent.com"}
    ):
        raise ValueError("La URL de actualización no pertenece a GitHub.")

    carpeta_temporal = os.path.abspath(tempfile.gettempdir())
    instalador = os.path.join(
        carpeta_temporal,
        f"SistemaDesvinculaciones-update-{os.getpid()}.exe",
    )
    script_actualizacion = os.path.join(
        carpeta_temporal,
        f"SistemaDesvinculaciones-bootstrap-{os.getpid()}.ps1",
    )
    ejecutable = obtener_ruta_ejecutable()

    try:
        response = requests.get(download_url, stream=True, timeout=60)
        response.raise_for_status()
        tamano_descargado = 0
        with open(instalador, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    tamano_descargado += len(chunk)
        if tamano_descargado == 0:
            raise OSError("El instalador descargado está vacío.")

        desinstalador = buscar_desinstalador_instalado()
        if not desinstalador:
            desinstalador = os.path.join(os.path.dirname(ejecutable), "unins000.exe")

        exe_uninstalar, args_extra = _normalizar_uninstall_string(desinstalador)
        if exe_uninstalar and os.path.exists(exe_uninstalar):
            uninstall_args = [*args_extra, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART']
            if not args_extra:
                uninstall_args = ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART']
        else:
            exe_uninstalar = ""
            uninstall_args = []

        script_content = f"""$ErrorActionPreference = 'Stop'
$installer = {_literal_powershell(instalador)}
$application = {_literal_powershell(ejecutable)}
$uninstallExecutable = { _literal_powershell(exe_uninstalar) if exe_uninstalar else "''" }
$uninstallArgs = @({", ".join(f"{_literal_powershell(arg)}" for arg in uninstall_args) if uninstall_args else ""})
Start-Sleep -Seconds 2
if ($uninstallExecutable -and (Test-Path -LiteralPath $uninstallExecutable)) {{
    $uninstallProcess = Start-Process -FilePath $uninstallExecutable -ArgumentList $uninstallArgs -Verb RunAs -Wait -PassThru
    if ($null -ne $uninstallProcess -and $uninstallProcess.ExitCode -ne 0) {{
        exit $uninstallProcess.ExitCode
    }}
}}
$installArguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS', '/RESTARTAPPLICATIONS')
$process = Start-Process -FilePath $installer -ArgumentList $installArguments -Verb RunAs -Wait -PassThru
if ($null -ne $process -and $process.ExitCode -ne 0) {{
    exit $process.ExitCode
}}
if (-not (Test-Path -LiteralPath $application)) {{
    exit 1
}}
Start-Process -FilePath $application -WorkingDirectory (Split-Path -Parent $application)
Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
"""
        with open(script_actualizacion, "w", encoding="utf-8") as f:
            f.write(script_content)

        # Etapa 1: el proceso actual solo deja preparado el bootstrapper.
        # Etapa 2: PowerShell espera, eleva y reemplaza la instalación.
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                script_actualizacion,
            ],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(2)
        # os._exit evita que Streamlit mantenga módulos o archivos abiertos.
        os._exit(0)

    except (OSError, requests.RequestException):
        for ruta in (instalador, script_actualizacion):
            try:
                if os.path.exists(ruta):
                    os.remove(ruta)
            except OSError:
                continue