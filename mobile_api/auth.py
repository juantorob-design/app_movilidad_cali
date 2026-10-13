from __future__ import annotations

from google.auth import exceptions as google_auth_exceptions
from google.auth.transport.requests import Request
from google.oauth2 import id_token


class MobileAuthenticationError(ValueError):
    """A Google identity token is invalid or has no verified email."""


def validar_identidad_google(
    token: str,
    audience: str,
    owner_email: str,
) -> dict:
    if not audience.strip():
        raise RuntimeError("SISTEMA_GOOGLE_WEB_CLIENT_ID is required.")
    normalized_owner = owner_email.strip().casefold()
    if not normalized_owner or "@" not in normalized_owner:
        raise RuntimeError("SISTEMA_WEB_OWNER_EMAIL must be configured.")

    try:
        claims = id_token.verify_oauth2_token(
            token,
            Request(),
            audience=audience.strip(),
        )
    except (ValueError, google_auth_exceptions.GoogleAuthError) as error:
        raise MobileAuthenticationError(
            "Google no pudo validar el inicio de sesión. Comprueba que la audiencia "
            "del cliente web en la APK coincida con la de la API y que la cuenta "
            "esté añadida como usuario de prueba de OAuth."
        ) from error

    email = str(claims.get("email") or "").strip().casefold()
    if not email or claims.get("email_verified") is not True:
        raise MobileAuthenticationError(
            "Se requiere una cuenta Google con correo verificado."
        )
    return {
        "email": email,
        "name": str(claims.get("name") or email).strip(),
    }
