# Release 1.1.26

## Corrección de persistencia de IA

- Conserva los campos extraídos por Ollama Vision al volver a ejecutar Streamlit.
- Evita que los datos detectados por lotes de páginas desaparezcan antes de guardar.
- Mantiene la evidencia por página, documentos detectados y faltantes.

## Validación

- Pruebas automatizadas: 10/10.
- Ejecutable iniciado correctamente con health check HTTP 200.
- Ollama Vision `qwen2.5vl:3b` respondió con JSON válido en una página real.
