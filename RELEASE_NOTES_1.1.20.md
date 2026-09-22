# Sistema de Desvinculaciones v1.1.20

## Cambios

- Centralización de las reglas de clasificación documental y generación de
  nombres en `document_rules.py`.
- Corrección de la clasificación negativa de expedientes sin recurso.
- Pruebas de regresión para los tres desenlaces válidos:
  `Con recurso`, `Sin recurso` y `Desistimiento`.
- Pruebas para tipos documentales y nombres de expediente/PDF.
- `.gitignore` ampliado para evitar publicar credenciales, cachés, PDFs de
  prueba, binarios y artefactos de compilación.
- Documentación de validación y preparación para release actualizada.

## Validación

- `python -m unittest discover -s tests -v`: 7 pruebas aprobadas.
- `python -m py_compile app_6.py local_ai_service.py document_rules.py`:
  aprobado.
- `git diff --check`: aprobado.
- La interfaz Streamlit continúa respondiendo localmente en
  `http://127.0.0.1:8501/`.

## Publicación

La versión requiere generar y verificar el instalador antes de crear el
release de GitHub:

`installer/SistemaDesvinculaciones-Setup-1.1.20.exe`
