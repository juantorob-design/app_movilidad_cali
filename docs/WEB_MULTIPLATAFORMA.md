# Versión web y aplicación móvil instalable

## Alcance acordado

- El programa instalable de Windows se conserva.
- La versión web reutiliza la aplicación operativa existente; no mantiene una
  copia paralela de la lógica de OCR, reglas de documentos, Drive o Sheets.
- Solo una cuenta Google exacta, configurada por el propietario, puede entrar.
- El servidor usa el token Google del propietario para Drive, Sheets y Gmail,
  igual que la instalación de escritorio.
- Los registros siguen sincronizándose con Google Sheets y los documentos con
  Google Drive. La copia JSON local se guarda en un volumen persistente del
  servidor para no depender del almacenamiento temporal del contenedor.
- El portal puede instalarse como PWA en móviles. Necesita internet para
  consultar o procesar expedientes; no guarda documentos para uso sin conexión.

El propietario controla el servidor, dominio, cuentas OAuth y permisos de acceso
a Google Drive/Sheets. Perfiles, permisos de descarga y mensajes de soporte se
comparten mediante Supabase. La clave privilegiada de Supabase solo se configura
en servidores; nunca se incorpora al ejecutable de escritorio ni a la APK.

## Qué se añadió

- `web_app.py`: punto de entrada web que ejecuta `app_6.py` en modo navegador;
  el ejecutable existente conserva su inicio normal.
- `web_platform/auth.py`: inicio de sesión OIDC de Google y validación exacta
  de la única cuenta autorizada.
- `run_web.ps1`: arranque local de prueba, sin publicar el puerto.
- `Dockerfile.web` y `docker-compose.web.yml`: paquete Linux para servidor,
  almacenamiento persistente, token de Google y proxy HTTPS.
- `deploy/nginx-web.conf`, `deploy/Caddyfile` y `deploy/pwa/`: reverse proxy,
  TLS automático e instalación desde Chrome/Android o Safari/iOS.
- `web-secrets.example.toml`: plantilla sin credenciales reales.
- `mobile_api/shared_workspace.py` y la migración
  `supabase/migrations/202610120001_shared_permissions_and_inbox.sql`: datos
  comunes para perfiles, permisos y mensajes de soporte.

`web_platform/database.py` y su migración PostgreSQL son una base opcional de
trabajo futuro; no es el almacén compartido de perfiles ni del buzón.

## Requisitos que no son permisos institucionales

1. Un servidor Linux propio o una máquina propia siempre encendida. Para abrirla
   desde fuera de esa red se necesita un dominio HTTPS y que el servidor sea
   accesible por Internet, VPN privada o túnel seguro. La configuración Caddy
   incluida automatiza HTTPS una vez que el DNS del dominio apunta al servidor.
2. En un proyecto Google Cloud que controle el propietario:
   - Habilitar Google Drive API, Google Sheets API y Gmail API si se desean
     notificaciones por correo.
   - Crear un cliente OAuth de tipo **Aplicación web** para el inicio web.
   - Autorizar `https://TU-DOMINIO/oauth2callback` como URI de redirección y
     `https://TU-DOMINIO` como origen.
   - Para pruebas locales, autorizar también
     `http://localhost:8501/oauth2callback` como URI y
     `http://localhost:8501` como origen.
   - Si el consentimiento está en modo de prueba, agregar solamente el correo
     del propietario como usuario de prueba.
3. El `credentials.json` y el `token.json` de la cuenta propietaria que ya usa
   el programa de escritorio. El token debe corresponder al mismo correo y
   tener los permisos Drive/Sheets requeridos. Se monta en el contenedor como
   secreto; nunca se incorpora a la imagen ni a Git.
4. La cuenta propietaria debe tener acceso de edición a la carpeta `PDFS
   Escaneados` y a la hoja existente.
5. Para sincronizar perfiles y mensajes entre escritorio, web y Android, aplica
   la migración de Supabase descrita abajo y configura las claves de servidor.

El cliente OAuth web para el login es distinto del cliente OAuth de escritorio
que autentica Drive. Ambos pertenecen al propietario; el cliente web no es un
permiso administrado por la entidad.

## Prueba en este computador

1. Crea `.streamlit/secrets.toml` copiando
   [`web-secrets.example.toml`](../web-secrets.example.toml).
2. En el archivo local, configura
   `auth.redirect_uri = "http://localhost:8501/oauth2callback"` y registra
   también ese callback y el origen `http://localhost:8501` en el cliente
   OAuth web de Google. Conserva el callback HTTPS del dominio para producción.
3. Instala las dependencias web en el entorno virtual:

   ```powershell
   .\venv\Scripts\python.exe -m pip install -r requirements-web.txt
   ```

4. Rellena el único correo autorizado y los datos reales del cliente Google
   OAuth web. No guardes secretos en el repositorio.
5. Ejecuta:

   ```powershell
   .\run_web.ps1
   ```

6. Abre `http://localhost:8501`, inicia sesión y comprueba que Drive y Sheets
   corresponden a la misma cuenta Google configurada.

Para probarlo desde un teléfono en la misma red se puede usar
`.\run_web.ps1 -ListenOnNetwork`, sustituyendo `127.0.0.1` por la IP del
computador. No uses ese modo en una red pública ni sin HTTPS.

## Despliegue en servidor propio con Docker

1. Instala Docker Engine y el complemento Docker Compose en el servidor Linux.
2. Publica el nombre DNS que se usará para la aplicación y dirige sus registros
   al servidor. Permite el tráfico entrante HTTPS (443) y, para emitir/renovar
   certificados automáticamente con Caddy, HTTP (80).
3. Copia el proyecto sin incluir `.env`, `token.json`, `credentials.json`,
   PDFs ni archivos de datos.
4. Crea `.streamlit/secrets.toml` desde la plantilla y usa en
   `auth.redirect_uri` exactamente `https://TU-DOMINIO/oauth2callback`.
5. Coloca `token.json` y `credentials.json` en el servidor, con acceso de
   lectura solo para el administrador del host. El token debe ser renovable;
   el contenedor puede actualizarlo.
6. Crea `.env` en la carpeta de despliegue con:

   ```dotenv
   SISTEMA_WEB_DOMAIN=TU-DOMINIO
   SISTEMA_WEB_OWNER_EMAIL=tu.correo@gmail.com
   SISTEMA_GOOGLE_WEB_CLIENT_ID=CLIENT_ID_DE_APLICACION_WEB
   SUPABASE_URL=https://TU-PROYECTO.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=CLAVE_PRIVILEGIADA_SOLO_EN_ESTE_SERVIDOR
   SISTEMA_DRIVE_FOLDER_ID=ID_DE_PDFS_ESCANEADOS
   SISTEMA_SPREADSHEET_ID=ID_DE_LA_HOJA
   SISTEMA_OLLAMA_URL=http://host.docker.internal:11434
   ```

7. Construye y arranca:

   ```bash
   docker compose -f docker-compose.web.yml up -d --build
   docker compose -f docker-compose.web.yml ps
   docker compose -f docker-compose.web.yml logs -f web https
   ```

8. Abre `https://TU-DOMINIO` y valida primero el login del propietario, la
   conexión a Drive/Sheets, una carga de prueba sin información real y un
   reinicio del contenedor para verificar persistencia.

La base local y el respaldo histórico opcional se guardan en `web-data/`; los
certificados de Caddy se guardan en volúmenes Docker. Incluye ambos en el plan
de copia de seguridad del servidor. Los tokens,
`.env`, `secrets.toml` y los datos nunca deben subirse al repositorio.

### Permisos y buzón compartidos

1. Verifica en Supabase que `public.profiles` exista y tenga `email`,
   `full_name`, `role` y `status`, tal como lo usa la autenticación actual.
2. Aplica `supabase/migrations/202610120001_shared_permissions_and_inbox.sql`
   desde el flujo de migraciones aprobado del proyecto. La migración agrega los
   permisos de descarga, crea `support_messages` y limita las operaciones
   autenticadas con RLS/RPC. No se ejecuta automáticamente al iniciar Docker.
3. En el `.env` del servidor establece `SUPABASE_URL` y
   `SUPABASE_SERVICE_ROLE_KEY`. Docker exige esta última variable para ambos
   servicios, web y API. Guárdala en el gestor de secretos del host; no la
   copies a `.streamlit/secrets.toml`, al repositorio, a `local.properties` ni
   a la configuración de Android.
4. En la aplicación de escritorio configura `SUPABASE_ANON_KEY` mediante su
   entorno protegido y habilita Google como proveedor OAuth de Supabase. Agrega
   `http://127.0.0.1:8765/oauth/callback` a las URL adicionales de redirección
   permitidas en Supabase Auth. Cada usuario debe tener un perfil en
   `public.profiles`; su rol y estado
   centrales son la autoridad para permisos compartidos.
5. La API Android valida el ID token de Google y consulta el perfil activo y su
   rol en Supabase. Sus pantallas de permisos y buzón usan la API autenticada del
   servidor; no contienen ni reciben la clave service role. La aprobación
   central de Supabase no agrega automáticamente la cuenta a los usuarios de
   prueba de OAuth de Google Cloud.

Si falta la migración o la clave del servidor, las operaciones compartidas deben
fallar explícitamente. No se debe considerar una actualización guardada en la
caché local como un cambio central confirmado.

### IA y OCR

El OCR de RapidOCR se ejecuta dentro del contenedor. Ollama puede seguir
instalado en el servidor y exponerse solo a Docker/red privada. En ese caso
ajusta `SISTEMA_OLLAMA_URL` al endpoint privado. No expongas el puerto de
Ollama a Internet. Si Ollama no está disponible, el OCR y las reglas
documentales permanecen activos.

### Instalar en un teléfono

- **Android/Chrome:** abre el dominio HTTPS, inicia sesión y elige “Instalar
  aplicación” o “Añadir a pantalla de inicio”.
- **iPhone/iPad:** abre el dominio HTTPS en Safari, toca Compartir y elige
  “Añadir a pantalla de inicio”.

La PWA abre el portal en modo aplicación y muestra una página informativa si se
pierde la red. Por protección de expedientes, no almacena copias offline ni
permite trabajar con datos cuando el servidor está desconectado.

### API para la app Android nativa

Compose incluye el servicio `mobile-api` y enruta `/api/` por HTTPS al
contenedor. El inicio nativo usa Google Credential Manager y el servidor
verifica el ID token contra el cliente OAuth web y el perfil activo en Supabase.
Para leer expedientes, la API reutiliza la credencial OAuth del programa y consulta
`tabla_2` (o `bd_desv`) en la hoja configurada por `SISTEMA_SPREADSHEET_ID`.
Compose monta `token.json` como secreto de solo lectura; nunca monta el JSON
local que se utiliza para pruebas.

La API Android también expone perfiles y mensajes compartidos. Los modificadores
y administradores pueden realizar operaciones documentales; solo
administradores pueden gestionar perfiles o marcar mensajes como leídos. La
solicitud de descarga se registra en el perfil, pero no altera por sí misma los
permisos ACL de Drive; los enlaces de Drive siguen sujetos a los permisos que
Google aplique a cada archivo. El APK debug no es una versión de distribución;
la API Android de una publicación debe apuntar al dominio HTTPS del despliegue.

## Límites y validación pendiente

- Las cuentas generales requieren un perfil activo con rol autorizado en
  Supabase y, mientras el consentimiento OAuth de Google siga en modo Prueba,
  también deben figurar como usuarios de prueba de Google Cloud.
- La interfaz se comparte con escritorio y tiene diseño Streamlit adaptable;
  faltan pruebas manuales con teléfonos Android e iOS reales y con el editor PDF
  visual. La división de documentos continúa siendo función del servidor.
- Docker no está instalado en el entorno de desarrollo actual; por eso el
  Compose queda preparado, pero todavía no se ha construido ni desplegado en
  un servidor real.
- La primera publicación operativa debe ocurrir solo después de validar el
  OAuth, Drive/Sheets, migración y claves de Supabase, subida/separación de PDFs,
  guardado y reinicio con el servidor y teléfono del propietario.
