import os
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from mobile_api import shared_workspace
from mobile_api.main import app, actualizar_perfil_compartido, crear_mensaje_compartido


class TestSharedWorkspaceClient(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_requires_server_credentials(self):
        with self.assertRaises(RuntimeError):
            shared_workspace.listar_perfiles()

    @patch.dict(
        os.environ,
        {
            "SUPABASE_URL": "https://project.example",
            "SUPABASE_SERVICE_ROLE_KEY": "server-test-key",
        },
        clear=True,
    )
    @patch("mobile_api.shared_workspace.requests.request")
    def test_lists_profiles_with_server_authentication(self, request):
        response = Mock(ok=True, content=b'[{"email":"a@example.com"}]')
        response.json.return_value = [{"email": "a@example.com"}]
        request.return_value = response

        profiles = shared_workspace.listar_perfiles()

        self.assertEqual(profiles, [{"email": "a@example.com"}])
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["headers"]["apikey"], "server-test-key")
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer server-test-key",
        )

    @patch("mobile_api.shared_workspace._request")
    def test_loads_a_single_profile_for_central_mobile_authorization(self, request):
        request.return_value = [{
            "email": "staff@example.com",
            "role": "Visualizador",
            "status": "Activo",
        }]

        profile = shared_workspace.obtener_perfil("Staff@Example.com")

        self.assertEqual(profile["email"], "staff@example.com")
        self.assertEqual(
            request.call_args.args,
            ("GET", "profiles?email=eq.staff@example.com"),
        )

    @patch("mobile_api.shared_workspace._request")
    def test_rejects_ambiguous_duplicate_profiles(self, request):
        request.return_value = [{"email": "staff@example.com"}, {"email": "staff@example.com"}]

        with self.assertRaises(RuntimeError):
            shared_workspace.obtener_perfil("staff@example.com")

    @patch("mobile_api.shared_workspace._request")
    def test_filters_non_admin_inbox_to_own_messages(self, request):
        request.return_value = []

        shared_workspace.listar_mensajes("Staff@Example.com")

        self.assertEqual(
            request.call_args.kwargs["params"]["sender_email"],
            "eq.staff@example.com",
        )

    @patch("mobile_api.shared_workspace._request")
    def test_admin_inbox_lists_messages_from_all_profiles(self, request):
        request.return_value = []

        shared_workspace.listar_mensajes("admin@example.com", can_manage=True)

        self.assertNotIn("sender_email", request.call_args.kwargs["params"])

    @patch.dict(
        os.environ,
        {
            "SUPABASE_URL": "https://project.example",
            "SUPABASE_SERVICE_ROLE_KEY": "server-test-key",
            "SISTEMA_WEB_OWNER_EMAIL": "owner@example.com",
        },
        clear=True,
    )
    def test_cannot_remove_primary_owner_access(self):
        with self.assertRaises(ValueError):
            shared_workspace.actualizar_perfil(
                "OWNER@example.com",
                "Administrador",
                "Activo",
                False,
            )

    def test_rejects_invalid_profile_role_before_request(self):
        with self.assertRaises(ValueError):
            shared_workspace.actualizar_perfil(
                "user@example.com",
                "Unknown",
                "Activo",
                False,
            )

    @patch.dict(
        os.environ,
        {
            "SUPABASE_URL": "https://project.example",
            "SUPABASE_SERVICE_ROLE_KEY": "server-test-key",
        },
        clear=True,
    )
    @patch("mobile_api.shared_workspace._request")
    def test_privileged_roles_always_keep_document_download_enabled(self, request):
        request.return_value = [{"email": "editor@example.com"}]

        shared_workspace.actualizar_perfil(
            "editor@example.com",
            "Modificador",
            "Activo",
            False,
        )

        self.assertTrue(request.call_args.kwargs["json"]["download_allowed"])

    @patch("mobile_api.shared_workspace._request")
    def test_rejects_empty_support_message(self, request):
        with self.assertRaises(ValueError):
            shared_workspace.crear_mensaje(
                "user@example.com",
                "Asunto",
                "   ",
            )
        request.assert_not_called()

    @patch("mobile_api.shared_workspace._request")
    def test_requires_confirmation_after_marking_read(self, request):
        request.return_value = []
        with self.assertRaises(RuntimeError):
            shared_workspace.marcar_mensaje_leido(
                "d2719c7a-6d64-4a7d-a94c-646a9b31c8a1"
            )


class TestSharedWorkspaceEndpoints(unittest.TestCase):
    def test_workspace_routes_require_bearer_authentication(self):
        paths = app.openapi()["paths"]
        for path, method in (
            ("/api/v1/workspace/profiles", "get"),
            ("/api/v1/workspace/profiles", "patch"),
            ("/api/v1/workspace/profiles/me/download-request", "post"),
            ("/api/v1/workspace/messages", "get"),
            ("/api/v1/workspace/messages", "post"),
            ("/api/v1/workspace/messages/{message_id}/read", "patch"),
        ):
            self.assertEqual(paths[path][method]["security"], [{"HTTPBearer": []}])

    def test_profile_listing_requires_an_administrator(self):
            from mobile_api.main import listar_perfiles_compartidos

            with self.assertRaises(HTTPException) as raised:
                listar_perfiles_compartidos({"email": "viewer@example.com", "role": "Visualizador"})

            self.assertEqual(raised.exception.status_code, 403)

    def test_rejects_profile_payload_without_download_permission(self):
        with self.assertRaises(HTTPException) as raised:
            actualizar_perfil_compartido(
                {"email": "user@example.com", "role": "Visualizador", "status": "Activo"},
                {"email": "owner@example.com"},
            )

        self.assertEqual(raised.exception.status_code, 422)

    def test_profile_update_requires_an_administrator(self):
        with self.assertRaises(HTTPException) as raised:
            actualizar_perfil_compartido(
                {
                    "email": "user@example.com",
                    "role": "Visualizador",
                    "status": "Activo",
                    "download_allowed": False,
                },
                {"email": "viewer@example.com", "role": "Visualizador"},
            )

        self.assertEqual(raised.exception.status_code, 403)

    @patch("mobile_api.main.shared_workspace.solicitar_permiso_descarga")
    def test_download_permission_request_uses_authenticated_profile(self, request):
        from mobile_api.main import solicitar_permiso_descarga

        result = solicitar_permiso_descarga({
            "email": "viewer@example.com",
            "role": "Visualizador",
            "download_allowed": False,
        })

        self.assertEqual(result, {"status": "requested"})
        request.assert_called_once_with("viewer@example.com")

    def test_non_viewer_cannot_request_download_permission(self):
        from mobile_api.main import solicitar_permiso_descarga

        with self.assertRaises(HTTPException) as raised:
            solicitar_permiso_descarga({
                "email": "editor@example.com",
                "role": "Modificador",
                "download_allowed": True,
            })

        self.assertEqual(raised.exception.status_code, 403)

    def test_rejects_non_boolean_download_permission(self):
        with self.assertRaises(HTTPException) as raised:
            actualizar_perfil_compartido(
                {
                    "email": "user@example.com",
                    "role": "Visualizador",
                    "status": "Activo",
                    "download_allowed": "true",
                },
                {"email": "owner@example.com"},
            )

        self.assertEqual(raised.exception.status_code, 422)

    @patch("mobile_api.main.shared_workspace.crear_mensaje")
    def test_message_sender_comes_from_authenticated_identity(self, create_message):
        create_message.return_value = {"id": "message-1"}

        result = crear_mensaje_compartido(
            {"subject": "Ayuda", "message": "Consulta"},
            {"email": "owner@example.com"},
        )

        self.assertEqual(result, {"mensaje": {"id": "message-1"}})
        create_message.assert_called_once_with(
            "owner@example.com",
            "Ayuda",
            "Consulta",
        )

    def test_rejects_client_supplied_message_identity(self):
        with self.assertRaises(HTTPException) as raised:
            crear_mensaje_compartido(
                {
                    "sender_email": "attacker@example.com",
                    "subject": "Ayuda",
                    "message": "Consulta",
                },
                {"email": "owner@example.com"},
            )

        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
