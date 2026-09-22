# Secretaría de Tránsito y Transporte - Desvinculaciones

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

El flujo documental debe seguir la secuencia administrativa correcta: petición,
consulta QX, resolución o requerimiento, citaciones, notificación, recurso y
constancia de ejecutoria. La aplicación debe clasificar el caso como `Con
recurso`, `Sin recurso` o `Desistimiento` y separar cada documento en su carpeta
correspondiente dentro del expediente. Solo después de separar por tipos se
aplica la lectura y el OCR de cada bloque para rellenar los formularios y la
hoja de registro.

Las imágenes PNG y JPG cargadas como documentos se convierten automáticamente
a PDF antes de guardarse. De esta forma pueden formar parte del expediente
unificado, conservar su tipo documental y sincronizarse con Drive y Sheets.

Cuando se cargan varios PDF, el sistema limpia las páginas blancas, separa los
bloques consecutivos y conserva las páginas de origen de cada complemento. El
PDF unificado se genera con la prelación administrativa obligatoria: petición,
consulta QX, resolución o requerimiento, desistimiento cuando corresponda,
citaciones, notificaciones, recurso y sus actuaciones, constancia de ejecutoria
y remisión a registro. Los documentos que no pertenecen al flujo quedan al
final como `Otro`.

Los complementos temporales usan la convención
`NRO_PETICION_PLACA_DD_MM_AAAA_CAJA_FOLDER_CARPETA_RECURSO.pdf`. Al confirmar
el registro se trasladan desde `Peticion/RADICADO_PLACA_DD_MM_AAAA` a
`PDFS Escaneados/AÑO/RADICADO_PLACA_DD_MM_AAAA`, manteniendo sus subcarpetas
por tipo documental.
En la consulta del expediente se puede elegir entre el PDF completo unificado
y un explorador individual de complementos.

Los anexos pueden llegar sin fecha de petición. Si el expediente todavía no
existe, se conservan en la carpeta temporal de la petición y se pueden
consultar por radicado o placa hasta confirmar los datos y unirlos.
El checklist documental se calcula según el desenlace: sin recurso, con recurso
o desistimiento.

Para usar el escritorio integrado:

```powershell
.\venv\Scripts\python run_app.py
```

## Validación y preparación para release

Las reglas documentales y los nombres de expediente se centralizan en el módulo
`document_rules.py` para mantener una base única de validación y evitar que la
UI o el OCR rompan la lógica de clasificación documental.

Se incluye una prueba mínima con `unittest` para validar:

- clasificación de caso: `Con recurso`, `Sin recurso`, `Desistimiento`
- detección de tipos documentales
- generación de nombres de expediente y PDF

```powershell
python -m unittest discover -s tests -v
```

Antes de publicar una versión se recomienda dejar el repositorio limpio usando
los patrones del `.gitignore` del proyecto y evitar subir artefactos
generados, cachés OCR, tokens, credenciales, PDFs temporales y binarios de
construcción.

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

### Análisis con IA local

El análisis generativo es opcional y se ejecuta localmente mediante
[Ollama](https://ollama.com/). El texto OCR no se envía a Gemini ni a otro
servicio externo. Instala Ollama, inicia su servicio y descarga un modelo:

```powershell
ollama pull qwen2.5:7b
```

La aplicación detecta Ollama en `http://127.0.0.1:11434`, inicia el servicio
local si está instalado y ejecuta automáticamente el análisis estructurado
después del OCR. Se puede cambiar el modelo mediante
`SISTEMA_OLLAMA_MODEL`; la URL y el tiempo de espera también se pueden ajustar
con `SISTEMA_OLLAMA_URL` y `SISTEMA_OLLAMA_TIMEOUT`. Si Ollama no está
disponible, el OCR, las reglas administrativas y el formulario siguen
funcionando sin cambios.

El instalador de Windows incluye Ollama y lo ejecuta silenciosamente solo si
no existe una instalación compatible. Si falta `qwen2.5:7b`, la aplicación
inicia su descarga en segundo plano y muestra su estado. Los modelos se
conservan en `%USERPROFILE%\.ollama\models` durante las actualizaciones.

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
