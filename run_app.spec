# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

block_cipher = None

# Recolectar datos de Streamlit, PyWebView y Google API
datas = collect_data_files('streamlit')
datas += collect_data_files('webview')
datas += collect_data_files('googleapiclient')

# Incluir metadatos de paquetes requeridos
datas += copy_metadata('streamlit')
datas += copy_metadata('pywebview')
datas += copy_metadata('google-api-python-client')

# Archivos estáticos indispensables del proyecto
archivos_proyecto = [
    ('app_6.py', '.'),
    ('updater.py', '.'),
    ('images', 'images'),
]

# El cliente OAuth de escritorio no contiene tokens ni datos de usuarios.
# Se empaqueta para que una instalación nueva pueda iniciar la autorización.
if os.path.exists('credentials.json'):
    archivos_proyecto.append(('credentials.json', '.'))

# Incluir archivos opcionales si existen en la raíz
if os.path.exists('Icono.ico'):
    archivos_proyecto.append(('Icono.ico', '.'))

if os.path.exists('.streamlit'):
    archivos_proyecto.append(('.streamlit', '.streamlit'))

datas += archivos_proyecto

# Importaciones ocultas para evitar errores de módulos no encontrados en tiempo de ejecución
hiddenimports = [
    'streamlit',
    'streamlit.web.cli',
    'streamlit.runtime.caching',
    'webview',
    'PySide6',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'openpyxl',
    'openpyxl.cell',
    'openpyxl.styles',
    'pandas',
    'google.oauth2',
    'google.oauth2.credentials',
    'google.auth',
    'google.auth.transport.requests',
    'google_auth_oauthlib',
    'google_auth_oauthlib.flow',
    'googleapiclient',
    'googleapiclient.discovery',
    'googleapiclient.errors',
    'googleapiclient.http',
    'clr',
] + collect_submodules('streamlit') + collect_submodules('webview') + collect_submodules('openpyxl') + collect_submodules('googleapiclient') + collect_submodules('google_auth_oauthlib') + collect_submodules('PySide6')

# Resolver la ruta del icono para el ejecutable (.exe)
icono_path = 'Icono.ico' if os.path.exists('Icono.ico') else os.path.join('images', 'logo.ico')
icono_final = icono_path if os.path.exists(icono_path) else None

a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SistemaDesvinculaciones',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icono_final,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SistemaDesvinculaciones',
)