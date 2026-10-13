import os
import unittest
from unittest.mock import patch

from mobile_api.expedientes import (
    _records_from_values,
    cargar_expedientes_sheets,
    extraer_resumen_expediente,
)


class TestMobileApiExpedientes(unittest.TestCase):
    def test_maps_operational_sheet_columns_to_mobile_fields(self):
        records = _records_from_values(
            [
                [
                    "RAD PADRE",
                    "FECHA SOLICITUD",
                    "PLACA",
                    "EMPRESA",
                    "NIT",
                    "PROPIETARIO",
                    "CEDULA",
                    "TIPO CASO",
                    "REQUERIMIENTO",
                    "DESISTIMIENTO",
                    "RESOLUCION RECURSO",
                    "FECHA RESOLUCION RECURSO",
                    "DOCUMENTOS DRIVE",
                ],
                [
                    "RAD-2026-001",
                    "01/10/2026",
                    "ABC123",
                    "Transportes",
                    "900123",
                    "Propietario",
                    "123456",
                    "Sin recurso",
                    "REQ-2026-001",
                    "",
                    "",
                    "",
                    "https://drive.google.com/example",
                ],
                ["", "", "", "", "", "", "", "", "", "", "", "", ""],
            ]
        )

        self.assertEqual(list(records), ["RAD-2026-001"])
        self.assertEqual(records["RAD-2026-001"]["placa"], "ABC123")
        self.assertEqual(records["RAD-2026-001"]["fecha_solicitud"], "01/10/2026")
        self.assertEqual(records["RAD-2026-001"]["nit_empresa"], "900123")
        self.assertEqual(records["RAD-2026-001"]["cedula_propietario"], "123456")
        self.assertEqual(records["RAD-2026-001"]["caso"], "Sin recurso")
        self.assertEqual(records["RAD-2026-001"]["requerimiento"], "REQ-2026-001")
        self.assertTrue(records["RAD-2026-001"]["documentos_drive"].startswith("https://"))

    def test_mobile_summary_includes_identity_fields_for_search(self):
        summary = extraer_resumen_expediente(
            {
                "radicado_padre": "RAD-2026-003",
                "cedula_propietario": "123456",
                "nit_empresa": "900123",
            }
        )

        self.assertEqual(summary["cedula_propietario"], "123456")
        self.assertEqual(summary["nit_empresa"], "900123")

    def test_rejects_demo_rows_in_operational_sheet(self):
        with self.assertRaisesRegex(RuntimeError, "Demo records"):
            _records_from_values(
                [
                    ["RAD PADRE", "PLACA"],
                    ["PRUEBA-001", "TST001"],
                ]
            )

    def test_requires_owner_email_before_accessing_sheets(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SISTEMA_WEB_OWNER_EMAIL"):
                cargar_expedientes_sheets()

    @patch.dict(
        os.environ,
        {
            "SISTEMA_GOOGLE_TOKEN_FILE": "missing-owner-token.json",
            "SISTEMA_WEB_OWNER_EMAIL": "owner@example.com",
            "SISTEMA_SPREADSHEET_ID": "spreadsheet-id",
        },
        clear=True,
    )
    def test_explains_how_to_create_the_missing_google_token(self):
        with self.assertRaisesRegex(RuntimeError, "Inicia sesión en el programa"):
            cargar_expedientes_sheets()

    @patch("mobile_api.expedientes._sheet_title", return_value="tabla_2")
    @patch("mobile_api.expedientes._google_get")
    @patch("mobile_api.expedientes._google_session")
    @patch.dict(
        os.environ,
        {
            "SISTEMA_WEB_OWNER_EMAIL": "owner@example.com",
            "SISTEMA_SPREADSHEET_ID": "spreadsheet-id",
        },
        clear=True,
    )
    def test_reads_authorized_owner_sheet_and_maps_rows(
        self,
        create_session,
        google_get,
        _sheet_title,
    ):
        create_session.return_value = object()
        google_get.side_effect = [
            {"email": "OWNER@example.com"},
            {
                "values": [
                    ["RAD PADRE", "PLACA"],
                    ["RAD-2026-002", "XYZ123"],
                ]
            },
        ]

        records = cargar_expedientes_sheets()

        self.assertEqual(records["RAD-2026-002"]["placa"], "XYZ123")
        self.assertEqual(google_get.call_count, 2)
        self.assertEqual(
            google_get.call_args.args[1],
            "https://sheets.googleapis.com/v4/spreadsheets/"
            "spreadsheet-id/values/tabla_2!A1:AZ2000",
        )

    @patch("mobile_api.expedientes._google_get", return_value={"email": "other@example.com"})
    @patch("mobile_api.expedientes._google_session")
    @patch.dict(
        os.environ,
        {
            "SISTEMA_WEB_OWNER_EMAIL": "owner@example.com",
            "SISTEMA_SPREADSHEET_ID": "spreadsheet-id",
        },
        clear=True,
    )
    def test_rejects_google_token_for_a_different_owner(
        self,
        _create_session,
        _google_get,
    ):
        with self.assertRaisesRegex(RuntimeError, "no pertenece"):
            cargar_expedientes_sheets()


if __name__ == "__main__":
    unittest.main()
