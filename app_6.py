import os
import sys
import shutil
import subprocess

# --- INYECCIÓN DE RUTAS Y ENTORNO PARA PYINSTALLER ---
if getattr(sys, 'frozen', False):
    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)
    internal_dir = os.path.join(base_dir, '_internal')
    if os.path.exists(internal_dir) and internal_dir not in sys.path:
        sys.path.insert(0, internal_dir)
    os.environ["PYTHONPATH"] = base_dir + (f";{internal_dir}" if os.path.exists(internal_dir) else "") + os.pathsep + os.environ.get("PYTHONPATH", "")

import json
import datetime
import math
import base64
import io
import hashlib
import hmac
import re
import unicodedata
import secrets
import tempfile
import threading
import webbrowser
from functools import lru_cache
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import quote, urlencode, urlparse, parse_qs

import streamlit as st
import streamlit.components.v1 as components
try:
    from streamlit_pdf import pdf_viewer
except ImportError:
    pdf_viewer = None
import pandas as pd
import requests
from dotenv import load_dotenv
import document_rules as _document_rules
from document_rules import (
    clasificar_tipo_caso,
    clasificar_tipo_documento,
    componentes_ubicacion,
    fecha_para_nombre_carpeta,
    nombre_carpeta_expediente,
    nombre_pdf_expediente,
    normalizar_errores_ocr,
    normalizar_tipo_documental,
    tipos_documentales_detectados,
)
try:
    import webview
except ImportError:
    webview = None

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    PdfReader = None
    PdfWriter = None
try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None

try:
    from rapidocr_onnxruntime import RapidOCR
except (ImportError, ModuleNotFoundError):
    RapidOCR = None

try:
    import onnxruntime as ort
except (ImportError, ModuleNotFoundError):
    ort = None
try:
    from local_ai_service import (
        OLLAMA_MODEL,
        OLLAMA_TEXT_MODEL,
        OLLAMA_VISION_MODEL,
        OLLAMA_DOWNLOAD_URL,
        analizar_expediente_local,
        analizar_paginas_local,
        analisis_a_markdown,
        campos_formulario_desde_ia,
        ollama_disponible,
    )
except ImportError:
    OLLAMA_MODEL = "qwen2.5:7b"
    OLLAMA_TEXT_MODEL = OLLAMA_MODEL
    OLLAMA_VISION_MODEL = OLLAMA_MODEL
    OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
    analizar_expediente_local = None
    analizar_paginas_local = None
    analisis_a_markdown = None
    campos_formulario_desde_ia = lambda resultado: {}
    ollama_disponible = lambda: False
try:
    from dependency_manager import (
        OLLAMA_MODEL as OLLAMA_REQUIRED_MODEL,
        buscar_ollama,
        descargar_modelo,
        descargar_modelo_en_segundo_plano,
        estado_descarga_modelo,
        iniciar_servicio_ollama,
        obtener_modelos_ollama,
    )
except ImportError:
    OLLAMA_REQUIRED_MODEL = OLLAMA_MODEL
    buscar_ollama = lambda: None
    descargar_modelo = None
    descargar_modelo_en_segundo_plano = lambda *args, **kwargs: False
    estado_descarga_modelo = lambda: {"running": False, "message": "", "error": ""}
    iniciar_servicio_ollama = lambda: False
    obtener_modelos_ollama = lambda: []

_ocr_engine = None
_ocr_last_error = ""
_ocr_cache_writes_pending = 0
# Los expedientes recibidos son escaneos y pueden superar ampliamente ocho
# páginas. Limitar el OCR dejaba sin leer la mayor parte del expediente.
OCR_MAX_PAGES = None
# 1.2x conserva una resolución suficiente para formularios escaneados y
# reduce el costo del OCR frente al renderizado anterior de 1.5x.
OCR_RENDER_SCALE = 1.2
OCR_CACHE_VERSION = "3"
BLANK_PAGE_DARK_PIXEL_RATIO = 0.005
_ocr_persistent_cache = None


def proveedores_ocr_disponibles():
    """Devuelve los proveedores ONNX disponibles, sin exigir permisos de administrador."""
    if ort is None:
        return []
    try:
        return list(ort.get_available_providers())
    except (AttributeError, RuntimeError):
        return []


def configuracion_ocr_local():
    """Selecciona aceleración GPU compatible y conserva CPU como respaldo."""
    proveedores = proveedores_ocr_disponibles()
    if "CUDAExecutionProvider" in proveedores:
        return {"use_cuda": True, "use_dml": False}
    if "DmlExecutionProvider" in proveedores:
        return {"use_cuda": False, "use_dml": True}
    return {"use_cuda": False, "use_dml": False}


def estado_ocr_local():
    proveedores = proveedores_ocr_disponibles()
    if "CUDAExecutionProvider" in proveedores:
        return "GPU NVIDIA (CUDA)"
    if "DmlExecutionProvider" in proveedores:
        return "GPU Windows (DirectML)"
    if "CPUExecutionProvider" in proveedores:
        return "CPU local"
    return "No disponible"


def crear_motor_ocr():
    if RapidOCR is None:
        return None
    configuracion = configuracion_ocr_local()
    try:
        return RapidOCR(**configuracion)
    except (TypeError, RuntimeError, ValueError):
        if configuracion.get("use_dml") or configuracion.get("use_cuda"):
            return RapidOCR(use_cuda=False, use_dml=False)
        raise

try:
    from updater import obtener_actualizacion_disponible, download_and_apply_update
except ImportError:
    def obtener_actualizacion_disponible():
        return None

    def download_and_apply_update(download_url):
        return None

load_dotenv()

def dir_recursos():
    """Archivos estáticos empaquetados, como imágenes e iconos."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.abspath(".")

def dir_datos():
    """Datos que se escriben (base local y token OAuth). En el .exe no pueden ir dentro del paquete."""
    if getattr(sys, 'frozen', False):
        ruta = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "SistemaDesvinculaciones")
        os.makedirs(ruta, exist_ok=True)
        return ruta
    return os.path.abspath(".")

def resolver_ruta(ruta_relativa):
    return os.path.join(dir_recursos(), ruta_relativa)

def resolver_dato(ruta_relativa):
    return os.path.join(dir_datos(), ruta_relativa)


def ruta_editor_pdf():
    """Obtiene el editor PDF integrado en la instalación, si existe."""
    if getattr(sys, "frozen", False):
        candidato = os.path.join(
            os.path.dirname(sys.executable),
            "EditorPDFLocal",
            "EditorPDFLocal.exe",
        )
        if os.path.isfile(candidato):
            return candidato
    candidato = os.path.join(os.path.abspath("."), "dist_pdf_editor", "EditorPDFLocal", "EditorPDFLocal.exe")
    return candidato if os.path.isfile(candidato) else ""


def abrir_editor_pdf():
    """Abre el editor PDF local sin bloquear la aplicación principal."""
    ruta = ruta_editor_pdf()
    if not ruta:
        raise FileNotFoundError(
            "El Editor PDF local no está incluido en esta instalación."
        )
    subprocess.Popen(
        [ruta],
        cwd=os.path.dirname(ruta),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def inicializar_memoria_local():
    """Prepara la memoria local usada por OCR y datos de la instalación."""
    carpeta = dir_datos()
    os.makedirs(carpeta, exist_ok=True)
    ruta_cache = os.path.join(carpeta, "ocr_cache.json")
    if not os.path.exists(ruta_cache):
        temporal = f"{ruta_cache}.tmp"
        try:
            with open(temporal, "w", encoding="utf-8") as archivo:
                json.dump({}, archivo)
            os.replace(temporal, ruta_cache)
        except OSError:
            if os.path.exists(temporal):
                os.remove(temporal)


inicializar_memoria_local()


def preparar_ollama_en_segundo_plano():
    """Inicia Ollama y prepara el modelo requerido sin bloquear Streamlit."""
    if not buscar_ollama():
        return
    if not iniciar_servicio_ollama():
        return
    if OLLAMA_REQUIRED_MODEL in obtener_modelos_ollama():
        return
    descargar_modelo_en_segundo_plano(OLLAMA_REQUIRED_MODEL)


threading.Thread(
    target=preparar_ollama_en_segundo_plano,
    name="ollama-setup",
    daemon=True,
).start()


def obtener_ruta_imagen(nombre_archivo):
    return resolver_ruta(os.path.join("images", nombre_archivo))

def get_image_base64(ruta):
    if os.path.exists(ruta):
        try:
            with open(ruta, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode()
                ext = os.path.splitext(ruta)[1].replace(".", "").lower()
                if ext == "svg":
                    ext = "svg+xml"
                return f"data:image/{ext};base64,{encoded_string}"
        except Exception:
            return ""
    return ""

def abrir_en_navegador(url, descripcion):
    """Abre una página web dentro de una ventana administrada por la aplicación."""
    try:
        if webview is not None:
            webview.create_window(
                descripcion,
                url=url,
                maximized=True,
                resizable=True,
            )
            st.toast(f"{descripcion} se abrió dentro de la aplicación.", icon=":material/open_in_new:")
            return
        webbrowser.open_new_tab(url)
        st.warning(f"{descripcion} se abrió en el navegador externo porque WebView2 no está disponible.")
    except Exception as error:
        st.error(f"No fue posible abrir {descripcion} dentro de la aplicación: {error}")

def render_image_action(img_path, label, href, target="_self", external=False):
    if not os.path.exists(img_path):
        return
    encoded = get_image_base64(img_path)
    external_attrs = f'href="{href}" target="{target}" rel="noopener"'
    st.markdown(
        f'<a class="action-tile" {external_attrs}>'
        f'<img src="{encoded}" alt="{label}"><span>{label}</span></a>',
        unsafe_allow_html=True,
    )

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="Secretaría de Tránsito y Transporte - Desvinculaciones",
    page_icon=resolver_ruta("icon.ico"),
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- VERIFICACIÓN DE ACTUALIZACIONES ---
if 'updater_checked' not in st.session_state:
    st.session_state.updater_checked = True
    st.session_state.actualizacion_disponible = obtener_actualizacion_disponible()
else:
    actualizacion_guardada = st.session_state.get("actualizacion_disponible")
    if actualizacion_guardada:
        try:
            from updater import is_newer_version, CURRENT_VERSION
            if not is_newer_version(
                actualizacion_guardada.get("version", ""),
                CURRENT_VERSION,
            ):
                st.session_state.actualizacion_disponible = None
        except (ImportError, TypeError, ValueError):
            st.session_state.actualizacion_disponible = None

SUPER_ADMIN_EMAIL = "juan.torob@cun.edu.co"
SUPABASE_URL = os.environ.get(
    "SUPABASE_URL",
    "https://ktgogijxtsidctkidrav.supabase.co",
).rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()
SUPABASE_OAUTH_REDIRECT = os.environ.get(
    "SUPABASE_OAUTH_REDIRECT",
    "http://127.0.0.1:8765/oauth/callback",
).strip()
DRIVE_FOLDER_ID = os.environ.get(
    "SISTEMA_DRIVE_FOLDER_ID",
    "1wA5LrPmk5vcgG3YP2LgROeNvcupJK2Gs",
).strip()
DRIVE_REQUEST_FOLDER_NAME = "Peticion"
DRIVE_UNLINKED_FOLDER_NAME = "Por_vincular"
SUBCARPETAS_DOCUMENTALES = (
    "peticion",
    "consulta",
    "resolucion resuelve",
    "citacion",
    "notificacion",
    "recurso",
    "constancia de ejecutoria",
    "remision",
    "desistimiento",
)
SPREADSHEET_CONFIG_FILE = resolver_dato("sistema_spreadsheet_id.json")
SPREADSHEET_ID = os.environ.get(
    "SISTEMA_SPREADSHEET_ID",
    "1oQ5GnxSj4_gGA-p2NjlN3o0uDOLaIELZu4gpohLK6Uo",
).strip()
if not SPREADSHEET_ID:
    try:
        with open(SPREADSHEET_CONFIG_FILE, "r", encoding="utf-8") as archivo:
            config = json.load(archivo)
            SPREADSHEET_ID = str(config.get("spreadsheet_id", "")).strip()
    except (OSError, ValueError, TypeError):
        SPREADSHEET_ID = ""
SHEET_URL = (
    f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"
    if SPREADSHEET_ID
    else "https://docs.google.com/spreadsheets/create"
)
HISTORICO_FILENAME = "BD_DESVINCULACIONES ADMINISTRATIVAS.xlsx"


def guardar_spreadsheet_id(id_hoja):
    if not id_hoja:
        return
    try:
        os.makedirs(os.path.dirname(SPREADSHEET_CONFIG_FILE), exist_ok=True)
        with open(SPREADSHEET_CONFIG_FILE, "w", encoding="utf-8") as archivo:
            json.dump({"spreadsheet_id": id_hoja}, archivo, ensure_ascii=False, indent=2)
        os.environ["SISTEMA_SPREADSHEET_ID"] = id_hoja
    except OSError:
        pass


def obtener_hoja_registro(service, spreadsheet_id=None):
    """Devuelve la hoja operacional activa; prioriza tabla_2 y crea una si no existe."""
    if not service:
        return "tabla_2"
    target_id = spreadsheet_id or SPREADSHEET_ID
    if not target_id:
        return "tabla_2"
    try:
        metadata = service.spreadsheets().get(
            spreadsheetId=target_id,
            fields="sheets(properties(sheetId,title))",
        ).execute()
        hojas = metadata.get("sheets", [])
        nombres = {
            hoja.get("properties", {}).get("title", "").strip().lower():
            hoja.get("properties", {}).get("title", "").strip()
            for hoja in hojas
            if hoja.get("properties", {}).get("title", "").strip()
        }
        if "tabla_2" in nombres:
            return nombres["tabla_2"]
        if "bd_desv" in nombres:
            return nombres["bd_desv"]
        service.spreadsheets().batchUpdate(
            spreadsheetId=target_id,
            body={
                "requests": [{
                    "addSheet": {
                        "properties": {
                            "title": "tabla_2",
                            "gridProperties": {"frozenRowCount": 1},
                        }
                    }
                }]
            },
        ).execute()
        return "tabla_2"
    except Exception:
        return "tabla_2"


def rango_hoja_registro(service, columnas="A:Z", spreadsheet_id=None):
    nombre_hoja = obtener_hoja_registro(service, spreadsheet_id)
    titulo_seguro = nombre_hoja.replace("'", "''")
    return f"'{titulo_seguro}'!{columnas}"


def asegurador_registro_hoja(service, spreadsheet_id=None):
    if not service:
        return False
    target_id = spreadsheet_id or SPREADSHEET_ID
    if not target_id:
        return False
    try:
        hoja_bd = obtener_hoja_registro(service, target_id)
        rango = rango_hoja_registro(service, "A1:AZ1", target_id)
        valores = service.spreadsheets().values().get(
            spreadsheetId=target_id,
            range=rango,
        ).execute().get("values", [])
        asegurar_dimension_grid(
            service,
            target_id,
            hoja_bd,
            filas=1000,
            columnas=max(len(COLUMNAS_SHEET_OFICIALES), 43),
        )
        if valores and any(str(celda).strip() for celda in valores[0]):
            encabezados = [normalizar_campo_sheet(valor) for valor in valores[0]]
            if any(clave in encabezados for clave in ("FECHASOLICITUD", "PLACA", "RADPADRE")):
                return True
        service.spreadsheets().values().update(
            spreadsheetId=target_id,
            range=rango,
            valueInputOption="USER_ENTERED",
            body={"values": [COLUMNAS_SHEET_OFICIALES]},
        ).execute()
        return True
    except Exception:
        return False


def asegurar_dimension_grid(service, spreadsheet_id, nombre_hoja, filas, columnas):
    """Amplía la cuadrícula antes de escribir rangos nuevos."""
    if not service or not spreadsheet_id or not nombre_hoja:
        return
    metadata = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,title,gridProperties(rowCount,columnCount)))",
    ).execute()
    hoja = next(
        (
            item.get("properties", {})
            for item in metadata.get("sheets", [])
            if item.get("properties", {}).get("title") == nombre_hoja
        ),
        None,
    )
    if not hoja:
        return
    grid = hoja.get("gridProperties", {})
    cambios = {}
    if int(grid.get("rowCount") or 0) < filas:
        cambios["rowCount"] = filas
    if int(grid.get("columnCount") or 0) < columnas:
        cambios["columnCount"] = columnas
    if cambios:
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [{
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": hoja.get("sheetId"),
                            "gridProperties": cambios,
                        },
                        "fields": ",".join(f"gridProperties.{clave}" for clave in cambios),
                    }
                }]
            },
        ).execute()


def asegurar_hoja_bd_desv(service):
    """Asegura la hoja operativa del sistema; usa tabla_2 cuando existe y crea la hoja si hace falta."""
    global SPREADSHEET_ID, SHEET_URL
    if not service:
        return SPREADSHEET_ID or None
    try:
        if SPREADSHEET_ID:
            try:
                service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID, fields="spreadsheetId").execute()
                SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"
                if asegurador_registro_hoja(service, SPREADSHEET_ID):
                    return SPREADSHEET_ID
            except Exception:
                SPREADSHEET_ID = ""
        resultados = service.files().list(
            q="mimeType='application/vnd.google-apps.spreadsheet' and trashed = false and name contains 'BD_DESVINCULACIONES ADMINISTRATIVAS'",
            fields="files(id,name)",
            pageSize=20,
        ).execute().get("files", [])
        if resultados:
            SPREADSHEET_ID = resultados[0].get("id")
            guardar_spreadsheet_id(SPREADSHEET_ID)
            SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"
            asegurador_registro_hoja(service, SPREADSHEET_ID)
            return SPREADSHEET_ID
        nueva = service.spreadsheets().create(
            body={
                "properties": {
                    "title": "BD_DESVINCULACIONES ADMINISTRATIVAS",
                    "locale": "es_CO",
                    "timeZone": "America/Bogota",
                },
                "sheets": [{
                    "properties": {
                        "sheetId": 0,
                        "title": "tabla_2",
                        "gridProperties": {"frozenRowCount": 1},
                    }
                }],
            },
            fields="spreadsheetId,sheets(properties(sheetId,title))",
        ).execute()
        SPREADSHEET_ID = nueva.get("spreadsheetId")
        if SPREADSHEET_ID:
            guardar_spreadsheet_id(SPREADSHEET_ID)
            SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"
            asegurador_registro_hoja(service, SPREADSHEET_ID)
        return SPREADSHEET_ID
    except Exception as error:
        st.warning(f"No fue posible asegurar la hoja principal de Google Sheets: {error}")
        return SPREADSHEET_ID or None


# Actualiza la URL del navegador con el ID real de la hoja activa.
if SPREADSHEET_ID:
    SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"

# ARCHIVOS OFICIALES DEL PROYECTO
LOCAL_DB_FILE = resolver_dato("database_local.json")
# Google OAuth is optional. Keep credentials outside the source tree when possible.
CLIENT_SECRETS_FILE = os.environ.get(
    "SISTEMA_GOOGLE_CREDENTIALS",
    resolver_dato("credentials.json")
    if os.path.exists(resolver_dato("credentials.json"))
    else resolver_ruta("credentials.json"),
)
TOKEN_FILE = resolver_dato("token.json")
HISTORICO_FILE = os.environ.get(
    "SISTEMA_HISTORICO_FILE",
    resolver_ruta(os.path.join("respaldo", HISTORICO_FILENAME)),
)

_db_origen = resolver_ruta("database_local.json")
if not os.path.exists(LOCAL_DB_FILE) and os.path.exists(_db_origen):
    try:
        shutil.copy2(_db_origen, LOCAL_DB_FILE)
    except Exception:
        pass

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/gmail.send',
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

ROLES_DISPONIBLES = ["Sin Rol Asignado", "Visualizador", "Modificador", "Administrador", "Super Administrador"]
ESTADOS_DISPONIBLES = ["Pendiente", "Activo", "Inactivo"]
TIPOS_DOCUMENTALES = [
    "Expediente completo",
    "Solicitud",
    "Consulta QX",
    "Documento de identidad",
    "Tarjeta de propiedad",
    "Certificado o soporte",
    "Resolución",
    "Requerimiento",
    "Oficio de citación",
    "Notificación",
    "Notificación personal",
    "Notificación por aviso",
    "Notificación por publicación web",
    "Constancia de ejecutoria",
    "Recurso",
    "Resolución del recurso",
    "Remisión a registro",
    "Desistimiento",
    "Otro",
]
TIPOS_CASO = ["Detección automática", "Con recurso", "Sin recurso", "Desistimiento"]
DOCUMENTOS_REQUERIDOS_POR_CASO = {
    "Con recurso": {
        "Solicitud",
        "Consulta QX",
        "Resolución",
        "Oficio de citación",
        "Notificación",
        "Recurso",
        "Resolución del recurso",
        "Citación del recurso",
        "Notificación del recurso",
        "Constancia de ejecutoria",
        "Remisión a registro",
    },
    "Sin recurso": {
        "Solicitud",
        "Consulta QX",
        "Resolución",
        "Oficio de citación",
        "Notificación",
        "Constancia de ejecutoria",
        "Remisión a registro",
    },
    "Desistimiento": {"Solicitud", "Consulta QX", "Desistimiento"},
}

DOCUMENTOS_BASE_POR_CASO = {
    "Con recurso": (
        "Solicitud",
        "Consulta QX",
        "Resolución",
        "Oficio de citación",
        "Notificación",
        "Recurso",
        "Resolución del recurso",
        "Constancia de ejecutoria",
    ),
    "Sin recurso": (
        "Solicitud",
        "Consulta QX",
        "Resolución",
        "Oficio de citación",
        "Notificación",
        "Constancia de ejecutoria",
    ),
    "Desistimiento": ("Solicitud", "Consulta QX", "Desistimiento"),
}

CHECKLIST_GRUPOS_POR_CASO = {
    "Con recurso": (
        ("Solicitud",),
        ("Consulta QX",),
        ("Resolución", "Requerimiento"),
        ("Oficio de citación",),
        ("Notificación personal", "Notificación por aviso", "Notificación por publicación web", "Notificación"),
        ("Recurso",),
        ("Resolución del recurso",),
        ("Citación del recurso",),
        ("Notificación del recurso",),
        ("Constancia de ejecutoria",),
        ("Remisión a registro",),
    ),
    "Sin recurso": (
        ("Solicitud",),
        ("Consulta QX",),
        ("Resolución", "Requerimiento"),
        ("Oficio de citación",),
        ("Notificación personal", "Notificación por aviso", "Notificación por publicación web", "Notificación"),
        ("Constancia de ejecutoria",),
        ("Remisión a registro",),
    ),
    "Desistimiento": (
        ("Solicitud",),
        ("Consulta QX",),
        ("Desistimiento",),
    ),
}

ORDEN_DOCUMENTAL_PRELACION = (
    "Solicitud",
    "Consulta QX",
    "Resolución",
    "Requerimiento",
    "Desistimiento",
    "Oficio de citación",
    "Notificación personal",
    "Notificación por aviso",
    "Notificación por publicación web",
    "Notificación",
    "Recurso",
    "Resolución del recurso",
    "Citación del recurso",
    "Notificación del recurso",
    "Constancia de ejecutoria",
    "Remisión a registro",
)


def supabase_configurado():
    """Indica si la aplicación tiene configurado el cliente público de Supabase."""
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def supabase_auth_password(email, password):
    """Autentica una cuenta local en Supabase Auth y devuelve su sesión."""
    if not supabase_configurado():
        return None
    try:
        response = requests.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Content-Type": "application/json",
            },
            json={"email": email, "password": password},
            timeout=15,
        )
    except requests.RequestException as error:
        st.warning(f"No fue posible contactar el servidor de autorización: {error}")
        return None
    if response.status_code != 200:
        return None
    return response.json()


def supabase_registrar_password(email, password, nombre):
    """Registra una cuenta local en Supabase; el perfil queda pendiente por RLS."""
    if not supabase_configurado():
        return False
    try:
        response = requests.post(
            f"{SUPABASE_URL}/auth/v1/signup",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Content-Type": "application/json",
            },
            json={
                "email": email,
                "password": password,
                "data": {"full_name": nombre},
            },
            timeout=15,
        )
    except requests.RequestException as error:
        st.warning(f"No fue posible registrar la cuenta en el servidor: {error}")
        return False
    if response.status_code not in (200, 201):
        return False
    return True


def supabase_autenticar_google():
    """Completa Google OAuth en Supabase usando PKCE y un callback local."""
    if not supabase_configurado():
        return None
    parsed_redirect = urlparse(SUPABASE_OAUTH_REDIRECT)
    if parsed_redirect.hostname not in {"127.0.0.1", "localhost"}:
        st.error("La redirección OAuth local de Supabase no es segura.")
        return None

    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    callback = {}

    class OAuthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            callback.update({key: values[0] for key, values in query.items() if values})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body>Autorizacion completada. Puedes volver a la aplicacion.</body></html>"
            )

        def log_message(self, *_args):
            return

    try:
        server = HTTPServer((parsed_redirect.hostname, parsed_redirect.port or 80), OAuthHandler)
    except OSError as error:
        st.error(f"No se pudo iniciar el callback OAuth local: {error}")
        return None

    server_thread = threading.Thread(target=server.handle_request, daemon=True)
    server_thread.start()
    authorize_url = (
        f"{SUPABASE_URL}/auth/v1/authorize?"
        + urlencode({
            "provider": "google",
            "redirect_to": SUPABASE_OAUTH_REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "s256",
        })
    )
    webbrowser.open(authorize_url)
    server_thread.join(timeout=180)
    server.server_close()
    if "code" not in callback:
        if callback.get("error_description"):
            st.error(callback["error_description"])
        else:
            st.error("No se recibió la autorización de Google desde Supabase.")
        return None

    try:
        response = requests.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=pkce",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Content-Type": "application/json",
            },
            json={"auth_code": callback["code"], "code_verifier": verifier},
            timeout=15,
        )
    except requests.RequestException as error:
        st.error(f"No fue posible completar la sesión de Supabase: {error}")
        return None
    if response.status_code != 200:
        st.error("Supabase no pudo completar el inicio con Google.")
        return None
    return response.json()


def supabase_obtener_usuario(access_token):
    if not supabase_configurado() or not access_token:
        return None
    response = requests.get(
        f"{SUPABASE_URL}/auth/v1/user",
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": "Bearer " + access_token,
        },
        timeout=15,
    )
    if response.status_code != 200:
        return None
    return response.json()


def supabase_obtener_perfil(access_token):
    """Obtiene el estado y rol remotos del usuario autenticado."""
    if not supabase_configurado() or not access_token:
        return None
    usuario = supabase_obtener_usuario(access_token)
    email = str((usuario or {}).get("email", "")).strip().lower()
    if not email:
        return None
    try:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": "Bearer " + access_token,
            },
            params={
                "select": "email,full_name,role,status",
                "email": f"eq.{email}",
            },
            timeout=15,
        )
    except requests.RequestException as error:
        st.warning(f"No fue posible consultar el perfil remoto: {error}")
        return None
    if response.status_code != 200:
        return None
    perfiles = response.json()
    return perfiles[0] if perfiles else None


def supabase_obtener_perfiles(access_token):
    """Obtiene todos los perfiles visibles para el usuario autenticado."""
    if not supabase_configurado() or not access_token:
        return []
    try:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": "Bearer " + access_token,
            },
            params={"select": "email,full_name,role,status"},
            timeout=15,
        )
    except requests.RequestException as error:
        st.warning(f"No fue posible consultar los usuarios remotos: {error}")
        return []
    if response.status_code != 200:
        st.warning("No fue posible cargar los usuarios desde Supabase.")
        return []
    return response.json()


def supabase_actualizar_perfil(access_token, email, role, status):
    """Actualiza rol y estado respetando las políticas RLS de Supabase."""
    if not supabase_configurado() or not access_token:
        return False
    try:
        response = requests.patch(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": "Bearer " + access_token,
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            params={"email": f"eq.{email}"},
            json={"role": role, "status": status},
            timeout=15,
        )
    except requests.RequestException as error:
        st.error(f"No fue posible guardar los permisos remotos: {error}")
        return False
    if response.status_code not in (200, 204):
        st.error("Supabase rechazó el cambio de permisos. Verifica las políticas RLS.")
        return False
    return True


def obtener_novedad_version():
    """Obtiene las notas de la versión publicada para el buzón."""
    version_url = (
        "https://raw.githubusercontent.com/juantorob-design/"
        "app_movilidad_cali/main/version.json"
    )
    try:
        response = requests.get(version_url, timeout=5)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        data = {}
    return data or {
        "version": "1.0.5",
        "changelog": "Versión estable del sistema.",
    }


def obtener_usuarios_pendientes():
    """Devuelve cuentas pendientes visibles en la sesión centralizada."""
    if st.session_state.get("supabase_access_token"):
        perfiles = supabase_obtener_perfiles(
            st.session_state["supabase_access_token"]
        )
        if perfiles:
            return [
                perfil for perfil in perfiles
                if perfil.get("status") == "Pendiente"
            ]
    return [
        {"email": email, "full_name": info.get("alias", email)}
        for email, info in st.session_state.get("usuarios", {}).items()
        if info.get("estado") == "Pendiente"
    ]

def enviar_notificacion_correo(destinatario, asunto, mensaje):
    """Envía una alerta usando el Gmail autorizado en esta instalación."""
    destinatario = str(destinatario or "").strip()
    asunto = str(asunto or "").strip()
    mensaje = str(mensaje or "").strip()
    if not destinatario or not asunto or not mensaje:
        return False
    creds = get_google_credentials()
    if not creds or not creds.has_scopes(["https://www.googleapis.com/auth/gmail.send"]):
        return False
    correo = EmailMessage()
    correo["To"] = destinatario
    correo["Subject"] = asunto
    correo["From"] = obtener_email_google(creds) or SUPER_ADMIN_EMAIL
    correo.set_content(mensaje)
    try:
        servicio = build("gmail", "v1", credentials=creds)
        servicio.users().messages().send(
            userId="me",
            body={
                "raw": base64.urlsafe_b64encode(correo.as_bytes()).decode("ascii")
            },
        ).execute()
        return True
    except Exception as error:
        st.warning(f"No fue posible enviar la notificación por correo: {error}")
        return False


def notificar_super_admin(asunto, mensaje):
    """Notifica al correo institucional configurado como Super Administrador."""
    return enviar_notificacion_correo(SUPER_ADMIN_EMAIL, asunto, mensaje)


def obtener_solicitudes_descarga():
    return [
        {"email": email, "alias": info.get("alias", email)}
        for email, info in st.session_state.get("usuarios", {}).items()
        if solicitud_descarga_pendiente(info)
    ]


def agregar_mensaje_soporte(remitente, asunto, mensaje):
    """Guarda una consulta de soporte local para que la revise el Super Administrador."""
    texto = str(mensaje or "").strip()
    if not texto:
        return False
    mensajes = st.session_state.setdefault("mensajes_soporte", [])
    mensajes.append({
        "id": secrets.token_urlsafe(12),
        "fecha": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "remitente": remitente,
        "asunto": str(asunto or "Soporte").strip() or "Soporte",
        "mensaje": texto,
        "leido": False,
    })
    guardar_local_json(st.session_state.db_expedientes)
    notificar_super_admin(
        f"[Soporte urgente] {str(asunto or 'Soporte').strip() or 'Soporte'}",
        (
            f"Se recibió una consulta de soporte de {remitente}.\n\n"
            f"Asunto: {str(asunto or 'Soporte').strip() or 'Soporte'}\n\n"
            f"{texto}\n\n"
            "Ingresa al Buzón de Mensajes para revisarla."
        ),
    )
    return True


def sincronizar_perfiles_remotos():
    """Mezcla perfiles visibles de Supabase con la caché local de usuarios."""
    access_token = st.session_state.get("supabase_access_token")
    if not access_token:
        return False
    perfiles = supabase_obtener_perfiles(access_token)
    if not perfiles:
        return False
    usuarios = st.session_state.setdefault("usuarios", {})
    for perfil in perfiles:
        email = str(perfil.get("email", "")).strip().lower()
        if not email:
            continue
        actual = usuarios.setdefault(email, {
            "alias": email,
            "password": "",
            "metodo": "Supabase Auth",
            "fecha_registro": str(datetime.date.today()),
        })
        actual["alias"] = perfil.get("full_name") or actual.get("alias") or email
        actual["rol"] = perfil.get("role") or "Sin Rol Asignado"
        actual["estado"] = perfil.get("status") or "Pendiente"
    guardar_local_json(st.session_state.db_expedientes)
    return True


# Rutas de Imágenes
IMG_LOGO = obtener_ruta_imagen("logo.png")
IMG_BOTON_MENU = obtener_ruta_imagen("menu_flotante.png")
IMG_CARD_REGISTRO = obtener_ruta_imagen("card_registro.png")
IMG_CARD_BUSCADOR = obtener_ruta_imagen("card_buscador.png")
IMG_CARD_DRIVE = obtener_ruta_imagen("card_drive.png")
IMG_CARD_SHEETS = obtener_ruta_imagen("card_sheets.png")
IMG_CARD_PERMISOS = obtener_ruta_imagen("card_permisos.png")
IMG_CARD_PERFIL = obtener_ruta_imagen("card_perfil.png")

# --- ESTILOS CSS REVISADOS ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {
        background: transparent !important;
    }
    header[data-testid="stHeader"] button {
        color: #f8fafc !important;
    }
    
    button[title="View fullscreen"], 
    div[data-testid="stImage"] button,
    .stApp [data-testid="StyledFullScreenButton"] {
        display: none !important;
    }

    .stApp {
        background-color: #0d1322 !important;
        color: #f8fafc !important;
    }

    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 5rem;
        max-width: 1280px;
    }

    .header-box {
        text-align: center;
        margin-bottom: 20px;
    }
    .brand-logo {
        display: block;
        height: 120px;
        object-fit: contain;
        width: 120px;
    }
    .brand-logo-wrap {
        align-items: center;
        display: flex;
        justify-content: center;
        margin: 0 auto 12px;
        width: 100%;
    }
    .header-title {
        color: #ffffff;
        font-size: 24px;
        font-weight: 800;
        margin-top: 5px;
    }
    .header-subtitle {
        color: #38bdf8;
        font-weight: 600;
        font-size: 14px;
    }

    .launcher-title {
        color: #f8fafc;
        font-size: 16px;
        font-weight: 700;
        margin: 24px 0 12px 4px;
        text-align: center;
    }

    .profile-chip {
        color: #cbd5e1;
        font-size: 13px;
        margin: 0 auto 16px;
        max-width: 420px;
        padding: 8px 14px;
        text-align: center;
    }

    .action-tile {
        align-items: center;
        background: transparent;
        border: 1px solid transparent;
        border-radius: 12px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        min-height: 126px;
        padding: 8px 6px;
        text-align: center;
        text-decoration: none !important;
        transition: transform 0.18s ease, filter 0.18s ease;
    }

    .action-tile:hover {
        background: #16243c;
        border-color: #2d466b;
        filter: brightness(1.16);
        transform: translateY(-4px);
    }

    .action-tile img {
        border-radius: 18px;
        display: block;
        height: 72px;
        margin: 0 auto 8px;
        object-fit: contain;
        width: 72px;
    }

    .action-tile span {
        color: #f8fafc;
        display: block;
        font-size: 12px;
        font-weight: 600;
        line-height: 1.25;
    }

    .launcher-grid {
        display: grid;
        gap: 12px;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        margin: 0 auto;
        max-width: 900px;
        width: 100%;
    }
    @media (min-width: 1100px) {
        .launcher-grid {
            grid-template-columns: repeat(6, minmax(0, 1fr));
        }
    }



    div[data-baseweb="input"] {
        background-color: #ffffff !important;
        border-radius: 8px !important;
    }
    div[data-baseweb="input"] input {
        color: #0d1322 !important;
        font-weight: 600 !important;
        font-size: 15px !important;
    }

    div[data-testid="column"] {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: flex-start;
    }

    section[data-testid="stSidebar"] {
        background: #111a2b !important;
        border-right: 1px solid #263854;
    }

    section[data-testid="stSidebar"] [data-testid="stImage"] img {
        border-radius: 14px;
    }
    section[data-testid="stSidebar"] [data-testid="stImage"] {
        display: flex;
        justify-content: center;
    }
    section[data-testid="stSidebar"] [data-testid="stImage"] img {
        margin: 0 auto;
    }
    .sidebar-brand {
        display: flex;
        justify-content: center;
        align-items: center;
        width: 100%;
        margin: 0 auto 12px;
    }
    .sidebar-brand img {
        display: block;
        height: 92px;
        width: 92px;
        object-fit: contain;
        border-radius: 14px;
    }
    </style>
""", unsafe_allow_html=True)

# --- GOOGLE OAUTH Y APIS ---
def autenticar_google_escritorio():
    """Abre el navegador del sistema y completa OAuth en localhost."""
    if not os.path.exists(CLIENT_SECRETS_FILE):
        st.error(
            "No se encontró la configuración de Google. "
            "El inicio de sesión local sigue disponible."
        )
        return None
    try:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
        browser_name = obtener_navegador_oauth()
        oauth_port = int(os.environ.get("SISTEMA_OAUTH_PORT", "8080"))
        creds = flow.run_local_server(
            port=oauth_port,
            prompt="consent",
            open_browser=True,
            browser=browser_name,
            success_message="Autenticación completada. Puedes cerrar esta ventana y volver a la aplicación.",
        )
        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
        return creds
    except Exception as e:
        st.error(f"Error durante el proceso de autenticación: {e}")
        return None

def obtener_navegador_oauth():
    """Selecciona Edge o Chrome para OAuth sin depender del navegador predeterminado."""
    browser_path = os.environ.get("SISTEMA_OAUTH_BROWSER", "").strip()
    candidatos = [
        browser_path,
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for candidato in candidatos:
        if candidato and os.path.exists(candidato):
            nombre = "sistema_oauth_browser"
            webbrowser.register(nombre, None, webbrowser.BackgroundBrowser(candidato))
            return nombre
    return None

def revisar_configuracion_oauth():
    """Indica si el cliente web tiene registrada la redirección local usada por la app."""
    try:
        with open(CLIENT_SECRETS_FILE, "r", encoding="utf-8-sig") as archivo:
            config = json.load(archivo)
        cliente = config.get("web") or config.get("installed") or {}
        oauth_port = os.environ.get("SISTEMA_OAUTH_PORT", "8080").strip()
        if not oauth_port.isdigit() or not 1 <= int(oauth_port) <= 65535:
            return "SISTEMA_OAUTH_PORT debe ser un puerto válido entre 1 y 65535."
        redirect_uris = cliente.get("redirect_uris", [])
        if config.get("web") and not any(
            uri in {
                f"http://localhost:{oauth_port}/",
                f"http://127.0.0.1:{oauth_port}/",
            }
            for uri in redirect_uris
        ):
            return (
                "Tu credentials.json es de tipo web y no tiene registrada la "
                f"redirección local del puerto {oauth_port}. Agrega "
                f"http://localhost:{oauth_port}/ y "
                f"http://127.0.0.1:{oauth_port}/ en Google Cloud, "
                "o descarga un cliente OAuth de tipo Aplicación de escritorio."
            )
    except (OSError, json.JSONDecodeError, TypeError):
        return "credentials.json no tiene un formato OAuth válido."
    return None

def get_google_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            # Se carga el conjunto real del token para poder detectar si requiere
            # una nueva autorización (por ejemplo, el permiso gmail.send).
            creds = Credentials.from_authorized_user_file(TOKEN_FILE)
            if creds and creds.valid:
                return creds
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
                return creds
        except Exception:
            creds = None
    return creds

def obtener_email_google(creds):
    try:
        service = build("oauth2", "v2", credentials=creds)
        user_info = service.userinfo().get().execute()
        return (user_info.get("email") or "").strip().lower()
    except Exception:
        return None

def get_drive_service():
    creds = get_google_credentials()
    if not creds:
        return None
    try:
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        st.error(f"Error al conectar con Google Drive API: {e}")
        return None

def get_sheets_service():
    creds = get_google_credentials()
    if not creds:
        return None
    try:
        service = build("sheets", "v4", credentials=creds)
        asegurar_hoja_bd_desv(service)
        return service
    except Exception as e:
        st.error(f"Error al conectar con Google Sheets API: {e}")
        return None

def subir_archivo_a_drive(service, file_buffer, file_name, folder_id):
    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, f"temp_{file_name}")
    try:
        file_metadata = {'name': file_name, 'parents': [folder_id]}
        with open(temp_path, "wb") as f:
            f.write(file_buffer.getbuffer())

        media = MediaFileUpload(temp_path, resumable=True)
        file_uploaded = service.files().create(
            body=file_metadata, media_body=media, fields='id, webViewLink'
        ).execute()

        return file_uploaded.get('id'), file_uploaded.get('webViewLink')
    except Exception as e:
        st.error(f"Error al subir a Google Drive: {e}")
        return None, None
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def buscar_o_crear_carpeta_drive(service, parent_id, folder_name):
    """Devuelve una carpeta hija única, creándola si todavía no existe."""
    if not service or not parent_id or not folder_name:
        return None
    try:
        query = (
            f"'{parent_id}' in parents and trashed = false "
            "and mimeType = 'application/vnd.google-apps.folder' "
            f"and name = '{folder_name.replace(chr(39), chr(39) + chr(39))}'"
        )
        carpetas = service.files().list(
            q=query,
            fields="files(id,name,parents)",
            pageSize=100,
            orderBy="createdTime",
        ).execute().get("files", [])
        if carpetas:
            return carpetas[0].get("id")
        creada = service.files().create(
            body={
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            },
            fields="id",
        ).execute()
        return creada.get("id")
    except Exception as error:
        st.error(f"No fue posible preparar la carpeta de Drive '{folder_name}': {error}")
        return None


def buscar_carpeta_drive(service, parent_id, folder_name):
    """Busca una carpeta hija sin crearla."""
    if not service or not parent_id or not folder_name:
        return None
    try:
        nombre = folder_name.replace("'", "''")
        query = (
            f"'{parent_id}' in parents and trashed = false "
            "and mimeType = 'application/vnd.google-apps.folder' "
            f"and name = '{nombre}'"
        )
        carpetas = service.files().list(
            q=query,
            fields="files(id,name,parents)",
            pageSize=10,
        ).execute().get("files", [])
        return carpetas[0].get("id") if carpetas else None
    except Exception as error:
        st.warning(f"No fue posible buscar la carpeta de Drive '{folder_name}': {error}")
        return None


def buscar_carpeta_drive_por_nombres(service, parent_id, nombres):
    """Busca una carpeta hija aceptando diferencias de mayúsculas y pluralización."""
    if not service or not parent_id:
        return None
    candidatos = {
        re.sub(r"[^a-z0-9]", "", str(nombre or "").casefold())
        for nombre in nombres
        if str(nombre or "").strip()
    }
    if not candidatos:
        return None
    try:
        carpetas = service.files().list(
            q=(
                f"'{parent_id}' in parents and trashed = false "
                "and mimeType = 'application/vnd.google-apps.folder'"
            ),
            fields="files(id,name,parents)",
            pageSize=1000,
        ).execute().get("files", [])
        for carpeta in carpetas:
            clave = re.sub(
                r"[^a-z0-9]",
                "",
                str(carpeta.get("name", "")).casefold(),
            )
            if clave in candidatos:
                return carpeta.get("id")
    except Exception as error:
        st.warning(
            "No fue posible localizar la carpeta documental en Drive: "
            f"{error}"
        )
    return None


def carpeta_primaria_documentos_drive(service):
    """Devuelve la raíz documental real: preferiblemente 'PDFS Escaneados' bajo la base configurada."""
    if not service or not DRIVE_FOLDER_ID:
        return None
    try:
        metadata = service.files().get(fileId=DRIVE_FOLDER_ID, fields="id,name").execute()
        nombre_base = str(metadata.get("name", "")).strip().casefold()
        if nombre_base == "pdfs escaneados":
            return DRIVE_FOLDER_ID
    except Exception:
        pass

    carpeta_documental = buscar_carpeta_drive_por_nombres(
        service,
        DRIVE_FOLDER_ID,
        ("PDFS Escaneados", "PDFS ESCANEADOS"),
    )
    if carpeta_documental:
        return carpeta_documental

    creada = buscar_o_crear_carpeta_drive(service, DRIVE_FOLDER_ID, "PDFS Escaneados")
    return creada or DRIVE_FOLDER_ID


def carpeta_drive_para_peticiones(service):
    """Obtiene PDFS Escaneados/Peticion, raíz única de expedientes y pendientes."""
    base_id = carpeta_primaria_documentos_drive(service)
    if not base_id:
        return None
    return (
        buscar_carpeta_drive_por_nombres(
            service,
            base_id,
            ("Peticion", "Peticiones"),
        )
        or buscar_o_crear_carpeta_drive(
            service,
            base_id,
            DRIVE_REQUEST_FOLDER_NAME,
        )
    )


def carpeta_drive_para_fecha(service, fecha):
    """Obtiene PDFS Escaneados/AÑO para el expediente confirmado."""
    base_id = carpeta_primaria_documentos_drive(service)
    if not base_id:
        return None
    try:
        fecha_obj = datetime.date.fromisoformat(str(fecha or "").strip())
    except (TypeError, ValueError):
        st.error(
            "No se puede clasificar el documento en Drive porque la fecha de "
            "la petición no es válida. Usa el formato AAAA-MM-DD."
        )
        return None
    return buscar_o_crear_carpeta_drive(service, base_id, str(fecha_obj.year))


def carpeta_drive_para_expediente(service, fecha, radicado, placa, ubicacion):
    """Obtiene PDFS Escaneados/AÑO/RADICADO... para el expediente confirmado."""
    carpeta_anual_id = carpeta_drive_para_fecha(service, fecha)
    if not carpeta_anual_id:
        return None

    nombre_expediente = nombre_carpeta_expediente(radicado, placa, fecha, ubicacion)
    if not nombre_expediente:
        return carpeta_anual_id

    return buscar_o_crear_carpeta_drive(
        service,
        carpeta_anual_id,
        nombre_expediente,
    )


def componentes_ubicacion(ubicacion):
    """Convierte la ubicación administrativa en niveles físicos de Drive."""
    texto = str(ubicacion or "").strip()
    if not texto:
        return "", "", ""

    texto = texto.replace("/", " ").replace("|", " ")
    coincidencias = re.findall(
        r"(caja|folder|carpeta)\s*[-:_ ]*\s*([A-Za-z0-9]+)",
        texto,
        flags=re.IGNORECASE,
    )
    if coincidencias:
        valores = {}
        for clave, valor in coincidencias:
            valores[clave.casefold()] = valor.strip("-_ ")
        caja = valores.get("caja")
        folder = valores.get("folder")
        carpeta = valores.get("carpeta")
        if caja or folder or carpeta:
            return (
                f"CAJA-{caja}" if caja else "",
                f"FOLDER-{folder}" if folder else "",
                f"CARPETA-{carpeta}" if carpeta else "",
            )

    # Compatibilidad con cadenas heredadas de la forma: "Carpeta 1 - Folder 1 - Caja 1"
    coincidencia = re.search(
        r"(?:carpeta|carpeta\s*\d+)\s*(\d+)\s*-\s*(?:folder|folder\s*\d+)\s*(\d+)\s*-\s*(?:caja|caja\s*\d+)\s*(\d+)",
        texto,
        flags=re.IGNORECASE,
    )
    if coincidencia:
        carpeta, folder, caja = coincidencia.groups()
        return f"CAJA-{caja}", f"FOLDER-{folder}", f"CARPETA-{carpeta}"

    return "", "", ""


def _normalizar_parte_ubicacion(valor, prefijo):
    """Normaliza una parte de la ubicación para nombres de expediente."""
    texto = str(valor or "").strip()
    if not texto:
        return ""
    texto = texto.replace("/", " ").replace("|", " ")
    texto = re.sub(rf"^{re.escape(prefijo)}\s*[-_: ]*", "", texto, flags=re.IGNORECASE)
    texto = texto.strip("-_/ ")
    return f"{prefijo}-{texto}" if texto else ""


def nombre_raiz_expediente(radicado, placa, fecha):
    """Genera la raíz estable del expediente sin ubicación física."""
    return nombre_carpeta_expediente(
        radicado,
        placa,
        fecha,
        "",
    )


def carpeta_drive_para_staging(service, radicado, placa, fecha):
    """Obtiene PDFs Escaneados/Peticion/RADICADO_PLACA_FECHA para el staging temporal."""
    peticiones_id = carpeta_drive_para_peticiones(service)
    if not peticiones_id:
        return None
    return buscar_o_crear_carpeta_drive(
        service,
        peticiones_id,
        nombre_carpeta_peticion(radicado, placa, fecha),
    )


def carpeta_drive_para_complementos_sin_vincular(service, placa):
    """Obtiene PDFs Escaneados/Peticion/Por_vincular/PLACA para anexos sin expediente padre."""
    peticiones_id = carpeta_drive_para_peticiones(service)
    if not peticiones_id:
        return None
    bandeja_id = buscar_o_crear_carpeta_drive(
        service,
        peticiones_id,
        DRIVE_UNLINKED_FOLDER_NAME,
    )
    if not bandeja_id:
        return None
    return buscar_o_crear_carpeta_drive(
        service,
        bandeja_id,
        _token_nombre_documento(placa) or "PLACA_SIN_IDENTIFICAR",
    )


def fusionar_complementos_sin_vincular(service, placa, carpeta_expediente_id):
    """Mueve complementos de Por_vincular a un expediente recién localizado."""
    peticiones_id = carpeta_drive_para_peticiones(service)
    origen = (
        buscar_carpeta_drive(service, peticiones_id, DRIVE_UNLINKED_FOLDER_NAME)
        if peticiones_id
        else None
    )
    origen = buscar_carpeta_drive(
        service,
        origen,
        _token_nombre_documento(placa) or "PLACA_SIN_IDENTIFICAR",
    ) if origen else None
    if not origen or not carpeta_expediente_id:
        return 0
    movidos = 0
    try:
        elementos = service.files().list(
            q=f"'{origen}' in parents and trashed = false",
            fields="files(id,name,mimeType)",
            pageSize=1000,
        ).execute().get("files", [])
        for elemento in elementos:
            if elemento.get("mimeType") == "application/vnd.google-apps.folder":
                destino = carpeta_drive_para_documento(
                    service,
                    carpeta_expediente_id,
                    elemento.get("name", "Otro"),
                )
                fusionar_carpeta_drive(service, elemento.get("id"), destino)
            else:
                destino = carpeta_drive_para_documento(
                    service,
                    carpeta_expediente_id,
                    "Otro",
                )
                if mover_archivo_drive(service, elemento.get("id"), destino):
                    movidos += 1
        if not elementos:
            service.files().delete(fileId=origen).execute()
    except Exception as error:
        st.warning(
            f"No fue posible reunificar complementos de {placa}: {error}"
        )
    return movidos

def buscar_carpeta_expediente_drive(service, fecha, radicado, placa):
    """Busca un expediente pendiente en Peticion o confirmado dentro del año."""
    if not service:
        return None
    base_id = carpeta_primaria_documentos_drive(service)
    if not base_id:
        return None
    nombre = nombre_raiz_expediente(radicado, placa, fecha)
    nombre_legacy = nombre_carpeta_peticion(radicado, placa, fecha)
    peticiones_id = carpeta_drive_para_peticiones(service)
    if peticiones_id:
        encontrada = buscar_carpeta_drive(service, peticiones_id, nombre)
        if not encontrada and nombre_legacy != nombre:
            encontrada = buscar_carpeta_drive(service, peticiones_id, nombre_legacy)
        if encontrada:
            return encontrada
        if placa:
            coincidencias = service.files().list(
                q=(
                    f"'{peticiones_id}' in parents and trashed = false "
                    "and mimeType = 'application/vnd.google-apps.folder' "
                    f"and name contains '{_token_nombre_documento(placa)}'"
                ),
                fields="files(id,name)",
                pageSize=50,
            ).execute().get("files", [])
            if coincidencias:
                return coincidencias[0].get("id")
    try:
        fecha_obj = datetime.date.fromisoformat(str(fecha or "").strip())
    except (TypeError, ValueError):
        return None
    anual_id = buscar_carpeta_drive(service, base_id, str(fecha_obj.year))
    if not anual_id:
        return None
    encontrada = buscar_carpeta_drive(service, anual_id, nombre)
    if not encontrada and nombre_legacy != nombre:
        encontrada = buscar_carpeta_drive(service, anual_id, nombre_legacy)
    if encontrada or not placa:
        return encontrada
    coincidencias = service.files().list(
        q=(
            f"'{anual_id}' in parents and trashed = false "
            "and mimeType = 'application/vnd.google-apps.folder' "
            f"and name contains '{_token_nombre_documento(placa)}'"
        ),
        fields="files(id,name)",
        pageSize=50,
    ).execute().get("files", [])
    return coincidencias[0].get("id") if coincidencias else None

def carpeta_drive_para_documento(service, carpeta_expediente_id, tipo_documento):
    """Obtiene una subcarpeta del expediente para cada tipo documental."""
    tipo = str(tipo_documento or "Otro").strip().casefold()
    equivalencias = {
        "solicitud": "peticion",
        "petición": "peticion",
        "consulta qx": "consulta",
        "resolución": "resolucion resuelve",
        "requerimiento": "resolucion resuelve",
        "oficio de citación": "citacion",
        "citación del recurso": "citacion",
        "notificación": "notificacion",
        "notificación personal": "notificacion",
        "notificación por aviso": "notificacion",
        "notificación por publicación web": "notificacion",
        "notificación del recurso": "notificacion",
        "recurso": "recurso",
        "resolución del recurso": "recurso",
        "constancia de ejecutoria": "constancia de ejecutoria",
        "remisión a registro": "remision",
        "desistimiento": "desistimiento",
    }
    nombre = equivalencias.get(tipo, "Otro")
    return buscar_o_crear_carpeta_drive(
        service,
        carpeta_expediente_id,
        nombre,
    )


def preparar_subcarpetas_documentales(service, carpeta_expediente_id):
    """Crea las subcarpetas documentales estándar del expediente."""
    creadas = {}
    for nombre in SUBCARPETAS_DOCUMENTALES:
        carpeta_id = buscar_o_crear_carpeta_drive(
            service,
            carpeta_expediente_id,
            nombre,
        )
        if not carpeta_id:
            raise RuntimeError(
                f"No fue posible crear la subcarpeta documental '{nombre}'."
            )
        creadas[nombre] = carpeta_id
    return creadas


def nombre_complemento_peticion(
    radicado,
    placa,
    fecha,
    caja="",
    folder="",
    carpeta="",
    recurso="",
    numero=1,
):
    """Genera el nombre estándar de un bloque documental temporal."""
    fecha_formateada = fecha_para_nombre_carpeta(fecha)
    tipo = _token_nombre_documento(recurso or "Otro").lower()
    base = "_".join(
        token
        for token in (
            _token_nombre_documento(radicado or "NRO_PETICION_PENDIENTE"),
            _token_nombre_documento(placa or "PLACA_PENDIENTE"),
            fecha_formateada,
            tipo,
        )
        if token
    )
    sufijo = f"_{int(numero):02d}" if numero > 1 else ""
    return f"{base}{sufijo}.pdf"


def ordenar_documentos_por_precedencia(documentos):
    """Ordena complementos según la secuencia administrativa obligatoria."""
    posiciones = {
        tipo.casefold(): indice
        for indice, tipo in enumerate(ORDEN_DOCUMENTAL_PRELACION)
    }

    def clave(item):
        tipo = str(
            item.get("tipo_documento")
            or item.get("tipo")
            or "Otro"
        ).strip()
        tipo_normalizado = tipo.casefold()
        posicion = posiciones.get(tipo_normalizado)
        if posicion is None and tipo_normalizado == "oficio de citación":
            posicion = posiciones["oficio de citación"]
        if posicion is None:
            posicion = len(ORDEN_DOCUMENTAL_PRELACION)
        return posicion, str(item.get("nombre") or "").casefold()

    return sorted(documentos or [], key=clave)


def preparar_carga_drive(
    service,
    archivos,
    radicado,
    placa,
    fecha,
    tipo_fallback,
    carga_id,
    es_complemento=False,
    partes_analizadas=None,
):
    """Sube el PDF completo temporal y sus partes documentales al staging."""
    if not service:
        return [], None, "Google Drive no está autenticado."
    try:
        if es_complemento and not buscar_carpeta_expediente_drive(
            service,
            fecha,
            radicado,
            placa,
        ):
            carpeta_expediente = carpeta_drive_para_complementos_sin_vincular(
                service,
                placa,
            )
        elif not str(fecha or "").strip():
            return [], None, (
                "Completa la fecha de la petición para ubicar el documento "
                "en la carpeta temporal del expediente."
            )
        else:
            carpeta_expediente = buscar_carpeta_expediente_drive(
                service,
                fecha,
                radicado,
                placa,
            ) or carpeta_drive_para_staging(service, radicado, placa, fecha)
        if not carpeta_expediente:
            return [], None, "No fue posible crear la carpeta de carga en Drive."
        preparar_subcarpetas_documentales(service, carpeta_expediente)

        documentos = []
        for archivo in archivos:
            contenido = archivo.getvalue()
            if not archivo.name.lower().endswith(".pdf"):
                contenido = convertir_imagen_a_pdf(contenido, archivo.name)
            nombre_temporal = (
                f"{nombre_carpeta_peticion(radicado, placa, fecha)}_COMPLETO.pdf"
            )
            existente_completo = buscar_archivo_drive(
                service,
                carpeta_expediente,
                nombre_temporal,
                contenido,
            )
            if existente_completo:
                completo_id = existente_completo.get("id")
                completo_url = existente_completo.get("webViewLink")
            else:
                completo_id, completo_url = subir_archivo_a_drive(
                    service,
                    io.BytesIO(contenido),
                    nombre_temporal,
                    carpeta_expediente,
                )
            documentos.append({
                "nombre": nombre_temporal,
                "nombre_original": archivo.name,
                "tipo_documento": "Expediente completo",
                "drive_id": completo_id,
                "drive_url": completo_url,
                "drive_folder_id": carpeta_expediente,
                "huella": huella_contenido(contenido),
                "paginas": 0,
                "texto_analizado": "",
                "carga_id": carga_id,
                "staged": True,
                "es_pdf_completo": True,
            })
            clave_partes = huella_contenido(contenido)
            if partes_analizadas is not None and clave_partes in partes_analizadas:
                partes = list(partes_analizadas.get(clave_partes) or [])
            else:
                partes = separar_pdf_completo(contenido, tipo_fallback)
            for numero, parte in enumerate(partes, start=1):
                tipo = parte.get("tipo") or tipo_fallback or "Otro"
                carpeta_tipo = carpeta_drive_para_documento(
                    service,
                    carpeta_expediente,
                    tipo,
                )
                nombre = nombre_complemento_peticion(
                    radicado,
                    placa,
                    fecha,
                    numero=numero,
                    recurso=tipo,
                )
                existente = buscar_archivo_drive(
                    service,
                    carpeta_tipo,
                    nombre,
                    parte["contenido"],
                )
                if existente:
                    file_id = existente.get("id")
                    drive_url = existente.get("webViewLink")
                else:
                    file_id, drive_url = subir_archivo_a_drive(
                        service,
                        io.BytesIO(parte["contenido"]),
                        nombre,
                        carpeta_tipo,
                    )
                documentos.append({
                    "nombre": nombre,
                    "nombre_original": archivo.name,
                    "tipo_documento": tipo,
                    "drive_id": file_id,
                    "drive_url": drive_url,
                    "drive_folder_id": carpeta_tipo,
                    "huella": huella_contenido(parte["contenido"]),
                    "paginas": parte.get("paginas", 0),
                    "texto_analizado": parte.get("texto", ""),
                    "carga_id": carga_id,
                    "staged": True,
                })
        return documentos, carpeta_expediente, None
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        return [], None, f"No fue posible preparar la carga en Drive: {error}"


def mover_archivo_drive(service, file_id, carpeta_destino_id):
    """Mueve un archivo pendiente sin descargarlo ni volverlo a subir."""
    if not service or not file_id or not carpeta_destino_id:
        return False
    try:
        actual = service.files().get(
            fileId=file_id,
            fields="parents,name,md5Checksum",
        ).execute()
        padres_lista = actual.get("parents", [])
        if carpeta_destino_id in padres_lista:
            return True
        nombre = str(actual.get("name") or "").replace("'", "''")
        md5 = actual.get("md5Checksum")
        if nombre:
            query = (
                f"'{carpeta_destino_id}' in parents and trashed = false "
                f"and name = '{nombre}'"
            )
            existentes = service.files().list(
                q=query,
                fields="files(id,md5Checksum)",
                pageSize=10,
            ).execute().get("files", [])
            if any(md5 and item.get("md5Checksum") == md5 for item in existentes):
                return True
        padres = ",".join(padres_lista)
        service.files().update(
            fileId=file_id,
            addParents=carpeta_destino_id,
            removeParents=padres,
            fields="id,parents,webViewLink",
        ).execute()
        return True
    except Exception as error:
        st.warning(f"No fue posible mover el pendiente al expediente: {error}")
        return False


def renombrar_archivo_drive(service, file_id, nombre):
    """Renombra un archivo de Drive sin cambiar su carpeta."""
    if not service or not file_id or not nombre:
        return False
    try:
        service.files().update(
            fileId=file_id,
            body={"name": nombre},
            fields="id,name,parents,webViewLink",
        ).execute()
        return True
    except Exception as error:
        st.warning(f"No fue posible renombrar el archivo del expediente: {error}")
        return False


def mover_carpeta_drive(service, folder_id, carpeta_destino_id):
    """Mueve una carpeta de Peticion al año definitivo sin duplicar contenido."""
    return mover_archivo_drive(service, folder_id, carpeta_destino_id)


def renombrar_carpeta_drive(service, folder_id, nombre):
    if not service or not folder_id or not nombre:
        return False
    try:
        service.files().update(
            fileId=folder_id,
            body={"name": nombre},
            fields="id,name",
        ).execute()
        return True
    except Exception as error:
        st.warning(f"No fue posible renombrar la carpeta del expediente: {error}")
        return False


def fusionar_carpeta_drive(service, origen_id, destino_id):
    """Mueve el contenido de una carpeta temporal a la definitiva sin duplicar archivos."""
    if not service or not origen_id or not destino_id or origen_id == destino_id:
        return origen_id == destino_id
    try:
        elementos = service.files().list(
            q=f"'{origen_id}' in parents and trashed = false",
            fields="files(id,name,mimeType,parents,md5Checksum)",
            pageSize=1000,
        ).execute().get("files", [])
        for elemento in elementos:
            if elemento.get("mimeType") == "application/vnd.google-apps.folder":
                subcarpeta_destino = buscar_o_crear_carpeta_drive(
                    service,
                    destino_id,
                    elemento.get("name", "Otro"),
                )
                if not fusionar_carpeta_drive(
                    service,
                    elemento.get("id"),
                    subcarpeta_destino,
                ):
                    return False
            else:
                nombre = elemento.get("name", "")
                nombre_escapado = nombre.replace("'", "''")
                existente = service.files().list(
                    q=(
                        f"'{destino_id}' in parents and trashed = false "
                        f"and name = '{nombre_escapado}'"
                    ),
                    fields="files(id,md5Checksum)",
                    pageSize=2,
                ).execute().get("files", [])
                if existente and any(
                    elemento.get("md5Checksum")
                    and item.get("md5Checksum") == elemento.get("md5Checksum")
                    for item in existente
                ):
                    service.files().delete(fileId=elemento.get("id")).execute()
                elif not mover_archivo_drive(
                    service,
                    elemento.get("id"),
                    destino_id,
                ):
                    return False
        service.files().delete(fileId=origen_id).execute()
        return True
    except Exception as error:
        st.warning(f"No fue posible consolidar la carpeta temporal de Drive: {error}")
        return False


def huella_contenido(contenido):
    return hashlib.sha256(contenido).hexdigest()


def _ruta_cache_ocr():
    return resolver_dato("ocr_cache.json")


def _cargar_cache_ocr():
    global _ocr_persistent_cache
    if _ocr_persistent_cache is not None:
        return _ocr_persistent_cache
    ruta = _ruta_cache_ocr()
    try:
        with open(ruta, "r", encoding="utf-8") as archivo:
            cache = json.load(archivo)
        _ocr_persistent_cache = cache if isinstance(cache, dict) else {}
    except (OSError, ValueError, TypeError):
        _ocr_persistent_cache = {}
    return _ocr_persistent_cache


def _guardar_cache_ocr():
    cache = _ocr_persistent_cache
    if not isinstance(cache, dict):
        return
    ruta = _ruta_cache_ocr()
    temporal = f"{ruta}.tmp"
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(temporal, "w", encoding="utf-8") as archivo:
            json.dump(cache, archivo, ensure_ascii=False)
        os.replace(temporal, ruta)
    except OSError:
        if os.path.exists(temporal):
            os.remove(temporal)


def _clave_cache_ocr(contenido, pagina, escala):
    return f"{OCR_CACHE_VERSION}:{huella_contenido(contenido)}:{pagina}:{escala:g}"


def obtener_texto_ocr_pagina(contenido, pagina, objeto_pagina, escala=OCR_RENDER_SCALE):
    """Lee una página usando la caché persistente para no repetir OCR costoso."""
    if fitz is None or RapidOCR is None:
        return ""
    cache = _cargar_cache_ocr()
    clave = _clave_cache_ocr(contenido, pagina, escala)
    texto_guardado = cache.get(clave)
    if isinstance(texto_guardado, str) and texto_guardado.strip():
        return texto_guardado
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = crear_motor_ocr()
    pixmap = objeto_pagina.get_pixmap(
        matrix=fitz.Matrix(escala, escala),
        alpha=False,
    )
    resultado, _ = _ocr_engine(pixmap.tobytes("png"))
    texto = normalizar_texto_documento(
        " ".join(str(elemento[1]) for elemento in (resultado or []))
    )
    global _ocr_cache_writes_pending
    cache[clave] = texto
    _ocr_cache_writes_pending += 1
    if _ocr_cache_writes_pending >= 8:
        _guardar_cache_ocr()
        _ocr_cache_writes_pending = 0
    return texto


def buscar_archivo_drive(service, folder_id, file_name, contenido):
    """Busca una copia por nombre o contenido antes de crear otro archivo."""
    if not service:
        return None
    try:
        resultados = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="files(id,name,webViewLink,md5Checksum,size)",
            pageSize=1000,
        ).execute().get("files", [])
        md5 = hashlib.md5(contenido).hexdigest()
        for archivo in resultados:
            if archivo.get("name") == file_name:
                return archivo
            if archivo.get("md5Checksum") == md5:
                return archivo
    except Exception as error:
        st.warning(f"No fue posible verificar duplicados en Drive: {error}")
    return None


def eliminar_archivo_drive(service, file_id):
    if service and file_id:
        try:
            service.files().update(
                fileId=file_id,
                body={"trashed": True},
                fields="id",
            ).execute()
        except Exception as error:
            st.warning(f"No fue posible reemplazar el archivo anterior en Drive: {error}")


def listar_archivos_drive(service, folder_id):
    try:
        query = f"'{folder_id}' in parents and trashed = false"
        results = service.files().list(
            q=query, fields="files(id, name, mimeType, modifiedTime, webViewLink, size)"
        ).execute()
        return results.get('files', [])
    except Exception as e:
        st.error(f"Error consultando Drive: {e}")
        return []

def descargar_archivo_drive(service, file_id):
    buffer = io.BytesIO()
    request = service.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(buffer, request)
    terminado = False
    while not terminado:
        _, terminado = downloader.next_chunk()
    return buffer.getvalue()


def _extraer_texto_pdf(contenido, progreso=None):
    """Lee texto digital y OCR de cada página para consolidar todos los campos."""
    global _ocr_cache_writes_pending, _ocr_last_error
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(io.BytesIO(contenido))
        textos_digitales = [
            (pagina.extract_text() or "").replace("\xa0", " ")
            for pagina in reader.pages
        ]
        texto = " ".join(textos_digitales)
        texto = normalizar_texto_documento(texto)
    except Exception:
        textos_digitales = []
        texto = ""
    if fitz is None or RapidOCR is None:
        return texto
    try:
        global _ocr_engine
        if _ocr_engine is None:
            _ocr_engine = crear_motor_ocr()
        documento = fitz.open(stream=contenido, filetype="pdf")
        paginas = []
        total_paginas = len(documento)
        for indice, pagina in enumerate(documento):
            if OCR_MAX_PAGES is not None and indice >= OCR_MAX_PAGES:
                break
            texto_digital = (
                textos_digitales[indice]
                if indice < len(textos_digitales)
                else ""
            )
            pixmap_vista = pagina.get_pixmap(
                matrix=fitz.Matrix(0.35, 0.35),
                alpha=False,
            )
            texto_ocr = ""
            if not pagina_pixeles_blancos(pixmap_vista):
                texto_ocr = obtener_texto_ocr_pagina(
                    contenido,
                    indice,
                    pagina,
                )
            texto_pagina = " ".join(
                parte for parte in (texto_digital, texto_ocr) if parte
            )
            if texto_pagina:
                paginas.append(texto_pagina)
            if progreso:
                progreso(indice + 1, total_paginas)
        documento.close()
        if _ocr_cache_writes_pending:
            _guardar_cache_ocr()
            _ocr_cache_writes_pending = 0
        return normalizar_texto_documento(" ".join(paginas))
    except Exception as error:
        _ocr_last_error = str(error)
        return texto


def extraer_paginas_hibridas_pdf(contenido, progreso=None):
    """Extrae texto por página y selecciona solo páginas débiles para visión."""
    if fitz is None:
        return [], ""
    try:
        reader = PdfReader(io.BytesIO(contenido)) if PdfReader is not None else None
        textos_digitales = [
            (pagina.extract_text() or "").replace("\xa0", " ")
            for pagina in (reader.pages if reader else [])
        ]
        documento = fitz.open(stream=contenido, filetype="pdf")
        paginas = []
        for indice, pagina in enumerate(documento):
            if OCR_MAX_PAGES is not None and indice >= OCR_MAX_PAGES:
                break
            texto_digital = (
                normalizar_texto_documento(textos_digitales[indice])
                if indice < len(textos_digitales)
                else ""
            )
            texto_ocr = ""
            pixmap = pagina.get_pixmap(matrix=fitz.Matrix(0.35, 0.35), alpha=False)
            pagina_blanca = pagina_pixeles_blancos(pixmap)
            if not texto_digital and not pagina_blanca:
                texto_ocr = obtener_texto_ocr_pagina(
                    contenido,
                    indice,
                    pagina,
                    escala=OCR_RENDER_SCALE,
                )
            texto = normalizar_errores_ocr(" ".join(
                parte for parte in (texto_digital, texto_ocr) if parte
            ))
            palabras = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9]{2,}", texto)
            caracteres_invalidos = len(re.findall(r"[^\w\sÁÉÍÓÚáéíóúÑñ.,;:/#()%-]", texto))
            critico = (
                len(palabras) < 8
                or (len(texto) > 40 and caracteres_invalidos / len(texto) > 0.15)
                or bool(re.search(r"firma|sello|manuscrit", texto, re.IGNORECASE))
            )
            paginas.append({
                "pagina": indice + 1,
                "texto": texto,
                "pagina_blanca": pagina_blanca and not texto_digital and not texto_ocr,
                "critica": critico,
            })
            if progreso:
                progreso(indice + 1, len(documento))
        documento.close()
        texto_completo = normalizar_texto_documento(
            " ".join(item["texto"] for item in paginas if item["texto"])
        )
        return paginas, texto_completo
    except Exception as error:
        global _ocr_last_error
        _ocr_last_error = str(error)
        return [], ""


def separar_pdf_con_textos(contenido, tipo_fallback, paginas_hibridas):
    """Separa bloques usando OCR ya calculado y descarta páginas casi blancas."""
    if PdfReader is None or PdfWriter is None:
        return [{"contenido": contenido, "tipo": tipo_fallback, "paginas": 0}]
    lector = PdfReader(io.BytesIO(contenido))
    grupos = []
    actual = None
    for indice, pagina in enumerate(lector.pages):
        item = (
            paginas_hibridas[indice]
            if indice < len(paginas_hibridas)
            else {"texto": ""}
        )
        texto = item.get("texto", "")
        if item.get("pagina_blanca") and len(texto.strip()) < 8:
            continue
        tipo = clasificar_tipo_documento(texto, "")
        tipo = tipo or (actual["tipo"] if actual else detectar_estado_documento(
            texto, tipo_fallback
        ))
        if actual and actual["tipo"] == tipo:
            actual["paginas"].append(pagina)
            actual["indices"].append(indice)
        else:
            actual = {"tipo": tipo, "paginas": [pagina], "indices": [indice]}
            grupos.append(actual)
    resultado = []
    for grupo in grupos:
        escritor = PdfWriter()
        for pagina in grupo["paginas"]:
            escritor.add_page(pagina)
        salida = io.BytesIO()
        escritor.write(salida)
        resultado.append({
            "contenido": salida.getvalue(),
            "tipo": grupo["tipo"],
            "paginas": len(grupo["paginas"]),
            "paginas_por_seccion": [indice + 1 for indice in grupo["indices"]],
            "texto": normalizar_texto_documento(" ".join(
                paginas_hibridas[indice].get("texto", "")
                for indice in grupo["indices"]
                if indice < len(paginas_hibridas)
            )),
        })
    return resultado


def extraer_texto_por_partes_pdf(contenido, tipo_fallback="Solicitud"):
    """Procesa primero por fragments del expediente para no OCRar el PDF completo."""
    try:
        if not contenido:
            return ""
        partes = separar_pdf_completo(contenido, tipo_fallback)
        if not partes or len(partes) == 1 and partes[0].get("contenido") == contenido:
            return _extraer_texto_pdf(contenido)
        textos = []
        for parte in partes:
            subtexto = parte.get("texto") or _extraer_texto_pdf(parte.get("contenido") or contenido)
            texto_limpio = normalizar_texto_documento(subtexto)
            if texto_limpio:
                textos.append(texto_limpio)
        return normalizar_texto_documento(" ".join(textos))
    except Exception:
        return _extraer_texto_pdf(contenido)


@lru_cache(maxsize=8)
def extraer_texto_pdf(contenido):
    """Devuelve texto cacheado para lecturas repetidas del mismo documento."""
    return _extraer_texto_pdf(contenido)


def extraer_texto_pdf_con_progreso(contenido, progreso):
    """Extrae texto y notifica el avance de OCR sin contaminar la caché."""
    return _extraer_texto_pdf(contenido, progreso=progreso)


def paginas_visuales_para_ia(contenido, inicio=1, maximo=4):
    """Renderiza lotes pequeños para Ollama Vision sin cargar un PDF completo."""
    if fitz is None or not contenido:
        return []
    documento = fitz.open(stream=contenido, filetype="pdf")
    paginas = []
    try:
        limite = min(len(documento), inicio - 1 + maximo)
        for indice in range(inicio - 1, limite):
            pixmap = documento[indice].get_pixmap(
                matrix=fitz.Matrix(0.65, 0.65),
                alpha=False,
            )
            imagen = pixmap.tobytes("jpg", jpg_quality=76)
            paginas.append((indice + 1, imagen))
    finally:
        documento.close()
    return paginas


def normalizar_texto_documento(texto):
    return " ".join(str(texto or "").replace("\xa0", " ").split())


def normalizar_errores_ocr(texto):
    """Corrige errores frecuentes del OCR antes de aplicar reglas documentales."""
    texto = normalizar_texto_documento(texto)
    # Algunos motores devuelven el carácter de reemplazo en lugar de una vocal acentuada.
    texto = texto.replace("\ufffd", "o").replace("?", "o")
    reemplazos = (
        (r"\bempr[_\s]*a\b", "empresa"),
        (r"notificaci.n", "notificación"),
        (r"resoluci.n", "resolución"),
        (r"radicaci.n", "radicación"),
        (r"matr.cula", "matrícula"),
        (r"c.dula", "cédula"),
        (r"direcci.n", "dirección"),
        (r"\bveh[ií]cul[o0]\b", "vehículo"),
        (r"resoluci[oó6]n", "resolución"),
        (r"notificaci[oó6]n", "notificación"),
        (r"ejecutori[aá6]|ejecutor[ií]a", "ejecutoria"),
        (r"radicad[oó6]\s*no\b|radicadono\b", "radicado no"),
        (r"direcci[oó6]n", "dirección"),
        (r"matr[ií1]cula", "matrícula"),
        (r"c[eé3]dula", "cédula"),
        (r"fech[aá]\s*(?:de\s*)?resoluci[oó6]n", "fecha resolución"),
        (r"fech[aá]\s*(?:de\s*)?notificaci[oó6]n", "fecha notificación"),
        (r"fech[aá]\s*(?:de\s*)?recurso", "fecha recurso"),
        (r"fech[aá]\s*(?:de\s*)?radicaci[oó]n", "fecha radicación"),
    )
    for patron, reemplazo in reemplazos:
        texto = re.sub(patron, reemplazo, texto, flags=re.IGNORECASE)
    return texto


def fecha_para_formulario(valor):
    try:
        return datetime.date.fromisoformat(str(valor).strip()) if valor else None
    except (TypeError, ValueError):
        return None


def radicado_padre_valido(valor):
    """Rechaza etiquetas OCR y conserva radicados con evidencia numérica."""
    texto = normalizar_texto_documento(valor).strip().upper()
    if not texto or texto in {"ICADOPADRE", "RADICADOPADRE", "RADICADO PADRE"}:
        return False
    return len(re.sub(r"\D", "", texto)) >= 8


def combinar_datos_detectados(destino, nuevos):
    """Consolida valores encontrados en todas las páginas sin perder evidencia."""
    for campo, valor in (nuevos or {}).items():
        if not valor:
            continue
        if campo in {
            "empresa",
            "propietario",
            "direccion_empresa",
            "direccion_propietario",
            "nueva_empresa",
        } and valor_ocr_sospechoso(valor):
            continue
        if campo == "radicado_padre" and not radicado_padre_valido(valor):
            continue
        actual = destino.get(campo)
        if not actual:
            destino[campo] = valor
            continue
        if campo in {"radicado_padre", "nit", "cedula", "placa"}:
            actual_limpio = re.sub(r"\D", "", str(actual))
            nuevo_limpio = re.sub(r"\D", "", str(valor))
            if len(nuevo_limpio) > len(actual_limpio):
                destino[campo] = valor
        elif len(str(valor)) > len(str(actual)):
            destino[campo] = valor
    return destino


def combinar_campos_ia(destino, resultado_ia):
    """Completa campos y reemplaza solo si la lectura OCR actual es claramente corrupta."""
    if not resultado_ia or campos_formulario_desde_ia is None:
        return destino
    campos_ia = campos_formulario_desde_ia(resultado_ia)
    for campo, valor in campos_ia.items():
        if campo == "tipo_caso":
            if valor in TIPOS_CASO and valor != "Detección automática":
                destino[campo] = valor
            continue
        if campo == "radicado_padre" and not radicado_padre_valido(valor):
            continue
        actual = destino.get(campo)
        if not actual:
            destino[campo] = valor
            continue
        if campo in {
            "empresa",
            "propietario",
            "direccion_empresa",
            "direccion_propietario",
            "nueva_empresa",
        } and valor_ocr_sospechoso(actual):
            destino[campo] = valor
            continue
        if campo in {"nit", "cedula", "radicado_padre", "placa"}:
            actual_limpio = re.sub(r"\D", "", str(actual))
            nuevo_limpio = re.sub(r"\D", "", str(valor))
            if len(nuevo_limpio) > len(actual_limpio):
                destino[campo] = valor
    return destino


def valor_ocr_sospechoso(valor):
    """Detecta residuos de interfaz o etiquetas que no son datos administrativos."""
    texto = normalizar_texto_documento(valor).lower()
    if not texto:
        return False
    patrones = (
        r"\bde\s*:\s*mi\s+preferencia\b",
        r"\b(?:identificacion|identificación)\s+doc\b",
        r"\b(?:nombres?|apellidos?)\s*/?\s*(?:emp|pan)\b",
        r"\bobligaciones\b",
        r"\bseleccione\b|\bseleccionar\b",
    )
    return any(re.search(patron, texto) for patron in patrones)


def normalizar_identificador(valor):
    """Normaliza identificadores OCR y Sheets para comparar formatos distintos."""
    return re.sub(r"[^A-Z0-9]", "", str(valor or "").upper())


def combinar_datos_por_coincidencia(destino, fuente):
    """Completa campos vacíos desde un expediente coincidente, sin sobrescribir."""
    campos = (
        "radicado_padre", "placa", "empresa", "nit", "cedula",
        "propietario", "direccion_empresa", "direccion_propietario",
        "nueva_empresa", "funcionario", "correo", "fecha_solicitud",
        "fecha_radicacion", "resolucion", "fecha_resolucion",
        "tipo_notificacion", "fecha_notificacion", "fecha_ejecutoria",
        "recurso", "fecha_recurso", "tipo_caso", "ubicacion",
    )
    for campo in campos:
        valor_fuente = fuente.get(campo)
        if not valor_fuente:
            continue
        if campo == "radicado_padre" and not radicado_padre_valido(valor_fuente):
            continue
        if not destino.get(campo):
            destino[campo] = valor_fuente
    return destino


def buscar_expediente_local_por_coincidencias(expedientes, datos):
    """Busca un expediente local usando varios identificadores confiables."""
    buscados = {
        campo: normalizar_identificador(datos.get(campo, ""))
        for campo in ("radicado_padre", "placa", "empresa", "nit", "cedula")
    }
    mejor = None
    mejor_puntaje = 0
    for expediente in (expedientes or {}).values():
        candidato_radicado = expediente.get("radicado_padre", "")
        if candidato_radicado and buscados.get("radicado_padre") and not radicado_padre_valido(candidato_radicado):
            continue
        puntaje = 0
        for campo, valor in buscados.items():
            if campo == "radicado_padre" and not radicado_padre_valido(expediente.get(campo, "")):
                continue
            existente = normalizar_identificador(expediente.get(campo, ""))
            if valor and existente and valor == existente:
                puntaje += 4 if campo == "radicado_padre" else 2
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = expediente, puntaje
    return mejor if mejor_puntaje >= 2 else None


def enrutar_documento_cargado(datos, es_complemento, drive_service=None):
    """Determina la ruta del archivo antes de habilitar el guardado."""
    datos = datos or {}
    radicado = datos.get("radicado_padre", "")
    placa = datos.get("placa", "")
    fecha = datos.get("fecha_solicitud", "")
    local = buscar_expediente_local_por_coincidencias(
        st.session_state.get("db_expedientes", {}),
        datos,
    )
    remoto = (
        buscar_carpeta_expediente_drive(
            drive_service,
            fecha,
            radicado,
            placa,
        )
        if drive_service and fecha and radicado
        else None
    )
    if local or remoto:
        return {
            "estado": "ACTUALIZADO_CON_COMPLEMENTO" if es_complemento else "EXPEDIENTE_EXISTENTE",
            "carpeta_drive_id": remoto,
            "expediente_local": local,
        }
    if es_complemento:
        return {
            "estado": "PENDIENTE_VINCULACION",
            "carpeta_drive_id": (
                carpeta_drive_para_complementos_sin_vincular(drive_service, placa)
                if drive_service and placa
                else None
            ),
            "expediente_local": None,
        }
    return {
        "estado": "EXPEDIENTE_PRINCIPAL",
        "carpeta_drive_id": None,
        "expediente_local": None,
    }


def buscar_expedientes_local_consulta(expedientes, campo, criterio):
    """Busca expedientes locales por cualquiera de los campos consultables."""
    criterio = str(criterio or "").strip().upper()
    if not criterio:
        return []
    resultados = []
    for expediente in (expedientes or {}).values():
        if campo == "radicado_padre":
            valor = expediente.get("radicado_padre", "")
        elif campo == "fecha_solicitud":
            valor = expediente.get("fecha_solicitud", "")
        else:
            valor = expediente.get(campo, "")
        if criterio in str(valor or "").strip().upper():
            resultados.append(expediente)
    return resultados


def buscar_expedientes_sheet_consulta(service, campo, criterio):
    """Busca registros remotos usando la misma tabla de Sheets."""
    if not service or not criterio:
        return []
    filas = leer_registros_sheets(service)
    if not filas:
        return []
    encabezados = [normalizar_campo_sheet(valor) for valor in filas[0]]
    resultados = []
    for numero, fila in enumerate(filas[1:], start=2):
        registro = datos_registro_sheet({
            "fila": fila,
            "numero": numero,
            "encabezados": encabezados,
        })
        valor = registro.get(campo, "")
        if str(criterio).strip().upper() in str(valor or "").strip().upper():
            registro = normalizar_expediente_consulta(registro)
            registro["fila_sheet"] = numero
            resultados.append(registro)
    return resultados


def normalizar_expediente_consulta(expediente):
    """Completa la forma mínima para mostrar registros locales o remotos."""
    datos = dict(expediente or {})
    datos.setdefault("radicado_padre", "")
    datos.setdefault("placa", "")
    datos.setdefault("ubicacion", "")
    datos.setdefault("estado", "Registrado en Google Sheets")
    datos.setdefault("modificado_por", "")
    datos.setdefault("ultima_modificacion", "")
    datos.setdefault("tipo_caso", "")
    datos.setdefault("canvas_paginas", [])
    datos.setdefault("documentos_esperados", [])
    return datos


def clave_expediente_consulta(expediente):
    """Construye una clave estable para deduplicar resultados locales y remotos."""
    datos = normalizar_expediente_consulta(expediente)
    radicado = str(datos.get("radicado_padre", "")).strip().upper()
    if radicado:
        return ("radicado", radicado)
    identificador = str(datos.get("id", "")).strip().upper()
    if identificador:
        return ("id", identificador)
    return (
        "datos",
        tuple(
            str(datos.get(campo, "")).strip().upper()
            for campo in ("placa", "fecha_solicitud", "empresa", "nit", "cedula", "ubicacion")
        ),
    )


def ocr_respaldo_primera_pagina(contenido):
    """Relee la primera página en escala de grises si faltan placa o fecha."""
    if fitz is None or RapidOCR is None:
        return ""
    try:
        documento = fitz.open(stream=contenido, filetype="pdf")
        if not documento.page_count:
            documento.close()
            return ""
        pixmap = documento.load_page(0).get_pixmap(
            matrix=fitz.Matrix(1.8, 1.8),
            colorspace=fitz.csGRAY,
            alpha=False,
        )
        documento.close()
        global _ocr_engine
        if _ocr_engine is None:
            _ocr_engine = crear_motor_ocr()
        resultado, _ = _ocr_engine(pixmap.tobytes("png"))
        return normalizar_texto_documento(
            " ".join(str(elemento[1]) for elemento in (resultado or []))
        )
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        st.warning(f"No fue posible ejecutar el OCR de respaldo: {error}")
        return ""


def extraer_datos_pdf(contenido, texto=None):
    """Extrae metadatos de PDFs digitales; devuelve vacío si es un escaneo sin OCR."""
    texto = normalizar_errores_ocr(
        extraer_texto_pdf(contenido) if texto is None else texto
    )
    patron_placa = r"\b[A-Z]{3}-?\d{3}\b"
    patron_fecha = (
        r"\b(?:0[1-9]|[12][0-9]|3[01])[-/]"
        r"(?:0[1-9]|1[012])[-/](?:20\d{2})\b"
    )
    if (
        not re.search(patron_placa, texto, flags=re.IGNORECASE)
        or not re.search(patron_fecha, texto, flags=re.IGNORECASE)
    ):
        texto_respaldo = ocr_respaldo_primera_pagina(contenido)
        if texto_respaldo:
            texto = normalizar_errores_ocr(f"{texto} {texto_respaldo}")
    if not texto:
        return {}
    patrones = {
        "radicado_padre": [
            r"\b(?:rad|radicado|radicaci[oó]n|orfeo)\s*(?:padre|principal)?\s*(?:no\.?)?\s*[:.#\-]?\s*([A-Z0-9][A-Z0-9./\-]{7,})\b",
            r"\b(20\d{16})\b",
        ],
        "placa": [
            r"(?:placa|placas|matr[ií]cula|matricula|veh[ií]culo)\s*[:#\-]?\s*([A-Z]{3}\s*[-]?\s*\d{3})\b",
            r"\b([A-Z]{3}-?\d{3})\b",
        ],
        "fecha_solicitud": [
            r"(?:fecha\s*(?:de\s*)?(?:creaci[oó]n|radicaci[oó]n|solicitud|recibido))\s*[:#\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"\b(\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s+de\s+20\d{2})\b",
            r"\b(\d{1,2}\s+(?:de\s+)?(?:ene(?:ro)?|feb(?:rero)?|mar(?:zo)?|"
            r"abr(?:il)?|may(?:o)?|jun(?:io)?|jul(?:io)?|ago(?:sto)?|"
            r"sep(?:tiembre)?|set(?:iembre)?|oct(?:ubre)?|nov(?:iembre)?|"
            r"dic(?:iembre)?)\s+(?:de\s+)?20\d{2})\b",
            r"\b((?:0[1-9]|[12][0-9]|3[01])[-/](?:0[1-9]|1[012])[-/](?:20\d{2}))\b",
        ],
        "fecha_radicacion": [
            r"(?:fecha\s+de\s+)?radicaci[oó]n\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"(?:fecha\s+de\s+)?radicaci[oó]n\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}\s+(?:de\s+)?[A-Za-záéíóú]+(?:\s+de)?\s+20\d{2})",
        ],
        "fecha_recurso": [
            r"fecha\s+(?:de\s+)?recurso\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"fecha\s+(?:de\s+)?recurso\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}\s+(?:de\s+)?[A-Za-záéíóú]+(?:\s+de)?\s+20\d{2})",
        ],
        "fecha_resolucion": [
            r"(?:fecha\s+(?:de\s+)?resoluci[oó]n|resoluci[oó]n[^.]{0,80}?\b(?:del|de fecha))\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"fecha\s+(?:de\s+)?resoluci[oó]n\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}\s+(?:de\s+)?[A-Za-záéíóú]+(?:\s+de)?\s+20\d{2})",
        ],
        "fecha_notificacion": [
            r"(?:fecha\s+(?:de\s+)?notificaci[oó]n|notificaci[oó]n[^.]{0,80}?\b(?:del|de fecha))\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"fecha\s+(?:de\s+)?notificaci[oó]n\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}\s+(?:de\s+)?[A-Za-záéíóú]+(?:\s+de)?\s+20\d{2})",
        ],
        "fecha_ejecutoria": [
            r"fecha\s+(?:de\s+)?(?:constancia\s+de\s+)?ejecutoria\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"fecha\s+(?:de\s+)?(?:constancia\s+de\s+)?ejecutoria\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}\s+(?:de\s+)?[A-Za-záéíóú]+(?:\s+de)?\s+20\d{2})",
        ],
        "correo": [
            r"\b([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})\b",
        ],
        "nit": [
            r"\b(?:NIT|NIT\.?|n\.i\.t\.?)\s*[:#.\-]?\s*([0-9][0-9.\s]{5,14}(?:\s*[\-–]\s*[0-9])?)\b",
        ],
        "cedula": [
            r"\b(?:c[eé]dula|c\.c\.|identificaci[oó]n)\s*[:#\-]?\s*([0-9][0-9.\s]{5,14})\b",
        ],
        "empresa": [
            r"\bempresa\s*[:#\-]?\s*([^|]{3,100}?)(?=\s+(?:NIT|propietario|placa|radicado|resoluci[oó]n|correo)\b|$)",
            r"\bempresa\s+de\s+transportes?\s+([^|]{3,100}?)(?=\s+(?:NIT|contrato|resoluci[oó]n|placa)\b|$)",
            r"\b(EMPRESA\s+DE\s+TRANSPORTES?\s+[A-Z0-9ÁÉÍÓÚÑ .,&-]{4,100}?)(?=\s+(?:NIT|RESOLUCI|CONTRATO|PLACA)\b|$)",
        ],
        "propietario": [
            r"\bpropietario(?:\s+del\s+veh[ií]culo)?\s*[:#\-]?\s*([^|]{3,100}?)(?=\s+(?:c[eé]dula|CC|placa|direcci[oó]n|resoluci[oó]n|correo|NIT)\b|$)",
            r"\b(?:representante\s+legal|gerente)\s*[:#\-]?\s*([A-ZÁÉÍÓÚÑ][^|]{3,100}?)(?=\s+(?:identificado|con\s+c[eé]dula|NIT|solicito)\b)",
        ],
        "direccion_empresa": [
            r"\bdirecci[oó]n\s+(?:de\s+)?empresa\s*[:#\-]?\s*([^|]{5,150}?)(?=\s+(?:direcci[oó]n|propietario|NIT|radicado|nueva\s+empresa)\b|$)",
        ],
        "direccion_propietario": [
            r"\bdirecci[oó]n\s+(?:del\s+)?propietario\s*[:#\-]?\s*([^|]{5,150}?)(?=\s+(?:propietario|c[eé]dula|placa|radicado|nueva\s+empresa)\b|$)",
        ],
        "nueva_empresa": [
            r"\bnueva\s+empresa\s*[:#\-]?\s*([^|]{3,120}?)(?=\s+(?:NIT|radicado|placa|fecha)\b|$)",
        ],
        "tipo_notificacion": [
            r"\bnotificaci[oó]n\s+(?:por\s+)?(personal|citación|citaci[oó]n|aviso|publicaci[oó]n|electrónica|electronica|correo)\b",
        ],
        "funcionario": [
            r"\bfuncionario\s+(?:que\s+)?desvincula\s*[:#\-]\s*([^|]{3,100}?)(?=\s+(?:fecha|observaci[oó]n|estado)\b|$)",
        ],
        "recurso": [
            r"\b(recurso(?:\s+de\s+(?:reposici[oó]n|apelaci[oó]n))?)\b",
        ],
        "resolucion": [
            r"\b(?:resoluci[oó]n|acto\s+administrativo)\s*(?:No\.?|N[°ºo]\.?)?\s*[:#\-]?\s*([A-Z0-9./\-]{4,40})\b",
        ],
    }
    meses = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
        "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
        "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
        "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
        "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11,
        "dic": 12,
    }
    datos = {}
    for campo, opciones in patrones.items():
        for patron in opciones:
            coincidencia = re.search(patron, texto, flags=re.IGNORECASE)
            if coincidencia:
                valor = coincidencia.group(1).strip(" .,:;")
                if campo == "radicado_padre":
                    valor = re.sub(r"\s+", "", valor).upper()
                if campo == "placa":
                    valor = re.sub(r"[\s-]", "", valor).upper()
                elif campo.startswith("fecha_"):
                    fecha_texto = valor.lower()
                    fecha_larga = re.fullmatch(
                        r"(\d{1,2})\s+(?:de\s+)?([a-záéíóú]+)\s+(?:de\s+)?(20\d{2})",
                        fecha_texto,
                    )
                    if fecha_larga:
                        dia, mes, anio = fecha_larga.groups()
                        valor = f"{anio}-{meses.get(mes, 0):02d}-{int(dia):02d}"
                    else:
                        partes = re.split(r"[/-]", valor)
                        if len(partes) == 3:
                            if len(partes[0]) == 4:
                                valor = "-".join(partes)
                            else:
                                dia, mes, anio = partes
                                if len(anio) == 2:
                                    anio = "20" + anio
                                valor = f"{anio}-{mes.zfill(2)}-{dia.zfill(2)}"
                elif campo == "nit":
                    valor = re.sub(r"\D", "", valor)
                elif campo == "cedula":
                    valor = re.sub(r"\D", "", valor)
                elif campo in {
                    "correo", "nit", "cedula", "empresa", "propietario",
                    "direccion_empresa", "direccion_propietario", "nueva_empresa",
                    "tipo_notificacion", "funcionario", "resolucion",
                }:
                    valor = re.sub(r"\s+", " ", valor).strip()
                datos[campo] = valor
                break
    if not datos.get("fecha_radicacion"):
        coincidencia_fecha_radicacion = re.search(
            r"radicaci[oó?]n[^0-9]{0,30}"
            r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            texto,
            flags=re.IGNORECASE,
        )
        if coincidencia_fecha_radicacion:
            dia_mes_anio = coincidencia_fecha_radicacion.group(1).split("/")
            if len(dia_mes_anio) == 1:
                dia_mes_anio = coincidencia_fecha_radicacion.group(1).split("-")
            if len(dia_mes_anio) == 3:
                if len(dia_mes_anio[0]) == 4:
                    datos["fecha_radicacion"] = "-".join(dia_mes_anio)
                else:
                    dia, mes, anio = dia_mes_anio
                    datos["fecha_radicacion"] = (
                        f"{'20' + anio if len(anio) == 2 else anio}-"
                        f"{mes.zfill(2)}-{dia.zfill(2)}"
                    )
    coincidencia_empresa = re.search(
        r"\bEMPRESA\s+DE\s+TRANSPORTES?\s+"
        r"[A-Z0-9ÁÉÍÓÚÑ .,&-]{4,100}",
        texto,
        flags=re.IGNORECASE,
    )
    if coincidencia_empresa:
        empresa_detectada = re.split(
            r"\s+(?:NIT|RESOLUCI\w*|NOTIFICACI\w*|CONTRATO|PLACA)\b",
            coincidencia_empresa.group(0),
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" .,:;-")
        if len(empresa_detectada) >= len(str(datos.get("empresa", ""))):
            datos["empresa"] = empresa_detectada
    if datos.get("empresa"):
        datos["empresa"] = re.split(
            r"\s+(?:NIT|RESOLUCI\w*|NOTIFICACI\w*|CONTRATO|PLACA)\b",
            str(datos["empresa"]),
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" .,:;-")
    radicado_extraido = str(datos.get("radicado_padre", "")).strip()
    if radicado_extraido and not radicado_padre_valido(radicado_extraido):
        datos.pop("radicado_padre", None)
        datos.pop("radicado_revision", None)
        radicado_extraido = ""
    if radicado_extraido and not re.fullmatch(r"20\d{16}", radicado_extraido):
        datos["radicado_revision"] = (
            f"Revisar radicado detectado: {radicado_extraido}. "
            "Confirma el número completo en el formulario."
        )
    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", str(datos.get("resolucion", ""))):
        coincidencia_resolucion = re.search(
            r"\bresoluci[oó]n\s+(?:No\.?|N[°ºo]\.?)\s*[:#\-]?\s*([A-Z0-9-]{3,40})\b",
            texto,
            flags=re.IGNORECASE,
        )
        if coincidencia_resolucion:
            datos["resolucion"] = coincidencia_resolucion.group(1).strip()

    def fecha_en_contexto(etiquetas):
        etiqueta = "|".join(etiquetas)
        coincidencia = re.search(
            rf"(?:{etiqueta}).{{0,100}}?"
            r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            texto,
            flags=re.IGNORECASE,
        )
        if not coincidencia:
            return ""
        valor = coincidencia.group(1)
        partes = re.split(r"[/-]", valor)
        if len(partes) != 3:
            return ""
        if len(partes[0]) == 4:
            return "-".join(partes)
        dia, mes, anio = partes
        return f"{'20' + anio if len(anio) == 2 else anio}-{mes.zfill(2)}-{dia.zfill(2)}"

    for campo, etiquetas in {
        "fecha_resolucion": (r"resoluci[oó]n",),
        "fecha_notificacion": (r"notificaci[oó]n",),
        "fecha_ejecutoria": (r"ejecutoria",),
        "fecha_recurso": (r"recurso",),
    }.items():
        if not datos.get(campo):
            fecha_contexto = fecha_en_contexto(etiquetas)
            if fecha_contexto:
                datos[campo] = fecha_contexto
    if not datos.get("fecha_solicitud"):
        fecha_solicitud = re.search(
            r"\b(\d{1,2}[/-]\d{1,2}[/-]20\d{2}|20\d{2}[/-]\d{1,2}[/-]\d{1,2})\b",
            texto,
        )
        if fecha_solicitud:
            valor = fecha_solicitud.group(1)
            partes = re.split(r"[/-]", valor)
            if len(partes) == 3:
                if len(partes[0]) == 4:
                    datos["fecha_solicitud"] = "-".join(partes)
                else:
                    dia, mes, anio = partes
                    datos["fecha_solicitud"] = f"{anio}-{mes.zfill(2)}-{dia.zfill(2)}"
    for campo in (
        "empresa",
        "propietario",
        "direccion_empresa",
        "direccion_propietario",
        "nueva_empresa",
    ):
        if datos.get(campo) and valor_ocr_sospechoso(datos[campo]):
            datos.pop(campo, None)
    return datos


def unir_archivos_pdf(archivos):
    """Une PDF en el orden recibido y devuelve sus bytes, o None si no es posible."""
    if PdfReader is None or PdfWriter is None or not archivos:
        return None
    escritor = PdfWriter()
    try:
        for contenido in archivos:
            lector = PdfReader(io.BytesIO(contenido))
            for pagina in lector.pages:
                escritor.add_page(pagina)
        salida = io.BytesIO()
        escritor.write(salida)
        return salida.getvalue()
    except Exception:
        return None


def convertir_imagen_a_pdf(contenido, nombre):
    """Convierte una imagen cargada a PDF para integrarla al expediente."""
    if Image is None:
        raise RuntimeError(
            "La conversión de imágenes requiere la dependencia Pillow."
        )
    try:
        with Image.open(io.BytesIO(contenido)) as imagen:
            imagen_rgb = imagen.convert("RGB")
            salida = io.BytesIO()
            imagen_rgb.save(salida, format="PDF", resolution=150.0)
            return salida.getvalue()
    except (OSError, ValueError) as error:
        raise ValueError(f"No se pudo convertir {nombre} a PDF: {error}") from error


@lru_cache(maxsize=4)
def detectar_estado_documento(texto, tipo_fallback="Solicitud"):
    """Devuelve si un PDF es un expediente completo o un complemento."""
    evidencia = normalizar_errores_ocr(texto or "").lower()
    if not evidencia:
        return "Expediente completo" if str(tipo_fallback or "").strip() == "Expediente completo" else "Complemento"
    multi_seccion = re.search(
        r"\b(?:solicitud|petici[oó]n)\b.*\b(?:resoluci[oó]n|recurso|notificaci[oó]n|citaci[oó]n|ejecutoria|consulta\s+qx)\b|"
        r"\b(?:resoluci[oó]n|recurso|notificaci[oó]n|citaci[oó]n|ejecutoria|consulta\s+qx)\b.*\b(?:solicitud|petici[oó]n)\b",
        evidencia,
    )
    if multi_seccion:
        return "Expediente completo"
    if re.search(r"\b(?:solicitud|petici[oó]n|consulta\s+qx|requerimiento|desistimiento|recurso|resoluci[oó]n|notificaci[oó]n|citaci[oó]n|constancia\s+de\s+ejecutoria)\b", evidencia):
        return "Complemento"
    return "Expediente completo" if str(tipo_fallback or "").strip() == "Expediente completo" else "Complemento"


@lru_cache(maxsize=2)
def separar_pdf_completo(contenido, tipo_fallback):
    """Quita páginas vacías y separa un PDF por bloques documentales detectables."""
    global _ocr_cache_writes_pending
    if PdfReader is None or PdfWriter is None:
        return [{"contenido": contenido, "tipo": tipo_fallback, "paginas": 0}]
    try:
        lector = PdfReader(io.BytesIO(contenido))
        documento_visual = fitz.open(stream=contenido, filetype="pdf") if fitz else None
        grupos = []
        actual = None
        textos_paginas = {}
        for numero_pagina, pagina in enumerate(lector.pages):
            texto = " ".join((pagina.extract_text() or "").split())
            pixmap = None
            if documento_visual:
                pixmap = documento_visual.load_page(numero_pagina).get_pixmap(
                    matrix=fitz.Matrix(1.0, 1.0),
                    alpha=False,
                )
            if len(texto) < 8 and pagina_pixeles_blancos(pixmap):
                continue
            texto_ocr = ""
            if documento_visual and not pagina_pixeles_blancos(pixmap):
                texto_ocr = obtener_texto_ocr_pagina(
                    contenido,
                    numero_pagina,
                    documento_visual.load_page(numero_pagina),
                )
            texto = " ".join(parte for parte in (texto, texto_ocr) if parte)
            textos_paginas[numero_pagina] = texto
            tipo_detectado = clasificar_tipo_documento(texto, "")
            tipo = tipo_detectado or (actual["tipo"] if actual else detectar_estado_documento(texto, tipo_fallback))
            if actual and actual["tipo"] == tipo:
                actual["paginas"].append(pagina)
                actual["indices"].append(numero_pagina)
            else:
                actual = {
                    "tipo": tipo,
                    "paginas": [pagina],
                    "indices": [numero_pagina],
                }
                grupos.append(actual)
        if documento_visual:
            documento_visual.close()
        if _ocr_cache_writes_pending:
            _guardar_cache_ocr()
            _ocr_cache_writes_pending = 0
        if not grupos:
            return []
        resultado = []
        for grupo in grupos:
            escritor = PdfWriter()
            for pagina in grupo["paginas"]:
                escritor.add_page(pagina)
            salida = io.BytesIO()
            escritor.write(salida)
            resultado.append({
                "contenido": salida.getvalue(),
                "tipo": grupo["tipo"],
                "paginas": len(grupo["paginas"]),
                "paginas_por_seccion": [
                    indice + 1 for indice in grupo["indices"]
                ],
                "texto": normalizar_texto_documento(
                    " ".join(
                        textos_paginas.get(indice, "")
                        for indice in grupo["indices"]
                    )
                ),
            })
        return resultado
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        st.warning(
            "No fue posible clasificar todas las páginas del PDF; "
            f"se conservará el expediente completo sin perder hojas: {error}"
        )
        return [{
            "contenido": contenido,
            "tipo": tipo_fallback or "Expediente completo",
            "paginas": len(PdfReader(io.BytesIO(contenido)).pages),
        }]


def pagina_pdf_vacia(contenido, numero_pagina):
    """Detecta hojas blancas sin OCR, usando texto y una muestra de píxeles."""
    if fitz is None:
        return False
    try:
        documento = fitz.open(stream=contenido, filetype="pdf")
        pagina = documento.load_page(numero_pagina)
        pixmap = pagina.get_pixmap(matrix=fitz.Matrix(0.35, 0.35), alpha=False)
        muestras = pixmap.samples
        if not muestras:
            documento.close()
            return True
        canales = pixmap.n
        pixeles_oscuros = 0
        total_pixeles = len(muestras) // canales
        for indice in range(0, len(muestras), canales):
            if min(muestras[indice:indice + 3]) < 245:
                pixeles_oscuros += 1
        documento.close()
        return total_pixeles == 0 or (
            pixeles_oscuros / total_pixeles
        ) < BLANK_PAGE_DARK_PIXEL_RATIO
    except Exception:
        return False


def pagina_pixeles_blancos(pixmap):
    if pixmap is None or not pixmap.samples:
        return True
    canales = pixmap.n
    total_pixeles = len(pixmap.samples) // canales
    muestras_por_pixel = max(canales * 4, 1)
    pixeles_oscuros = sum(
        1
        for indice in range(0, len(pixmap.samples), muestras_por_pixel)
        if min(pixmap.samples[indice:indice + 3]) < 245
    )
    return total_pixeles == 0 or (
        pixeles_oscuros / max(total_pixeles // 4, 1)
    ) < BLANK_PAGE_DARK_PIXEL_RATIO


def extraer_texto_ocr_pixmap(pixmap):
    """Extrae una muestra OCR de una página para clasificar su sección."""
    if pixmap is None or RapidOCR is None:
        return ""
    try:
        global _ocr_engine
        if _ocr_engine is None:
            _ocr_engine = crear_motor_ocr()
        resultado, _ = _ocr_engine(pixmap.tobytes("png"))
        return normalizar_texto_documento(
            " ".join(str(elemento[1]) for elemento in (resultado or []))
        )
    except Exception:
        return ""


def clasificar_tipo_documento(texto, tipo_fallback):
    evidencia = normalizar_errores_ocr(texto).lower()
    if re.search(
        r"\bdesistim\w*\b|\bdeclara(?:r)?\s+el\s+desistimiento\b",
        evidencia,
    ):
        return "Desistimiento"
    puntuaciones = {
        "Desistimiento": [
            (9, r"\bdesistimiento\b|declara(?:r)?\s+el\s+desistimiento"),
            (3, r"\bdesistim\w*"),
        ],
        "Resolución del recurso": [
            (14, r"resoluci[oó]n\s+del\s+recurso|resolucion\s+del\s+recurso|recurso\s+resuelto"),
        ],
        "Citación del recurso": [
            (14, r"citaci[oó]n\s+del\s+recurso|citacion\s+del\s+recurso"),
        ],
        "Notificación del recurso": [
            (14, r"notificaci[oó]n\s+(?:del|de la)\s+recurso|notificacion\s+(?:del|de la)\s+recurso"),
        ],
        "Resolución": [
            (10, r"\bresoluci[oó]n\b|\bresolucion\b\s*(?:no|n[°ºo])?\s*[:#\-.]?\s*\w+"),
            (9, r"\bpor\s+la\s+cual\b.*\bdesvincul"),
            (3, r"\bresoluci[oó]n\b|\bresolucion\b|acto\s+administrativo|resuelve"),
        ],
        "Requerimiento": [
            (8, r"\brequerimient[oó]\b|\brequerimiento\b|requerido\s+para|requerir"),
        ],
        "Notificación personal": [
            (12, r"notificaci[oó]n\s+personal|notificacion\s+personal|personalmente\s+notificado"),
        ],
        "Notificación por aviso": [
            (10, r"notificaci[oó]n\s+por\s+aviso|notificacion\s+por\s+aviso|aviso\s+de\s+notificaci"),
        ],
        "Notificación por publicación web": [
            (10, r"notificaci[oó]n\s+por\s+publicaci[oó]n\s+web|notificacion\s+por\s+publicacion\s+web|publicaci[oó]n\s+web"),
        ],
        "Oficio de citación": [
            (8, r"oficio\s+de\s+citaci[oó]n|citacion\s+de\s+la\s+empresa|citacion\s+al\s+propietario|oficio\s+de\s+citado"),
        ],
        "Constancia de ejecutoria": [
            (10, r"constancia\s+de\s+ejecutoria"),
            (7, r"\bejecutoria\b|\bfirmeza\b|\bconstancia\b"),
        ],
        "Remisión a registro": [
            (12, r"remisi[oó]n\s+(?:a|al)\s+registro|remision\s+(?:a|al)\s+registro"),
            (8, r"registro\s+automotor|remitir\s+al\s+registro"),
        ],
        "Recurso": [
            (10, r"recurso\s+de\s+(?:reposici[oó]n|apelaci[oó]n)"),
            (8, r"interpuso\s+(?:un\s+)?recurso|present[oó]\s+(?:un\s+)?recurso"),
            (3, r"\brecurso\b|impugn"),
        ],
        "Consulta QX": [
            (12, r"consulta\s+de\s+verificaci[oó]n\s+de\s+propiedad|consulta\s+de\s+propiedad|verificaci[oó]n\s+de\s+propiedad|consulta\s+qx|verificaci[oó]n\s+qx"),
        ],
        "Solicitud": [
            (10, r"derecho\s+de\s+petici[oó]n|derecho\s+de\s+peticion|solicitud\s+de\s+desvinculaci[oó]n"),
            (8, r"\bsolicito\b.*\bdesvincul"),
            (3, r"\bsolicitud\b|\bpetici[oó]n\b|\bpeticion\b"),
        ],
    }
    mejor_tipo = None
    mejor_puntaje = 0
    for tipo, reglas in puntuaciones.items():
        puntaje = sum(
            puntos for puntos, patron in reglas
            if re.search(patron, evidencia, flags=re.IGNORECASE | re.DOTALL)
        )
        if puntaje > mejor_puntaje:
            mejor_tipo = tipo
            mejor_puntaje = puntaje
    return mejor_tipo or tipo_fallback


def tipos_documentales_detectados(texto, tipo_fallback):
    """Devuelve todos los tipos mencionados en un expediente unificado."""
    evidencia = normalizar_errores_ocr(texto).lower()
    reglas = [
        ("Desistimiento", r"desistim|desiste"),
        ("Recurso", r"\brecurso\b|reposici[oó]n|reposicion|apelaci[oó]n|apelacion|impugn|interpone\s+recurso|recurre"),
        ("Resolución del recurso", r"resoluci[oó]n\s+del\s+recurso|resolucion\s+del\s+recurso|recurso\s+resuelto"),
        ("Citación del recurso", r"citaci[oó]n\s+(?:del|de la)\s+recurso|citacion\s+(?:del|de la)\s+recurso"),
        ("Notificación del recurso", r"notificaci[oó]n\s+(?:del|de la)\s+recurso|notificacion\s+(?:del|de la)\s+recurso"),
        ("Resolución", r"\bresoluci[oó]n\b|\bresolucion\b|acto\s+administrativo|resuelve"),
        ("Requerimiento", r"requerimient[oó]|requerimiento"),
        ("Oficio de citación", r"oficio\s+de\s+citaci[oó]n|citaci[oó]n\s+al\s+propietario|citaci[oó]n\s+de\s+la\s+empresa|citacion\s+al\s+propietario"),
        ("Notificación personal", r"notificaci[oó]n\s+personal|notificacion\s+personal|personalmente\s+notificado"),
        ("Notificación por aviso", r"notificaci[oó]n\s+por\s+aviso|notificacion\s+por\s+aviso|aviso\s+de\s+notificaci"),
        ("Notificación por publicación web", r"notificaci[oó]n\s+por\s+publicaci[oó]n\s+web|notificacion\s+por\s+publicacion\s+web|publicaci[oó]n\s+web"),
        ("Notificación", r"\bnotificaci[oó]n\b|\bnotificacion\b"),
        ("Constancia de ejecutoria", r"ejecutoria|firmeza|constancia.*firme"),
        ("Remisión a registro", r"remisi[oó]n\s+(?:a|al)\s+registro|registro\s+automotor|remitir\s+al\s+registro"),
        ("Consulta QX", r"consulta\s+de\s+verificaci[oó]n\s+de\s+propiedad|consulta\s+de\s+propiedad|verificaci[oó]n\s+de\s+propiedad|consulta\s+qx|verificaci[oó]n\s+qx"),
        ("Solicitud", r"derecho de petici[oó]n|derecho de peticion|solicito|solicitud|petici[oó]n|peticion"),
    ]
    detectados = {
        tipo for tipo, patron in reglas
        if re.search(patron, evidencia)
        and not (
            tipo == "Recurso"
            and re.search(
                r"\bsin\s+recurso\b|no\s+interpuso|no\s+present[oó]|"
                r"sin\s+interponer",
                evidencia,
            )
        )
    }
    tipos_especificos = {
        "Notificación personal",
        "Notificación por aviso",
        "Notificación por publicación web",
    }
    if detectados & tipos_especificos:
        detectados.discard("Notificación")
    return detectados or {tipo_fallback}


def normalizar_tipo_documental(valor):
    """Convierte variantes OCR/IA al nombre documental canónico del checklist."""
    texto = normalizar_errores_ocr(valor).lower()
    texto = re.sub(r"\s+", " ", texto).strip()
    if not texto:
        return ""
    if re.search(r"desistim|desiste", texto):
        return "Desistimiento"
    if re.search(r"consulta.*(?:qx|propiedad)|verificaci[oó]n.*(?:qx|propiedad)|\bqx\b|\brunt\b", texto):
        return "Consulta QX"
    if re.search(r"resoluci[oó]n.*recurso|recurso.*resuelto", texto):
        return "Resolución del recurso"
    if re.search(r"citaci[oó]n.*recurso", texto):
        return "Citación del recurso"
    if re.search(r"notificaci[oó]n.*recurso", texto):
        return "Notificación del recurso"
    if re.search(r"remisi[oó]n.*registro|registro automotor|remitir.*registro", texto):
        return "Remisión a registro"
    if re.search(r"constancia.*ejecutoria|constancia.*firmeza|\bejecutoria\b|\bfirmeza\b", texto):
        return "Constancia de ejecutoria"
    if re.search(r"notificaci[oó]n.*personal|personalmente notificado", texto):
        return "Notificación personal"
    if re.search(r"notificaci[oó]n.*aviso|aviso de notificaci[oó]n", texto):
        return "Notificación por aviso"
    if re.search(r"notificaci[oó]n.*(?:publicaci[oó]n|web)|publicaci[oó]n.*web|edicto", texto):
        return "Notificación por publicación web"
    if re.search(r"\bnotificaci[oó]n\b|\bnotificacion\b", texto):
        return "Notificación"
    if re.search(r"oficio.*citaci[oó]n|citaci[oó]n.*(?:empresa|propietario)|citado", texto):
        return "Oficio de citación"
    if re.search(r"requerimient|requerido para|requerir", texto):
        return "Requerimiento"
    if re.search(r"\bresoluci[oó]n\b|acto administrativo|resuelve", texto):
        return "Resolución"
    if re.search(r"\brecurso\b|reposici[oó]n|apelaci[oó]n|impugn|interpone|recurre", texto):
        return "Recurso"
    if re.search(r"solicitud|petici[oó]n|derecho de petici[oó]n|solicita", texto):
        return "Solicitud"
    return ""


def normalizar_tipo_caso(valor):
    """Acepta variantes de Ollama y devuelve solo un desenlace válido."""
    texto = normalizar_errores_ocr(valor).lower()
    if re.search(r"desistim|desiste", texto):
        return "Desistimiento"
    if re.search(r"sin\s+recurso|no\s+(?:se\s+)?interpuso\s+recurso", texto):
        return "Sin recurso"
    if re.search(r"con\s+recurso|recurso", texto):
        return "Con recurso"
    return ""


def tipos_documentales_desde_ia(resultado):
    """Obtiene tipos canónicos de la lista documental devuelta por Ollama."""
    detectados = set()
    for documento in (resultado or {}).get("documentos_detectados") or []:
        if isinstance(documento, dict):
            tipo = normalizar_tipo_documental(documento.get("tipo"))
        else:
            tipo = normalizar_tipo_documental(documento)
        if tipo:
            detectados.add(tipo)
    return detectados


def aplicar_clasificacion_ia_a_partes(partes, resultado):
    """Ajusta el tipo de cada bloque usando las páginas que identificó Ollama."""
    por_pagina = {}
    for seccion in (resultado or {}).get("paginas_por_seccion") or []:
        if not isinstance(seccion, dict):
            continue
        tipo = normalizar_tipo_documental(seccion.get("tipo"))
        if not tipo:
            continue
        for pagina in seccion.get("paginas") or []:
            try:
                por_pagina[int(pagina)] = tipo
            except (TypeError, ValueError):
                continue
    for documento in (resultado or {}).get("documentos_detectados") or []:
        if not isinstance(documento, dict):
            continue
        tipo = normalizar_tipo_documental(documento.get("tipo"))
        if not tipo:
            continue
        paginas = documento.get("paginas") or []
        if not paginas:
            paginas = [
                int(valor)
                for valor in re.findall(
                    r"\b(?:p[aá]gina|p[aá]ginas?)\s*[:#]?\s*(\d+)",
                    str(documento.get("paginas_o_evidencia", "")),
                    flags=re.IGNORECASE,
                )
            ]
        for pagina in paginas:
            try:
                por_pagina[int(pagina)] = tipo
            except (TypeError, ValueError):
                continue
    for parte in partes or []:
        paginas = parte.get("paginas_por_seccion") or []
        tipos = [por_pagina.get(int(pagina)) for pagina in paginas if str(pagina).isdigit()]
        tipos = [tipo for tipo in tipos if tipo]
        if tipos:
            parte["tipo"] = max(set(tipos), key=tipos.count)
    return partes


def nombre_documento_expediente(
    radicado,
    placa,
    fecha,
    ubicacion,
    extension,
    tipo_caso=None,
):
    """Genera un nombre estable para ubicar documentos aunque lleguen con otro nombre."""
    partes = [radicado, placa, fecha, ubicacion, tipo_caso]
    nombre = "_".join(
        token for token in (_token_nombre_documento(parte) for parte in partes)
        if token
    )
    return f"{nombre or 'EXPEDIENTE'}{extension.lower()}"


def _token_nombre_documento(valor):
    """Normaliza un valor para la convención de nombres del expediente."""
    texto = str(valor or "").strip()
    if not texto:
        return ""
    texto = re.sub(r"[^A-Za-z0-9ÁÉÍÓÚáéíóúÑñÜü]+", "-", texto)
    texto = re.sub(r"-+", "-", texto).strip("-")
    return texto


def nombre_carpeta_expediente(radicado, placa, fecha, ubicacion):
    """Genera la carpeta final: RADICADO_PADRE_PLACA_AAAA-MM-DD_UBICACION."""
    fecha_formateada = fecha_para_nombre_carpeta(fecha)
    caja, folder, carpeta = componentes_ubicacion(ubicacion)
    partes = [radicado, placa, fecha_formateada]
    for token in (caja, folder, carpeta):
        if token:
            partes.append(token)
    nombre = "_".join(
        token for token in (_token_nombre_documento(parte) for parte in partes)
        if token
    )
    return nombre or "RADICADO_PENDIENTE"


def fecha_para_nombre_carpeta(fecha):
    """Normaliza una fecha de expediente al formato ordenable AAAA-MM-DD."""
    try:
        return datetime.date.fromisoformat(str(fecha or "").strip()).isoformat()
    except (TypeError, ValueError):
        return "FECHA_PENDIENTE"


def nombre_carpeta_peticion(radicado, placa, fecha):
    """Genera la carpeta temporal con fecha visible en formato AAAA-MM-DD."""
    fecha_formateada = fecha_para_nombre_carpeta(fecha)
    partes = [
        radicado or "RADICADO_PENDIENTE",
        placa or "PLACA_PENDIENTE",
    ]
    return "_".join(
        [_token_nombre_documento(parte) for parte in partes] + [fecha_formateada]
    )


def nombre_pdf_expediente(
    radicado,
    placa,
    fecha,
    tipo_caso=None,
    caja="",
    folder="",
    carpeta="",
    extension=".pdf",
):
    """Genera el PDF completo con ubicación física en el nombre."""
    fecha_formateada = fecha_para_nombre_carpeta(fecha)
    partes = [
        _token_nombre_documento(radicado),
        _token_nombre_documento(placa),
        fecha_formateada,
    ]
    for valor, prefijo in (
        (caja, "CAJA"),
        (folder, "FOLDER"),
        (carpeta, "CARPETA"),
    ):
        parte = _normalizar_parte_ubicacion(valor, prefijo)
        if parte:
            partes.append(parte)
    nombre = "_".join(token for token in partes if token)
    return f"{nombre or 'EXPEDIENTE'}{extension.lower()}"


def clasificar_tipo_caso(texto="", nombre=""):
    """Identifica el desenlace válido del expediente según el flujo administrativo."""
    evidencia = normalizar_errores_ocr(f"{nombre} {texto}").lower()
    if re.search(r"desistim|desestimiento|desistimiento|desiste", evidencia):
        return "Desistimiento"
    if re.search(
        r"\bsin\s+recurso\b|no\s+interpuso\s+(?:un\s+)?recurso\b|"
        r"no\s+se\s+interpuso\s+(?:un\s+)?recurso\b|"
        r"no\s+present[oó]\s+(?:el\s+|un\s+)?recurso\b|"
        r"sin\s+interponer\s+(?:el\s+)?recurso|"
        r"\bno\s+se\s+present[oó]\s+recurso\b|"
        r"\bconstancia\s+de\s+ejecutoria\b",
        evidencia,
    ):
        return "Sin recurso"
    if re.search(
        r"\bcon\s+recurso\b|\brecurso\s+de\s+reposici[oó]n\b|"
        r"\bpresent[oó]\s+(?:un\s+)?recurso\b|\binterpuso\s+(?:un\s+)?recurso\b|"
        r"\bse\s+resuelve\s+el\s+recurso\b|\bresoluci[oó]n\s+del\s+recurso\b",
        evidencia,
    ):
        return "Con recurso"
    return None


def documentos_faltantes(registro):
    esperados = set(registro.get("documentos_esperados", []))
    anexados = {
        normalizar_tipo_documental(documento.get("tipo_documento"))
        for documento in registro.get("canvas_paginas", [])
        if documento.get("tipo_documento")
    }
    if registro.get("tipo_caso") == "Con recurso":
        anexados.add("Recurso")
    faltantes = []
    notificaciones = {
        "Notificación",
        "Notificación personal",
        "Notificación por aviso",
        "Notificación por publicación web",
    }
    for esperado in esperados:
        canonico = normalizar_tipo_documental(esperado)
        if canonico in anexados:
            continue
        if canonico == "Notificación" and anexados & notificaciones:
            continue
        if canonico == "Resolución" and "Requerimiento" in anexados:
            continue
        faltantes.append(esperado)
    return sorted(faltantes)


def documentos_requeridos_por_caso(tipo_caso, documentos_adicionales=None):
    requeridos = set(DOCUMENTOS_REQUERIDOS_POR_CASO.get(tipo_caso, set()))
    requeridos.update(documentos_adicionales or [])
    return sorted(requeridos)


def renderizar_checklist_documental(tipo_caso, documentos_presentes):
    """Muestra el checklist del proceso y sus documentos detectados."""
    grupos = CHECKLIST_GRUPOS_POR_CASO.get(tipo_caso, ())
    presentes = {
        normalizar_tipo_documental(documento)
        for documento in (documentos_presentes or [])
    }
    presentes.discard("")
    faltantes = [
        grupo for grupo in grupos
        if not any(
            (normalizar_tipo_documental(opcion) or opcion) in presentes
            for opcion in grupo
        )
    ]
    st.markdown("#### Checklist documental")
    st.caption(f"Proceso seleccionado: **{tipo_caso}**")
    columnas = st.columns(2)
    for indice, grupo in enumerate(grupos):
        encontrado = next(
            (
                opcion
                for opcion in grupo
                if (normalizar_tipo_documental(opcion) or opcion) in presentes
            ),
            "",
        )
        etiqueta = " o ".join(grupo)
        texto = f"{'✅' if encontrado else '⬜'} {etiqueta}"
        if grupo in faltantes:
            columnas[indice % 2].warning(texto)
        else:
            columnas[indice % 2].success(texto)
    if faltantes:
        st.warning(
            "Faltan documentos: "
            + ", ".join(" o ".join(grupo) for grupo in faltantes)
        )
    else:
        st.success("Checklist completo para este proceso.")


def mostrar_documento_en_aplicacion(contenido, nombre, solo_lectura=False):
    """Muestra un documento sin abrir Drive ni exponer controles de descarga al visualizador."""
    extension = os.path.splitext(nombre)[1].lower()
    if extension == ".pdf":
        if pdf_viewer is not None:
            pdf_viewer(
                contenido,
                height=700,
                key=f"pdf-preview-{huella_contenido(contenido)[:16]}",
            )
            return
        pdf_data = base64.b64encode(contenido).decode("ascii")
        controles = "" if solo_lectura else "toolbar=1&navpanes=1"
        bloqueo = " oncontextmenu=\"return false;\"" if solo_lectura else ""
        components.html(
            f"""
            <iframe
                src="data:application/pdf;base64,{pdf_data}{'#' + controles if controles else ''}"
                style="width:100%;height:700px;border:0"
                {bloqueo}
            ></iframe>
            """,
            height=700,
            scrolling=False,
        )
    elif extension in {".png", ".jpg", ".jpeg"}:
        st.image(contenido, caption=nombre, width="stretch")
    else:
        st.info("Este tipo de archivo no tiene vista previa integrada.")


def guardar_documento_local(contenido, nombre):
    """Conserva una copia local para visualizar el expediente sin conexión a Drive."""
    carpeta = resolver_dato("documentos")
    os.makedirs(carpeta, exist_ok=True)
    extension = os.path.splitext(nombre)[1].lower() or ".pdf"
    ruta = os.path.join(carpeta, f"{huella_contenido(contenido)}{extension}")
    if not os.path.exists(ruta):
        with open(ruta, "wb") as archivo:
            archivo.write(contenido)
    return ruta


def leer_documento_local(documento):
    ruta = documento.get("ruta_local", "")
    if ruta and os.path.exists(ruta):
        with open(ruta, "rb") as archivo:
            return archivo.read()
    return None

def obtener_rango_primera_hoja(service, columnas="A:Z"):
    nombre_hoja = obtener_hoja_registro(service, SPREADSHEET_ID)
    if not nombre_hoja:
        raise ValueError("No se pudo identificar la pestaña de Google Sheets.")
    titulo_seguro = nombre_hoja.replace("'", "''")
    return f"'{titulo_seguro}'!{columnas}"


def normalizar_campo_sheet(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    # Algunas copias históricas tienen letras acentuadas dañadas como �.
    texto = texto.replace("�", "O")
    texto = texto.replace("_", " ")
    texto = re.sub(r"[^A-Z0-9 ]", " ", texto.upper())
    return re.sub(r"\s+", " ", texto).strip()


def clave_campo_sheet(valor):
    return re.sub(r"\s+", "", normalizar_campo_sheet(valor))


COLUMNAS_SHEET_OFICIALES = [
    "FECHA SOLICITUD",
    "PLACA",
    "EMPRESA",
    "NIT",
    "DIRECCION EMPRESA",
    "PROPIETARIO",
    "CEDULA",
    "DIRECCION PROPIETARIO",
    "RAD PADRE",
    "FECHA RADICACION",
    "RESOLUCION DESVINCULACION",
    "FECHA DESVINCULACION",
    "OBSERVACION",
    "FUNCIONARIO QUE DESVINCULA",
    "NUEVA EMPRESA",
    "SOLICITANTE",
    "ESTADO",
    "CORREO ELECTRONICO",
    "RECURSO",
    "FECHA RECURSO",
    "OBSERVACIONES",
    "TIPO CASO",
    "TIPO NOTIFICACION",
    "FECHA NOTIFICACION",
    "FECHA EJECUTORIA",
    "FECHA REMISION REGISTRO",
    "QX VERIFICADO",
    "ID EXPEDIENTE",
    "UBICACION FISICA",
    "CAJA",
    "FOLDER",
    "CARPETA",
    "FOLIACION",
    "FECHA ULTIMA MODIFICACION",
    "SUBIDO POR",
    "CORREO SUBIDA",
    "CARGO SUBIDA",
    "ACCESO DIGITAL",
    "DRIVE FOLDER",
    "DOCUMENTOS DRIVE",
    "PDF UNIFICADO",
    "DOCUMENTOS FALTANTES",
    "CONTENIDO DOCUMENTAL",
]


ALIASES_COLUMNAS_SHEET = {
    "FECHA": "fecha_solicitud",
    "FECHASOLICITUD": "fecha_solicitud",
    "RADPADRE": "radicado_padre",
    "RADICADOPADRE": "radicado_padre",
    "DIRECCIONEMPRESA": "direccion_empresa",
    "DIRECCIONPROPIETARIO": "direccion_propietario",
    "RESOLUCIONDESVINCULACION": "resolucion",
    "RESOLUCION": "resolucion",
    "FECHADESVINCULACION": "fecha_resolucion",
    "FECHARECURSO": "fecha_recurso",
    "TIPOCASO": "tipo_caso",
    "TIPONOTIFICACION": "tipo_notificacion",
    "FECHANOTIFICACION": "fecha_notificacion",
    "FECHAEJECUTORIA": "fecha_ejecutoria",
    "FECHAREMISIONREGISTRO": "fecha_remision_registro",
    "QXVERIFICADO": "qx_verificado",
    "UBICACIONFISICA": "ubicacion",
    "FECHAULTIMAMODIFICACION": "ultima_modificacion",
    "ACCESODIGITAL": "drive_folder",
    "DRIVEFOLDER": "drive_folder",
    "DOCUMENTOSDRIVE": "documentos_drive",
    "PDFUNIFICADO": "pdf_unificado",
    "DOCUMENTOSFALTANTES": "documentos_faltantes_drive",
    "CONTENIDODOCUMENTAL": "contenido_documental",
}


def letra_columna(numero):
    resultado = ""
    while numero:
        numero, resto = divmod(numero - 1, 26)
        resultado = chr(65 + resto) + resultado
    return resultado


def buscar_registro_en_sheets(
    service,
    radicado="",
    placa="",
    fecha="",
    empresa="",
    nit="",
    cedula="",
):
    if not service or not any((radicado, placa, fecha, empresa, nit, cedula)):
        return None
    try:
        filas = leer_registros_sheets(service)
        if not filas:
            return None
        encabezados = [normalizar_campo_sheet(valor) for valor in filas[0]]
        indices = {
            "radicado": next(
                (
                    i
                    for i, valor in enumerate(encabezados)
                    if clave_campo_sheet(valor) in {"RADPADRE", "RADICADOPADRE"}
                ),
                None,
            ),
            "placa": next(
                (i for i, valor in enumerate(encabezados) if clave_campo_sheet(valor) == "PLACA"),
                None,
            ),
            "fecha": next(
                (
                    i
                    for i, valor in enumerate(encabezados)
                    if clave_campo_sheet(valor) in {"FECHA", "FECHASOLICITUD"}
                ),
                None,
            ),
            "empresa": next(
                (i for i, valor in enumerate(encabezados) if clave_campo_sheet(valor) == "EMPRESA"),
                None,
            ),
            "nit": next(
                (i for i, valor in enumerate(encabezados) if clave_campo_sheet(valor) == "NIT"),
                None,
            ),
            "cedula": next(
                (i for i, valor in enumerate(encabezados) if clave_campo_sheet(valor) == "CEDULA"),
                None,
            ),
        }
        buscados = {
            "radicado": normalizar_identificador(radicado),
            "placa": normalizar_identificador(placa),
            "fecha": normalizar_identificador(fecha),
            "empresa": normalizar_identificador(empresa),
            "nit": normalizar_identificador(nit),
            "cedula": normalizar_identificador(cedula),
        }
        mejor_coincidencia = None
        mejor_puntaje = 0
        for numero, fila in enumerate(filas[1:], start=2):
            puntaje = 0
            for campo, indice in indices.items():
                buscado = buscados[campo]
                if not buscado or indice is None or len(fila) <= indice:
                    continue
                valor = normalizar_identificador(fila[indice])
                if valor and valor == buscado:
                    puntaje += 4 if campo == "radicado" else 2
            if puntaje > mejor_puntaje:
                mejor_puntaje = puntaje
                mejor_coincidencia = {
                    "fila": fila,
                    "numero": numero,
                    "encabezados": encabezados,
                    "puntaje": puntaje,
                }
        if mejor_coincidencia and mejor_puntaje >= 2:
            return mejor_coincidencia
    except Exception as error:
        st.warning(f"No fue posible consultar el registro actual de Google Sheets: {error}")
    return None


def datos_registro_sheet(registro_sheet):
    if not registro_sheet:
        return {}
    fila = registro_sheet["fila"]
    datos = {}
    indice_direccion = 0
    for indice, encabezado in enumerate(registro_sheet["encabezados"]):
        clave = clave_campo_sheet(encabezado)
        campo = ALIASES_COLUMNAS_SHEET.get(clave)
        if clave in {"DIRECCIONEMPRESA", "DIRECCIONPROPIETARIO"}:
            campo = (
                "direccion_empresa"
                if clave == "DIRECCIONEMPRESA"
                else "direccion_propietario"
            )
        if not campo and clave == "DIRECCION":
            campo = "direccion_empresa" if indice_direccion == 0 else "direccion_propietario"
            indice_direccion += 1
        if campo and indice < len(fila) and str(fila[indice]).strip():
            valor = str(fila[indice]).strip()
            if campo == "qx_verificado":
                datos[campo] = valor.upper() in {"SI", "SÍ", "TRUE", "1"}
            else:
                datos[campo] = valor
    return datos


def resumen_documentos_drive(registro_datos):
    documentos = registro_datos.get("canvas_paginas", [])
    documentos_con_enlace = []
    for documento in documentos:
        nombre = documento.get("nombre", "").strip()
        if not nombre:
            continue
        enlace = documento.get("drive_url", "").strip()
        if not enlace and documento.get("drive_id"):
            enlace = f"https://drive.google.com/file/d/{documento['drive_id']}/view"
        documentos_con_enlace.append(
            f"{nombre} -> {enlace}" if enlace else nombre
        )
    faltantes = documentos_faltantes(registro_datos)
    return {
        "ACCESO DIGITAL": registro_datos.get("drive_folder", ""),
        "DRIVE FOLDER": registro_datos.get("drive_folder", ""),
        "DOCUMENTOS DRIVE": " | ".join(documentos_con_enlace),
        "PDF UNIFICADO": next(
            (
                documento.get("drive_url", "")
                for documento in documentos
                if documento.get("tipo_documento") == "Expediente completo"
            ),
            "",
        ),
        "DOCUMENTOS FALTANTES": ", ".join(faltantes),
        "CONTENIDO DOCUMENTAL": " | ".join(
            f"{documento.get('tipo_documento', 'Documento')}: "
            f"{documento.get('nombre', '')}"
            for documento in documentos
        ),
    }


def valores_registro_para_sheet(registro_datos, columnas_drive):
    valores = {
        "FECHA SOLICITUD": registro_datos.get("fecha_solicitud", ""),
        "FECHA": registro_datos.get("fecha_solicitud", ""),
        "PLACA": registro_datos.get("placa", ""),
        "EMPRESA": registro_datos.get("empresa", ""),
        "NIT": registro_datos.get("nit", ""),
        "DIRECCION EMPRESA": registro_datos.get("direccion_empresa", ""),
        "DIRECCION": registro_datos.get("direccion_empresa", ""),
        "PROPIETARIO": registro_datos.get("propietario", ""),
        "CEDULA": registro_datos.get("cedula", ""),
        "DIRECCION PROPIETARIO": registro_datos.get("direccion_propietario", ""),
        "RAD PADRE": registro_datos.get("radicado_padre", ""),
        "RADICADO PADRE": registro_datos.get("radicado_padre", ""),
        "FECHA RADICACION": registro_datos.get("fecha_radicacion", ""),
        "FECHA RAD-": registro_datos.get("fecha_radicacion", ""),
        "RESOLUCION DESVINCULACION": registro_datos.get("resolucion", ""),
        "RESOLUCION": registro_datos.get("resolucion", ""),
        "FECHA DESVINCULACION": registro_datos.get("fecha_resolucion", ""),
        "FECHA DESVINCULACN": registro_datos.get("fecha_resolucion", ""),
        "OBSERVACION": registro_datos.get("observacion", ""),
        "FUNCIONARIO QUE DESVINCULA": registro_datos.get("funcionario", ""),
        "NUEVA EMPRESA": registro_datos.get("nueva_empresa", ""),
        "SOLICITANTE": registro_datos.get("solicitante", ""),
        "ESTADO": registro_datos.get("estado", ""),
        "CORREO ELECTRONICO": registro_datos.get("correo", ""),
        "RECURSO": registro_datos.get("recurso", ""),
        "FECHA RECURSO": registro_datos.get("fecha_recurso", ""),
        "OBSERVACIONES": registro_datos.get("notas", ""),
        "TIPO CASO": registro_datos.get("tipo_caso", ""),
        "TIPO NOTIFICACION": registro_datos.get("tipo_notificacion", ""),
        "FECHA NOTIFICACION": registro_datos.get("fecha_notificacion", ""),
        "FECHA EJECUTORIA": registro_datos.get("fecha_ejecutoria", ""),
        "FECHA REMISION REGISTRO": registro_datos.get("fecha_remision_registro", ""),
        "QX VERIFICADO": "SI" if registro_datos.get("qx_verificado") else "NO",
        "ID EXPEDIENTE": registro_datos.get("id", ""),
        "UBICACION FISICA": registro_datos.get("ubicacion", ""),
        "CAJA": registro_datos.get("caja", ""),
        "FOLDER": registro_datos.get("folder", ""),
        "CARPETA": registro_datos.get("carpeta", ""),
        "FOLIACION": registro_datos.get("foliacion", ""),
        "FECHA ULTIMA MODIFICACION": registro_datos.get("ultima_modificacion", ""),
        "SUBIDO POR": registro_datos.get("subido_por", ""),
        "CORREO SUBIDA": registro_datos.get("correo_subida", ""),
        "CARGO SUBIDA": registro_datos.get("cargo_subida", ""),
        "ACCESO DIGITAL": registro_datos.get("drive_folder", ""),
        "DRIVE FOLDER": registro_datos.get("drive_folder", ""),
    }
    valores.update(columnas_drive)
    return valores


def fila_registro_para_sheet(encabezados, registro_datos, fila_anterior=None):
    columnas_drive = resumen_documentos_drive(registro_datos)
    valores = valores_registro_para_sheet(registro_datos, columnas_drive)
    fila = list(fila_anterior or [])
    indice_direccion = 0
    for indice, encabezado in enumerate(encabezados):
        while len(fila) <= indice:
            fila.append("")
        clave = clave_campo_sheet(encabezado)
        if clave in {"DIRECCION", "DIRECCIONEMPRESA", "DIRECCIONPROPIETARIO"}:
            if clave == "DIRECCIONPROPIETARIO":
                valor = registro_datos.get("direccion_propietario", "")
            elif clave == "DIRECCIONEMPRESA":
                valor = registro_datos.get("direccion_empresa", "")
            else:
                valor = (
                    registro_datos.get("direccion_empresa", "")
                    if indice_direccion == 0
                    else registro_datos.get("direccion_propietario", "")
                )
                indice_direccion += 1
        else:
            valor = valores.get(normalizar_campo_sheet(encabezado), "")
            if not valor:
                valor = valores.get(encabezado, "")
                if not valor:
                    valor = valores.get(ALIASES_COLUMNAS_SHEET.get(clave, ""), "")
        if valor:
            fila[indice] = valor
    return fila


def ordenar_sheet_por_fecha(service, encabezados):
    encabezados_normalizados = [
        normalizar_campo_sheet(encabezado) for encabezado in encabezados
    ]
    indice_fecha = next(
        (
            encabezados_normalizados.index(nombre)
            for nombre in ("FECHA", "FECHA SOLICITUD", "FECHA_SOLICITUD")
            if nombre in encabezados_normalizados
        ),
        None,
    )
    if indice_fecha is None:
        return
    metadata = service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID,
        fields="sheets.properties(sheetId,title)",
    ).execute()
    hojas = metadata.get("sheets", [])
    if not hojas:
        return
    nombre_hoja = obtener_hoja_registro(service, SPREADSHEET_ID)
    propiedades = next(
        (
            hoja.get("properties", {})
            for hoja in hojas
            if hoja.get("properties", {}).get("title", "").strip() == nombre_hoja
        ),
        hojas[0].get("properties", {}),
    )
    service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={
            "requests": [{
                "sortRange": {
                    "range": {
                        "sheetId": propiedades.get("sheetId"),
                        "startRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": len(encabezados),
                    },
                    "sortSpecs": [{
                        "dimensionIndex": indice_fecha,
                        "sortOrder": "ASCENDING",
                    }],
                }
            }]
        },
    ).execute()


def configurar_tabla_registro_sheet(service, cantidad_columnas):
    """Convierte la pestaña operativa en una tabla filtrable y legible."""
    metadata = service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID,
        fields="sheets.properties(sheetId,title,gridProperties)",
    ).execute()
    hojas = metadata.get("sheets", [])
    if not hojas or not cantidad_columnas:
        return
    nombre_hoja = obtener_hoja_registro(service, SPREADSHEET_ID)
    propiedades = next(
        (
            hoja.get("properties", {})
            for hoja in hojas
            if hoja.get("properties", {}).get("title", "").strip() == nombre_hoja
        ),
        hojas[0].get("properties", {}),
    )
    sheet_id = propiedades.get("sheetId")
    requests = [
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },
        {
            "setBasicFilter": {
                "filter": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "startColumnIndex": 0,
                        "endColumnIndex": cantidad_columnas,
                    },
                }
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": cantidad_columnas,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.08, "green": 0.25, "blue": 0.45},
                        "textFormat": {
                            "bold": True,
                            "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                        },
                        "horizontalAlignment": "CENTER",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
            }
        },
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": cantidad_columnas,
                }
            }
        },
    ]
    service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": requests},
    ).execute()


def guardar_registro_en_sheets(service, registro_datos):
    try:
        nombre_hoja = obtener_hoja_registro(service, SPREADSHEET_ID)
        asegurar_dimension_grid(
            service,
            SPREADSHEET_ID,
            nombre_hoja,
            filas=1000,
            columnas=max(len(COLUMNAS_SHEET_OFICIALES), 43),
        )
        existente = buscar_registro_en_sheets(
            service,
            registro_datos.get("radicado_padre"),
            registro_datos.get("placa"),
            registro_datos.get("fecha_solicitud"),
        )
        if existente:
            fila = list(existente["fila"])
            encabezados = list(existente["encabezados"])
            columnas_drive = resumen_documentos_drive(registro_datos)
            encabezados_normalizados = [normalizar_campo_sheet(nombre) for nombre in encabezados]
            faltantes_oficiales = [
                nombre for nombre in COLUMNAS_SHEET_OFICIALES
                if normalizar_campo_sheet(nombre) not in encabezados_normalizados
            ]
            if faltantes_oficiales:
                encabezados.extend(faltantes_oficiales)
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=rango_hoja_registro(
                        service,
                        f"A1:{letra_columna(len(encabezados))}1",
                        SPREADSHEET_ID,
                    ),
                    valueInputOption="USER_ENTERED",
                    body={"values": [encabezados]},
                ).execute()
                asegurar_dimension_grid(
                    service,
                    SPREADSHEET_ID,
                    nombre_hoja,
                    filas=1000,
                    columnas=len(encabezados),
                )
            fila = fila_registro_para_sheet(encabezados, registro_datos, fila)
            rango = rango_hoja_registro(
                service,
                f"A{existente['numero']}:{letra_columna(max(len(fila), len(encabezados)))}{existente['numero']}",
                SPREADSHEET_ID,
            )
            body = {"values": [fila]}
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=rango,
                valueInputOption="USER_ENTERED",
                body=body,
            ).execute()
            ordenar_sheet_por_fecha(service, encabezados)
            configurar_tabla_registro_sheet(service, len(encabezados))
        else:
            filas_actuales = leer_registros_sheets(service)
            if not filas_actuales:
                raise ValueError("La pestaña de Google Sheets no tiene encabezados.")
            encabezados = list(filas_actuales[0])
            columnas_drive = resumen_documentos_drive(registro_datos)
            encabezados_normalizados = [normalizar_campo_sheet(nombre) for nombre in encabezados]
            faltantes_oficiales = [
                nombre for nombre in COLUMNAS_SHEET_OFICIALES
                if normalizar_campo_sheet(nombre) not in encabezados_normalizados
            ]
            if faltantes_oficiales:
                encabezados.extend(faltantes_oficiales)
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=rango_hoja_registro(
                        service,
                        f"A1:{letra_columna(len(encabezados))}1",
                        SPREADSHEET_ID,
                    ),
                    valueInputOption="USER_ENTERED",
                    body={"values": [encabezados]},
                ).execute()
                asegurar_dimension_grid(
                    service,
                    SPREADSHEET_ID,
                    nombre_hoja,
                    filas=1000,
                    columnas=len(encabezados),
                )
            valores = [fila_registro_para_sheet(encabezados, registro_datos)]
            siguiente_fila = len(filas_actuales) + 1
            rango = rango_hoja_registro(
                service,
                f"A{siguiente_fila}:{letra_columna(len(encabezados))}{siguiente_fila}",
                SPREADSHEET_ID,
            )
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=rango,
                valueInputOption="USER_ENTERED",
                body={"values": valores},
            ).execute()
            ordenar_sheet_por_fecha(service, encabezados)
            configurar_tabla_registro_sheet(service, len(encabezados))
        return True
    except Exception as e:
        st.error(f"Error guardando en Google Sheets: {e}")
        return False

def leer_registros_sheets(service):
    try:
        if service and SPREADSHEET_ID:
            asegurador_registro_hoja(service, SPREADSHEET_ID)
        sheet = service.spreadsheets()
        rango = rango_hoja_registro(service, "A1:AZ2000", SPREADSHEET_ID)
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=rango
        ).execute()
        return result.get('values', [])
    except Exception as e:
        st.error(f"Error al leer Google Sheets: {e}")
        return []

def guardar_local_json(data):
    try:
        contenido = {
            "expedientes": data,
            "usuarios": st.session_state.get("usuarios", {}),
            "mensajes_soporte": st.session_state.get("mensajes_soporte", []),
            "pendientes": st.session_state.get("pendientes", {}),
        }
        with open(LOCAL_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(contenido, f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"Error al guardar en database_local.json: {e}")

def cargar_base_datos_inicial(service):
    db_cargada = {}
    usuarios_cargados = {}

    if os.path.exists(LOCAL_DB_FILE):
        try:
            with open(LOCAL_DB_FILE, 'r', encoding='utf-8-sig') as f:
                raw_data = json.load(f)
                if "expedientes" in raw_data:
                    db_cargada = raw_data.get("expedientes", {})
                    usuarios_cargados.update(raw_data.get("usuarios", {}))
                    st.session_state.mensajes_soporte = raw_data.get(
                        "mensajes_soporte",
                        [],
                    )
                    st.session_state.pendientes = raw_data.get("pendientes", {})
                else:
                    db_cargada = raw_data
                    st.session_state.mensajes_soporte = []
        except Exception:
            pass

    if service:
        filas = leer_registros_sheets(service)
        if filas and len(filas) > 1:
            encabezados_sheet = [
                normalizar_campo_sheet(valor) for valor in filas[0]
            ]
            for fila in filas[1:]:
                rad = _valor_fila_normalizada(
                    fila,
                    encabezados_sheet,
                    "RAD PADRE",
                    "RADICADO PADRE",
                )
                if rad:
                    if rad not in db_cargada:
                        valores_sheet = {
                            encabezado: fila[indice]
                            for indice, encabezado in enumerate(encabezados_sheet)
                            if indice < len(fila)
                        }
                        db_cargada[rad] = {
                            "id": _valor_fila_normalizada(fila, encabezados_sheet, "ID") or 1,
                            "radicado_padre": rad,
                            "placa": _valor_fila_normalizada(fila, encabezados_sheet, "PLACA"),
                            "solicitante": _valor_fila_normalizada(fila, encabezados_sheet, "SOLICITANTE"),
                            "fecha_solicitud": _fecha_historica(
                                _valor_fila_normalizada(fila, encabezados_sheet, "FECHA")
                            ),
                            "fecha_minima": _fecha_historica(
                                _valor_fila_normalizada(fila, encabezados_sheet, "FECHA")
                            ),
                            "fecha_radicacion": _fecha_historica(
                                _valor_fila_normalizada(fila, encabezados_sheet, "FECHA RAD-")
                            ),
                            "resolucion": _valor_fila_normalizada(
                                fila, encabezados_sheet,
                                "RESOLUCION DESVINCULACION",
                                "RESOLUCN DESVINCULACN",
                            ),
                            "fecha_resolucion": _fecha_historica(
                                _valor_fila_normalizada(
                                    fila, encabezados_sheet,
                                    "FECHA DESVINCULACION",
                                    "FECHA DESVINCULACN",
                                )
                            ),
                            "remitido": _valor_fila_normalizada(fila, encabezados_sheet, "REMITIDO").upper() == "SI",
                            "ubicacion": _valor_fila_normalizada(fila, encabezados_sheet, "UBICACION"),
                            "estado": _valor_fila_normalizada(fila, encabezados_sheet, "ESTADO"),
                            "canvas_paginas": [],
                            "drive_folder": valores_sheet.get(
                                "DRIVE FOLDER",
                                f"https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}",
                            ),
                            "documentos_drive": valores_sheet.get("DOCUMENTOS DRIVE", ""),
                            "pdf_unificado": valores_sheet.get("PDF UNIFICADO", ""),
                            "documentos_faltantes_drive": valores_sheet.get(
                                "DOCUMENTOS FALTANTES", ""
                            ),
                            "contenido_documental": valores_sheet.get(
                                "CONTENIDO DOCUMENTAL", ""
                            ),
                            "modificado_por": _valor_fila_normalizada(fila, encabezados_sheet, "FUNCIONARIO") or "Sistema",
                            "ultima_modificacion": "",
                            "notas": _valor_fila_normalizada(fila, encabezados_sheet, "OBSERVACIONES", "OBSERVACION"),
                            "nombre_ubicacion": _valor_fila_normalizada(fila, encabezados_sheet, "UBICACION"),
                        }
        db_cargada = dict(sorted(
            db_cargada.items(),
            key=lambda item: item[1].get("fecha_solicitud") or "9999-12-31",
        ))

    return db_cargada, usuarios_cargados


def _texto_historico(valor):
    """Normaliza valores del Excel sin alterar el archivo histórico original."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    texto = str(valor).strip()
    reemplazos = {
        "DIRECCI�N": "DIRECCIÓN",
        "CORREO ELECTR�NICO": "CORREO ELECTRÓNICO",
        "RESOLUCI�N": "RESOLUCIÓN",
        "OBSERVACI�N": "OBSERVACIÓN",
        "FUNCIONARIO QUE DESVINCULA": "FUNCIONARIO QUE DESVINCULA",
        "ROCI�": "ROCÍ",
        "CA�AVERAL": "CAÑAVERAL",
        "MU�OZ": "MUÑOZ",
        "ORTEG�N": "ORTEGÓN",
    }
    for origen, destino in reemplazos.items():
        texto = texto.replace(origen, destino)
    return texto


def _fecha_historica(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    if isinstance(valor, pd.Timestamp):
        return valor.strftime("%Y-%m-%d")
    texto = str(valor).strip()
    if not texto:
        return ""
    try:
        if texto.isdigit() or re.fullmatch(r"\d+(?:\.\d+)?", texto):
            numero = float(texto)
            if math.isfinite(numero):
                fecha = pd.to_datetime(numero, unit="D", origin="1899-12-30", errors="coerce")
                if not pd.isna(fecha):
                    return fecha.strftime("%Y-%m-%d")
        fecha = pd.to_datetime(texto, dayfirst=True, errors="coerce")
        return "" if pd.isna(fecha) else fecha.strftime("%Y-%m-%d")
    except Exception:
        return ""


def _valor_fila_normalizada(fila, encabezados, *nombres):
    for nombre in nombres:
        indice = encabezados.index(normalizar_campo_sheet(nombre)) if normalizar_campo_sheet(nombre) in encabezados else None
        if indice is not None and indice < len(fila):
            valor = _texto_historico(fila[indice])
            if valor:
                return valor
    return ""


def _cargar_datos_complementarios():
    datos = {}
    if not os.path.exists(HISTORICO_FILE):
        return datos
    hoja = pd.read_excel(HISTORICO_FILE, sheet_name="DATOS", dtype=object)
    hoja.columns = [normalizar_campo_sheet(col) for col in hoja.columns]
    for _, fila in hoja.iterrows():
        empresa = _texto_historico(fila.get("EMPRESA")).upper()
        nit = _texto_historico(fila.get("NIT"))
        if empresa or nit:
            datos[(empresa, nit)] = {
                "empresa": _texto_historico(fila.get("EMPRESA")),
                "nit": nit,
                "direccion_empresa": _texto_historico(
                    fila.get("DIRECCION") or fila.get("DIRECCN")
                ),
                "funcionario": _texto_historico(
                    fila.get("FUNCIONARIOS") or fila.get("FUNCIONARIO")
                ),
                "solicitante": _texto_historico(fila.get("SOLICITANTE")),
                "estado": _texto_historico(fila.get("ESTADO")),
                "observacion": _texto_historico(
                    fila.get("OBSERVACION") or fila.get("OBSERVACN")
                ),
            }
    return datos


def leer_base_historica():
    """Lee la hoja histórica y la convierte al modelo local actual."""
    if not os.path.exists(HISTORICO_FILE):
        raise FileNotFoundError(f"No se encontró el respaldo: {HISTORICO_FILE}")

    historico = pd.read_excel(HISTORICO_FILE, sheet_name="BD_DESV", dtype=object)
    historico.columns = [_texto_historico(col).upper() for col in historico.columns]
    datos_complementarios = _cargar_datos_complementarios()
    registros = []
    for _, fila in historico.iterrows():
        radicado = _texto_historico(fila.get("RAD PADRE"))
        if not radicado:
            continue
        empresa = _texto_historico(fila.get("EMPRESA"))
        nit = _texto_historico(fila.get("NIT"))
        complemento = datos_complementarios.get(
            (empresa.upper(), nit),
            {},
        )
        registro = {
            "radicado_padre": radicado,
            "placa": _texto_historico(fila.get("PLACA")).upper(),
            "empresa": empresa or complemento.get("empresa", ""),
            "nit": nit or complemento.get("nit", ""),
            "direccion_empresa": _texto_historico(fila.get("DIRECCIÓN")),
            "propietario": _texto_historico(fila.get("PROPIETARIO")),
            "cedula": _texto_historico(fila.get("CEDULA")),
            "direccion_propietario": _texto_historico(fila.get("DIRECCIÓN.1")),
            "fecha_solicitud": _fecha_historica(fila.get("FECHA")),
            "fecha_radicacion": _fecha_historica(fila.get("FECHA RAD-")),
            "resolucion": _texto_historico(fila.get("RESOLUCIÓN\nDESVINCULACIÓN")),
            "fecha_resolucion": _fecha_historica(fila.get("FECHA\n DESVINCULACIÓN")),
            "observacion": _texto_historico(fila.get("OBSERVACIÓN")) or complemento.get("observacion", ""),
            "funcionario": _texto_historico(fila.get("FUNCIONARIO QUE DESVINCULA")) or complemento.get("funcionario", ""),
            "nueva_empresa": _texto_historico(fila.get("NUEVA EMPRESA")),
            "solicitante": _texto_historico(fila.get("SOLICITANTE")) or complemento.get("solicitante", ""),
            "estado": _texto_historico(fila.get("ESTADO")) or complemento.get("estado", ""),
            "correo": _texto_historico(fila.get("CORREO ELECTRÓNICO")),
            "recurso": _texto_historico(fila.get("RECURSO")),
            "fecha_recurso": _fecha_historica(fila.get("FECHA RECURSO")),
            "notas": _texto_historico(fila.get("OBSERVACIONES")),
        }
        if not registro["notas"]:
            registro["notas"] = registro["observacion"]
        registros.append(registro)
    return sorted(
        registros,
        key=lambda registro: registro.get("fecha_solicitud") or "9999-12-31",
    )


def convertir_historico_a_expediente(registro, expediente_id):
    return {
        "id": expediente_id,
        **registro,
        "fecha_minima": registro.get("fecha_solicitud", ""),
        "qx_verificado": False,
        "tipo_notificacion": "",
        "fecha_notificacion": "",
        "fecha_ejecutoria": "",
        "remitido": False,
        "fecha_remision_registro": "",
        "ubicacion": "",
        "caja": "",
        "folder": "",
        "carpeta": "",
        "canvas_paginas": [],
        "drive_folder": f"https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}",
        "modificado_por": "Importación histórica",
        "ultima_modificacion": str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "origen": HISTORICO_FILENAME,
    }


def importar_base_historica():
    registros = leer_base_historica()
    importados = 0
    duplicados = 0
    for registro in registros:
        radicado = registro["radicado_padre"]
        if radicado in st.session_state.db_expedientes:
            duplicados += 1
            continue
        expediente_id = siguiente_numero_expediente() + importados
        st.session_state.db_expedientes[radicado] = convertir_historico_a_expediente(
            registro, expediente_id
        )
        importados += 1
    if importados:
        guardar_local_json(st.session_state.db_expedientes)
    return importados, duplicados, len(registros)

# --- INICIALIZACIÓN ---
drive_service = get_drive_service()
sheets_service = get_sheets_service()

if 'db_expedientes' not in st.session_state or 'usuarios' not in st.session_state:
    exp_data, usr_data = cargar_base_datos_inicial(sheets_service)
    st.session_state.db_expedientes = exp_data
    st.session_state.usuarios = usr_data
if "mensajes_soporte" not in st.session_state:
    st.session_state.mensajes_soporte = []
if "pendientes" not in st.session_state:
    st.session_state.pendientes = {}

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.logged_user = None

if 'navegacion' not in st.session_state:
    st.session_state.navegacion = "Inicio"

if 'form_registro_version' not in st.session_state:
    st.session_state.form_registro_version = 0

# Restaurar automáticamente solo una cuenta de Google ya aprobada.
if (
    not st.session_state.get("logged_in", False)
    and not st.session_state.get("google_auto_login_disabled", False)
    and os.path.exists(TOKEN_FILE)
):
    creds_auto = get_google_credentials()
    if creds_auto:
        email_auto = obtener_email_google(creds_auto)
        usuario_auto = st.session_state.usuarios.get(email_auto) if email_auto else None
        if usuario_auto and (
            usuario_auto.get("estado") == "Activo"
            and usuario_auto.get("rol") != "Sin Rol Asignado"
        ):
            st.session_state.logged_user = email_auto
            st.session_state.logged_in = True

nav_param = st.query_params.get("nav")
if nav_param in {
    "Inicio",
    "Entrada de Expedientes",
    "Consulta & Archivo",
    "Gestión de Permisos",
    "Buzón de Mensajes",
    "Mi Perfil",
}:
    st.session_state.navegacion = nav_param
    del st.query_params["nav"]

external_param = st.query_params.get("external")
if external_param in {"drive", "sheets"}:
    external_url, external_title = (
        (
            f"https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}",
            "Google Drive",
        )
        if external_param == "drive"
        else (SHEET_URL, "Google Sheets")
    )
    abrir_en_navegador(external_url, external_title)
    del st.query_params["external"]

def cerrar_sesion():
    st.session_state.logged_in = False
    st.session_state.logged_user = None
    st.session_state.navegacion = "Inicio"
    st.session_state.supabase_access_token = None
    st.session_state.google_auto_login_disabled = True
    st.rerun()

def calcular_ubicacion(n):
    """30 procesos por folder, 3 folders por caja (90 procesos). La carpeta es el consecutivo del proceso."""
    n = max(1, int(n))
    caja = math.floor((n - 1) / 90) + 1
    folder = ((n - 1) % 90) // 30 + 1
    codigo = f"Carpeta {n} - Folder {folder} - Caja {caja}"
    return caja, folder, codigo

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"

def verificar_password(password, stored_password):
    if not stored_password:
        return False, False

    if stored_password.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt_hex, digest_hex = stored_password.split("$", 3)
            calculated = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations),
            ).hex()
            return hmac.compare_digest(calculated, digest_hex), False
        except (ValueError, TypeError):
            return False, False

    # Migrate legacy plaintext passwords after a successful login.
    return hmac.compare_digest(str(stored_password), password), True

def siguiente_numero_expediente():
    if not st.session_state.db_expedientes:
        return 1
    ids = []
    for exp in st.session_state.db_expedientes.values():
        try:
            ids.append(int(exp.get("id") or 0))
        except (TypeError, ValueError):
            pass
    return max(ids) + 1 if ids else 1

def calcular_estado_tramite(registro):
    completo = bool(
        registro.get("radicado_padre")
        and registro.get("fecha_solicitud")
        and registro.get("qx_verificado")
        and registro.get("resolucion")
        and registro.get("fecha_resolucion")
        and registro.get("tipo_notificacion")
        and registro.get("fecha_notificacion")
        and registro.get("fecha_ejecutoria")
        and registro.get("remitido")
        and registro.get("fecha_remision_registro")
    )
    return "COMPLETO" if completo else "EN TRÁMITE"

def cuenta_activa(usuario):
    if not usuario:
        return False
    if usuario.get("rol") == "Super Administrador":
        return usuario.get("estado", "Activo") == "Activo"
    return usuario.get("estado") == "Activo" and usuario.get("rol") != "Sin Rol Asignado"


def cuenta_bloqueada(usuario):
    return bool(usuario) and usuario.get("estado") == "Inactivo"


def puede_descargar_documentos(usuario):
    if not usuario:
        return False
    return usuario.get("rol") in {
        "Modificador",
        "Administrador",
        "Super Administrador",
    } or bool(usuario.get("permiso_descarga"))


def puede_eliminar_documentos(usuario):
    return bool(usuario) and usuario.get("rol") in {
        "Modificador",
        "Super Administrador",
    }


def solicitud_descarga_pendiente(usuario):
    return bool(usuario) and bool(usuario.get("solicitud_descarga"))


def opciones_autorizadas(rol):
    permisos = {
        "Visualizador": {"Inicio", "Consulta & Archivo", "Buzón de Mensajes", "Mi Perfil"},
        "Modificador": {"Inicio", "Entrada de Expedientes", "Consulta & Archivo", "Buzón de Mensajes", "Mi Perfil"},
        "Administrador": {
            "Inicio", "Entrada de Expedientes", "Consulta & Archivo",
            "Base Histórica", "Buzón de Mensajes", "Mi Perfil",
        },
        "Super Administrador": {
            "Inicio", "Entrada de Expedientes", "Consulta & Archivo",
            "Base Histórica", "Gestión de Permisos", "Buzón de Mensajes", "Mi Perfil",
        },
    }
    return permisos.get(rol, {"Inicio", "Mi Perfil"})

# --- FUNCIÓN DE RENDERIZADO ESTILO MENÚ DE WINDOWS ---
def render_win_app(col, img_path, titulo, destino_nav, key_prefix):
    with col:
        render_image_action(img_path, titulo, f"?nav={quote(destino_nav)}")


def enlace_aplicacion_externa(url, titulo):
    """Usa pestaña integrada en el ejecutable y HTTPS en el navegador de desarrollo."""
    if getattr(sys, "frozen", False):
        return (
            f"sistema://open?url={quote(url, safe='')}"
            f"&title={quote(titulo, safe='')}"
        )
    return url


def render_launcher_grid(items):
    tiles = []
    for img_path, label, href in items:
        if not os.path.exists(img_path):
            continue
        encoded = get_image_base64(img_path)
        tiles.append(
            f'<a class="action-tile" href="{href}" target="_self">'
            f'<img src="{encoded}" alt="{label}"><span>{label}</span></a>'
        )
    if tiles:
        st.markdown(
            f'<div class="launcher-grid">{"".join(tiles)}</div>',
            unsafe_allow_html=True,
        )

# Keep document classification and naming authoritative in the shared module.
normalizar_errores_ocr = _document_rules.normalizar_errores_ocr
componentes_ubicacion = _document_rules.componentes_ubicacion
nombre_carpeta_expediente = _document_rules.nombre_carpeta_expediente
fecha_para_nombre_carpeta = _document_rules.fecha_para_nombre_carpeta
nombre_pdf_expediente = _document_rules.nombre_pdf_expediente
clasificar_tipo_caso = _document_rules.clasificar_tipo_caso
clasificar_tipo_documento = _document_rules.clasificar_tipo_documento
tipos_documentales_detectados = _document_rules.tipos_documentales_detectados
normalizar_tipo_documental = _document_rules.normalizar_tipo_documental

# --- PANTALLA DE INGRESO / LOGIN ---
if not st.session_state.get("logged_in", False):
    col_a, col_b, col_c = st.columns([1, 2, 1])
    with col_b:
        if os.path.exists(IMG_LOGO):
            col_img1, col_img2, col_img3 = st.columns([1, 1, 1])
            with col_img2:
                st.image(IMG_LOGO, width=110)
        st.markdown("""
            <div class="header-box">
                <div class="header-title">SECRETARÍA DE TRÁNSITO Y TRANSPORTE - DESVINCULACIONES</div>
            </div>
        """, unsafe_allow_html=True)

        tab_local, tab_google, tab_register = st.tabs(["Clave Local", "Iniciar con Google", "Registro"])

        with tab_local:
            with st.form("form_login_local"):
                usr_input = st.text_input("Correo Institucional *").strip().lower()
                pwd_input = st.text_input("Contraseña *", type="password")
                btn_login = st.form_submit_button("Iniciar Sesión Local", width="stretch")

            if btn_login:
                usuarios = st.session_state.get("usuarios", {})
                usuario = usuarios.get(usr_input)
                password_ok, legacy_password = (
                    verificar_password(pwd_input, usuario.get("password", ""))
                    if usuario
                    else (False, False)
                )
                remote_session = supabase_auth_password(usr_input, pwd_input)
                if remote_session:
                    perfil_remoto = supabase_obtener_perfil(
                        remote_session.get("access_token")
                    )
                    if perfil_remoto:
                        usuario = usuarios.setdefault(
                            usr_input,
                            {
                                "alias": perfil_remoto.get("full_name") or usr_input,
                                "password": "",
                                "metodo": "Supabase Auth",
                                "fecha_registro": str(datetime.date.today()),
                            },
                        )
                        usuario["rol"] = perfil_remoto.get("role", "Sin Rol Asignado")
                        usuario["estado"] = perfil_remoto.get("status", "Pendiente")
                        usuario["alias"] = perfil_remoto.get("full_name") or usuario.get("alias", usr_input)
                        st.session_state.usuarios = usuarios
                        st.session_state.supabase_access_token = remote_session.get("access_token")
                        sincronizar_perfiles_remotos()
                        password_ok = True
                if usuario and password_ok:
                    if not cuenta_activa(usuario):
                        st.warning("Su cuenta está pendiente de activación. Un administrador debe asignarle rol y estado Activo.")
                    else:
                        if legacy_password:
                            usuario["password"] = hash_password(pwd_input)
                            guardar_local_json(st.session_state.db_expedientes)
                        st.session_state.logged_user = usr_input
                        st.session_state.logged_in = True
                        st.rerun()
                else:
                    st.error("Credenciales incorrectas.")

        with tab_google:
            st.write("Iniciar sesión o ingresar con su cuenta de Google vinculada:")
            oauth_warning = revisar_configuracion_oauth() if os.path.exists(CLIENT_SECRETS_FILE) else None
            if oauth_warning:
                st.warning(oauth_warning)
            st.caption("La autorización se abrirá con Microsoft Edge o Chrome, no necesariamente con tu navegador predeterminado.")
            
            # El token local de Google se conserva para Drive y Sheets.
            has_token = os.path.exists(TOKEN_FILE)

            if has_token:
                credenciales_actuales = get_google_credentials()
                if credenciales_actuales and not credenciales_actuales.has_scopes(
                    ["https://www.googleapis.com/auth/gmail.send"]
                ):
                    st.info(
                        "Para recibir y enviar alertas por correo debes actualizar "
                        "la autorización de Google en este equipo."
                    )
                    if st.button("Actualizar autorización para notificaciones"):
                        autenticar_google_escritorio()
                        st.rerun()
                if st.button("🟢 Ingresar con Google (Sesión Activa)", width="stretch"):
                    creds = get_google_credentials()
                    if creds:
                        user_email = obtener_email_google(creds)
                        usuarios = st.session_state.get("usuarios", {})
                        if user_email not in usuarios:
                            usuarios[user_email] = {
                                "alias": user_email,
                                "password": "",
                                "rol": "Super Administrador" if user_email == SUPER_ADMIN_EMAIL else "Sin Rol Asignado",
                                "estado": "Activo" if user_email == SUPER_ADMIN_EMAIL else "Pendiente",
                                "metodo": "Google",
                                "fecha_registro": str(datetime.date.today()),
                            }
                            st.session_state.usuarios = usuarios
                            guardar_local_json(st.session_state.db_expedientes)
                        if not cuenta_activa(usuarios.get(user_email)):
                            st.warning("Su cuenta de Google está pendiente de activación.")
                        else:
                            st.session_state.logged_user = user_email
                            st.session_state.logged_in = True
                            st.rerun()
            else:
                st.markdown("""
                    <style>
                    div[data-testid="stButton"] > button[key="btn_google_official"] {
                        background-color: #ffffff !important;
                        color: #1f2937 !important;
                        border: 1px solid #dadce0 !important;
                        border-radius: 6px !important;
                        font-family: 'Roboto', 'Segoe UI', sans-serif !important;
                        font-weight: 600 !important;
                        font-size: 15px !important;
                        height: 48px !important;
                        box-shadow: 0 1px 3px rgba(0,0,0,0.08) !important;
                        transition: background-color 0.2s, box-shadow 0.2s !important;
                    }
                    div[data-testid="stButton"] > button[key="btn_google_official"]:hover {
                        background-color: #f8fafc !important;
                        border-color: #d1d5db !important;
                        box-shadow: 0 2px 6px rgba(0,0,0,0.12) !important;
                    }
                    </style>
                """, unsafe_allow_html=True)

                if st.button("G  Continuar con Google", key="btn_google_official", width="stretch"):
                    with st.spinner("Iniciando autenticación... Por favor, complete el inicio de sesión en el navegador que se abrirá automáticamente."):
                        creds_res = autenticar_google_escritorio()
                        if creds_res:
                                user_email = obtener_email_google(creds_res)
                                usuarios = st.session_state.get("usuarios", {})
                                if user_email not in usuarios:
                                    usuarios[user_email] = {
                                        "alias": user_email,
                                        "password": "",
                                        "rol": "Super Administrador" if user_email == SUPER_ADMIN_EMAIL else "Sin Rol Asignado",
                                        "estado": "Activo" if user_email == SUPER_ADMIN_EMAIL else "Pendiente",
                                        "metodo": "Google",
                                        "fecha_registro": str(datetime.date.today()),
                                    }
                                    st.session_state.usuarios = usuarios
                                    guardar_local_json(st.session_state.db_expedientes)
                                if not cuenta_activa(usuarios.get(user_email)):
                                    st.warning("Su cuenta de Google está pendiente de activación.")
                                else:
                                    st.session_state.logged_user = user_email
                                    st.session_state.logged_in = True
                                    st.rerun()

        with tab_register:
            with st.form("form_reg"):
                reg_nombre = st.text_input("Nombre Completo *")
                reg_correo = st.text_input("Correo Institucional *").strip().lower()
                reg_pass = st.text_input("Contraseña *", type="password")
                btn_reg = st.form_submit_button("Crear Cuenta", width="stretch")

            if btn_reg:
                if not reg_nombre or not reg_correo or not reg_pass:
                    st.error("Por favor complete todos los campos obligatorios (*).")
                elif reg_correo not in st.session_state.get("usuarios", {}):
                    primer_usuario = not st.session_state.usuarios
                    remote_registered = supabase_registrar_password(
                        reg_correo, reg_pass, reg_nombre
                    )
                    st.session_state.usuarios[reg_correo] = {
                        "alias": reg_nombre,
                        "password": hash_password(reg_pass),
                        "rol": "Super Administrador" if primer_usuario else "Sin Rol Asignado",
                        "estado": "Activo" if primer_usuario else "Pendiente",
                        "metodo": "Supabase Auth" if remote_registered else "Clave Local",
                        "fecha_registro": str(datetime.date.today())
                    }
                    guardar_local_json(st.session_state.db_expedientes)
                    if primer_usuario:
                        st.success("Cuenta creada. Es el primer usuario y quedó habilitado como administrador.")
                    else:
                        notificar_super_admin(
                            "Nueva solicitud de activación - Sistema de Desvinculaciones",
                            (
                                f"Se registró una nueva cuenta pendiente.\n\n"
                                f"Nombre: {reg_nombre}\n"
                                f"Correo: {reg_correo}\n\n"
                                "Ingresa a Gestión de Permisos para asignar el rol y activar la cuenta."
                            ),
                        )
                        st.success("Solicitud registrada exitosamente. Un administrador debe activarla.")
                else:
                    st.warning("El correo ya se encuentra registrado.")

    st.stop()

# --- INFORMACIÓN DEL USUARIO LOGUEADO ---
correo_activo = st.session_state.logged_user
datos_usuario = st.session_state.usuarios.get(correo_activo)

if not datos_usuario:
    datos_usuario = {
        "alias": correo_activo if correo_activo else "Usuario Institucional",
        "rol": "Super Administrador" if correo_activo == SUPER_ADMIN_EMAIL else "Sin Rol Asignado",
        "estado": "Activo" if correo_activo == SUPER_ADMIN_EMAIL else "Pendiente",
        "metodo": "Google OAuth",
        "fecha_registro": str(datetime.date.today()),
    }
    if correo_activo:
        st.session_state.usuarios[correo_activo] = datos_usuario
        guardar_local_json(st.session_state.db_expedientes)

if st.session_state.get("supabase_access_token"):
    sincronizar_perfiles_remotos()
    datos_usuario = st.session_state.usuarios.get(correo_activo, datos_usuario)

if not cuenta_activa(datos_usuario):
    if cuenta_bloqueada(datos_usuario):
        st.error("Esta cuenta está bloqueada. Comuníquese con un administrador.")
    else:
        st.warning("Su cuenta está pendiente de aprobación. Un administrador debe asignarle un rol y activarla.")
    if st.button("Volver al inicio de sesión"):
        cerrar_sesion()
    st.stop()

actualizacion = st.session_state.get("actualizacion_disponible")
if actualizacion:
    with st.container(border=True):
        st.warning(
            f"Hay una nueva versión disponible: **{actualizacion['version']}**"
        )
        st.caption(actualizacion.get("changelog", "Sin notas de versión."))
        actualizar_col, despues_col = st.columns([1, 1])
        with actualizar_col:
            autorizar_actualizacion = st.button(
                "Actualizar ahora",
                type="primary",
                key="autorizar_actualizacion",
                width="stretch",
            )
        with despues_col:
            posponer_actualizacion = st.button(
                "Más tarde",
                key="posponer_actualizacion",
                width="stretch",
            )
        if posponer_actualizacion:
            st.session_state.actualizacion_disponible = None
            st.rerun()
        if autorizar_actualizacion:
            if not getattr(sys, "frozen", False):
                st.info(
                    "La actualización automática está disponible en el instalador "
                    "de Windows. Este entorno de desarrollo no puede reemplazarse."
                )
                if actualizacion.get("download_url"):
                    st.link_button(
                        "Descargar instalador manualmente",
                        actualizacion["download_url"],
                        width="stretch",
                    )
            elif not actualizacion.get("download_url"):
                st.error("La versión nueva no tiene una URL de instalador válida.")
            else:
                with st.spinner("Descargando y preparando la actualización..."):
                    try:
                        download_and_apply_update(actualizacion["download_url"])
                    except (OSError, RuntimeError, ValueError, requests.RequestException) as error:
                        st.error(f"No fue posible iniciar la actualización: {error}")

rol_actual = datos_usuario.get("rol", "Sin Rol Asignado")
estado_actual = datos_usuario.get("estado", "Pendiente")

es_admin = rol_actual in ["Super Administrador", "Administrador"]
es_modificador = rol_actual in ["Super Administrador", "Administrador", "Modificador"]
es_super_admin = rol_actual == "Super Administrador"
puede_abrir_google = es_modificador
puede_descargar = puede_descargar_documentos(datos_usuario)
puede_eliminar = puede_eliminar_documentos(datos_usuario)

opciones_permitidas = opciones_autorizadas(rol_actual)
if st.session_state.navegacion not in opciones_permitidas:
    st.session_state.navegacion = "Inicio"
opciones_menu = [
    opcion for opcion in [
        "Inicio", "Entrada de Expedientes", "Consulta & Archivo",
        "Base Histórica", "Gestión de Permisos", "Buzón de Mensajes", "Mi Perfil",
    ]
    if opcion in opciones_permitidas
]

# --- NAVEGACIÓN LATERAL ---
with st.sidebar:
    if os.path.exists(IMG_LOGO):
        sidebar_logo_data = get_image_base64(IMG_LOGO)
        st.markdown(
            f'<div class="sidebar-brand"><img src="{sidebar_logo_data}" '
            'alt="Secretaría de Tránsito y Transporte - Desvinculaciones"></div>',
            unsafe_allow_html=True,
        )
    st.markdown("### Sistema de desvinculaciones")
    st.caption(datos_usuario["alias"])
    st.caption(f"Lectura local: {estado_ocr_local()}")
    estado_ollama = estado_descarga_modelo()
    if estado_ollama.get("running"):
        st.info(f"IA local: {estado_ollama.get('message') or 'preparando modelo'}")
    elif estado_ollama.get("error"):
        st.warning(f"IA local: {estado_ollama['error']}")
    elif buscar_ollama() and ollama_disponible():
        modelos_disponibles = obtener_modelos_ollama()
        if OLLAMA_REQUIRED_MODEL in modelos_disponibles:
            st.caption(f"IA local: {OLLAMA_REQUIRED_MODEL} disponible")
        else:
            st.warning(f"IA local: falta descargar {OLLAMA_REQUIRED_MODEL}")
    st.divider()
    for opc in opciones_menu:
        if opc in {"Google Drive", "Hoja Google Sheets"}:
            continue
        etiqueta = opc
        if opc == "Buzón de Mensajes" and es_super_admin:
            pendientes = len(obtener_usuarios_pendientes())
            solicitudes = len(obtener_solicitudes_descarga())
            soporte = sum(
                1 for mensaje in st.session_state.get("mensajes_soporte", [])
                if not mensaje.get("leido")
            )
            total_avisos = pendientes + solicitudes + soporte
            if total_avisos:
                etiqueta = f"🔔 {opc} ({total_avisos})"
            else:
                etiqueta = f"🔔 {opc}"
        if st.button(etiqueta, key=f"btn_side_{opc}", width="stretch"):
            st.session_state.navegacion = opc
            st.rerun()
    st.divider()
    if st.button("Cerrar sesión", key="btn_side_logout", width="stretch"):
        cerrar_sesion()

if st.session_state.navegacion == "Inicio":

    if os.path.exists(IMG_LOGO):
        logo_data = get_image_base64(IMG_LOGO)
        st.markdown(
            f'<div class="brand-logo-wrap"><img class="brand-logo" src="{logo_data}" '
            'alt="Secretaría de Tránsito y Transporte - Desvinculaciones"></div>',
            unsafe_allow_html=True,
        )
    st.markdown("""
        <div class="header-box">
            <div class="header-title">SECRETARÍA DE TRÁNSITO Y TRANSPORTE - DESVINCULACIONES</div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="launcher-title">Aplicaciones del sistema</div>', unsafe_allow_html=True)
    mosaico = []
    if "Entrada de Expedientes" in opciones_permitidas:
        mosaico.append((IMG_CARD_REGISTRO, "Registro de Entrada", f"?nav={quote('Entrada de Expedientes')}"))
    if "Consulta & Archivo" in opciones_permitidas:
        mosaico.append((IMG_CARD_BUSCADOR, "Buscador & Archivo", f"?nav={quote('Consulta & Archivo')}"))
    if puede_abrir_google:
        mosaico.extend([
            (
                IMG_CARD_DRIVE,
                "Google Drive",
                enlace_aplicacion_externa(
                    f"https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}",
                    "Google Drive",
                ),
            ),
            (
                IMG_CARD_SHEETS,
                "Google Sheets",
                enlace_aplicacion_externa(SHEET_URL, "Google Sheets"),
            ),
        ])
    if es_super_admin:
        mosaico.append((IMG_CARD_PERMISOS, "Gestión Permisos", f"?nav={quote('Gestión de Permisos')}"))
    mosaico.append((IMG_CARD_PERFIL, "Mi Perfil", f"?nav={quote('Mi Perfil')}"))
    render_launcher_grid(mosaico)

    expedientes = list(st.session_state.db_expedientes.values())
    total_expedientes = len(expedientes)
    completos = sum(
        1 for expediente in expedientes
        if expediente.get("estado") == "COMPLETO"
    )
    pendientes_documentales = sum(
        1 for expediente in expedientes
        if documentos_faltantes(expediente)
    )
    documentos_drive = sum(
        len(expediente.get("canvas_paginas", []))
        for expediente in expedientes
    )
    st.markdown('<div class="launcher-title">Estado del archivo</div>', unsafe_allow_html=True)
    resumen_1, resumen_2, resumen_3, resumen_4 = st.columns(4)
    resumen_1.metric("Expedientes", total_expedientes)
    resumen_2.metric("Completos", completos)
    resumen_3.metric("Con faltantes", pendientes_documentales)
    resumen_4.metric("Documentos registrados", documentos_drive)
    st.caption(
        "El escritorio muestra el estado de la base local sincronizada. "
        "Los documentos y sus enlaces se consultan desde el expediente y Google Drive."
    )

elif st.session_state.navegacion == "Entrada de Expedientes":
    if st.button("⬅️ Volver al Inicio"):
        st.session_state.navegacion = "Inicio"
        st.rerun()

    st.header("Entrada y Digitalización de Desvinculaciones")

    if not es_modificador:
        st.warning("Rol de Visualizador: Modo de solo lectura.")
    else:
        editor_pdf = ruta_editor_pdf()
        if editor_pdf:
            if st.button(
                "Abrir Editor PDF local",
                key="abrir_editor_pdf_entrada",
                help="Une, divide, gira o extrae páginas antes de cargarlas al expediente.",
            ):
                try:
                    abrir_editor_pdf()
                except (FileNotFoundError, OSError, subprocess.SubprocessError) as error:
                    st.error(f"No fue posible abrir el Editor PDF local: {error}")
        else:
            st.caption(
                "El Editor PDF local no está disponible en esta instalación. "
                "Los PDFs aún se procesan directamente desde este formulario."
            )
        st.subheader("1. Cargar documentos")
        st.caption(
            "Carga primero el PDF completo o los documentos individuales. "
            "El sistema intentará identificar el radicado, la placa, la fecha y el desenlace."
        )
        archivos_canvas = st.file_uploader(
            "Seleccionar documentos (PDF, PNG, JPG o JPEG)",
            type=["pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key=f"archivos_canvas_{st.session_state.form_registro_version}",
        )
        st.markdown("#### Organización documental")
        st.caption(
            "Define primero qué documentos debe contener el expediente y qué tipo "
            "tendrán los archivos cargados."
        )
        documentos_col, tipo_col = st.columns(2)
        with documentos_col:
            documentos_esperados = st.multiselect(
                "Documentos esperados",
                options=TIPOS_DOCUMENTALES,
                default=["Solicitud"],
                key=f"documentos_esperados_{st.session_state.form_registro_version}",
            )
        with tipo_col:
            tipo_documento = st.selectbox(
                "Tipo del archivo que vas a anexar",
                options=TIPOS_DOCUMENTALES,
                index=TIPOS_DOCUMENTALES.index("Solicitud"),
                key=f"tipo_documento_{st.session_state.form_registro_version}",
            )
        carga_id = (
            huella_contenido(
                b"".join(archivo.getvalue() for archivo in archivos_canvas)
            )[:12]
            if archivos_canvas
            else f"v{st.session_state.form_registro_version}"
        )
        peticion_incluida = st.checkbox(
            "La petición principal está incluida en esta carga",
            value=tipo_documento == "Solicitud",
            key=f"peticion_incluida_{carga_id}",
            help=(
                "Si se carga un anexo suelto, desmarca esta opción y completa "
                "manualmente el radicado y la fecha de creación de la petición."
            ),
        )
        if tipo_documento == "Expediente completo":
            st.info(
                "Si cargas varios documentos individuales, selecciona su tipo "
                "específico. 'Expediente completo' se reserva para un PDF unificado."
            )
        orden_archivos = []
        datos_carga = {}
        datos_sheet = {}
        tipos_carga = set()
        tipos_documentales_carga = set()
        textos_analizados = {}
        partes_analizadas_por_archivo = {}
        contenidos_visuales_ia = []
        paginas_criticas_por_archivo = {}
        fecha_carga = None
        tipo_caso_detectado = ""
        if archivos_canvas:
            opciones_orden = [
                f"{indice + 1:02d} - {archivo.name}"
                for indice, archivo in enumerate(archivos_canvas)
            ]
            orden_archivos = st.multiselect(
                "Orden documental del expediente",
                options=opciones_orden,
                default=opciones_orden,
            )
            barra_analisis = st.progress(
                0,
                text=f"Preparando análisis de {len(archivos_canvas)} archivo(s)...",
            )
            estado_analisis = st.empty()
            total_archivos = len(archivos_canvas)
            for indice_archivo, archivo in enumerate(archivos_canvas, start=1):
                estado_analisis.info(
                    f"Analizando archivo {indice_archivo} de {total_archivos}: "
                    f"**{archivo.name}**. El OCR puede tardar según el número de páginas."
                )
                contenido = archivo.getvalue()
                contenido_analizable = contenido
                if not archivo.name.lower().endswith(".pdf"):
                    try:
                        contenido_analizable = convertir_imagen_a_pdf(
                            contenido,
                            archivo.name,
                        )
                    except ValueError:
                        contenido_analizable = b""
                if archivo.name.lower().endswith(".pdf"):
                    paginas_hibridas, texto_archivo = extraer_paginas_hibridas_pdf(
                        contenido_analizable,
                        lambda pagina, total, indice=indice_archivo: barra_analisis.progress(
                            min(
                                (indice - 1 + (pagina / max(total, 1)))
                                / total_archivos,
                                1.0,
                            ),
                            text=(
                                f"Analizando archivo {indice} de {total_archivos}: "
                                f"página {pagina} de {total}"
                            ),
                        ),
                    )
                    partes_analisis = separar_pdf_con_textos(
                        contenido_analizable,
                        tipo_documento,
                        paginas_hibridas,
                    )
                    clave_contenido = huella_contenido(contenido_analizable)
                    partes_analizadas_por_archivo[clave_contenido] = partes_analisis
                    if partes_analisis and len(partes_analisis) > 1 and not texto_archivo:
                        textos_partes = []
                        for parte in partes_analisis:
                            subtexto = normalizar_texto_documento(
                                parte.get("texto")
                                or extraer_texto_pdf_con_progreso(
                                    parte.get("contenido") or contenido_analizable,
                                    lambda pagina, total, indice=indice_archivo, nombre=archivo.name: barra_analisis.progress(
                                        min(
                                            (indice - 1 + (pagina / max(total, 1)))
                                            / total_archivos,
                                            1.0,
                                        ),
                                        text=(
                                            f"Analizando {nombre}: página {pagina} de {total}"
                                        ),
                                    ),
                                )
                            )
                            if subtexto:
                                textos_partes.append(subtexto)
                        texto_archivo = normalizar_texto_documento(" ".join(textos_partes))
                    else:
                        paginas_hibridas, texto_archivo = extraer_paginas_hibridas_pdf(
                            contenido_analizable,
                            lambda pagina, total, indice=indice_archivo: barra_analisis.progress(
                                min(
                                    (indice - 1 + (pagina / max(total, 1)))
                                    / total_archivos,
                                    1.0,
                                ),
                                text=(
                                    f"Analizando archivo {indice} de {total_archivos}: "
                                    f"página {pagina} de {total}"
                                ),
                            ),
                        )
                        paginas_criticas = [
                            item["pagina"] for item in paginas_hibridas if item["critica"]
                        ]
                        if len(paginas_criticas) > 8:
                            paginas_priorizadas = sorted(
                                (
                                    item for item in paginas_hibridas
                                    if item["pagina"] in paginas_criticas
                                ),
                                key=lambda item: (
                                    not bool(re.search(
                                        r"firma|sello|manuscrit",
                                        item["texto"],
                                        re.IGNORECASE,
                                    )),
                                    len(item["texto"]),
                                ),
                            )
                            paginas_criticas = [
                                item["pagina"] for item in paginas_priorizadas[:8]
                            ]
                        if paginas_criticas:
                            paginas_criticas_por_archivo[clave_contenido] = paginas_criticas
                            contenidos_visuales_ia.append(
                                (archivo.name, contenido_analizable, paginas_criticas)
                            )
                else:
                    texto_archivo = normalizar_texto_documento(
                        extraer_texto_pdf_con_progreso(
                            contenido_analizable,
                            lambda pagina, total, indice=indice_archivo: barra_analisis.progress(
                                min(
                                    (indice - 1 + (pagina / max(total, 1)))
                                    / total_archivos,
                                    1.0,
                                ),
                                text=(
                                    f"Analizando archivo {indice} de {total_archivos}: "
                                    f"página {pagina} de {total}"
                                ),
                            ),
                        )
                    )
                textos_analizados[huella_contenido(contenido_analizable)] = texto_archivo
                datos_archivo = extraer_datos_pdf(
                    contenido_analizable,
                    texto=texto_archivo,
                )
                if archivo.name.lower().endswith(".pdf"):
                    for parte in (
                        partes_analizadas_por_archivo.get(
                            huella_contenido(contenido_analizable),
                            [],
                        )
                        or []
                    ):
                        if parte.get("texto") or parte.get("contenido"):
                            combinar_datos_detectados(
                                datos_archivo,
                                extraer_datos_pdf(
                                    parte.get("contenido") or contenido_analizable,
                                    texto=parte.get("texto") or texto_archivo,
                                ),
                            )
                combinar_datos_detectados(
                    datos_carga,
                    datos_archivo,
                )
                coincidencia_radicado = re.search(
                    r"(?<!\d)(\d{15,22})(?!\d)",
                    archivo.name,
                )
                if coincidencia_radicado:
                    datos_carga["radicado_padre"] = coincidencia_radicado.group(1)
                tipo_detectado = clasificar_tipo_caso(
                    texto_archivo,
                    archivo.name,
                )
                estado_documento = detectar_estado_documento(
                    texto_archivo,
                    tipo_documento,
                )
                datos_archivo["estado_carga"] = estado_documento
                datos_archivo["paginas_por_seccion"] = [
                    {
                        "tipo": parte.get("tipo", "Otro"),
                        "paginas": parte.get("paginas_por_seccion", []),
                    }
                    for parte in (
                        partes_analizadas_por_archivo.get(
                            huella_contenido(contenido_analizable),
                            [],
                        )
                        if archivo.name.lower().endswith(".pdf")
                        else []
                    )
                ]
                if tipo_detectado:
                    tipos_carga.add(tipo_detectado)
                tipos_documentales_archivo = tipos_documentales_detectados(
                    texto_archivo,
                    tipo_documento,
                )
                if archivo.name.lower().endswith(".pdf"):
                    partes_clasificadas = partes_analizadas_por_archivo.get(
                        huella_contenido(contenido_analizable),
                        [],
                    )
                    tipos_documentales_archivo.update(
                        parte.get("tipo")
                        for parte in partes_clasificadas
                        if parte.get("tipo")
                    )
                tipos_documentales_carga.update(tipos_documentales_archivo)
            barra_analisis.progress(
                0.75,
                text="OCR terminado. Clasificando y organizando el expediente...",
            )
            estado_analisis.success(
                "Lectura de los archivos terminada. Revisa los datos detectados "
                "antes de guardar."
            )
            expediente_coincidente = buscar_expediente_local_por_coincidencias(
                st.session_state.db_expedientes,
                datos_carga,
            )
            if expediente_coincidente:
                combinar_datos_por_coincidencia(datos_carga, expediente_coincidente)
                st.info(
                    "Se encontraron coincidencias en la base local por radicado, "
                    "placa o datos administrativos. Se usaron para completar "
                    "campos que el OCR no pudo leer."
                )
            if datos_carga:
                st.success(
                    "Datos detectados: "
                    + ", ".join(f"{campo}={valor}" for campo, valor in datos_carga.items())
                )
                if datos_carga.get("radicado_revision"):
                    st.warning(
                        "El OCR detectó un radicado que puede contener un dígito "
                        "incorrecto. Revisa y corrige **Radicado Padre (Orfeo)** "
                        "manualmente antes de guardar."
                    )
                st.info(
                    "Revisa especialmente radicado padre, placa, fechas, "
                    "información administrativa y ubicación física. La "
                    "información confirmada en el formulario tiene prioridad "
                    "sobre la lectura automática."
                )
            else:
                st.warning(
                    "No se encontró texto seleccionable en los archivos. "
                    "Si el PDF es un escaneo como imagen, completa los campos "
                    "manualmente o habilita OCR en el equipo."
                )
                if _ocr_last_error:
                    st.warning(
                        "El OCR no pudo procesar el PDF: "
                        f"{_ocr_last_error}. Revisa que el paquete instalado "
                        "incluya los recursos de RapidOCR."
                    )
            # Ollama se ejecuta automáticamente una sola vez por carga. El
            # resultado se conserva en session_state para evitar repetir el
            # análisis en cada rerun de Streamlit.
            clave_ia = f"analisis_ia_local_{carga_id}"
            clave_intento_ia = f"analisis_ia_local_intento_{carga_id}"
            texto_ocr_completo = normalizar_texto_documento(
                " ".join(textos_analizados.values())
            )
            campos_criticos_faltantes = {
                campo for campo in (
                    "radicado_padre",
                    "placa",
                    "fecha_solicitud",
                    "empresa",
                    "nit",
                    "propietario",
                    "cedula",
                ) if not datos_carga.get(campo)
            }
            vision_necesaria = bool(
                paginas_criticas_por_archivo and campos_criticos_faltantes
            )
            if (
                analizar_paginas_local is not None
                and not st.session_state.get(clave_ia)
                and not st.session_state.get(f"{clave_intento_ia}_vision")
                and contenidos_visuales_ia
                and vision_necesaria
            ):
                st.session_state[f"{clave_intento_ia}_vision"] = True
                if buscar_ollama():
                    iniciar_servicio_ollama()
                modelos_locales = (
                    obtener_modelos_ollama() if ollama_disponible() else []
                )
                if OLLAMA_VISION_MODEL in modelos_locales:
                    try:
                        resultado_visual = {
                            "documentos_detectados": [],
                            "paginas_por_seccion": [],
                            "faltantes": [],
                        }
                        for nombre_pdf, contenido_pdf, paginas_criticas in contenidos_visuales_ia:
                            for inicio in range(0, len(paginas_criticas), 2):
                                paginas = [
                                    pagina
                                    for numero in paginas_criticas[inicio:inicio + 2]
                                    for pagina in paginas_visuales_para_ia(
                                        contenido_pdf,
                                        inicio=numero,
                                        maximo=1,
                                    )
                                ]
                                if not paginas:
                                    continue
                                with st.spinner(
                                    f"Ollama Vision analiza {nombre_pdf}: "
                                    f"páginas {paginas_criticas[inicio]}..."
                                ):
                                    lote = analizar_paginas_local(
                                        paginas,
                                        modelo=OLLAMA_VISION_MODEL,
                                    )
                                for clave in ("documentos_detectados", "paginas_por_seccion", "faltantes"):
                                    valores = lote.get(clave)
                                    if isinstance(valores, list):
                                        resultado_visual[clave].extend(valores)
                                for campo in FORMULARIO_CAMPOS:
                                    valor = lote.get(campo)
                                    if (
                                        campo not in resultado_visual
                                        or not resultado_visual.get(campo)
                                    ) and isinstance(valor, (str, int, float)) and str(valor).strip():
                                        resultado_visual[campo] = valor
                                combinar_campos_ia(datos_carga, lote)
                        st.session_state[clave_ia] = resultado_visual
                        st.success(
                            "Ollama Vision analizó las páginas con evidencia visual. "
                            "Revisa los campos y el checklist antes de guardar. "
                            "Se usó únicamente porque el OCR no produjo texto suficiente."
                        )
                    except (ConnectionError, TimeoutError, ValueError) as error:
                        st.warning(
                            f"Ollama Vision no pudo analizar las páginas: {error}. "
                            "Se conserva el OCR como respaldo explícito."
                        )
                else:
                    st.info(
                        f"El modelo visual `{OLLAMA_VISION_MODEL}` no está instalado. "
                        "La carga continuará con OCR y análisis textual."
                    )
            if (
                analizar_expediente_local is not None
                and analisis_a_markdown is not None
                and texto_ocr_completo
                and len(texto_ocr_completo) <= 12000
                and campos_criticos_faltantes
                and not st.session_state.get(clave_ia)
                and not st.session_state.get(clave_intento_ia)
            ):
                st.session_state[clave_intento_ia] = True
                if buscar_ollama():
                    iniciar_servicio_ollama()
                if ollama_disponible():
                    modelos_locales = obtener_modelos_ollama()
                    if OLLAMA_REQUIRED_MODEL in modelos_locales:
                        try:
                            with st.spinner(
                                f"La IA local está extrayendo datos con {OLLAMA_REQUIRED_MODEL}..."
                            ):
                                resultado_ia = analizar_expediente_local(
                                    texto_ocr_completo,
                                    modelo=OLLAMA_TEXT_MODEL,
                                )
                            st.session_state[clave_ia] = resultado_ia
                            combinar_campos_ia(datos_carga, resultado_ia)
                            st.success(
                                "Ollama revisó únicamente el texto corto con campos faltantes. "
                                "Revisa la evidencia antes de guardar."
                            )
                        except (ConnectionError, TimeoutError, ValueError) as error:
                            st.warning(
                                f"Ollama no pudo completar la extracción automática: {error}. "
                                "Se conserva el OCR y el respaldo por expresiones regulares."
                            )
                    else:
                        st.warning(
                            f"Ollama está activo, pero el modelo `{OLLAMA_REQUIRED_MODEL}` "
                            "no está descargado. Se usará el OCR y las reglas locales."
                        )
                else:
                    st.warning(
                        "Ollama no está disponible en localhost. Se usará el OCR y el "
                        "las reglas locales."
                    )
            resultado_ia_automatico = st.session_state.get(clave_ia)
            if resultado_ia_automatico:
                combinar_campos_ia(datos_carga, resultado_ia_automatico)
                tipos_documentales_carga.update(
                    tipos_documentales_desde_ia(resultado_ia_automatico)
                )
                for partes in partes_analizadas_por_archivo.values():
                    aplicar_clasificacion_ia_a_partes(
                        partes,
                        resultado_ia_automatico,
                    )
                tipos_documentales_carga.update(
                    parte.get("tipo")
                    for partes in partes_analizadas_por_archivo.values()
                    for parte in partes
                    if parte.get("tipo")
                )
            tipo_caso_ia = normalizar_tipo_caso(
                (resultado_ia_automatico or {}).get("tipo_caso")
            )
            tipo_caso_detectado = (
                tipo_caso_ia
                or clasificar_tipo_caso(
                    " ".join(textos_analizados.values()),
                    " ".join(archivo.name for archivo in archivos_canvas),
                )
            )
            if tipo_caso_detectado not in TIPOS_CASO:
                tipo_caso_detectado = datos_carga.get("tipo_caso", "")
            ruta_documento = enrutar_documento_cargado(
                datos_carga,
                es_complemento=not peticion_incluida,
                drive_service=drive_service,
            )
            if ruta_documento["estado"] == "PENDIENTE_VINCULACION":
                st.info(
                    "El complemento se conservará en Por_vincular hasta localizar "
                    "el expediente principal."
                )
            elif ruta_documento["estado"] == "ACTUALIZADO_CON_COMPLEMENTO":
                st.success(
                    "Se encontró el expediente principal. El complemento se "
                    "integrará directamente en su subcarpeta documental."
                )
            carga_staging = st.session_state.setdefault("_cargas_drive", {})
            if drive_service and carga_id not in carga_staging:
                documentos_staged, carpeta_staged, error_staging = preparar_carga_drive(
                    drive_service,
                    archivos_canvas,
                    datos_carga.get("radicado_padre", ""),
                    datos_carga.get("placa", ""),
                    datos_carga.get("fecha_solicitud", ""),
                    tipo_documento,
                    carga_id,
                    es_complemento=not peticion_incluida,
                    partes_analizadas=partes_analizadas_por_archivo,
                )
                if error_staging:
                    st.warning(error_staging)
                elif documentos_staged:
                    carga_staging[carga_id] = {
                        "documentos": documentos_staged,
                        "drive_folder_id": carpeta_staged,
                        "estado": (
                            "PENDIENTE_VINCULACION"
                            if not peticion_incluida
                            else "EXPEDIENTE_PRINCIPAL"
                        ),
                    }
                    st.success(
                        "Partes documentales subidas a Drive para continuar el análisis. "
                        "El PDF unificado se generará al completar el registro."
                    )
            staged_actual = carga_staging.get(carga_id) or {}
            for documento_staged in staged_actual.get("documentos", []):
                tipo_staged = normalizar_tipo_documental(
                    documento_staged.get("tipo_documento", "")
                )
                if tipo_staged:
                    tipos_documentales_carga.add(tipo_staged)
            if not drive_service:
                st.warning(
                    "Drive no está autenticado: la carga se conserva localmente y "
                    "no se puede crear la estructura documental remota."
                )
            barra_analisis.progress(
                0.9,
                text="Clasificación y carga preliminar terminadas. Revisa el formulario.",
            )
            if len(tipos_carga) == 1:
                st.info(f"Desenlace detectado: {next(iter(tipos_carga))}")
            elif len(tipos_carga) > 1:
                st.warning("Se detectaron varios desenlaces; revisa que pertenezcan al mismo expediente.")
            tipo_checklist = tipo_caso_detectado or next(
                iter(tipos_carga),
                "Detección automática",
            )
            if tipo_checklist in DOCUMENTOS_BASE_POR_CASO:
                documentos_checklist = set(tipos_documentales_carga)
                if tipo_checklist == "Con recurso":
                    documentos_checklist.add("Recurso")
                renderizar_checklist_documental(
                    tipo_checklist,
                    sorted(documentos_checklist),
                )
            campos_detectados = sorted(
                campo.replace("_", " ").capitalize()
                for campo, valor in datos_carga.items()
                if valor
            )
            with st.container(border=True):
                st.markdown("#### Resumen de la carga")
                resumen_col1, resumen_col2, resumen_col3 = st.columns(3)
                resumen_col1.metric("Archivos recibidos", len(archivos_canvas))
                resumen_col2.metric("Campos leídos", len(campos_detectados))
                resumen_col3.metric(
                    "Desenlace",
                    tipo_checklist if tipo_checklist in TIPOS_CASO else "Por confirmar",
                )
                st.write(
                    "✅ Archivo recibido y analizado. "
                    "Los datos encontrados se cargaron en el formulario."
                )
                if campos_detectados:
                    st.caption(
                        "Campos que se intentarán registrar: "
                        + ", ".join(campos_detectados)
                    )
                else:
                    st.warning(
                        "No se encontraron datos legibles automáticamente. "
                        "Completa los campos manualmente antes de guardar."
                    )
                st.caption(
                    "Antes de guardar, revisa los campos resaltados y confirma "
                    "que la información corresponda al expediente."
                )
            st.markdown("#### Análisis documental con IA local")
            st.caption(
                f"Opcional y privado: usa Ollama en este equipo con el modelo "
                f"`{OLLAMA_MODEL}`. El OCR no se envía a Internet."
            )
            if ollama_disponible():
                modelos_locales = obtener_modelos_ollama()
                if OLLAMA_REQUIRED_MODEL not in modelos_locales:
                    clave_pull = f"ollama_pull_iniciado_{carga_id}"
                    if not st.session_state.get(clave_pull):
                        if descargar_modelo_en_segundo_plano(OLLAMA_REQUIRED_MODEL):
                                st.session_state[clave_pull] = True
                                st.info(
                                    f"Ollama está descargando `{OLLAMA_REQUIRED_MODEL}` "
                                    "en segundo plano. Puedes continuar revisando el formulario."
                                )
                    estado_pull = estado_descarga_modelo()
                    if estado_pull.get("running"):
                        st.info(str(estado_pull.get("message") or "Descargando modelo local..."))
                    elif estado_pull.get("error"):
                        st.warning(
                                f"No fue posible descargar automáticamente el modelo: "
                                f"{estado_pull['error']}"
                        )
                    else:
                        st.warning(
                                f"El modelo `{OLLAMA_REQUIRED_MODEL}` todavía no está disponible. "
                                "La descarga automática quedó iniciada en segundo plano."
                        )
                st.caption(
                    "El análisis estructurado se ejecuta automáticamente después del OCR. "
                    "Los campos ya confirmados conservan prioridad."
                )
            else:
                st.info(
                    "IA local no disponible todavía. Instala Ollama, inicia su servicio "
                    f"y descarga el modelo `{OLLAMA_MODEL}` para habilitar este análisis."
                )
                if st.button(
                    "Descargar e instalar Ollama",
                    key=f"descargar_ollama_{carga_id}",
                ):
                    try:
                        if not webbrowser.open(OLLAMA_DOWNLOAD_URL):
                            raise RuntimeError(
                                "Windows no pudo abrir el navegador para la descarga."
                            )
                        st.success(
                            "Se abrió la descarga oficial de Ollama. "
                            "Después de instalarlo, reinicia su servicio y vuelve a "
                            "usar el botón de descarga del modelo."
                        )
                    except (OSError, RuntimeError) as error:
                        st.error(
                            f"No fue posible abrir la descarga de Ollama: {error}"
                        )
            resultado_ia_guardado = st.session_state.get(f"analisis_ia_local_{carga_id}")
            if resultado_ia_guardado and analisis_a_markdown is not None:
                with st.container(border=True):
                    st.markdown(analisis_a_markdown(resultado_ia_guardado))
            st.markdown("#### Vista previa y destino del documento")
            destino_radicado = datos_carga.get("radicado_padre", "")
            destino_placa = datos_carga.get("placa", "")
            destino_fecha = datos_carga.get("fecha_solicitud", "")
            expediente_vista = st.session_state.db_expedientes.get(
                str(destino_radicado).strip()
            )
            if expediente_vista:
                destino_fecha = destino_fecha or expediente_vista.get("fecha_solicitud", "")
                destino_placa = destino_placa or expediente_vista.get("placa", "")
            if destino_fecha:
                try:
                    anio_destino = datetime.date.fromisoformat(
                        str(destino_fecha)
                    ).year
                    destino_texto = (
                        f"Peticion/{anio_destino}/"
                        f"{destino_radicado or 'RADICADO_PENDIENTE'}_"
                        f"{destino_placa or 'PLACA_PENDIENTE'}"
                    )
                except ValueError:
                    destino_texto = "Carpeta anual pendiente de confirmar la fecha de petición"
            else:
                destino_texto = (
                    "Peticion/ "
                    f"{destino_radicado or destino_placa or 'IDENTIFICADOR_PENDIENTE'}"
                )
            vista_col, destino_col = st.columns([1.35, 1])
            with destino_col:
                st.info(f"**Destino previsto**\n\n`{destino_texto}`")
                if expediente_vista:
                    st.success("Este radicado ya tiene un expediente registrado.")
                    if expediente_vista.get("drive_folder") and puede_descargar:
                        st.markdown(
                            f"[Abrir carpeta actual del expediente]({expediente_vista['drive_folder']})"
                        )
                    if expediente_vista.get("pdf_unificado") and puede_descargar:
                        st.markdown(
                            f"[Abrir PDF completo actual]({expediente_vista['pdf_unificado']})"
                        )
                    if (
                        not puede_descargar
                        and (expediente_vista.get("drive_folder") or expediente_vista.get("pdf_unificado"))
                    ):
                        st.caption(
                            "El acceso directo de Drive y la descarga están reservados "
                            "para usuarios autorizados."
                        )
                else:
                    st.caption(
                        "El destino final se confirmará al guardar, después de "
                        "validar el radicado, la placa y la fecha."
                    )
            with vista_col:
                for indice, archivo in enumerate(archivos_canvas):
                    with st.expander(
                        f"Ver archivo {indice + 1}: {archivo.name}",
                        expanded=indice == 0,
                    ):
                        contenido_vista = archivo.getvalue()
                        nombre_vista = archivo.name
                        if not nombre_vista.lower().endswith(".pdf"):
                            try:
                                contenido_vista = convertir_imagen_a_pdf(
                                    contenido_vista,
                                    nombre_vista,
                                )
                                nombre_vista = f"{os.path.splitext(nombre_vista)[0]}.pdf"
                            except ValueError:
                                pass
                        mostrar_documento_en_aplicacion(
                            contenido_vista,
                            nombre_vista,
                            solo_lectura=True,
                        )
            registro_sheet = buscar_registro_en_sheets(
                sheets_service,
                datos_carga.get("radicado_padre", ""),
                datos_carga.get("placa", ""),
                datos_carga.get("fecha_solicitud", ""),
                datos_carga.get("empresa", ""),
                datos_carga.get("nit", ""),
                datos_carga.get("cedula", ""),
            )
            datos_sheet = datos_registro_sheet(registro_sheet)
            if datos_sheet:
                st.info(
                    "Este expediente ya está registrado en Google Sheets. "
                    "Se usarán sus datos actuales y solo se completarán campos faltantes."
                )
                st.caption(
                    "Campos encontrados en Sheets: "
                    + ", ".join(datos_sheet.keys())
                )
            combinar_datos_por_coincidencia(datos_carga, datos_sheet)
            if datos_carga.get("fecha_solicitud"):
                try:
                    fecha_carga = datetime.date.fromisoformat(
                        datos_carga["fecha_solicitud"]
                    )
                except ValueError:
                    st.warning("La fecha detectada no pudo convertirse; debes verificarla.")

        foliacion_detectada = 0
        for archivo in archivos_canvas:
            if not archivo.name.lower().endswith(".pdf") or PdfReader is None:
                continue
            try:
                foliacion_detectada += len(PdfReader(io.BytesIO(archivo.getvalue())).pages)
            except (OSError, ValueError):
                continue
        foliacion_inicial = int(datos_carga.get("foliacion") or foliacion_detectada or 0)
        campos_formulario = {
            f"radicado_padre_{carga_id}": datos_carga.get("radicado_padre", ""),
            f"fecha_solicitud_{carga_id}": fecha_carga,
            f"matricula_qx_{carga_id}": datos_carga.get("placa", ""),
            f"resolucion_{carga_id}": datos_carga.get("resolucion", ""),
            f"empresa_{carga_id}": datos_carga.get("empresa", ""),
            f"nit_{carga_id}": datos_carga.get("nit", ""),
            f"propietario_{carga_id}": datos_carga.get("propietario", ""),
            f"cedula_{carga_id}": datos_carga.get("cedula", ""),
            f"direccion_empresa_{carga_id}": datos_carga.get("direccion_empresa", ""),
            f"correo_{carga_id}": datos_carga.get("correo", ""),
            f"funcionario_{carga_id}": datos_carga.get(
                "funcionario",
                "",
            ),
            f"observacion_{carga_id}": datos_carga.get("observacion", ""),
            f"tipo_caso_{carga_id}": (
                tipo_caso_detectado
                if tipo_caso_detectado in TIPOS_CASO
                else "Detección automática"
            ),
            f"solicitante_{carga_id}": datos_carga.get("solicitante", "Propietario"),
            f"qx_verificado_{carga_id}": bool(datos_carga.get("qx_verificado", False)),
            f"fecha_resolucion_{carga_id}": fecha_para_formulario(
                datos_carga.get("fecha_resolucion")
            ),
            f"tipo_notificacion_{carga_id}": datos_carga.get("tipo_notificacion", ""),
            f"fecha_notificacion_{carga_id}": fecha_para_formulario(
                datos_carga.get("fecha_notificacion")
            ),
            f"fecha_ejecutoria_{carga_id}": fecha_para_formulario(
                datos_carga.get("fecha_ejecutoria")
            ),
            f"fecha_remision_{carga_id}": fecha_para_formulario(
                datos_carga.get("fecha_remision_registro")
            ),
            f"remitido_{carga_id}": bool(datos_carga.get("remitido", False)),
            f"notas_{carga_id}": datos_carga.get("notas", ""),
            f"direccion_propietario_{carga_id}": datos_carga.get(
                "direccion_propietario",
                "",
            ),
            f"nueva_empresa_{carga_id}": datos_carga.get("nueva_empresa", ""),
            f"recurso_{carga_id}": datos_carga.get("recurso", ""),
            f"fecha_recurso_{carga_id}": fecha_para_formulario(
                datos_carga.get("fecha_recurso")
            ),
            f"fecha_radicacion_{carga_id}": datos_carga.get("fecha_radicacion", ""),
            f"observacion_{carga_id}": datos_carga.get("observacion", ""),
            f"ubicacion_fisica_{carga_id}": datos_carga.get("ubicacion", ""),
            f"foliacion_{carga_id}": foliacion_inicial,
        }
        carga_anterior = st.session_state.get("_registro_carga_id")
        if carga_anterior != carga_id:
            for clave, valor in campos_formulario.items():
                if valor not in (None, ""):
                    st.session_state.setdefault(clave, valor)
            st.session_state["_registro_carga_id"] = carga_id

        st.subheader("2. Confirmar y completar el expediente")
        with st.form("form_registro_canvas"):
            f_col1, f_col2, f_col3 = st.columns(3)
            with f_col1:
                radicado_padre = st.text_input(
                    "Radicado Padre (Orfeo) *",
                    value=datos_carga.get("radicado_padre", ""),
                    placeholder="Se detectará desde el documento o puedes escribirlo",
                    key=f"radicado_padre_{carga_id}",
                ).strip()
                if not datos_carga.get("radicado_padre"):
                    st.warning("Radicado no detectado: escríbelo manualmente.")
                solicitante_opciones = ["Propietario", "Empresa", "Apoderado", "Entidad pública", "Otro"]
                solicitante_actual = datos_carga.get("solicitante", "Propietario")
                solicitante = st.selectbox(
                    "Solicitante",
                    solicitante_opciones,
                    index=(
                        solicitante_opciones.index(solicitante_actual)
                        if solicitante_actual in solicitante_opciones
                        else 0
                    ),
                    key=f"solicitante_{carga_id}",
                )
                fecha_solicitud = st.date_input(
                    "Fecha Solicitud",
                    value=fecha_carga,
                    key=f"fecha_solicitud_{carga_id}",
                )
                if not datos_carga.get("fecha_solicitud"):
                    st.warning("Fecha no detectada: verifica o completa la fecha.")
                tipo_inicial = next(iter(tipos_carga), "Detección automática")
                tipo_caso = st.selectbox(
                    "Tipo de caso",
                    options=TIPOS_CASO,
                    index=TIPOS_CASO.index(tipo_inicial),
                    key=f"tipo_caso_{carga_id}",
                )
                st.session_state.setdefault(f"foliacion_{carga_id}", foliacion_inicial)
                foliacion_registro = st.number_input(
                    "Foliación (hojas)",
                    min_value=0,
                    step=1,
                    key=f"foliacion_{carga_id}",
                    help=(
                        "Se propone el conteo del PDF, pero puedes corregirlo. "
                        "El valor guardado manualmente tiene prioridad."
                    ),
                )
            with f_col2:
                matricula_qx = st.text_input(
                    "Matrícula QX (Placa) *",
                    value=datos_carga.get("placa", ""),
                    placeholder="Se detectará desde el documento o puedes escribirla",
                    key=f"matricula_qx_{carga_id}",
                ).strip().upper()
                if not datos_carga.get("placa"):
                    st.warning("Placa no detectada: escríbela manualmente.")
                qx_verificado = st.checkbox(
                    "QX verificado (propiedad)",
                    key=f"qx_verificado_{carga_id}",
                )
                num_resolucion = st.text_input(
                    "N° Resolución Administrativa",
                    value=datos_carga.get("resolucion", ""),
                    key=f"resolucion_{carga_id}",
                ).strip()
                fecha_resolucion = st.date_input(
                    "Fecha Resolución",
                    value=fecha_para_formulario(datos_carga.get("fecha_resolucion")),
                    key=f"fecha_resolucion_{carga_id}",
                )
            with f_col3:
                tipos_notificacion = [
                    "",
                    "Personal",
                    "Citación",
                    "Aviso",
                    "Publicación",
                    "Electrónica",
                    "Correo",
                ]
                notificacion_actual = datos_carga.get("tipo_notificacion", "")
                tipo_notificacion = st.selectbox(
                    "Tipo de notificación",
                    tipos_notificacion,
                    index=(
                        tipos_notificacion.index(notificacion_actual)
                        if notificacion_actual in tipos_notificacion
                        else 0
                    ),
                    key=f"tipo_notificacion_{carga_id}",
                )
                fecha_notificacion = st.date_input(
                    "Fecha Notificación",
                    value=fecha_para_formulario(datos_carga.get("fecha_notificacion")),
                    key=f"fecha_notificacion_{carga_id}",
                )
                fecha_ejecutoria = st.date_input(
                    "Fecha Constancia de Ejecutoria",
                    value=fecha_para_formulario(datos_carga.get("fecha_ejecutoria")),
                    key=f"fecha_ejecutoria_{carga_id}",
                )
                remitido = st.checkbox(
                    "Remitido a Registro Automotor",
                    key=f"remitido_{carga_id}",
                )
                fecha_remision = st.date_input(
                    "Fecha remisión a registro",
                    value=fecha_para_formulario(datos_carga.get("fecha_remision_registro")),
                    key=f"fecha_remision_{carga_id}",
                )
                notas = st.text_area(
                    "Notas",
                    placeholder="Anotaciones adicionales del expediente",
                    value=datos_carga.get("notas", ""),
                    key=f"notas_{carga_id}",
                )

            st.markdown("#### Información administrativa completa")
            datos_col1, datos_col2, datos_col3 = st.columns(3)
            with datos_col1:
                empresa_registro = st.text_input(
                    "Empresa",
                    value=datos_carga.get("empresa", ""),
                    key=f"empresa_{carga_id}",
                )
                nit_registro = st.text_input(
                    "NIT",
                    value=datos_carga.get("nit", ""),
                    key=f"nit_{carga_id}",
                )
                propietario_registro = st.text_input(
                    "Propietario",
                    value=datos_carga.get("propietario", ""),
                    key=f"propietario_{carga_id}",
                )
                cedula_registro = st.text_input(
                    "Cédula",
                    value=datos_carga.get("cedula", ""),
                    key=f"cedula_{carga_id}",
                )
            with datos_col2:
                direccion_empresa_registro = st.text_input(
                    "Dirección empresa",
                    value=datos_carga.get("direccion_empresa", ""),
                    key=f"direccion_empresa_{carga_id}",
                )
                direccion_propietario_registro = st.text_input(
                    "Dirección propietario",
                    value=datos_carga.get("direccion_propietario", ""),
                    key=f"direccion_propietario_{carga_id}",
                )
                nueva_empresa_registro = st.text_input(
                    "Nueva empresa",
                    value=datos_carga.get("nueva_empresa", ""),
                    key=f"nueva_empresa_{carga_id}",
                )
                funcionario_registro = st.text_input(
                    "Funcionario que desvincula",
                    value=datos_carga.get("funcionario", ""),
                    key=f"funcionario_{carga_id}",
                )
            with datos_col3:
                fecha_radicacion_registro = st.text_input(
                    "Fecha de radicación",
                    value=datos_carga.get("fecha_radicacion", ""),
                    placeholder="AAAA-MM-DD",
                    key=f"fecha_radicacion_{carga_id}",
                )
                correo_registro = st.text_input(
                    "Correo electrónico",
                    value=datos_carga.get("correo", ""),
                    key=f"correo_{carga_id}",
                )
                recurso_registro = st.text_input(
                    "Recurso",
                    value=datos_carga.get("recurso", ""),
                    key=f"recurso_{carga_id}",
                )
                fecha_recurso_registro = st.date_input(
                    "Fecha recurso",
                    value=fecha_para_formulario(datos_carga.get("fecha_recurso")),
                    key=f"fecha_recurso_{carga_id}",
                )
                observacion_registro = st.text_area(
                    "Observación",
                    value=datos_carga.get("observacion", ""),
                    key=f"observacion_{carga_id}",
                )
                ubicacion_registro = st.text_input(
                    "Ubicación física *",
                    value=datos_carga.get("ubicacion", ""),
                    placeholder="Ejemplo: Caja-004-Folder-02-carpeta-#",
                    key=f"ubicacion_fisica_{carga_id}",
                    help=(
                        "Este dato lo confirma manualmente el registrador y se "
                        "usará al nombrar la carpeta definitiva de Drive."
                    ),
                ).strip()
            campos_revision = [
                etiqueta
                for etiqueta, campo in (
                    ("Empresa", "empresa"),
                    ("NIT", "nit"),
                    ("Propietario", "propietario"),
                    ("Cédula", "cedula"),
                    ("Fecha de radicación", "fecha_radicacion"),
                )
                if not datos_carga.get(campo)
            ]
            if campos_revision:
                st.warning(
                    "No se pudieron confirmar automáticamente: "
                    + ", ".join(campos_revision)
                    + ". Verifica otros documentos y completa estos campos manualmente."
                )

            btn_guardar = st.form_submit_button("Guardar y Sincronizar Datos", width="stretch")

        if btn_guardar:
            if not ubicacion_registro:
                st.error(
                    "Indica la Ubicación física manualmente antes de guardar. "
                    "Ejemplo: Caja-004-Folder-02-carpeta-#."
                )
                st.stop()
            if not radicado_padre and not archivos_canvas:
                st.error(
                    "Indica el radicado del expediente para poder asociar el registro."
                )
            else:
                if sheets_service and not datos_sheet:
                    registro_existente_sheet = buscar_registro_en_sheets(
                        sheets_service,
                        radicado_padre.strip(),
                        matricula_qx.strip(),
                        str(fecha_solicitud or ""),
                        datos_carga.get("empresa", ""),
                        datos_carga.get("nit", ""),
                        datos_carga.get("cedula", ""),
                    )
                    datos_sheet = datos_registro_sheet(registro_existente_sheet)
                if not radicado_padre.strip() and datos_sheet.get("radicado_padre"):
                    radicado_padre = datos_sheet["radicado_padre"]
                if not radicado_padre.strip() and matricula_qx.strip():
                    expediente_por_placa = next(
                        (
                            expediente
                            for expediente in st.session_state.db_expedientes.values()
                            if str(expediente.get("placa", "")).strip().upper()
                            == matricula_qx.strip().upper()
                        ),
                        None,
                    )
                    if expediente_por_placa:
                        radicado_padre = expediente_por_placa.get("radicado_padre", "")
                expediente_previo = st.session_state.db_expedientes.get(
                    radicado_padre.strip()
                )
                fecha_expediente = (
                    (expediente_previo or {}).get("fecha_solicitud")
                    or datos_sheet.get("fecha_solicitud", "")
                )
                placa_expediente = (
                    (expediente_previo or {}).get("placa")
                    or datos_sheet.get("placa", "")
                )
                existente = st.session_state.db_expedientes.get(radicado_padre)
                if existente:
                    total_expedientes = existente.get("id") or siguiente_numero_expediente()
                    caja, folder, cod_ub = calcular_ubicacion(total_expedientes)
                else:
                    total_expedientes = siguiente_numero_expediente()
                    caja, folder, cod_ub = calcular_ubicacion(total_expedientes)

                canvas_list = [
                    documento.copy()
                    for documento in (existente or {}).get("canvas_paginas", [])
                    if documento.get("tipo_documento") != "Expediente completo"
                ]
                documentos_detectados = []
                archivos_ordenados = archivos_canvas or []
                carpeta_expediente_drive_id = None
                fecha_registro_previa = fecha_solicitud or fecha_expediente
                staged_carga = st.session_state.get("_cargas_drive", {}).get(
                    carga_id,
                    {},
                )
                staged_folder_id = staged_carga.get("drive_folder_id")
                if drive_service:
                    if staged_folder_id and fecha_registro_previa:
                        carpeta_definitiva_id = carpeta_drive_para_expediente(
                            drive_service,
                            str(fecha_registro_previa),
                            radicado_padre,
                            matricula_qx or placa_expediente,
                            ubicacion_registro,
                        )
                        if (
                            carpeta_definitiva_id
                            and carpeta_definitiva_id != staged_folder_id
                        ):
                            fusionar_carpeta_drive(
                                drive_service,
                                staged_folder_id,
                                carpeta_definitiva_id,
                            )
                            staged_folder_id = carpeta_definitiva_id
                        else:
                            carpeta_peticiones_id = carpeta_drive_para_fecha(
                                drive_service,
                                str(fecha_registro_previa),
                            )
                            if carpeta_peticiones_id:
                                mover_carpeta_drive(
                                    drive_service,
                                    staged_folder_id,
                                    carpeta_peticiones_id,
                                )
                        carpeta_expediente_drive_id = staged_folder_id
                    elif staged_folder_id:
                        carpeta_expediente_drive_id = staged_folder_id
                    elif fecha_registro_previa:
                        carpeta_expediente_drive_id = carpeta_drive_para_expediente(
                            drive_service,
                            str(fecha_registro_previa),
                            radicado_padre,
                            matricula_qx or placa_expediente,
                            ubicacion_registro,
                        )
                    else:
                        carpeta_expediente_drive_id = carpeta_drive_para_staging(
                            drive_service,
                            radicado_padre,
                            matricula_qx or placa_expediente,
                            str(fecha_registro_previa or ""),
                        )
                    if carpeta_expediente_drive_id and (
                        matricula_qx or placa_expediente
                    ):
                        fusionar_complementos_sin_vincular(
                            drive_service,
                            matricula_qx or placa_expediente,
                            carpeta_expediente_drive_id,
                        )
                staged_documentos = [
                    documento.copy()
                    for documento in staged_carga.get("documentos", [])
                    if not documento.get("es_pdf_completo")
                ]
                staged_pdf_completos = [
                    documento
                    for documento in staged_carga.get("documentos", [])
                    if documento.get("es_pdf_completo")
                ]
                if drive_service and carpeta_expediente_drive_id:
                    for documento in staged_documentos:
                        carpeta_tipo = carpeta_drive_para_documento(
                            drive_service,
                            carpeta_expediente_drive_id,
                            documento.get("tipo_documento", "Otro"),
                        )
                        if carpeta_tipo and documento.get("drive_id"):
                            movido = mover_archivo_drive(
                                drive_service,
                                documento["drive_id"],
                                carpeta_tipo,
                            )
                            if movido:
                                documento["drive_folder_id"] = carpeta_tipo
                            else:
                                nombre_documento = documento.get("nombre", "")
                                if nombre_documento:
                                    nombre_escapado = nombre_documento.replace("'", "''")
                                    coincidencias = drive_service.files().list(
                                        q=(
                                            f"'{carpeta_tipo}' in parents and trashed = false "
                                            f"and name = '{nombre_escapado}'"
                                        ),
                                        fields="files(id,webViewLink)",
                                        pageSize=2,
                                    ).execute().get("files", [])
                                    if coincidencias:
                                        documento["drive_id"] = coincidencias[0].get("id")
                                        documento["drive_url"] = coincidencias[0].get("webViewLink")
                                        documento["drive_folder_id"] = carpeta_tipo
                    for documento in staged_pdf_completos:
                        mover_archivo_drive(
                            drive_service,
                            documento.get("drive_id"),
                            carpeta_expediente_drive_id,
                        )
                canvas_list.extend(staged_documentos)
                if archivos_canvas and orden_archivos:
                    indices = [
                        int(opcion.split(" - ", 1)[0]) - 1
                        for opcion in orden_archivos
                    ]
                    archivos_ordenados = [archivos_canvas[indice] for indice in indices]
                if archivos_ordenados:
                    archivos_preparados = []
                    barra_guardado = st.progress(
                        0,
                        text="Preparando documentos para guardar...",
                    )
                    estado_guardado = st.empty()
                    total_guardado = len(archivos_ordenados)
                    for indice_guardado, archivo in enumerate(
                        archivos_ordenados,
                        start=1,
                    ):
                        estado_guardado.info(
                            f"Preparando documento {indice_guardado} de "
                            f"{total_guardado}: **{archivo.name}**"
                        )
                        contenido_original = archivo.getvalue()
                        if archivo.name.lower().endswith(".pdf"):
                            partes = partes_analizadas_por_archivo.get(
                                huella_contenido(contenido_original)
                            )
                            if partes is None:
                                partes = separar_pdf_completo(
                                    contenido_original,
                                    tipo_documento,
                                )
                            if not partes:
                                st.warning(
                                    f"El archivo '{archivo.name}' no contiene páginas útiles "
                                    "después de limpiar las páginas blancas."
                                )
                        else:
                            contenido_imagen = convertir_imagen_a_pdf(
                                contenido_original,
                                archivo.name,
                            )
                            partes = [{
                                "contenido": contenido_imagen,
                                "tipo": tipo_documento,
                                "paginas": 1,
                            }]
                        for numero, parte in enumerate(partes, start=1):
                            archivos_preparados.append({
                                "nombre": (
                                    (
                                        f"{os.path.splitext(archivo.name)[0]}.pdf"
                                        if not archivo.name.lower().endswith(".pdf")
                                        else archivo.name
                                    )
                                    if len(partes) == 1
                                    else f"{os.path.splitext(archivo.name)[0]}_{numero}.pdf"
                                ),
                                "nombre_original": archivo.name,
                                "texto_analizado": (
                                    parte.get("texto")
                                    or textos_analizados.get(
                                        huella_contenido(contenido_original),
                                        "",
                                    )
                                ),
                                "paginas_por_seccion": parte.get(
                                    "paginas_por_seccion",
                                    [],
                                ),
                                **parte,
                            })
                        barra_guardado.progress(
                            indice_guardado / max(total_guardado, 1),
                            text=(
                                f"Documentos preparados: {indice_guardado} "
                                f"de {total_guardado}"
                            ),
                        )
                    for idx, archivo_preparado in enumerate(archivos_preparados):
                        estado_guardado.info(
                            f"Guardando documento {idx + 1} de "
                            f"{len(archivos_preparados)}: "
                            f"**{archivo_preparado['nombre_original']}**"
                        )
                        barra_guardado.progress(
                            min(
                                (total_guardado + idx + 1)
                                / max(total_guardado + len(archivos_preparados), 1),
                                1.0,
                            ),
                            text=(
                                f"Guardando documento {idx + 1} de "
                                f"{len(archivos_preparados)}"
                            ),
                        )
                        contenido_archivo = archivo_preparado["contenido"]
                        nombre_original = archivo_preparado["nombre"]
                        nombre_fuente = archivo_preparado.get(
                            "nombre_original",
                            nombre_original,
                        )
                        texto_pdf = archivo_preparado.get("texto_analizado")
                        if texto_pdf is None and nombre_original.lower().endswith(".pdf"):
                            texto_pdf = extraer_texto_pdf(contenido_archivo)
                        texto_pdf = texto_pdf or ""
                        datos_pdf = extraer_datos_pdf(
                            contenido_archivo,
                            texto=texto_pdf,
                        )
                        tipo_detectado = clasificar_tipo_caso(texto_pdf, nombre_original)
                        tipo_documento_final = clasificar_tipo_documento(
                            texto_pdf,
                            archivo_preparado["tipo"],
                        )
                        nombre_drive = nombre_documento_expediente(
                            datos_pdf.get("radicado_padre") or radicado_padre,
                            datos_pdf.get("placa") or matricula_qx,
                            str(fecha_registro_previa or "PENDIENTE"),
                            tipo_documento_final,
                            os.path.splitext(nombre_original)[1] or ".pdf",
                            tipo_detectado,
                        )
                        if datos_pdf:
                            documentos_detectados.append(
                                f"{nombre_fuente}: " + ", ".join(
                                    f"{campo}={valor}" for campo, valor in datos_pdf.items()
                                )
                            )
                        ruta_local = guardar_documento_local(
                            contenido_archivo,
                            nombre_drive,
                        )
                        file_id, drive_url = None, None
                        huella = huella_contenido(contenido_archivo)
                        staged_existente = next(
                            (
                                documento for documento in canvas_list
                                if documento.get("staged")
                                and documento.get("huella") == huella
                            ),
                            None,
                        )
                        if staged_existente:
                            st.info(
                                f"Se reutilizó desde Drive la parte ya cargada: "
                                f"{nombre_original}"
                            )
                            continue
                        duplicado_local = next(
                            (
                                documento for documento in (
                                    (existente or {}).get("canvas_paginas", [])
                                )
                                if documento.get("huella") == huella
                                or (
                                    documento.get("nombre") == nombre_drive
                                    and documento.get("tipo_documento") == archivo_preparado["tipo"]
                                )
                            ),
                            None,
                        )
                        if duplicado_local:
                            st.info(f"Se omitió el duplicado: {nombre_original}")
                            continue
                        carpeta_documento_id = carpeta_expediente_drive_id
                        if drive_service and carpeta_documento_id:
                            carpeta_documento_id = carpeta_drive_para_documento(
                                drive_service,
                                carpeta_expediente_drive_id,
                                tipo_documento_final,
                            )
                            if carpeta_documento_id:
                                duplicado_drive = buscar_archivo_drive(
                                    drive_service,
                                    carpeta_documento_id,
                                    nombre_drive,
                                    contenido_archivo,
                                )
                                if duplicado_drive:
                                    file_id = duplicado_drive.get("id")
                                    drive_url = duplicado_drive.get("webViewLink")
                                else:
                                    file_id, drive_url = subir_archivo_a_drive(
                                        drive_service,
                                        io.BytesIO(contenido_archivo),
                                        nombre_drive,
                                        carpeta_documento_id,
                                    )
                        canvas_list.append({
                            "pagina_id": len(canvas_list) + 1,
                            "nombre": nombre_drive,
                            "nombre_original": nombre_fuente,
                            "tamano": f"{round(len(contenido_archivo) / 1024, 1)} KB",
                            "drive_id": file_id,
                            "drive_url": drive_url,
                            "drive_folder_id": carpeta_documento_id,
                            "metadatos_pdf": datos_pdf,
                            "tipo_documento": tipo_documento_final,
                            "tipo_caso_detectado": tipo_detectado,
                            "paginas_por_seccion": archivo_preparado.get(
                                "paginas_por_seccion",
                                [],
                            ),
                            "estado_carga": (
                                "Expediente completo"
                                if tipo_documento_final == "Expediente completo"
                                else "Complemento"
                            ),
                            "huella": huella,
                            "ruta_local": ruta_local,
                            "pendiente": not bool(fecha_registro_previa),
                        })

                    documentos_para_unificar = [
                        archivo
                        for archivo in archivos_preparados
                        if archivo["nombre"].lower().endswith(".pdf")
                    ]
                    if existente and drive_service:
                        huellas_unificado = {
                            huella_contenido(documento["contenido"])
                            for documento in documentos_para_unificar
                        }
                        documentos_existentes = ordenar_documentos_por_precedencia(
                            existente.get("canvas_paginas", [])
                        )
                        for documento_existente in documentos_existentes:
                            if (
                                documento_existente.get("tipo_documento")
                                == "Expediente completo"
                                or not documento_existente.get("drive_id")
                            ):
                                continue
                            try:
                                contenido_existente = descargar_archivo_drive(
                                    drive_service,
                                    documento_existente["drive_id"],
                                )
                            except Exception as error:
                                st.warning(
                                    "No se pudo recuperar un documento anterior para "
                                    f"reconstruir el PDF completo: {error}"
                                )
                                continue
                            huella_existente = huella_contenido(contenido_existente)
                            if huella_existente not in huellas_unificado:
                                documento_existente = documento_existente.copy()
                                documento_existente["contenido"] = contenido_existente
                                documentos_para_unificar.append(documento_existente)
                                huellas_unificado.add(huella_existente)
                    archivos_para_unificar = ordenar_documentos_por_precedencia(
                        documentos_para_unificar
                    )
                    pdfs_cargados = [
                        documento["contenido"]
                        for documento in archivos_para_unificar
                    ]
                    if pdfs_cargados:
                        pdf_unificado = unir_archivos_pdf(pdfs_cargados)
                        if pdf_unificado:
                            nombre_unificado = nombre_pdf_expediente(
                                radicado_padre,
                                matricula_qx,
                                str(fecha_registro_previa),
                            )
                            id_unificado, url_unificado = (None, None)
                            huella_unificado = huella_contenido(pdf_unificado)
                            anterior_unificado = next(
                                (
                                    documento for documento in (
                                        (existente or {}).get("canvas_paginas", [])
                                    )
                                    if documento.get("tipo_documento") == "Expediente completo"
                                ),
                                None,
                            )
                            if drive_service:
                                carpeta_unificado_id = carpeta_expediente_drive_id or carpeta_drive_para_fecha(
                                    drive_service,
                                    str(fecha_registro_previa),
                                )
                                copia_unificada = buscar_archivo_drive(
                                    drive_service,
                                    carpeta_unificado_id,
                                    nombre_unificado,
                                    pdf_unificado,
                                )
                                if copia_unificada:
                                    id_unificado = copia_unificada.get("id")
                                    url_unificado = copia_unificada.get("webViewLink")
                                else:
                                    id_unificado, url_unificado = subir_archivo_a_drive(
                                        drive_service,
                                        io.BytesIO(pdf_unificado),
                                        nombre_unificado,
                                        carpeta_unificado_id,
                                    )
                                    if anterior_unificado and anterior_unificado.get("drive_id"):
                                        eliminar_archivo_drive(
                                            drive_service,
                                            anterior_unificado["drive_id"],
                                        )
                                for documento_temporal in staged_pdf_completos:
                                    temporal_id = documento_temporal.get("drive_id")
                                    if temporal_id and temporal_id != id_unificado:
                                        eliminar_archivo_drive(
                                            drive_service,
                                            temporal_id,
                                        )
                            canvas_list = [
                                documento for documento in canvas_list
                                if documento.get("tipo_documento") != "Expediente completo"
                            ]
                            canvas_list.append({
                                "pagina_id": len(canvas_list) + 1,
                                "nombre": nombre_unificado,
                                "nombre_original": "PDF unificado",
                                "tamano": f"{round(len(pdf_unificado) / 1024, 1)} KB",
                                "drive_id": id_unificado,
                                "drive_url": url_unificado,
                                "metadatos_pdf": {},
                                "tipo_documento": "Expediente completo",
                                "tipo_caso_detectado": tipo_caso_final,
                                "estado_carga": "Expediente completo",
                                "paginas_por_seccion": list(
                                    range(1, len(PdfReader(io.BytesIO(pdf_unificado)).pages) + 1)
                                ) if PdfReader is not None else [],
                                "orden_fuentes": [
                                    archivo.name for archivo in archivos_ordenados
                                ],
                                "huella": huella_unificado,
                                "ruta_local": guardar_documento_local(
                                    pdf_unificado,
                                    nombre_unificado,
                                ),
                            })
                            st.info(
                                "Se creó un PDF unificado respetando el orden seleccionado. "
                                "Los archivos fuente quedan registrados en el expediente."
                            )
                    barra_guardado.progress(
                        1.0,
                        text="Documentos preparados y guardados correctamente.",
                    )
                    estado_guardado.success(
                        "Todos los documentos terminaron de procesarse."
                    )

                datos_detectados = {}
                tipos_detectados = {
                    documento.get("tipo_caso_detectado")
                    for documento in canvas_list
                    if documento.get("tipo_caso_detectado")
                }
                if len(tipos_detectados) > 1:
                    st.error(
                        "Los archivos cargados corresponden a desenlaces diferentes. "
                        "Cárgalos en expedientes separados."
                    )
                    st.stop()
                tipo_caso_final = (
                    next(iter(tipos_detectados))
                    if tipos_detectados
                    else tipo_caso
                )
                if tipo_caso_final == "Detección automática":
                    st.error(
                        "No fue posible identificar el desenlace. Selecciona "
                        "Con recurso, Sin recurso o Desistimiento."
                    )
                    st.stop()
                documentos_esperados = documentos_requeridos_por_caso(
                    tipo_caso_final,
                    documentos_esperados,
                )
                for documento in canvas_list:
                    for campo, valor in documento.get("metadatos_pdf", {}).items():
                        datos_detectados.setdefault(campo, valor)
                # El formulario confirmado por el registrador tiene prioridad
                # sobre cualquier candidato OCR dudoso.
                radicado_registro = radicado_padre.strip() or datos_detectados.get(
                    "radicado_padre",
                    "",
                )
                placa_registro = matricula_qx.strip() or datos_detectados.get("placa", "")
                # La fecha de la petición es la única fuente para el año documental.
                placa_registro = placa_registro or placa_expediente
                fecha_registro = str(
                    fecha_solicitud
                    or datos_detectados.get("fecha_solicitud")
                    or fecha_expediente
                )
                if not radicado_registro:
                    st.error(
                        "No fue posible asociar el archivo a un expediente. "
                        "Indica el radicado padre."
                    )
                    st.stop()
                if not placa_registro:
                    st.error(
                        "Este expediente aún no tiene placa. Completa la placa "
                        "para crear el expediente inicial; los anexos posteriores "
                        "sí pueden reutilizar la placa ya registrada."
                    )
                    st.stop()
                if archivos_canvas and not peticion_incluida:
                    if not radicado_padre.strip() or not fecha_registro.strip():
                        st.error(
                            "Este archivo no contiene la petición principal. "
                            "Debes indicar el radicado. La fecha de la petición "
                            "se reutiliza desde el expediente existente."
                        )
                        st.stop()
                existente_final = st.session_state.db_expedientes.get(radicado_registro)
                fuente_existente = dict(existente_final or {})
                combinar_datos_por_coincidencia(fuente_existente, datos_detectados)
                combinar_datos_por_coincidencia(fuente_existente, datos_carga)
                combinar_datos_por_coincidencia(fuente_existente, datos_sheet)

                def valor_actual(campo, valor_nuevo=""):
                    return valor_nuevo or fuente_existente.get(campo, "")

                registro_datos = {
                    **fuente_existente,
                    "id": total_expedientes,
                    "radicado_padre": radicado_registro,
                    "placa": placa_registro,
                    "ubicacion": ubicacion_registro,
                    "empresa": valor_actual("empresa", empresa_registro.strip()),
                    "nit": valor_actual("nit", nit_registro.strip()),
                    "direccion_empresa": valor_actual(
                        "direccion_empresa",
                        direccion_empresa_registro.strip(),
                    ),
                    "direccion_propietario": valor_actual(
                        "direccion_propietario",
                        direccion_propietario_registro.strip(),
                    ),
                    "propietario": valor_actual("propietario", propietario_registro.strip()),
                    "cedula": valor_actual("cedula", cedula_registro.strip()),
                    "observacion": valor_actual(
                        "observacion",
                        observacion_registro.strip(),
                    ),
                    "funcionario": valor_actual(
                        "funcionario",
                        funcionario_registro.strip(),
                    ),
                    "nueva_empresa": valor_actual(
                        "nueva_empresa",
                        nueva_empresa_registro.strip(),
                    ),
                    "correo": valor_actual("correo", correo_registro.strip()),
                    "recurso": valor_actual("recurso", recurso_registro.strip()),
                    "fecha_recurso": valor_actual(
                        "fecha_recurso",
                        str(fecha_recurso_registro).strip()
                        if "fecha_recurso_registro" in locals()
                        else "",
                    ),
                    "solicitante": valor_actual("solicitante", solicitante),
                    "tipo_caso": tipo_caso_final,
                    "fecha_solicitud": fecha_registro,
                    "fecha_minima": fecha_registro,
                    "peticion_incluida": peticion_incluida,
                    "peticion_pendiente": not peticion_incluida,
                    "fecha_radicacion": valor_actual(
                        "fecha_radicacion",
                        fecha_radicacion_registro.strip(),
                    ),
                    "foliacion": int(foliacion_registro),
                    "qx_verificado": qx_verificado or fuente_existente.get("qx_verificado", False),
                    "resolucion": valor_actual("resolucion", num_resolucion),
                    "fecha_resolucion": valor_actual(
                        "fecha_resolucion",
                        str(fecha_resolucion) if fecha_resolucion else "",
                    ),
                    "tipo_notificacion": valor_actual("tipo_notificacion", tipo_notificacion),
                    "fecha_notificacion": valor_actual(
                        "fecha_notificacion",
                        str(fecha_notificacion) if fecha_notificacion else "",
                    ),
                    "fecha_ejecutoria": valor_actual(
                        "fecha_ejecutoria",
                        str(fecha_ejecutoria) if fecha_ejecutoria else "",
                    ),
                    "remitido": remitido or fuente_existente.get("remitido", False),
                    "fecha_remision_registro": valor_actual(
                        "fecha_remision_registro",
                        str(fecha_remision) if fecha_remision else "",
                    ),
                    "ubicacion": ubicacion_registro,
                    "caja": valor_actual("caja", caja),
                    "folder": valor_actual("folder", folder),
                    "carpeta": valor_actual("carpeta", total_expedientes),
                    "estado": valor_actual("estado"),
                    "canvas_paginas": canvas_list,
                    "documentos_esperados": documentos_esperados,
                    "drive_folder": valor_actual(
                        "drive_folder",
                        (
                            f"https://drive.google.com/drive/folders/{carpeta_expediente_drive_id}"
                            if "carpeta_expediente_drive_id" in locals()
                            and carpeta_expediente_drive_id
                            else f"https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}"
                        ),
                    ),
                    "modificado_por": datos_usuario["alias"],
                    "subido_por": datos_usuario.get("alias", correo_activo),
                    "correo_subida": correo_activo,
                    "cargo_subida": rol_actual,
                    "notas": valor_actual("notas", notas.strip()),
                    "nombre_ubicacion": nombre_carpeta_expediente(
                        radicado_registro,
                        placa_registro,
                        fecha_registro,
                        ubicacion_registro,
                    ),
                    "ultima_modificacion": str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                }
                pendientes_clave = radicado_registro.strip().upper()
                pendientes_asociados = list(
                    st.session_state.get("pendientes", {}).get(pendientes_clave, [])
                )
                if fecha_registro and pendientes_asociados:
                    for pendiente in pendientes_asociados:
                        if drive_service and carpeta_expediente_drive_id:
                            carpeta_pendiente_destino = carpeta_drive_para_documento(
                                drive_service,
                                carpeta_expediente_drive_id,
                                pendiente.get("tipo_documento", "Otro"),
                            )
                            mover_archivo_drive(
                                drive_service,
                                pendiente.get("drive_id"),
                                carpeta_pendiente_destino or carpeta_expediente_drive_id,
                            )
                        pendiente["pendiente"] = False
                        pendiente["reubicado_en"] = registro_datos.get("drive_folder", "")
                        canvas_list.append(pendiente)
                    st.session_state.pendientes.pop(pendientes_clave, None)
                elif canvas_list and not fecha_registro:
                    st.session_state.pendientes.setdefault(pendientes_clave, []).extend(
                        canvas_list
                    )
                    st.warning(
                        "El documento quedó en la carpeta temporal de Peticion. "
                        "Cuando registres la petición con este radicado, "
                        "se podrá reubicar y unir al expediente."
                    )
                if existente_final:
                    paginas_previas = existente_final.get("canvas_paginas", [])
                    paginas_previas = [
                        documento for documento in paginas_previas
                        if documento.get("tipo_documento") != "Expediente completo"
                    ]
                    documentos_unicos = []
                    claves_documentos = set()
                    for documento in paginas_previas + canvas_list:
                        clave = (
                            documento.get("huella")
                            or documento.get("drive_id")
                            or (
                                documento.get("nombre"),
                                documento.get("tipo_documento"),
                            )
                        )
                        if clave in claves_documentos:
                            continue
                        claves_documentos.add(clave)
                        documentos_unicos.append(documento)
                    registro_datos["canvas_paginas"] = documentos_unicos
                    registro_datos["documentos_esperados"] = sorted(
                        set(existente_final.get("documentos_esperados", []))
                        | set(documentos_esperados)
                    )
                    registro_datos["id"] = existente_final.get("id", total_expedientes)
                    registro_datos["tipo_caso"] = existente_final.get("tipo_caso", tipo_caso)
                for pagina_id, documento in enumerate(
                    registro_datos["canvas_paginas"], start=1
                ):
                    documento["pagina_id"] = pagina_id
                registro_datos["estado"] = calcular_estado_tramite(registro_datos)

                st.session_state.db_expedientes[radicado_registro] = registro_datos
                guardar_local_json(st.session_state.db_expedientes)

                if "barra_guardado" in locals():
                    barra_guardado.progress(
                        0.97,
                        text="Registro local y expediente documental guardados. Sincronizando Sheets...",
                    )
                sheets_ok = False
                if sheets_service:
                    sheets_ok = guardar_registro_en_sheets(sheets_service, registro_datos)

                if "barra_guardado" in locals():
                    barra_guardado.progress(
                        1.0,
                        text="Proceso terminado: Local, Drive y Sheets actualizados.",
                    )
                if sheets_ok:
                    st.success(
                        "Proceso guardado en Local, Drive y Google Sheets. "
                        f"Ubicación: **{ubicacion_registro}**"
                    )
                else:
                    st.warning("Guardado en archivo local y Drive. Falló la conexión con Google Sheets.")
                if documentos_detectados:
                    st.info("Datos identificados en los PDF: " + " | ".join(documentos_detectados))
                faltantes = documentos_faltantes(registro_datos)
                if faltantes:
                    st.warning("Documentos aún faltantes: " + ", ".join(faltantes))
                else:
                    st.success("El expediente ya tiene todos los documentos esperados.")
                st.session_state.form_registro_version += 1

elif st.session_state.navegacion == "Consulta & Archivo":
    if st.button("⬅️ Volver al Inicio"):
        st.session_state.navegacion = "Inicio"
        st.rerun()

    st.header("Consulta General de Expedientes")
    pendientes = st.session_state.get("pendientes", {})
    total_pendientes = sum(len(documentos) for documentos in pendientes.values())
    with st.container(border=True):
        st.subheader("Bandeja de PDF por asociar")
        st.metric("PDF sin expediente completo", total_pendientes)
        st.caption(
            "Estos archivos conservan su radicado o placa y esperan la petición "
            "principal para ser reubicados y unidos al expediente."
        )
        if pendientes:
            for clave, documentos in sorted(pendientes.items()):
                with st.expander(f"{clave} ({len(documentos)} archivo(s))"):
                    for documento in documentos:
                        nombre = documento.get("nombre", "Documento pendiente")
                        enlace = documento.get("drive_url", "")
                        if enlace:
                            st.markdown(f"- [{nombre}]({enlace})")
                        else:
                            st.write(f"- {nombre}")
        else:
            st.success("No hay PDF por asociar.")

    tipo_busqueda = st.selectbox(
        "Buscar por",
        [
            ("Radicado Padre", "radicado_padre"),
            ("Placa", "placa"),
            ("Empresa", "empresa"),
            ("NIT", "nit"),
            ("Cédula", "cedula"),
            ("Ubicación física", "ubicacion"),
            ("Fecha de solicitud", "fecha_solicitud"),
        ],
        format_func=lambda opcion: opcion[0],
    )
    coincidencias = []
    etiqueta_busqueda, campo_busqueda = tipo_busqueda
    criterio = st.text_input(
        f"{etiqueta_busqueda}:",
        placeholder=(
            "Ej: 202501730100462182"
            if campo_busqueda == "radicado_padre"
            else "Ej: ABC123"
            if campo_busqueda == "placa"
            else "Escribe el valor que deseas localizar"
        ),
        key="consulta_criterio",
    ).strip().upper()
    if campo_busqueda != "fecha_solicitud":
        coincidencias = buscar_expedientes_local_consulta(
            st.session_state.db_expedientes,
            campo_busqueda,
            criterio,
        )
    else:
        hoy = datetime.date.today()
        anios = sorted({
            int(str(exp.get("fecha_solicitud", ""))[:4])
            for exp in st.session_state.db_expedientes.values()
            if str(exp.get("fecha_solicitud", ""))[:4].isdigit()
        }, reverse=True)
        if not anios:
            anios = [hoy.year]
        f1, f2, f3 = st.columns(3)
        with f1:
            anio = st.selectbox("Año", anios)
        with f2:
            mes = st.selectbox("Mes", ["Todos"] + list(range(1, 13)))
        with f3:
            dia = st.selectbox("Día", ["Todos"] + list(range(1, 32)))
        criterio_fecha = (
            f"{anio:04d}"
            + (f"-{mes:02d}" if mes != "Todos" else "")
            + (f"-{dia:02d}" if dia != "Todos" else "")
        )
        coincidencias = buscar_expedientes_local_consulta(
            st.session_state.db_expedientes,
            "fecha_solicitud",
            criterio_fecha,
        )

    criterio_remoto = (
        criterio if campo_busqueda != "fecha_solicitud" else criterio_fecha
    )
    if criterio_remoto and sheets_service:
        try:
            remotos = buscar_expedientes_sheet_consulta(
                sheets_service,
                campo_busqueda,
                criterio_remoto,
            )
            conocidos = {
                clave_expediente_consulta(expediente)
                for expediente in coincidencias
            }
            for remoto in remotos:
                remoto_normalizado = normalizar_expediente_consulta(remoto)
                clave = clave_expediente_consulta(remoto_normalizado)
                if clave not in conocidos:
                    coincidencias.append(remoto_normalizado)
                    conocidos.add(clave)
        except (OSError, ValueError, TypeError) as error:
            st.warning(f"No fue posible consultar Google Sheets: {error}")

    coincidencias = [
        normalizar_expediente_consulta(expediente)
        for expediente in coincidencias
    ]
    if len(coincidencias) == 1:
        exp = coincidencias[0]
        st.subheader(f"Expediente Radicado: {exp['radicado_padre']} - Placa: {exp['placa']}")
        if exp.get("tipo_caso"):
            st.caption(f"Tipo de caso: {exp['tipo_caso']}")
        faltantes = documentos_faltantes(exp)
        tipo_consulta = exp.get("tipo_caso", "Detección automática")
        if tipo_consulta in DOCUMENTOS_BASE_POR_CASO:
            renderizar_checklist_documental(
                tipo_consulta,
                [
                    documento.get("tipo_documento")
                    for documento in exp.get("canvas_paginas", [])
                    if documento.get("tipo_documento") != "Expediente completo"
                ],
            )
        elif faltantes:
            st.warning("Documentos faltantes: " + ", ".join(faltantes))

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Ubicación Física", exp["ubicacion"])
        m2.metric("Estado Trámite", exp["estado"])
        m3.metric("Modificado Por", exp["modificado_por"])
        m4.metric("Última Edición", exp["ultima_modificacion"])
        st.divider()

        if any(
            exp.get(campo)
            for campo in (
                "drive_folder",
                "documentos_drive",
                "pdf_unificado",
                "contenido_documental",
            )
        ):
            st.subheader("Índice Google Sheets - Google Drive")
            if exp.get("drive_folder") and puede_descargar:
                st.markdown(f"[Abrir carpeta del expediente en Drive]({exp['drive_folder']})")
            if exp.get("documentos_drive"):
                st.caption("Archivos registrados: " + exp["documentos_drive"])
            if exp.get("contenido_documental"):
                st.caption("Contenido documental: " + exp["contenido_documental"])
            if exp.get("pdf_unificado") and puede_descargar:
                st.markdown(f"[Abrir PDF unificado]({exp['pdf_unificado']})")
            if (
                not puede_descargar
                and (exp.get("drive_folder") or exp.get("pdf_unificado"))
            ):
                st.caption(
                    "El acceso directo de Drive y la descarga están reservados "
                    "para usuarios autorizados."
                )
            if exp.get("documentos_faltantes_drive"):
                st.warning(
                    "Faltantes registrados en Sheets: "
                    + exp["documentos_faltantes_drive"]
                )
            st.divider()

        st.subheader("Documentos Digitalizados")
        paginas = exp.get("canvas_paginas", [])
        if not paginas:
            st.info("Este expediente no posee archivos adjuntos registrados localmente.")
        else:
            documentos_completos = [
                documento
                for documento in paginas
                if documento.get("tipo_documento") == "Expediente completo"
            ]
            opciones_visualizacion = []
            if documentos_completos:
                opciones_visualizacion.append("PDF completo unificado")
            opciones_visualizacion.append("Explorador de complementos")
            modo_visualizacion = st.radio(
                "Modo de visualización",
                opciones_visualizacion,
                horizontal=True,
                key=f"modo_visualizacion_{exp['radicado_padre']}",
            )
            if modo_visualizacion == "PDF completo unificado":
                paginas_visibles = documentos_completos[:1]
            else:
                complementos = [
                    documento
                    for documento in paginas
                    if documento.get("tipo_documento") != "Expediente completo"
                ]
                if not complementos:
                    st.info("No hay complementos individuales disponibles.")
                    paginas_visibles = []
                else:
                    nombres_complementos = [
                        documento.get("nombre", "Complemento")
                        for documento in complementos
                    ]
                    complemento_seleccionado = st.selectbox(
                        "Complemento",
                        nombres_complementos,
                        key=f"complemento_visualizacion_{exp['radicado_padre']}",
                    )
                    paginas_visibles = [
                        documento
                        for documento in complementos
                        if documento.get("nombre") == complemento_seleccionado
                    ]
            for p in paginas_visibles:
                cp1, cp2, cp3 = st.columns([3, 1.5, 1.5])
                cp1.write(f"Página {p['pagina_id']}: {p['nombre']} ({p['tamano']})")
                if (p.get("drive_id") and drive_service) or p.get("ruta_local"):
                    if cp2.button("Ver documento", key=f"view_drive_{exp['radicado_padre']}_{p['pagina_id']}"):
                        try:
                            contenido = (
                                descargar_archivo_drive(drive_service, p["drive_id"])
                                if p.get("drive_id") and drive_service
                                else leer_documento_local(p)
                            )
                            if not contenido:
                                raise FileNotFoundError("La copia local del documento no existe.")
                            with st.expander(f"Vista previa: {p['nombre']}", expanded=True):
                                mostrar_documento_en_aplicacion(
                                    contenido,
                                    p["nombre"],
                                    solo_lectura=not es_modificador,
                                )
                        except Exception as error:
                            st.error(f"No fue posible mostrar el documento: {error}")
                    if puede_descargar:
                        try:
                            contenido_descarga = (
                                descargar_archivo_drive(drive_service, p["drive_id"])
                                if p.get("drive_id") and drive_service
                                else leer_documento_local(p)
                            )
                            if not contenido_descarga:
                                raise FileNotFoundError("La copia local del documento no existe.")
                            cp3.download_button(
                                "Descargar",
                                data=contenido_descarga,
                                file_name=p["nombre"],
                                mime="application/pdf",
                                key=f"download_drive_{exp['radicado_padre']}_{p['pagina_id']}",
                            )
                        except Exception as error:
                            cp3.error(f"No disponible: {error}")
                    elif rol_actual == "Visualizador":
                        cp3.download_button(
                            "Descargar",
                            data=b"",
                            file_name=p["nombre"],
                            mime="application/pdf",
                            disabled=True,
                            key=f"download_disabled_{exp['radicado_padre']}_{p['pagina_id']}",
                        )
                        if not datos_usuario.get("permiso_descarga"):
                            etiqueta = (
                                "Solicitud enviada"
                                if solicitud_descarga_pendiente(datos_usuario)
                                else "Solicitar permiso"
                            )
                            if cp3.button(
                                etiqueta,
                                disabled=solicitud_descarga_pendiente(datos_usuario),
                                key=f"request_download_{exp['radicado_padre']}_{p['pagina_id']}",
                            ):
                                datos_usuario["solicitud_descarga"] = True
                                st.session_state.usuarios[correo_activo] = datos_usuario
                                guardar_local_json(st.session_state.db_expedientes)
                                st.success("Solicitud enviada al Super Administrador.")
                                st.rerun()
                else:
                    cp2.caption("Sin vista previa disponible")

                if puede_eliminar and st.button(
                    "Eliminar",
                    key=f"del_{exp['radicado_padre']}_{p['pagina_id']}",
                ):
                    exp["canvas_paginas"].remove(p)
                    guardar_local_json(st.session_state.db_expedientes)
                    st.success(f"Página {p['pagina_id']} eliminada.")
                    st.rerun()
    elif len(coincidencias) > 1:
        st.info(f"Se encontraron {len(coincidencias)} expedientes.")
        st.dataframe(
            pd.DataFrame(coincidencias)[
                ["radicado_padre", "placa", "ubicacion", "estado", "modificado_por"]
            ],
            width="stretch",
        )
        for exp in coincidencias:
            with st.expander(
                f"{exp.get('radicado_padre', '')} - Placa {exp.get('placa', '')}"
            ):
                faltantes = documentos_faltantes(exp)
                if faltantes:
                    st.warning("Faltantes: " + ", ".join(faltantes))
                paginas = exp.get("canvas_paginas", [])
                if not paginas:
                    st.caption("Este proceso no tiene documentos registrados.")
                    continue
                for p in paginas:
                    col_info, col_view, col_download = st.columns([3, 1, 1])
                    col_info.write(f"{p.get('nombre', 'Documento')} ({p.get('tamano', '')})")
                    if (p.get("drive_id") and drive_service) or p.get("ruta_local"):
                        if col_view.button(
                            "Ver",
                            key=f"view_multi_{exp.get('radicado_padre')}_{p.get('pagina_id')}",
                        ):
                            try:
                                contenido = (
                                    descargar_archivo_drive(drive_service, p["drive_id"])
                                    if p.get("drive_id") and drive_service
                                    else leer_documento_local(p)
                                )
                                if not contenido:
                                    raise FileNotFoundError("La copia local del documento no existe.")
                                with st.expander(
                                    f"Vista previa: {p.get('nombre', 'Documento')}",
                                    expanded=True,
                                ):
                                    mostrar_documento_en_aplicacion(
                                        contenido,
                                        p.get("nombre", "documento.pdf"),
                                        solo_lectura=not es_modificador,
                                    )
                            except Exception as error:
                                st.error(f"No fue posible mostrar el documento: {error}")
                        if puede_descargar:
                            try:
                                contenido = (
                                    descargar_archivo_drive(drive_service, p["drive_id"])
                                    if p.get("drive_id") and drive_service
                                    else leer_documento_local(p)
                                )
                                if not contenido:
                                    raise FileNotFoundError("La copia local del documento no existe.")
                                col_download.download_button(
                                    "Descargar",
                                    data=contenido,
                                    file_name=p.get("nombre", "documento.pdf"),
                                    mime="application/pdf",
                                    key=f"download_multi_{exp.get('radicado_padre')}_{p.get('pagina_id')}",
                                )
                            except Exception as error:
                                col_download.caption(f"No disponible: {error}")
                        elif rol_actual == "Visualizador":
                            col_download.download_button(
                                "Descargar",
                                data=b"",
                                file_name=p.get("nombre", "documento.pdf"),
                                mime="application/pdf",
                                disabled=True,
                                key=f"download_disabled_multi_{exp.get('radicado_padre')}_{p.get('pagina_id')}",
                            )
                            if not datos_usuario.get("permiso_descarga"):
                                etiqueta = (
                                    "Solicitud enviada"
                                    if solicitud_descarga_pendiente(datos_usuario)
                                    else "Solicitar permiso"
                                )
                                if col_download.button(
                                    etiqueta,
                                    disabled=solicitud_descarga_pendiente(datos_usuario),
                                    key=f"request_download_multi_{exp.get('radicado_padre')}_{p.get('pagina_id')}",
                                ):
                                    datos_usuario["solicitud_descarga"] = True
                                    st.session_state.usuarios[correo_activo] = datos_usuario
                                    guardar_local_json(st.session_state.db_expedientes)
                                    st.success("Solicitud enviada al Super Administrador.")
                                    st.rerun()
    elif criterio:
        st.warning("No se encontró ningún expediente por ese radicado o placa.")

elif st.session_state.navegacion == "Buzón de Mensajes":
    if st.button("⬅️ Volver al Inicio"):
        st.session_state.navegacion = "Inicio"
        st.rerun()

    st.header("Buzón de Mensajes")
    novedades = obtener_novedad_version()
    st.subheader(f"Novedades de la versión {novedades.get('version', 'actual')}")
    st.info(novedades.get("changelog", "No hay notas de versión disponibles."))
    st.caption("Las actualizaciones se publican mediante el instalador oficial de GitHub.")

    st.subheader("Soporte")
    st.caption(
        "Envía una consulta al Super Administrador. Las notificaciones quedan "
        "registradas en el buzón local del sistema."
    )
    with st.form("form_mensaje_soporte"):
        asunto_soporte = st.text_input("Asunto", placeholder="Ej: Documento sin petición")
        mensaje_soporte = st.text_area(
            "Mensaje",
            placeholder="Describe el problema, radicado o ayuda que necesitas.",
        )
        enviar_soporte = st.form_submit_button("Enviar consulta")
    if enviar_soporte:
        if agregar_mensaje_soporte(
            correo_activo,
            asunto_soporte,
            mensaje_soporte,
        ):
            st.success("Consulta enviada al buzón del Super Administrador.")
            st.rerun()

    if es_super_admin:
        mensajes = st.session_state.get("mensajes_soporte", [])
        st.subheader("Consultas de soporte")
        pendientes_soporte = [mensaje for mensaje in mensajes if not mensaje.get("leido")]
        if pendientes_soporte:
            st.warning(f"Hay {len(pendientes_soporte)} consulta(s) sin leer.")
        for mensaje in reversed(mensajes):
            with st.expander(
                f"{mensaje.get('asunto', 'Soporte')} · {mensaje.get('fecha', '')}"
            ):
                st.write(f"**De:** {mensaje.get('remitente', '')}")
                st.write(mensaje.get("mensaje", ""))
                if not mensaje.get("leido") and st.button(
                    "Marcar como leída",
                    key=f"read_support_{mensaje.get('id')}",
                ):
                    mensaje["leido"] = True
                    guardar_local_json(st.session_state.db_expedientes)
                    st.rerun()
        pendientes = obtener_usuarios_pendientes()
        st.subheader("Cuentas por aprobar")
        if pendientes:
            st.warning(f"Hay {len(pendientes)} cuenta(s) esperando activación.")
            for pendiente in pendientes:
                st.write(
                    f"- **{pendiente.get('full_name') or pendiente.get('alias') or 'Usuario'}** "
                    f"(`{pendiente.get('email', '')}`)"
                )
            st.info("Abre Gestión de Permisos para asignar el rol y activar cada cuenta.")
        else:
            st.success("No hay cuentas por aprobar.")
        solicitudes = obtener_solicitudes_descarga()
        st.subheader("Solicitudes de descarga")
        if solicitudes:
            st.warning(f"Hay {len(solicitudes)} solicitud(es) de descarga pendientes.")
            for solicitud in solicitudes:
                st.write(
                    f"- **{solicitud['alias']}** (`{solicitud['email']}`) "
                    "requiere autorización en Gestión de Permisos."
                )
        else:
            st.success("No hay solicitudes de descarga pendientes.")

elif st.session_state.navegacion == "Base Histórica" and es_admin:
    if st.button("⬅️ Volver al Inicio"):
        st.session_state.navegacion = "Inicio"
        st.rerun()

    st.header("Base histórica y respaldo")
    st.write(
        "El Excel histórico se configura como un archivo externo de solo lectura. "
        "La importación agrega sus procesos al almacenamiento local sin modificar el archivo."
    )

    if not os.path.exists(HISTORICO_FILE):
        st.error(
            "No se encontró el archivo histórico externo configurado. "
            "Configura SISTEMA_HISTORICO_FILE si necesitas importar el respaldo."
        )
    else:
        st.success(f"Respaldo disponible: {HISTORICO_FILENAME}")
        try:
            registros_historicos = leer_base_historica()
            radicados_actuales = set(st.session_state.db_expedientes)
            nuevos = [
                registro for registro in registros_historicos
                if registro["radicado_padre"] not in radicados_actuales
            ]
            st.metric("Registros en el respaldo", len(registros_historicos))
            st.metric("Registros nuevos para importar", len(nuevos))
            if registros_historicos:
                tabla_historica = pd.DataFrame(registros_historicos)
                tabla_historica["_orden_fecha"] = pd.to_datetime(
                    tabla_historica["fecha_solicitud"],
                    errors="coerce",
                )
                tabla_historica = tabla_historica.sort_values(
                    "_orden_fecha",
                    ascending=True,
                    na_position="last",
                ).drop(columns="_orden_fecha")
                st.dataframe(
                    tabla_historica[
                        ["radicado_padre", "placa", "empresa", "fecha_solicitud", "estado"]
                    ].head(100),
                    width="stretch",
                )
        except (FileNotFoundError, ValueError, OSError) as error:
            st.error(f"No fue posible leer la base histórica: {error}")
        else:
            col_importar, col_descargar = st.columns(2)
            with col_importar:
                if st.button(
                    "Importar registros nuevos al programa",
                    type="primary",
                    width="stretch",
                    disabled=not nuevos,
                ):
                    importados, duplicados, total = importar_base_historica()
                    st.success(
                        f"Importación terminada: {importados} nuevos, "
                        f"{duplicados} ya existentes, de {total} registros válidos."
                    )
                    st.rerun()
            with col_descargar:
                with open(HISTORICO_FILE, "rb") as respaldo:
                    st.download_button(
                        "Descargar respaldo original",
                        data=respaldo.read(),
                        file_name=HISTORICO_FILENAME,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        width="stretch",
                    )

elif st.session_state.navegacion == "Google Drive":
    if st.button("⬅️ Volver al Inicio"):
        st.session_state.navegacion = "Inicio"
        st.rerun()

    st.header("Google Drive")
    st.write("Google Drive se abrirá en el navegador para conservar todas sus funciones y permisos.")
    if st.button("Abrir carpeta de Google Drive", type="primary", width="stretch"):
        abrir_en_navegador(
            f"https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}",
            "Google Drive",
        )

elif st.session_state.navegacion == "Hoja Google Sheets":
    if st.button("⬅️ Volver al Inicio"):
        st.session_state.navegacion = "Inicio"
        st.rerun()

    st.header("Google Sheets")
    st.write("Google Sheets se abrirá en el navegador para permitir edición, filtros y colaboración completos.")
    if st.button("Abrir base de datos en Google Sheets", type="primary", width="stretch"):
        abrir_en_navegador(SHEET_URL, "Google Sheets")

elif st.session_state.navegacion == "Gestión de Permisos" and es_super_admin:
    if st.button("⬅️ Volver al Inicio"):
        st.session_state.navegacion = "Inicio"
        st.rerun()

    st.header("Administración de Usuarios y Permisos")
    if st.session_state.get("supabase_access_token"):
        sincronizar_perfiles_remotos()
    elif supabase_configurado():
        st.warning(
            "Esta sesión no tiene un token de Supabase. "
            "Inicia sesión con la cuenta local vinculada para cargar y guardar usuarios remotos."
        )

    for email, uinfo in list(st.session_state.usuarios.items()):
        with st.expander(f"{uinfo['alias']} ({email}) - Rol: {uinfo.get('rol')}"):
            with st.form(key=f"form_perm_sys_{email}"):
                c_a1, c_a2 = st.columns(2)
                
                rol_user = uinfo.get("rol", "Sin Rol Asignado")
                idx_rol = ROLES_DISPONIBLES.index(rol_user) if rol_user in ROLES_DISPONIBLES else 0

                estado_user = uinfo.get("estado", "Pendiente")
                idx_estado = ESTADOS_DISPONIBLES.index(estado_user) if estado_user in ESTADOS_DISPONIBLES else 0

                with c_a1:
                    nuevo_rol = st.selectbox("Rol:", options=ROLES_DISPONIBLES, index=idx_rol)
                with c_a2:
                    nuevo_estado = st.selectbox("Estado:", options=ESTADOS_DISPONIBLES, index=idx_estado)
                permiso_descarga = st.checkbox(
                    "Permitir descarga de documentos",
                    value=bool(uinfo.get("permiso_descarga")),
                    disabled=email == SUPER_ADMIN_EMAIL,
                )
                if solicitud_descarga_pendiente(uinfo):
                    st.warning("Este usuario tiene una solicitud de descarga pendiente.")

                if st.form_submit_button("Guardar Permiso"):
                    remote_saved = supabase_actualizar_perfil(
                        st.session_state.get("supabase_access_token"),
                        email,
                        nuevo_rol,
                        nuevo_estado,
                    )
                    if not remote_saved and supabase_configurado():
                        st.error("No se guardaron los permisos: Supabase no autorizó el cambio.")
                        continue
                    st.session_state.usuarios[email]["rol"] = nuevo_rol
                    st.session_state.usuarios[email]["estado"] = nuevo_estado
                    st.session_state.usuarios[email]["permiso_descarga"] = (
                        permiso_descarga or nuevo_rol in {
                            "Modificador",
                            "Administrador",
                            "Super Administrador",
                        }
                    )
                    if st.session_state.usuarios[email]["permiso_descarga"]:
                        st.session_state.usuarios[email]["solicitud_descarga"] = False
                    guardar_local_json(st.session_state.db_expedientes)
                    enviar_notificacion_correo(
                        email,
                        "Actualización de permisos - Sistema de Desvinculaciones",
                        (
                            f"Tu cuenta fue actualizada por {correo_activo}.\n\n"
                            f"Estado: {nuevo_estado}\n"
                            f"Rol asignado: {nuevo_rol}\n"
                            f"Descarga de documentos: "
                            f"{'autorizada' if st.session_state.usuarios[email]['permiso_descarga'] else 'no autorizada'}\n\n"
                            "Ingresa al sistema para consultar los cambios."
                        ),
                    )
                    if nuevo_estado == "Activo" or nuevo_rol != rol_user:
                        notificar_super_admin(
                            "Permisos actualizados - Sistema de Desvinculaciones",
                            (
                                f"{correo_activo} actualizó la cuenta {email}.\n"
                                f"Estado: {nuevo_estado}; rol: {nuevo_rol}."
                            ),
                        )
                    st.success("Permisos guardados en Supabase y en la caché local.")
                    st.rerun()

elif st.session_state.navegacion == "Mi Perfil":
    if st.button("⬅️ Volver al Inicio"):
        st.session_state.navegacion = "Inicio"
        st.rerun()

    st.header("Perfil de Usuario")

    st.markdown(f"""
    * **Alias / Nombre:** `{datos_usuario['alias']}`
    * **Correo Electrónico:** `{correo_activo}`
    * **Rol del Sistema:** `{rol_actual}`
    * **Estado de la Cuenta:** `{estado_actual}`
    * **Descarga de documentos:** `{"Autorizada" if puede_descargar else "No autorizada"}`
    * **Autenticación:** `{datos_usuario.get('metodo', 'Google / Local')}`
    * **Registrado:** `{datos_usuario.get('fecha_registro', '2026-01-01')}`
    """)

    st.divider()

    if rol_actual == "Visualizador" and not puede_descargar:
        if solicitud_descarga_pendiente(datos_usuario):
            st.info("Tu solicitud de descarga está pendiente de aprobación.")
        elif st.button("Solicitar permiso para descargar documentos"):
            datos_usuario["solicitud_descarga"] = True
            st.session_state.usuarios[correo_activo] = datos_usuario
            guardar_local_json(st.session_state.db_expedientes)
            st.success("Solicitud enviada al Super Administrador.")
            st.rerun()

    if st.button("Cerrar Sesión del Sistema", width="stretch"):
        cerrar_sesion()