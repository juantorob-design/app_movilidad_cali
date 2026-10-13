import unittest

from app_6 import extraer_datos_pdf
from document_extraction import extraer_datos_desde_texto

from document_rules import (
    clasificar_tipo_caso,
    clasificar_tipo_documento,
    nombre_carpeta_expediente,
    nombre_pdf_expediente,
    normalizar_tipo_documental,
    tipos_documentales_detectados,
)


class TestDocumentRules(unittest.TestCase):
    def test_shared_extractor_returns_mobile_and_desktop_case_fields(self):
        text = (
            "Radicado padre: 202541520140874961. Placa: ABC-123. "
            "Fecha de solicitud: 11/06/2025. NIT: 8050135165."
        )
        expected = {
            "radicado_padre": "202541520140874961",
            "placa": "ABC123",
            "fecha_solicitud": "2025-06-11",
            "nit": "8050135165",
        }

        self.assertEqual(extraer_datos_desde_texto(text), expected)
        self.assertEqual(extraer_datos_pdf(b"", texto=text), expected)

    def test_extraer_datos_descarta_etiqueta_ocr_contaminada(self):
        datos = extraer_datos_pdf(
            b"",
            texto=(
                "PLACA GVS914 NIT 8050135165 "
                "PROPIETARIO s (1) Identificacion Doc Nombres Emp/Pan % Moroso 94379462"
            ),
        )
        self.assertEqual(datos["placa"], "GVS914")
        self.assertNotIn("propietario", datos)

    def test_clasifica_desistimiento(self):
        texto = "El interesado presenta desistimiento y no continúa con la solicitud."
        self.assertEqual(clasificar_tipo_caso(texto), "Desistimiento")

    def test_clasifica_con_recurso(self):
        texto = "Se interpuso recurso de reposición contra la resolución."
        self.assertEqual(clasificar_tipo_caso(texto), "Con recurso")

    def test_clasifica_sin_recurso(self):
        texto = "No se interpuso recurso y consta ejecutoria."
        self.assertEqual(clasificar_tipo_caso(texto), "Sin recurso")

    def test_positive_resource_evidence_takes_precedence_over_no_resource_phrase(self):
        texto = (
            "La constancia indica que no se interpuso recurso. "
            "Después se presentó recurso de reposición."
        )
        self.assertEqual(clasificar_tipo_caso(texto), "Con recurso")

    def test_identifica_tipo_documental(self):
        self.assertEqual(
            normalizar_tipo_documental("Resolución del recurso en el expediente"),
            "Resolución del recurso",
        )
        self.assertEqual(
            normalizar_tipo_documental("Notificacion por aviso"),
            "Notificación por aviso",
        )

    def test_detecta_tipos_documentales(self):
        texto = "Solicitud y resolución. Se interpuso recurso de reposición."
        tipos = tipos_documentales_detectados(texto, "Otro")
        self.assertIn("Solicitud", tipos)
        self.assertIn("Resolución", tipos)
        self.assertIn("Recurso", tipos)

    def test_generacion_de_nombres(self):
        self.assertEqual(
            nombre_carpeta_expediente("1202541730100462182", "ABC123", "2026-03-07", "CAJA-1/FOLDER-1/CARPETA-1"),
            "1202541730100462182_ABC123_2026-03-07_CAJA-1_FOLDER-1_CARPETA-1",
        )
        self.assertEqual(
            nombre_pdf_expediente("1202541730100462182", "ABC123", "2026-03-07", caja="CAJA-1", folder="FOLDER-1", carpeta="CARPETA-1"),
            "1202541730100462182_ABC123_2026-03-07_CAJA-1_FOLDER-1_CARPETA-1.pdf",
        )

    def test_clasifica_documento_por_patrones(self):
        self.assertEqual(
            clasificar_tipo_documento("oficio de citación al propietario", "Otro"),
            "Oficio de citación",
        )

    def test_classifies_a_resolution_that_decides_an_appeal_separately(self):
        self.assertEqual(
            clasificar_tipo_documento(
                "Resolución No. 4152.010.21.0.1894 de 2025. "
                "Por el cual se resuelve un recurso de reposición.",
                "Otro",
            ),
            "Resolución del recurso",
        )

    def test_classifies_request_from_its_reference_even_if_the_heading_is_ocr_noisy(self):
        self.assertEqual(
            clasificar_tipo_documento(
                "Santiago de Cali. REFERENCIA: SOLICITUD DESVINCULACION "
                "ADMINISTRATIVA DE VEHICULO.",
                "Otro",
            ),
            "Solicitud",
        )

    def test_classifies_main_resolution_even_when_its_body_mentions_notification(self):
        texto = (
            "Resolución No. 4152.01. Por la cual se resuelve la solicitud de "
            "desvinculación administrativa. "
            + "En cumplimiento de la normativa vigente y de las actuaciones "
            "administrativas previas, se revisaron los documentos aportados. " * 8
            + "La notificación personal del acto se surtirá después."
        )
        self.assertEqual(
            clasificar_tipo_documento(texto, "Otro"),
            "Resolución",
        )

    def test_citation_for_personal_notification_is_not_the_notification_itself(self):
        texto = (
            "Asunto: Citación para notificación personal. "
            "Sírvase comparecer para notificarse del contenido de la resolución."
        )
        self.assertEqual(
            clasificar_tipo_documento(texto, "Otro"),
            "Oficio de citación",
        )

    def test_notification_takes_priority_over_the_resolution_it_references(self):
        texto = (
            "Asunto: Notificación personal de acto administrativo. "
            "Se notifica personalmente la resolución que resuelve un recurso "
            "de reposición."
        )
        self.assertEqual(
            clasificar_tipo_documento(texto, "Otro"),
            "Notificación personal",
        )

    def test_compact_ocr_notification_subject_is_still_classified(self):
        self.assertEqual(
            clasificar_tipo_documento(
                "ASUNTO:NOTIFICACIONDEACTOADMINISTRATIVOQUERESUELVERECURSODEREPOSICION",
                "Otro",
            ),
            "Notificación",
        )

    def test_compact_ocr_personal_notification_header_is_classified(self):
        self.assertEqual(
            clasificar_tipo_documento(
                "NOTIFICACIONPERSONALexpedientededesvinculacionABC123",
                "Otro",
            ),
            "Notificación personal",
        )

    def test_classifies_subject_after_letter_metadata(self):
        texto = (
            "Al contestar por favor cite estos datos: Radicado No. 202541520140874961 "
            "Fecha 11-06-2025 TRD: 4152.014.13.1.2183.087496 Rad. Padre: 12345 "
            "Representante legal. Asunto: Notificación personal de acto administrativo."
        )
        self.assertEqual(
            clasificar_tipo_documento(texto, "Otro"),
            "Notificación personal",
        )

    def test_notice_by_publication_is_not_misclassified_by_its_personal_notice_reference(self):
        texto = (
            "Radicado No. 12345. ASUNTO: Notificación por aviso - la "
            "resolución No. 456. Al no haberse surtido la notificación personal "
            "dentro de los términos, se publica este aviso."
        )
        self.assertEqual(
            clasificar_tipo_documento(texto, "Otro"),
            "Notificación por aviso",
        )

    def test_contestation_of_a_resolution_is_classified_as_the_appeal(self):
        texto = (
            "Radicado No. 12345. Fecha 11-06-2025. REF. CONTESTACION "
            "RESOLUCION No. 4152.010.21.0.00794."
        )
        self.assertEqual(
            clasificar_tipo_documento(texto, "Otro"),
            "Recurso",
        )

    def test_compact_execution_certificate_takes_priority_over_its_resolution_reference(self):
        texto = (
            "42 CONSTANCIA DEEJECUTORIA. Hace constar que mediante Resolución "
            "No. 4152.010 se resolvió la solicitud de desvinculación."
        )
        self.assertEqual(
            clasificar_tipo_documento(texto, "Otro"),
            "Constancia de ejecutoria",
        )

    def test_compact_ocr_titles_for_supporting_documents_remain_other(self):
        for texto in (
            "CONTRATODEVINCULACIONDEVEHICULO",
            "IDENTIFICACIONPERSONAL CEDULA DE CIUDADANIA",
            "AUTORIZACIONDETRAMITES",
            "REPORTE DE ESTADO DE CUENTAS",
        ):
            with self.subTest(texto=texto):
                self.assertEqual(clasificar_tipo_documento(texto, "Solicitud"), "Otro")

    def test_references_to_a_resolution_do_not_classify_a_contract_as_a_resolution(self):
        self.assertEqual(
            clasificar_tipo_documento(
                "Contrato de vinculación de vehículo. Se anexa copia de la resolución.",
                "Otro",
            ),
            "Otro",
        )

    def test_classifies_a_resolution_by_its_number_and_decision_heading(self):
        self.assertEqual(
            clasificar_tipo_documento(
                "Resolución No. 4223.01.03.1614. RESUELVE: desvincular el vehículo.",
                "Otro",
            ),
            "Resolución",
        )

    def test_classifies_resolution_decision_and_fallo_headings(self):
        for texto in (
            "Resolución que resuelve el acto administrativo",
            "Resolución de fallo del proceso de desvinculación",
        ):
            with self.subTest(texto=texto):
                self.assertEqual(
                    clasificar_tipo_documento(texto, "Otro"),
                    "Resolución",
                )

    def test_identifies_supporting_documents_as_other(self):
        for texto in (
            "Cláusulas del contrato de vinculación",
            "Tarjeta de operación",
            "Licencia de tránsito",
        ):
            with self.subTest(texto=texto):
                self.assertEqual(
                    clasificar_tipo_documento(texto, "Solicitud"),
                    "Otro",
                )

    def test_weak_document_mention_keeps_the_continuation_fallback(self):
        self.assertEqual(
            clasificar_tipo_documento(
                "La solicitud menciona el recurso presentado anteriormente.",
                "Otro",
            ),
            "Otro",
        )


if __name__ == "__main__":
    unittest.main()
