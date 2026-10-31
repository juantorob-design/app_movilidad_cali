import os

import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="Presentación | Sistema de Desvinculaciones",
    page_icon="📊",
    layout="wide",
)

ROOT = os.path.dirname(os.path.abspath(__file__))
SCREENSHOTS = os.path.join(ROOT, "docs", "screenshots")

st.markdown(
    """
    <style>
    .hero {
        padding: 2rem 2.2rem;
        border-radius: 18px;
        background: linear-gradient(120deg, #0d2442, #126e8c);
        color: white;
        margin-bottom: 1.2rem;
    }
    .hero h1 { margin: 0; font-size: 2.2rem; }
    .hero p { margin: .45rem 0 0; font-size: 1.05rem; }
    .step {
        border-left: 4px solid #21a0c4;
        padding: .2rem 0 .2rem .8rem;
        margin: .65rem 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
      <h1>Secretaría de Tránsito y Transporte - Desvinculaciones</h1>
      <p>Presentación ejecutiva</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.info(
    "Este dashboard es un material independiente para exposición. "
    "No modifica la aplicación operativa ni requiere credenciales, tokens o datos personales."
)

metricas = [
    ("Versión escritorio declarada", "1.1.28"),
    ("APK Android", "0.1.5 / code 6 firmada e instalada; acceso Google y resumen autenticado probados en BlueStacks"),
    ("Columnas de BD_DESV", 21),
    ("Desenlaces válidos", 3),
    ("Pruebas automatizadas", "148 pasaron"),
]
with st.container(horizontal=True):
    for label, value in metricas:
        st.metric(label, value, border=True)
st.caption(
    "Corte: 31 de octubre de 2026. La versión declarada no confirma por sí sola "
    "que el instalador esté publicado o actualizado en todos los equipos."
)

tab_resumen, tab_capacitacion, tab_flujo, tab_trabajo, tab_validacion, tab_galeria = st.tabs(
    ["Resumen", "Capacitación", "Flujo de trabajo", "Trabajo realizado", "Validación", "Galería"]
)

with tab_resumen:
    st.subheader("¿Qué problema resuelve?")
    st.write(
        "Centraliza expedientes, documentos, metadatos, historial y permisos "
        "en un solo flujo. Reduce búsquedas manuales, duplicados y pérdida de "
        "información al completar procesos históricos."
    )
    left, right = st.columns(2)
    with left:
        st.markdown("#### Componentes")
        st.markdown(
            "- Escritorio visual de aplicaciones\n"
            "- Registro y digitalización\n"
            "- Buscador y archivo\n"
            "- Base histórica\n"
            "- Google Drive y Google Sheets\n"
            "- Roles y permisos\n"
            "- Instalador y actualizaciones"
        )
    with right:
        st.markdown("#### Resultados")
        st.success("Documentos organizados y trazables")
        st.success("Metadatos conservados al actualizar")
        st.success("Menos duplicados en Drive y Sheets")
        st.success("Distribución controlada por roles")
        st.success("Complementos sin vincular visibles y reubicables")

    st.subheader("Capacidades vigentes del sistema")
    st.markdown(
        "- Escritorio 1.1.28; Android 0.1.5 (versionCode 6) corregida, firmada e instalada en BlueStacks; acceso y resumen probados; IA local pendiente.\n"
        "- OCR local de PDFs con caché persistente y selección DirectML/CPU.\n"
        "- Detección, clasificación y separación de Solicitud, Resolución, Notificación, Recurso, Desistimiento y Constancia.\n"
        "- Visor PDF integrado, copias locales, foliación y barra de progreso.\n"
        "- Formulario administrativo precargado desde OCR, base local y Google Sheets, sin sobrescribir datos confirmados.\n"
        "- Checklist automático por tipo de caso y advertencia para radicados dudosos.\n"
        "- Drive organizado por año y expediente, con PDF completo y complementos en carpetas separadas.\n"
        "- Google Sheets con tabla, filtros, trazabilidad, actualización de filas y enlaces a Drive.\n"
        "- Consulta unificada por radicado, placa, empresa, NIT, cédula, ubicación física y fecha.\n"
        "- Roles, permisos de descarga, auditoría, deduplicación y actualizador autorizado desde GitHub.\n"
        "- Editor PDF local para unir, dividir, extraer, ordenar y rotar documentos."
    )
    st.subheader("Alcance móvil")
    st.markdown(
        "La APK permite seleccionar la petición principal en PDF o imagen y "
        "enviarla a la API para OCR y separación documental. Además, el código "
        "integra IA local Qwen2.5-VL 3B para analizar hasta cinco páginas y "
        "proponer radicado, placa y fecha sin sobrescribir campos escritos. "
        "La primera descarga requiere ~2,93 GB, conexión y teléfono con al menos "
        "6 GB de RAM. Debug y Release compilaron; la prueba de inferencia en dispositivo sigue "
        "pendiente. El complemento sin expediente es un flujo independiente; "
        "la PWA gratuita actual no procesa expedientes ni PDF."
    )

with tab_capacitacion:
    st.subheader("Guion de capacitación")
    st.markdown(
        """
        #### 1. Ingreso y permisos
        Inicie sesión con Google o con una cuenta local. Las cuentas nuevas quedan
        pendientes hasta que el Super Administrador asigne rol y estado activo.

        #### 2. Registro de entrada
        Cargue la petición o cualquier anexo. Revise el visor integrado, el resumen
        de lectura, el destino previsto y los datos que se copiarán al formulario.
        Complete solo los campos que el documento no permita leer automáticamente.

        #### 3. Regla documental principal
        El año de Drive siempre sale de la fecha de creación de la petición. Un
        anexo puede llegar sin fecha propia: si el expediente existe, reutiliza la
        fecha guardada; si todavía no existe, queda en
        `Pendientes/Por_vincular/PLACA` hasta localizar el expediente principal.

        #### 4. Revisión de resultados
        Confirme el checklist de Solicitud, Recurso, Resolución, Notificación,
        Desistimiento o Constancia de ejecutoria. Revise la carpeta de destino,
        el PDF unificado y la fila relacionada en Google Sheets.

        #### 5. Complementos y consulta
        En Consulta & Archivo revise la bandeja de documentos por vincular. Cuando aparezca
        la petición principal, el sistema puede mover los anexos a la carpeta anual,
        incorporarlos al expediente y reconstruir el PDF completo.

        #### 6. Actualización
        Si hay una versión nueva, seleccione `Actualizar ahora` para autorizarla o
        `Más tarde` para posponerla. No se descarga el instalador sin autorización.
        """
    )
    st.subheader("Ejemplo visible: proceso de Desistimiento")
    ejemplo_col1, ejemplo_col2 = st.columns(2)
    with ejemplo_col1:
        st.markdown(
            """
            **Caso:** un ciudadano desiste de la solicitud.

            1. Cargar la petición o el documento de desistimiento.
            2. Revisar el radicado, placa y fecha detectados.
            3. Seleccionar **Desistimiento** si el texto no lo identifica.
            4. Confirmar el tipo documental correspondiente.
            """
        )
    with ejemplo_col2:
        st.success("✅ Solicitud")
        st.success("✅ Desistimiento")
        st.warning("⬜ Resolución o acto correspondiente si aplica")
        st.caption(
            "El checklist permite ver inmediatamente qué está presente y qué "
            "debe completarse antes de cerrar el expediente."
        )
    st.warning(
        "Para una demostración use datos controlados o anonimizados. No exponga "
        "credenciales, tokens ni expedientes reales."
    )

with tab_flujo:
    st.subheader("Flujo funcional para explicar en la exposición")
    pasos = [
        ("1. Solicitud", "Inicia el análisis desde la petición y su fecha; extrae radicado, placa y datos disponibles."),
        ("2. Consulta QX", "Verifica la propiedad del vehículo antes de evaluar la actuación administrativa."),
        ("3. Resolución o requerimiento", "Si existe resolución, continúa con citación. Si solo existe requerimiento, también continúa con citación. Si no existe ninguno, revisa si hay desistimiento."),
        ("4. Citaciones", "Identifica y separa los oficios dirigidos a la empresa y al propietario."),
        ("5. Comunicación", "Distingue notificación personal, por aviso o por publicación web."),
        ("6. Recurso", "Si existe, procesa recurso, resolución del recurso, citación y notificación del recurso."),
        ("7. Cierre", "Registra constancia de ejecutoria y remisión a registro cuando correspondan."),
        ("8. Clasificar y guardar", "Usa solo Con recurso, Sin recurso o Desistimiento; separa bloques y conserva el PDF completo y la trazabilidad."),
    ]
    for title, description in pasos:
        st.markdown(
            f'<div class="step"><strong>{title}</strong><br>{description}</div>',
            unsafe_allow_html=True,
        )
    st.subheader("Integraciones")
    integraciones = pd.DataFrame(
        [
            {"Servicio": "Google Drive", "Función": "Archivos y PDF unificados", "Resultado": "Enlaces trazables"},
            {"Servicio": "Google Sheets", "Función": "Metadatos y estados", "Resultado": "Fila actualizada o nueva"},
            {"Servicio": "Supabase", "Función": "Perfiles y roles", "Resultado": "Acceso controlado"},
            {"Servicio": "GitHub", "Función": "Código y releases", "Resultado": "Instalador actualizable"},
        ]
    )
    st.dataframe(integraciones, width="stretch", hide_index=True)

with tab_validacion:
    st.subheader("Estado de validación al 31 de octubre de 2026")
    validaciones = [
        ("Suite automatizada", "158 pruebas Python pasaron en local", "APROBADA"),
        ("API Render", "OpenAPI 0.1.0; /health respondió 200; lista protegida sin token devolvió 401", "DISPONIBLE; AUTENTICACIÓN REQUERIDA"),
        ("Build Android", "0.1.5/code 6 Debug y Release compiladas; lintDebug y lintVitalRelease pasaron; firma v2 verificada", "BUILD Y FIRMA APROBADOS"),
        ("Inicio Android", "APK Release instalada y abierta en el AVD dedicado hasta acceso Google; sin excepción fatal", "SMOKE TEST APROBADO"),
        ("Búsqueda por ubicación", "No se confirmó la búsqueda con la Release corregida; no se usaron datos de expedientes como consulta de prueba", "PENDIENTE DE VALIDACIÓN"),
        ("Estado del archivo compartido", "Retest histórico de BlueStacks: 2 expedientes, 0 completos, 2 con faltantes y 2 documentos registrados", "LECTURA HISTÓRICA APROBADA"),
        ("IA en Android", "Qwen2.5-VL 3B; modelo de ~2,93 GB; no se descargó ni se probó inferencia en un teléfono", "PENDIENTE DE VALIDACIÓN EN TELÉFONO"),
        ("PDF de ejemplo", "87 páginas; OCR en 66, 25 bloques, Con recurso, 14 campos; 468,7 s", "PROCESADO LOCALMENTE"),
        ("Carga larga", "La API entrega un trabajo asíncrono y Android consulta avance por página", "PRUEBAS LOCALES APROBADAS"),
        ("Drive y Sheets", "No se cargaron archivos ni se escribieron datos en esta validación", "SIN ESCRITURAS; E2E PENDIENTE"),
        ("OAuth móvil", "ID token y lecturas OK; Release actualizada con Bearer en la consulta del trabajo OCR", "LECTURA APROBADA; E2E PENDIENTE"),
        ("Gmail", "Permiso gmail.send en el token actual", "PENDIENTE DE AUTORIZACIÓN"),
    ]
    st.dataframe(
        pd.DataFrame(validaciones, columns=["Área", "Comprobación", "Resultado"]),
        width="stretch",
        hide_index=True,
    )
    st.warning(
        "La carga de prueba en BlueStacks no quedó confirmada: el servidor "
        "reportó el trabajo previo aún en proceso y no se reenvió el archivo. "
        "No se confirmó escritura en Drive ni Sheets; verificar el estado antes "
        "de cualquier reintento."
    )
    st.info(
        "En la validación del 31 de octubre, la Release 0.1.5/code 6 se instaló "
        "y abrió en el AVD dedicado hasta la pantalla de acceso Google, sin "
        "excepción fatal; no se autenticó ni se realizaron escrituras. El "
        "retest histórico de BlueStacks sí completó OAuth y mostró 2 "
        "expedientes, 0 completos, 2 con faltantes y 2 documentos registrados. "
        "La búsqueda por ubicación sigue sin validación con la Release corregida. "
        "Render /health respondió 200 y las rutas protegidas sin token "
        "respondieron 401. No se repitió la carga del PDF y la IA no se ejecutó."
    )
    st.info(
        "Las validaciones históricas contra Google Drive/Sheets no se repitieron "
        "en este corte. El correo de alertas requiere autorizar gmail.send."
    )

with tab_trabajo:
    st.subheader("Trabajo realizado")
    st.markdown(
        "- Escritorio Windows con registro, búsqueda, archivo, permisos y dashboard operativo.\n"
        "- Carga Android de petición principal PDF/foto, complementos, OCR y separación por bloques; IA local Qwen2.5-VL integrada en el código para prellenar radicado, placa y fecha desde hasta cinco páginas. Debug compiló; falta validar inferencia física.\n"
        "- API móvil y escritorio comparten motor OCR, reglas de extracción y clasificación; Android completa campos vacíos, refresca el expediente y consulta trabajos OCR asíncronos con progreso.\n"
        "- API con integración a Google Drive/Sheets y autorización centralizada.\n"
        "- Clasificación permitida: Con recurso, Sin recurso o Desistimiento.\n"
        "- Escritorio declarado 1.1.28; Android 0.1.5 (versionCode 6) corregida, firmada e instalada en BlueStacks; autenticación y resumen aprobados; IA local pendiente.\n"
        "- Render desplegó 04594d8 y responde 200 en /health. La corrección del helper permitió consultar el resumen autenticado; la búsqueda por ubicación aún no se valida con la Release corregida.\n"
        "- Suite Python: 158 pruebas pasaron. Build Debug/Release, lintDebug y lintVitalRelease terminaron; no hay tests unitarios Kotlin. No se confirmó carga ni escritura de datos de prueba."
    )
    with open(os.path.join(ROOT, "docs", "INFORME_APLICACION.md"), "rb") as informe:
        informe_data = informe.read()
    st.download_button(
        "Descargar informe completo",
        data=informe_data,
        file_name="INFORME_APLICACION.md",
        mime="text/markdown",
    )

with tab_galeria:
    st.subheader("Galería para explicar la interfaz")
    imagenes = [
        ("01-escritorio-mosaico.png", "Escritorio principal"),
        ("02-entrada-expedientes.png", "Entrada de expedientes"),
        ("03-consulta-archivo.png", "Consulta y archivo"),
        ("04-base-historica.png", "Base histórica"),
        ("05-gestion-permisos.png", "Gestión de permisos"),
        ("06-mi-perfil.png", "Perfil de usuario"),
    ]
    for filename, caption in imagenes:
        path = os.path.join(SCREENSHOTS, filename)
        if os.path.exists(path):
            st.image(path, caption=caption, width="stretch")
