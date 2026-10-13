from __future__ import annotations

import datetime
import os
from typing import Any
from urllib.parse import quote

import requests


ROLES = {
    "Sin Rol Asignado",
    "Visualizador",
    "Modificador",
    "Administrador",
    "Super Administrador",
}
STATUSES = {"Pendiente", "Activo", "Inactivo"}
_TIMEOUT = 15


def _configuration() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError(
            "Configura SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY solo en el servidor."
        )
    return url, key


def _request(method: str, path: str, **kwargs) -> Any:
    url, key = _configuration()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        **kwargs.pop("headers", {}),
    }
    try:
        response = requests.request(
            method,
            f"{url}/rest/v1/{path}",
            headers=headers,
            timeout=_TIMEOUT,
            **kwargs,
        )
    except requests.RequestException as error:
        raise RuntimeError("No fue posible conectar con el espacio compartido.") from error
    if not response.ok:
        raise RuntimeError(
            f"El espacio compartido rechazó la operación (HTTP {response.status_code})."
        )
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as error:
        raise RuntimeError("El espacio compartido devolvió una respuesta inválida.") from error


def listar_perfiles() -> list[dict[str, Any]]:
    result = _request(
        "GET",
        "profiles",
        params={
            "select": "email,full_name,role,status,download_allowed,download_requested",
            "order": "email.asc",
        },
    )
    if not isinstance(result, list):
        raise RuntimeError("La lista de perfiles compartidos no es válida.")
    return result


def obtener_perfil(email: str) -> dict[str, Any] | None:
    normalized_email = email.strip().casefold()
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("El correo del usuario no es válido.")
    result = _request(
        "GET",
        f"profiles?email=eq.{quote(normalized_email, safe='@')}",
        params={
            "select": "email,full_name,role,status,download_allowed,download_requested",
            "limit": "2",
        },
    )
    if not isinstance(result, list):
        raise RuntimeError("El perfil compartido no tiene un formato válido.")
    if len(result) > 1:
        raise RuntimeError("Hay perfiles duplicados para el mismo correo.")
    return result[0] if result else None


def actualizar_perfil(
    email: str,
    role: str,
    status: str,
    download_allowed: bool,
) -> None:
    normalized_email = email.strip().casefold()
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("El correo del usuario no es válido.")
    if role not in ROLES or status not in STATUSES:
        raise ValueError("El rol o estado seleccionado no es válido.")
    effective_download_allowed = download_allowed or role in {
        "Modificador",
        "Administrador",
        "Super Administrador",
    }
    if normalized_email == os.environ.get(
        "SISTEMA_WEB_OWNER_EMAIL",
        "",
    ).strip().casefold() and (role != "Super Administrador" or status != "Activo"):
        raise ValueError("No se puede retirar el acceso del propietario principal.")
    updated = _request(
        "PATCH",
        f"profiles?email=eq.{quote(normalized_email, safe='@')}",
        json={
            "role": role,
            "status": status,
            "download_allowed": effective_download_allowed,
            "download_requested": False,
        },
        params={"select": "email"},
        headers={"Prefer": "return=representation"},
    )
    if not isinstance(updated, list) or not updated:
        raise ValueError("No existe un perfil central con ese correo.")


def listar_mensajes(
    email: str,
    can_manage: bool = False,
) -> list[dict[str, Any]]:
    normalized_email = email.strip().casefold()
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("El correo del usuario no es válido.")
    filters = {"order": "created_at.desc", "limit": 200}
    if not can_manage:
        filters["sender_email"] = f"eq.{normalized_email}"
    result = _request(
        "GET",
        "support_messages",
        params={
            "select": "id,sender_email,subject,message,created_at,read_at",
            **filters,
        },
    )
    if not isinstance(result, list):
        raise RuntimeError("La lista de mensajes compartidos no es válida.")
    return result


def crear_mensaje(remitente: str, asunto: str, mensaje: str) -> dict[str, Any]:
    sender = remitente.strip().casefold()
    subject = asunto.strip() or "Soporte"
    body = mensaje.strip()
    if not sender or "@" not in sender:
        raise ValueError("El correo remitente no es válido.")
    if not body:
        raise ValueError("Escribe un mensaje antes de enviarlo.")
    if len(subject) > 200 or len(body) > 10000:
        raise ValueError("El asunto o mensaje supera el límite permitido.")
    result = _request(
        "POST",
        "support_messages",
        params={"select": "id,sender_email,subject,message,created_at,read_at"},
        json={"sender_email": sender, "subject": subject, "message": body},
        headers={"Prefer": "return=representation"},
    )
    if not isinstance(result, list) or not result:
        raise RuntimeError("No se confirmó el registro del mensaje compartido.")
    return result[0]


def marcar_mensaje_leido(message_id: str) -> None:
    if len(message_id) > 80 or not message_id.strip():
        raise ValueError("El identificador del mensaje no es válido.")
    result = _request(
        "PATCH",
        f"support_messages?id=eq.{quote(message_id.strip(), safe='-')}&read_at=is.null",
        json={"read_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
        headers={"Prefer": "return=representation"},
    )
    if not isinstance(result, list) or not result:
        raise RuntimeError("No se pudo confirmar el estado del mensaje.")


def solicitar_permiso_descarga(email: str) -> None:
    normalized_email = email.strip().casefold()
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("El correo del usuario no es válido.")
    result = _request(
        "PATCH",
        f"profiles?email=eq.{quote(normalized_email, safe='@')}&role=eq.Visualizador&status=eq.Activo",
        json={"download_requested": True},
        headers={"Prefer": "return=representation"},
    )
    if not isinstance(result, list) or not result:
        raise ValueError("El perfil no está habilitado para solicitar descargas.")
