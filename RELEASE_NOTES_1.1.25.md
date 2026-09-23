# Release 1.1.25

## IA local visual

- Integra Ollama Vision como analista principal para páginas escaneadas.
- Usa `qwen2.5vl:3b` por defecto para reducir consumo y tiempo de respuesta.
- Conserva `qwen2.5:7b` como modelo textual configurable mediante
  `SISTEMA_OLLAMA_TEXT_MODEL`.
- Envía a Ollama únicamente imágenes renderizadas y texto en `localhost`.
- Exige JSON estructurado con documentos, páginas, evidencia y faltantes.
- Mantiene OCR como respaldo explícito cuando la visión local no está disponible.

## Blindaje documental

- La IA no puede marcar un documento solo por una mención general dentro de otro.
- Las páginas y bloques se conservan para trazabilidad.
- Los valores contaminados por etiquetas de interfaz se rechazan antes de llenar el formulario.
- Los campos confirmados conservan prioridad sobre cualquier resultado automático.

## Validación

- 10 pruebas automatizadas OK.
- Modelo `qwen2.5vl:3b` instalado y confirmado con capacidad `vision`.
- Prueba real de una página PDF completada con respuesta JSON válida.
