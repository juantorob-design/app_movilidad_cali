import unittest

from app_6 import contar_expedientes_en_filas_sheet


class TestSheetRecordCount(unittest.TestCase):
    def test_counts_unique_nonempty_parent_case_numbers(self):
        rows = [
            ["RAD PADRE", "PLACA"],
            ["RAD-001", "ABC123"],
            ["", "XYZ987"],
            ["RAD-002", "DEF456"],
            ["RAD-001", "ABC123"],
        ]

        self.assertEqual(contar_expedientes_en_filas_sheet(rows), 2)

    def test_accepts_parent_case_header_alias(self):
        self.assertEqual(
            contar_expedientes_en_filas_sheet(
                [
                    ["RADICADO PADRE", "PLACA"],
                    ["RAD-001", "ABC123"],
                ]
            ),
            1,
        )

    def test_returns_zero_for_a_valid_sheet_with_only_headers(self):
        self.assertEqual(
            contar_expedientes_en_filas_sheet([["RAD PADRE", "PLACA"]]),
            0,
        )

    def test_returns_none_when_sheet_cannot_be_counted(self):
        self.assertIsNone(contar_expedientes_en_filas_sheet([]))
        self.assertIsNone(
            contar_expedientes_en_filas_sheet([["PLACA"], ["ABC123"]])
        )


if __name__ == "__main__":
    unittest.main()
