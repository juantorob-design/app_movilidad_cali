# Informe de la aplicación: Sistema de Desvinculaciones

## 1. Resumen ejecutivo

El Sistema de Desvinculaciones es una aplicación de escritorio para registrar,
organizar, consultar y conservar expedientes administrativos de desvinculación.
Integra una interfaz Streamlit dentro de un ejecutable Windows, almacenamiento
local de respaldo, Google Drive para los documentos y Google Sheets para los
metadatos colaborativos.

Su objetivo principal es reemplazar procesos dispersos de carga, búsqueda y
seguimiento por un flujo único, trazable y controlado por roles.

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

El inicio presenta un escritorio visual con accesos a:

- Registro de Entrada.
- Buscador y Archivo.
- Google Drive.
- Google Sheets.
- Base Histórica.
- Gestión de Permisos.
- Mi Perfil.

El dashboard ejecutivo muestra expedientes gestionados, completitud documental,
documentos registrados, expedientes con faltantes, conexión con Google y
distribución de desenlaces.

### 3.2 Registro de expedientes

El usuario carga uno o varios PDF, PNG, JPG o JPEG. El sistema:

1. lee el texto disponible;
2. identifica radicado, placa y fecha cuando es posible;
3. convierte imágenes a PDF;
4. permite indicar el tipo documental;
5. valida los documentos esperados;
6. identifica el desenlace del caso;
7. conserva los datos anteriores si un campo nuevo llega vacío.

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
anual. Un archivo suelto debe incluir manualmente radicado, fecha de creación de la
petición y placa; de lo contrario, la carga se bloquea. Cuando se carga sin la
petición principal, el expediente queda marcado como pendiente.

El dashboard de capacitación es independiente, se abre con `abrir_presentacion.ps1`
en el puerto 8510 y no forma parte del ejecutable operativo.

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

La nueva versión preparada para publicación es la 1.0.5:

<https://github.com/juantorob-design/app_movilidad_cali/releases/tag/v1.0.5>

## 7. Guion de demostración

Para mostrar la aplicación en una reunión:

1. Explicar que el escritorio concentra todo el proceso.
2. Abrir el dashboard y mostrar indicadores de expedientes y faltantes.
3. Entrar a Registro de Entrada y cargar un documento.
4. Mostrar la detección de radicado, placa, fecha y tipo documental.
5. Explicar la clasificación con recurso, sin recurso o desistimiento.
6. Mostrar cómo se conserva el expediente y se genera el PDF unificado.
7. Abrir Consulta y Archivo para buscar por radicado, placa o fecha.
8. Mostrar los enlaces de Drive y la fila relacionada de Sheets.
9. Explicar los roles y el control de permisos.
10. Finalizar mostrando el instalador, la actualización y la protección de datos.

## 8. Validación de cierre

Se realizaron pruebas controladas contra los servicios reales:

- Google Sheets: lectura de pestañas, escritura de una fila temporal, lectura de
  retorno, actualización de una celda y limpieza final.
- Google Drive: lectura de la carpeta principal y comprobación de su estructura,
  sin conservar archivos de prueba.
- Aplicación: compilación Python, revisión de formato y respuesta HTTP 200 de
  Streamlit.
- Duplicados: verificación por nombre y huella de contenido antes de subir.
- Clasificación anual: validación para que solo la fecha de petición determine el
  año.

La fila temporal usada para la prueba de Sheets fue eliminada y no quedaron
marcadores de prueba en la hoja. El permiso Gmail `gmail.send` debe autorizarse
en cada equipo para activar los correos de emergencia.

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
- documentación y galería de presentación.
- guion de capacitación independiente y constancia de pruebas reales.

## 10. Estado actual y recomendaciones

La aplicación está compilada, instalada y publicada. La validación local del
ejecutable y del servidor Streamlit fue exitosa. Como control operativo
periódico se recomienda:

- realizar respaldos de la hoja y de la carpeta de Drive;
- probar una actualización en un equipo de prueba antes de cambiar de versión;
- revisar permisos de las cuentas activas;
- no publicar bases históricas, tokens, credenciales ni expedientes;
- probar con un expediente controlado después de cada cambio de configuración
  de Google.
- autorizar Gmail desde el botón de actualización de notificaciones antes de
  depender de los correos de emergencia.
