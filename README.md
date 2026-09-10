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

El archivo histórico incluido en `respaldo/` se conserva como respaldo de solo lectura.
