import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from web_platform.database import (
    CaseConcurrencyError,
    guardar_expediente,
    registrar_usuario_oidc,
)
from web_platform.drive import crear_servicio_drive
from web_platform.auth import validar_correo_propietario
from web_platform.settings import WebConfigurationError, WebSettings, normalizar_identidad_oidc


def valid_environment():
    return {
        "SISTEMA_DATABASE_URL": "postgresql://web_app:secret@db.institucion.gov/sistema",
        "SISTEMA_DRIVE_FOLDER_ID": "institutional-drive-folder",
        "GOOGLE_APPLICATION_CREDENTIALS": "C:\\secure\\service-account.json",
        "SISTEMA_ALLOWED_EMAIL_DOMAINS": "institucion.gov",
        "SISTEMA_WEB_SUPER_ADMIN_EMAIL": "admin@institucion.gov",
        "SISTEMA_WEB_PUBLIC_URL": "https://desvinculaciones.institucion.gov",
    }


class TestDockerBuildContext(unittest.TestCase):
    def test_web_image_context_excludes_local_secrets_and_android_artifacts(self):
        dockerignore = (
            Path(__file__).resolve().parents[1] / ".dockerignore"
        ).read_text(encoding="utf-8")

        self.assertIn("*secret*.json", dockerignore)
        self.assertIn("*credential*.json", dockerignore)
        self.assertIn("token.json", dockerignore)
        self.assertIn("android_app/", dockerignore)
        self.assertIn("venv_mobile/", dockerignore)


class FakeCursor:
    def __init__(self, result=None):
        self.result = result
        self.commands = []
        self.parameters = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, command, parameters=None):
        self.commands.append(command)
        self.parameters.append(parameters)

    def fetchone(self):
        return self.result


class FakeConnection:
    def __init__(self, cursors):
        self.cursors = iter(cursors)
        self.transactions = 0

    def cursor(self):
        return next(self.cursors)

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield


class TestWebSettings(unittest.TestCase):
    def test_loads_required_institutional_configuration(self):
        settings = WebSettings.from_env(valid_environment())

        self.assertEqual(settings.allowed_email_domains, ("institucion.gov",))
        self.assertEqual(settings.super_admin_email, "admin@institucion.gov")
        self.assertEqual(settings.public_url, "https://desvinculaciones.institucion.gov")

    def test_rejects_missing_database_configuration(self):
        environment = valid_environment()
        environment.pop("SISTEMA_DATABASE_URL")

        with self.assertRaises(WebConfigurationError):
            WebSettings.from_env(environment)

    def test_rejects_non_postgres_database_url(self):
        environment = valid_environment()
        environment["SISTEMA_DATABASE_URL"] = "sqlite:///local.db"

        with self.assertRaises(WebConfigurationError):
            WebSettings.from_env(environment)

    def test_rejects_missing_institutional_email_domain(self):
        environment = valid_environment()
        environment["SISTEMA_ALLOWED_EMAIL_DOMAINS"] = ""

        with self.assertRaises(WebConfigurationError):
            WebSettings.from_env(environment)

    def test_rejects_insecure_public_url(self):
        environment = valid_environment()
        environment["SISTEMA_WEB_PUBLIC_URL"] = "http://desvinculaciones.institucion.gov"

        with self.assertRaises(WebConfigurationError):
            WebSettings.from_env(environment)

    def test_rejects_unverified_or_external_identity(self):
        with self.assertRaises(WebConfigurationError):
            normalizar_identidad_oidc(
                "user@institucion.gov",
                False,
                ("institucion.gov",),
            )
        with self.assertRaises(WebConfigurationError):
            normalizar_identidad_oidc(
                "user@gmail.com",
                True,
                ("institucion.gov",),
            )

    def test_normalizes_verified_workspace_identity(self):
        self.assertEqual(
            normalizar_identidad_oidc(
                "  User@Institucion.gov ",
                True,
                ("institucion.gov",),
            ),
            "user@institucion.gov",
        )


class TestOwnerOnlyWebAuth(unittest.TestCase):
    def test_allows_only_the_configured_google_account(self):
        self.assertEqual(
            validar_correo_propietario(
                "  Owner@Gmail.com ",
                "owner@gmail.com",
            ),
            "owner@gmail.com",
        )

    def test_rejects_every_other_google_account(self):
        with self.assertRaises(WebConfigurationError):
            validar_correo_propietario(
                "another.user@gmail.com",
                "owner@gmail.com",
            )

    def test_rejects_missing_owner_configuration(self):
        with self.assertRaises(WebConfigurationError):
            validar_correo_propietario("owner@gmail.com", "")

    def test_owner_allowlist_is_case_insensitive_but_not_domain_wide(self):
        self.assertEqual(
            validar_correo_propietario(
                "OWNER@gmail.com",
                "owner@gmail.com",
            ),
            "owner@gmail.com",
        )
        with self.assertRaises(WebConfigurationError):
            validar_correo_propietario(
                "colleague@gmail.com",
                "owner@gmail.com",
            )


class TestWebPostgresOperations(unittest.TestCase):
    def test_oidc_registration_defaults_new_users_to_pending(self):
        cursor = FakeCursor(
            ("staff@institucion.gov", "Staff", "Sin Rol Asignado", "Pendiente")
        )
        connection = FakeConnection([cursor])

        profile = registrar_usuario_oidc(
            connection,
            "Staff@Institucion.gov",
            "Staff",
            "admin@institucion.gov",
        )

        self.assertEqual(profile["estado"], "Pendiente")
        self.assertEqual(cursor.parameters[0], (
            "staff@institucion.gov",
            "Staff",
            "Sin Rol Asignado",
            "Pendiente",
        ))

    def test_first_super_admin_is_created_active_without_resetting_existing_profile(self):
        cursor = FakeCursor(
            ("admin@institucion.gov", "Admin", "Super Administrador", "Activo")
        )
        connection = FakeConnection([cursor])

        profile = registrar_usuario_oidc(
            connection,
            "admin@institucion.gov",
            "Admin",
            "ADMIN@INSTITUCION.GOV",
        )

        self.assertEqual(profile["rol"], "Super Administrador")
        self.assertEqual(profile["estado"], "Activo")
        self.assertIn("ON CONFLICT (email) DO NOTHING", cursor.commands[0])

    def test_case_save_uses_version_guard_and_writes_audit_event(self):
        save_cursor = FakeCursor((3,))
        connection = FakeConnection([save_cursor])

        version = guardar_expediente(
            connection,
            "RAD-001",
            {"radicado_padre": "RAD-001", "placa": "ABC123"},
            "staff@institucion.gov",
            version_esperada=2,
        )

        self.assertEqual(version, 3)
        self.assertIn("AND version = %s", save_cursor.commands[0])
        self.assertEqual(save_cursor.parameters[1][0:3], (
            "staff@institucion.gov",
            "expediente_actualizado",
            "RAD-001",
        ))

    def test_concurrent_case_change_is_reported_not_overwritten(self):
        connection = FakeConnection([FakeCursor(None)])

        with self.assertRaises(CaseConcurrencyError):
            guardar_expediente(
                connection,
                "RAD-001",
                {"radicado_padre": "RAD-001"},
                "staff@institucion.gov",
                version_esperada=2,
            )

    def test_case_save_rejects_non_serializable_payload_before_database_write(self):
        connection = FakeConnection([])

        with self.assertRaises(ValueError):
            guardar_expediente(
                connection,
                "RAD-001",
                {"binary": object()},
                "staff@institucion.gov",
                version_esperada=None,
            )

        self.assertEqual(connection.transactions, 0)


class TestWebDriveService(unittest.TestCase):
    def test_creates_drive_client_and_validates_shared_root(self):
        settings = WebSettings.from_env(valid_environment())
        service = MagicMock()
        service.files().get.return_value.execute.return_value = {
            "id": settings.drive_folder_id,
            "name": "PDFS Escaneados",
            "mimeType": "application/vnd.google-apps.folder",
        }
        with (
            patch(
                "google.oauth2.service_account.Credentials.from_service_account_file"
            ) as credentials_factory,
            patch("googleapiclient.discovery.build", return_value=service) as build,
        ):
            credentials_factory.return_value = object()
            result = crear_servicio_drive(settings)

        self.assertIs(result, service)
        credentials_factory.assert_called_once_with(
            settings.service_account_file,
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        build.assert_called_once_with(
            "drive",
            "v3",
            credentials=credentials_factory.return_value,
            cache_discovery=False,
        )

    def test_rejects_a_drive_root_that_is_not_a_folder(self):
        settings = WebSettings.from_env(valid_environment())
        service = MagicMock()
        service.files().get.return_value.execute.return_value = {
            "id": settings.drive_folder_id,
            "name": "Unexpected file",
            "mimeType": "application/pdf",
        }
        with (
            patch(
                "google.oauth2.service_account.Credentials.from_service_account_file"
            ),
            patch("googleapiclient.discovery.build", return_value=service),
        ):
            with self.assertRaises(ValueError):
                crear_servicio_drive(settings)


if __name__ == "__main__":
    unittest.main()
