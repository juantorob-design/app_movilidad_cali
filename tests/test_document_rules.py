import unittest

from document_rules import (
    clasificar_tipo_caso,
    clasificar_tipo_documento,
    nombre_carpeta_expediente,
    nombre_pdf_expediente,
    normalizar_tipo_documental,
    tipos_documentales_detectados,
)


class TestDocumentRules(unittest.TestCase):
    def test_clasifica_desistimiento(self):
        texto = "El interesado presenta desistimiento y no continúa con la solicitud."
        self.assertEqual(clasificar_tipo_caso(texto), "Desistimiento")

    def test_clasifica_con_recurso(self):
        texto = "Se interpuso recurso de reposición contra la resolución."
        self.assertEqual(clasificar_tipo_caso(texto), "Con recurso")

    def test_clasifica_sin_recurso(self):
        texto = "No se interpuso recurso y consta ejecutoria."
        self.assertEqual(clasificar_tipo_caso(texto), "Sin recurso")

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


if __name__ == "__main__":
    unittest.main()
