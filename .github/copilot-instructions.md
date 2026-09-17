# Instrucciones del proyecto: sistema de desvinculaciones

## Flujo administrativo obligatorio

Cuando el programa procese un expediente PDF, debe seguir este orden de análisis:

1. Solicitud o petición.
2. Consulta de verificación de propiedad del vehículo.
3. Resolución que resuelve el acto administrativo.
   - Si hay resolución, continuar con citación.
   - Si no hay resolución pero sí hay requerimiento, continuar con citación.
   - Si no hay requerimiento ni resolución, verificar si hay desistimiento.
4. Oficios de citación a empresa y propietario.
5. Comunicación:
   - Notificación personal.
   - Notificación por aviso.
   - Notificación por publicación web.
6. Si hay recurso, procesar:
   - Recurso.
   - Resolución del recurso.
   - Citación del recurso.
   - Notificación del recurso.
7. Constancia de ejecutoria.
8. Remisión a registro.

Solo existen tres finales válidos: `Con recurso`, `Sin recurso` o `Desistimiento`.

## Reglas para OCR, separación y guardado

- El OCR no debe leerse como un único bloque del expediente completo si hay documentos separados.
- Debe separar el PDF por bloques documentales antes de completar el formulario.
- Cada tipo documental debe guardarse en su carpeta correcta dentro de la estructura de Drive del expediente.
- La carpeta `Pendientes` solo se usa como staging temporal para cargas sin fecha definitiva.
- Una vez confirmada la fecha, la carpeta se mueve al año correspondiente y se conserva el PDF completo junto a los complementos.
- Los documentos de la misma familia se mantienen unidos en su subcarpeta; no se mezclan páginas de resolución, notificación, recurso o solicitud.
- Las páginas de continuación heredan el tipo del bloque anterior si no tienen suficiente evidencia.
- El nombre del expediente debe usar la convención: `RADICADO_PADRE_PLACA_FECHA_UBICACION`.
- El PDF completo se guarda con el nombre: `RADICADO_PADRE_PLACA_FECHA.pdf`.
- Los documentos individuales deben conservar el tipo documental y la ruta de origen para trazabilidad.

## Búsqueda y completado de datos en el formulario

- La IA debe priorizar los campos del formulario y buscar solo dentro de los documentos relevantes del expediente.
- La búsqueda de datos debe combinar: radicado padre, placa, NIT, empresa, cédula, propietario y fecha.
- Si un complemento aporta un dato faltante, debe completarse sin sobrescribir valores ya confirmados.
- La detección de tipos documentales debe reconocer documentos como `Consulta QX`, `Requerimiento`, `Oficio de citación`, `Resolución del recurso`, `Notificación personal`, `Notificación por aviso`, `Notificación por publicación web`.
- La clasificación no debe confundirse con un texto general del expediente; debe usar la secuencia administrativa como prioridad.

## Reglas de validación

- Si aparece resolución de desistimiento, clasificarlo como `Desistimiento`.
- Si aparece recurso o resolución del recurso, clasificarlo como `Con recurso`.
- Si no aparece recurso pero sí hay constancia de ejecutoria o resolución final, clasificarlo como `Sin recurso`.
- Todo lo que no corresponda al flujo principal debe quedarse en `Otro` y no reemplazar un documento principal.
