# Sistema de Desvinculaciones - Versión 1.1.12

**Fecha de lanzamiento:** 16 de septiembre de 2026  
**Versión anterior:** 1.1.11  
**Plataforma:** Windows 64-bit  
**Tamaño del instalador:** ~28 MB  

---

## 🎯 Propósito

La versión **1.1.12** completa la funcionalidad integral del sistema de desvinculaciones con una consulta ampliada, normalización de datos de Google Sheets, deduplicación robusta y descripción detallada de todas las capacidades operativas.

---

## ✨ Novedades en esta versión

### 1. **Consulta unificada y búsqueda ampliada**
- Buscar expedientes por **7 criterios diferentes**:
  - Radicado Padre
  - Placa
  - Empresa
  - NIT
  - Cédula
  - Ubicación física
  - Fecha de solicitud
- Integración de resultados **locales y Google Sheets**.
- Deduplicación inteligente entre bases de datos.
- Búsqueda por coincidencia parcial (mayúsculas insensibles).

### 2. **Normalización de registros remotos**
- Los registros incompletos de Google Sheets se completan automáticamente con valores predeterminados.
- Evita errores al mostrar expedientes que no tengan campos locales como `canvas_paginas`, `estado` o `modificado_por`.
- Cada registro remoto se trata como una vista segura sin perder información.

### 3. **Deduplicación local/remota robusta**
- Usa **claves estables** que consideran:
  - Radicado padre (prioridad máxima).
  - ID de expediente.
  - Tupla de placa, fecha, empresa, NIT, cédula y ubicación.
- Previene mostrar dos veces el mismo expediente cuando aparece tanto localmente como en Sheets.
- Mantiene la integridad de datos sin duplicar filas.

### 4. **Menú lateral colapsado por defecto**
- La barra lateral de navegación comienza colapsada para maximizar el área de visualización.
- Sigue siendo completamente funcional y accesible.
- Mejora la experiencia visual de la interfaz.

---

## 🔧 Características técnicas incluidas

El sistema operativo integra todas las funcionalidades desarrolladas hasta esta versión:

### **OCR e ingesta de documentos**
- Lectura local de PDFs con RapidOCR + ONNX Runtime DirectML.
- Caché persistente de OCR (versión 3) para evitar reprocessamiento.
- Selección automática GPU (DirectML) o CPU según disponibilidad.
- Detección de escritura manuscrita con advertencia de dudas.
- Copias locales de documentos para visualización sin conexión.

### **Clasificación y separación documental**
- Detección automática de:
  - Solicitud
  - Resolución
  - Notificación
  - Recurso
  - Desistimiento
  - Constancia de ejecutoria
- Separación por páginas con índices y texto OCR asociado.
- Checklist según tipo de caso (Sin recurso, Con recurso, Desistimiento).

### **Visor integrado y edición**
- Visualización de PDF antes de guardar.
- Foliación editable (numeración de páginas).
- Barra de progreso que representa el tiempo real de procesamiento.
- Editor PDF local independiente para unir, dividir, extraer, ordenar y rotar documentos.

### **Formulario administrativo inteligente**
- Precarga desde:
  - OCR del documento.
  - Base de datos local (si el expediente existe).
  - Google Sheets (si existe registro remoto).
- **Prioridad:** El formulario confirmado por el registrador nunca se sobrescribe.
- Ubicación física manual obligatoria.
- Validación y advertencia para radicados dudosos.

### **Organización en Google Drive**
- Estructura: `Peticion/Pendientes/AÑO` para staging.
- Carpeta final: `RADICADO_PADRE_PLACA_FECHA_UBICACION`.
- PDF completo: `RADICADO_PADRE_PLACA_FECHA.pdf`.
- Complementos en subcarpetas por tipo documental.
- Deduplicación automática por nombre y contenido.
- Consolidación de carpetas temporales.

### **Google Sheets con trazabilidad**
- 21 columnas administrativas y documentales.
- Lectura de registros existentes.
- Escritura de filas nuevas o actualización de existentes.
- Filtros, formato de encabezado y ajuste automático de columnas.
- Tabla congelada en la fila 1.
- Enlaces directos a Drive y PDF unificados.

### **Control de acceso y auditoría**
- **4 roles:**
  - Super Administrador (gestión total).
  - Administrador (operación y reporte).
  - Modificador (carga y edición).
  - Visualizador (lectura).
- Solicitudes de descarga para usuarios sin permiso.
- Auditoría de acciones y cambios.
- Autenticación local y Google OAuth.

### **Bandeja de pendientes**
- PDFs sin expediente principal se guardan en `Peticion/Pendientes`.
- Identificados por radicado o placa.
- Asociación posterior cuando aparezca la petición.
- Unión automática al expediente.

### **Actualizador autorizado**
- Consulta `version.json` en GitHub Raw.
- Descarga solo con autorización explícita del usuario.
- PowerShell con elevación para instalación silenciosa.
- Reinicio automático de la aplicación.

---

## 📋 Cambios en archivos

- **app_6.py** (+678 líneas, -136 líneas)
  - Consulta ampliada con 7 criterios.
  - Normalización de registros incompletos.
  - Deduplicación robusta local/remota.
  - Menú lateral colapsado por defecto.

- **updater.py** (1 línea)
  - Versión actualizada a `1.1.12`.

- **installer.iss** (1 línea)
  - Versión del instalador `1.1.12`.

- **version.json** (3 líneas)
  - Referencia a `1.1.12`.
  - Changelog completo.

- **presentacion_dashboard.py** (+10 líneas)
  - Descripción ampliada de novedades.
  - Referencia a consulta unificada.
  - Actualización de ruta `Peticion/Pendientes`.

- **docs/INFORME_APLICACION.md** (+4 líneas)
  - Versión y referencias actualizadas.

---

## ✅ Validaciones completadas

| Prueba | Resultado | Detalles |
|--------|-----------|----------|
| Compilación Python | ✅ APROBADA | `py_compile` sin errores |
| Formato de código | ✅ APROBADA | `git diff --check` limpio |
| AppTest Streamlit | ✅ APROBADA | `app_6.py` y `presentacion_dashboard.py` |
| Búsqueda local | ✅ APROBADA | 7 criterios implementados |
| Búsqueda remota simulada | ✅ APROBADA | Mock de Google Sheets |
| Normalización de registros | ✅ APROBADA | Campos predeterminados completados |
| Deduplicación | ✅ APROBADA | Claves estables sin duplicados |
| Empaquetado PyInstaller | ✅ APROBADA | Ejecutable de 27.8 MB |
| Arranque del ejecutable | ✅ APROBADA | Proceso activo y respondiendo |
| Sintaxis de configuración | ✅ APROBADA | `version.json`, `updater.py`, `installer.iss` |

---

## 🚀 Instalación

1. Descargar `SistemaDesvinculaciones-Setup-1.1.12.exe`.
2. Ejecutar con permisos de administrador.
3. Completar el asistente de instalación.
4. Abrir la aplicación desde el escritorio.

**Nota:** El actualizador buscará esta versión en GitHub Raw. Asegúrese de que `version.json` esté publicado en la rama `main`.

---

## 📝 Notas de compatibilidad

- **Anterior a 1.1.11:** Se recomienda una instalación limpia para evitar conflictos de caché OCR.
- **Desde 1.1.11:** Actualización segura; se conservan expedientes, Google Drive y Google Sheets.
- **Python requerido:** 3.12.x (incluido en el instalador).
- **Dependencias críticas:**
  - RapidOCR 1.4.4
  - ONNX Runtime DirectML 1.24.4
  - Streamlit 1.28.x
  - PySide6 para visualización de escritorio.

---

## 🔐 Seguridad

- No se publican tokens de OAuth, credenciales ni datos de usuarios.
- Los expedientes quedan en Drive y Sheets del organismo; no se envían a servicios externos.
- El editor PDF local trabaja en equipo sin subir archivos a internet.
- Actualizador validado contra GitHub con HTTPS.

---

## 📞 Soporte

Para reportar problemas, contacte al desarrollador o abra un issue en el repositorio:

[GitHub - juantorob-design/app_movilidad_cali](https://github.com/juantorob-design/app_movilidad_cali)

---

**Versión:** 1.1.12  
**Compilada:** 16 de septiembre de 2026  
**Estado:** Listo para distribución  
