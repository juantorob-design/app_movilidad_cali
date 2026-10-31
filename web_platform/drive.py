from __future__ import annotations

from .settings import WebSettings


DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive",)


def crear_servicio_drive(settings: WebSettings):
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_service_account_file(
        settings.service_account_file,
        scopes=list(DRIVE_SCOPES),
    )
    service = build(
        "drive",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )
    folder = service.files().get(
        fileId=settings.drive_folder_id,
        fields="id,name,mimeType",
        supportsAllDrives=True,
    ).execute()
    if folder.get("mimeType") != "application/vnd.google-apps.folder":
        raise ValueError(
            "SISTEMA_DRIVE_FOLDER_ID no corresponde a una carpeta de Drive."
        )
    return service
