import io
import unittest
from unittest.mock import MagicMock, patch

import app_6


class UploadedFile:
    name = "expediente.pdf"

    def __init__(self, content):
        self._content = content

    def getvalue(self):
        return self._content


class TestDriveStaging(unittest.TestCase):
    def _drive_service(self, configured_folder):
        service = MagicMock()
        service.files().get.return_value.execute.return_value = configured_folder
        return service

    def test_configured_pdf_root_is_used_without_creating_a_nested_root(self):
        service = self._drive_service({
            "id": "pdfs-root",
            "name": "PDFS Escaneados",
            "parents": ["shared-root"],
        })
        with patch.object(app_6, "DRIVE_FOLDER_ID", "pdfs-root"):
            root = app_6.carpeta_primaria_documentos_drive(service)

        self.assertEqual(root, "pdfs-root")

    def test_resolves_legacy_pending_folder_id_to_its_document_root_parent(self):
        service = MagicMock()
        service.files().get.return_value.execute.side_effect = [
            {
                "id": "old-pending",
                "name": "Pendientes",
                "parents": ["pdfs-root"],
            },
            {
                "id": "pdfs-root",
                "name": "PDFS Escaneados",
            },
        ]
        with (
            patch.object(app_6, "DRIVE_FOLDER_ID", "old-pending"),
            patch.object(app_6, "buscar_carpeta_drive_por_nombres") as find_child,
        ):
            root = app_6.carpeta_primaria_documentos_drive(service)

        self.assertEqual(root, "pdfs-root")
        find_child.assert_not_called()

    def test_resolves_nested_duplicate_document_root_to_the_outer_root(self):
        service = MagicMock()
        service.files().get.return_value.execute.side_effect = [
            {
                "id": "nested-root",
                "name": "PDFS Escaneados",
                "parents": ["old-pending"],
            },
            {
                "id": "old-pending",
                "name": "Pendientes",
                "parents": ["outer-root"],
            },
            {
                "id": "outer-root",
                "name": "PDFS Escaneados",
            },
        ]
        with (
            patch.object(app_6, "DRIVE_FOLDER_ID", "nested-root"),
            patch.object(app_6, "buscar_carpeta_drive_por_nombres") as find_child,
        ):
            root = app_6.carpeta_primaria_documentos_drive(service)

        self.assertEqual(root, "outer-root")
        find_child.assert_not_called()

    def test_resolves_legacy_peticion_folder_id_to_its_document_root_parent(self):
        service = MagicMock()
        service.files().get.return_value.execute.side_effect = [
            {
                "id": "old-peticion",
                "name": "Peticion",
                "parents": ["pdfs-root"],
            },
            {
                "id": "pdfs-root",
                "name": "PDFS Escaneados",
            },
        ]
        with (
            patch.object(app_6, "DRIVE_FOLDER_ID", "old-peticion"),
            patch.object(app_6, "buscar_carpeta_drive_por_nombres") as find_child,
        ):
            root = app_6.carpeta_primaria_documentos_drive(service)

        self.assertEqual(root, "pdfs-root")
        find_child.assert_not_called()

    def test_invalid_drive_root_stops_instead_of_creating_a_duplicate_root(self):
        service = self._drive_service({
            "id": "shared-root",
            "name": "Shared with me",
            "parents": [],
        })
        with (
            patch.object(app_6, "DRIVE_FOLDER_ID", "shared-root"),
            patch.object(app_6, "buscar_carpeta_drive_por_nombres", return_value=None),
            patch.object(app_6, "buscar_o_crear_carpeta_drive") as create,
            patch.object(app_6.st, "error") as show_error,
        ):
            root = app_6.carpeta_primaria_documentos_drive(service)

        self.assertIsNone(root)
        create.assert_not_called()
        show_error.assert_called_once()

    def test_staging_uses_the_pending_folder_name(self):
        service = object()
        with (
            patch.object(app_6, "carpeta_primaria_documentos_drive", return_value="drive-root"),
            patch.object(app_6, "buscar_carpeta_drive_por_nombres", return_value=None),
            patch.object(app_6, "buscar_o_crear_carpeta_drive", return_value="pending-folder") as create,
        ):
            folder = app_6.carpeta_drive_para_peticiones(service)

        self.assertEqual(folder, "pending-folder")
        create.assert_called_once_with(service, "drive-root", "Pendientes")

    def test_resource_resolution_is_saved_with_resolutions(self):
        service = object()
        with patch.object(
            app_6,
            "buscar_o_crear_carpeta_drive",
            return_value="resolutions-folder",
        ) as create:
            folder = app_6.carpeta_drive_para_documento(
                service,
                "case-folder",
                "Resolución del recurso",
            )

        self.assertEqual(folder, "resolutions-folder")
        create.assert_called_once_with(
            service,
            "case-folder",
            "resolucion resuelve",
        )

    def test_unlinked_document_folder_names_keep_their_document_family(self):
        service = object()
        folder_names = {
            "peticion": "peticion",
            "consulta": "consulta",
            "resolucion resuelve": "resolucion resuelve",
            "citacion": "citacion",
            "notificacion": "notificacion",
            "recurso": "recurso",
            "constancia de ejecutoria": "constancia de ejecutoria",
            "remision": "remision",
            "otro": "Otro",
        }

        for folder_name, expected_destination in folder_names.items():
            with self.subTest(folder_name=folder_name), patch.object(
                app_6,
                "buscar_o_crear_carpeta_drive",
                return_value="destination-folder",
            ) as create:
                folder = app_6.carpeta_drive_para_documento(
                    service,
                    "case-folder",
                    folder_name,
                )

            self.assertEqual(folder, "destination-folder")
            create.assert_called_once_with(
                service,
                "case-folder",
                expected_destination,
            )

    def test_checklist_types_are_read_from_nonempty_drive_subfolders(self):
        service = MagicMock()
        service.files().list.return_value.execute.side_effect = [
            {
                "files": [
                    {"id": "petition-folder", "name": "peticion"},
                    {"id": "resolution-folder", "name": "resolucion resuelve"},
                    {"id": "empty-folder", "name": "recurso"},
                ]
            },
            {
                "files": [{
                    "name": "1202541730100462182_GVS914_2023-02-15_Solicitud.pdf",
                    "mimeType": "application/pdf",
                }]
            },
            {
                "files": [{
                    "name": "1202541730100462182_GVS914_2023-02-15_Resolución-del-recurso.pdf",
                    "mimeType": "application/pdf",
                }]
            },
            {"files": []},
        ]

        present = app_6.tipos_documentales_en_carpeta_drive(
            service,
            "case-folder",
        )

        self.assertEqual(present, {"Solicitud", "Resolución del recurso"})

    @unittest.skipIf(
        app_6.PdfReader is None or app_6.PdfWriter is None,
        "pypdf is required to test PDF splitting",
    )
    def test_splitter_keeps_continuations_and_removes_blank_pages(self):
        writer = app_6.PdfWriter()
        for _ in range(5):
            writer.add_blank_page(width=612, height=792)
        source = io.BytesIO()
        writer.write(source)
        metadata = [
            {"texto": "Derecho de petición solicitud de desvinculación"},
            {"texto": ""},
            {"texto": "Resolución que resuelve el acto administrativo"},
            {"texto": "", "pagina_blanca": True},
            {"texto": "Recurso de reposición interpuesto"},
        ]

        parts = app_6.separar_pdf_con_textos(
            source.getvalue(),
            "Otro",
            metadata,
        )

        self.assertEqual(
            [part["tipo"] for part in parts],
            ["Solicitud", "Resolución", "Recurso"],
        )
        self.assertEqual([part["paginas"] for part in parts], [2, 1, 1])
        self.assertEqual(
            [part["paginas_por_seccion"] for part in parts],
            [[1, 2], [3], [5]],
        )
        self.assertEqual(
            [
                len(app_6.PdfReader(io.BytesIO(part["contenido"])).pages)
                for part in parts
            ],
            [2, 1, 1],
        )

    @unittest.skipIf(app_6.fitz is None, "PyMuPDF is required to detect blank pages")
    def test_pdf_splitter_removes_real_blank_pages_and_preserves_document_groups(self):
        source = app_6.fitz.open()
        request = source.new_page(width=100, height=100)
        request.insert_text(
            (10, 20),
            "Derecho de peticion. Solicitud de desvinculacion.",
        )
        source.new_page(width=100, height=100)
        resolution = source.new_page(width=100, height=100)
        resolution.insert_text((10, 20), "Resolucion No. 123")
        resource = source.new_page(width=100, height=100)
        resource.insert_text((10, 20), "Recurso de reposicion")
        content = source.tobytes()
        source.close()

        with patch.object(
            app_6,
            "obtener_texto_ocr_pagina",
            return_value="",
        ) as ocr_page:
            parts = app_6.separar_pdf_completo(content, "Otro")

        self.assertEqual(ocr_page.call_count, 3)
        self.assertEqual(
            [part["tipo"] for part in parts],
            ["Solicitud", "Resolución", "Recurso"],
        )
        self.assertEqual([part["paginas"] for part in parts], [1, 1, 1])
        self.assertEqual(
            [part["paginas_por_seccion"] for part in parts],
            [[1], [3], [4]],
        )

    @unittest.skipIf(app_6.fitz is None, "PyMuPDF is required to test PDF splitting")
    def test_splitter_keeps_citations_notifications_resource_decisions_and_other_separate(self):
        source = app_6.fitz.open()
        citation = source.new_page(width=200, height=200)
        citation.insert_text(
            (10, 20),
            "Asunto: Citacion para notificacion personal. Sirvase comparecer.",
        )
        continuation = source.new_page(width=200, height=200)
        continuation.insert_text(
            (10, 20),
            "La resolucion referida debe consultarse en la sede administrativa.",
        )
        source.new_page(width=200, height=200)
        notification = source.new_page(width=200, height=200)
        notification.insert_text(
            (10, 20),
            "Asunto: Notificacion personal de acto administrativo. "
            "Se notifica la resolucion que resuelve un recurso de reposicion.",
        )
        resource_decision = source.new_page(width=200, height=200)
        resource_decision.insert_text(
            (10, 20),
            "Resolucion No. 4152. Por el cual se resuelve un recurso de reposicion.",
        )
        supporting_document = source.new_page(width=200, height=200)
        supporting_document.insert_text(
            (10, 20),
            "CONTRATODEVINCULACIONDEVEHICULO",
        )
        content = source.tobytes()
        source.close()

        with patch.object(app_6, "obtener_texto_ocr_pagina", return_value=""):
            parts = app_6.separar_pdf_completo(content, "Solicitud")

        self.assertEqual(
            [part["tipo"] for part in parts],
            [
                "Oficio de citación",
                "Notificación personal",
                "Resolución del recurso",
                "Otro",
            ],
        )
        self.assertEqual(
            [part["paginas_por_seccion"] for part in parts],
            [[1, 2], [4], [5], [6]],
        )

    def test_fragment_type_is_not_overwritten_by_text_from_another_document(self):
        self.assertEqual(
            app_6.tipo_documento_de_parte(
                "La Resolución No. 123 menciona el recurso presentado",
                "Recurso",
            ),
            "Recurso",
        )

    def test_generic_fragment_type_is_completed_from_its_own_text(self):
        self.assertEqual(
            app_6.tipo_documento_de_parte(
                "Consulta de verificación de propiedad del vehículo",
                "Otro",
            ),
            "Consulta QX",
        )

    def _prepare(self, full_pdf, parts, folders=None):
        uploads = []
        folders = folders or {}

        def upload(_service, file_buffer, file_name, folder_id):
            uploads.append((file_name, folder_id, file_buffer.getvalue()))
            return f"drive-{len(uploads)}", f"https://drive/{len(uploads)}"

        def document_folder(_service, _case_folder, type_name):
            return folders.get(type_name, "peticion-folder")

        key = app_6.huella_contenido(full_pdf)
        with (
            patch.object(app_6, "buscar_carpeta_expediente_drive", return_value=None),
            patch.object(app_6, "carpeta_drive_para_staging", return_value="pending-case"),
            patch.object(app_6, "preparar_subcarpetas_documentales", return_value={}),
            patch.object(
                app_6,
                "carpeta_drive_para_documento",
                side_effect=document_folder,
            ),
            patch.object(app_6, "buscar_archivo_drive", return_value=None),
            patch.object(app_6, "subir_archivo_a_drive", side_effect=upload),
            patch.object(app_6, "separar_pdf_completo", return_value=[]),
        ):
            documents, folder, error = app_6.preparar_carga_drive(
                object(),
                [UploadedFile(full_pdf)],
                "1202541730100462182",
                "GVS914",
                "2023-02-15",
                "Solicitud",
                "test-carga",
                partes_analizadas={key: parts},
            )
        return documents, folder, error, uploads

    def test_uploads_full_pdf_only_at_case_root_and_fragment_to_type_folder(self):
        full_pdf = b"%PDF-full-expediente"
        fragment = b"%PDF-solicitud-fragment"
        parts = [{
            "contenido": fragment,
            "tipo": "Solicitud",
            "paginas": 2,
            "paginas_por_seccion": [1, 2],
        }]

        documents, folder, error, uploads = self._prepare(full_pdf, parts)

        self.assertIsNone(error)
        self.assertEqual(folder, "pending-case")
        self.assertEqual(len(documents), 2)
        self.assertEqual(uploads[0][1:], ("pending-case", full_pdf))
        self.assertEqual(uploads[1][1:], ("peticion-folder", fragment))
        self.assertTrue(documents[0]["es_pdf_completo"])
        self.assertFalse(documents[1].get("es_pdf_completo", False))

    def test_fragment_names_keep_case_name_and_suffix_each_document_type(self):
        full_pdf = b"%PDF-full-expediente"
        parts = [
            {"contenido": b"%PDF-solicitud", "tipo": "Solicitud", "paginas": 1},
            {"contenido": b"%PDF-resolucion-a", "tipo": "Resolución", "paginas": 1},
            {"contenido": b"%PDF-resolucion-b", "tipo": "Resolución", "paginas": 1},
        ]

        documents, _folder, error, _uploads = self._prepare(full_pdf, parts)

        self.assertIsNone(error)
        self.assertEqual(
            [document["nombre"] for document in documents[1:]],
            [
                "1202541730100462182_GVS914_2023-02-15_Solicitud.pdf",
                "1202541730100462182_GVS914_2023-02-15_Resolución.pdf",
                "1202541730100462182_GVS914_2023-02-15_Resolución_02.pdf",
            ],
        )

    def test_each_fragment_is_uploaded_to_its_document_type_folder(self):
        documents, _folder, error, uploads = self._prepare(
            b"%PDF-full",
            [
                {"contenido": b"%PDF-request", "tipo": "Solicitud"},
                {"contenido": b"%PDF-resource", "tipo": "Recurso"},
            ],
            folders={
                "Solicitud": "petition-folder",
                "Recurso": "resource-folder",
            },
        )

        self.assertIsNone(error)
        self.assertEqual(
            [upload[1] for upload in uploads],
            ["pending-case", "petition-folder", "resource-folder"],
        )
        self.assertEqual(
            [document["drive_folder_id"] for document in documents[1:]],
            ["petition-folder", "resource-folder"],
        )

    def test_does_not_copy_full_pdf_into_document_folder_when_split_is_missing(self):
        full_pdf = b"%PDF-unsplit-expediente"

        documents, folder, error, uploads = self._prepare(full_pdf, [])

        self.assertEqual(folder, "pending-case")
        self.assertEqual(len(documents), 1)
        self.assertTrue(documents[0]["es_pdf_completo"])
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0][1:], ("pending-case", full_pdf))
        self.assertIn("no se copió dentro de ninguna subcarpeta", error)

    def test_does_not_treat_original_pdf_as_a_document_fragment(self):
        full_pdf = b"%PDF-original"
        parts = [{
            "contenido": full_pdf,
            "tipo": "Solicitud",
            "paginas": 10,
        }]

        documents, _folder, error, uploads = self._prepare(full_pdf, parts)

        self.assertEqual(len(documents), 1)
        self.assertTrue(documents[0]["es_pdf_completo"])
        self.assertEqual(len(uploads), 1)
        self.assertIn("no se copió dentro de ninguna subcarpeta", error)


if __name__ == "__main__":
    unittest.main()
