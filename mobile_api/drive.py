"""Google Drive operations for the mobile API."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Iterable
from datetime import date, datetime
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession
from google.auth.exceptions import GoogleAuthError
from requests.exceptions import RequestException

from .expedientes import _google_get, _google_session


DRIVE_API_URL = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
MAX_PDF_BYTES = 50 * 1024 * 1024

DOCUMENT_FOLDERS = {
    "solicitud": "peticion",
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
    "resolución del recurso": "resolucion resuelve",
    "constancia de ejecutoria": "constancia de ejecutoria",
    "remisión a registro": "remision",
    "desistimiento": "desistimiento",
    "otro": "Otro",
}


def _quote_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _drive_error(response, action: str) -> None:
    if response.status_code in (401, 403):
        raise RuntimeError(
            "Google rechazó el acceso a Drive. Vuelve a autorizar la cuenta "
            "propietaria con el permiso de Drive y verifica la carpeta configurada."
        )
    if response.status_code >= 400:
        raise RuntimeError(f"No fue posible {action} en Google Drive (HTTP {response.status_code}).")


def _request_json(session: AuthorizedSession, method: str, url: str, action: str, **kwargs) -> dict:
    try:
        response = session.request(method, url, timeout=60, **kwargs)
    except GoogleAuthError as error:
        raise RuntimeError(
            "La autorización de Google venció o fue revocada. Vuelve a autorizar "
            "la cuenta propietaria."
        ) from error
    except RequestException as error:
        raise RuntimeError(f"No fue posible conectar con Google Drive para {action}.") from error
    _drive_error(response, action)
    try:
        return response.json() if response.content else {}
    except ValueError as error:
        raise RuntimeError(f"Google Drive devolvió una respuesta inválida al {action}.") from error


def _list_children(session: AuthorizedSession, parent_id: str) -> list[dict]:
    result: list[dict] = []
    page_token = None
    while True:
        params = {
            "q": f"'{_quote_query(parent_id)}' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,parents,webViewLink,appProperties,size)",
            "pageSize": 1000,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        page = _google_get(session, f"{DRIVE_API_URL}/files", params=params)
        result.extend(page.get("files", []))
        page_token = page.get("nextPageToken")
        if not page_token:
            return result


def _find_child(session: AuthorizedSession, parent_id: str, name: str) -> dict | None:
    escaped_name = _quote_query(name)
    page = _google_get(
        session,
        f"{DRIVE_API_URL}/files",
        params={
            "q": (
                f"'{_quote_query(parent_id)}' in parents and trashed = false "
                f"and name = '{escaped_name}'"
            ),
            "fields": "files(id,name,mimeType,parents,webViewLink,appProperties)",
            "pageSize": 100,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
    )
    return next(iter(page.get("files", [])), None)


def _ensure_folder(session: AuthorizedSession, parent_id: str, name: str) -> str:
    existing = _find_child(session, parent_id, name)
    if existing:
        if existing.get("mimeType") != FOLDER_MIME_TYPE:
            raise RuntimeError(f"Drive ya contiene un archivo llamado «{name}» en la ruta esperada.")
        return str(existing["id"])
    folder = _request_json(
        session,
        "POST",
        f"{DRIVE_API_URL}/files",
        "crear una carpeta",
        params={"fields": "id,name,mimeType,parents"},
        json={
            "name": name,
            "mimeType": FOLDER_MIME_TYPE,
            "parents": [parent_id],
        },
    )
    folder_id = str(folder.get("id") or "")
    if not folder_id:
        raise RuntimeError(f"Google Drive no devolvió el identificador de la carpeta «{name}».")
    return folder_id


def _documents_root(session: AuthorizedSession) -> str:
    configured_id = os.environ.get(
        "SISTEMA_DRIVE_FOLDER_ID",
        "1vwsw0RKXsoYYqXwhH2OZPaD-BrTiUUyl",
    ).strip()
    if not configured_id:
        raise RuntimeError("SISTEMA_DRIVE_FOLDER_ID debe señalar la carpeta raíz de Drive.")
    metadata = _google_get(
        session,
        f"{DRIVE_API_URL}/files/{quote(configured_id, safe='')}",
        params={"fields": "id,name,mimeType,parents"},
    )
    name = str(metadata.get("name") or "").strip().casefold()
    if metadata.get("mimeType") != FOLDER_MIME_TYPE:
        raise RuntimeError("La ruta configurada de Google Drive no es una carpeta.")
    if name == "pdfs escaneados":
        return configured_id
    root = _find_child(session, configured_id, "PDFS Escaneados")
    if not root:
        raise RuntimeError(
            "La carpeta configurada no es «PDFS Escaneados» ni contiene esa "
            "carpeta. No se creó una estructura alternativa."
        )
    if root.get("mimeType") != FOLDER_MIME_TYPE:
        raise RuntimeError("El elemento «PDFS Escaneados» de Drive no es una carpeta.")
    return str(root["id"])


def _safe_name(value: str, fallback: str) -> str:
    token = re.sub(r"[^A-Za-z0-9ÁÉÍÓÚáéíóúÑñÜü-]+", "-", str(value or "").strip())
    token = re.sub(r"-+", "-", token).strip("-")
    return token or fallback


def normalizar_fecha(valor: str) -> str:
    try:
        return date.fromisoformat(str(valor or "").strip()).isoformat()
    except ValueError:
        try:
            return datetime.strptime(str(valor).strip(), "%d/%m/%Y").date().isoformat()
        except ValueError as error:
            raise ValueError("La fecha de solicitud debe usar AAAA-MM-DD o DD/MM/AAAA.") from error


def _request_folder(session: AuthorizedSession) -> str:
    return _ensure_folder(session, _documents_root(session), "Pendientes")


def expediente_folder(
    session: AuthorizedSession,
    radicado: str,
    placa: str,
    fecha: str,
    ubicacion: str = "",
) -> tuple[str, str]:
    from document_rules import nombre_carpeta_expediente

    root = _documents_root(session)
    fecha = normalizar_fecha(fecha)
    year = fecha[:4]
    annual_folder = _ensure_folder(session, root, year)
    name = nombre_carpeta_expediente(radicado, placa, fecha, ubicacion)
    return _ensure_folder(session, annual_folder, name), name


def find_expediente_folder(
    session: AuthorizedSession,
    radicado: str,
    placa: str,
    fecha: str,
    ubicacion: str = "",
) -> str | None:
    from document_rules import nombre_carpeta_expediente

    fecha = normalizar_fecha(fecha)
    year = fecha[:4]
    annual_folder = _find_child(session, _documents_root(session), year)
    if not annual_folder:
        return None
    name = nombre_carpeta_expediente(radicado, placa, fecha, ubicacion)
    folder = _find_child(session, str(annual_folder["id"]), name)
    if not folder:
        return None
    if folder.get("mimeType") != FOLDER_MIME_TYPE:
        raise RuntimeError(f"El elemento «{name}» de Drive no es una carpeta.")
    return str(folder["id"])


def pending_document_folder(
    session: AuthorizedSession,
    radicado: str,
    placa: str,
    fecha: str,
    is_unlinked_complement: bool = False,
    batch_id: str = "",
) -> str:
    pending = _request_folder(session)
    if is_unlinked_complement:
        unlinked = _ensure_folder(session, pending, "Por_vincular")
        plate_folder = _ensure_folder(
            session,
            unlinked,
            _safe_name(placa, "PLACA_SIN_IDENTIFICAR"),
        )
        if batch_id:
            return _ensure_folder(session, plate_folder, f"COMPLEMENTO_{batch_id}")
        return plate_folder
    from document_rules import nombre_carpeta_expediente

    name = nombre_carpeta_expediente(radicado, placa, fecha, "")
    return _ensure_folder(session, pending, name)


def document_folder(session: AuthorizedSession, parent_id: str, document_type: str) -> str:
    name = DOCUMENT_FOLDERS.get(document_type.strip().casefold(), "Otro")
    return _ensure_folder(session, parent_id, name)


def upload_pdf(
    session: AuthorizedSession,
    parent_id: str,
    filename: str,
    content: bytes,
    document_type: str,
    source_filename: str = "",
    source_pages: list[int] | None = None,
    pending_batch_id: str = "",
    suggested_case: str = "",
) -> dict:
    if not content or len(content) > MAX_PDF_BYTES:
        raise ValueError("El PDF debe tener entre 1 byte y 50 MB.")
    fingerprint = hashlib.sha256(content).hexdigest()
    existing = _google_get(
        session,
        f"{DRIVE_API_URL}/files",
        params={
            "q": (
                f"'{_quote_query(parent_id)}' in parents and trashed = false "
                "and appProperties has { "
                f"key='sha256' and value='{fingerprint}'"
                " }"
            ),
            "fields": "files(id,name,mimeType,parents,webViewLink,appProperties)",
            "pageSize": 10,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
    )
    if existing.get("files"):
        return {**existing["files"][0], "duplicate": True}

    boundary = f"mobile-api-{uuid.uuid4().hex}"
    app_properties = {"sha256": fingerprint, "documentType": document_type}
    if source_filename:
        app_properties["sourceFileName"] = source_filename[:120]
    if source_pages:
        app_properties["sourcePages"] = f"{source_pages[0]}-{source_pages[-1]}"
    if pending_batch_id:
        app_properties["pendingBatchId"] = pending_batch_id
    if suggested_case in {"Con recurso", "Sin recurso", "Desistimiento"}:
        app_properties["suggestedCase"] = suggested_case
    metadata = {
        "name": filename,
        "mimeType": "application/pdf",
        "parents": [parent_id],
        "appProperties": app_properties,
    }
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata, ensure_ascii=False)}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8") + content + f"\r\n--{boundary}--".encode("ascii")
    return _request_json(
        session,
        "POST",
        DRIVE_UPLOAD_URL,
        "guardar el PDF",
        params={
            "uploadType": "multipart",
            "fields": "id,name,mimeType,parents,webViewLink,appProperties",
            "supportsAllDrives": "true",
        },
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
        data=body,
    )


def checklist(session: AuthorizedSession, folder_id: str) -> dict:
    from document_rules import clasificar_tipo_documento

    folders = _list_children(session, folder_id)
    present: set[str] = set()
    documents: list[dict] = []
    for folder in folders:
        if folder.get("mimeType") != FOLDER_MIME_TYPE:
            continue
        items = _list_children(session, str(folder["id"]))
        for item in items:
            if item.get("mimeType") == FOLDER_MIME_TYPE:
                continue
            kind = str((item.get("appProperties") or {}).get("documentType") or "")
            if not kind:
                kind = clasificar_tipo_documento(str(item.get("name") or ""), "Otro")
            present.add(kind)
            documents.append(
                {
                    "id": item.get("id"),
                    "nombre": item.get("name", ""),
                    "tipo_documento": kind,
                    "url": item.get("webViewLink", ""),
                    "archivo_origen": (item.get("appProperties") or {}).get("sourceFileName", ""),
                    "paginas_origen": (item.get("appProperties") or {}).get("sourcePages", ""),
                }
            )
    return {"presentes": sorted(present), "documentos": documents}


def listar_complementos_pendientes(
    session: AuthorizedSession,
    placa: str,
) -> list[dict]:
    pending = _find_child(session, _documents_root(session), "Pendientes")
    if not pending:
        return []
    unlinked = _find_child(session, str(pending["id"]), "Por_vincular")
    if not unlinked:
        return []
    plate = _find_child(
        session,
        str(unlinked["id"]),
        _safe_name(placa, "PLACA_SIN_IDENTIFICAR"),
    )
    if not plate:
        return []
    batches = []
    for batch in _list_children(session, str(plate["id"])):
        if batch.get("mimeType") != FOLDER_MIME_TYPE:
            continue
        files = []
        for item in _list_children(session, str(batch["id"])):
            if item.get("mimeType") == FOLDER_MIME_TYPE:
                files.extend(_list_children(session, str(item["id"])))
            else:
                files.append(item)
        suggested_case = next(
            (
                str((item.get("appProperties") or {}).get("suggestedCase") or "")
                for item in files
                if (item.get("appProperties") or {}).get("suggestedCase")
            ),
            "",
        )
        batches.append(
            {
                "id": str(batch["id"]),
                "nombre": str(batch.get("name") or ""),
                "clasificacion_sugerida": suggested_case,
                "archivos": [
                    {
                        "id": item.get("id"),
                        "nombre": item.get("name", ""),
                        "tipo_documento": (item.get("appProperties") or {}).get(
                            "documentType",
                            "Otro",
                        ),
                    }
                    for item in files
                    if item.get("mimeType") != FOLDER_MIME_TYPE
                ],
            }
        )
    return batches


def _move_file(
    session: AuthorizedSession,
    file_id: str,
    destination_id: str,
    action: str,
) -> None:
    metadata = _google_get(
        session,
        f"{DRIVE_API_URL}/files/{quote(file_id, safe='')}",
        params={"fields": "id,parents", "supportsAllDrives": "true"},
    )
    parents = [str(parent) for parent in metadata.get("parents", [])]
    if destination_id in parents:
        return
    _request_json(
        session,
        "PATCH",
        f"{DRIVE_API_URL}/files/{quote(file_id, safe='')}",
        action,
        params={
            "addParents": destination_id,
            "removeParents": ",".join(parents),
            "fields": "id,parents",
            "supportsAllDrives": "true",
        },
    )


def vincular_complemento_pendiente(
    session: AuthorizedSession,
    placa: str,
    batch_id: str,
    target_folder_id: str,
) -> dict:
    batches = listar_complementos_pendientes(session, placa)
    batch = next((entry for entry in batches if entry["id"] == batch_id), None)
    if not batch:
        raise LookupError("No se encontró el complemento pendiente para esa placa.")
    pending_root = _find_child(session, _documents_root(session), "Pendientes")
    unlinked = _find_child(session, str(pending_root["id"]), "Por_vincular")
    plate = _find_child(
        session,
        str(unlinked["id"]),
        _safe_name(placa, "PLACA_SIN_IDENTIFICAR"),
    )
    batch_folder = _find_child(session, str(plate["id"]), batch["nombre"])
    if not batch_folder or str(batch_folder["id"]) != batch_id:
        raise RuntimeError("La carpeta temporal del complemento cambió durante la vinculación.")

    files_to_move = []
    for item in _list_children(session, batch_id):
        if item.get("mimeType") != FOLDER_MIME_TYPE:
            files_to_move.append((item, target_folder_id))
            continue
        destination = document_folder(
            session,
            target_folder_id,
            _find_batch_type(session, str(item["id"])),
        )
        for child in _list_children(session, str(item["id"])):
            if child.get("mimeType") != FOLDER_MIME_TYPE:
                files_to_move.append((child, destination))

    moved = 0
    try:
        for item, destination in files_to_move:
            _move_file(session, str(item["id"]), destination, "vincular el complemento")
            moved += 1
    except RuntimeError as error:
        raise RuntimeError(
            f"Drive vinculó {moved} de {len(files_to_move)} archivos antes de fallar. "
            "Revisa el checklist del expediente y vuelve a intentar para completar."
        ) from error
    return {
        "archivos_vinculados": moved,
        "batch_id": batch_id,
        "clasificacion_sugerida": batch.get("clasificacion_sugerida", ""),
    }


def _find_batch_type(session: AuthorizedSession, folder_id: str) -> str:
    files = _list_children(session, folder_id)
    types = {
        str((item.get("appProperties") or {}).get("documentType") or "Otro")
        for item in files
        if item.get("mimeType") != FOLDER_MIME_TYPE
    }
    if len(types) > 1:
        raise RuntimeError("La carpeta temporal mezcla tipos documentales y no se moverá.")
    return next(iter(types), "Otro")


def listar_raiz_documental() -> Iterable[dict]:
    session = _google_session(required_scopes={DRIVE_SCOPE})
    return _list_children(session, _documents_root(session))
