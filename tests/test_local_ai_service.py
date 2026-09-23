import base64
import json
import unittest
from unittest.mock import patch

import local_ai_service


class TestLocalAIService(unittest.TestCase):
    def test_vision_payload_contains_ordered_images_without_data_prefix(self):
        resultado = {
            "tipo_caso": "Con recurso",
            "documentos_detectados": [
                {"tipo": "Solicitud", "paginas": [1], "paginas_o_evidencia": "Página 1"}
            ],
            "paginas_por_seccion": [{"tipo": "Solicitud", "paginas": [1]}],
            "faltantes": [],
        }

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": json.dumps(resultado)}}

        with patch.object(local_ai_service, "ollama_disponible", return_value=True), \
            patch.object(local_ai_service.requests, "post", return_value=Response()) as post:
            recibido = local_ai_service.analizar_paginas_local(
                [(1, b"pagina-uno"), (2, b"pagina-dos")],
                modelo="qwen2.5vl:7b",
            )

        payload = post.call_args.kwargs["json"]
        mensaje = payload["messages"][1]
        self.assertEqual(recibido["tipo_caso"], "Con recurso")
        self.assertEqual(mensaje["images"], [
            base64.b64encode(b"pagina-uno").decode("ascii"),
            base64.b64encode(b"pagina-dos").decode("ascii"),
        ])
        self.assertTrue(all(not imagen.startswith("data:") for imagen in mensaje["images"]))
        self.assertEqual(payload["model"], "qwen2.5vl:7b")

    def test_vision_rejects_empty_pages(self):
        with self.assertRaises(ValueError):
            local_ai_service.analizar_paginas_local([(1, b"")])

    def test_vision_rejects_invalid_schema(self):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": '{"faltantes": "no-es-lista"}'}}

        with patch.object(local_ai_service, "ollama_disponible", return_value=True), \
            patch.object(local_ai_service.requests, "post", return_value=Response()):
            with self.assertRaises(ValueError):
                local_ai_service.analizar_paginas_local([(1, b"pagina")])


if __name__ == "__main__":
    unittest.main()
