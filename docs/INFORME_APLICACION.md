# Informe de la aplicación: Sistema de Desvinculaciones

**Corte de estado: 31 de octubre de 2026.**

## 1. Resumen ejecutivo

El Sistema de Desvinculaciones integra la aplicación de escritorio Windows, un
cliente Android con API móvil y una versión web en desarrollo para registrar,
organizar, consultar y conservar expedientes administrativos. Google Drive
almacena los documentos y Google Sheets mantiene los metadatos operativos; la
API móvil mantiene las credenciales de Google en el servidor y no en el teléfono.

La versión de escritorio declarada en `version.json` es 1.1.28. Se generó una
distribución PyInstaller aislada que incluye el ejecutable de escritorio y
`EditorPDFLocal`; no se publicó ni se instaló sobre la distribución existente.
La distribución Android general aún corresponde a la 0.1.3 (versionCode 4).
La Release corregida 0.1.5 (versionCode 6), firmada con la clave de publicación
existente y configurada con la URL real de Render, pasó la verificación de
firma y se instaló en BlueStacks Pie64 con `adb install -r`, conservando sus
datos. La app abrió sin crash. El arreglo sustituye el
encabezado de autorización literal del helper `workspaceRequest` por el token
de la sesión. Tras actualizar la app se repitió el acceso Google y, en el retest
posterior, el resumen autenticado cargó correctamente: 2 expedientes, 0 completos,
2 con faltantes y 2 documentos registrados. La búsqueda por ubicación no quedó
confirmada con esta Release; no se usó un dato de expediente para completar esa
prueba. Render respondió `/health` 200 y las rutas protegidas consultadas sin
token devolvieron 401, como se espera. No se probó en un teléfono físico.

La compilación Release firmada, instalación, autenticación y lectura del resumen
quedaron completadas. La carga del PDF de prueba no quedó confirmada: el servidor
reportó un trabajo anterior en proceso y no se envió una segunda copia. No se
confirmó escritura en Drive ni Sheets. El PDF de ejemplo de 87 páginas sí se
procesó localmente contra la API móvil; esto no fue una carga desde Android ni
una prueba de persistencia remota.

En la validación incremental del 31 de octubre, las 158 pruebas Python pasaron;
Debug y Release compilaron, `lintDebug` terminó correctamente y se verificó la
firma v2 del APK Release (0.1.5/code 6). Se instaló y abrió en el AVD dedicado
de pruebas hasta la pantalla de acceso Google, sin excepción fatal. Render
`/health` respondió 200; OpenAPI 0.1.0 incluyó las rutas esperadas de resumen,
expedientes y espacio compartido, y la lista de expedientes sin token respondió
401. Esta comprobación no autenticó una cuenta, no cargó archivos ni escribió
en Drive o Sheets. No hay pruebas unitarias Kotlin.

## 2. Problema que resuelve

Antes de centralizar el proceso, la información podía estar distribuida entre
archivos PDF, imágenes, carpetas de Drive, hojas de cálculo y respaldos Excel.
Esto dificultaba:

- encontrar un expediente por radicado, placa o fecha;
- saber qué documento faltaba;
- evitar filas o archivos duplicados;
- conservar datos históricos al completar un expediente;
- mantener una relación clara entre los metadatos y sus documentos;
- controlar quién podía consultar, modificar, descargar o administrar.

La aplicación reúne esas tareas en una sola interfaz y mantiene la trazabilidad
del expediente desde la carga hasta la consulta.

## 3. Funciones principales

### 3.1 Escritorio y dashboard

El inicio operativo presenta un escritorio visual con accesos a:

- Registro de Entrada.
- Buscador y Archivo.
- Google Drive.
- Google Sheets.
- Base Histórica.
- Gestión de Permisos.
- Mi Perfil.

El dashboard ejecutivo muestra expedientes gestionados, completitud documental,
documentos registrados, expedientes con faltantes, conexión con Google y
distribución de desenlaces. Los indicadores de archivo usan el cálculo común
basado en Google Sheets descrito en la sección Android/API.

### 3.2 Registro de expedientes

El usuario carga uno o varios PDF, PNG, JPG o JPEG. El sistema:

1. lee el texto disponible;
2. identifica radicado, placa y fecha cuando es posible;
3. convierte imágenes a PDF;
4. permite indicar el tipo documental;
5. valida los documentos esperados;
6. identifica el desenlace del caso;
7. conserva los datos anteriores si un campo nuevo llega vacío.

Antes de guardar, el registro muestra un resumen de archivos recibidos, campos
detectados, desenlace y destino previsto. También incorpora un visor integrado
para revisar el PDF sin salir del formulario.

### 3.3 Clasificación de desenlaces

El sistema trabaja con tres desenlaces válidos:

- Con recurso.
- Sin recurso.
- Desistimiento.

Cuando la evidencia del documento no es suficiente, se solicita clasificación
manual. También se evita procesar un lote que mezcle desenlaces incompatibles.

### 3.4 Organización documental

Los documentos pueden separarse y ordenarse por tipo. Se reconocen, entre
otros, solicitud, resolución, notificación, recurso, desistimiento y constancia
de ejecutoria.

Cuando hay varios documentos se crea un PDF unificado en el orden definido y
se conservan los archivos fuente junto con su trazabilidad.

Los documentos complementarios pueden llegar sin la fecha de la petición. Si
se pueden identificar por radicado o placa, reutilizan los datos del expediente
o de Sheets. Si todavía no existe la petición principal, se guardan en
`Pendientes/Por_vincular/PLACA`, con un nombre identificable, y quedan disponibles
en la bandeja de pendientes para revisarlos, moverlos y unirlos posteriormente.

El checklist documental distingue los tres desenlaces:

- **Sin recurso:** Solicitud, Resolución, Notificación y Constancia de ejecutoria.
- **Con recurso:** Solicitud, Recurso, Resolución y Notificación.
- **Desistimiento:** Solicitud y Desistimiento.

El análisis prioriza la secuencia administrativa: solicitud, consulta QX,
resolución o requerimiento, citaciones a empresa y propietario, comunicación,
actuaciones del recurso cuando aplique, constancia de ejecutoria y remisión a
registro. Si no hay resolución ni requerimiento, se verifica desistimiento.
Las páginas de continuación heredan el tipo del bloque anterior cuando no hay
evidencia suficiente, y los documentos ajenos al flujo quedan como `Otro`.

### 3.5 Google Drive

Drive funciona como repositorio documental. Antes de subir un archivo, el
sistema compara nombre y contenido para evitar duplicados. Los enlaces del
archivo se guardan en el expediente y se reflejan en Sheets.

Cuando se genera una nueva versión del PDF unificado, la versión anterior se
envía a la papelera para evitar confusión, mientras que los archivos fuente
anteriores se conservan.

### 3.6 Google Sheets

Sheets funciona como base colaborativa de metadatos. La aplicación:

- busca por radicado y placa;
- actualiza la fila existente cuando encuentra el expediente;
- agrega una fila cuando es un registro nuevo;
- conserva datos históricos no reemplazados;
- maneja las 21 columnas reales de `BD_DESV`;
- integra información complementaria de `DATOS`;
- ordena los registros por fecha.

### 3.7 Soporte y notificaciones

El Buzón de Mensajes permite enviar consultas de soporte y conserva cada mensaje
en la base local. La campana del menú muestra pendientes de activación, solicitudes
de descarga y mensajes de soporte sin leer. El correo de emergencia al Super
Administrador utiliza Gmail API después de autorizar el permiso `gmail.send` en
cada instalación.

### 3.8 Base histórica

La base histórica Excel se trata como respaldo externo de solo lectura. Sus
registros se leen, se ordenan por fecha y se pueden importar al almacenamiento
local sin modificar el archivo original.

Las dos hojas principales se interpretan así:

- `BD_DESV`: información completa de los expedientes.
- `DATOS`: información complementaria para completar campos faltantes.

### 3.9 Regla de petición y año documental

La petición/radicado padre es la fuente única para clasificar el año del expediente.
La fecha de resolución, notificación, recurso o anexos no puede cambiar la carpeta
anual. Un archivo complementario puede guardarse con el radicado o la placa
disponibles. Si no hay suficiente información para asociarlo a un expediente,
se conserva en la bandeja de pendientes sin inventar un año documental.

El dashboard de capacitación es independiente, se abre con `abrir_presentacion.ps1`
en el puerto 8510 y no forma parte del ejecutable operativo.

### 3.10 Android, API móvil y web

La aplicación Android permite iniciar sesión, consultar y editar campos
operativos autorizados, crear expedientes con una petición principal obligatoria
y cargar PDF o imágenes PNG/JPG. La API móvil convierte imágenes a PDF, ejecuta
OCR y separación documental, conserva el archivo completo y guarda bloques
clasificados en Drive. El cliente también admite complementos sin expediente,
que se almacenan en `Pendientes/Por_vincular/PLACA/`.

La API móvil comparte con escritorio el motor RapidOCR, la escala de renderizado
OCR y el extractor de campos. También reutiliza las reglas de clasificación para
corregir encabezados OCR compactos. Los datos detectados completan únicamente
campos vacíos del expediente; los valores confirmados no se sobrescriben y los
campos sin columna disponible se informan. Tras cargar, Android muestra los
campos guardados o pendientes y vuelve a consultar el expediente. La carga
Android usa un trabajo asíncrono y consulta el avance por página para que la
respuesta HTTP inicial no tenga que esperar a que termine el OCR. La cola admite
una carga activa por instancia; su estado es temporal en memoria y se pierde si
la instancia de la API se reinicia.

El escritorio y Android leen la misma hoja operacional de Google Sheets. El
resumen «Estado del archivo» usa ahora un cálculo Python compartido para los
dos clientes y un endpoint autenticado de la API: cuenta radicados únicos,
completitud según los campos administrativos requeridos, expedientes con
documentos faltantes y documentos descritos en Sheets. El escritorio actualiza
los indicadores al iniciar y mediante «Actualizar estado desde Google Sheets»;
Android los carga al iniciar sesión y los vuelve a consultar al actualizar,
crear, editar o procesar un expediente. Si la lectura falla, se muestra «No
disponible»/un error y no se presentan cifras antiguas de la caché como si
fueran actuales. Los documentos contados son los metadatos registrados en Sheets,
no una enumeración en tiempo real de cada archivo Drive.

El escritorio usa Ollama local en Windows. Android incorpora ahora una ruta de
inferencia completamente local con Llamatik/llama.cpp y Qwen2.5-VL 3B
cuantizado Q3_K_M, más su proyector visual coincidente. La primera descarga
requiere aproximadamente 2,93 GB y se valida con SHA-256 antes de instalarse en
el almacenamiento privado de la app. El usuario puede cancelar la descarga o el
análisis. La IA analiza hasta cinco páginas de la petición principal y propone
radicado, placa y fecha; solo llena campos vacíos para no reemplazar valores
confirmados. El OCR y el procesamiento documental completos siguen pasando por
la API cuando se guarda el expediente. Esta integración aún requiere validar la
compilación final y probar inferencia real en un teléfono de al menos 6 GB de
RAM. No equivale todavía a toda la IA ni a todas las funciones del escritorio.
El runtime Llamatik tiene licencia MIT; los pesos derivan de
[Qwen2.5-VL](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct/blob/main/LICENSE)
y mantienen la licencia del modelo original. La app descarga ambos archivos
desde el [repositorio GGUF](https://huggingface.co/mradermacher/Qwen2.5-VL-3B-Instruct-GGUF)
y no los incluye en el APK.

En la revisión de paridad con escritorio se alinearon permisos de accesos
directos a Drive/Sheets y de gestión de perfiles, se añadió la ubicación física
a la búsqueda móvil y se habilitó abrir desde la APK el enlace Drive de cada
documento. Se retiró la falsa vista «Base Histórica»: en escritorio esta función
lee un Excel externo configurado localmente, fuente que la API móvil no tiene
disponible. La importación histórica, el editor PDF local, la carga en lote de
varios archivos y la vista previa/descarga controlada de documentos siguen
siendo funciones de escritorio no equivalentes en Android.

En una comprobación anterior en BlueStacks, OAuth cargó los dos expedientes
operativos; el detalle y la lista documental de Drive funcionaron, y el enlace
abrió el PDF en Google Drive. En ese momento, la búsqueda por ubicación física
no encontró el expediente aunque su detalle sí mostraba la ubicación: la APK
consultaba Render en `ed57989` y la respuesta resumida publicada no incluía ese
campo. Aunque el código local ya lo incorporaba, esa versión de la API aún no
estaba desplegada. El retest posterior de la Release 0.1.5 confirmó OAuth y el
resumen autenticado, pero no volvió a confirmar la búsqueda por ubicación. No se
volvió a enviar el PDF ni se modificaron datos de Drive o Sheets en estas pruebas.

Las pruebas automatizadas cubren conversión, clasificación, trazabilidad,
extracción compartida, caché OCR y operaciones de Drive/Sheets simuladas. No
equivalen a una escritura real con el PDF de ejemplo. El modo web reutiliza la
aplicación Streamlit; la PWA alojada gratuita aún no procesa expedientes ni PDF.

## 4. Modelo de datos de Sheets

La aplicación conserva las columnas:

1. FECHA
2. PLACA
3. EMPRESA
4. NIT
5. DIRECCIÓN de empresa
6. PROPIETARIO
7. CÉDULA
8. DIRECCIÓN del propietario
9. RAD PADRE
10. FECHA RAD
11. RESOLUCIÓN DE DESVINCULACIÓN
12. FECHA DE DESVINCULACIÓN
13. OBSERVACIÓN
14. FUNCIONARIO QUE DESVINCULA
15. NUEVA EMPRESA
16. SOLICITANTE
17. ESTADO
18. CORREO ELECTRÓNICO
19. RECURSO
20. FECHA RECURSO
21. OBSERVACIONES

Las dos columnas con el nombre `DIRECCIÓN` se procesan por posición para
conservar la diferencia entre dirección de empresa y dirección del propietario.

La aplicación utiliza actualmente el archivo `BD_DESVINCULACIONES ADMINISTRATIVAS`
con ID `1oQ5GnxSj4_gGA-p2NjlN3o0uDOLaIELZu4gpohLK6Uo`, ubicado en la carpeta
principal de Drive. El archivo antiguo `DESVINCULACIONES ADMIN APP` ya no forma
parte de la configuración activa.

Los documentos se organizan en Drive con la estructura
`AÑO/RADICADO_PADRE_PLACA_FECHA_UBICACION`. Antes de confirmar el registro, la
carga temporal se guarda en `Pendientes/RADICADO_PADRE_PLACA_FECHA`; allí el
PDF completo queda en la raíz y los fragmentos documentales se guardan en sus
subcarpetas. Dentro de cada expediente
se crea una subcarpeta por tipo documental, como `Solicitud`, `Recurso`,
`Resolución` o `Notificación`. El PDF unificado permanece en la carpeta raíz
del expediente con el nombre `RADICADO_PADRE_PLACA_FECHA.pdf` y se reconstruye
al agregar anexos, conservando también los documentos individuales para consulta
y descarga. Los anexos cargados sin fecha se guardan temporalmente en
`Pendientes/Por_vincular/PLACA` y se mueven a la carpeta anual y subcarpeta documental
correspondiente cuando el expediente queda asociado a su fecha.

## 5. Seguridad y permisos

Los roles disponibles son:

- **Visualizador:** consulta y visualiza; no modifica ni elimina.
- **Modificador:** registra, consulta, descarga y puede eliminar documentos según
  los permisos asignados.
- **Administrador:** administra la operación y la base histórica.
- **Super Administrador:** controla usuarios, roles, estados y autorizaciones.

Las cuentas nuevas pueden quedar pendientes hasta ser activadas. Los tokens
OAuth se guardan localmente en el equipo y no forman parte del repositorio ni
de las releases públicas.

## 6. Instalación y actualización

La aplicación se empaqueta con PyInstaller y se distribuye mediante un
instalador de Inno Setup para Windows de 64 bits. El actualizador consulta
`version.json` en GitHub Raw y, si encuentra una versión superior, descarga el
instalador correspondiente.

La versión declarada actualmente en el repositorio es la 1.1.28. El historial
de esa versión está en [RELEASE_NOTES_1.1.28.md](../RELEASE_NOTES_1.1.28.md).

La versión del archivo no confirma por sí sola que el instalador se haya
publicado o instalado en todos los equipos.

Cuando existe una versión superior, la aplicación muestra un aviso con los
botones **Actualizar ahora** y **Más tarde**. La descarga solo inicia después
de la autorización explícita del usuario.

## 7. Guion de demostración

Para mostrar la aplicación en una reunión:

1. Explicar que el escritorio concentra todo el proceso.
2. Abrir el dashboard y mostrar indicadores de expedientes y faltantes.
3. Entrar a Registro de Entrada y cargar un documento controlado.
4. Mostrar el resumen, el visor, los campos detectados y el destino previsto.
5. Explicar el checklist de Sin recurso, Con recurso o Desistimiento.
6. Cargar un anexo sin fecha y mostrar la ruta de Pendientes.
7. Abrir Consulta & Archivo para revisar pendientes y buscar por radicado, placa o fecha.
8. Mostrar la carpeta de Drive, el PDF unificado y la fila relacionada de Sheets.
9. Explicar los roles, permisos y la conservación de datos existentes.
10. Finalizar mostrando el aviso de actualización autorizada y la protección de datos.

## 8. Validación de cierre

- Suite Python: **148 pruebas pasadas**.
- Escritorio: el bundle PyInstaller se generó en un destino aislado; contiene
  `SistemaDesvinculaciones.exe` y el programa `EditorPDFLocal`. El instalador no
  se publicó y no se reemplazó la distribución instalada.
- Android: la versión 0.1.5 (versionCode 6) compila con Android Gradle Plugin
  8.13.2, Gradle 8.13 y compileSdk 36. Tras corregir el encabezado de
  `workspaceRequest`, `:app:testDebugUnitTest`, `:app:assembleDebug`,
  `:app:assembleRelease` y `:app:lintVitalRelease` terminaron correctamente; no
  hay pruebas unitarias Kotlin. La firma v2 de la Release se verificó y la APK
  corregida se instaló sobre la existente en BlueStacks sin borrar sus datos.
- IA móvil: repositorio del modelo fijado a una revisión concreta; se verificaron
  los tamaños y SHA-256 publicados para configurar el descargador. No se
  descargaron los GGUF ni se comprobó inferencia. El emulador usado tiene
  2,5 GB de RAM (menos que los 6 GB recomendados para el dispositivo objetivo).
  Modelo Q3_K_M y proyector: ~2,93 GB en total.
- API Render: el commit `04594d8` se desplegó manualmente. En la verificación
  actual `/health` respondió 200; OpenAPI 0.1.0 expone 15 rutas, incluida
  `GET /api/v1/archivo/resumen`, protegida por autenticación Bearer. Las rutas
  protegidas devuelven 401 cuando se consultan sin token, según lo esperado.
- Emulador Android: instalación de Release 0.1.5/code 6 y apertura de
  `MainActivity` aprobadas, sin excepción fatal en Logcat. La app llegó a la
  pantalla de acceso Google. No se autenticó ni se probaron listas, formularios
  o carga porque Render estaba respondiendo 502. No había teléfono físico
  conectado.
- BlueStacks: la Release corregida 0.1.5 se instaló y abrió sin crash. La
  autenticación que había funcionado en la instalación anterior tuvo que
  repetirse tras actualizar; el selector Google se abrió, pero la app volvió a
  quedar en la pantalla de acceso. No se validaron el resumen autenticado ni la
  búsqueda por ubicación con el arreglo instalado en ese primer intento.
- Retest posterior en BlueStacks: se completó Google OAuth y el resumen
  autenticado mostró 2 expedientes, 0 completos, 2 con faltantes y 2 documentos
  registrados. La búsqueda por ubicación no se confirmó en esta Release.
- PDF de ejemplo (87 páginas, ~8,1 MB): la API local lo procesó en 468,7 s; 66
  páginas pasaron por OCR, produjo 25 bloques, clasificó `Con recurso` y
  detectó 14 campos. No se comparó página por página contra escritorio ni se
  guardó el resultado en Drive/Sheets.
- No se volvió a enviar el PDF ni se escribieron datos de prueba en servicios
  productivos. El último trabajo remoto seguía reportado en proceso y una
  consulta de Drive devolvió HTTP 502; confirmar ese trabajo antes de reintentar.
- La paridad funcional total sigue pendiente: histórico Excel, editor PDF,
  carga por lote, gestión documental completa y conversación IA no están
  disponibles en Android.

El permiso Gmail `gmail.send` debe autorizarse en cada equipo para activar los
correos de emergencia.

## 9. Trabajo realizado

Durante el desarrollo se corrigieron y consolidaron:

- autenticación local y Google OAuth;
- perfiles, roles, cuentas pendientes y Supabase;
- lectura inteligente de PDF;
- carga de imágenes y conversión a PDF;
- separación, clasificación y unión documental;
- prevención de duplicados en Drive;
- actualización sin pérdida de datos históricos;
- integración de `BD_DESV` y `DATOS`;
- normalización de encabezados con acentos dañados;
- ordenamiento de Sheets por fecha;
- escritorio integrado y enlaces de Drive/Sheets;
- empaquetado PyInstaller;
- instalador Inno Setup;
- actualización automática desde GitHub;
- actualización autorizada mediante botones dentro de la aplicación;
- resumen, visor integrado y checklist documental por proceso;
- bandeja de pendientes con asociación posterior por radicado o placa;
- documentación y galería de presentación.
- guion de capacitación independiente;
- API móvil y soporte de carga de PDF e imágenes desde Android;
- separación OCR por bloques, guardado del PDF original y trazabilidad de
  archivo de origen y páginas.
- extractor de campos compartido por escritorio y API móvil, con guardado sin
  sobrescribir los datos confirmados;
- IA visual local Android integrada al registro: Qwen2.5-VL 3B, descarga
  verificable y análisis de hasta cinco páginas para prellenar campos vacíos;
- resumen común del estado del archivo desplegado en la API para consultar las
  métricas calculadas desde Sheets.

## 10. Estado actual y recomendaciones

La suite Python local tiene 158 pruebas pasadas. Las compilaciones Android
Debug y Release 0.1.5 pasaron; `lintDebug` y `lintVitalRelease` terminaron y la
firma v2 se verificó. El APK Release se instaló y abrió en el AVD de pruebas
hasta el acceso Google, sin crash. El acceso autenticado y la lectura del
resumen constan en el retest histórico de BlueStacks; no se repitió la
autenticación en esta validación. Render responde `/health` 200, OpenAPI muestra
las rutas usadas por Android y las rutas protegidas sin token devuelven 401.
La búsqueda por ubicación no se confirmó con la Release corregida. No hay
pruebas unitarias Kotlin. La IA local aún no se ejecutó en un teléfono. El
resultado de la carga remota previa no quedó confirmado; no repetirla hasta
comprobar su estado. Como control operativo periódico se recomienda:

- realizar respaldos de la hoja y de la carpeta de Drive;
- probar una actualización en un equipo de prueba antes de cambiar de versión;
- revisar permisos de las cuentas activas;
- no publicar bases históricas, tokens, credenciales ni expedientes;
- probar con un expediente controlado después de cada cambio de configuración
  de Google.
- autorizar Gmail desde el botón de actualización de notificaciones antes de
  depender de los correos de emergencia.
- usar una copia o carpeta/hoja de pruebas antes de validar escritura real;
- comparar el resultado del PDF de ejemplo con el escritorio y revisar
  manualmente la secuencia administrativa.
- volver a cargar solo si el trabajo no aparece como completado; un reinicio de
  la instancia elimina los trabajos que siguen en memoria.
