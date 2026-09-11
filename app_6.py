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
import secrets
import tempfile
import threading
import webbrowser
from urllib.parse import quote

import streamlit as st
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
    from updater import check_for_updates
except ImportError:
    def check_for_updates():
        pass

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

# --- VERIFICACIÓN DE ACTUALIZACIONES EN SEGUNDO PLANO ---
if 'updater_checked' not in st.session_state:
    st.session_state.updater_checked = True
    threading.Thread(target=check_for_updates, daemon=True).start()

SUPER_ADMIN_EMAIL = "juan.torob@cun.edu.co"
SUPABASE_URL = os.environ.get(
    "SUPABASE_URL",
    "https://ktgogijxtsidctkidrav.supabase.co",
).rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()
DRIVE_FOLDER_ID = "1HQtfhjWv9M_PljH4mfP-qdke9d5nyGTF"
SPREADSHEET_ID = "1GW6cogkzdGoGgsA_jsR0ltpb2mlyDg4dK88gk7xh73o"
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
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

ROLES_DISPONIBLES = ["Sin Rol Asignado", "Visualizador", "Modificador", "Administrador", "Super Administrador"]
ESTADOS_DISPONIBLES = ["Pendiente", "Activo", "Inactivo"]


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


def supabase_obtener_perfil(access_token):
    """Obtiene el estado y rol remotos del usuario autenticado."""
    if not supabase_configurado() or not access_token:
        return None
    try:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {access_token}",
            },
            params={"select": "email,full_name,role,status"},
            timeout=15,
        )
    except requests.RequestException as error:
        st.warning(f"No fue posible consultar el perfil remoto: {error}")
        return None
    if response.status_code != 200:
        return None
    perfiles = response.json()
    return perfiles[0] if perfiles else None

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
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
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


def mostrar_documento_en_aplicacion(contenido, nombre):
    """Muestra un documento sin abrir Drive ni exponer controles de descarga al visualizador."""
    extension = os.path.splitext(nombre)[1].lower()
    if extension == ".pdf":
        st.pdf(contenido)
    elif extension in {".png", ".jpg", ".jpeg"}:
        st.image(contenido, caption=nombre, width="stretch")
    else:
        st.info("Este tipo de archivo no tiene vista previa integrada.")

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


def guardar_registro_en_sheets(service, registro_datos):
    try:
        valores = [[
            registro_datos.get("id", ""),
            registro_datos.get("radicado_padre", ""),
            registro_datos.get("placa", ""),
            registro_datos.get("solicitante", ""),
            registro_datos.get("fecha_minima", ""),
            registro_datos.get("resolucion", ""),
            "SI" if registro_datos.get("remitido", False) else "NO",
            registro_datos.get("ubicacion", ""),
            registro_datos.get("estado", ""),
            registro_datos.get("modificado_por", ""),
            registro_datos.get("ultima_modificacion", ""),
            registro_datos.get("notas", "")
        ]]
        body = {'values': valores}
        rango = obtener_rango_primera_hoja(service, "A:L")
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=rango,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()
        return True
    except Exception as e:
        st.error(f"Error guardando en Google Sheets: {e}")
        return False

def leer_registros_sheets(service):
    try:
        sheet = service.spreadsheets()
        rango = obtener_rango_primera_hoja(service, "A1:Z1000")
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
            "usuarios": st.session_state.get("usuarios", {})
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
                else:
                    db_cargada = raw_data
        except Exception:
            pass

    if service:
        filas = leer_registros_sheets(service)
        if filas and len(filas) > 1:
            for fila in filas[1:]:
                if len(fila) >= 2 and fila[1]:
                    rad = fila[1]
                    if rad not in db_cargada:
                        db_cargada[rad] = {
                            "id": fila[0] if len(fila) > 0 else 1,
                            "radicado_padre": rad,
                            "placa": fila[2] if len(fila) > 2 else "",
                            "solicitante": fila[3] if len(fila) > 3 else "",
                            "fecha_minima": fila[4] if len(fila) > 4 else "",
                            "resolucion": fila[5] if len(fila) > 5 else "",
                            "remitido": fila[6] == "SI" if len(fila) > 6 else False,
                            "ubicacion": fila[7] if len(fila) > 7 else "",
                            "estado": fila[8] if len(fila) > 8 else "",
                            "canvas_paginas": [],
                            "drive_folder": f"https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}",
                            "modificado_por": fila[9] if len(fila) > 9 else "Sistema",
                            "ultima_modificacion": fila[10] if len(fila) > 10 else "",
                            "notas": fila[11] if len(fila) > 11 else ""
                        }

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
    fecha = pd.to_datetime(valor, errors="coerce")
    return "" if pd.isna(fecha) else fecha.strftime("%Y-%m-%d")


def leer_base_historica():
    """Lee la hoja histórica y la convierte al modelo local actual."""
    if not os.path.exists(HISTORICO_FILE):
        raise FileNotFoundError(f"No se encontró el respaldo: {HISTORICO_FILE}")

    historico = pd.read_excel(HISTORICO_FILE, sheet_name="BD_DESV", dtype=object)
    historico.columns = [_texto_historico(col).upper() for col in historico.columns]
    registros = []
    for _, fila in historico.iterrows():
        radicado = _texto_historico(fila.get("RAD PADRE"))
        if not radicado:
            continue
        registros.append({
            "radicado_padre": radicado,
            "placa": _texto_historico(fila.get("PLACA")).upper(),
            "empresa": _texto_historico(fila.get("EMPRESA")),
            "nit": _texto_historico(fila.get("NIT")),
            "direccion_empresa": _texto_historico(fila.get("DIRECCIÓN")),
            "propietario": _texto_historico(fila.get("PROPIETARIO")),
            "cedula": _texto_historico(fila.get("CEDULA")),
            "direccion_propietario": _texto_historico(fila.get("DIRECCIÓN.1")),
            "fecha_solicitud": _fecha_historica(fila.get("FECHA")),
            "fecha_radicacion": _fecha_historica(fila.get("FECHA RAD-")),
            "resolucion": _texto_historico(fila.get("RESOLUCIÓN\nDESVINCULACIÓN")),
            "fecha_resolucion": _fecha_historica(fila.get("FECHA\n DESVINCULACIÓN")),
            "observacion": _texto_historico(fila.get("OBSERVACIÓN")),
            "funcionario": _texto_historico(fila.get("FUNCIONARIO QUE DESVINCULA")),
            "nueva_empresa": _texto_historico(fila.get("NUEVA EMPRESA")),
            "solicitante": _texto_historico(fila.get("SOLICITANTE")),
            "estado": _texto_historico(fila.get("ESTADO")),
            "correo": _texto_historico(fila.get("CORREO ELECTRÓNICO")),
            "recurso": _texto_historico(fila.get("RECURSO")),
            "fecha_recurso": _fecha_historica(fila.get("FECHA RECURSO")),
            "notas": _texto_historico(fila.get("OBSERVACIONES")),
        })
    return registros


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

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.logged_user = None

if 'navegacion' not in st.session_state:
    st.session_state.navegacion = "Inicio"

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


def opciones_autorizadas(rol):
    permisos = {
        "Visualizador": {"Inicio", "Consulta & Archivo", "Mi Perfil"},
        "Modificador": {"Inicio", "Entrada de Expedientes", "Consulta & Archivo", "Mi Perfil"},
        "Administrador": {
            "Inicio", "Entrada de Expedientes", "Consulta & Archivo",
            "Base Histórica", "Mi Perfil",
        },
        "Super Administrador": {
            "Inicio", "Entrada de Expedientes", "Consulta & Archivo",
            "Base Histórica", "Gestión de Permisos", "Mi Perfil",
        },
    }
    return permisos.get(rol, {"Inicio", "Mi Perfil"})

# --- FUNCIÓN DE RENDERIZADO ESTILO MENÚ DE WINDOWS ---
def render_win_app(col, img_path, titulo, destino_nav, key_prefix):
    with col:
        render_image_action(img_path, titulo, f"?nav={quote(destino_nav)}")

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
            
            has_token = os.path.exists(TOKEN_FILE)

            if has_token:
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

if not cuenta_activa(datos_usuario):
    if cuenta_bloqueada(datos_usuario):
        st.error("Esta cuenta está bloqueada. Comuníquese con un administrador.")
    else:
        st.warning("Su cuenta está pendiente de aprobación. Un administrador debe asignarle un rol y activarla.")
    if st.button("Volver al inicio de sesión"):
        cerrar_sesion()
    st.stop()

rol_actual = datos_usuario.get("rol", "Sin Rol Asignado")
estado_actual = datos_usuario.get("estado", "Pendiente")

es_admin = rol_actual in ["Super Administrador", "Administrador"]
es_modificador = rol_actual in ["Super Administrador", "Administrador", "Modificador"]
es_super_admin = rol_actual == "Super Administrador"
puede_abrir_google = es_modificador

opciones_permitidas = opciones_autorizadas(rol_actual)
if st.session_state.navegacion not in opciones_permitidas:
    st.session_state.navegacion = "Inicio"
opciones_menu = [
    opcion for opcion in [
        "Inicio", "Entrada de Expedientes", "Consulta & Archivo",
        "Base Histórica", "Gestión de Permisos", "Mi Perfil",
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
    st.divider()
    for opc in opciones_menu:
        if opc in {"Google Drive", "Hoja Google Sheets"}:
            continue
        if st.button(opc, key=f"btn_side_{opc}", width="stretch"):
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
                f"sistema://open?url={quote(f'https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}', safe='')}&title=Google%20Drive",
            ),
            (
                IMG_CARD_SHEETS,
                "Google Sheets",
                f"sistema://open?url={quote(SHEET_URL, safe='')}&title=Google%20Sheets",
            ),
        ])
    if es_super_admin:
        mosaico.append((IMG_CARD_PERMISOS, "Gestión Permisos", f"?nav={quote('Gestión de Permisos')}"))
    mosaico.append((IMG_CARD_PERFIL, "Mi Perfil", f"?nav={quote('Mi Perfil')}"))
    render_launcher_grid(mosaico)

elif st.session_state.navegacion == "Entrada de Expedientes":
    if st.button("⬅️ Volver al Inicio"):
        st.session_state.navegacion = "Inicio"
        st.rerun()

    st.header("Entrada y Digitalización de Desvinculaciones")

    if not es_modificador:
        st.warning("Rol de Visualizador: Modo de solo lectura.")
    else:
        with st.form("form_registro_canvas"):
            f_col1, f_col2, f_col3 = st.columns(3)
            with f_col1:
                radicado_padre = st.text_input("Radicado Padre (Orfeo) *", placeholder="2026-ORFEO-00123").strip()
                solicitante = st.selectbox("Solicitante", ["Propietario", "Empresa"])
                fecha_solicitud = st.date_input("Fecha Solicitud", value=datetime.date.today())
            with f_col2:
                matricula_qx = st.text_input("Matrícula QX (Placa) *", placeholder="ABC123").strip().upper()
                qx_verificado = st.checkbox("QX verificado (propiedad)")
                num_resolucion = st.text_input("N° Resolución Administrativa").strip()
                fecha_resolucion = st.date_input("Fecha Resolución", value=None)
            with f_col3:
                tipo_notificacion = st.selectbox("Tipo de notificación", ["", "Citación", "Aviso", "Publicación"])
                fecha_notificacion = st.date_input("Fecha Notificación", value=None)
                fecha_ejecutoria = st.date_input("Fecha Constancia de Ejecutoria", value=None)
                remitido = st.checkbox("Remitido a Registro Automotor")
                fecha_remision = st.date_input("Fecha remisión a registro", value=None)
                notas = st.text_area("Notas", placeholder="Anotaciones adicionales del expediente")

            st.subheader("Cargar Páginas Escaneadas")
            archivos_canvas = st.file_uploader(
                "Subir archivos del expediente (PDF, PNG, JPG)",
                type=["pdf", "png", "jpg"],
                accept_multiple_files=True
            )

            btn_guardar = st.form_submit_button("Guardar y Sincronizar Datos", width="stretch")

        if btn_guardar:
            if not radicado_padre or not matricula_qx:
                st.error("El Radicado Padre y la Matrícula QX son obligatorios.")
            else:
                existente = st.session_state.db_expedientes.get(radicado_padre)
                if existente:
                    total_expedientes = existente.get("id") or siguiente_numero_expediente()
                    caja, folder, cod_ub = calcular_ubicacion(total_expedientes)
                else:
                    total_expedientes = siguiente_numero_expediente()
                    caja, folder, cod_ub = calcular_ubicacion(total_expedientes)

                canvas_list = []
                if archivos_canvas:
                    for idx, f in enumerate(archivos_canvas):
                        file_id, drive_url = None, None
                        if drive_service:
                            file_id, drive_url = subir_archivo_a_drive(
                                drive_service, f, f"{radicado_padre}_{f.name}", DRIVE_FOLDER_ID
                            )
                        canvas_list.append({
                            "pagina_id": idx + 1,
                            "nombre": f.name,
                            "tamano": f"{round(f.size / 1024, 1)} KB",
                            "drive_id": file_id,
                            "drive_url": drive_url
                        })

                registro_datos = {
                    "id": total_expedientes,
                    "radicado_padre": radicado_padre,
                    "placa": matricula_qx,
                    "solicitante": solicitante,
                    "fecha_solicitud": str(fecha_solicitud),
                    "fecha_minima": str(fecha_solicitud),
                    "qx_verificado": qx_verificado,
                    "resolucion": num_resolucion,
                    "fecha_resolucion": str(fecha_resolucion) if fecha_resolucion else "",
                    "tipo_notificacion": tipo_notificacion,
                    "fecha_notificacion": str(fecha_notificacion) if fecha_notificacion else "",
                    "fecha_ejecutoria": str(fecha_ejecutoria) if fecha_ejecutoria else "",
                    "remitido": remitido,
                    "fecha_remision_registro": str(fecha_remision) if fecha_remision else "",
                    "ubicacion": cod_ub,
                    "caja": caja,
                    "folder": folder,
                    "carpeta": total_expedientes,
                    "estado": "",
                    "canvas_paginas": canvas_list,
                    "drive_folder": f"https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}",
                    "modificado_por": datos_usuario["alias"],
                    "notas": notas.strip(),
                    "ultima_modificacion": str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                }
                registro_datos["estado"] = calcular_estado_tramite(registro_datos)

                st.session_state.db_expedientes[radicado_padre] = registro_datos
                guardar_local_json(st.session_state.db_expedientes)

                sheets_ok = False
                if sheets_service:
                    sheets_ok = guardar_registro_en_sheets(sheets_service, registro_datos)

                if sheets_ok:
                    st.success(f"Proceso guardado en Local, Drive y Google Sheets. Ubicación: **{cod_ub}**")
                else:
                    st.warning("Guardado en archivo local y Drive. Falló la conexión con Google Sheets.")

elif st.session_state.navegacion == "Consulta & Archivo":
    if st.button("⬅️ Volver al Inicio"):
        st.session_state.navegacion = "Inicio"
        st.rerun()

    st.header("Consulta General de Expedientes")

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

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Ubicación Física", exp["ubicacion"])
        m2.metric("Estado Trámite", exp["estado"])
        m3.metric("Modificado Por", exp["modificado_por"])
        m4.metric("Última Edición", exp["ultima_modificacion"])
        st.divider()

        st.subheader("Documentos Digitalizados")
        paginas = exp.get("canvas_paginas", [])
        if not paginas:
            st.info("Este expediente no posee archivos adjuntos registrados localmente.")
        else:
            for p in paginas:
                cp1, cp2, cp3 = st.columns([3, 1.5, 1.5])
                cp1.write(f"Página {p['pagina_id']}: {p['nombre']} ({p['tamano']})")
                if p.get("drive_id") and drive_service:
                    if cp2.button("Ver documento", key=f"view_drive_{exp['radicado_padre']}_{p['pagina_id']}"):
                        try:
                            contenido = descargar_archivo_drive(drive_service, p["drive_id"])
                            with st.expander(f"Vista previa: {p['nombre']}", expanded=True):
                                mostrar_documento_en_aplicacion(contenido, p["nombre"])
                        except Exception as error:
                            st.error(f"No fue posible mostrar el documento: {error}")
                    if es_modificador:
                        try:
                            contenido_descarga = descargar_archivo_drive(drive_service, p["drive_id"])
                            cp3.download_button(
                                "Descargar",
                                data=contenido_descarga,
                                file_name=p["nombre"],
                                mime="application/pdf",
                                key=f"download_drive_{exp['radicado_padre']}_{p['pagina_id']}",
                            )
                        except Exception as error:
                            cp3.error(f"No disponible: {error}")
                else:
                    cp2.caption("Sin vista previa disponible")

                if es_modificador and st.button(
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
                paginas = exp.get("canvas_paginas", [])
                if not paginas:
                    st.caption("Este proceso no tiene documentos registrados.")
                    continue
                for p in paginas:
                    col_info, col_view, col_download = st.columns([3, 1, 1])
                    col_info.write(f"{p.get('nombre', 'Documento')} ({p.get('tamano', '')})")
                    if p.get("drive_id") and drive_service:
                        if col_view.button(
                            "Ver",
                            key=f"view_multi_{exp.get('radicado_padre')}_{p.get('pagina_id')}",
                        ):
                            try:
                                contenido = descargar_archivo_drive(drive_service, p["drive_id"])
                                with st.expander(
                                    f"Vista previa: {p.get('nombre', 'Documento')}",
                                    expanded=True,
                                ):
                                    mostrar_documento_en_aplicacion(
                                        contenido,
                                        p.get("nombre", "documento.pdf"),
                                    )
                            except Exception as error:
                                st.error(f"No fue posible mostrar el documento: {error}")
                        if es_modificador:
                            try:
                                contenido = descargar_archivo_drive(drive_service, p["drive_id"])
                                col_download.download_button(
                                    "Descargar",
                                    data=contenido,
                                    file_name=p.get("nombre", "documento.pdf"),
                                    mime="application/pdf",
                                    key=f"download_multi_{exp.get('radicado_padre')}_{p.get('pagina_id')}",
                                )
                            except Exception as error:
                                col_download.caption(f"No disponible: {error}")
    elif criterio:
        st.warning("No se encontró ningún expediente por ese radicado o placa.")

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
                st.dataframe(
                    pd.DataFrame(registros_historicos)[
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

                if st.form_submit_button("Guardar Permiso"):
                    st.session_state.usuarios[email]["rol"] = nuevo_rol
                    st.session_state.usuarios[email]["estado"] = nuevo_estado
                    guardar_local_json(st.session_state.db_expedientes)
                    st.success("Permisos guardados.")
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
    * **Autenticación:** `{datos_usuario.get('metodo', 'Google / Local')}`
    * **Registrado:** `{datos_usuario.get('fecha_registro', '2026-01-01')}`
    """)

    st.divider()

    if st.button("Cerrar Sesión del Sistema", width="stretch"):
        cerrar_sesion()