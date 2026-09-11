# Sistema de Desvinculaciones

Aplicación de escritorio para gestionar expedientes de desvinculación administrativa,
documentos digitalizados y sincronización con Google Drive y Google Sheets.

## Ejecución en desarrollo

```powershell
py -3.12 -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\streamlit run app_6.py
```

Para usar el escritorio integrado:

```powershell
.\venv\Scripts\python run_app.py
```

## Compilación para Windows

Ejecuta `build_app.ps1` para generar el ejecutable. Después compila
`installer.iss` con Inno Setup para crear el instalador de Windows.

Las actualizaciones publicadas se consultan mediante `version.json` y se aplican
ejecutando el instalador de la nueva versión, sin reemplazar archivos mientras
la aplicación está abierta.

## Datos y credenciales

Las credenciales OAuth, tokens, la base local y los entornos de Python están excluidos
del repositorio. Deben configurarse localmente en cada equipo.

### Supabase y autorización

El proyecto usa Supabase para autenticar cuentas locales y mantener el perfil remoto
(estado y rol). La base de datos aplica RLS: las cuentas nuevas quedan `Pendiente` y
solo el Super Administrador `juan.torob@cun.edu.co` puede activarlas o cambiar sus
permisos.

1. Copia `.env.example` como `.env`.
2. En Supabase, copia únicamente `Project URL` y la clave pública `anon`.
3. Nunca uses `service_role` en la aplicación ni la publiques.
4. Configura el Client ID y Client Secret de Google en Supabase y conserva el
   `credentials.json` de Google fuera del repositorio.

La integración mantiene el modo local como respaldo durante la migración. Cuando
Supabase está configurado, los inicios locales nuevos se registran en Supabase y
los perfiles autenticados toman su estado y rol remotos antes de entrar al escritorio.

Los expedientes y respaldos con datos personales no deben publicarse en GitHub ni
incluirse en releases públicos. El archivo histórico local debe conservarse fuera
del repositorio, con acceso restringido y cifrado.
