import os
import sys
import shutil

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
    import fitz
except ImportError:
    fitz = None

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    RapidOCR = None

try:
    import onnxruntime as ort
except ImportError:
    ort = None

_ocr_engine = None
_ocr_cache_writes_pending = 0
# Los expedientes recibidos son escaneos y pueden superar ampliamente ocho
# páginas. Limitar el OCR dejaba sin leer la mayor parte del expediente.
OCR_MAX_PAGES = None
# 1.2x conserva una resolución suficiente para formularios escaneados y
# reduce el costo del OCR frente al renderizado anterior de 1.5x.
OCR_RENDER_SCALE = 1.2
OCR_CACHE_VERSION = "2"
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
    return RapidOCR(**configuracion_ocr_local())

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
    page_title="Sistema de Desvinculaciones - Alcaldía de Cali",
    layout="wide",
    initial_sidebar_state="expanded",
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
    "1HQtfhjWv9M_PljH4mfP-qdke9d5nyGTF",
).strip()
DRIVE_SCANNED_FOLDER_NAME = "PDFS Escaneados"
SPREADSHEET_ID = os.environ.get(
    "SISTEMA_SPREADSHEET_ID",
    "1oQ5GnxSj4_gGA-p2NjlN3o0uDOLaIELZu4gpohLK6Uo",
).strip()
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"
HISTORICO_FILENAME = "BD_DESVINCULACIONES ADMINISTRATIVAS.xlsx"

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
    "Notificación",
    "Constancia de ejecutoria",
    "Recurso",
    "Desistimiento",
    "Remisión a registro",
    "Otro",
]
TIPOS_CASO = ["Detección automática", "Con recurso", "Sin recurso", "Desistimiento"]
DOCUMENTOS_REQUERIDOS_POR_CASO = {
    "Con recurso": {"Solicitud", "Resolución", "Notificación", "Recurso"},
    "Sin recurso": {"Solicitud", "Resolución", "Notificación", "Constancia de ejecutoria"},
    "Desistimiento": {"Solicitud", "Desistimiento"},
}

DOCUMENTOS_BASE_POR_CASO = {
    "Con recurso": ("Solicitud", "Resolución", "Notificación", "Recurso"),
    "Sin recurso": ("Solicitud", "Resolución", "Notificación", "Constancia de ejecutoria"),
    "Desistimiento": ("Solicitud", "Desistimiento"),
}


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
        if config.get("web") and not any(
            "8080" in uri for uri in cliente.get("redirect_uris", [])
        ):
            return (
                "Tu credentials.json es de tipo web y no tiene registrada la "
                "redirección local del puerto 8080. Agrega "
                "http://localhost:8080/ y http://127.0.0.1:8080/ en Google Cloud, "
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
        return build("sheets", "v4", credentials=creds)
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


def carpeta_drive_para_fecha(service, fecha):
    """Obtiene PDFS Escaneados/AÑO para clasificar cada documento por año."""
    try:
        fecha_obj = datetime.date.fromisoformat(str(fecha or "").strip())
        anio = str(fecha_obj.year)
        escaneados_id = buscar_o_crear_carpeta_drive(
            service,
            DRIVE_FOLDER_ID,
            DRIVE_SCANNED_FOLDER_NAME,
        )
        if not escaneados_id:
            return None
        return buscar_o_crear_carpeta_drive(service, escaneados_id, anio)
    except (TypeError, ValueError):
        st.error(
            "No se puede clasificar el documento en Drive porque la fecha de "
            "la petición no es válida. Usa el formato AAAA-MM-DD."
        )
        return None


def carpeta_drive_para_expediente(service, fecha, radicado, placa, ubicacion):
    """Obtiene la carpeta estable AÑO/EXPEDIENTE dentro de PDFS Escaneados."""
    carpeta_anual_id = carpeta_drive_para_fecha(service, fecha)
    if not carpeta_anual_id:
        return None
    nombre = nombre_documento_expediente(
        radicado,
        placa,
        str(fecha),
        ubicacion,
        "",
    )
    return buscar_o_crear_carpeta_drive(service, carpeta_anual_id, nombre)


def carpeta_drive_para_pendientes(service):
    """Obtiene la bandeja donde se conservan anexos sin fecha de petición."""
    escaneados_id = buscar_o_crear_carpeta_drive(
        service,
        DRIVE_FOLDER_ID,
        DRIVE_SCANNED_FOLDER_NAME,
    )
    if not escaneados_id:
        return None
    return buscar_o_crear_carpeta_drive(service, escaneados_id, "Pendientes")


def carpeta_drive_para_documento(service, carpeta_expediente_id, tipo_documento):
    """Obtiene una subcarpeta del expediente para cada tipo documental."""
    nombre = re.sub(
        r"[^A-Za-z0-9ÁÉÍÓÚáéíóúÑñÜü -]+",
        "",
        str(tipo_documento or "Otro"),
    ).strip() or "Otro"
    return buscar_o_crear_carpeta_drive(
        service,
        carpeta_expediente_id,
        nombre,
    )


def preparar_carga_drive(
    service,
    archivos,
    radicado,
    placa,
    fecha,
    tipo_fallback,
    carga_id,
):
    """Sube de inmediato las partes detectadas; el PDF unificado se crea al guardar."""
    if not service:
        return [], None, "Google Drive no está autenticado."
    try:
        if fecha:
            carpeta_expediente = carpeta_drive_para_expediente(
                service,
                str(fecha),
                radicado or "RADICADO_PENDIENTE",
                placa or "PLACA_PENDIENTE",
                f"Carga-{carga_id}",
            )
        else:
            pendientes = carpeta_drive_para_pendientes(service)
            carpeta_expediente = buscar_o_crear_carpeta_drive(
                service,
                pendientes,
                f"Carga-{radicado or carga_id}",
            )
        if not carpeta_expediente:
            return [], None, "No fue posible crear la carpeta de carga en Drive."

        documentos = []
        for archivo in archivos:
            contenido = archivo.getvalue()
            if not archivo.name.lower().endswith(".pdf"):
                contenido = convertir_imagen_a_pdf(contenido, archivo.name)
            partes = separar_pdf_completo(contenido, tipo_fallback)
            for numero, parte in enumerate(partes, start=1):
                tipo = parte.get("tipo") or tipo_fallback or "Otro"
                carpeta_tipo = carpeta_drive_para_documento(
                    service,
                    carpeta_expediente,
                    tipo,
                )
                base = re.sub(
                    r"[^A-Za-z0-9._-]+",
                    "_",
                    os.path.splitext(archivo.name)[0],
                ).strip("_") or f"carga_{carga_id}"
                nombre = f"{base}_{tipo}_{numero:02d}.pdf"
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
                    "carga_id": carga_id,
                    "staged": True,
                })
        return documentos, carpeta_expediente, None
    except (OSError, ValueError, TypeError) as error:
        return [], None, f"No fue posible preparar la carga en Drive: {error}"


def mover_archivo_drive(service, file_id, carpeta_destino_id):
    """Mueve un archivo pendiente sin descargarlo ni volverlo a subir."""
    if not service or not file_id or not carpeta_destino_id:
        return False
    try:
        actual = service.files().get(fileId=file_id, fields="parents").execute()
        padres_lista = actual.get("parents", [])
        if carpeta_destino_id in padres_lista:
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


def mover_carpeta_drive(service, folder_id, carpeta_destino_id):
    """Mueve una carpeta de Pendientes al año definitivo sin duplicar su contenido."""
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
    if isinstance(texto_guardado, str):
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
    """Devuelve texto digital y usa OCR local como respaldo para PDFs escaneados."""
    global _ocr_cache_writes_pending
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(io.BytesIO(contenido))
        texto = " ".join(
            (pagina.extract_text() or "").replace("\xa0", " ")
            for pagina in reader.pages
        )
        texto = normalizar_texto_documento(texto)
        texto_util = bool(
            re.search(
                r"\b(?:radicado|radicaci[oó]n|placa|matr[ií]cula|solicitud|"
                r"petici[oó]n|resoluci[oó]n|notificaci[oó]n|recurso|"
                r"desistim|desiste)\b",
                texto,
                flags=re.IGNORECASE,
            )
        )
        datos_basicos = extraer_datos_pdf(contenido, texto=texto) if texto else {}
        if texto and texto_util and len(datos_basicos) >= 4:
            if progreso:
                progreso(1, 1)
            return texto
    except Exception:
        texto = ""
    if fitz is None or RapidOCR is None:
        return texto
    try:
        global _ocr_engine
        if _ocr_engine is None:
            _ocr_engine = crear_motor_ocr()
        documento = fitz.open(stream=contenido, filetype="pdf")
        paginas = [texto] if texto else []
        total_paginas = len(documento)
        for indice, pagina in enumerate(documento):
            if OCR_MAX_PAGES is not None and indice >= OCR_MAX_PAGES:
                break
            pixmap_vista = pagina.get_pixmap(
                matrix=fitz.Matrix(0.35, 0.35),
                alpha=False,
            )
            if pagina_pixeles_blancos(pixmap_vista):
                if progreso:
                    progreso(indice + 1, total_paginas)
                continue
            texto_pagina = obtener_texto_ocr_pagina(
                contenido,
                indice,
                pagina,
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
    except Exception:
        return texto


@lru_cache(maxsize=8)
def extraer_texto_pdf(contenido):
    """Devuelve texto cacheado para lecturas repetidas del mismo documento."""
    return _extraer_texto_pdf(contenido)


def extraer_texto_pdf_con_progreso(contenido, progreso):
    """Extrae texto y notifica el avance de OCR sin contaminar la caché."""
    return _extraer_texto_pdf(contenido, progreso=progreso)


def normalizar_texto_documento(texto):
    return " ".join(str(texto or "").replace("\xa0", " ").split())


def normalizar_errores_ocr(texto):
    """Corrige errores frecuentes del OCR antes de aplicar reglas documentales."""
    texto = normalizar_texto_documento(texto)
    reemplazos = (
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


def combinar_datos_detectados(destino, nuevos):
    """Conserva el primer valor útil y evita que un anexo borre otro dato."""
    for campo, valor in (nuevos or {}).items():
        if valor and not destino.get(campo):
            destino[campo] = valor
    return destino


def extraer_datos_pdf(contenido, texto=None):
    """Extrae metadatos de PDFs digitales; devuelve vacío si es un escaneo sin OCR."""
    texto = normalizar_errores_ocr(
        extraer_texto_pdf(contenido) if texto is None else texto
    )
    if not texto:
        return {}
    patrones = {
        "radicado_padre": [
            r"\b(?:rad|radicado|radicaci[oó]n|orfeo)\s*(?:padre|principal)?\s*(?:no\.?)?\s*[:.#\-]?\s*([A-Z0-9][A-Z0-9./\-]{7,})\b",
            r"\b(20\d{2}\d{14,18})\b",
        ],
        "placa": [
            r"(?:placa|placas|matr[ií]cula|matricula|veh[ií]culo)\s*[:#\-]?\s*([A-Z]{3}\s*[-]?\s*\d{3})\b",
        ],
        "fecha_solicitud": [
            r"(?:fecha\s*(?:de\s*)?(?:creaci[oó]n|radicaci[oó]n|solicitud|recibido))\s*[:#\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"\b(\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s+de\s+20\d{2})\b",
            r"\b(\d{1,2}\s+(?:de\s+)?(?:ene(?:ro)?|feb(?:rero)?|mar(?:zo)?|"
            r"abr(?:il)?|may(?:o)?|jun(?:io)?|jul(?:io)?|ago(?:sto)?|"
            r"sep(?:tiembre)?|set(?:iembre)?|oct(?:ubre)?|nov(?:iembre)?|"
            r"dic(?:iembre)?)\s+(?:de\s+)?20\d{2})\b",
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
            r"fecha\s+(?:de\s+)?resoluci[oó]n\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
            r"fecha\s+(?:de\s+)?resoluci[oó]n\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}\s+(?:de\s+)?[A-Za-záéíóú]+(?:\s+de)?\s+20\d{2})",
        ],
        "fecha_notificacion": [
            r"fecha\s+(?:de\s+)?notificaci[oó]n\s*[:#\-]?\s*(?:de\s+)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
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
            r"\b(?:NIT|n\.i\.t\.)\s*[:#\-]?\s*([0-9]{6,12}(?:\s*[\-–]\s*[0-9])?)\b",
        ],
        "cedula": [
            r"\b(?:c[eé]dula|c\.c\.|identificaci[oó]n)\s*[:#\-]?\s*([0-9][0-9.\s]{5,14})\b",
        ],
        "empresa": [
            r"\bempresa\s*[:#\-]?\s*([^|]{3,100}?)(?=\s+(?:NIT|propietario|placa|radicado|resoluci[oó]n|correo)\b|$)",
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
                elif campo in {
                    "correo", "nit", "cedula", "empresa", "propietario",
                    "direccion_empresa", "direccion_propietario", "nueva_empresa",
                    "tipo_notificacion", "funcionario", "resolucion",
                }:
                    valor = re.sub(r"\s+", " ", valor).strip()
                datos[campo] = valor
                break
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
def separar_pdf_completo(contenido, tipo_fallback):
    """Quita páginas vacías y separa un PDF por bloques documentales detectables."""
    global _ocr_cache_writes_pending
    if PdfReader is None or PdfWriter is None:
        return [{"contenido": contenido, "tipo": tipo_fallback, "paginas": 0}]
    try:
        lector = PdfReader(io.BytesIO(contenido))
        documento_visual = fitz.open(stream=contenido, filetype="pdf") if fitz else None
        tiene_texto_digital = any(
            len(" ".join((pagina.extract_text() or "").split())) >= 8
            for pagina in lector.pages
        )
        grupos = []
        actual = None
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
            requiere_ocr = not texto
            if requiere_ocr:
                texto = obtener_texto_ocr_pagina(
                    contenido,
                    numero_pagina,
                    documento_visual.load_page(numero_pagina),
                )
            elif not tiene_texto_digital:
                texto = f"{texto} {obtener_texto_ocr_pagina(contenido, numero_pagina, documento_visual.load_page(numero_pagina))}".strip()
            elif not re.search(
                r"resoluci[oó]n|notificaci[oó]n|recurso|desistim|"
                r"solicitud|petici[oó]n",
                texto,
                flags=re.IGNORECASE,
            ):
                texto = f"{texto} {obtener_texto_ocr_pagina(contenido, numero_pagina, documento_visual.load_page(numero_pagina))}".strip()
            tipo = clasificar_tipo_documento(texto, tipo_fallback)
            if actual and actual["tipo"] == tipo:
                actual["paginas"].append(pagina)
            else:
                actual = {"tipo": tipo, "paginas": [pagina]}
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
            })
        return resultado
    except Exception:
        return [{"contenido": contenido, "tipo": tipo_fallback, "paginas": 0}]


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
        return total_pixeles == 0 or (pixeles_oscuros / total_pixeles) < 0.001
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
    return total_pixeles == 0 or (pixeles_oscuros / max(total_pixeles // 4, 1)) < 0.001


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
        r"\bsin\s+recurso\b|no\s+interpuso|no\s+present[oó]|"
        r"sin\s+interponer",
        evidencia,
    ):
        if re.search(r"resoluci[oó]n|acto\s+administrativo", evidencia):
            return "Resolución"
    reglas = [
        (
            "Desistimiento",
            r"desistim|desiste|declara(?:r)?\s+(?:el\s+)?desistimiento|"
            r"desistimiento\s+de\s+una\s+solicitud",
        ),
        ("Resolución", r"\bresoluci[oó]n\b"),
        ("Recurso", r"\brecurso\b|reposici[oó]n|apelaci[oó]n"),
        ("Notificación", r"notificaci[oó]n|citado|aviso"),
        ("Constancia de ejecutoria", r"ejecutoria|firmeza"),
        ("Solicitud", r"derecho de petici[oó]n|solicito|solicitud"),
    ]
    for tipo, patron in reglas:
        if re.search(patron, evidencia):
            return tipo
    return tipo_fallback


def tipos_documentales_detectados(texto, tipo_fallback):
    """Devuelve todos los tipos mencionados en un expediente unificado."""
    evidencia = normalizar_errores_ocr(texto).lower()
    reglas = [
        ("Desistimiento", r"desistim|desiste"),
        ("Recurso", r"\brecurso\b|reposici[oó]n|apelaci[oó]n"),
        ("Resolución", r"\bresoluci[oó]n\b|acto\s+administrativo"),
        ("Notificación", r"notificaci[oó]n|citado|aviso|publicaci[oó]n"),
        ("Constancia de ejecutoria", r"ejecutoria|firmeza"),
        ("Solicitud", r"derecho de petici[oó]n|solicito|solicitud"),
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
    return detectados or {tipo_fallback}


def nombre_documento_expediente(radicado, placa, fecha, ubicacion, extension):
    """Genera un nombre estable para ubicar documentos aunque lleguen con otro nombre."""
    partes = [radicado, placa, fecha, ubicacion]
    nombre = "_".join(
        re.sub(r"[^A-Za-z0-9-]+", "-", str(parte).strip()).strip("-")
        for parte in partes
    )
    return f"{nombre}{extension.lower()}"


def clasificar_tipo_caso(texto="", nombre=""):
    """Identifica uno de los tres desenlaces válidos del expediente."""
    evidencia = normalizar_errores_ocr(f"{nombre} {texto}").lower()
    if re.search(r"desistim|desestimiento|desistimiento|desiste", evidencia):
        return "Desistimiento"
    if re.search(
        r"\bsin\s+recurso\b|no\s+interpuso\s+(?:un\s+)?recurso|"
        r"sin\s+interponer\s+(?:el\s+)?recurso|"
        r"\bno\s+present[oó]\s+(?:el\s+|un\s+)?recurso\b|"
        r"\bno\s+se\s+present[oó]\s+recurso\b",
        evidencia,
    ):
        return "Sin recurso"
    if re.search(
        r"\bcon\s+recurso\b|\brecurso\s+de\s+reposici[oó]n\b|"
        r"\binterpuso\s+(?:un\s+)?recurso\b|\bpresent[oó]\s+(?:un\s+)?recurso\b|"
        r"\bse\s+resuelve\s+el\s+recurso\b",
        evidencia,
    ):
        return "Con recurso"
    return None


def documentos_faltantes(registro):
    esperados = set(registro.get("documentos_esperados", []))
    anexados = {
        documento.get("tipo_documento")
        for documento in registro.get("canvas_paginas", [])
        if documento.get("tipo_documento")
    }
    return sorted(esperados - anexados)


def documentos_requeridos_por_caso(tipo_caso, documentos_adicionales=None):
    requeridos = set(DOCUMENTOS_REQUERIDOS_POR_CASO.get(tipo_caso, set()))
    requeridos.update(documentos_adicionales or [])
    return sorted(requeridos)


def renderizar_checklist_documental(tipo_caso, documentos_presentes):
    """Muestra el checklist del proceso y sus documentos detectados."""
    requeridos = documentos_requeridos_por_caso(tipo_caso)
    presentes = set(documentos_presentes or [])
    if tipo_caso == "Desistimiento":
        presentes.add("Desistimiento")
    elif tipo_caso == "Con recurso":
        presentes.add("Recurso")
    faltantes = [nombre for nombre in requeridos if nombre not in presentes]
    st.markdown("#### Checklist documental")
    st.caption(f"Proceso seleccionado: **{tipo_caso}**")
    columnas = st.columns(2)
    for indice, documento in enumerate(requeridos):
        icono = "✅" if documento in presentes else "⬜"
        texto = f"{icono} {documento}"
        if faltantes and documento in faltantes:
            columnas[indice % 2].warning(texto)
        else:
            columnas[indice % 2].success(texto)
    if faltantes:
        st.warning("Faltan documentos: " + ", ".join(faltantes))
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
    metadata = service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID,
        fields="sheets.properties.title",
    ).execute()
    hojas = metadata.get("sheets", [])
    if not hojas:
        raise ValueError("El archivo de Google Sheets no contiene pestañas.")
    titulo = hojas[0].get("properties", {}).get("title", "").strip()
    if not titulo:
        raise ValueError("No se pudo identificar la pestaña de Google Sheets.")
    titulo_seguro = titulo.replace("'", "''")
    return f"'{titulo_seguro}'!{columnas}"


def normalizar_campo_sheet(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    # Algunas copias históricas tienen letras acentuadas dañadas como �.
    texto = texto.replace("�", "O")
    return re.sub(r"\s+", " ", texto).strip().upper()


COLUMNAS_SHEET_OFICIALES = [
    "FECHA",
    "PLACA",
    "EMPRESA",
    "NIT",
    "DIRECCIÓN",
    "PROPIETARIO",
    "CEDULA",
    "DIRECCIÓN",
    "RAD PADRE",
    "FECHA RAD-",
    "RESOLUCIÓN DESVINCULACIÓN",
    "FECHA DESVINCULACIÓN",
    "OBSERVACIÓN",
    "FUNCIONARIO QUE DESVINCULA",
    "NUEVA EMPRESA",
    "SOLICITANTE",
    "ESTADO",
    "CORREO ELECTRÓNICO",
    "RECURSO",
    "FECHA RECURSO",
    "OBSERVACIONES",
    "TIPO CASO",
    "TIPO NOTIFICACIÓN",
    "FECHA NOTIFICACIÓN",
    "FECHA EJECUTORIA",
    "FECHA REMISIÓN REGISTRO",
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


def letra_columna(numero):
    resultado = ""
    while numero:
        numero, resto = divmod(numero - 1, 26)
        resultado = chr(65 + resto) + resultado
    return resultado


def buscar_registro_en_sheets(service, radicado="", placa="", fecha=""):
    if not service or (not radicado and not placa and not fecha):
        return None
    try:
        filas = leer_registros_sheets(service)
        if not filas:
            return None
        encabezados = [normalizar_campo_sheet(valor) for valor in filas[0]]
        indice_rad = next(
            (i for i, valor in enumerate(encabezados) if valor == "RAD PADRE"),
            None,
        )
        indice_placa = next(
            (i for i, valor in enumerate(encabezados) if valor == "PLACA"),
            None,
        )
        indice_fecha = next(
            (
                i for i, valor in enumerate(encabezados)
                if valor in {"FECHA", "FECHA SOLICITUD", "FECHA_SOLICITUD"}
            ),
            None,
        )
        coincidencia_por_placa = None
        coincidencia_por_fecha = None
        fecha_normalizada = str(fecha or "").strip()
        for numero, fila in enumerate(filas[1:], start=2):
            valor_rad = str(fila[indice_rad]).strip().upper() if indice_rad is not None and len(fila) > indice_rad else ""
            valor_placa = str(fila[indice_placa]).strip().upper() if indice_placa is not None and len(fila) > indice_placa else ""
            valor_fecha = str(fila[indice_fecha]).strip() if indice_fecha is not None and len(fila) > indice_fecha else ""
            coincide_radicado = (
                bool(radicado)
                and valor_rad == str(radicado).strip().upper()
            )
            coincide_placa = (
                bool(placa)
                and valor_placa == str(placa).strip().upper()
            )
            if coincide_radicado:
                return {
                    "fila": fila,
                    "numero": numero,
                    "encabezados": encabezados,
                }
            if coincide_placa and not coincidencia_por_placa:
                coincidencia_por_placa = {
                    "fila": fila,
                    "numero": numero,
                    "encabezados": encabezados,
                }
            if fecha_normalizada and valor_fecha == fecha_normalizada and not coincidencia_por_fecha:
                coincidencia_por_fecha = {
                    "fila": fila,
                    "numero": numero,
                    "encabezados": encabezados,
                }
            elif fecha_normalizada and valor_fecha == fecha_normalizada:
                coincidencia_por_fecha = "multiple"
        if coincidencia_por_placa and not radicado:
            return coincidencia_por_placa
        if coincidencia_por_fecha and coincidencia_por_fecha != "multiple" and not radicado and not placa:
            return coincidencia_por_fecha
    except Exception as error:
        st.warning(f"No fue posible consultar el registro actual de Google Sheets: {error}")
    return None


def datos_registro_sheet(registro_sheet):
    if not registro_sheet:
        return {}
    fila = registro_sheet["fila"]
    datos = {}
    mapa = {
        "FECHA": "fecha_solicitud",
        "FECHA SOLICITUD": "fecha_solicitud",
        "FECHA_SOLICITUD": "fecha_solicitud",
        "PLACA": "placa",
        "RAD PADRE": "radicado_padre",
        "EMPRESA": "empresa",
        "NIT": "nit",
        "DIRECCION": "direccion_empresa",
        "PROPIETARIO": "propietario",
        "CEDULA": "cedula",
        "FECHA RAD-": "fecha_radicacion",
        "RESOLUCN DESVINCULACN": "resolucion",
        "FECHA DESVINCULACION": "fecha_resolucion",
        "FECHA DESVINCULACN": "fecha_resolucion",
        "RESOLUCION": "resolucion",
        "RESOLUCION DESVINCULACION": "resolucion",
        "OBSERVACION": "observacion",
        "FUNCIONARIO QUE DESVINCULA": "funcionario",
        "NUEVA EMPRESA": "nueva_empresa",
        "SOLICITANTE": "solicitante",
        "ESTADO": "estado",
        "CORREO ELECTRONICO": "correo",
        "RECURSO": "recurso",
        "FECHA RECURSO": "fecha_recurso",
        "OBSERVACIONES": "notas",
        "TIPO CASO": "tipo_caso",
        "TIPO NOTIFICACION": "tipo_notificacion",
        "FECHA NOTIFICACION": "fecha_notificacion",
        "FECHA EJECUTORIA": "fecha_ejecutoria",
        "FECHA REMISION REGISTRO": "fecha_remision_registro",
        "QX VERIFICADO": "qx_verificado",
        "ID EXPEDIENTE": "id",
        "UBICACION FISICA": "ubicacion",
        "CAJA": "caja",
        "FOLDER": "folder",
        "CARPETA": "carpeta",
        "FOLIACION": "foliacion",
        "FECHA ULTIMA MODIFICACION": "ultima_modificacion",
        "SUBIDO POR": "subido_por",
        "CORREO SUBIDA": "correo_subida",
        "CARGO SUBIDA": "cargo_subida",
        "ACCESO DIGITAL": "drive_folder",
        "DRIVE FOLDER": "drive_folder",
        "DOCUMENTOS DRIVE": "documentos_drive",
        "PDF UNIFICADO": "pdf_unificado",
        "DOCUMENTOS FALTANTES": "documentos_faltantes_drive",
        "CONTENIDO DOCUMENTAL": "contenido_documental",
    }
    indice_direccion = 0
    for indice, encabezado in enumerate(registro_sheet["encabezados"]):
        if encabezado == "DIRECCION":
            campo = (
                "direccion_empresa"
                if indice_direccion == 0
                else "direccion_propietario"
            )
            indice_direccion += 1
        else:
            campo = mapa.get(encabezado)
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
        "FECHA": registro_datos.get("fecha_solicitud", ""),
        "FECHA_SOLICITUD": registro_datos.get("fecha_solicitud", ""),
        "PLACA": registro_datos.get("placa", ""),
        "EMPRESA": registro_datos.get("empresa", ""),
        "NIT": registro_datos.get("nit", ""),
        "DIRECCION": registro_datos.get("direccion_empresa", ""),
        "PROPIETARIO": registro_datos.get("propietario", ""),
        "CEDULA": registro_datos.get("cedula", ""),
        "RAD PADRE": registro_datos.get("radicado_padre", ""),
        "RADICADO_PADRE": registro_datos.get("radicado_padre", ""),
        "FECHA RAD-": registro_datos.get("fecha_radicacion", ""),
        "FECHA_RADICACION": registro_datos.get("fecha_radicacion", ""),
        "RESOLUCN DESVINCULACN": registro_datos.get("resolucion", ""),
        "RESOLUCION DESVINCULACION": registro_datos.get("resolucion", ""),
        "RESOLUCION": registro_datos.get("resolucion", ""),
        "FECHA DESVINCULACN": registro_datos.get("fecha_resolucion", ""),
        "FECHA DESVINCULACION": registro_datos.get("fecha_resolucion", ""),
        "FECHA_DESVINCULACION": registro_datos.get("fecha_resolucion", ""),
        "OBSERVACION": registro_datos.get("observacion", ""),
        "FUNCIONARIO QUE DESVINCULA": registro_datos.get("funcionario", ""),
        "NUEVA EMPRESA": registro_datos.get("nueva_empresa", ""),
        "SOLICITANTE": registro_datos.get("solicitante", ""),
        "ESTADO": registro_datos.get("estado", ""),
        "CORREO ELECTRONICO": registro_datos.get("correo", ""),
        "CORREO_ELECTRONICO": registro_datos.get("correo", ""),
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
        clave = normalizar_campo_sheet(encabezado)
        if clave == "DIRECCION":
            valor = (
                registro_datos.get("direccion_empresa", "")
                if indice_direccion == 0
                else registro_datos.get("direccion_propietario", "")
            )
            indice_direccion += 1
        else:
            valor = valores.get(clave, "")
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
    propiedades = hojas[0].get("properties", {})
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


def guardar_registro_en_sheets(service, registro_datos):
    try:
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
                    range=obtener_rango_primera_hoja(
                        service,
                        f"A1:{letra_columna(len(encabezados))}1",
                    ),
                    valueInputOption="USER_ENTERED",
                    body={"values": [encabezados]},
                ).execute()
            fila = fila_registro_para_sheet(encabezados, registro_datos, fila)
            rango = obtener_rango_primera_hoja(
                service,
                f"A{existente['numero']}:{letra_columna(max(len(fila), len(encabezados)))}{existente['numero']}",
            )
            body = {"values": [fila]}
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=rango,
                valueInputOption="USER_ENTERED",
                body=body,
            ).execute()
            ordenar_sheet_por_fecha(service, encabezados)
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
                    range=obtener_rango_primera_hoja(
                        service,
                        f"A1:{letra_columna(len(encabezados))}1",
                    ),
                    valueInputOption="USER_ENTERED",
                    body={"values": [encabezados]},
                ).execute()
            valores = [fila_registro_para_sheet(encabezados, registro_datos)]
            siguiente_fila = len(filas_actuales) + 1
            rango = obtener_rango_primera_hoja(
                service,
                f"A{siguiente_fila}:{letra_columna(len(encabezados))}{siguiente_fila}",
            )
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=rango,
                valueInputOption="USER_ENTERED",
                body={"values": valores},
            ).execute()
            ordenar_sheet_por_fecha(service, encabezados)
        return True
    except Exception as e:
        st.error(f"Error guardando en Google Sheets: {e}")
        return False

def leer_registros_sheets(service):
    try:
        sheet = service.spreadsheets()
        rango = obtener_rango_primera_hoja(service, "A1:AZ2000")
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
                <div class="header-title">ALCALDÍA DE SANTIAGO DE CALI</div>
                <div class="header-subtitle">SECRETARÍA DE TRÁNSITO Y TRANSPORTE — SISTEMA DE DESVINCULACIONES</div>
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
                    download_and_apply_update(actualizacion["download_url"])

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
            'alt="Logo Alcaldía de Santiago de Cali"></div>',
            unsafe_allow_html=True,
        )
    st.markdown("### Sistema de desvinculaciones")
    st.caption(datos_usuario["alias"])
    st.caption(f"Lectura local: {estado_ocr_local()}")
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
            'alt="Logo Alcaldía de Santiago de Cali"></div>',
            unsafe_allow_html=True,
        )
    st.markdown("""
        <div class="header-box">
            <div class="header-title">ALCALDÍA DE SANTIAGO DE CALI</div>
            <div class="header-subtitle">SECRETARÍA DE TRÁNSITO Y TRANSPORTE — SISTEMA DE DESVINCULACIONES</div>
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
                combinar_datos_detectados(
                    datos_carga,
                    extraer_datos_pdf(
                        contenido_analizable,
                        texto=texto_archivo,
                    ),
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
                if tipo_detectado:
                    tipos_carga.add(tipo_detectado)
                tipos_documentales_carga.update(
                    tipos_documentales_detectados(texto_archivo, tipo_documento)
                )
            barra_analisis.progress(
                1.0,
                text="Análisis terminado. Información lista para confirmar.",
            )
            estado_analisis.success(
                "Lectura de los archivos terminada. Revisa los datos detectados "
                "antes de guardar."
            )
            if datos_carga:
                st.success(
                    "Datos detectados: "
                    + ", ".join(f"{campo}={valor}" for campo, valor in datos_carga.items())
                )
            else:
                st.warning(
                    "No se encontró texto seleccionable en los archivos. "
                    "Si el PDF es un escaneo como imagen, completa los campos "
                    "manualmente o habilita OCR en el equipo."
                )
            tipo_caso_detectado = clasificar_tipo_caso(
                " ".join(textos_analizados.values()),
                " ".join(archivo.name for archivo in archivos_canvas),
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
                )
                if error_staging:
                    st.warning(error_staging)
                elif documentos_staged:
                    carga_staging[carga_id] = {
                        "documentos": documentos_staged,
                        "drive_folder_id": carpeta_staged,
                    }
                    st.success(
                        "Partes documentales subidas a Drive para continuar el análisis. "
                        "El PDF unificado se generará al completar el registro."
                    )
            elif not drive_service:
                st.warning(
                    "Drive no está autenticado: la carga se conserva localmente y "
                    "no se puede crear la estructura documental remota."
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
                renderizar_checklist_documental(
                    tipo_checklist,
                    sorted(tipos_documentales_carga),
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
                        f"PDFS Escaneados/{anio_destino}/"
                        f"{destino_radicado or 'RADICADO_PENDIENTE'}_"
                        f"{destino_placa or 'PLACA_PENDIENTE'}"
                    )
                except ValueError:
                    destino_texto = "Carpeta anual pendiente de confirmar la fecha de petición"
            else:
                destino_texto = (
                    "PDFS Escaneados/Pendientes/ "
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
            datos_carga = {**datos_carga, **datos_sheet}
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
            f"foliacion_{carga_id}": foliacion_inicial,
        }
        carga_anterior = st.session_state.get("_registro_carga_id")
        if carga_anterior != carga_id:
            for clave, valor in campos_formulario.items():
                if valor not in (None, ""):
                    st.session_state[clave] = valor
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
                foliacion_registro = st.number_input(
                    "Foliación (hojas)",
                    min_value=0,
                    step=1,
                    value=foliacion_inicial,
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

            btn_guardar = st.form_submit_button("Guardar y Sincronizar Datos", width="stretch")

        if btn_guardar:
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
                        carpeta_anual_id = carpeta_drive_para_fecha(
                            drive_service,
                            str(fecha_registro_previa),
                        )
                        if carpeta_anual_id:
                            mover_carpeta_drive(
                                drive_service,
                                staged_folder_id,
                                carpeta_anual_id,
                            )
                        nombre_expediente = nombre_documento_expediente(
                            radicado_padre,
                            matricula_qx or placa_expediente,
                            str(fecha_registro_previa),
                            cod_ub,
                            "",
                        )
                        renombrar_carpeta_drive(
                            drive_service,
                            staged_folder_id,
                            nombre_expediente,
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
                            f"Expediente-completo_{cod_ub}",
                        )
                    else:
                        carpeta_expediente_drive_id = carpeta_drive_para_pendientes(
                            drive_service
                        )
                staged_documentos = [
                    documento.copy()
                    for documento in staged_carga.get("documentos", [])
                ]
                if drive_service and carpeta_expediente_drive_id:
                    for documento in staged_documentos:
                        carpeta_tipo = carpeta_drive_para_documento(
                            drive_service,
                            carpeta_expediente_drive_id,
                            documento.get("tipo_documento", "Otro"),
                        )
                        if carpeta_tipo and documento.get("drive_id"):
                            if mover_archivo_drive(
                                drive_service,
                                documento["drive_id"],
                                carpeta_tipo,
                            ):
                                documento["drive_folder_id"] = carpeta_tipo
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
                        texto_analizado = (
                            textos_analizados.get(huella_contenido(contenido_original))
                            if len(partes) == 1
                            else None
                        )
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
                                "texto_analizado": texto_analizado,
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
                            "huella": huella,
                            "ruta_local": ruta_local,
                            "pendiente": not bool(fecha_registro_previa),
                        })

                    pdfs_cargados = [
                        archivo["contenido"] for archivo in archivos_preparados
                        if archivo["nombre"].lower().endswith(".pdf")
                    ]
                    if existente and drive_service:
                        huellas_unificado = {
                            huella_contenido(contenido)
                            for contenido in pdfs_cargados
                        }
                        for documento_existente in existente.get("canvas_paginas", []):
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
                                pdfs_cargados.insert(0, contenido_existente)
                                huellas_unificado.add(huella_existente)
                    if pdfs_cargados:
                        pdf_unificado = unir_archivos_pdf(pdfs_cargados)
                        if pdf_unificado:
                            nombre_unificado = nombre_documento_expediente(
                                radicado_padre,
                                matricula_qx,
                                str(fecha_registro_previa),
                                f"Expediente-completo_{cod_ub}",
                                ".pdf",
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
                radicado_registro = (
                    datos_detectados.get("radicado_padre", radicado_padre)
                    if peticion_incluida
                    else radicado_padre.strip()
                )
                placa_registro = datos_detectados.get("placa") or matricula_qx
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
                fuente_existente = {
                    **(existente_final or {}),
                    **datos_detectados,
                    **datos_sheet,
                }

                def valor_actual(campo, valor_nuevo=""):
                    return valor_nuevo or fuente_existente.get(campo, "")

                registro_datos = {
                    **fuente_existente,
                    "id": total_expedientes,
                    "radicado_padre": radicado_registro,
                    "placa": placa_registro,
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
                    "ubicacion": valor_actual("ubicacion", cod_ub),
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
                    "nombre_ubicacion": nombre_documento_expediente(
                        radicado_registro,
                        placa_registro,
                        fecha_registro,
                        cod_ub,
                        "",
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
                        "El documento quedó en la carpeta **Pendientes**. "
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

                sheets_ok = False
                if sheets_service:
                    sheets_ok = guardar_registro_en_sheets(sheets_service, registro_datos)

                if sheets_ok:
                    st.success(f"Proceso guardado en Local, Drive y Google Sheets. Ubicación: **{cod_ub}**")
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
        st.subheader("Bandeja de PDF pendientes")
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
            st.success("No hay PDF pendientes de asociación.")

    tipo_busqueda = st.radio(
        "Tipo de búsqueda",
        ["Radicado Padre", "Placa", "Fecha"],
        horizontal=True,
    )
    coincidencias = []
    criterio = ""
    if tipo_busqueda == "Radicado Padre":
        criterio = st.text_input(
            "Radicado Padre:",
            placeholder="Ej: 2026-ORFEO-00123",
        ).strip().upper()
        coincidencias = [
            exp for radicado, exp in st.session_state.db_expedientes.items()
            if criterio and criterio in str(radicado).upper()
        ]
    elif tipo_busqueda == "Placa":
        criterio = st.text_input(
            "Placa:",
            placeholder="Ej: ABC123",
        ).strip().upper()
        coincidencias = [
            exp for exp in st.session_state.db_expedientes.values()
            if criterio and criterio in str(exp.get("placa", "")).upper()
        ]
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
        coincidencias = []
        for exp in st.session_state.db_expedientes.values():
            try:
                fecha = datetime.date.fromisoformat(str(exp.get("fecha_solicitud", "")))
            except ValueError:
                continue
            if fecha.year == anio and (mes == "Todos" or fecha.month == mes) and (
                dia == "Todos" or fecha.day == dia
            ):
                coincidencias.append(exp)

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
            for p in paginas:
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
        st.subheader("Pendientes de aprobación")
        if pendientes:
            st.warning(f"Hay {len(pendientes)} cuenta(s) esperando activación.")
            for pendiente in pendientes:
                st.write(
                    f"- **{pendiente.get('full_name') or pendiente.get('alias') or 'Usuario'}** "
                    f"(`{pendiente.get('email', '')}`)"
                )
            st.info("Abre Gestión de Permisos para asignar el rol y activar cada cuenta.")
        else:
            st.success("No hay cuentas pendientes de aprobación.")
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