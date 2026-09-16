# Instrucciones para publicar el Release v1.1.12 en GitHub

## 📋 Requisitos previos

- Acceso a GitHub con permisos de push a `juantorob-design/app_movilidad_cali`.
- Los siguientes archivos compilados y listos:
  - Ejecutable: `dist/SistemaDesvinculaciones/SistemaDesvinculaciones.exe`
  - Notas de lanzamiento: `RELEASE_NOTES_1.1.12.md`
  - Pantallas capturadas en `docs/screenshots/`

---

## 🔧 Opción 1: Publicar desde GitHub Web (Recomendado para primeras versiones)

### Paso 1: Ir a la página de releases

1. Abre en el navegador:
   ```
   https://github.com/juantorob-design/app_movilidad_cali/releases
   ```

2. Haz clic en el botón **"Draft a new release"** (o **"Create a new release"** si es la primera vez).

### Paso 2: Completar los detalles del release

En el formulario, rellena los siguientes campos:

**Tag version:**
```
v1.1.12
```

**Release title:**
```
Sistema de Desvinculaciones v1.1.12 - Consulta Ampliada e Integración Robusta
```

**Descripción del release:**

Copia y pega el contenido completo de `RELEASE_NOTES_1.1.12.md`. El contenido incluye:

```markdown
# Sistema de Desvinculaciones - Versión 1.1.12

**Fecha de lanzamiento:** 16 de septiembre de 2026  
**Versión anterior:** 1.1.11  
**Plataforma:** Windows 64-bit  
**Tamaño del instalador:** ~28 MB  

[... resto del contenido de RELEASE_NOTES_1.1.12.md ...]
```

### Paso 3: Añadir capturas de pantalla en la descripción

Después de copiar las notas, añade una sección **Galería de Pantallas**:

```markdown
## 📸 Galería de Pantallas

### Escritorio Principal
![Escritorio Principal](https://github.com/juantorob-design/app_movilidad_cali/raw/main/docs/screenshots/01-escritorio-mosaico.png)

### Registro de Expedientes
![Entrada de Expedientes](https://github.com/juantorob-design/app_movilidad_cali/raw/main/docs/screenshots/02-entrada-expedientes.png)

### Consulta y Archivo
![Consulta y Archivo](https://github.com/juantorob-design/app_movilidad_cali/raw/main/docs/screenshots/03-consulta-archivo.png)

### Base Histórica
![Base Histórica](https://github.com/juantorob-design/app_movilidad_cali/raw/main/docs/screenshots/04-base-historica.png)

### Gestión de Permisos
![Gestión de Permisos](https://github.com/juantorob-design/app_movilidad_cali/raw/main/docs/screenshots/05-gestion-permisos.png)

### Perfil de Usuario
![Perfil de Usuario](https://github.com/juantorob-design/app_movilidad_cali/raw/main/docs/screenshots/06-mi-perfil.png)
```

**Nota:** Las URLs de las imágenes asumen que ya están en la rama `main` del repositorio en `docs/screenshots/`.

### Paso 4: Subir el archivo ejecutable

1. Desplázate a la sección **"Attachments"** (o similar, según la versión de GitHub).
2. Arrastra y suelta o selecciona el archivo:
   ```
   SistemaDesvinculaciones-Setup-1.1.12.exe
   ```
   desde `C:\Users\-\Desktop\sistema_desvinculaciones\dist\SistemaDesvinculaciones\`

3. **Alternativa:** Si el navegador no permite archivos de este tamaño, sube el archivo como artifact usando:
   - Las GitHub Actions.
   - O publica el instalador en una rama de releases dedicada.

### Paso 5: Marcar como "Latest Release" (opcional)

Si esta es la última versión estable, asegúrate de que el checkbox **"Set as the latest release"** esté marcado.

### Paso 6: Publicar

1. Haz clic en **"Publish release"**.
2. GitHub creará automáticamente un tag `v1.1.12` en tu repositorio.

---

## 🔄 Opción 2: Publicar desde línea de comandos (Avanzado)

Si prefieres manejar todo desde PowerShell o Git CLI:

### Paso 1: Crear un tag anotado

```powershell
cd C:\Users\-\Desktop\sistema_desvinculaciones
git tag -a v1.1.12 -m "Sistema de Desvinculaciones v1.1.12 - Consulta Ampliada e Integración Robusta"
```

### Paso 2: Subir el tag a GitHub

```powershell
git push origin v1.1.12
```

### Paso 3: Crear el release desde la línea de comandos con GitHub CLI

Si tienes instalado GitHub CLI (`gh`):

```powershell
$releaseNotes = Get-Content .\RELEASE_NOTES_1.1.12.md -Raw
gh release create v1.1.12 --title "Sistema de Desvinculaciones v1.1.12" --notes $releaseNotes `
  .\dist\SistemaDesvinculaciones\SistemaDesvinculaciones.exe
```

**Alternativa sin GitHub CLI:**

Sube manualmente el archivo ejecutable al release en GitHub Web después de que se haya creado el tag.

---

## ✅ Checklist pre-publicación

Antes de hacer clic en **"Publish"**, verifica que:

- [ ] **Tag:** Comienza con `v1.1.12` (ej: `v1.1.12`, no `1.1.12` solo).
- [ ] **Descripción:** Incluye todas las secciones de `RELEASE_NOTES_1.1.12.md`.
- [ ] **Ejecutable:** `SistemaDesvinculaciones-Setup-1.1.12.exe` está subido o será subido.
- [ ] **Screenshots:** Las referencias a imágenes apuntan a URLs válidas en GitHub.
- [ ] **version.json:** Apunta a la descarga correcta:
  ```json
  "download_url": "https://github.com/juantorob-design/app_movilidad_cali/releases/download/v1.1.12/SistemaDesvinculaciones-Setup-1.1.12.exe"
  ```
- [ ] **Latest Release:** Si es la versión actual, marca **"Set as the latest release"**.

---

## 📝 Post-publicación

Después de publicar el release:

1. **Verifica el enlace del instalador:**
   ```
   https://github.com/juantorob-design/app_movilidad_cali/releases/download/v1.1.12/SistemaDesvinculaciones-Setup-1.1.12.exe
   ```

2. **Prueba la descarga** desde una sesión incógnita o diferente para confirmar que el archivo es accesible.

3. **Valida el actualizador:**
   - Abre la aplicación compilada versión 1.1.11.
   - El actualizador debe detectar la nueva versión 1.1.12.
   - Confirma que el enlace de descarga funciona.

4. **Documenta cualquier feedback** en el repositorio o en un issue.

---

## 🔗 Enlaces importantes

- **Release Page:** https://github.com/juantorob-design/app_movilidad_cali/releases
- **Version File:** https://raw.githubusercontent.com/juantorob-design/app_movilidad_cali/main/version.json
- **Instalador:** https://github.com/juantorob-design/app_movilidad_cali/releases/download/v1.1.12/SistemaDesvinculaciones-Setup-1.1.12.exe

---

## ⚠️ Notas de seguridad

- **No publiques tokens o credenciales** en las notas de lanzamiento.
- **No incluyas datos de prueba reales** que contengan información sensible.
- **Valida que version.json sea accesible desde GitHub Raw** para que el actualizador funcione.
- **Prueba el instalador en una máquina limpia** antes de marcar como "Latest Release".

---

**Versión de estas instrucciones:** 1.0  
**Última actualización:** 16 de septiembre de 2026  
**Estado:** Listo para ejecución  
