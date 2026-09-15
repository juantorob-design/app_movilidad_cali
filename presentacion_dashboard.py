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
      <h1>Sistema de Desvinculaciones</h1>
      <p>Presentación ejecutiva · Alcaldía de Santiago de Cali</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.info(
    "Este dashboard es un material independiente para exposición. "
    "No modifica la aplicación operativa ni requiere credenciales, tokens o datos personales."
)

metricas = [
    ("Versión operativa", "1.1.8"),
    ("Columnas de BD_DESV", 21),
    ("Desenlaces válidos", 3),
    ("Formatos de entrada", 4),
]
cols = st.columns(4)
for col, (label, value) in zip(cols, metricas):
    col.metric(label, value)

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
        st.success("Pendientes visibles y reubicables")

    st.subheader("Qué cambió en la versión 1.1.8")
    st.markdown(
        "- Visor del PDF dentro del registro, antes de guardar.\n"
        "- Resumen de archivos, campos detectados y destino previsto.\n"
        "- Checklist automático según el desenlace del expediente.\n"
        "- Bandeja de pendientes para documentos sin fecha de petición.\n"
        "- Asociación posterior por radicado o placa y unión al expediente."
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
        fecha guardada; si todavía no existe, queda en `PDFS Escaneados/Pendientes`
        identificado por radicado o placa.

        #### 4. Revisión de resultados
        Confirme el checklist de Solicitud, Recurso, Resolución, Notificación,
        Desistimiento o Constancia de ejecutoria. Revise la carpeta de destino,
        el PDF unificado y la fila relacionada en Google Sheets.

        #### 5. Pendientes y consulta
        En Consulta & Archivo revise la bandeja de PDF pendientes. Cuando aparezca
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
        ("1. Capturar", "Se cargan PDF, PNG, JPG o JPEG."),
        ("2. Leer y revisar", "Se extraen datos, se muestra el visor y el destino previsto."),
        ("3. Clasificar", "Se identifica recurso, sin recurso o desistimiento."),
        ("4. Validar", "El checklist muestra documentos presentes y faltantes."),
        ("5. Organizar", "Drive guarda por año o en Pendientes y genera el PDF unificado."),
        ("6. Sincronizar", "Sheets conserva los campos completos y sus enlaces."),
        ("7. Consultar", "El expediente y los pendientes se buscan por radicado o placa."),
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
    st.subheader("Pruebas de cierre")
    validaciones = [
    ("Google Sheets", "Lectura, escritura, actualización y limpieza de fila temporal", "APROBADA"),
    ("Google Drive", "Conexión con la carpeta principal y lectura de estructura", "APROBADA"),
    ("Duplicados", "Comparación por nombre y huella de contenido", "APROBADA"),
    ("Clasificación anual", "Año obtenido exclusivamente de la fecha de petición", "APROBADA"),
    ("Aplicación", "Compilación y estado HTTP de Streamlit", "APROBADA"),
    ("Gmail", "Permiso gmail.send en el token actual", "PENDIENTE DE AUTORIZACIÓN"),
    ]
    st.dataframe(
    pd.DataFrame(validaciones, columns=["Área", "Comprobación", "Resultado"]),
    width="stretch",
    hide_index=True,
    )
    st.info(
    "El correo de alertas queda activo después de pulsar "
    "«Actualizar autorización para notificaciones» y aceptar el permiso de Gmail."
    )

with tab_trabajo:
    st.subheader("Trabajo realizado")
    trabajo = [
        "Corrección del cargador de archivos y navegación del escritorio.",
        "Autenticación local, Google OAuth y persistencia segura del token.",
        "Roles Visualizador, Modificador, Administrador y Super Administrador.",
        "Lectura inteligente de PDF y detección de campos.",
        "Conversión de imágenes a PDF.",
        "Separación heurística, clasificación y unión ordenada de expedientes.",
        "Prevención de duplicados mediante nombre y huella de contenido.",
        "Checklist por proceso y estado documental visible.",
        "Resumen y visor integrado antes de guardar cada carga.",
        "Bandeja de pendientes y asociación posterior por radicado o placa.",
        "Integración de BD_DESV y DATOS con las 21 columnas reales.",
        "Preservación de datos históricos al anexar documentos.",
        "Instalador Windows con PyInstaller e Inno Setup.",
        "Actualizador autorizado desde GitHub Raw y release 1.1.8.",
        "Pruebas de sintaxis, dependencias, servidor, ejecutable e instalador.",
        "Prueba real de Google Sheets: escritura, lectura, actualización y eliminación controlada.",
        "Corrección de escritura por fila exacta para evitar desplazamientos de columnas.",
        "Verificación de Drive y retiro del Sheet antiguo de la configuración activa.",
    ]
    for item in trabajo:
        st.checkbox(item, value=True, disabled=True)
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
            st.image(path, caption=caption, use_container_width=True)
