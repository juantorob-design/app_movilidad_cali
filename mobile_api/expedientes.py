"""
Expediente listing, searching, and management for the mobile API.
Reutiliza funciones de app_6.py sin duplicar lógica ni introducir dependencias de Streamlit.
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Any
from urllib.parse import quote

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from requests.exceptions import RequestException


DEFAULT_SPREADSHEET_ID = "1oQ5GnxSj4_gGA-p2NjlN3o0uDOLaIELZu4gpohLK6Uo"
SPREADSHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
OWNER_INFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
SHEETS_API_URL = "https://sheets.googleapis.com/v4/spreadsheets"
FIELDS_TO_SHEET_COLUMNS = {
    "radicado_padre": ("RAD PADRE", "RADICADO PADRE"),
    "fecha_solicitud": ("FECHA SOLICITUD", "FECHA"),
    "placa": ("PLACA",),
    "empresa": ("EMPRESA",),
    "nit_empresa": ("NIT", "NIT EMPRESA"),
    "propietario": ("PROPIETARIO",),
    "cedula_propietario": ("CEDULA", "CEDULA PROPIETARIO"),
    "direccion_empresa": ("DIRECCION EMPRESA",),
    "direccion_propietario": ("DIRECCION PROPIETARIO",),
    "solicitante": ("SOLICITANTE",),
    "resolucion": ("RESOLUCION DESVINCULACION", "RESOLUCION"),
    "fecha_resolucion": ("FECHA DESVINCULACION", "FECHA RESOLUCION"),
    "requerimiento": ("REQUERIMIENTO",),
    "desistimiento": ("DESISTIMIENTO",),
    "tipo_notificacion": ("TIPO NOTIFICACION",),
    "fecha_notificacion": ("FECHA NOTIFICACION",),
    "recurso": ("RECURSO",),
    "fecha_recurso": ("FECHA RECURSO",),
    "resolucion_recurso": ("RESOLUCION RECURSO", "RESOLUCION DEL RECURSO"),
    "fecha_resolucion_recurso": (
        "FECHA RESOLUCION RECURSO",
        "FECHA RESOLUCION DEL RECURSO",
    ),
    "fecha_ejecutoria": ("FECHA EJECUTORIA",),
    "fecha_remision_registro": ("FECHA REMISION REGISTRO",),
    "qx_verificado": ("QX VERIFICADO",),
    "remitido": ("REMITIDO",),
    "estado": ("ESTADO",),
    "caso": ("TIPO CASO", "CASO"),
    "ubicacion": ("UBICACION FISICA", "UBICACION"),
    "caja": ("CAJA",),
    "observaciones": ("OBSERVACIONES", "OBSERVACION"),
    "drive_folder": ("DRIVE FOLDER",),
    "documentos_drive": ("DOCUMENTOS DRIVE",),
    "pdf_unificado": ("PDF UNIFICADO",),
    "documentos_faltantes_drive": ("DOCUMENTOS FALTANTES",),
    "contenido_documental": ("CONTENIDO DOCUMENTAL",),
}


def normalizar_campo(valor: str) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(char for char in texto if not unicodedata.combining(char))
    texto = texto.replace("�", "O").replace("_", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", texto.upper())).strip()


def _google_session(
    required_scopes: set[str] | None = None,
) -> AuthorizedSession:
    token_path = os.environ.get("SISTEMA_GOOGLE_TOKEN_FILE", "").strip()
    if not token_path:
        raise RuntimeError(
            "SISTEMA_GOOGLE_TOKEN_FILE debe apuntar al token Google del programa."
        )
    if not os.path.isfile(token_path):
        raise RuntimeError(
            "No existe token.json. Inicia sesión en el programa de escritorio "
            "con la cuenta propietaria para habilitar la lectura móvil."
        )
    try:
        credentials = Credentials.from_authorized_user_file(token_path)
    except (OSError, ValueError) as error:
        raise RuntimeError("token.json no tiene un formato OAuth válido.") from error
    required = required_scopes or {SPREADSHEETS_SCOPE}
    missing = required.difference(credentials.scopes or ())
    if missing:
        service = "Drive" if any("drive" in scope for scope in missing) else "Google Sheets"
        raise RuntimeError(
            f"La cuenta Google autorizada no tiene todos los permisos de {service}. "
            "Vuelve a autorizar el programa con los permisos solicitados."
        )
    return AuthorizedSession(credentials)


def google_session_for_owner(
    required_scopes: set[str] | None = None,
) -> AuthorizedSession:
    owner_email = os.environ.get("SISTEMA_WEB_OWNER_EMAIL", "").strip().casefold()
    if not owner_email or "@" not in owner_email:
        raise RuntimeError("SISTEMA_WEB_OWNER_EMAIL debe identificar al propietario de la hoja.")
    session = _google_session(required_scopes)
    identity = _google_get(session, OWNER_INFO_URL)
    account_email = str(identity.get("email") or "").strip().casefold()
    if not account_email or account_email != owner_email:
        raise RuntimeError(
            "token.json no pertenece a la cuenta indicada en SISTEMA_WEB_OWNER_EMAIL."
        )
    return session


def _google_get(session: AuthorizedSession, url: str, **kwargs) -> dict:
    try:
        response = session.get(url, timeout=20, **kwargs)
    except GoogleAuthError as error:
        raise RuntimeError(
            "La autorización de Google del programa venció o fue revocada. "
            "Vuelve a autorizar la cuenta propietaria."
        ) from error
    except RequestException as error:
        raise RuntimeError("No fue posible conectar con las API de Google.") from error
    if response.status_code in (401, 403):
        raise RuntimeError(
            "Google rechazó la cuenta del programa. Vuelve a autorizar el acceso "
            "a Sheets y verifica que la cuenta pueda abrir la hoja configurada."
        )
    if not response.ok:
        raise RuntimeError(
            f"La API de Google respondió con HTTP {response.status_code}."
        )
    try:
        return response.json()
    except ValueError as error:
        raise RuntimeError("La respuesta de Google no tiene un formato válido.") from error


def _sheet_title(session: AuthorizedSession, spreadsheet_id: str) -> str:
    metadata = _google_get(
        session,
        f"{SHEETS_API_URL}/{spreadsheet_id}",
        params={"fields": "sheets.properties.title"},
    )
    titles = [
        str(sheet.get("properties", {}).get("title", "")).strip()
        for sheet in metadata.get("sheets", [])
    ]
    by_normalized_title = {normalizar_campo(title): title for title in titles if title}
    for candidate in ("TABLA 2", "BD DESV"):
        if candidate in by_normalized_title:
            return by_normalized_title[candidate]
    raise RuntimeError(
        "La hoja configurada no contiene las pestañas tabla_2 o bd_desv."
    )


def _record_value(row: list, positions: dict[str, int], *names: str) -> str:
    for name in names:
        index = positions.get(normalizar_campo(name))
        if index is not None and index < len(row):
            value = str(row[index] or "").strip()
            if value:
                return value
    return ""


def _records_from_values(values: list[list]) -> dict[str, dict]:
    if not values:
        return {}
    headers = [normalizar_campo(value) for value in values[0]]
    positions = {header: index for index, header in enumerate(headers) if header}
    if "RAD PADRE" not in positions and "RADICADO PADRE" not in positions:
        raise RuntimeError("The Google worksheet is missing its parent-case number column.")

    records: dict[str, dict] = {}
    for row in values[1:]:
        radicado = _record_value(row, positions, "RAD PADRE", "RADICADO PADRE")
        if not radicado:
            continue
        placa = _record_value(row, positions, "PLACA").upper()
        if radicado.upper().startswith("PRUEBA-") or placa.startswith("TST"):
            raise RuntimeError(
                "Demo records were found in the Google worksheet; "
                "remove them before using the mobile API."
            )
        records[radicado] = {
            "radicado_padre": radicado,
            "fecha_solicitud": _record_value(row, positions, "FECHA SOLICITUD", "FECHA"),
            "placa": placa,
            "empresa": _record_value(row, positions, "EMPRESA"),
            "nit_empresa": _record_value(row, positions, "NIT"),
            "propietario": _record_value(row, positions, "PROPIETARIO"),
            "cedula_propietario": _record_value(row, positions, "CEDULA"),
            "direccion_empresa": _record_value(row, positions, "DIRECCION EMPRESA"),
            "direccion_propietario": _record_value(row, positions, "DIRECCION PROPIETARIO"),
            "solicitante": _record_value(row, positions, "SOLICITANTE"),
            "resolucion": _record_value(row, positions, "RESOLUCION DESVINCULACION", "RESOLUCION"),
            "fecha_resolucion": _record_value(row, positions, "FECHA DESVINCULACION"),
            "requerimiento": _record_value(row, positions, "REQUERIMIENTO"),
            "desistimiento": _record_value(row, positions, "DESISTIMIENTO"),
            "tipo_notificacion": _record_value(row, positions, "TIPO NOTIFICACION"),
            "fecha_notificacion": _record_value(row, positions, "FECHA NOTIFICACION"),
            "recurso": _record_value(row, positions, "RECURSO"),
            "fecha_recurso": _record_value(row, positions, "FECHA RECURSO"),
            "resolucion_recurso": _record_value(
                row,
                positions,
                "RESOLUCION RECURSO",
                "RESOLUCION DEL RECURSO",
            ),
            "fecha_resolucion_recurso": _record_value(
                row,
                positions,
                "FECHA RESOLUCION RECURSO",
                "FECHA RESOLUCION DEL RECURSO",
            ),
            "fecha_ejecutoria": _record_value(row, positions, "FECHA EJECUTORIA"),
            "fecha_remision_registro": _record_value(row, positions, "FECHA REMISION REGISTRO"),
            "qx_verificado": _record_value(row, positions, "QX VERIFICADO"),
            "remitido": _record_value(row, positions, "REMITIDO"),
            "estado": _record_value(row, positions, "ESTADO"),
            "caso": _record_value(row, positions, "TIPO CASO", "CASO"),
            "ubicacion": _record_value(row, positions, "UBICACION FISICA", "UBICACION"),
            "caja": _record_value(row, positions, "CAJA"),
            "observaciones": _record_value(row, positions, "OBSERVACIONES", "OBSERVACION"),
            "drive_folder": _record_value(row, positions, "DRIVE FOLDER"),
            "documentos_drive": _record_value(row, positions, "DOCUMENTOS DRIVE"),
            "pdf_unificado": _record_value(row, positions, "PDF UNIFICADO"),
            "documentos_faltantes_drive": _record_value(row, positions, "DOCUMENTOS FALTANTES"),
            "contenido_documental": _record_value(row, positions, "CONTENIDO DOCUMENTAL"),
        }
    return records


def cargar_expedientes_sheets() -> dict[str, dict]:
    """Lee la hoja operacional existente del sistema como fuente de verdad."""
    spreadsheet_id = os.environ.get(
        "SISTEMA_SPREADSHEET_ID",
        DEFAULT_SPREADSHEET_ID,
    ).strip()
    if not spreadsheet_id:
        raise RuntimeError(
            "SISTEMA_SPREADSHEET_ID debe identificar la hoja Google del programa."
        )
    session = google_session_for_owner()
    title = _sheet_title(session, spreadsheet_id)
    quoted_title = title.replace("'", "''")
    result = _google_get(
        session,
        f"{SHEETS_API_URL}/{spreadsheet_id}/values/{quoted_title}!A1:AZ2000",
        params={"valueRenderOption": "FORMATTED_VALUE"},
    )
    return _records_from_values(result.get("values", []))


def _spreadsheet_id() -> str:
    spreadsheet_id = os.environ.get(
        "SISTEMA_SPREADSHEET_ID",
        DEFAULT_SPREADSHEET_ID,
    ).strip()
    if not spreadsheet_id:
        raise RuntimeError(
            "SISTEMA_SPREADSHEET_ID debe identificar la hoja Google del programa."
        )
    return spreadsheet_id


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _write_sheet_values(
    session: AuthorizedSession,
    spreadsheet_id: str,
    range_name: str,
    values: list[list[str]],
    append: bool,
) -> dict:
    suffix = ":append" if append else ""
    params = {"valueInputOption": "RAW"}
    if append:
        params["insertDataOption"] = "INSERT_ROWS"
    url = (
        f"{SHEETS_API_URL}/{spreadsheet_id}/values/"
        f"{quote(range_name, safe='!:$')} {suffix}"
    ).replace(" ", "")
    try:
        response = session.post(
            url,
            params=params,
            json={"values": values},
            timeout=30,
        ) if append else session.put(
            url,
            params=params,
            json={"values": values},
            timeout=30,
        )
    except GoogleAuthError as error:
        raise RuntimeError(
            "La autorización de Google venció o fue revocada. Vuelve a autorizar "
            "la cuenta propietaria."
        ) from error
    except RequestException as error:
        raise RuntimeError("No fue posible conectar con Google Sheets para guardar.") from error
    if response.status_code in (401, 403):
        raise RuntimeError(
            "Google rechazó el permiso de escritura en Sheets. Vuelve a autorizar "
            "la cuenta propietaria."
        )
    if not response.ok:
        raise RuntimeError(f"Google Sheets rechazó el guardado (HTTP {response.status_code}).")
    try:
        return response.json()
    except ValueError as error:
        raise RuntimeError("Google Sheets devolvió una respuesta inválida al guardar.") from error


def _write_sheet_cells(
    session: AuthorizedSession,
    spreadsheet_id: str,
    updates: list[dict[str, Any]],
) -> dict:
    try:
        response = session.post(
            f"{SHEETS_API_URL}/{spreadsheet_id}/values:batchUpdate",
            json={"valueInputOption": "RAW", "data": updates},
            timeout=30,
        )
    except GoogleAuthError as error:
        raise RuntimeError(
            "La autorización de Google venció o fue revocada. Vuelve a autorizar "
            "la cuenta propietaria."
        ) from error
    except RequestException as error:
        raise RuntimeError("No fue posible conectar con Google Sheets para guardar.") from error
    if response.status_code in (401, 403):
        raise RuntimeError(
            "Google rechazó el permiso de escritura en Sheets. Vuelve a autorizar "
            "la cuenta propietaria."
        )
    if not response.ok:
        raise RuntimeError(f"Google Sheets rechazó el guardado (HTTP {response.status_code}).")
    try:
        return response.json()
    except ValueError as error:
        raise RuntimeError("Google Sheets devolvió una respuesta inválida al guardar.") from error


def guardar_expediente_sheets(
    expediente: dict[str, Any],
    radicado_existente: str | None = None,
    ignorar_columnas_faltantes: bool = False,
) -> dict[str, Any]:
    """Create a case or patch an existing row without modifying unrelated columns."""
    from datetime import date

    if not isinstance(expediente, dict):
        raise ValueError("Los datos del expediente deben ser un objeto.")
    unknown = set(expediente).difference(FIELDS_TO_SHEET_COLUMNS)
    if unknown:
        raise ValueError("El formulario contiene campos no permitidos.")
    data = {
        key: str(value).strip()
        for key, value in expediente.items()
        if key in FIELDS_TO_SHEET_COLUMNS and value is not None
    }
    radicado = data.get("radicado_padre", "").strip()
    if not radicado or len(radicado) > 100:
        raise ValueError("El radicado padre es obligatorio y no puede superar 100 caracteres.")
    if radicado_existente and radicado.casefold() != radicado_existente.strip().casefold():
        raise ValueError("El radicado padre de un expediente existente no se puede cambiar.")
    if not data.get("placa"):
        raise ValueError("La placa es obligatoria.")
    if not data.get("fecha_solicitud"):
        raise ValueError("La fecha de solicitud es obligatoria.")
    try:
        date.fromisoformat(data["fecha_solicitud"])
    except ValueError as error:
        raise ValueError("La fecha de solicitud debe usar el formato AAAA-MM-DD.") from error
    if data.get("caso") and data["caso"] not in {"Con recurso", "Sin recurso", "Desistimiento"}:
        raise ValueError("La clasificación debe ser Con recurso, Sin recurso o Desistimiento.")

    session = google_session_for_owner()
    spreadsheet_id = _spreadsheet_id()
    title = _sheet_title(session, spreadsheet_id)
    quoted_title = title.replace("'", "''")
    range_name = f"'{quoted_title}'!A1:AZ2000"
    result = _google_get(
        session,
        f"{SHEETS_API_URL}/{spreadsheet_id}/values/{quote(range_name, safe='!:$')}",
        params={"valueRenderOption": "FORMATTED_VALUE"},
    )
    rows = result.get("values", [])
    if not rows:
        raise RuntimeError("La pestaña operacional no tiene una fila de encabezados.")
    headers = [normalizar_campo(value) for value in rows[0]]
    positions: dict[str, list[int]] = {}
    for index, header in enumerate(headers):
        if header:
            positions.setdefault(header, []).append(index)
    radicado_positions = positions.get("RAD PADRE") or positions.get("RADICADO PADRE")
    if not radicado_positions:
        raise RuntimeError("La pestaña operacional no tiene la columna RAD PADRE.")

    matching_rows = [
        row_index
        for row_index, row in enumerate(rows[1:], start=2)
        if row and str(row[radicado_positions[0]] if len(row) > radicado_positions[0] else "")
        .strip()
        .casefold() == (radicado_existente or radicado).casefold()
    ]
    if len(matching_rows) > 1:
        raise RuntimeError("La hoja tiene radicados duplicados; se canceló el guardado.")
    if radicado_existente and not matching_rows:
        raise LookupError("No se encontró el expediente que se intenta actualizar.")
    if not radicado_existente and matching_rows:
        raise FileExistsError("Ya existe un expediente con ese radicado padre.")

    mapped_positions: dict[str, list[int]] = {}
    campos_no_guardados = []
    for field in data:
        matched_positions = [
            index
            for column in FIELDS_TO_SHEET_COLUMNS[field]
            for index in positions.get(normalizar_campo(column), [])
        ]
        if not matched_positions:
            if ignorar_columnas_faltantes and field not in {
                "radicado_padre",
                "fecha_solicitud",
                "placa",
            }:
                campos_no_guardados.append(field)
                continue
            raise RuntimeError(
                f"La pestaña operacional no contiene una columna para «{field}»."
            )
        mapped_positions[field] = matched_positions
    data = {field: value for field, value in data.items() if field in mapped_positions}

    if matching_rows:
        row_number = matching_rows[0]
        updates = [
            {
                "range": f"'{quoted_title}'!{_column_name(index + 1)}{row_number}",
                "values": [[data[field]]],
            }
            for field, indexes in mapped_positions.items()
            for index in indexes
        ]
        _write_sheet_cells(
            session,
            spreadsheet_id,
            updates,
        )
    else:
        row_width = max(
            len(headers),
            max((index + 1 for indexes in positions.values() for index in indexes), default=0),
        )
        row = [""] * row_width
        for field, value in data.items():
            for index in mapped_positions[field]:
                row[index] = value
        _write_sheet_values(
            session,
            spreadsheet_id,
            f"'{quoted_title}'!A:{_column_name(len(row))}",
            [row],
            append=True,
        )
    result_payload = {"radicado_padre": radicado, "expediente": data}
    if campos_no_guardados:
        result_payload["campos_no_guardados"] = campos_no_guardados
    return result_payload


def normalizar_criterio(criterio: str | None) -> str:
    """Normaliza un criterio de búsqueda: minúsculas, espacios, acentos simples."""
    if not criterio:
        return ""
    return str(criterio).lower().strip()


def buscar_expedientes(
    expedientes: dict[str, dict],
    campo: str,
    criterio: str,
) -> list[dict]:
    """
    Busca expedientes por un campo específico.
    Retorna lista de expedientes que coinciden, vacía si no hay coincidencias.
    """
    if not criterio or not campo:
        return []

    criterio_norm = normalizar_criterio(criterio)
    resultados = []

    for radicado, exp in expedientes.items():
        valor = str(exp.get(campo) or "").lower().strip()
        if criterio_norm in valor:
            resultados.append({**exp, "radicado_padre": radicado})

    return resultados


def obtener_expediente(
    expedientes: dict[str, dict],
    radicado_padre: str,
) -> dict[str, Any] | None:
    """Obtiene un expediente por radicado padre."""
    if not radicado_padre:
        return None
    exp = expedientes.get(radicado_padre)
    if exp:
        return {**exp, "radicado_padre": radicado_padre}
    return None


def extraer_resumen_expediente(expediente: dict, radicado: str = "") -> dict[str, Any]:
    """
    Extrae un resumen condensado del expediente para lista móvil.
    Incluye radicado, placa, fecha, propietario, estado y fecha_ultima_actualizacion.
    """
    return {
        "radicado_padre": radicado or expediente.get("radicado_padre", ""),
        "placa": expediente.get("placa", ""),
        "fecha_solicitud": expediente.get("fecha_solicitud", ""),
        "ubicacion": expediente.get("ubicacion", ""),
        "propietario": expediente.get("propietario", ""),
        "cedula_propietario": expediente.get("cedula_propietario", ""),
        "nit_empresa": expediente.get("nit_empresa", ""),
        "empresa": expediente.get("empresa", ""),
        "caso": expediente.get("caso", ""),
        "fecha_ultima_actualizacion": expediente.get("fecha_ultima_actualizacion", ""),
    }


def listar_expedientes_resumidos(expedientes: dict[str, dict]) -> list[dict]:
    """Retorna lista de resúmenes de expedientes, ordenada por fecha."""
    resumenes = [
        extraer_resumen_expediente(exp, radicado)
        for radicado, exp in expedientes.items()
    ]
    resumenes.sort(
        key=lambda x: x.get("fecha_solicitud") or "",
        reverse=True
    )
    return resumenes
