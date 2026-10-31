from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse


class WebConfigurationError(ValueError):
    """La configuración requerida para el servidor web está ausente o es inválida."""


@dataclass(frozen=True)
class WebSettings:
    database_url: str
    drive_folder_id: str
    service_account_file: str
    allowed_email_domains: tuple[str, ...]
    super_admin_email: str
    ollama_url: str
    public_url: str

    @classmethod
    def from_env(cls, environ=None) -> "WebSettings":
        values = os.environ if environ is None else environ
        database_url = str(values.get("SISTEMA_DATABASE_URL", "")).strip()
        parsed_database_url = urlparse(database_url)
        if parsed_database_url.scheme not in {"postgres", "postgresql"}:
            raise WebConfigurationError(
                "SISTEMA_DATABASE_URL debe usar el esquema PostgreSQL."
            )
        if not parsed_database_url.hostname:
            raise WebConfigurationError(
                "SISTEMA_DATABASE_URL debe incluir el servidor de base de datos."
            )

        drive_folder_id = str(
            values.get("SISTEMA_DRIVE_FOLDER_ID", "")
        ).strip()
        if not drive_folder_id:
            raise WebConfigurationError(
                "SISTEMA_DRIVE_FOLDER_ID es obligatorio en el servidor web."
            )

        service_account_file = str(
            values.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        ).strip()
        if not service_account_file:
            raise WebConfigurationError(
                "GOOGLE_APPLICATION_CREDENTIALS debe apuntar a la cuenta "
                "de servicio compartida con la carpeta de Drive."
            )

        domains = tuple(
            sorted(
                {
                    domain.casefold().lstrip("@").strip()
                    for domain in re.split(
                        r"[,;\s]+",
                        str(values.get("SISTEMA_ALLOWED_EMAIL_DOMAINS", "")),
                    )
                    if domain.strip()
                }
            )
        )
        if not domains or any(
            not re.fullmatch(r"[a-z0-9.-]+", domain)
            or domain.startswith(".")
            or domain.endswith(".")
            or ".." in domain
            for domain in domains
        ):
            raise WebConfigurationError(
                "SISTEMA_ALLOWED_EMAIL_DOMAINS debe contener uno o más "
                "dominios institucionales válidos."
            )

        super_admin_email = str(
            values.get("SISTEMA_WEB_SUPER_ADMIN_EMAIL", "")
        ).strip().casefold()
        if "@" not in super_admin_email or not any(
            super_admin_email.endswith(f"@{domain}") for domain in domains
        ):
            raise WebConfigurationError(
                "SISTEMA_WEB_SUPER_ADMIN_EMAIL debe pertenecer a un dominio "
                "institucional permitido."
            )

        public_url = str(values.get("SISTEMA_WEB_PUBLIC_URL", "")).strip()
        if public_url:
            parsed_public_url = urlparse(public_url)
            if (
                parsed_public_url.scheme != "https"
                or not parsed_public_url.hostname
                or parsed_public_url.username
                or parsed_public_url.password
            ):
                raise WebConfigurationError(
                    "SISTEMA_WEB_PUBLIC_URL debe ser una URL HTTPS institucional."
                )

        return cls(
            database_url=database_url,
            drive_folder_id=drive_folder_id,
            service_account_file=service_account_file,
            allowed_email_domains=domains,
            super_admin_email=super_admin_email,
            ollama_url=str(
                values.get(
                    "SISTEMA_OLLAMA_URL",
                    "http://127.0.0.1:11434",
                )
            ).strip().rstrip("/"),
            public_url=public_url,
        )


@lru_cache(maxsize=1)
def get_web_settings() -> WebSettings:
    return WebSettings.from_env()


def normalizar_identidad_oidc(
    email: str | None,
    email_verified: bool,
    allowed_domains: tuple[str, ...],
) -> str:
    normalized_email = str(email or "").strip().casefold()
    if not email_verified:
        raise WebConfigurationError(
            "Google no confirmó que el correo de la sesión esté verificado."
        )
    local_part, separator, domain = normalized_email.rpartition("@")
    if not separator or not local_part or domain not in allowed_domains:
        raise WebConfigurationError(
            "La cuenta de Google no pertenece a un dominio institucional autorizado."
        )
    return normalized_email
