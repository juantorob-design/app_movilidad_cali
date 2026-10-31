import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app_6


class TestDesktopOAuthMigration(unittest.TestCase):
    def test_web_oauth_client_defaults_to_automatic_port_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client_file = Path(temp_dir) / "credentials.json"
            client_file.write_text(
                json.dumps(
                    {
                        "web": {
                            "client_id": "web-client-id",
                            "redirect_uris": ["http://localhost:8080/"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(app_6, "CLIENT_SECRETS_FILE", str(client_file)),
                patch.dict(os.environ, {}, clear=True),
            ):
                message = app_6.revisar_configuracion_oauth()

        self.assertIn("tipo Aplicación de escritorio", message)

    def test_web_oauth_client_accepts_matching_explicit_port(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client_file = Path(temp_dir) / "credentials.json"
            client_file.write_text(
                json.dumps(
                    {
                        "web": {
                            "client_id": "web-client-id",
                            "redirect_uris": ["http://localhost:8080/"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(app_6, "CLIENT_SECRETS_FILE", str(client_file)),
                patch.dict(os.environ, {"SISTEMA_OAUTH_PORT": "8080"}),
            ):
                message = app_6.revisar_configuracion_oauth()

        self.assertIsNone(message)

    def test_rejects_saved_token_from_another_oauth_client(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client_file = Path(temp_dir) / "credentials.json"
            client_file.write_text(
                json.dumps({"installed": {"client_id": "active-client-id"}}),
                encoding="utf-8",
            )

            with patch.object(app_6, "CLIENT_SECRETS_FILE", str(client_file)):
                self.assertFalse(
                    app_6._token_uses_configured_google_client(
                        Mock(client_id="previous-client-id"),
                    )
                )

    def test_accepts_saved_token_from_configured_oauth_client(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client_file = Path(temp_dir) / "credentials.json"
            client_file.write_text(
                json.dumps({"installed": {"client_id": "active-client-id"}}),
                encoding="utf-8",
            )

            with patch.object(app_6, "CLIENT_SECRETS_FILE", str(client_file)):
                self.assertTrue(
                    app_6._token_uses_configured_google_client(
                        Mock(client_id="active-client-id"),
                    )
                )

    def test_keeps_existing_token_when_client_file_is_not_installed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client_file = Path(temp_dir) / "missing-credentials.json"

            with patch.object(app_6, "CLIENT_SECRETS_FILE", str(client_file)):
                self.assertTrue(
                    app_6._token_uses_configured_google_client(
                        Mock(client_id="previous-client-id"),
                    )
                )


if __name__ == "__main__":
    unittest.main()
