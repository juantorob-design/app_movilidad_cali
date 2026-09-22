# Sistema de Desvinculaciones v1.1.22

## Corrección definitiva del ejecutable

- El archivo `document_rules.py` se incluye mediante ruta absoluta en la
  especificación de PyInstaller.
- El módulo queda disponible dentro de `_internal` en la distribución final.
- Se comprobó que el ejecutable inicia sin `ModuleNotFoundError`.
- Se comprobó la interfaz Streamlit y el escritorio principal después del
  arranque.

## Validación

- 7 pruebas de regresión aprobadas.
- Compilación Python aprobada.
- Ejecutable generado mediante reconstrucción limpia.
- `document_rules.py` presente dentro de `_internal`.
- Endpoint local: `HTTP 200`, respuesta `ok`.
- Interfaz principal cargada correctamente.
