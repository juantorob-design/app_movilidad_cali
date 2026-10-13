package co.sistemadesvinculaciones.mobile

import android.net.Uri
import android.os.Bundle
import android.database.Cursor
import android.content.ActivityNotFoundException
import android.content.Intent
import android.provider.OpenableColumns
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.browser.customtabs.CustomTabsIntent
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.NoCredentialException
import androidx.compose.foundation.clickable
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import androidx.compose.ui.res.painterResource
import androidx.lifecycle.lifecycleScope
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.delay

data class Expediente(
    val radicado_padre: String,
    val placa: String,
    val fecha_solicitud: String,
    val propietario: String,
    val cedula_propietario: String,
    val empresa: String,
    val nit_empresa: String,
    val caso: String,
)

private data class DocumentoDrive(
    val nombre: String,
    val tipo: String,
    val url: String,
    val archivoOrigen: String,
    val paginasOrigen: String,
)

private data class ComplementoPendiente(
    val id: String,
    val nombre: String,
    val archivos: List<String>,
)

private data class CaseEditorField(
    val key: String,
    val label: String,
    val multiline: Boolean = false,
)

private data class WorkspaceProfile(
    val email: String,
    val fullName: String,
    val role: String,
    val status: String,
    val downloadAllowed: Boolean,
    val downloadRequested: Boolean,
)

private data class WorkspaceMessage(
    val id: String,
    val senderEmail: String,
    val subject: String,
    val message: String,
    val createdAt: String,
    val readAt: String,
)

private val CaseEditorFields = listOf(
    CaseEditorField("fecha_solicitud", "Fecha de solicitud (AAAA-MM-DD)"),
    CaseEditorField("placa", "Placa"),
    CaseEditorField("empresa", "Empresa"),
    CaseEditorField("nit_empresa", "NIT de la empresa"),
    CaseEditorField("direccion_empresa", "Dirección de la empresa", multiline = true),
    CaseEditorField("propietario", "Propietario"),
    CaseEditorField("cedula_propietario", "Cédula del propietario"),
    CaseEditorField("direccion_propietario", "Dirección del propietario", multiline = true),
    CaseEditorField("solicitante", "Solicitante"),
    CaseEditorField("qx_verificado", "Consulta QX verificada"),
    CaseEditorField("requerimiento", "Requerimiento"),
    CaseEditorField("resolucion", "Resolución"),
    CaseEditorField("fecha_resolucion", "Fecha de resolución"),
    CaseEditorField("desistimiento", "Desistimiento"),
    CaseEditorField("tipo_notificacion", "Tipo de notificación"),
    CaseEditorField("fecha_notificacion", "Fecha de notificación"),
    CaseEditorField("recurso", "Recurso"),
    CaseEditorField("fecha_recurso", "Fecha del recurso"),
    CaseEditorField("resolucion_recurso", "Resolución del recurso"),
    CaseEditorField("fecha_resolucion_recurso", "Fecha de resolución del recurso"),
    CaseEditorField("fecha_ejecutoria", "Fecha de ejecutoria"),
    CaseEditorField("fecha_remision_registro", "Fecha de remisión a registro"),
    CaseEditorField("estado", "Estado"),
    CaseEditorField("caso", "Clasificación final"),
    CaseEditorField("ubicacion", "Ubicación física"),
    CaseEditorField("caja", "Caja"),
    CaseEditorField("observaciones", "Observaciones", multiline = true),
)

private val Navy = Color(0xFF0D1322)
private val Panel = Color(0xFF172136)
private val PanelRaised = Color(0xFF1D2B43)
private val Cyan = Color(0xFF38BDF8)
private val Muted = Color(0xFFB8C4D6)
private val DividerColor = Color(0xFF2D3B52)

private val AppColors = darkColorScheme(
    primary = Cyan,
    onPrimary = Navy,
    background = Navy,
    onBackground = Color(0xFFF8FAFC),
    surface = Panel,
    onSurface = Color(0xFFF8FAFC),
    surfaceVariant = PanelRaised,
    onSurfaceVariant = Muted,
    outline = DividerColor,
    error = Color(0xFFFCA5A5),
)

private fun normalizarFechaSolicitud(value: String): String {
    val text = value.trim()
    val formatters = listOf(
        DateTimeFormatter.ISO_LOCAL_DATE,
        DateTimeFormatter.ofPattern("d/M/uuuu"),
        DateTimeFormatter.ofPattern("d-M-uuuu"),
    )
    var lastError: DateTimeParseException? = null
    for (formatter in formatters) {
        try {
            return LocalDate.parse(text, formatter).format(DateTimeFormatter.ISO_LOCAL_DATE)
        } catch (error: DateTimeParseException) {
            lastError = error
        }
    }
    throw lastError ?: DateTimeParseException("Invalid date", text, 0)
}

class MainActivity : ComponentActivity() {
    private val apiWakeClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(35, TimeUnit.SECONDS)
            .callTimeout(35, TimeUnit.SECONDS)
            .build()
    }
    private val apiRequestClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(5, TimeUnit.MINUTES)
            .readTimeout(15, TimeUnit.MINUTES)
            .callTimeout(20, TimeUnit.MINUTES)
            .build()
    }
    private var appState by mutableStateOf<AppState>(AppState.Login)
    private var userEmail by mutableStateOf("")
    private var userRole by mutableStateOf("")
    private var downloadAllowed by mutableStateOf(false)
    private var downloadRequested by mutableStateOf(false)
    private var authToken by mutableStateOf("")
    private var cases by mutableStateOf<List<Expediente>>(emptyList())
    private var selectedCaseData by mutableStateOf<JSONObject?>(null)
    private var selectedDocuments by mutableStateOf<List<DocumentoDrive>>(emptyList())
    private var pendingComplements by mutableStateOf<List<ComplementoPendiente>>(emptyList())
    private var uploadSummary by mutableStateOf("")
    private var message by mutableStateOf("")
    private var busy by mutableStateOf(false)
    private var caseListTitle by mutableStateOf("Consulta de expedientes")
    private var sharedProfiles by mutableStateOf<List<WorkspaceProfile>>(emptyList())
    private var sharedMessages by mutableStateOf<List<WorkspaceMessage>>(emptyList())

    sealed class AppState {
        object Login : AppState()
        object Home : AppState()
        object CaseList : AppState()
        object CaseDetail : AppState()
        object CaseEdit : AppState()
        object NewCase : AppState()
        object Profile : AppState()
        object WorkspacePermissions : AppState()
        object WorkspaceInbox : AppState()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = AppColors) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    when (appState) {
                        AppState.Login -> {
                            LoginScreen(
                                message = message,
                                busy = busy,
                                onSignIn = ::signIn,
                            )
                        }
                        AppState.Home -> {
                            HomeScreen(
                                userEmail = userEmail,
                                userRole = userRole,
                                canEditCases = userRole in setOf(
                                    "Modificador",
                                    "Administrador",
                                    "Super Administrador",
                                ),
                                canManageProfiles = userRole in setOf(
                                    "Administrador",
                                    "Super Administrador",
                                ),
                                downloadAllowed = downloadAllowed,
                                downloadRequested = downloadRequested,
                                cases = cases,
                                message = message,
                                busy = busy,
                                onOpenCases = {
                                    caseListTitle = "Consulta de expedientes"
                                    appState = AppState.CaseList
                                },
                                onOpenHistorical = {
                                    caseListTitle = "Base Histórica"
                                    appState = AppState.CaseList
                                },
                                onCreateCase = { appState = AppState.NewCase },
                                onOpenProfile = { appState = AppState.Profile },
                                onOpenPermissions = ::openSharedPermissions,
                                onOpenInbox = ::openSharedInbox,
                                onRequestDownload = ::requestDownloadPermission,
                                onOpenDrive = {
                                    openExternalUrl(
                                        "https://drive.google.com/drive/folders/" +
                                            BuildConfig.DRIVE_FOLDER_ID,
                                        "Google Drive",
                                    )
                                },
                                onOpenSheets = {
                                    openExternalUrl(
                                        "https://docs.google.com/spreadsheets/d/" +
                                            BuildConfig.SPREADSHEET_ID + "/edit",
                                        "Google Sheets",
                                    )
                                },
                                onRefresh = ::refreshCases,
                                onLogout = ::logout,
                            )
                        }
                        AppState.CaseList -> {
                            CaseListScreen(
                                cases = cases,
                                message = message,
                                busy = busy,
                                userEmail = userEmail,
                                title = caseListTitle,
                                onCaseSelect = ::selectCase,
                                onRefresh = ::refreshCases,
                                onHome = { appState = AppState.Home },
                                onLogout = ::logout,
                            )
                        }
                        AppState.CaseDetail -> {
                            CaseDetailScreen(
                                caseData = selectedCaseData,
                                documents = selectedDocuments,
                                pendingComplements = pendingComplements,
                                uploadSummary = uploadSummary,
                                statusMessage = message,
                                busy = busy,
                                canEditCases = userRole in setOf(
                                    "Modificador",
                                    "Administrador",
                                    "Super Administrador",
                                ),
                                onBack = { appState = AppState.CaseList },
                                onEditCase = { appState = AppState.CaseEdit },
                                onUploadPdf = ::uploadCasePdf,
                                onRefreshChecklist = ::refreshChecklist,
                                onLinkComplement = ::linkPendingComplement,
                            )
                        }
                        AppState.CaseEdit -> {
                            selectedCaseData?.let { caseData ->
                                CaseEditorScreen(
                                    caseData = caseData,
                                    busy = busy,
                                    message = message,
                                    onBack = { appState = AppState.CaseDetail },
                                    onSave = ::updateCase,
                                )
                            }
                        }
                        AppState.NewCase -> {
                            NewCaseScreen(
                                busy = busy,
                                message = message,
                                onBack = { appState = AppState.Home },
                                onCreate = ::createCase,
                                onUploadComplement = { plate, uri ->
                                    uploadUnlinkedComplement(uri, plate)
                                },
                            )
                        }
                        AppState.Profile -> {
                            ProfileScreen(
                                userEmail = userEmail,
                                userRole = userRole,
                                onBack = { appState = AppState.Home },
                                onLogout = ::logout,
                            )
                        }
                        AppState.WorkspacePermissions -> {
                            WorkspacePermissionsScreen(
                                profiles = sharedProfiles,
                                busy = busy,
                                message = message,
                                ownerEmail = userEmail,
                                onBack = { appState = AppState.Home },
                                onRefresh = ::openSharedPermissions,
                                onSave = ::saveSharedProfile,
                            )
                        }
                        AppState.WorkspaceInbox -> {
                            WorkspaceInboxScreen(
                                messages = sharedMessages,
                                busy = busy,
                                message = message,
                                canManageMessages = userRole in setOf(
                                    "Administrador",
                                    "Super Administrador",
                                ),
                                onBack = { appState = AppState.Home },
                                onRefresh = ::openSharedInbox,
                                onSend = ::sendSharedMessage,
                                onMarkRead = ::markSharedMessageRead,
                            )
                        }
                    }
                }
            }
        }
    }

    private fun signIn() {
        if (!BuildConfig.GOOGLE_WEB_CLIENT_ID.endsWith(".apps.googleusercontent.com")) {
            message = "Configura el ID real del cliente OAuth web de Google."
            return
        }
        val apiUri = Uri.parse(BuildConfig.API_BASE_URL)
        val apiHost = apiUri.host
        if (apiHost.isNullOrBlank() || apiHost.endsWith(".invalid")) {
            message = "Configura la URL real de la API."
            return
        }
        val localDebugHttp = BuildConfig.DEBUG &&
            apiUri.scheme == "http" &&
            apiHost in setOf("10.0.2.2", "10.0.3.2", "127.0.0.1", "localhost")
        if (apiUri.scheme != "https" && !localDebugHttp) {
            message = "La API debe usar HTTPS. HTTP solo se permite en un emulador local de depuración."
            return
        }

        lifecycleScope.launch {
            busy = true
            message = "Activando el servidor y esperando autenticación de Google..."
            try {
                wakeApiServer()
                val token = obtainGoogleIdToken()
                val result = validateTokenWithServer(token)
                authToken = token
                val currentUser = JSONObject(result)
                userEmail = currentUser.optString("email", "")
                userRole = currentUser.optString("role", "")
                downloadAllowed = currentUser.optBoolean("download_allowed")
                downloadRequested = currentUser.optBoolean("download_requested")
                appState = AppState.Home
                try {
                    message = "Sesión verificada. Cargando expedientes..."
                    cases = fetchCasesFromServer()
                    message = "Listo. ${cases.size} expedientes encontrados."
                } catch (error: Exception) {
                    cases = emptyList()
                    message = "Sesión verificada, pero no se pudieron cargar expedientes: " +
                        (error.message ?: "error desconocido.")
                }
            } catch (error: Exception) {
                authToken = ""
                userEmail = ""
                cases = emptyList()
                message = if (error is NoCredentialException) {
                    "Google no encontró una cuenta disponible para esta app. Comprueba que " +
                        "la cuenta esté añadida al dispositivo, tenga un perfil aprobado y " +
                        "esté en usuarios de prueba si el consentimiento Google está en modo de prueba."
                } else if (error is GetCredentialCancellationException) {
                    "Se canceló el inicio de sesión. Puedes intentarlo de nuevo."
                } else if (error is SecurityException) {
                    "Google rechazó esta instalación. Verifica que el paquete y la huella " +
                        "SHA-1 del APK estén registrados en el proyecto OAuth de Android."
                } else if (error is IOException) {
                    error.message?.takeIf(String::isNotBlank)
                        ?: "No se pudo conectar con el servidor. Comprueba la API y la red."
                } else {
                    "Google no completó el inicio de sesión (${error.javaClass.simpleName}). " +
                        "Comprueba la cuenta autorizada, la conexión y vuelve a intentarlo."
                }
            } finally {
                busy = false
            }
        }
    }

    private suspend fun wakeApiServer() = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("${BuildConfig.API_BASE_URL.trimEnd('/')}/health")
            .get()
            .build()
        var lastError: IOException? = null

        repeat(3) { attempt ->
            try {
                apiWakeClient.newCall(request).execute().use { response ->
                    if (response.isSuccessful) return@withContext
                    if (response.code !in setOf(502, 503, 504)) {
                        throw IllegalStateException(
                            "El servidor respondió con un error (${response.code}).",
                        )
                    }
                    lastError = IOException("El servidor está iniciando (${response.code}).")
                }
            } catch (error: IOException) {
                lastError = error
            }
            if (attempt < 2) delay(1500L * (attempt + 1))
        }

        throw IOException(
            "No se pudo activar el servidor. Inténtalo de nuevo en un momento.",
            lastError,
        )
    }

    private suspend fun obtainGoogleIdToken(): String {
        val googleIdOption = GetGoogleIdOption.Builder()
            .setServerClientId(BuildConfig.GOOGLE_WEB_CLIENT_ID)
            .setFilterByAuthorizedAccounts(false)
            .setAutoSelectEnabled(false)
            .build()
        val request = GetCredentialRequest.Builder()
            .addCredentialOption(googleIdOption)
            .build()
        val credential = CredentialManager.create(this)
            .getCredential(request = request, context = this)
            .credential
        val googleCredential = credential as? CustomCredential
            ?: throw IOException("Google no devolvió una credencial compatible.")
        if (googleCredential.type != GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) {
            throw IOException("Google no devolvió un ID token válido.")
        }
        return try {
            GoogleIdTokenCredential.createFrom(googleCredential.data).idToken
        } catch (error: Exception) {
            throw IOException("No se pudo leer la credencial de Google.", error)
        }
    }

    private suspend fun validateTokenWithServer(idToken: String): String =
        withContext(Dispatchers.IO) {
            val request = Request.Builder()
                .url("${BuildConfig.API_BASE_URL.trimEnd('/')}/api/v1/me")
                .header("Authorization", "Bearer $idToken")
                .get()
                .build()
            apiRequestClient.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    val detail = runCatching {
                        JSONObject(body).optString("detail")
                    }.getOrDefault("")
                    throw IOException(
                        detail.ifBlank {
                            "El servidor rechazó la sesión (${response.code})."
                        }
                    )
                }
                body
            }
        }

    private suspend fun fetchCasesFromServer(): List<Expediente> =
        withContext(Dispatchers.IO) {
            val request = Request.Builder()
                .url("${BuildConfig.API_BASE_URL.trimEnd('/')}/api/v1/expedientes")
                .header("Authorization", "Bearer $authToken")
                .get()
                .build()
            apiRequestClient.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    val body = response.body?.string().orEmpty()
                    val detail = runCatching {
                        JSONObject(body).optString("detail")
                    }.getOrDefault("")
                    throw IOException(
                        detail.ifBlank {
                            "No se pudieron cargar los expedientes (${response.code})."
                        }
                    )
                }
                val body = response.body?.string().orEmpty()
                val json = JSONObject(body)
                val expedientesArray = json.optJSONArray("expedientes") ?: JSONArray()
                val result = mutableListOf<Expediente>()
                for (i in 0 until expedientesArray.length()) {
                    val obj = expedientesArray.getJSONObject(i)
                    result.add(
                        Expediente(
                            radicado_padre = obj.optString("radicado_padre", ""),
                            placa = obj.optString("placa", ""),
                            fecha_solicitud = obj.optString("fecha_solicitud", ""),
                            propietario = obj.optString("propietario", ""),
                            cedula_propietario = obj.optString("cedula_propietario", ""),
                            empresa = obj.optString("empresa", ""),
                            nit_empresa = obj.optString("nit_empresa", ""),
                            caso = obj.optString("caso", ""),
                        )
                    )
                }
                result
            }
        }

    private suspend fun workspaceRequest(
        method: String,
        path: String,
        payload: JSONObject? = null,
    ): JSONObject = withContext(Dispatchers.IO) {
        val requestBuilder = Request.Builder()
            .url("${BuildConfig.API_BASE_URL.trimEnd('/')}$path")
            .header("Authorization", "******")
        when (method) {
            "GET" -> requestBuilder.get()
            "POST" -> requestBuilder.post(
                (payload ?: JSONObject()).toString()
                    .toRequestBody("application/json; charset=utf-8".toMediaType()),
            )
            "PATCH" -> requestBuilder.patch(
                (payload ?: JSONObject()).toString()
                    .toRequestBody("application/json; charset=utf-8".toMediaType()),
            )
            else -> throw IllegalArgumentException("Método no admitido.")
        }
        apiRequestClient.newCall(requestBuilder.build()).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw IOException(apiError(body, response.code))
            }
            if (body.isBlank()) JSONObject() else JSONObject(body)
        }
    }

    private suspend fun loadSharedProfiles() {
        val result = workspaceRequest("GET", "/api/v1/workspace/profiles")
        val profiles = result.optJSONArray("perfiles") ?: JSONArray()
        sharedProfiles = (0 until profiles.length()).map { index ->
            val profile = profiles.getJSONObject(index)
            WorkspaceProfile(
                email = profile.optString("email"),
                fullName = profile.optString("full_name"),
                role = profile.optString("role", "Sin Rol Asignado"),
                status = profile.optString("status", "Pendiente"),
                downloadAllowed = profile.optBoolean("download_allowed"),
                downloadRequested = profile.optBoolean("download_requested"),
            )
        }
    }

    private suspend fun loadSharedMessages() {
        val result = workspaceRequest("GET", "/api/v1/workspace/messages")
        val messages = result.optJSONArray("mensajes") ?: JSONArray()
        sharedMessages = (0 until messages.length()).map { index ->
            val item = messages.getJSONObject(index)
            WorkspaceMessage(
                id = item.optString("id"),
                senderEmail = item.optString("sender_email"),
                subject = item.optString("subject", "Soporte"),
                message = item.optString("message"),
                createdAt = item.optString("created_at"),
                readAt = item.optString("read_at"),
            )
        }
    }

    private fun openSharedPermissions() {
        appState = AppState.WorkspacePermissions
        lifecycleScope.launch {
            busy = true
            message = "Cargando permisos compartidos..."
            try {
                loadSharedProfiles()
                message = "${sharedProfiles.size} perfiles cargados desde el espacio compartido."
            } catch (error: Exception) {
                message = error.message ?: "No se pudieron cargar los permisos."
            } finally {
                busy = false
            }
        }
    }

    private fun saveSharedProfile(profile: WorkspaceProfile) {
        lifecycleScope.launch {
            busy = true
            message = "Guardando permisos compartidos..."
            try {
                val payload = JSONObject()
                    .put("email", profile.email)
                    .put("role", profile.role)
                    .put("status", profile.status)
                    .put("download_allowed", profile.downloadAllowed)
                workspaceRequest("PATCH", "/api/v1/workspace/profiles", payload)
                loadSharedProfiles()
                message = "Permisos guardados para ${profile.email}."
            } catch (error: Exception) {
                message = error.message ?: "No se pudieron guardar los permisos."
            } finally {
                busy = false
            }
        }
    }

    private fun requestDownloadPermission() {
        lifecycleScope.launch {
            busy = true
            message = "Enviando solicitud de descarga..."
            try {
                workspaceRequest(
                    "POST",
                    "/api/v1/workspace/profiles/me/download-request",
                )
                downloadRequested = true
                message = "Solicitud enviada al administrador."
            } catch (error: Exception) {
                message = error.message ?: "No se pudo solicitar el permiso."
            } finally {
                busy = false
            }
        }
    }

    private fun openSharedInbox() {
        appState = AppState.WorkspaceInbox
        lifecycleScope.launch {
            busy = true
            message = "Cargando el buzón compartido..."
            try {
                loadSharedMessages()
                message = "${sharedMessages.size} mensajes cargados desde el espacio compartido."
            } catch (error: Exception) {
                message = error.message ?: "No se pudo cargar el buzón."
            } finally {
                busy = false
            }
        }
    }

    private fun sendSharedMessage(subject: String, text: String) {
        lifecycleScope.launch {
            busy = true
            message = "Enviando mensaje..."
            try {
                workspaceRequest(
                    "POST",
                    "/api/v1/workspace/messages",
                    JSONObject().put("subject", subject).put("message", text),
                )
                loadSharedMessages()
                message = "Mensaje guardado en el buzón compartido."
            } catch (error: Exception) {
                message = error.message ?: "No se pudo enviar el mensaje."
            } finally {
                busy = false
            }
        }
    }

    private fun markSharedMessageRead(messageId: String) {
        lifecycleScope.launch {
            busy = true
            try {
                workspaceRequest(
                    "PATCH",
                    "/api/v1/workspace/messages/${Uri.encode(messageId)}/read",
                )
                loadSharedMessages()
                message = "Estado del mensaje actualizado."
            } catch (error: Exception) {
                message = error.message ?: "No se pudo actualizar el mensaje."
            } finally {
                busy = false
            }
        }
    }

    private fun refreshCases() {
        lifecycleScope.launch {
            busy = true
            try {
                val currentUser = JSONObject(validateTokenWithServer(authToken))
                userRole = currentUser.optString("role", "")
                downloadAllowed = currentUser.optBoolean("download_allowed")
                downloadRequested = currentUser.optBoolean("download_requested")
                cases = fetchCasesFromServer()
                message = "Permisos y expedientes actualizados desde el servidor."
            } catch (error: Exception) {
                message = error.message ?: "No se pudieron actualizar los expedientes."
            } finally {
                busy = false
            }
        }
    }

    private fun selectCase(radicado: String) {
        lifecycleScope.launch {
            busy = true
            try {
                val caseDetail = fetchCaseDetails(radicado)
                selectedCaseData = JSONObject(caseDetail).optJSONObject("expediente")
                selectedDocuments = emptyList()
                uploadSummary = ""
                appState = AppState.CaseDetail
                message = ""
                try {
                    loadChecklist(radicado)
                } catch (error: Exception) {
                    uploadSummary = error.message ?: "No se pudo consultar Google Drive."
                }
            } catch (error: Exception) {
                message = error.message ?: "No se pudo abrir el expediente."
            } finally {
                busy = false
            }
        }
    }

    private suspend fun fetchCaseDetails(radicado: String): String =
        withContext(Dispatchers.IO) {
            val request = Request.Builder()
                .url("${BuildConfig.API_BASE_URL.trimEnd('/')}/api/v1/expedientes/$radicado")
                .header("Authorization", "Bearer $authToken")
                .get()
                .build()
            apiRequestClient.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    throw IOException("No se encontró el expediente (${response.code}).")
                }
                response.body?.string().orEmpty()
            }
        }

    private fun createCase(
        radicado: String,
        placa: String,
        fecha: String,
        documentoPrincipal: Uri,
    ) {
        lifecycleScope.launch {
            busy = true
            message = ""
            var saved = false
            try {
                val body = JSONObject()
                    .put("radicado_padre", radicado.trim())
                    .put("placa", placa.trim().uppercase())
                    .put("fecha_solicitud", fecha.trim())
                withContext(Dispatchers.IO) {
                    val request = Request.Builder()
                        .url("${BuildConfig.API_BASE_URL.trimEnd('/')}/api/v1/expedientes")
                        .header("Authorization", "Bearer $authToken")
                        .post(body.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
                        .build()
                    apiRequestClient.newCall(request).execute().use { response ->
                        val responseBody = response.body?.string().orEmpty()
                        if (!response.isSuccessful) {
                            throw IOException(apiError(responseBody, response.code))
                        }
                    }
                }
                saved = true
                selectedCaseData = JSONObject()
                    .put("radicado_padre", radicado.trim())
                    .put("placa", placa.trim().uppercase())
                    .put("fecha_solicitud", fecha.trim())
                appState = AppState.CaseDetail
                uploadSummary = "Expediente guardado. Preparando el documento principal..."
                try {
                    cases = fetchCasesFromServer()
                } catch (error: IOException) {
                    message = "Expediente guardado; no se pudo actualizar la lista: " +
                        (error.message ?: "error de conexión.")
                }
            } catch (error: Exception) {
                message = error.message ?: "No se pudo guardar el expediente."
            } finally {
                busy = false
            }
            if (saved) {
                uploadPdf(documentoPrincipal, radicado.trim(), null)
            }
        }
    }

    private fun updateCase(values: Map<String, String>) {
        val currentCase = selectedCaseData
        val radicado = currentCase?.optString("radicado_padre").orEmpty()
        if (currentCase == null || radicado.isBlank()) {
            message = "Abre un expediente antes de guardar cambios."
            return
        }

        val fechaSolicitud = try {
            normalizarFechaSolicitud(values["fecha_solicitud"].orEmpty())
        } catch (error: DateTimeParseException) {
            message = "La fecha de solicitud debe usar AAAA-MM-DD o DD/MM/AAAA."
            return
        }
        val placa = values["placa"].orEmpty().trim().uppercase()
        if (placa.isBlank()) {
            message = "La placa es obligatoria."
            return
        }

        val payload = JSONObject()
            .put("radicado_padre", radicado)
            .put("fecha_solicitud", fechaSolicitud)
            .put("placa", placa)
        for ((key, value) in values) {
            if (key == "fecha_solicitud" || key == "placa") continue
            val originalValue = currentCase.optString(key).trim()
            val original = if (key == "qx_verificado") {
                when (originalValue.uppercase()) {
                    "SI", "SÍ", "TRUE", "1" -> "Sí"
                    "NO", "FALSE", "0" -> "No"
                    else -> ""
                }
            } else {
                originalValue
            }
            val updated = value.trim()
            if (updated != original) payload.put(key, updated)
        }

        lifecycleScope.launch {
            busy = true
            message = ""
            try {
                withContext(Dispatchers.IO) {
                    val request = Request.Builder()
                        .url(
                            "${BuildConfig.API_BASE_URL.trimEnd('/')}/api/v1/expedientes/" +
                                Uri.encode(radicado),
                        )
                        .header("Authorization", "******")
                        .put(
                            payload.toString().toRequestBody(
                                "application/json; charset=utf-8".toMediaType(),
                            ),
                        )
                        .build()
                    apiRequestClient.newCall(request).execute().use { response ->
                        val responseBody = response.body?.string().orEmpty()
                        if (!response.isSuccessful) {
                            throw IOException(apiError(responseBody, response.code))
                        }
                    }
                }
                selectedCaseData = JSONObject(fetchCaseDetails(radicado))
                    .optJSONObject("expediente")
                appState = AppState.CaseDetail
                message = try {
                    cases = fetchCasesFromServer()
                    "Cambios guardados en Google Sheets."
                } catch (error: Exception) {
                    "Cambios guardados; no se pudo actualizar la lista: " +
                        (error.message ?: "error de conexión.")
                }
            } catch (error: Exception) {
                message = error.message ?: "No se pudieron guardar los cambios."
            } finally {
                busy = false
            }
        }
    }

    private fun uploadCasePdf(uri: Uri) {
        val radicado = selectedCaseData?.optString("radicado_padre").orEmpty()
        if (radicado.isBlank()) {
            uploadSummary = "Abre un expediente antes de cargar documentos."
            return
        }
        uploadPdf(uri, radicado, null)
    }

    private fun uploadUnlinkedComplement(uri: Uri, plate: String) {
        if (plate.isBlank()) {
            message = "La placa es obligatoria para guardar un complemento pendiente."
            return
        }
        uploadPdf(uri, "PENDIENTE", plate.trim().uppercase())
    }

    private fun uploadPdf(uri: Uri, radicado: String, unlinkedPlate: String?) {
        lifecycleScope.launch {
            busy = true
            uploadSummary = "Leyendo y organizando el documento..."
            if (unlinkedPlate != null) {
                message = "Guardando complemento pendiente para la placa $unlinkedPlate..."
            }
            try {
                val acceptedJob = withContext(Dispatchers.IO) {
                    val filename = displayName(uri).ifBlank { "documento" }
                    val contentType = documentContentType(uri, filename)
                    val bytes = readDocument(uri)
                    val requestBody = MultipartBody.Builder()
                        .setType(MultipartBody.FORM)
                        .addFormDataPart(
                            "archivo",
                            filename,
                            bytes.toRequestBody(contentType.toMediaType()),
                        )
                        .addFormDataPart("tipo_documento", "Otro")
                        .addFormDataPart("placa_complemento", unlinkedPlate.orEmpty())
                        .addFormDataPart("complemento_sin_vincular", (unlinkedPlate != null).toString())
                        .build()
                    val request = Request.Builder()
                        .url(
                            "${BuildConfig.API_BASE_URL.trimEnd('/')}/api/v1/expedientes/" +
                                "${Uri.encode(radicado)}/upload-pdf/jobs"
                        )
                        .header("Authorization", "Bearer $authToken")
                        .post(requestBody)
                        .build()
                    apiRequestClient.newCall(request).execute().use { response ->
                        val body = response.body?.string().orEmpty()
                        if (!response.isSuccessful) {
                            throw IOException(apiError(body, response.code))
                        }
                        JSONObject(body)
                    }
                }
                val result = awaitUploadJob(acceptedJob)
                val blocks = result.optJSONArray("bloques") ?: JSONArray()
                uploadSummary = "Documento procesado: ${result.optInt("paginas")} páginas, " +
                    "${blocks.length()} bloques; OCR en ${result.optInt("paginas_ocr")} páginas."
                val suggestedClassification = result.optString("clasificacion_sugerida")
                val finalClassification = result.optString("clasificacion_final")
                if (suggestedClassification.isNotBlank()) {
                    uploadSummary += " Clasificación detectada: $suggestedClassification."
                } else {
                    uploadSummary += " El OCR no encontró evidencia suficiente para " +
                        "determinar la clasificación; requiere revisión."
                }
                if (finalClassification.isNotBlank()) {
                    uploadSummary += " Clasificación final registrada: $finalClassification."
                }
                val savedOcrFields = result.optJSONArray("campos_ocr_guardados") ?: JSONArray()
                if (savedOcrFields.length() > 0) {
                    uploadSummary += " Campos completados automáticamente: " +
                        "${savedOcrFields.length()}."
                }
                val pendingOcrFields = result.optJSONArray("campos_ocr_pendientes") ?: JSONArray()
                if (pendingOcrFields.length() > 0) {
                    val pendingNames = (0 until pendingOcrFields.length())
                        .joinToString { pendingOcrFields.optString(it) }
                    uploadSummary += " Campos OCR pendientes de guardar: $pendingNames."
                }
                val warning = result.optString("advertencia")
                if (warning.isNotBlank()) {
                    uploadSummary += " $warning"
                }
                if (unlinkedPlate == null) {
                    try {
                        loadChecklist(radicado)
                        selectedCaseData = JSONObject(fetchCaseDetails(radicado))
                            .optJSONObject("expediente")
                    } catch (error: Exception) {
                        uploadSummary += " No se pudo actualizar la vista del expediente: " +
                            (error.message ?: "error de consulta.")
                    }
                } else {
                    uploadSummary += " Se guardó temporalmente en Pendientes/Por_vincular/$unlinkedPlate."
                    message = uploadSummary
                }
            } catch (error: Exception) {
                uploadSummary = error.message ?: "No se pudo procesar el PDF."
                if (unlinkedPlate != null) {
                    message = uploadSummary
                }
            } finally {
                busy = false
            }
        }
    }

    private suspend fun awaitUploadJob(accepted: JSONObject): JSONObject {
        val jobId = accepted.optString("job_id")
        if (jobId.isBlank()) return accepted
        val deadline = System.currentTimeMillis() + TimeUnit.MINUTES.toMillis(20)
        while (System.currentTimeMillis() < deadline) {
            delay(1500)
            val status = withContext(Dispatchers.IO) {
                val request = Request.Builder()
                    .url(
                        "${BuildConfig.API_BASE_URL.trimEnd('/')}/api/v1/expedientes/" +
                            "upload-jobs/${Uri.encode(jobId)}"
                    )
                    .header("Authorization", "******")
                    .get()
                    .build()
                apiRequestClient.newCall(request).execute().use { response ->
                    val body = response.body?.string().orEmpty()
                    if (!response.isSuccessful) {
                        throw IOException(apiError(body, response.code))
                    }
                    JSONObject(body)
                }
            }
            when (status.optString("estado")) {
                "completado" -> {
                    return status.optJSONObject("resultado")
                        ?: throw IOException("El trabajo terminó sin devolver resultados.")
                }
                "error" -> throw IOException(
                    status.optString("error").ifBlank {
                        "No se pudo procesar el documento."
                    },
                )
                else -> {
                    val progress = status.optJSONObject("progreso")
                    val processedPages = progress?.optInt("paginas_procesadas") ?: 0
                    val totalPages = progress?.optInt("paginas_totales") ?: 0
                    uploadSummary = if (totalPages > 0) {
                        "OCR y separación documental: $processedPages de " +
                            "$totalPages páginas procesadas..."
                    } else {
                        "El servidor está preparando el documento para OCR y separación..."
                    }
                }
            }
        }
        throw IOException(
            "El procesamiento superó los 20 minutos. Consulta el estado del expediente antes de volver a cargar.",
        )
    }

    private fun refreshChecklist() {
        val radicado = selectedCaseData?.optString("radicado_padre").orEmpty()
        if (radicado.isBlank()) return
        lifecycleScope.launch {
            busy = true
            try {
                loadChecklist(radicado)
                uploadSummary = "Lista documental actualizada desde Drive."
            } catch (error: Exception) {
                uploadSummary = error.message ?: "No se pudo consultar Google Drive."
            } finally {
                busy = false
            }
        }
    }

    private suspend fun loadChecklist(radicado: String) {
        val responseBody = withContext(Dispatchers.IO) {
            val request = Request.Builder()
                .url(
                    "${BuildConfig.API_BASE_URL.trimEnd('/')}/api/v1/expedientes/" +
                        "${Uri.encode(radicado)}/checklist"
                )
                .header("Authorization", "Bearer $authToken")
                .get()
                .build()
            apiRequestClient.newCall(request).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    throw IOException(apiError(body, response.code))
                }
                body
            }
        }
        val documents = JSONObject(responseBody).optJSONArray("documentos") ?: JSONArray()
        selectedDocuments = (0 until documents.length()).map { index ->
            val item = documents.getJSONObject(index)
            DocumentoDrive(
                nombre = item.optString("nombre"),
                tipo = item.optString("tipo_documento"),
                url = item.optString("url"),
                archivoOrigen = item.optString("archivo_origen"),
                paginasOrigen = item.optString("paginas_origen"),
            )
        }
        val pending = JSONObject(responseBody).optJSONArray("complementos_pendientes") ?: JSONArray()
        pendingComplements = (0 until pending.length()).map { index ->
            val item = pending.getJSONObject(index)
            val files = item.optJSONArray("archivos") ?: JSONArray()
            ComplementoPendiente(
                id = item.optString("id"),
                nombre = item.optString("nombre"),
                archivos = (0 until files.length()).map { fileIndex ->
                    val file = files.getJSONObject(fileIndex)
                    "${file.optString("tipo_documento")}: ${file.optString("nombre")}"
                },
            )
        }.filter { it.id.isNotBlank() && it.archivos.isNotEmpty() }
    }

    private fun linkPendingComplement(batchId: String) {
        val radicado = selectedCaseData?.optString("radicado_padre").orEmpty()
        if (radicado.isBlank()) return
        lifecycleScope.launch {
            busy = true
            uploadSummary = "Vinculando complemento al expediente..."
            try {
                val responseBody = withContext(Dispatchers.IO) {
                    val payload = JSONObject().put("lote_pendiente", batchId)
                    val request = Request.Builder()
                        .url(
                            "${BuildConfig.API_BASE_URL.trimEnd('/')}/api/v1/expedientes/" +
                                "${Uri.encode(radicado)}/vincular-complemento"
                        )
                        .header("Authorization", "Bearer $authToken")
                        .post(payload.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
                        .build()
                    apiRequestClient.newCall(request).execute().use { response ->
                        val body = response.body?.string().orEmpty()
                        if (!response.isSuccessful) {
                            throw IOException(apiError(body, response.code))
                        }
                        body
                    }
                }
                val result = JSONObject(responseBody)
                val moved = result.optInt("archivos_vinculados")
                loadChecklist(radicado)
                uploadSummary = "Complemento vinculado: $moved archivos. El PDF completo y " +
                    "sus documentos quedaron en la carpeta anual del expediente."
                val classification = result.optString("clasificacion_final")
                if (classification.isNotBlank()) {
                    uploadSummary += " Clasificación final: $classification."
                }
                val warning = result.optString("advertencia")
                if (warning.isNotBlank()) uploadSummary += " $warning"
            } catch (error: Exception) {
                uploadSummary = error.message ?: "No se pudo vincular el complemento."
            } finally {
                busy = false
            }
        }
    }

    private fun readDocument(uri: Uri): ByteArray {
        val output = ByteArrayOutputStream()
        val input = contentResolver.openInputStream(uri)
            ?: throw IOException("No se pudo abrir el archivo seleccionado.")
        input.use { stream ->
            val buffer = ByteArray(8192)
            var total = 0
            while (true) {
                val count = stream.read(buffer)
                if (count < 0) break
                total += count
                if (total > 50 * 1024 * 1024) {
                    throw IOException("El documento supera el tamaño máximo de 50 MB.")
                }
                output.write(buffer, 0, count)
            }
        }
        return output.toByteArray()
    }

    private fun documentContentType(uri: Uri, filename: String): String {
        val mimeType = contentResolver.getType(uri)?.substringBefore(';')?.lowercase()
        val candidate = mimeType ?: when (filename.substringAfterLast('.', "").lowercase()) {
            "pdf" -> "application/pdf"
            "png" -> "image/png"
            "jpg", "jpeg" -> "image/jpeg"
            else -> ""
        }
        return when (candidate) {
            "application/pdf" -> "application/pdf"
            "image/png" -> "image/png"
            "image/jpeg", "image/jpg", "image/pjpeg" -> "image/jpeg"
            else -> throw IOException("Seleccione un archivo PDF, PNG o JPG.")
        }
    }

    private fun displayName(uri: Uri): String {
        val cursor: Cursor? = contentResolver.query(
            uri,
            arrayOf(OpenableColumns.DISPLAY_NAME),
            null,
            null,
            null,
        )
        return cursor?.use {
            if (it.moveToFirst()) it.getString(0).orEmpty() else ""
        }.orEmpty()
    }

    private fun apiError(body: String, statusCode: Int): String {
        val detail = runCatching { JSONObject(body).optString("detail") }.getOrDefault("")
        return detail.ifBlank { "La API rechazó la solicitud ($statusCode)." }
    }

    private fun logout() {
        authToken = ""
        userEmail = ""
        userRole = ""
        downloadAllowed = false
        downloadRequested = false
        cases = emptyList()
        selectedCaseData = null
        selectedDocuments = emptyList()
        pendingComplements = emptyList()
        sharedProfiles = emptyList()
        sharedMessages = emptyList()
        uploadSummary = ""
        message = ""
        appState = AppState.Login
    }

    private fun openExternalUrl(url: String, service: String) {
        try {
            CustomTabsIntent.Builder()
                .setShowTitle(true)
                .build()
                .launchUrl(this, Uri.parse(url))
        } catch (_: ActivityNotFoundException) {
            try {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            } catch (_: ActivityNotFoundException) {
                message = "No hay una aplicación o navegador disponible para abrir $service."
            }
        }
    }
}

@Composable
private fun LoginScreen(
    message: String,
    busy: Boolean,
    onSignIn: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 28.dp)
            .navigationBarsPadding()
            .statusBarsPadding(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        BrandMark()
        Spacer(Modifier.height(24.dp))
        Text("ALCALDÍA DE SANTIAGO DE CALI", style = MaterialTheme.typography.labelLarge, color = Cyan)
        Text(
            "SECRETARÍA DE TRÁNSITO Y TRANSPORTE",
            style = MaterialTheme.typography.labelMedium,
            color = Muted,
        )
        Spacer(Modifier.height(14.dp))
        Text(
            "Sistema de desvinculaciones",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
        )
        Text(
            "Consulta y seguimiento de expedientes",
            modifier = Modifier.padding(top = 8.dp),
            style = MaterialTheme.typography.bodyMedium,
            color = Muted,
        )
        Spacer(Modifier.height(28.dp))
        if (busy) {
            CircularProgressIndicator()
        } else {
            Button(
                onClick = onSignIn,
                modifier = Modifier.fillMaxWidth().heightIn(min = 54.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = Color.White,
                    contentColor = Color(0xFF202124),
                ),
            ) {
                Text("G", color = Color(0xFF4285F4), fontWeight = FontWeight.Bold)
                Spacer(Modifier.width(12.dp))
                Text("Continuar con Google", fontWeight = FontWeight.SemiBold)
            }
        }
        if (message.isNotBlank()) {
            StatusBanner(message, isError = !busy)
        }
        Spacer(Modifier.height(18.dp))
        Text(
            "Acceso protegido para pruebas. Inicia sesión con la cuenta Google autorizada.",
            style = MaterialTheme.typography.bodySmall,
            color = Muted,
        )
    }
}

@Composable
private fun BrandMark() {
    Surface(
        modifier = Modifier.size(104.dp),
        shape = MaterialTheme.shapes.extraLarge,
        color = PanelRaised,
    ) {
        Image(
            painter = painterResource(R.drawable.logo_app),
            contentDescription = "Icono de Desvinculaciones Cali",
            modifier = Modifier.padding(8.dp),
            contentScale = ContentScale.Fit,
        )
    }
}

@Composable
private fun StatusBanner(message: String, isError: Boolean) {
    Surface(
        modifier = Modifier.fillMaxWidth().padding(top = 16.dp),
        shape = MaterialTheme.shapes.medium,
        color = if (isError) Color(0xFF3B202A) else PanelRaised,
    ) {
        Text(
            message,
            modifier = Modifier.padding(14.dp),
            style = MaterialTheme.typography.bodySmall,
            color = if (isError) MaterialTheme.colorScheme.error else Muted,
        )
    }
}

@Composable
private fun NewCaseScreen(
    busy: Boolean,
    message: String,
    onBack: () -> Unit,
    onCreate: (radicado: String, placa: String, fecha: String, documentoPrincipal: Uri) -> Unit,
    onUploadComplement: (placa: String, uri: Uri) -> Unit,
) {
    var radicado by remember { mutableStateOf("") }
    var placa by remember { mutableStateOf("") }
    var fecha by remember { mutableStateOf("") }
    var documentoPrincipal by remember { mutableStateOf<Uri?>(null) }
    val primaryDocumentPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri != null) documentoPrincipal = uri
    }
    val complementPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri != null) onUploadComplement(placa, uri)
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 20.dp, vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.Default.ArrowBack, contentDescription = "Volver")
            }
            Text("Registrar expediente", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        }
        Text(
            "Los datos se guardan en la hoja operacional conectada.",
            modifier = Modifier.padding(bottom = 16.dp),
            color = Muted,
            style = MaterialTheme.typography.bodySmall,
        )
        Text(
            "Petición principal (PDF o foto) · requerida",
            modifier = Modifier.padding(top = 8.dp, bottom = 6.dp),
            color = Muted,
            style = MaterialTheme.typography.bodySmall,
        )
        OutlinedButton(
            onClick = {
                primaryDocumentPicker.launch(
                    arrayOf("application/pdf", "image/png", "image/jpeg"),
                )
            },
            enabled = !busy,
            modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp),
        ) {
            Text(
                if (documentoPrincipal == null) {
                    "Seleccionar petición PDF o foto"
                } else {
                    "Petición seleccionada · cambiar archivo"
                },
            )
        }
        if (documentoPrincipal != null) {
            Text(
                "Se procesará con OCR al guardar el expediente.",
                modifier = Modifier.padding(top = 4.dp),
                color = Muted,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        OutlinedTextField(
            value = radicado,
            onValueChange = { radicado = it },
            label = { Text("Radicado padre") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = placa,
            onValueChange = { placa = it.uppercase() },
            label = { Text("Placa") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        )
        OutlinedTextField(
            value = fecha,
            onValueChange = { fecha = it },
            label = { Text("Fecha de solicitud (AAAA-MM-DD)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        )
        Text(
            "La clasificación final se completará con la evidencia documental procesada.",
            modifier = Modifier.padding(top = 12.dp),
            color = Muted,
            style = MaterialTheme.typography.bodySmall,
        )
        Button(
            onClick = {
                documentoPrincipal?.let { onCreate(radicado, placa, fecha, it) }
            },
            enabled = !busy && radicado.isNotBlank() && placa.isNotBlank() &&
                fecha.isNotBlank() && documentoPrincipal != null,
            modifier = Modifier.fillMaxWidth().padding(top = 14.dp).heightIn(min = 50.dp),
        ) {
            if (busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
            else Text("Guardar y procesar expediente")
        }
        if (message.isNotBlank()) {
            StatusBanner(message, isError = message.contains("no se", ignoreCase = true))
        }
        HorizontalDivider(Modifier.padding(vertical = 20.dp), color = DividerColor)
        Text(
            "Complemento sin expediente",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
        )
        Text(
            "Se conserva temporalmente en Pendientes/Por_vincular/PLACA.",
            modifier = Modifier.padding(top = 4.dp, bottom = 10.dp),
            color = Muted,
            style = MaterialTheme.typography.bodySmall,
        )
        OutlinedButton(
            onClick = {
                complementPicker.launch(
                    arrayOf("application/pdf", "image/png", "image/jpeg"),
                )
            },
            enabled = !busy && placa.isNotBlank(),
            modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp),
        ) {
            Text("Seleccionar complemento PDF o imagen")
        }
    }
}

@Composable
private fun HomeScreen(
    userEmail: String,
    userRole: String,
    canEditCases: Boolean,
    canManageProfiles: Boolean,
    downloadAllowed: Boolean,
    downloadRequested: Boolean,
    cases: List<Expediente>,
    message: String,
    busy: Boolean,
    onOpenCases: () -> Unit,
    onOpenHistorical: () -> Unit,
    onCreateCase: () -> Unit,
    onOpenProfile: () -> Unit,
    onOpenPermissions: () -> Unit,
    onOpenInbox: () -> Unit,
    onRequestDownload: () -> Unit,
    onOpenDrive: () -> Unit,
    onOpenSheets: () -> Unit,
    onRefresh: () -> Unit,
    onLogout: () -> Unit,
) {
    val casesWithAppeal = cases.count { it.caso.equals("Con recurso", ignoreCase = true) }
    val casesWithoutAppeal = cases.count { it.caso.equals("Sin recurso", ignoreCase = true) }
    val withdrawals = cases.count { it.caso.equals("Desistimiento", ignoreCase = true) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 12.dp),
    ) {
        AppHeader(userEmail = userEmail, onLogout = onLogout)
        Text(
            "Rol: $userRole",
            modifier = Modifier.padding(top = 6.dp),
            color = Cyan,
            style = MaterialTheme.typography.labelMedium,
        )
        if (userRole == "Visualizador" && !downloadAllowed) {
            OutlinedButton(
                onClick = onRequestDownload,
                enabled = !busy && !downloadRequested,
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            ) {
                Text(
                    if (downloadRequested) "Solicitud de descarga enviada"
                    else "Solicitar permiso de descarga",
                )
            }
        }
        Spacer(Modifier.height(12.dp))
        BrandMark()
        Text(
            "ALCALDÍA DE SANTIAGO DE CALI",
            modifier = Modifier.fillMaxWidth().padding(top = 14.dp),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
        )
        Text(
            "SECRETARÍA DE TRÁNSITO Y TRANSPORTE",
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
            style = MaterialTheme.typography.labelMedium,
            color = Cyan,
        )
        Text(
            "Sistema de desvinculaciones",
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
            style = MaterialTheme.typography.bodyMedium,
            color = Muted,
        )
        Spacer(Modifier.height(24.dp))
        Text("Aplicaciones del sistema", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text(
            "Accesos disponibles según las funciones conectadas en el móvil.",
            modifier = Modifier.padding(top = 4.dp, bottom = 10.dp),
            color = Muted,
            style = MaterialTheme.typography.bodySmall,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            AppTile(
                icon = "📄",
                title = "Registro de Entrada",
                description = if (canEditCases) {
                    "Crear expediente y cargar PDF con OCR."
                } else {
                    "Disponible para modificadores y administradores."
                },
                available = canEditCases,
                onClick = onCreateCase,
                modifier = Modifier.weight(1f),
            )
            AppTile(
                icon = "🔍",
                title = "Buscador y Archivo",
                description = "Consulta por radicado, placa, empresa o propietario.",
                available = true,
                onClick = onOpenCases,
                modifier = Modifier.weight(1f),
            )
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            AppTile(
                icon = "☁️",
                title = "Google Drive",
                description = "Abrir la carpeta documental del sistema.",
                available = true,
                onClick = onOpenDrive,
                modifier = Modifier.weight(1f),
            )
            AppTile(
                icon = "📊",
                title = "Google Sheets",
                description = "Abrir la hoja operacional del sistema.",
                available = true,
                onClick = onOpenSheets,
                modifier = Modifier.weight(1f),
            )
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            AppTile(
                icon = "🗂️",
                title = "Base Histórica",
                description = "Consulta de expedientes en la hoja compartida tabla_2.",
                available = true,
                onClick = onOpenHistorical,
                modifier = Modifier.weight(1f),
            )
            AppTile(
                icon = "🔐",
                title = "Gestión de Permisos",
                description = "Roles y solicitudes de descarga compartidos.",
                available = canManageProfiles,
                onClick = onOpenPermissions,
                modifier = Modifier.weight(1f),
            )
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            AppTile(
                icon = "🔔",
                title = "Buzón de Mensajes",
                description = "Consultas de soporte compartidas entre plataformas.",
                available = true,
                onClick = onOpenInbox,
                modifier = Modifier.weight(1f),
            )
            AppTile(
                icon = "👤",
                title = "Mi Perfil",
                description = "Cuenta Google autenticada en este dispositivo.",
                available = true,
                onClick = onOpenProfile,
                modifier = Modifier.weight(1f),
            )
        }
        Spacer(Modifier.height(24.dp))
        Text("Estado del archivo", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            MetricCard("Expedientes", cases.size.toString(), Modifier.weight(1f))
            MetricCard("Con recurso", casesWithAppeal.toString(), Modifier.weight(1f))
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            MetricCard("Sin recurso", casesWithoutAppeal.toString(), Modifier.weight(1f))
            MetricCard("Desistimientos", withdrawals.toString(), Modifier.weight(1f))
        }
        Spacer(Modifier.height(12.dp))
        OutlinedButton(
            onClick = onRefresh,
            enabled = !busy,
            modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp),
        ) {
            if (busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
            else Text("Actualizar información")
        }
        if (message.isNotBlank()) StatusBanner(message, isError = message.contains("no se", ignoreCase = true))
        Spacer(Modifier.height(8.dp))
        Text(
            "El registro, la consulta operacional y la carga documental con OCR " +
                "se conectan a la API local autorizada.",
            color = Muted,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun AppTile(
    icon: String,
    title: String,
    description: String,
    available: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit = {},
) {
    Surface(
        modifier = modifier
            .height(154.dp)
            .clickable(enabled = available, onClick = onClick),
        shape = MaterialTheme.shapes.large,
        color = if (available) PanelRaised else Panel,
        tonalElevation = if (available) 2.dp else 0.dp,
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(icon, style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.width(8.dp))
                Text(
                    if (available) "ABRIR" else "NO DISPONIBLE",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (available) Cyan else Muted,
                    fontWeight = FontWeight.Bold,
                )
            }
            Text(
                title,
                modifier = Modifier.padding(top = 8.dp),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
            )
            Text(
                description,
                modifier = Modifier.padding(top = 4.dp),
                style = MaterialTheme.typography.bodySmall,
                color = Muted,
            )
        }
    }
}

@Composable
private fun ProfileScreen(
    userEmail: String,
    userRole: String,
    onBack: () -> Unit,
    onLogout: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 20.dp, vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.Default.ArrowBack, contentDescription = "Volver al inicio")
            }
            Text("Mi Perfil", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        }
        Card(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
            colors = CardDefaults.cardColors(containerColor = Panel),
        ) {
            Column(Modifier.padding(18.dp)) {
                Text("Cuenta Google", style = MaterialTheme.typography.labelMedium, color = Muted)
                Text(
                    userEmail,
                    modifier = Modifier.padding(top = 6.dp),
                    style = MaterialTheme.typography.titleMedium,
                )
                Text(
                    "Rol: $userRole",
                    modifier = Modifier.padding(top = 6.dp),
                    style = MaterialTheme.typography.bodyMedium,
                )
                Text(
                    "Sesión autenticada por el servidor.",
                    modifier = Modifier.padding(top = 10.dp),
                    style = MaterialTheme.typography.bodySmall,
                    color = Cyan,
                )
            }
        }
        Text(
            "Gestión de permisos y buzón compartidos disponibles desde el menú principal.",
            modifier = Modifier.padding(top = 14.dp),
            style = MaterialTheme.typography.bodySmall,
            color = Muted,
        )
        OutlinedButton(
            onClick = onLogout,
            modifier = Modifier.fillMaxWidth().padding(top = 20.dp).heightIn(min = 50.dp),
        ) {
            Icon(Icons.Default.ExitToApp, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("Cerrar sesión")
        }
    }
}

@Composable
private fun WorkspacePermissionsScreen(
    profiles: List<WorkspaceProfile>,
    busy: Boolean,
    message: String,
    ownerEmail: String,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    onSave: (WorkspaceProfile) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 20.dp, vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.Default.ArrowBack, contentDescription = "Volver al inicio")
            }
            Text(
                "Gestión de permisos",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
            )
        }
        Text(
            "Cambios guardados en el espacio compartido por escritorio, web y móvil.",
            color = Muted,
            style = MaterialTheme.typography.bodySmall,
        )
        OutlinedButton(
            onClick = onRefresh,
            enabled = !busy,
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        ) {
            Text("Actualizar perfiles")
        }
        if (message.isNotBlank()) {
            StatusBanner(message, isError = message.contains("no se", ignoreCase = true))
        }
        if (profiles.isEmpty() && !busy) {
            Text(
                "No hay perfiles cargados. Actualiza la lista o verifica la conexión del servidor.",
                modifier = Modifier.padding(top = 14.dp),
                color = Muted,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        LazyColumn(
            modifier = Modifier.fillMaxWidth().weight(1f),
            contentPadding = PaddingValues(vertical = 8.dp),
        ) {
            items(profiles, key = { it.email }) { profile ->
                WorkspaceProfileCard(
                    profile = profile,
                    isOwner = profile.email.equals(ownerEmail, ignoreCase = true),
                    busy = busy,
                    onSave = onSave,
                )
            }
        }
    }
}

@Composable
private fun WorkspaceProfileCard(
    profile: WorkspaceProfile,
    isOwner: Boolean,
    busy: Boolean,
    onSave: (WorkspaceProfile) -> Unit,
) {
    var role by remember(profile.email, profile.role) { mutableStateOf(profile.role) }
    var status by remember(profile.email, profile.status) { mutableStateOf(profile.status) }
    var downloadAllowed by remember(profile.email, profile.downloadAllowed) {
        mutableStateOf(profile.downloadAllowed)
    }
    Card(
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
        colors = CardDefaults.cardColors(containerColor = Panel),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(
                profile.fullName.ifBlank { profile.email },
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(profile.email, color = Muted, style = MaterialTheme.typography.bodySmall)
            CaseEditorChoiceField(
                label = "Rol",
                value = role,
                choices = listOf(
                    "Sin Rol Asignado",
                    "Visualizador",
                    "Modificador",
                    "Administrador",
                    "Super Administrador",
                ),
                enabled = !busy && !isOwner,
                onValueChange = { role = it },
            )
            CaseEditorChoiceField(
                label = "Estado",
                value = status,
                choices = listOf("Pendiente", "Activo", "Inactivo"),
                enabled = !busy && !isOwner,
                onValueChange = { status = it },
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(
                    checked = downloadAllowed,
                    onCheckedChange = { downloadAllowed = it },
                    enabled = !busy && !isOwner,
                )
                Text("Permitir descarga de documentos")
            }
            if (profile.downloadRequested) {
                Text(
                    "Solicitud de descarga pendiente",
                    color = Cyan,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Button(
                onClick = {
                    onSave(
                        profile.copy(
                            role = role,
                            status = status,
                            downloadAllowed = downloadAllowed,
                        )
                    )
                },
                enabled = !busy && !isOwner,
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            ) {
                Text(if (isOwner) "Propietario protegido" else "Guardar permisos")
            }
        }
    }
}

@Composable
private fun WorkspaceInboxScreen(
    messages: List<WorkspaceMessage>,
    busy: Boolean,
    message: String,
    canManageMessages: Boolean,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    onSend: (String, String) -> Unit,
    onMarkRead: (String) -> Unit,
) {
    var subject by remember { mutableStateOf("") }
    var body by remember { mutableStateOf("") }
    LaunchedEffect(message) {
        if (message.startsWith("Mensaje guardado en el buzón compartido")) {
            subject = ""
            body = ""
        }
    }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 20.dp, vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.Default.ArrowBack, contentDescription = "Volver al inicio")
            }
            Text(
                "Buzón compartido",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
            )
        }
        OutlinedButton(
            onClick = onRefresh,
            enabled = !busy,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Actualizar mensajes")
        }
        if (message.isNotBlank()) {
            StatusBanner(message, isError = message.contains("no se", ignoreCase = true))
        }
        OutlinedTextField(
            value = subject,
            onValueChange = { subject = it.take(200) },
            label = { Text("Asunto") },
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            singleLine = true,
        )
        OutlinedTextField(
            value = body,
            onValueChange = { body = it.take(10000) },
            label = { Text("Consulta de soporte") },
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            minLines = 2,
            maxLines = 4,
        )
        Button(
            onClick = { onSend(subject, body) },
            enabled = !busy && body.isNotBlank(),
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        ) {
            Text("Enviar consulta")
        }
        Text(
            "Mensajes compartidos: ${messages.size}",
            modifier = Modifier.padding(top = 12.dp),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
        )
        LazyColumn(
            modifier = Modifier.fillMaxWidth().weight(1f),
            contentPadding = PaddingValues(vertical = 6.dp),
        ) {
            items(messages, key = { it.id }) { item ->
                Card(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp),
                    colors = CardDefaults.cardColors(containerColor = Panel),
                ) {
                    Column(Modifier.padding(14.dp)) {
                        Text(item.subject, fontWeight = FontWeight.Bold)
                        Text(
                            "${item.senderEmail} · ${item.createdAt}",
                            color = Muted,
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Text(item.message, modifier = Modifier.padding(top = 8.dp))
                        if (item.readAt.isBlank() && canManageMessages) {
                            TextButton(
                                onClick = { onMarkRead(item.id) },
                                enabled = !busy,
                            ) {
                                Text("Marcar como leída")
                            }
                        } else {
                            Text(
                                "Leído",
                                modifier = Modifier.padding(top = 6.dp),
                                color = Cyan,
                                style = MaterialTheme.typography.labelSmall,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AppHeader(userEmail: String, onLogout: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text("DESVINCULACIONES", color = Cyan, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold)
            Text(userEmail, color = Muted, style = MaterialTheme.typography.bodySmall)
        }
        TextButton(onClick = onLogout) {
            Icon(Icons.Default.ExitToApp, contentDescription = null)
            Spacer(Modifier.width(4.dp))
            Text("Salir")
        }
    }
}

@Composable
private fun MetricCard(label: String, value: String, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        shape = MaterialTheme.shapes.large,
        color = Panel,
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(label, style = MaterialTheme.typography.labelMedium, color = Muted)
            Text(value, modifier = Modifier.padding(top = 4.dp), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun CaseCard(case: Expediente, onSelect: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp)
            .clickable(onClick = onSelect),
        colors = CardDefaults.cardColors(containerColor = Panel),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(18.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(case.radicado_padre, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text("Placa ${case.placa.ifBlank { "Sin dato" }}", modifier = Modifier.padding(top = 3.dp), color = Cyan, style = MaterialTheme.typography.labelLarge)
                }
                CaseStatus(case.caso)
            }
            HorizontalDivider(Modifier.padding(vertical = 12.dp), color = DividerColor)
            Text(case.empresa.ifBlank { "Empresa sin dato" }, style = MaterialTheme.typography.bodyMedium)
            Text(
                "Propietario: ${case.propietario.ifBlank { "Sin dato" }}",
                modifier = Modifier.padding(top = 4.dp),
                style = MaterialTheme.typography.bodySmall,
                color = Muted,
            )
            Text(
                "Solicitud: ${case.fecha_solicitud.ifBlank { "Sin fecha" }}",
                modifier = Modifier.padding(top = 8.dp),
                style = MaterialTheme.typography.labelSmall,
                color = Muted,
            )
        }
    }
}

@Composable
private fun CaseStatus(status: String) {
    val label = when (status.trim().lowercase()) {
        "con recurso" -> "Con recurso"
        "sin recurso" -> "Sin recurso"
        "desistimiento" -> "Desistimiento"
        else -> status.ifBlank { "Sin clasificar" }
    }
    Surface(shape = MaterialTheme.shapes.small, color = PanelRaised) {
        Text(label, modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp), color = Cyan, style = MaterialTheme.typography.labelSmall)
    }
}

@Composable
private fun CaseListScreen(
    cases: List<Expediente>,
    message: String,
    busy: Boolean,
    userEmail: String,
    title: String,
    onCaseSelect: (String) -> Unit,
    onRefresh: () -> Unit,
    onHome: () -> Unit,
    onLogout: () -> Unit,
) {
    var searchText by remember { mutableStateOf(TextFieldValue("")) }

    val filteredCases = if (searchText.text.isEmpty()) {
        cases
    } else {
        cases.filter {
            it.radicado_padre.contains(searchText.text, ignoreCase = true) ||
                    it.placa.contains(searchText.text, ignoreCase = true) ||
                    it.nit_empresa.contains(searchText.text, ignoreCase = true) ||
                    it.empresa.contains(searchText.text, ignoreCase = true) ||
                    it.propietario.contains(searchText.text, ignoreCase = true) ||
                    it.cedula_propietario.contains(searchText.text, ignoreCase = true) ||
                    it.fecha_solicitud.contains(searchText.text, ignoreCase = true)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 20.dp)
    ) {
        AppHeader(userEmail = userEmail, onLogout = onLogout)
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onHome) { Icon(Icons.Default.ArrowBack, contentDescription = "Volver al inicio") }
            Text(title, Modifier.weight(1f), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            TextButton(onClick = onRefresh, enabled = !busy) { Text("Actualizar") }
        }

        if (title == "Base Histórica") {
            Text(
                "Fuente compartida: Google Sheets · pestaña tabla_2. La pestaña DATOS " +
                    "se mantiene como información auxiliar y no se mezcla con los expedientes.",
                modifier = Modifier.padding(bottom = 8.dp),
                color = Muted,
                style = MaterialTheme.typography.bodySmall,
            )
        }

        OutlinedTextField(
            value = searchText,
            onValueChange = { searchText = it },
            label = { Text("Radicado, placa, NIT, empresa, propietario, cédula o fecha") },
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 8.dp),
            leadingIcon = {
                Icon(
                    Icons.Default.Search,
                    contentDescription = "Buscar",
                )
            },
            singleLine = true,
        )

        if (message.isNotBlank()) {
            Text(message, modifier = Modifier.padding(vertical = 4.dp), color = Muted, style = MaterialTheme.typography.bodySmall)
        }
        Text("${filteredCases.size} expedientes", modifier = Modifier.padding(vertical = 8.dp), color = Muted, style = MaterialTheme.typography.labelMedium)

        LazyColumn(
            modifier = Modifier
                .weight(1f)
                .padding(bottom = 4.dp),
        ) {
            items(filteredCases, key = { it.radicado_padre }) { case ->
                CaseCard(
                    case = case,
                    onSelect = { onCaseSelect(case.radicado_padre) },
                )
            }
            if (filteredCases.isEmpty()) {
                item {
                    Surface(Modifier.fillMaxWidth(), shape = MaterialTheme.shapes.large, color = Panel) {
                        Text(
                            if (cases.isEmpty()) "No hay expedientes disponibles para mostrar."
                            else "No encontramos expedientes con ese criterio.",
                            Modifier.padding(20.dp),
                            color = Muted,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun CaseEditorScreen(
    caseData: JSONObject,
    busy: Boolean,
    message: String,
    onBack: () -> Unit,
    onSave: (Map<String, String>) -> Unit,
) {
    val radicado = caseData.optString("radicado_padre")
    var values by remember(radicado) {
        mutableStateOf(
            CaseEditorFields.associate { field ->
                val value = caseData.optString(field.key)
                field.key to if (field.key == "qx_verificado") {
                    when (value.trim().uppercase()) {
                        "SI", "SÍ", "TRUE", "1" -> "Sí"
                        "NO", "FALSE", "0" -> "No"
                        else -> ""
                    }
                } else {
                    value
                }
            },
        )
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 20.dp, vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.Default.ArrowBack, contentDescription = "Volver al expediente")
            }
            Column {
                Text("Editar expediente", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Text(radicado, color = Muted, style = MaterialTheme.typography.bodySmall)
            }
        }
        Text(
            "Solo se envían los campos que cambies. El radicado no se puede modificar.",
            modifier = Modifier.padding(top = 8.dp, bottom = 10.dp),
            color = Muted,
            style = MaterialTheme.typography.bodySmall,
        )
        CaseEditorFields.forEach { field ->
            when (field.key) {
                "caso" -> CaseEditorChoiceField(
                    label = field.label,
                    value = values[field.key].orEmpty(),
                    choices = listOf("", "Con recurso", "Sin recurso", "Desistimiento"),
                    enabled = !busy,
                    onValueChange = { values = values + (field.key to it) },
                )
                "qx_verificado" -> CaseEditorChoiceField(
                    label = field.label,
                    value = values[field.key].orEmpty(),
                    choices = listOf("", "Sí", "No"),
                    enabled = !busy,
                    onValueChange = { values = values + (field.key to it) },
                )
                else -> OutlinedTextField(
                    value = values[field.key].orEmpty(),
                    onValueChange = { values = values + (field.key to it) },
                    label = { Text(field.label) },
                    enabled = !busy,
                    singleLine = !field.multiline,
                    minLines = if (field.multiline) 3 else 1,
                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                )
            }
        }
        if (message.isNotBlank()) {
            StatusBanner(
                message,
                isError = message.contains("no se", ignoreCase = true) ||
                    message.contains("error", ignoreCase = true),
            )
        }
        Button(
            onClick = { onSave(values) },
            enabled = !busy &&
                values["fecha_solicitud"].orEmpty().isNotBlank() &&
                values["placa"].orEmpty().isNotBlank(),
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp).heightIn(min = 50.dp),
        ) {
            if (busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
            else Text("Guardar cambios en Google Sheets")
        }
    }
}

@Composable
private fun CaseEditorChoiceField(
    label: String,
    value: String,
    choices: List<String>,
    enabled: Boolean,
    onValueChange: (String) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    Box(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        OutlinedTextField(
            value = value.ifBlank { "Sin seleccionar" },
            onValueChange = {},
            label = { Text(label) },
            readOnly = true,
            enabled = enabled,
            trailingIcon = {
                IconButton(onClick = { expanded = true }, enabled = enabled) {
                    Icon(Icons.Default.ArrowDropDown, contentDescription = "Mostrar opciones")
                }
            },
            modifier = Modifier.fillMaxWidth(),
        )
        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false },
            modifier = Modifier.fillMaxWidth(0.9f),
        ) {
            choices.forEach { choice ->
                DropdownMenuItem(
                    text = { Text(choice.ifBlank { "Sin seleccionar" }) },
                    onClick = {
                        onValueChange(choice)
                        expanded = false
                    },
                )
            }
        }
    }
}

@Composable
private fun CaseDetailScreen(
    caseData: JSONObject?,
    documents: List<DocumentoDrive>,
    pendingComplements: List<ComplementoPendiente>,
    uploadSummary: String,
    statusMessage: String,
    busy: Boolean,
    canEditCases: Boolean,
    onBack: () -> Unit,
    onEditCase: () -> Unit,
    onUploadPdf: (Uri) -> Unit,
    onRefreshChecklist: () -> Unit,
    onLinkComplement: (String) -> Unit,
) {
    val documentPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri != null) onUploadPdf(uri)
    }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 20.dp, vertical = 12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.Default.ArrowBack, contentDescription = "Atrás")
            }
            Text(
                text = caseData?.optString("radicado_padre", "Detalles") ?: "Detalles",
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.weight(1f),
            )
        }

        Spacer(modifier = Modifier.height(16.dp))

        caseData?.let { case ->
            Text("Expediente operativo", color = Cyan, style = MaterialTheme.typography.labelMedium)
            Spacer(Modifier.height(12.dp))
            if (canEditCases) {
                OutlinedButton(
                    onClick = onEditCase,
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                ) {
                    Text("Editar datos del expediente")
                }
                Button(
                    onClick = {
                        documentPicker.launch(
                            arrayOf("application/pdf", "image/png", "image/jpeg"),
                        )
                    },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp),
                ) {
                    if (busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    else Text("Seleccionar PDF o imagen · OCR y organizar")
                }
            }
            OutlinedButton(
                onClick = onRefreshChecklist,
                enabled = !busy,
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp).heightIn(min = 48.dp),
            ) {
                Text("Actualizar documentos de Drive")
            }
            if (uploadSummary.isNotBlank()) {
                StatusBanner(
                    uploadSummary,
                    isError = uploadSummary.contains("no se", ignoreCase = true) ||
                        uploadSummary.contains("error", ignoreCase = true),
                )
            }
            if (statusMessage.isNotBlank()) {
                StatusBanner(
                    statusMessage,
                    isError = statusMessage.contains("no se", ignoreCase = true) ||
                        statusMessage.contains("error", ignoreCase = true),
                )
            }
            Spacer(Modifier.height(12.dp))
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(bottom = 12.dp),
                colors = CardDefaults.cardColors(containerColor = Panel),
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                ) {
                    DetailSection(
                        "Identificación del expediente",
                        case,
                        listOf(
                            "radicado_padre" to "Radicado padre",
                            "placa" to "Placa",
                            "fecha_solicitud" to "Fecha de solicitud",
                            "caso" to "Clasificación final",
                            "estado" to "Estado",
                        ),
                    )
                    DetailSection(
                        "Vehículo y partes",
                        case,
                        listOf(
                            "qx_verificado" to "Consulta QX verificada",
                            "empresa" to "Empresa",
                            "nit_empresa" to "NIT",
                            "direccion_empresa" to "Dirección de la empresa",
                            "propietario" to "Propietario",
                            "cedula_propietario" to "Cédula del propietario",
                            "direccion_propietario" to "Dirección del propietario",
                            "solicitante" to "Solicitante",
                        ),
                    )
                    DetailSection(
                        "Actuación administrativa",
                        case,
                        listOf(
                            "requerimiento" to "Requerimiento",
                            "resolucion" to "Resolución",
                            "fecha_resolucion" to "Fecha de resolución",
                            "desistimiento" to "Desistimiento",
                        ),
                    )
                    DetailSection(
                        "Notificación y recursos",
                        case,
                        listOf(
                            "tipo_notificacion" to "Tipo de notificación",
                            "fecha_notificacion" to "Fecha de notificación",
                            "recurso" to "Recurso",
                            "fecha_recurso" to "Fecha del recurso",
                            "resolucion_recurso" to "Resolución del recurso",
                            "fecha_resolucion_recurso" to "Fecha de resolución del recurso",
                        ),
                    )
                    DetailSection(
                        "Cierre y archivo",
                        case,
                        listOf(
                            "fecha_ejecutoria" to "Fecha de ejecutoria",
                            "fecha_remision_registro" to "Fecha de remisión a registro",
                            "ubicacion" to "Ubicación",
                            "caja" to "Caja",
                            "observaciones" to "Observaciones",
                        ),
                    )
                }
            }
        }

        Text(
            "Documentos encontrados en Drive",
            modifier = Modifier.padding(top = 6.dp, bottom = 8.dp),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold,
        )
        if (documents.isEmpty()) {
            Text("Todavía no hay documentos cargados.", color = Muted, style = MaterialTheme.typography.bodySmall)
        } else {
            documents.forEach { document ->
                Card(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                    colors = CardDefaults.cardColors(containerColor = Panel),
                ) {
                    Column(Modifier.padding(12.dp)) {
                        Text(document.tipo, color = Cyan, style = MaterialTheme.typography.labelMedium)
                        Text(document.nombre, style = MaterialTheme.typography.bodySmall)
                        if (document.archivoOrigen.isNotBlank()) {
                            Text(
                                "Origen: ${document.archivoOrigen} · páginas ${document.paginasOrigen}",
                                modifier = Modifier.padding(top = 3.dp),
                                color = Muted,
                                style = MaterialTheme.typography.labelSmall,
                            )
                        }
                    }
                    if (pendingComplements.isNotEmpty()) {
                        Text(
                            "Complementos pendientes para esta placa",
                            modifier = Modifier.padding(top = 18.dp, bottom = 8.dp),
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                        )
                        pendingComplements.forEach { pending ->
                            Card(
                                modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp),
                                colors = CardDefaults.cardColors(containerColor = Panel),
                            ) {
                                Column(Modifier.padding(12.dp)) {
                                    Text(pending.nombre, color = Cyan, style = MaterialTheme.typography.labelLarge)
                                    pending.archivos.forEach { filename ->
                                        Text(filename, modifier = Modifier.padding(top = 4.dp), style = MaterialTheme.typography.bodySmall)
                                    }
                                    if (canEditCases) {
                                        Button(
                                            onClick = { onLinkComplement(pending.id) },
                                            enabled = !busy,
                                            modifier = Modifier.fillMaxWidth().padding(top = 10.dp),
                                        ) {
                                            Text("Vincular a este expediente")
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun DetailSection(label: String, data: JSONObject, fields: List<Pair<String, String>>) {
    val presentFields = fields.filter { data.optString(it.first).isNotBlank() }
    if (presentFields.isEmpty()) return
    Text(
        label,
        modifier = Modifier.padding(top = 14.dp, bottom = 4.dp),
        style = MaterialTheme.typography.titleSmall,
        color = Cyan,
        fontWeight = FontWeight.Bold,
    )
    presentFields.forEach { (key, title) ->
        DetailField(title, data.optString(key))
    }
}

@Composable
private fun DetailField(label: String, value: String) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
    ) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = Muted)
        Text(value, style = MaterialTheme.typography.bodyMedium)
        HorizontalDivider(color = DividerColor)
    }
}
