from __future__ import annotations

import os
import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .auth import MobileAuthenticationError, validar_identidad_google
from .documents import DOCUMENT_TYPES, separar_pdf, validar_pdf
from .drive import (
    DRIVE_SCOPE,
    checklist as drive_checklist,
    document_folder,
    expediente_folder,
    find_expediente_folder,
    listar_complementos_pendientes,
    normalizar_fecha,
    pending_document_folder,
    upload_pdf,
    vincular_complemento_pendiente,
)
from .expedientes import (
    cargar_expedientes_sheets,
    buscar_expedientes,
    google_session_for_owner,
    guardar_expediente_sheets,
    obtener_expediente,
    listar_expedientes_resumidos,
)
from . import shared_workspace

ADMIN_ROLES = {"Administrador", "Super Administrador"}
EDITOR_ROLES = {"Modificador", *ADMIN_ROLES}

app = FastAPI(
    title="Sistema de Desvinculaciones API",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> dict[str, str]:
    """Dependency: obtiene el usuario autenticado."""
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google sign-in is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        identity = validar_identidad_google(
            credentials.credentials,
            os.environ.get("SISTEMA_GOOGLE_WEB_CLIENT_ID", ""),
            os.environ.get("SISTEMA_WEB_OWNER_EMAIL", ""),
        )
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google authentication is not configured on the server.",
        ) from error
    except MobileAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account is not authorized.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    try:
        profile = shared_workspace.obtener_perfil(identity["email"])
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The shared user directory is unavailable.",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account is not authorized.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    if not profile or profile.get("status") != "Activo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta no está activa. Solicita aprobación al administrador.",
        )
    role = str(profile.get("role") or "")
    if role not in shared_workspace.ROLES or role == "Sin Rol Asignado":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta no tiene un rol autorizado para usar la aplicación.",
        )
    identity.update(
        {
            "role": role,
            "status": "Activo",
            "download_allowed": bool(profile.get("download_allowed")),
            "download_requested": bool(profile.get("download_requested")),
        }
    )
    return identity


def _require_roles(user: dict[str, str], allowed_roles: set[str]) -> None:
    if user.get("role") not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu rol no tiene permiso para realizar esta operación.",
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def cargar_expedientes_configurados() -> dict:
    try:
        return cargar_expedientes_sheets()
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error


def _raise_operation_error(error: Exception) -> None:
    if isinstance(error, FileExistsError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if isinstance(error, LookupError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    if isinstance(error, ValueError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    if isinstance(error, RuntimeError):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    raise error


def _find_case(records: dict[str, dict], radicado: str) -> dict | None:
    return next(
        (
            case
            for key, case in records.items()
            if key.casefold() == radicado.strip().casefold()
        ),
        None,
    )


@app.get("/api/v1/me")
def current_user_endpoint(
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict[str, str]:
    return user


@app.get("/api/v1/workspace/profiles")
def listar_perfiles_compartidos(
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict:
    _require_roles(user, ADMIN_ROLES)
    try:
        profiles = shared_workspace.listar_perfiles()
    except (ValueError, RuntimeError) as error:
        _raise_operation_error(error)
    return {"perfiles": profiles, "total": len(profiles)}


@app.patch("/api/v1/workspace/profiles")
def actualizar_perfil_compartido(
    payload: dict,
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict[str, str]:
    if set(payload) != {"email", "role", "status", "download_allowed"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El perfil debe incluir correo, rol, estado y permiso de descarga.",
        )
    if not isinstance(payload.get("download_allowed"), bool):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El permiso de descarga debe ser booleano.",
        )
    _require_roles(user, ADMIN_ROLES)
    try:
        shared_workspace.actualizar_perfil(
            str(payload["email"]),
            str(payload["role"]),
            str(payload["status"]),
            payload["download_allowed"],
        )
    except (ValueError, RuntimeError) as error:
        _raise_operation_error(error)
    return {"status": "updated"}


@app.get("/api/v1/workspace/messages")
def listar_mensajes_compartidos(
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict:
    try:
        messages = shared_workspace.listar_mensajes(
            user["email"],
            can_manage=user.get("role") in ADMIN_ROLES,
        )
    except (ValueError, RuntimeError) as error:
        _raise_operation_error(error)
    return {"mensajes": messages, "total": len(messages)}


@app.post("/api/v1/workspace/messages", status_code=status.HTTP_201_CREATED)
def crear_mensaje_compartido(
    payload: dict,
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict:
    if (
        not set(payload).issubset({"subject", "message"})
        or not isinstance(payload.get("message"), str)
        or ("subject" in payload and not isinstance(payload["subject"], str))
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El mensaje debe incluir un asunto de texto y un contenido de texto.",
        )
    try:
        message = shared_workspace.crear_mensaje(
            user["email"],
            payload.get("subject", ""),
            payload["message"],
        )
    except (ValueError, RuntimeError) as error:
        _raise_operation_error(error)
    return {"mensaje": message}


@app.patch("/api/v1/workspace/messages/{message_id}/read")
def marcar_mensaje_compartido_leido(
    message_id: str,
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict[str, str]:
    _require_roles(user, ADMIN_ROLES)
    try:
        shared_workspace.marcar_mensaje_leido(message_id)
    except (ValueError, RuntimeError) as error:
        _raise_operation_error(error)
    return {"status": "read"}


@app.post("/api/v1/workspace/profiles/me/download-request")
def solicitar_permiso_descarga(
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict[str, str]:
    if user.get("role") != "Visualizador" or user.get("download_allowed"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu perfil no puede solicitar este permiso de descarga.",
        )
    try:
        shared_workspace.solicitar_permiso_descarga(user["email"])
    except (ValueError, RuntimeError) as error:
        _raise_operation_error(error)
    return {"status": "requested"}


@app.get("/api/v1/expedientes")
def listar_expedientes(
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict:
    """Lista todos los expedientes disponibles."""
    expedientes = cargar_expedientes_configurados()
    return {
        "expedientes": listar_expedientes_resumidos(expedientes),
        "total": len(expedientes),
    }


@app.get("/api/v1/expedientes/buscar")
def buscar_expedientes_endpoint(
    user: Annotated[dict[str, str], Depends(get_current_user)],
    q: str,
    campo: str = "radicado_padre",
) -> dict:
    """Busca expedientes por criterio."""
    if not q:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parámetro 'q' es requerido.",
        )
    expedientes = cargar_expedientes_configurados()
    resultados = buscar_expedientes(expedientes, campo, q)
    return {
        "criterio": q,
        "campo": campo,
        "expedientes": [
            {**exp, "radicado_padre": exp.get("radicado_padre", "")}
            for exp in resultados[:50]
        ],
        "total": len(resultados),
    }


@app.get("/api/v1/expedientes/{radicado}")
def obtener_expediente_endpoint(
    radicado: str,
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict:
    """Obtiene los detalles de un expediente."""
    if not radicado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Radicado es requerido.",
        )
    expedientes = cargar_expedientes_configurados()
    exp = obtener_expediente(expedientes, radicado)
    if not exp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expediente no encontrado.",
        )
    return {"expediente": exp}


@app.post("/api/v1/expedientes", status_code=status.HTTP_201_CREATED)
def crear_expediente(
    payload: dict,
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict:
    _require_roles(user, EDITOR_ROLES)
    try:
        return guardar_expediente_sheets(payload)
    except (FileExistsError, LookupError, ValueError, RuntimeError) as error:
        _raise_operation_error(error)


@app.put("/api/v1/expedientes/{radicado}")
def actualizar_expediente(
    radicado: str,
    payload: dict,
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict:
    _require_roles(user, EDITOR_ROLES)
    if str(payload.get("radicado_padre", radicado)).strip().casefold() != radicado.strip().casefold():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El radicado padre de un expediente existente no se puede cambiar.",
        )
    try:
        return guardar_expediente_sheets(payload, radicado_existente=radicado)
    except (FileExistsError, LookupError, ValueError, RuntimeError) as error:
        _raise_operation_error(error)


@app.post("/api/v1/expedientes/{radicado}/upload-pdf")
def subir_pdf_expediente(
    radicado: str,
    user: Annotated[dict[str, str], Depends(get_current_user)],
    archivo: UploadFile = File(...),
    tipo_documento: str = Form(default="Otro"),
    placa_complemento: str = Form(default=""),
    complemento_sin_vincular: bool = Form(default=False),
) -> dict:
    _require_roles(user, EDITOR_ROLES)
    if tipo_documento not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El tipo documental seleccionado no es válido.",
        )
    try:
        content = archivo.file.read(50 * 1024 * 1024 + 1)
        valid, detail = validar_pdf(content)
        if not valid:
            raise ValueError(detail)
        if len(content) > 50 * 1024 * 1024:
            raise ValueError("El PDF supera el tamaño máximo de 50 MB.")
        separated = separar_pdf(content, tipo_documento)
        suggested_case = str(separated.get("clasificacion_final") or "")

        cases = cargar_expedientes_configurados()
        case = _find_case(cases, radicado)
        if case is None and not complemento_sin_vincular:
            raise LookupError(
                "No existe ese expediente. Los complementos sin expediente deben "
                "marcarse como pendientes de vinculación."
            )
        if case is not None and complemento_sin_vincular:
            complemento_sin_vincular = False

        placa = (
            str(case.get("placa") or "").strip()
            if case
            else placa_complemento.strip().upper()
        )
        fecha = str(case.get("fecha_solicitud") or "").strip() if case else ""
        if not placa:
            raise ValueError("La placa es obligatoria para guardar el PDF.")

        session = google_session_for_owner({DRIVE_SCOPE})
        if case:
            folder_id, _ = expediente_folder(
                session,
                str(case["radicado_padre"]),
                placa,
                fecha,
                str(case.get("ubicacion") or ""),
            )
            file_stem = f"{case['radicado_padre']}_{placa}_{normalizar_fecha(fecha)}"
            full_name = f"{file_stem}.pdf"
            parent_radicado = str(case["radicado_padre"])
        else:
            batch_id = uuid.uuid4().hex[:12]
            folder_id = pending_document_folder(
                session,
                radicado,
                placa,
                "",
                is_unlinked_complement=True,
                batch_id=batch_id,
            )
            file_stem = f"PENDIENTE_{placa}"
            full_name = f"COMPLEMENTO_{placa}_Pendiente.pdf"
            parent_radicado = "PENDIENTE"
        if case:
            batch_id = ""

        full_pdf = upload_pdf(
            session,
            folder_id,
            full_name,
            content,
            "Expediente completo",
            pending_batch_id=batch_id,
            suggested_case=suggested_case,
        )
        blocks = []
        for index, block in enumerate(separated["bloques"], start=1):
            kind = block["tipo_documento"]
            target_folder = document_folder(session, folder_id, kind)
            safe_kind = "".join(
                character if character.isalnum() or character in "-_" else "_"
                for character in kind
            ).strip("_")
            name = f"{file_stem}_{safe_kind}_{index:02d}.pdf"
            uploaded = upload_pdf(
                session,
                target_folder,
                name,
                block["contenido"],
                kind,
                source_filename=archivo.filename or "",
                source_pages=block["paginas"],
                pending_batch_id=batch_id,
            )
            blocks.append(
                {
                    "nombre": uploaded.get("name", name),
                    "tipo_documento": kind,
                    "paginas": block["paginas"],
                    "archivo_origen": archivo.filename or "",
                    "url": uploaded.get("webViewLink", ""),
                    "duplicado": bool(uploaded.get("duplicate")),
                }
            )
        final_case = str(case.get("caso") or "").strip() if case else ""
        classification_updated = False
        classification_warning = ""
        if case and not final_case and suggested_case:
            try:
                guardar_expediente_sheets(
                    {
                        "radicado_padre": str(case["radicado_padre"]),
                        "fecha_solicitud": normalizar_fecha(fecha),
                        "placa": placa,
                        "caso": suggested_case,
                    },
                    radicado_existente=str(case["radicado_padre"]),
                )
            except (RuntimeError, ValueError) as error:
                classification_warning = (
                    "Los documentos se guardaron, pero la clasificación no se "
                    f"pudo actualizar en Sheets: {error}"
                )
            else:
                final_case = suggested_case
                classification_updated = True
        return {
            "radicado_padre": parent_radicado,
            "carpeta_drive": f"https://drive.google.com/drive/folders/{folder_id}",
            "pdf_completo": {
                "nombre": full_pdf.get("name", full_name),
                "url": full_pdf.get("webViewLink", ""),
                "duplicado": bool(full_pdf.get("duplicate")),
            },
            "paginas": separated["paginas"],
            "paginas_ocr": separated["paginas_ocr"],
            "bloques": blocks,
            "pendiente_vinculacion": case is None,
            "lote_pendiente": batch_id or None,
            "clasificacion_sugerida": suggested_case,
            "clasificacion_final": final_case,
            "clasificacion_actualizada": classification_updated,
            "advertencia": classification_warning,
        }
    except (FileExistsError, LookupError, ValueError, RuntimeError) as error:
        _raise_operation_error(error)
    finally:
        archivo.file.close()


@app.get("/api/v1/expedientes/{radicado}/checklist")
def obtener_checklist(
    radicado: str,
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict:
    cases = cargar_expedientes_configurados()
    case = _find_case(cases, radicado)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expediente no encontrado.",
        )
    try:
        session = google_session_for_owner({DRIVE_SCOPE})
        folder_id = find_expediente_folder(
            session,
            str(case["radicado_padre"]),
            str(case.get("placa") or ""),
            str(case.get("fecha_solicitud") or ""),
            str(case.get("ubicacion") or ""),
        )
        if not folder_id:
            return {
                "radicado_padre": case["radicado_padre"],
                "presentes": [],
                "documentos": [],
                "complementos_pendientes": listar_complementos_pendientes(
                    session,
                    str(case.get("placa") or ""),
                ),
            }
        return {
            "radicado_padre": case["radicado_padre"],
            **drive_checklist(session, folder_id),
            "complementos_pendientes": listar_complementos_pendientes(
                session,
                str(case.get("placa") or ""),
            ),
        }
    except (ValueError, RuntimeError) as error:
        _raise_operation_error(error)


@app.post("/api/v1/expedientes/{radicado}/vincular-complemento")
def vincular_complemento(
    radicado: str,
    payload: dict[str, str],
    user: Annotated[dict[str, str], Depends(get_current_user)],
) -> dict:
    _require_roles(user, EDITOR_ROLES)
    batch_id = str(payload.get("lote_pendiente") or "").strip()
    if not batch_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Indica el lote de complemento que se va a vincular.",
        )
    case = _find_case(cargar_expedientes_configurados(), radicado)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expediente no encontrado.",
        )
    try:
        session = google_session_for_owner({DRIVE_SCOPE})
        folder_id, _ = expediente_folder(
            session,
            str(case["radicado_padre"]),
            str(case.get("placa") or ""),
            str(case.get("fecha_solicitud") or ""),
            str(case.get("ubicacion") or ""),
        )
        result = vincular_complemento_pendiente(
            session,
            str(case.get("placa") or ""),
            batch_id,
            folder_id,
        )
        suggested_case = str(result.get("clasificacion_sugerida") or "")
        final_case = str(case.get("caso") or "").strip()
        classification_updated = False
        classification_warning = ""
        if not final_case and suggested_case in {
            "Con recurso",
            "Sin recurso",
            "Desistimiento",
        }:
            try:
                guardar_expediente_sheets(
                    {
                        "radicado_padre": str(case["radicado_padre"]),
                        "fecha_solicitud": normalizar_fecha(
                            str(case.get("fecha_solicitud") or "")
                        ),
                        "placa": str(case.get("placa") or ""),
                        "caso": suggested_case,
                    },
                    radicado_existente=str(case["radicado_padre"]),
                )
            except (RuntimeError, ValueError) as error:
                classification_warning = (
                    "El complemento se vinculó, pero la clasificación no se "
                    f"pudo actualizar en Sheets: {error}"
                )
            else:
                final_case = suggested_case
                classification_updated = True
        return {
            "radicado_padre": case["radicado_padre"],
            **result,
            "clasificacion_final": final_case,
            "clasificacion_actualizada": classification_updated,
            "advertencia": classification_warning,
        }
    except (LookupError, ValueError, RuntimeError) as error:
        _raise_operation_error(error)
