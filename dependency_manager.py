"""Preparación segura de Ollama y del modelo local.

No instala software durante el arranque. Las operaciones de instalación y
descarga requieren una acción explícita del usuario y verifican el manifiesto
antes de ejecutar un instalador externo.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests


APP_DATA_DIR = Path(
    os.environ.get(
        "LOCALAPPDATA",
        str(Path.home() / "AppData" / "Local"),
    )
) / "SistemaDesvinculaciones"
BIN_DIR = APP_DATA_DIR / "bin"
OLLAMA_MODEL = os.environ.get("SISTEMA_OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_MANIFEST_URL = os.environ.get("SISTEMA_OLLAMA_MANIFEST_URL", "").strip()
ALLOWED_MANIFEST_HOSTS = {
    "raw.githubusercontent.com",
    "github.com",
}


def buscar_ollama() -> str | None:
    """Encuentra Ollama en PATH o en sus ubicaciones habituales de Windows."""
    candidatos = [
        shutil.which("ollama"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Ollama", "ollama.exe"),
        str(BIN_DIR / "ollama.exe"),
    ]
    return next((ruta for ruta in candidatos if ruta and os.path.isfile(ruta)), None)


def obtener_modelos_ollama(ollama_path: str | None = None) -> list[str]:
    """Obtiene los modelos locales sin descargar ni modificar nada."""
    ejecutable = ollama_path or buscar_ollama()
    if not ejecutable:
        return []
    try:
        resultado = subprocess.run(
            [ejecutable, "list"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if resultado.returncode != 0:
        return []
    return [
        linea.split()[0]
        for linea in resultado.stdout.splitlines()[1:]
        if linea.split()
    ]


def descargar_modelo(
    modelo: str = OLLAMA_MODEL,
    progreso: Callable[[str], None] | None = None,
) -> None:
    """Descarga un modelo tras una acción explícita del usuario."""
    ejecutable = buscar_ollama()
    if not ejecutable:
        raise FileNotFoundError("Ollama no está instalado en este equipo.")
    proceso = subprocess.Popen(
        [ejecutable, "pull", modelo],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proceso.stdout:
        for linea in proceso.stdout:
            if progreso:
                progreso(linea.strip())
    codigo = proceso.wait()
    if codigo != 0:
        raise RuntimeError(f"Ollama no pudo descargar el modelo {modelo}.")


def cargar_manifesto_remoto(url: str = OLLAMA_MANIFEST_URL) -> dict:
    """Carga un manifiesto HTTPS explícitamente configurado y permitido."""
    if not url:
        raise ValueError("No hay manifiesto de motores configurado.")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_MANIFEST_HOSTS:
        raise ValueError("El manifiesto debe estar en GitHub mediante HTTPS.")
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        manifiesto = response.json()
    except (requests.RequestException, ValueError) as error:
        raise RuntimeError(f"No fue posible leer el manifiesto de motores: {error}") from error
    if not isinstance(manifiesto, dict):
        raise ValueError("El manifiesto de motores no tiene formato de objeto.")
    return manifiesto


def instalar_ollama_desde_manifesto(
    manifiesto: dict,
    progreso: Callable[[str], None] | None = None,
) -> str:
    """Descarga, verifica e instala Ollama tras confirmación del usuario."""
    instalador = manifiesto.get("ollama_installer") or {}
    url = str(instalador.get("url") or "").strip()
    esperado = str(instalador.get("sha256") or "").strip().lower()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"ollama.com", "github.com"}:
        raise ValueError("La descarga de Ollama no pertenece a un dominio permitido.")
    if len(esperado) != 64 or any(caracter not in "0123456789abcdef" for caracter in esperado):
        raise ValueError("El manifiesto no contiene un SHA-256 válido para Ollama.")
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    temporal = Path(tempfile.mkstemp(prefix="ollama-", suffix=".exe", dir=BIN_DIR)[1])
    try:
        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            digest = hashlib.sha256()
            with temporal.open("wb") as destino:
                for bloque in response.iter_content(chunk_size=1024 * 1024):
                    if bloque:
                        digest.update(bloque)
                        destino.write(bloque)
        if digest.hexdigest().lower() != esperado:
            raise ValueError("La firma SHA-256 del instalador de Ollama no coincide.")
        if progreso:
            progreso("Instalador verificado. Ejecutando instalación de Ollama...")
        resultado = subprocess.run(
            [str(temporal), "/silent"],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if resultado.returncode != 0:
            raise RuntimeError(
                f"La instalación de Ollama terminó con código {resultado.returncode}."
            )
        return str(temporal)
    except (OSError, requests.RequestException, subprocess.SubprocessError) as error:
        raise RuntimeError(f"No fue posible instalar Ollama: {error}") from error
    finally:
        try:
            temporal.unlink(missing_ok=True)
        except OSError:
            pass
