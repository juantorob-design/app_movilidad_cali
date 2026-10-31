# API móvil en Render Free (pruebas)

Este despliegue es una alternativa de prueba para la API móvil cuando Cloud Run
no está disponible. No es apropiado para operar expedientes reales: el servicio
gratuito puede apagarse por inactividad, su disco local es temporal y el plan
puede suspender servicios al agotar sus horas incluidas. Los PDF y datos
operacionales deben permanecer en Google Drive y Sheets, no en el filesystem del
contenedor.

## Crear el servicio

1. Sube a GitHub únicamente los cambios necesarios del repositorio y confirma
   que `.env`, `token.json`, `credentials.json`, PDFs y archivos de datos estén
   excluidos. No conectes Render a un fork o repositorio público que exponga
   información sensible.
2. En Render crea un **Blueprint** desde el repositorio y selecciona
   `render.yaml`. Comprueba que el servicio `sistema-desvinculaciones-api` use
   el plan **Free**. La configuración compila `Dockerfile.mobile-api`, publica
   `/health` como comprobación y desactiva los despliegues automáticos.
3. En la configuración de entorno del servicio, carga los valores solicitados
   por el Blueprint:
   - `SISTEMA_GOOGLE_WEB_CLIENT_ID`: el cliente Web OAuth del proyecto
     `sistema-desvinculaciones-cali`
     (`1019857870350-ccrqd53kcl0c6k799f0om2p5fnloviij.apps.googleusercontent.com`),
     que debe coincidir con la audiencia de los ID tokens de Android.
   - `SISTEMA_WEB_OWNER_EMAIL`: el correo propietario autorizado para Drive y
     Sheets.
   - `SISTEMA_SPREADSHEET_ID`: ID de la hoja operacional.
   - `SISTEMA_DRIVE_FOLDER_ID`: ID de la carpeta raíz de expedientes.
   - `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY`: valores del proyecto
     Supabase. La clave service role debe guardarse únicamente como secreto de
     Render.
4. Agrega `token.json` como **Secret File** del servicio, con nombre
   `token.json`. Render lo monta como `/etc/secrets/token.json`, ruta ya
   configurada mediante `SISTEMA_GOOGLE_TOKEN_FILE`. Usa un token renovable de
   la cuenta propietaria con los alcances necesarios de Drive y Sheets. No
   subas el archivo al repositorio ni lo pegues en este documento.
5. Inicia el primer despliegue desde Render y espera a que `/health` pase la
   comprobación. La ruta de salud no revela datos y no requiere autenticación.
   `/api/v1/me` y las demás rutas funcionales sí requieren un ID token Google.

## URL y activación automática desde Android

Render asignará al servicio una URL HTTPS `https://...onrender.com`. Compila
la APK indicando esa URL con la barra final:

Desde `android_app`, compila el APK Release con la clave de distribución local
configurada y protegida:

```powershell
.\build_release.ps1 -ApiBaseUrl https://NOMBRE-DEL-SERVICIO.onrender.com/
```

El wrapper usa el cliente Web OAuth del proyecto activo por defecto. Para
sobrescribirlo explícitamente, pasa `-GoogleWebClientId` con el mismo valor
configurado en `SISTEMA_GOOGLE_WEB_CLIENT_ID` en Render.

No guardes la clave ni sus contraseñas en el repositorio. Mantén una copia
protegida del archivo PKCS#12 en Drive privado y guarda su contraseña en un
gestor de contraseñas independiente. El archivo PKCS#12 está cifrado con esa
contraseña; para firmar desde otra instalación de Windows, restaura el archivo
y vuelve a proteger la contraseña con el perfil de Windows de ese equipo.

Al iniciar sesión, la APK llama `/health` antes de abrir Google Credential
Manager. Esa petición despierta automáticamente la instancia gratuita si estaba
inactiva; la aplicación reintenta mientras el servicio termina de arrancar.
No se necesita un botón ni un arranque manual. Tras más de 15 minutos sin
tráfico, Render puede dormir el servicio y el siguiente inicio de sesión puede
demorar alrededor de un minuto. Si Render suspende la instancia por límites de
uso, el despertar automático no puede levantarla hasta que el servicio vuelva a
estar disponible.

## Límites y validación

- Render Free puede reiniciar el contenedor y no proporciona disco persistente
  para este servicio. No guardes ahí expedientes, archivos subidos ni bases de
  datos.
- Google Drive y Sheets permanecen como almacenamiento de documentos y datos.
  Antes de cualquier uso, prueba con documentos ficticios y verifica OAuth,
  perfiles Supabase, consulta, carga, OCR y guardado.
- La URL pública de `/health` sirve para despertar y comprobar el proceso; no
  agregues credenciales a esa ruta. El resto de la API exige autenticación y
  permisos centralizados.
- No publiques un APK de distribución hasta usar la URL HTTPS real y validar
  firma, autorización, operación móvil completa y protección de datos.
