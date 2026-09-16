# Instrucciones prioritarias para el registro

## Lectura y separación del expediente

1. Todo PDF cargado debe leerse completo, página por página, con texto digital y
   OCR como respaldo.
2. El sistema debe separar los bloques documentales que reconozca: Solicitud o
   Petición, Recurso, Resolución, Notificación, Constancia de ejecutoria,
   Desistimiento y otros soportes.
3. La clasificación del caso debe reconocer exactamente uno de estos estados:
   `Con recurso`, `Sin recurso` o `Desistimiento`.
4. Una resolución que diga que se declara el desistimiento se clasifica como
   `Desistimiento`, aunque también contenga las palabras Resolución o
   Notificación.
5. La información detectada debe precargar el registro antes de guardar. Si un
   complemento aporta un dato que faltaba, debe completar el registro sin borrar
   los datos ya confirmados.
6. La separación debe clasificar cada página por evidencia priorizada. Los
   títulos de solicitud, resolución, notificación, recurso, desistimiento y
   ejecutoria tienen prioridad sobre menciones secundarias. Las páginas de
   continuación heredan el complemento anterior cuando no contienen texto
   suficiente, evitando enviarlas innecesariamente a `Otro`.

## Datos mínimos del registro

- Radicado Padre (Orfeo).
- Solicitante.
- Fecha de solicitud.
- Tipo de caso.
- Matrícula QX o placa.
- QX verificado.
- Número y fecha de resolución administrativa.
- Tipo y fecha de notificación.
- Fecha de constancia de ejecutoria.
- Recurso y fecha del recurso.
- Empresa, NIT y dirección de empresa.
- Propietario, cédula y dirección del propietario.
- Nueva empresa, si aplica.
- Funcionario que desvincula.
- Remisión a Registro Automotor y fecha de remisión.
- Observaciones y notas.
- Foliación total del expediente en hojas.

La foliación se propone automáticamente contando las páginas del PDF, pero el
valor del campo editable en el formulario tiene prioridad y es el que se
guarda en el registro local, Drive y Google Sheets.

El usuario que registra o modifica el expediente no se debe colocar
automáticamente como funcionario que desvincula.

Cada registro debe conservar también la trazabilidad de quien cargó los PDF:
nombre completo, correo de la cuenta activa y cargo o rol autorizado. Estos
datos se guardan en las columnas `SUBIDO POR`, `CORREO SUBIDA` y `CARGO
SUBIDA`, separadas del campo `FUNCIONARIO QUE DESVINCULA`.

## Organización en Google Drive

La estructura esperada es:

```text
Peticion/
  Pendientes/
  AÑO/
    RADICADO_PADRE_PLACA_FECHA_UBICACION/
      Solicitud/
      Recurso/
      Resolución/
      Notificación/
      Constancia de ejecutoria/
      Desistimiento/
      Otro/
      RADICADO_PADRE_PLACA_FECHA.pdf
```

Cada documento individual debe conservarse en su subcarpeta y también debe
existir un PDF completo en la raíz del expediente. Al agregar complementos:

1. Se conserva el documento anterior.
2. Se evita subir duplicados.
3. Se incorpora el complemento a la lista documental.
4. Se reconstruye el PDF completo en el mismo año y expediente.
5. El registro local y Google Sheets conservan los enlaces del PDF completo y
   de cada documento individual para consulta y descarga.
6. La lectura utiliza RapidOCR con ONNX Runtime, una IA local incluida en el
   instalador. No envía los documentos a servicios externos.
7. El OCR se conserva en una caché local por huella del archivo, página y
   resolución. Esto permite que la separación documental reutilice la lectura
   inicial sin volver a procesar las mismas páginas.
8. El instalador incluye ONNX Runtime DirectML y sus bibliotecas, por lo que no
   se necesita instalar Python ni descargar componentes manualmente en cada
   equipo. Al iniciar, ONNX Runtime detecta automáticamente CUDA para GPU
   NVIDIA, DirectML para GPU compatible con Windows o CPU local como respaldo.
   El uso normal de la GPU no requiere permisos administrativos; sí requiere
   que Windows tenga un controlador gráfico funcional.
9. Al terminar el análisis de una carga, las partes detectadas se suben
   inmediatamente a la carpeta del expediente en Drive. Si todavía no se conoce
   la fecha de la petición, se conservan en una carpeta identificada dentro de
   `Pendientes`.
10. El guardado reutiliza las partes ya subidas, mueve la carpeta pendiente al
    año correcto cuando aparece la fecha, reconstruye el PDF completo sin hojas
    blancas y sustituye la versión unificada anterior.
11. La hoja `BD_DESV` conserva una ubicación digital por registro mediante
    `ACCESO DIGITAL`, `DRIVE FOLDER`, `DOCUMENTOS DRIVE` y `PDF UNIFICADO`.
    La aplicación solo muestra enlaces directos y habilita descargas a usuarios
    con rol autorizado o permiso de descarga explícito.
12. Los expedientes completos confirmados pueden contener todos los
    complementos aunque la clasificación automática agrupe páginas en un bloque.
    La separación por tipo documental debe conservar el PDF completo y no
    descartar páginas.

Los archivos sin fecha se guardan en `Pendientes` hasta que el expediente tenga
fecha de solicitud; después se trasladan al año y subcarpeta documental
correspondientes.

## Navegación externa

Google Drive y Google Sheets se abren en pestañas controladas por la aplicación.
La barra debe ofrecer `Cerrar pestaña`, `Cerrar externas` y `Volver al sistema`.
Cerrar una pestaña no debe cerrar la aplicación ni desconectar la cuenta de
Google.
