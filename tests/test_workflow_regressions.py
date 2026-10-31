import unittest
from unittest.mock import patch

import app_6


class TestWorkflowRegressions(unittest.TestCase):
    def test_ai_fills_missing_fields_without_replacing_confirmed_values(self):
        destination = {
            "empresa": "Empresa confirmada",
            "fecha_solicitud": "",
        }

        with patch.object(
            app_6,
            "campos_formulario_desde_ia",
            return_value={
                "empresa": "Empresa detectada por IA",
                "fecha_solicitud": "2025-06-11",
            },
        ):
            result = app_6.combinar_campos_ia(destination, {"source": "test"})

        self.assertEqual(result["empresa"], "Empresa confirmada")
        self.assertEqual(result["fecha_solicitud"], "2025-06-11")

    def test_ai_replaces_contaminated_ocr_text(self):
        destination = {"propietario": "NOMBRES / EMP"}

        with patch.object(
            app_6,
            "campos_formulario_desde_ia",
            return_value={"propietario": "Propietario identificado"},
        ):
            result = app_6.combinar_campos_ia(destination, {"source": "test"})

        self.assertEqual(result["propietario"], "Propietario identificado")

    def test_documents_are_sorted_by_administrative_precedence(self):
        documents = [
            {"tipo_documento": "Otro", "nombre": "anexo.pdf"},
            {"tipo_documento": "Notificación por aviso", "nombre": "aviso.pdf"},
            {"tipo_documento": "Solicitud", "nombre": "solicitud.pdf"},
            {"tipo_documento": "Consulta QX", "nombre": "qx.pdf"},
        ]

        ordered = app_6.ordenar_documentos_por_precedencia(documents)

        self.assertEqual(
            [document["tipo_documento"] for document in ordered],
            ["Solicitud", "Consulta QX", "Notificación por aviso", "Otro"],
        )

    def test_requerimiento_satisfies_resolution_checklist_equivalence(self):
        faltantes = app_6.documentos_faltantes(
            {
                "documentos_esperados": ["Resolución"],
                "canvas_paginas": [{"tipo_documento": "Requerimiento"}],
            }
        )

        self.assertEqual(faltantes, [])

    def test_notification_subtype_satisfies_general_notification_requirement(self):
        faltantes = app_6.documentos_faltantes(
            {
                "documentos_esperados": ["Notificación"],
                "canvas_paginas": [
                    {"tipo_documento": "Notificación por publicación web"}
                ],
            }
        )

        self.assertEqual(faltantes, [])

    def test_unmatched_complement_remains_pending_linkage(self):
        with patch.object(
            app_6.st,
            "session_state",
            {"db_expedientes": {}},
        ):
            route = app_6.enrutar_documento_cargado(
                {"placa": "ABC123"},
                es_complemento=True,
            )

        self.assertEqual(route["estado"], "PENDIENTE_VINCULACION")
        self.assertIsNone(route["expediente_local"])

    def test_matching_complement_routes_to_existing_local_case(self):
        case = {
            "radicado_padre": "RAD-001",
            "placa": "ABC123",
            "empresa": "Empresa de prueba",
        }
        with patch.object(
            app_6.st,
            "session_state",
            {"db_expedientes": {"RAD-001": case}},
        ):
            route = app_6.enrutar_documento_cargado(
                {"placa": "ABC-123"},
                es_complemento=True,
            )

        self.assertEqual(route["estado"], "ACTUALIZADO_CON_COMPLEMENTO")
        self.assertIs(route["expediente_local"], case)


if __name__ == "__main__":
    unittest.main()
