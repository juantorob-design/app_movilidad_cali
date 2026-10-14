import unittest

from archive_status import expediente_completo, resumir_estado_archivo


class TestArchiveStatus(unittest.TestCase):
    def test_applies_desktop_completion_rule_to_operational_sheet_values(self):
        record = {
            "RAD PADRE": "RAD-001",
            "FECHA": "2026-01-01",
            "QX VERIFICADO": "SI",
            "RESOLUCION": "RES-001",
            "FECHA DESVINCULACION": "2026-01-02",
            "TIPO NOTIFICACION": "personal",
            "FECHA NOTIFICACION": "2026-01-03",
            "FECHA EJECUTORIA": "2026-01-04",
            "REMITIDO": "Sí",
            "FECHA REMISION REGISTRO": "2026-01-05",
        }

        self.assertTrue(expediente_completo(record))
        self.assertFalse(expediente_completo({**record, "REMITIDO": "NO"}))

    def test_summarizes_unique_cases_missing_documents_and_registered_files(self):
        records = [
            {
                "radicado_padre": "RAD-001",
                "qx_verificado": True,
                "remitido": True,
                "fecha_solicitud": "2026-01-01",
                "resolucion": "RES-001",
                "fecha_resolucion": "2026-01-02",
                "tipo_notificacion": "personal",
                "fecha_notificacion": "2026-01-03",
                "fecha_ejecutoria": "2026-01-04",
                "fecha_remision_registro": "2026-01-05",
                "documentos_faltantes_drive": "",
                "contenido_documental": "Solicitud: a.pdf | Resolución: b.pdf",
            },
            {
                **{
                    "radicado_padre": "RAD-001",
                    "qx_verificado": True,
                    "remitido": True,
                    "fecha_solicitud": "2026-01-01",
                    "resolucion": "RES-001",
                    "fecha_resolucion": "2026-01-02",
                    "tipo_notificacion": "personal",
                    "fecha_notificacion": "2026-01-03",
                    "fecha_ejecutoria": "2026-01-04",
                    "fecha_remision_registro": "2026-01-05",
                    "contenido_documental": "Solicitud: a.pdf | Resolución: b.pdf",
                },
                "RAD PADRE": "rad-001",
                "DOCUMENTOS FALTANTES": "Constancia de ejecutoria",
            },
            {
                "radicado_padre": "RAD-002",
                "documentos_faltantes_drive": "Notificación, Ejecutoria",
                "documentos_drive": "a.pdf -> https://drive.example/a | b.pdf -> https://drive.example/b",
            },
            {"radicado_padre": ""},
        ]

        self.assertEqual(
            resumir_estado_archivo(records),
            {
                "total_expedientes": 2,
                "completos": 1,
                "con_faltantes": 2,
                "documentos_registrados": 4,
            },
        )


if __name__ == "__main__":
    unittest.main()
