# Sistema de Desvinculaciones v1.1.21

## Corrección de empaquetado

- Incluye `document_rules.py` como dato del paquete PyInstaller.
- Declara `document_rules` como importación oculta para evitar fallos de
  importación al ejecutar el `.exe`.
- Verifica el arranque del ejecutable compilado y el endpoint de salud de
  Streamlit (`HTTP 200`, respuesta `ok`).

## Validación

- Pruebas de regresión: 7 aprobadas.
- Compilación Python: aprobada.
- Ejecutable compilado: generado correctamente.
- Arranque del ejecutable: aprobado.
- Endpoint local `http://127.0.0.1:8501/_stcore/health`: `200 / ok`.
