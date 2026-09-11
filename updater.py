import os
import sys
import requests
import subprocess
import threading
import tempfile

# Versión actual de la aplicación instalada
CURRENT_VERSION = "1.0.4"

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
        return os.path.abspath(sys.argv[0])
    return os.path.abspath(__file__)

def is_newer_version(remote_ver, current_ver):
    """Compara dos strings de versión semántica (ej: '1.1.0' > '1.0.0')."""
    def parse_ver(v):
        return [int(x) for x in str(v).replace('v', '').split('.')]
    try:
        return parse_ver(remote_ver) > parse_ver(current_ver)
    except Exception:
        return False

def check_for_updates(callback_notificacion=None):
    """
    Consulta la URL remota para verificar si existe una nueva versión.
    Permite un callback opcional para manejar la UI desde Streamlit.
    """
    if not VERSION_CHECK_URL:
        # Updates are opt-in until the public repository URL is configured.
        return

    try:
        response = requests.get(VERSION_CHECK_URL, timeout=5)
        if response.status_code == 200:
            data = response.json()
            remote_version = data.get("version")
            download_url = data.get("download_url")
            changelog = data.get("changelog", "Sin notas de versión.")

            if remote_version and is_newer_version(remote_version, CURRENT_VERSION):
                if callback_notificacion:
                    callback_notificacion(remote_version, download_url, changelog)
                else:
                    prompt_user_to_update(remote_version, download_url, changelog)
    except Exception as e:
        # Silencia errores de conexión para no interferir con el inicio del sistema
        pass

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

def download_and_apply_update(download_url):
    """Descarga el instalador y deja que Inno Setup actualice la instalación."""
    if not download_url:
        return

    if not getattr(sys, 'frozen', False):
        return

    instalador = os.path.join(
        tempfile.gettempdir(),
        f"SistemaDesvinculaciones-update-{os.getpid()}.exe",
    )
    script_limpieza = os.path.join(
        tempfile.gettempdir(),
        f"SistemaDesvinculaciones-update-{os.getpid()}.cmd",
    )

    try:
        response = requests.get(download_url, stream=True, timeout=60)
        response.raise_for_status()
        with open(instalador, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        bat_content = f"""@echo off
start "" /wait "{instalador}" /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS
del /f /q "{instalador}" >nul 2>&1
del /f /q "%~f0" >nul 2>&1
"""
        with open(script_limpieza, "w", encoding="utf-8") as f:
            f.write(bat_content)

        subprocess.Popen(
            ["cmd.exe", "/c", script_limpieza],
            creationflags=0x08000000,
        )
        sys.exit(0)

    except (OSError, requests.RequestException):
        for ruta in (instalador, script_limpieza):
            try:
                if os.path.exists(ruta):
                    os.remove(ruta)
            except OSError:
                continue