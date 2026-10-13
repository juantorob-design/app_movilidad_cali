import io
import os
import unittest
from unittest.mock import patch

import fitz
from fastapi import UploadFile

from mobile_api import drive, main
from mobile_api.documents import separar_pdf
from mobile_api.expedientes import _google_session, guardar_expediente_sheets


class TestMobileApiSheetsWrites(unittest.TestCase):
    base_environment = {
        "SISTEMA_WEB_OWNER_EMAIL": "owner@example.com",
        "SISTEMA_SPREADSHEET_ID": "sheet-id",
    }
    create_payload = {
        "radicado_padre": "RAD-2026-010",
        "fecha_solicitud": "2026-03-01",
        "placa": "ABC123",
        "caso": "Sin recurso",
    }

    def test_requires_declared_scopes_in_the_server_oauth_token(self):
        with (
            patch.dict(os.environ, {"SISTEMA_GOOGLE_TOKEN_FILE": "authorized-token.json"}, clear=True),
            patch("mobile_api.expedientes.os.path.isfile", return_value=True),
            patch(
                "mobile_api.expedientes.Credentials.from_authorized_user_file",
                return_value=type("CredentialsWithoutScopes", (), {"scopes": None})(),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "permisos de Google Sheets"):
                _google_session()

    def test_creates_a_case_by_appending_only_mapped_values(self):
        headers = [["RAD PADRE", "FECHA SOLICITUD", "PLACA", "TIPO CASO"]]
        with (
            patch.dict(os.environ, self.base_environment, clear=True),
            patch("mobile_api.expedientes.google_session_for_owner"),
            patch("mobile_api.expedientes._sheet_title", return_value="tabla_2"),
            patch("mobile_api.expedientes._google_get", return_value={"values": headers}),
            patch("mobile_api.expedientes._write_sheet_values") as write_values,
        ):
            result = guardar_expediente_sheets(self.create_payload)

        self.assertEqual(result["radicado_padre"], "RAD-2026-010")
        self.assertEqual(write_values.call_args.args[2], "'tabla_2'!A:D")
        self.assertEqual(
            write_values.call_args.args[3],
            [["RAD-2026-010", "2026-03-01", "ABC123", "Sin recurso"]],
        )
        self.assertTrue(write_values.call_args.kwargs["append"])

    def test_creates_a_case_without_a_preselected_final_classification(self):
        payload = {key: value for key, value in self.create_payload.items() if key != "caso"}
        with (
            patch.dict(os.environ, self.base_environment, clear=True),
            patch("mobile_api.expedientes.google_session_for_owner"),
            patch("mobile_api.expedientes._sheet_title", return_value="tabla_2"),
            patch(
                "mobile_api.expedientes._google_get",
                return_value={"values": [["RAD PADRE", "FECHA SOLICITUD", "PLACA"]]},
            ),
            patch("mobile_api.expedientes._write_sheet_values") as write_values,
        ):
            result = guardar_expediente_sheets(payload)

        self.assertEqual(result["expediente"], payload)
        self.assertEqual(
            write_values.call_args.args[3],
            [["RAD-2026-010", "2026-03-01", "ABC123"]],
        )

    def test_updates_only_the_matching_row_and_preserves_other_cells(self):
        values = {
            "values": [
                ["RAD PADRE", "FECHA SOLICITUD", "PLACA", "TIPO CASO", "OBSERVACIONES"],
                ["RAD-2026-010", "2026-03-01", "ABC123", "Sin recurso", "No modificar"],
            ]
        }
        payload = {
            "radicado_padre": "RAD-2026-010",
            "fecha_solicitud": "2026-03-01",
            "placa": "ABC123",
            "caso": "Con recurso",
        }
        with (
            patch.dict(os.environ, self.base_environment, clear=True),
            patch("mobile_api.expedientes.google_session_for_owner"),
            patch("mobile_api.expedientes._sheet_title", return_value="tabla_2"),
            patch("mobile_api.expedientes._google_get", return_value=values),
            patch("mobile_api.expedientes._write_sheet_cells") as write_cells,
        ):
            guardar_expediente_sheets(payload, radicado_existente="RAD-2026-010")

        self.assertEqual(
            write_cells.call_args.args[2],
            [
                {"range": "'tabla_2'!A2", "values": [["RAD-2026-010"]]},
                {"range": "'tabla_2'!B2", "values": [["2026-03-01"]]},
                {"range": "'tabla_2'!C2", "values": [["ABC123"]]},
                {"range": "'tabla_2'!D2", "values": [["Con recurso"]]},
            ],
        )
        self.assertNotIn("OBSERVACIONES", str(write_cells.call_args.args[2]))

    def test_refuses_to_write_when_a_requested_sheet_column_is_missing(self):
        with (
            patch.dict(os.environ, self.base_environment, clear=True),
            patch("mobile_api.expedientes.google_session_for_owner"),
            patch("mobile_api.expedientes._sheet_title", return_value="tabla_2"),
            patch(
                "mobile_api.expedientes._google_get",
                return_value={"values": [["RAD PADRE", "FECHA SOLICITUD", "PLACA"]]},
            ),
            patch("mobile_api.expedientes._write_sheet_values") as write_values,
        ):
            with self.assertRaisesRegex(RuntimeError, "caso"):
                guardar_expediente_sheets(self.create_payload)

        write_values.assert_not_called()

    def test_rejects_duplicate_parent_numbers(self):
        values = {
            "values": [
                ["RAD PADRE", "FECHA SOLICITUD", "PLACA", "TIPO CASO"],
                ["RAD-2026-010", "2026-03-01", "ABC123", "Sin recurso"],
            ]
        }
        with (
            patch.dict(os.environ, self.base_environment, clear=True),
            patch("mobile_api.expedientes.google_session_for_owner"),
            patch("mobile_api.expedientes._sheet_title", return_value="tabla_2"),
            patch("mobile_api.expedientes._google_get", return_value=values),
            patch("mobile_api.expedientes._write_sheet_values") as write_values,
        ):
            with self.assertRaises(FileExistsError):
                guardar_expediente_sheets(self.create_payload)
        write_values.assert_not_called()


class TestMobileApiDocumentWorkflow(unittest.TestCase):
    def test_final_classification_uses_desistimiento_resource_or_executoria_evidence(self):
        evidence = [
            ("La resolución declara el desistimiento de la solicitud.", "Desistimiento"),
            ("El interesado interpuso recurso de reposición.", "Con recurso"),
            ("Constancia de ejecutoria de la resolución administrativa.", "Sin recurso"),
            ("Solicitud de información y anexos generales.", ""),
            ("El interesado presentó desistimiento y no continuó con la solicitud.", ""),
            (
                "El interesado menciona desistimiento, pero interpuso recurso de reposición.",
                "Con recurso",
            ),
        ]
        for text, expected in evidence:
            with self.subTest(expected=expected):
                source = fitz.open()
                source.new_page().insert_text((50, 80), text)
                result = separar_pdf(source.tobytes())
                source.close()
                self.assertEqual(result["clasificacion_final"], expected)

    def test_pdf_is_split_by_document_type_and_continuation_pages_stay_together(self):
        source = fitz.open()
        first = source.new_page()
        first.insert_text(
            (50, 80),
            "DERECHO DE PETICION Solicitud de desvinculacion de vehiculo ABC123",
        )
        continuation = source.new_page()
        continuation.insert_text((50, 80), "Continuacion de los argumentos de la solicitud.")
        resolution = source.new_page()
        resolution.insert_text(
            (50, 80),
            "RESOLUCION No 999 por la cual se resuelve la solicitud de desvinculacion",
        )

        result = separar_pdf(source.tobytes())

        self.assertEqual(
            [(block["tipo_documento"], block["paginas"]) for block in result["bloques"]],
            [("Solicitud", [1, 2]), ("Resolución", [3])],
        )
        source.close()

    def test_scanned_pdf_retries_ocr_at_higher_resolution_if_classification_is_unknown(self):
        source = fitz.open()
        page = source.new_page(width=595, height=842)
        page.insert_text(
            (50, 80),
            "NOTIFICACION PERSONAL expediente de desvinculacion ABC123",
            fontsize=16,
        )
        image = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png")
        scanned = fitz.open()
        scanned_page = scanned.new_page(width=595, height=842)
        scanned_page.insert_image(scanned_page.rect, stream=image)

        result = separar_pdf(scanned.tobytes())

        self.assertEqual(result["paginas_ocr"], 1)
        self.assertEqual(result["bloques"][0]["tipo_documento"], "Notificación personal")
        source.close()
        scanned.close()

    def test_drive_date_normalizer_accepts_sheet_display_dates(self):
        self.assertEqual(drive.normalizar_fecha("01/03/2026"), "2026-03-01")
        with self.assertRaises(ValueError):
            drive.normalizar_fecha("fecha pendiente")

    def test_upload_splits_pdf_and_saves_original_and_blocks(self):
        case = {
            "radicado_padre": "RAD-2026-010",
            "placa": "ABC123",
            "fecha_solicitud": "01/03/2026",
            "ubicacion": "",
        }
        blocks = [
            {
                "tipo_documento": "Solicitud",
                "contenido": b"%PDF-block-1",
                "paginas": [1],
            },
            {
                "tipo_documento": "Resolución",
                "contenido": b"%PDF-block-2",
                "paginas": [2],
            },
        ]
        uploads = []

        def record_upload(_session, parent_id, filename, content, kind, **metadata):
            uploads.append((parent_id, filename, content, kind, metadata))
            return {"name": filename, "webViewLink": f"https://drive/{filename}"}

        upload = UploadFile(file=io.BytesIO(b"%PDF-document"), filename="expediente.pdf")
        with (
            patch.object(main, "validar_pdf", return_value=(True, "OK")),
            patch.object(main, "cargar_expedientes_configurados", return_value={case["radicado_padre"]: case}),
            patch.object(main, "google_session_for_owner", return_value=object()),
            patch.object(main, "expediente_folder", return_value=("folder-1", "case-folder")),
            patch.object(main, "document_folder", side_effect=["request-folder", "resolution-folder"]),
            patch.object(main, "upload_pdf", side_effect=record_upload),
            patch.object(main, "separar_pdf", return_value={"bloques": blocks, "paginas": 2, "paginas_ocr": 1}),
        ):
            result = main.subir_pdf_expediente(
                "RAD-2026-010",
                {"role": "Modificador"},
                upload,
                tipo_documento="Otro",
            )

        self.assertEqual(len(uploads), 3)
        self.assertEqual(uploads[0][1], "RAD-2026-010_ABC123_2026-03-01.pdf")
        self.assertEqual(
            uploads[1][4],
            {
                "source_filename": "expediente.pdf",
                "source_pages": [1],
                "pending_batch_id": "",
            },
        )
        self.assertEqual([block["tipo_documento"] for block in result["bloques"]], ["Solicitud", "Resolución"])
        self.assertEqual(result["bloques"][0]["paginas"], [1])
        self.assertFalse(result["pendiente_vinculacion"])
        self.assertTrue(upload.file.closed)

    def test_upload_saves_detected_classification_only_when_case_is_unclassified(self):
        case = {
            "radicado_padre": "RAD-2026-010",
            "placa": "ABC123",
            "fecha_solicitud": "01/03/2026",
            "ubicacion": "",
        }
        upload = UploadFile(file=io.BytesIO(b"%PDF-document"), filename="expediente.pdf")
        with (
            patch.object(main, "validar_pdf", return_value=(True, "OK")),
            patch.object(
                main,
                "cargar_expedientes_configurados",
                return_value={case["radicado_padre"]: case},
            ),
            patch.object(main, "google_session_for_owner", return_value=object()),
            patch.object(main, "expediente_folder", return_value=("folder-1", "case-folder")),
            patch.object(main, "upload_pdf", side_effect=lambda _s, _p, name, *_a, **_k: {"name": name}),
            patch.object(
                main,
                "separar_pdf",
                return_value={
                    "bloques": [],
                    "paginas": 1,
                    "paginas_ocr": 0,
                    "clasificacion_final": "Desistimiento",
                },
            ),
            patch.object(main, "guardar_expediente_sheets") as save_case,
        ):
            result = main.subir_pdf_expediente(
                "RAD-2026-010",
                {"role": "Modificador"},
                upload,
                tipo_documento="Otro",
            )

        save_case.assert_called_once_with(
            {
                "radicado_padre": "RAD-2026-010",
                "fecha_solicitud": "2026-03-01",
                "placa": "ABC123",
                "caso": "Desistimiento",
            },
            radicado_existente="RAD-2026-010",
        )
        self.assertEqual(result["clasificacion_final"], "Desistimiento")
        self.assertTrue(result["clasificacion_actualizada"])

    def test_upload_does_not_overwrite_a_confirmed_classification(self):
        case = {
            "radicado_padre": "RAD-2026-010",
            "placa": "ABC123",
            "fecha_solicitud": "01/03/2026",
            "ubicacion": "",
            "caso": "Sin recurso",
        }
        upload = UploadFile(file=io.BytesIO(b"%PDF-document"), filename="expediente.pdf")
        with (
            patch.object(main, "validar_pdf", return_value=(True, "OK")),
            patch.object(
                main,
                "cargar_expedientes_configurados",
                return_value={case["radicado_padre"]: case},
            ),
            patch.object(main, "google_session_for_owner", return_value=object()),
            patch.object(main, "expediente_folder", return_value=("folder-1", "case-folder")),
            patch.object(main, "upload_pdf", side_effect=lambda _s, _p, name, *_a, **_k: {"name": name}),
            patch.object(
                main,
                "separar_pdf",
                return_value={
                    "bloques": [],
                    "paginas": 1,
                    "paginas_ocr": 0,
                    "clasificacion_final": "Con recurso",
                },
            ),
            patch.object(main, "guardar_expediente_sheets") as save_case,
        ):
            result = main.subir_pdf_expediente(
                "RAD-2026-010",
                {"role": "Modificador"},
                upload,
                tipo_documento="Otro",
            )

        save_case.assert_not_called()
        self.assertEqual(result["clasificacion_sugerida"], "Con recurso")
        self.assertEqual(result["clasificacion_final"], "Sin recurso")
        self.assertFalse(result["clasificacion_actualizada"])

    def test_unlinked_complement_is_staged_by_vehicle_plate(self):
        upload = UploadFile(file=io.BytesIO(b"%PDF-document"), filename="complemento.pdf")
        with (
            patch.object(main, "validar_pdf", return_value=(True, "OK")),
            patch.object(main, "cargar_expedientes_configurados", return_value={}),
            patch.object(main, "google_session_for_owner", return_value=object()),
            patch.object(main, "pending_document_folder", return_value="pending-plate-folder") as pending_folder,
            patch.object(main, "document_folder", return_value="other-folder"),
            patch.object(
                main,
                "upload_pdf",
                side_effect=lambda _s, _p, name, *_args, **_kwargs: {"name": name},
            ),
            patch.object(main, "separar_pdf", return_value={"bloques": [], "paginas": 1, "paginas_ocr": 0}),
        ):
            result = main.subir_pdf_expediente(
                "PENDIENTE",
                {"role": "Modificador"},
                upload,
                tipo_documento="Otro",
                placa_complemento="abc123",
                complemento_sin_vincular=True,
            )

        pending_folder.assert_called_once_with(
            unittest.mock.ANY,
            "PENDIENTE",
            "ABC123",
            "",
            is_unlinked_complement=True,
            batch_id=unittest.mock.ANY,
        )
        self.assertTrue(result["pendiente_vinculacion"])
        self.assertEqual(result["pdf_completo"]["nombre"], "COMPLEMENTO_ABC123_Pendiente.pdf")
        self.assertEqual(result["lote_pendiente"], pending_folder.call_args.kwargs["batch_id"])

    def test_linking_pending_complement_moves_original_and_typed_pages(self):
        def find_child(_session, parent_id, name):
            return {
                ("root", "Pendientes"): {"id": "pending"},
                ("pending", "Por_vincular"): {"id": "unlinked"},
                ("unlinked", "ABC123"): {"id": "plate"},
                ("plate", "COMPLEMENTO_batch-1"): {"id": "batch-1"},
            }.get((parent_id, name))

        def list_children(_session, parent_id):
            return {
                "batch-1": [
                    {"id": "full-pdf", "mimeType": "application/pdf"},
                    {"id": "petition-folder", "mimeType": drive.FOLDER_MIME_TYPE},
                ],
                "petition-folder": [
                    {
                        "id": "petition-pdf",
                        "mimeType": "application/pdf",
                        "appProperties": {"documentType": "Solicitud"},
                    }
                ],
            }[parent_id]

        moved = []
        with (
            patch.object(drive, "_documents_root", return_value="root"),
            patch.object(drive, "_find_child", side_effect=find_child),
            patch.object(
                drive,
                "listar_complementos_pendientes",
                return_value=[{"id": "batch-1", "nombre": "COMPLEMENTO_batch-1", "archivos": []}],
            ),
            patch.object(drive, "_list_children", side_effect=list_children),
            patch.object(drive, "document_folder", return_value="petition-destination"),
            patch.object(
                drive,
                "_move_file",
                side_effect=lambda _s, file_id, dest, _action: moved.append((file_id, dest)),
            ),
        ):
            result = drive.vincular_complemento_pendiente(
                object(),
                "ABC123",
                "batch-1",
                "case-folder",
            )

        self.assertEqual(
            moved,
            [("full-pdf", "case-folder"), ("petition-pdf", "petition-destination")],
        )
        self.assertEqual(result["archivos_vinculados"], 2)

    def test_linking_pending_complement_fills_an_empty_final_classification(self):
        case = {
            "radicado_padre": "RAD-2026-010",
            "placa": "ABC123",
            "fecha_solicitud": "01/03/2026",
            "ubicacion": "",
            "caso": "",
        }
        with (
            patch.object(main, "cargar_expedientes_configurados", return_value={"RAD-2026-010": case}),
            patch.object(main, "_find_case", return_value=case),
            patch.object(main, "google_session_for_owner", return_value=object()),
            patch.object(main, "expediente_folder", return_value=("folder-1", "case-folder")),
            patch.object(
                main,
                "vincular_complemento_pendiente",
                return_value={
                    "archivos_vinculados": 2,
                    "batch_id": "batch-1",
                    "clasificacion_sugerida": "Con recurso",
                },
            ),
            patch.object(main, "guardar_expediente_sheets") as save_case,
        ):
            result = main.vincular_complemento(
                "RAD-2026-010",
                {"lote_pendiente": "batch-1"},
                {"role": "Modificador"},
            )

        save_case.assert_called_once_with(
            {
                "radicado_padre": "RAD-2026-010",
                "fecha_solicitud": "2026-03-01",
                "placa": "ABC123",
                "caso": "Con recurso",
            },
            radicado_existente="RAD-2026-010",
        )
        self.assertEqual(result["clasificacion_final"], "Con recurso")
        self.assertTrue(result["clasificacion_actualizada"])

    def test_linking_pending_complement_preserves_an_existing_classification(self):
        case = {
            "radicado_padre": "RAD-2026-010",
            "placa": "ABC123",
            "fecha_solicitud": "01/03/2026",
            "ubicacion": "",
            "caso": "Sin recurso",
        }
        with (
            patch.object(main, "cargar_expedientes_configurados", return_value={"RAD-2026-010": case}),
            patch.object(main, "_find_case", return_value=case),
            patch.object(main, "google_session_for_owner", return_value=object()),
            patch.object(main, "expediente_folder", return_value=("folder-1", "case-folder")),
            patch.object(
                main,
                "vincular_complemento_pendiente",
                return_value={
                    "archivos_vinculados": 2,
                    "batch_id": "batch-1",
                    "clasificacion_sugerida": "Con recurso",
                },
            ),
            patch.object(main, "guardar_expediente_sheets") as save_case,
        ):
            result = main.vincular_complemento(
                "RAD-2026-010",
                {"lote_pendiente": "batch-1"},
                {"role": "Modificador"},
            )

        save_case.assert_not_called()
        self.assertEqual(result["clasificacion_final"], "Sin recurso")
        self.assertFalse(result["clasificacion_actualizada"])

    def test_partial_pending_link_reports_progress_instead_of_success(self):
        def find_child(_session, parent_id, name):
            return {
                ("root", "Pendientes"): {"id": "pending"},
                ("pending", "Por_vincular"): {"id": "unlinked"},
                ("unlinked", "ABC123"): {"id": "plate"},
                ("plate", "COMPLEMENTO_batch-1"): {"id": "batch-1"},
            }.get((parent_id, name))

        files = [
            {"id": "full-pdf", "mimeType": "application/pdf"},
            {"id": "support-pdf", "mimeType": "application/pdf"},
        ]
        with (
            patch.object(drive, "_documents_root", return_value="root"),
            patch.object(drive, "_find_child", side_effect=find_child),
            patch.object(
                drive,
                "listar_complementos_pendientes",
                return_value=[{"id": "batch-1", "nombre": "COMPLEMENTO_batch-1", "archivos": []}],
            ),
            patch.object(
                drive,
                "_list_children",
                side_effect=lambda _s, _id: files if _id == "batch-1" else [],
            ),
            patch.object(
                drive,
                "_move_file",
                side_effect=[None, RuntimeError("Drive denied the second move")],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "vinculó 1 de 2 archivos"):
                drive.vincular_complemento_pendiente(
                    object(),
                    "ABC123",
                    "batch-1",
                    "case-folder",
                )


if __name__ == "__main__":
    unittest.main()
