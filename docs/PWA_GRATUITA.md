# PWA gratuita: alcance y despliegue

La alternativa sin servidor propio usa GitHub Pages para servir la interfaz
estática y Supabase para autenticación, perfiles, permisos y buzón. Google Drive
y Sheets siguen siendo los repositorios actuales de documentos y expedientes.
Este despliegue no contiene secretos privilegiados.

## Funciones disponibles en esta primera etapa

- Inicio de sesión Google mediante Supabase Auth y flujo PKCE.
- Verificación del estado y rol del perfil antes de mostrar el espacio.
- Consulta y envío de mensajes del buzón compartido.
- Consulta de perfiles y solicitudes de descarga para administradores.
- Solicitud de permiso de descarga para perfiles visualizadores.
- Instalación como PWA en Android, iOS y equipos compatibles.

La solicitud solo se registra en el perfil compartido para revisión
administrativa. Aprobarla no modifica los permisos ACL de Google Drive; los
enlaces externos a documentos siguen sujetos a los permisos configurados en
Google.

La app usa la clave pública `anon` desde el navegador. La seguridad depende de
RLS y de las funciones existentes. **Nunca** se debe publicar
`SUPABASE_SERVICE_ROLE_KEY`, tokens Google, credenciales OAuth ni credenciales
de Drive/Sheets.

## Publicar en GitHub Pages

1. En los ajustes del repositorio, habilita Pages con **GitHub Actions** como
   fuente de publicación.
2. En `Settings > Secrets and variables > Actions > Variables`, crea:
   - `SISTEMA_SUPABASE_URL`: URL HTTPS del proyecto Supabase.
   - `SISTEMA_SUPABASE_ANON_KEY`: clave pública anon/publishable del proyecto.
3. En Supabase Auth, configura como URL del sitio la URL Pages del repositorio
   y agrega esa misma URL (con la ruta del repositorio) a las redirecciones
   permitidas. La ruta del sitio de este repositorio es
   `https://juantorob-design.github.io/app_movilidad_cali/`.
4. Verifica que Google esté habilitado como proveedor de Supabase Auth y que el
   callback OAuth de Supabase esté registrado en el cliente OAuth de Google.
5. Publica los cambios en `main` o ejecuta manualmente el workflow **Deploy
   static PWA**. El workflow valida las variables, genera `config.js` solo en
   el artefacto de Pages y publica `deploy/pwa`.
6. Prueba inicio y cierre de sesión, perfil pendiente/activo, envío de mensaje,
   consulta administrativa de perfiles y solicitud de permisos con cuentas de
   prueba aprobadas.

La clave anon es pública por diseño: puede aparecer en el JavaScript descargado
por cualquier visitante. No uses aquí una clave service-role o secret. La
política RLS de Supabase debe seguir habilitada y validarse antes de distribuir
el sitio.

## Límites funcionales actuales

Esta interfaz **todavía no procesa expedientes ni PDFs**. El flujo de OCR,
separación por páginas, clasificación administrativa y guardado en Drive/Sheets
continúa en la aplicación de escritorio y en la API Python actuales. No se
deben subir documentos a esta primera PWA.

La PWA no guarda mensajes, expedientes ni PDFs para uso sin conexión. El plan
gratuito de Supabase puede pausar proyectos con poca actividad; no ofrece una
garantía de disponibilidad continua. GitHub Pages solo sirve contenido
estático: no sustituye FastAPI ni ejecuta OCR.

La primera PWA solo consulta los perfiles desde una sesión administrativa; no
permite cambiar roles o permisos. La función SQL existente requiere una
protección adicional para garantizar que otro administrador no pueda alterar
el acceso de la cuenta propietaria. Hasta verificar esa regla en el servidor,
los cambios administrativos siguen en los clientes actuales.

Antes de migrar el módulo de expedientes hay que definir y probar una interfaz
segura para Sheets/Drive y medir una opción de OCR local en navegador o Android.
No se debe exponer un token Google de propietario en el cliente para evitar
construir un servidor.
