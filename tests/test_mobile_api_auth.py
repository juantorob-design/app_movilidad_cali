import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from google.auth.exceptions import GoogleAuthError

from mobile_api.auth import MobileAuthenticationError, validar_identidad_google
from mobile_api.main import app, get_current_user


class TestMobileGoogleAuthentication(unittest.TestCase):
    @patch("mobile_api.auth.id_token.verify_oauth2_token")
    def test_accepts_verified_google_identity_for_central_profile_authorization(self, verify_token):
        verify_token.return_value = {
            "email": "Owner@Gmail.com",
            "email_verified": True,
            "name": "Owner",
        }

        identity = validar_identidad_google(
            "signed-google-token",
            "web-client-id",
            "owner@gmail.com",
        )

        self.assertEqual(identity, {"email": "owner@gmail.com", "name": "Owner"})
        verify_token.assert_called_once()
        self.assertEqual(verify_token.call_args.kwargs["audience"], "web-client-id")

    @patch("mobile_api.auth.id_token.verify_oauth2_token")
    def test_accepts_a_different_verified_google_account(self, verify_token):
        verify_token.return_value = {
            "email": "other@gmail.com",
            "email_verified": True,
        }

        identity = validar_identidad_google(
            "signed-google-token",
            "web-client-id",
            "owner@gmail.com",
        )

        self.assertEqual(identity["email"], "other@gmail.com")

    @patch("mobile_api.auth.id_token.verify_oauth2_token")
    def test_rejects_unverified_email(self, verify_token):
        verify_token.return_value = {
            "email": "owner@gmail.com",
            "email_verified": False,
        }

        with self.assertRaises(MobileAuthenticationError):
            validar_identidad_google(
                "signed-google-token",
                "web-client-id",
                "owner@gmail.com",
            )

    def test_fails_closed_when_audience_is_missing(self):
        with self.assertRaises(RuntimeError):
            validar_identidad_google("signed-google-token", "", "owner@gmail.com")

    @patch("mobile_api.auth.id_token.verify_oauth2_token")
    @patch.dict("os.environ", {"DESARROLLO_MODE": "true"}, clear=True)
    def test_development_mode_does_not_accept_static_tokens(self, verify_token):
        verify_token.side_effect = ValueError("invalid token")

        with self.assertRaises(MobileAuthenticationError):
            validar_identidad_google(
                "test-token",
                "web-client-id",
                "owner@gmail.com",
            )
        verify_token.assert_called_once()

    @patch("mobile_api.auth.id_token.verify_oauth2_token")
    def test_rejects_invalid_google_token(self, verify_token):
        verify_token.side_effect = GoogleAuthError("invalid")

        with self.assertRaises(MobileAuthenticationError):
            validar_identidad_google(
                "invalid-token",
                "web-client-id",
                "owner@gmail.com",
            )

    def test_api_requires_bearer_identity(self):
        with self.assertRaises(HTTPException) as raised:
            get_current_user(None)

        self.assertEqual(raised.exception.status_code, 401)

    def test_case_search_endpoint_requires_authentication(self):
        search_operation = app.openapi()["paths"]["/api/v1/expedientes/buscar"]["get"]
        self.assertEqual(search_operation["security"], [{"HTTPBearer": []}])

    @patch("mobile_api.main.validar_identidad_google")
    @patch("mobile_api.main.shared_workspace.obtener_perfil")
    @patch.dict(
        "os.environ",
        {
            "SISTEMA_GOOGLE_WEB_CLIENT_ID": "web-client-id",
            "SISTEMA_WEB_OWNER_EMAIL": "owner@gmail.com",
        },
        clear=False,
    )
    def test_api_requires_an_active_central_profile_for_google_identity(
        self,
        get_profile,
        validate_identity,
    ):
        validate_identity.return_value = {
            "email": "owner@gmail.com",
            "name": "Owner",
        }
        get_profile.return_value = {
            "email": "owner@gmail.com",
            "role": "Super Administrador",
            "status": "Activo",
            "download_allowed": True,
        }

        result = get_current_user(
            HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials="signed-google-token",
            )
        )

        self.assertEqual(
            result,
            {
                "email": "owner@gmail.com",
                "name": "Owner",
                "role": "Super Administrador",
                "status": "Activo",
                "download_allowed": True,
                "download_requested": False,
            },
        )
        validate_identity.assert_called_once_with(
            "signed-google-token",
            "web-client-id",
            "owner@gmail.com",
        )
        get_profile.assert_called_once_with("owner@gmail.com")

    @patch("mobile_api.main.validar_identidad_google")
    @patch("mobile_api.main.shared_workspace.obtener_perfil")
    @patch.dict(
        "os.environ",
        {
            "SISTEMA_GOOGLE_WEB_CLIENT_ID": "web-client-id",
            "SISTEMA_WEB_OWNER_EMAIL": "owner@gmail.com",
        },
        clear=False,
    )
    def test_api_rejects_users_without_an_active_approved_profile(
        self,
        get_profile,
        validate_identity,
    ):
        validate_identity.return_value = {"email": "staff@gmail.com", "name": "Staff"}
        get_profile.return_value = {
            "email": "staff@gmail.com",
            "role": "Sin Rol Asignado",
            "status": "Pendiente",
        }
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="signed-google-token",
        )

        with self.assertRaises(HTTPException) as raised:
            get_current_user(credentials)

        self.assertEqual(raised.exception.status_code, 403)

    @patch("mobile_api.main.validar_identidad_google")
    @patch("mobile_api.main.shared_workspace.obtener_perfil")
    @patch.dict(
        "os.environ",
        {
            "SISTEMA_GOOGLE_WEB_CLIENT_ID": "web-client-id",
            "SISTEMA_WEB_OWNER_EMAIL": "owner@gmail.com",
        },
        clear=False,
    )
    def test_api_fails_closed_when_central_profiles_are_unavailable(
        self,
        get_profile,
        validate_identity,
    ):
        validate_identity.return_value = {"email": "owner@gmail.com", "name": "Owner"}
        get_profile.side_effect = RuntimeError("Supabase unavailable")
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="signed-google-token",
        )

        with self.assertRaises(HTTPException) as raised:
            get_current_user(credentials)

        self.assertEqual(raised.exception.status_code, 503)

    @patch.dict("os.environ", {}, clear=True)
    def test_api_fails_closed_when_oauth_is_not_configured(self):
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="signed-google-token",
        )

        with self.assertRaises(HTTPException) as raised:
            get_current_user(credentials)

        self.assertEqual(raised.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
