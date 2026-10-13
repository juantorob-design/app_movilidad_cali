# Aplicacion Android nativa

Esta carpeta contiene el cliente Android independiente. El programa de Windows
y la version web se mantienen fuera de ella.

## Arquitectura de acceso compartido

- Android autentica una cuenta Google verificada con Google Identity y solicita
  un ID token firmado.
- El APK envia el token por HTTPS al API (`GET /api/v1/me`).
- El API verifica firma, audiencia y correo verificado; luego consulta el perfil
  compartido en Supabase y permite el acceso solo si esta activo y tiene rol.
- El perfil central de Supabase es la autoridad para el rol y la solicitud de
  permiso; el usuario propietario tambien debe conservar el rol de propietario
  activo configurado en el servidor.
- El token de Drive/Sheets y las credenciales OAuth del servidor nunca se
  incluyen ni se guardan en el telefono.
- Los expedientes se compartiran mediante endpoints versionados del servidor;
  Android no lee ni escribe directamente a Sheets o Drive.

## Estado y limitaciones reales

El inicio de sesion usa Google Credential Manager y el servidor valida la firma
del ID token, su audiencia, el correo verificado y la cuenta propietaria. No se
aceptan tokens de prueba. Los clientes OAuth de Android/Web y de escritorio son
distintos y ambos deben permanecer configurados.

La interfaz móvil conserva la paleta azul y cian y adapta el mosaico de
aplicaciones del programa de escritorio a una cuadrícula para celular. El
buscador, el listado, el detalle, el perfil, el registro básico y la carga de PDF
e imágenes PNG/JPG
están conectados a la API. La búsqueda incluye radicado, placa, NIT, empresa,
propietario, cédula y fecha. El icono adaptativo y la marca de la pantalla de
inicio usan la imagen `images/icon.ico` del programa original, convertida a
recursos compatibles con Android. Google Drive y Google Sheets abren la
carpeta documental y la hoja operacional configuradas en una pestaña del
navegador con control para cerrarla y volver a la app.

Registro de Entrada permite guardar inicialmente el radicado padre, la placa y
la fecha de solicitud; no solicita una clasificación antes de revisar los
documentos. Al cargar un PDF o una imagen PNG/JPG, el servidor convierte las
imágenes a PDF, hace OCR de páginas escaneadas,
separa bloques documentales contiguos según `document_rules.py`, guarda el PDF
completo y archiva cada bloque en la subcarpeta Drive de su tipo. Si encuentra
evidencia suficiente, propone una clasificación y la guarda en Sheets solo si
el expediente no tenía una clasificación confirmada; si no hay evidencia, el
caso queda pendiente de revisión. El detalle también lista los documentos
encontrados en Drive y muestra el nombre del PDF de origen y el rango de
páginas de cada bloque. Los complementos sin expediente se pueden guardar desde Registro de Entrada en
`Pendientes/Por_vincular/PLACA/`.

Base Histórica permite consultar en móvil los expedientes de la pestaña
compartida `tabla_2`, con los mismos filtros del buscador. No mezcla la pestaña
auxiliar `DATOS` ni la presenta como una tabla de expedientes. El respaldo Excel
`BD_DESV` del módulo histórico de escritorio no está disponible en la carpeta
de datos revisada, por lo que esta consulta usa la fuente Google compartida.
La lista móvil y el total del programa de escritorio cuentan los radicados padre
únicos de esa misma hoja operacional; los registros que solo estén en la caché
local no se suman al total de Google Sheets.
El detalle móvil permite editar los campos operativos que la API mapea a
columnas existentes de Sheets. El radicado permanece fijo, las clasificaciones
se limitan a los tres resultados válidos, y solo se envían los campos que
cambian; el servidor conserva las demás celdas. La fecha de solicitud admite
AAAA-MM-DD o DD/MM/AAAA y se guarda normalizada. Gestión de Permisos y Buzón
se conectan a la API autenticada y al espacio de Supabase compartido con el
programa de escritorio y la web. La APK permite revisar perfiles, actualizar
roles/estados/permisos de descarga y enviar/leer mensajes de soporte. El inicio
móvil respeta el rol activo compartido: los visualizadores consultan expedientes,
los modificadores y administradores pueden realizar operaciones documentales y
solo administradores gestionan perfiles y marcan mensajes como leídos. La API
vuelve a validar cada operación; ocultar controles en la app no sustituye esa
validación. El botón de solicitud registra la petición en el perfil compartido.
El permiso `download_allowed` todavía no cambia los permisos ACL de Google
Drive: como los accesos a Drive/Sheets se abren en aplicaciones externas, esa
casilla por sí sola no concede ni revoca el acceso a los archivos.
También se leyeron un detalle y su checklist de Drive. Aún falta probar
creación, carga y vinculación con un destino de pruebas separado antes de uso
administrativo.

El API móvil lee y escribe la hoja operacional `tabla_2` (o `bd_desv`, si la
primera no existe) del Google Sheet que usa el programa principal. Usa el archivo OAuth local del programa (`token.json`) y
valida que la cuenta autorizada corresponda al propietario configurado. La
autorización local confirmada tiene los permisos de Drive y Sheets requeridos;
el archivo permanece en el servidor y no forma parte del APK. Las operaciones de Drive
requieren el permiso `drive.file` solicitado por el programa; los archivos
individuales conservan el nombre del PDF de origen y sus páginas. No lee el JSON
local que contiene datos de prueba. Para crear expedientes, la hoja debe incluir las
columnas `RAD PADRE`, `FECHA SOLICITUD` y `PLACA` para registrar inicialmente
expedientes. Para guardar una clasificación detectada automáticamente, también
debe existir la columna `TIPO CASO`; la API no añade ni modifica encabezados
automáticamente.

## Requisitos para compilar

- JDK 17 y Android SDK Platform 35.
- Android Build Tools instalados.
- Gradle Wrapper 8.9 incluido en este proyecto; verifica la distribucion con
  el checksum SHA-256 oficial al descargarla.
- Para Google Identity: configurar un cliente OAuth Android con el identificador
  de paquete y la huella SHA-1/SHA-256 de firma; conservar el cliente OAuth Web
  como audiencia del ID token que verifica el servidor.
- Registrar el cliente Android y el cliente Web en el mismo proyecto de Google
  Cloud. El ID de cliente Web es publico y se configura en el APK; su secreto no
  se incluye en Android.
- La autenticación móvil usa los clientes OAuth del proyecto activo
  `sistema-desvinculaciones-cali`:
  - Cliente Web (audiencia): `1019857870350-ccrqd53kcl0c6k799f0om2p5fnloviij.apps.googleusercontent.com`.
  - Cliente Android de Release: registrado para el paquete
    `co.sistemadesvinculaciones.mobile` y la huella SHA-1 de la clave de
    distribución.
  - La aplicación está en modo de prueba; agrega las cuentas autorizadas como
    usuarios de prueba en Google Auth Platform.
- El cliente de escritorio usado por el programa Windows para Drive/Sheets está
  en `sistema-desvinculaciones-cali`; son configuraciones OAuth separadas. El ID
  de cliente web configurado en Android debe seguir emparejado con su cliente
  Android registrado.
- La pantalla de consentimiento sigue en modo **Prueba**. Google limita el inicio
  de sesión a los usuarios de prueba configurados en Cloud y puede hacer caducar
  sus tokens de autorización tras siete días; cuando ocurra, el usuario debe
  volver a autorizar. Aprobar un perfil en Supabase no lo añade a esa lista de
  prueba. Son controles distintos: Supabase determina el acceso al sistema y
  Google determina quién puede completar OAuth mientras la app siga en prueba.
  No publiques la aplicación ni amplíes la lista de usuarios sin completar la
  revisión OAuth que corresponda.
- Para publicar, usar una API con HTTPS y configurar el mismo correo propietario
  en la API. No se admite HTTP fuera de hosts locales en builds debug.

Desde `android_app`, compila con PowerShell. Sustituye la ruta del JDK y los
valores de configuracion por los de tu entorno:

```powershell
$env:JAVA_HOME = "C:\ruta\al\jdk-17"
.\gradlew.bat assembleDebug `
  -PAPI_BASE_URL=http://10.0.2.2:8000/ `
  -PGOOGLE_WEB_CLIENT_ID=tu-cliente-web.apps.googleusercontent.com `
  -PSISTEMA_SPREADSHEET_ID=id-de-la-hoja `
  -PSISTEMA_DRIVE_FOLDER_ID=id-de-la-carpeta
```

`10.0.2.2` solo conecta el emulador al PC de pruebas. El APK permite HTTP
únicamente para el emulador y loopback; el resto del tráfico requiere HTTPS.
En un teléfono físico usa una API desplegada con HTTPS. Antes de probar el inicio móvil, autoriza el
programa Windows con Google, confirma que se creó `token.json` para
`juan.torob@cun.edu.co`, inicia el API con `start_mobile_api.ps1` y verifica que
`http://127.0.0.1:8000/health` responda `{"status":"ok"}`. No sustituyas estos
datos por expedientes de demostración. En el emulador se validó la instalación
y el arranque de la APK; la API local también responde correctamente en
`/health`. El flujo móvil aún requiere una prueba de inicio de sesión y
operaciones de extremo a extremo con un expediente de prueba autorizado.

Para el despliegue de prueba en Render Free, consulta
[`docs/RENDER_GRATUITO.md`](../docs/RENDER_GRATUITO.md). Al iniciar sesión, la
APK consulta `/health` antes de autenticarse; esa petición despierta el servicio
si Render lo durmió y reintenta brevemente durante el arranque en frío. El primer
inicio puede tardar más de un minuto.

Los APK Release requieren una clave dedicada y protegida, distinta de la clave
debug. El archivo PKCS#12 y la contraseña DPAPI permanecen fuera del repositorio
en `%LOCALAPPDATA%\SistemaDesvinculaciones\release-signing\`. El wrapper
`build_release.ps1` usa esa contraseña solo en el proceso local de Gradle y
genera `app/build/outputs/apk/release/app-release.apk`. La copia de recuperación
del archivo PKCS#12 debe mantenerse en Drive privado; su contraseña debe
guardarse por separado en un gestor de contraseñas. En este equipo también se
guardó en Credenciales de Windows con el destino
`SistemaDesvinculaciones/AndroidReleaseKeystore`; Windows Hello desbloquea la
sesión, mientras DPAPI protege la copia local usada por el wrapper. No publiques
el APK hasta probar inicio de sesión y operaciones con una cuenta y documentos
ficticios.

El APK debug se genera en
`app/build/outputs/apk/debug/app-debug.apk`. Si no se pasan las propiedades,
la aplicacion bloquea el inicio de sesion; no se usan credenciales ficticias.
El APK debug esta firmado con una clave de desarrollo: no es una version de
distribucion ni debe publicarse. No incluyas secretos en el codigo o en archivos
Gradle versionados.
En Android Studio, selecciona JDK 17 como Gradle JDK antes de sincronizar el
proyecto.

## API

Desde la raíz del repositorio, instala `requirements-mobile-api.txt`. El
programa usa la hoja existente y el archivo OAuth local `token.json`; el script
lee ese archivo sin imprimir ni incluir su contenido en el APK. Puedes cambiar
la configuración mediante variables de entorno:

```powershell
$env:SISTEMA_GOOGLE_WEB_CLIENT_ID = "ID_CLIENTE_WEB.apps.googleusercontent.com"
$env:SISTEMA_WEB_OWNER_EMAIL = "correo-autorizado@gmail.com"
$env:SISTEMA_GOOGLE_TOKEN_FILE = "C:\ruta-segura\token.json"
$env:SISTEMA_SPREADSHEET_ID = "ID_DE_LA_HOJA"
```

El script `start_mobile_api.ps1` usa el entorno `venv` de Python 3.12
(requerido por RapidOCR), valida la audiencia del cliente Web de Android y
utiliza el `token.json` local autorizado por el cliente de escritorio nuevo.
El cliente OAuth de escritorio sirve a la API para Drive/Sheets; el cliente
OAuth Android/Web existente se conserva para el inicio de sesión móvil. Vuelve
a autorizar la cuenta propietaria y concede los permisos de Drive y Sheets para
generar un token compatible.
Ejecuta:

```powershell
python -m uvicorn mobile_api.main:app --host 127.0.0.1 --port 8000
```

La API debe publicarse detras de un proxy HTTPS antes de aceptar conexiones
desde telefonos. El endpoint de salud es publico; `/api/v1/me` exige un token
Google valido. No expongas Uvicorn directamente a Internet. Para habilitar las
rutas compartidas, aplica la migración `supabase/migrations/202610120001_shared_permissions_and_inbox.sql`
y configura `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` y
`SISTEMA_WEB_OWNER_EMAIL` en el servidor. La clave service role no debe añadirse
a Android, `local.properties` ni a la APK. El API local devolverá un error de
configuración hasta que el proceso servidor tenga esa clave.
