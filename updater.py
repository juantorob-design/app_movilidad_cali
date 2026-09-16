import os
import sys
import requests
import subprocess
import threading
import tempfile
from urllib.parse import urlparse

# Versión actual de la aplicación instalada
CURRENT_VERSION = "1.1.11"

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
        response = requests.get(VERSION_CHECK_URL, timeout=5)
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


def download_and_apply_update(download_url):
    """Descarga, instala con elevación y reinicia la aplicación actualizada."""
    if not download_url:
        return

    if not getattr(sys, 'frozen', False):
        return
    parsed_url = urlparse(download_url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.netloc.lower() not in {"github.com", "objects.githubusercontent.com"}
    ):
        raise ValueError("La URL de actualización no pertenece a GitHub.")

    instalador = os.path.join(
        tempfile.gettempdir(),
        f"SistemaDesvinculaciones-update-{os.getpid()}.exe",
    )
    script_actualizacion = os.path.join(
        tempfile.gettempdir(),
        f"SistemaDesvinculaciones-update-{os.getpid()}.ps1",
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

        script_content = f"""$ErrorActionPreference = 'Stop'
$installer = {_literal_powershell(instalador)}
$application = {_literal_powershell(ejecutable)}
Start-Sleep -Seconds 2
$arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS', '/RESTARTAPPLICATIONS')
$process = Start-Process -FilePath $installer -ArgumentList $arguments -Verb RunAs -Wait -PassThru
if ($process.ExitCode -ne 0) {{
    exit $process.ExitCode
}}
Start-Process -FilePath $application -WorkingDirectory (Split-Path -Parent $application)
Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
"""
        with open(script_actualizacion, "w", encoding="utf-8") as f:
            f.write(script_content)

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
        # El proceso auxiliar espera a que esta instancia libere sus archivos.
        os._exit(0)

    except (OSError, requests.RequestException):
        for ruta in (instalador, script_actualizacion):
            try:
                if os.path.exists(ruta):
                    os.remove(ruta)
            except OSError:
                continue