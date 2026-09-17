# Instrucciones prioritarias para el registro

## Lectura y separación del expediente

1. Todo PDF cargado debe leerse completo, página por página, con texto digital y
   OCR como respaldo.
2. La IA no debe leer todo el expediente completo como una sola masa textual. Debe
   detectar el flujo administrativo antes de OCR final:
   - Solicitud o petición.
   - Consulta de verificación de propiedad del vehículo.
   - Resolución que resuelve el acto administrativo.
   - Requerimiento, si aplica.
   - Oficios de citación a empresa y propietario.
   - Notificación personal, aviso o publicación web.
   - Recurso, si aplica.
   - Resolución del recurso, si aplica.
   - Constancia de ejecutoria.
   - Remisión a registro.
3. La separación documental debe guardar cada bloque en su carpeta correcta dentro
   del expediente y nunca mezclar páginas de diferentes tipos en una sola carpeta.
4. La clasificación del caso debe reconocer exactamente uno de estos estados:
   `Con recurso`, `Sin recurso` o `Desistimiento`.
5. Una resolución que diga que se declara el desistimiento se clasifica como
   `Desistimiento`, aunque también contenga palabras de Resolución o
   Notificación.
6. Si existen resolución y recurso, el caso es `Con recurso`. Si no hay recurso y
   existe constancia de ejecutoria o resolución final, el caso es `Sin recurso`.
   Si solo aparece desistimiento, el caso es `Desistimiento`.
7. La información detectada debe precargar el registro antes de guardar. Si un
   complemento aporta un dato que faltaba, debe completar el registro sin borrar
   los datos ya confirmados.
8. La separación debe clasificar cada página por evidencia priorizada. Los
   títulos de solicitud, resolución, notificación, recurso, desistimiento,
   ejecutoria, requerimiento, citación y consulta QX tienen prioridad sobre
   menciones secundarias. Las páginas de continuación heredan el complemento
   anterior cuando no contienen texto suficiente, evitando enviarlas
   innecesariamente a `Otro`.

## Flujo administrativo obligatorio

La desglose operativo del expediente debe respetar este orden:

1. Petición o solicitud.
2. Consulta de verificación de propiedad del vehículo.
3. Resolución que resuelve el acto administrativo.
   - Si hay resolución: continuar con el punto 4.
   - Si no hay resolución pero sí hay requerimiento: continuar con el punto 4.
   - Si no hay requerimiento ni resolución: verificar si hay desistimiento.
     - Si hay desistimiento: pasar al punto 5.
     - Si no hay desistimiento: debe existir resolución que resuelve o resolución
       de requerimiento.
4. Oficios de citación:
   - Empresa.
   - Propietario.
5. Comunicación:
   - Notificación personal.
   - Notificación por aviso.
   - Notificación por publicación web.
   - Si no hay recurso, continuar con el paso 7.
6. Recurso, si aplica:
   - Resolución del recurso.
   - Citación del recurso.
   - Notificación personal del recurso.
   - Notificación por aviso del recurso.
   - Publicación web del recurso.
7. Constancia de ejecutoria.
8. Remisión a registro.

Solo existen 3 finales posibles: `Con recurso`, `Sin recurso` o `Desistimiento`.
Todo documento fuera del flujo principal debe almacenarse como `Otro` y nunca
reemplazar el documento principal del expediente.

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

## Esquema tabular recomendado para la hoja `BD_DESV`

La hoja de cálculo debe mantener una tabla limpia y estable para facilitar la
búsqueda, la actualización y la validación automática por campos. El esquema
canónico recomendado es:

```text
FECHA SOLICITUD, PLACA, EMPRESA, NIT, DIRECCION EMPRESA, PROPIETARIO,
CEDULA, DIRECCION PROPIETARIO, RAD PADRE, FECHA RADICACION,
RESOLUCION DESVINCULACION, FECHA DESVINCULACION, OBSERVACION,
FUNCIONARIO QUE DESVINCULA, NUEVA EMPRESA, SOLICITANTE, ESTADO,
CORREO ELECTRONICO, RECURSO, FECHA RECURSO, OBSERVACIONES, TIPO CASO,
TIPO NOTIFICACION, FECHA NOTIFICACION, FECHA EJECUTORIA,
FECHA REMISION REGISTRO, QX VERIFICADO, ID EXPEDIENTE, UBICACION FISICA,
CAJA, FOLDER, CARPETA, FOLIACION, FECHA ULTIMA MODIFICACION, SUBIDO POR,
CORREO SUBIDA, CARGO SUBIDA, ACCESO DIGITAL, DRIVE FOLDER,
DOCUMENTOS DRIVE, PDF UNIFICADO, DOCUMENTOS FALTANTES,
CONTENIDO DOCUMENTAL
```

La aplicación debe seguir aceptando columnas legacy con nombres antiguos (por
ejemplo `DIRECCION`, `FECHA`, `RADICADO PADRE`, `RESOLUCION`, `FECHA`), pero
la escritura preferente debe usar este esquema centralizado para no duplicar
campos ni mezclar direcciones entre empresa y propietario.

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
