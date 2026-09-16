# Sistema de Desvinculaciones

Aplicación de escritorio para gestionar expedientes de desvinculación administrativa,
documentos digitalizados y sincronización con Google Drive y Google Sheets.

## Ejecución en desarrollo

```powershell
py -3.12 -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\streamlit run app_6.py
```

La dependencia `streamlit-pdf` se fija en una versión compatible con el visor
integrado de Streamlit para que la vista previa de documentos funcione también
en instalaciones nuevas.

Los PDF cargados se leen para identificar radicado, placa y fecha cuando esos
datos están disponibles en el texto. El archivo se normaliza como
`radicado_placa_fecha_ubicacion.pdf`; los PDF escaneados como imagen pueden
requerir que el usuario complete los campos del formulario. El registro muestra
un resumen y un visor integrado antes de guardar.

Las imágenes PNG y JPG cargadas como documentos se convierten automáticamente
a PDF antes de guardarse. De esta forma pueden formar parte del expediente
unificado, conservar su tipo documental y sincronizarse con Drive y Sheets.

Cuando se cargan varios PDF, la pantalla permite ordenar sus archivos antes de
guardarlos. El sistema genera además un PDF unificado en ese orden y conserva
los archivos fuente y su trazabilidad dentro del expediente.

Los anexos pueden llegar sin fecha de petición. Si el expediente todavía no
existe, se conservan en `PDFS Escaneados/Pendientes` y se pueden consultar por
radicado o placa hasta que la petición principal permita reubicarlos y unirlos.
El checklist documental se calcula según el desenlace: sin recurso, con recurso
o desistimiento.

Para usar el escritorio integrado:

```powershell
.\venv\Scripts\python run_app.py
```

Para abrir únicamente el dashboard de presentación:

```powershell
.\abrir_presentacion.ps1
```

El dashboard se abre en `http://127.0.0.1:8510`.

El dashboard y el informe son materiales independientes para capacitación y
exposición. Permanecen en la carpeta principal/documentación y no se incluyen en
la compilación del programa operativo: `run_app.spec` solo empaqueta `run_app.py`,
`app_6.py`, `updater.py`, imágenes y la configuración OAuth.

## Compilación para Windows

Ejecuta `build_app.ps1` para generar el ejecutable. Después compila
`installer.iss` con Inno Setup para crear el instalador de Windows.

Las actualizaciones publicadas se consultan mediante `version.json`. Cuando hay
una versión nueva, la aplicación muestra botones para autorizar **Actualizar
ahora** o seleccionar **Más tarde**; el instalador no se descarga sin autorización.
Al autorizarla, la aplicación se cierra, el instalador solicita elevación de
Windows, espera a terminar la instalación y abre nuevamente la versión actualizada.

El instalador incluye ONNX Runtime DirectML para acelerar el OCR con la GPU
disponible en Windows. La aplicación detecta automáticamente CUDA, DirectML o
CPU; no instala Python ni solicita permisos administrativos para acceder a la
GPU. Si el equipo no tiene una GPU compatible o el controlador no está
disponible, el OCR continúa funcionando mediante CPU local.

## Datos y credenciales

Las credenciales OAuth, tokens, la base local y los entornos de Python están excluidos
del repositorio. Deben configurarse localmente en cada equipo.

El instalador incluye únicamente la configuración del cliente OAuth de escritorio
(`credentials.json`) para permitir la primera autorización de Google. El token de
cada usuario se guarda localmente en `%LOCALAPPDATA%\SistemaDesvinculaciones\token.json`
y nunca se incluye en el instalador ni en GitHub.

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
