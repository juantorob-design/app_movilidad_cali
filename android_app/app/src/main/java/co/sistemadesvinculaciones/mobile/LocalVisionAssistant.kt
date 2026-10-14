package co.sistemadesvinculaciones.mobile

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.pdf.PdfRenderer
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.os.ParcelFileDescriptor
import android.os.StatFs
import com.llamatik.library.platform.GenStream
import com.llamatik.library.platform.MultimodalBridge
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.security.MessageDigest
import java.util.Locale
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.job

internal data class LocalAiExtraction(
    val sourceUri: String,
    val radicado: String,
    val placa: String,
    val fechaSolicitud: String,
)

internal class LocalVisionAssistant(context: Context) {
    private data class ModelFile(
        val name: String,
        val size: Long,
        val sha256: String,
    )

    private val appContext = context.applicationContext
    private val modelDirectory = File(appContext.filesDir, "local-vision")
    private val mainHandler = Handler(Looper.getMainLooper())
    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .callTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    @Volatile private var activeCall: Call? = null
    @Volatile private var modelLoaded = false

    suspend fun extractPrimaryDocument(
        uri: Uri,
        onProgress: (String, Float?) -> Unit,
    ): LocalAiExtraction = withContext(Dispatchers.IO) {
        ensureModelFiles(onProgress)
        currentCoroutineContext().ensureActive()

        if (!modelLoaded) {
            notifyProgress(onProgress, "Cargando Qwen Vision en este dispositivo…", null)
            val model = File(modelDirectory, MODEL.name)
            val projector = File(modelDirectory, PROJECTOR.name)
            if (!MultimodalBridge.initModel(model.absolutePath, projector.absolutePath)) {
                MultimodalBridge.release()
                throw IOException("No se pudo iniciar Qwen Vision. Verifica que el teléfono tenga al menos 6 GB de RAM.")
            }
            modelLoaded = true
        }

        val pages = readDocumentPages(uri)
        var radicado = ""
        var placa = ""
        var fecha = ""
        for ((index, imageBytes) in pages.withIndex()) {
            currentCoroutineContext().ensureActive()
            notifyProgress(onProgress, "IA local: analizando página ${index + 1} de ${pages.size}…", null)
            val fields = analyzePage(imageBytes)
            if (radicado.isBlank()) radicado = fields.optString("radicado_padre").trim()
            if (placa.isBlank()) placa = fields.optString("placa").trim().uppercase(Locale.ROOT)
            if (fecha.isBlank()) fecha = fields.optString("fecha_solicitud").trim()
            if (radicado.isNotBlank() && placa.isNotBlank() && fecha.isNotBlank()) break
        }

        LocalAiExtraction(
            sourceUri = uri.toString(),
            radicado = radicado,
            placa = placa,
            fechaSolicitud = fecha,
        )
    }

    fun cancel() {
        activeCall?.cancel()
        if (modelLoaded) MultimodalBridge.cancelAnalysis()
    }

    fun release() {
        if (modelLoaded) {
            MultimodalBridge.release()
            modelLoaded = false
        }
    }

    private suspend fun ensureModelFiles(onProgress: (String, Float?) -> Unit) {
        if (!modelDirectory.exists() && !modelDirectory.mkdirs()) {
            throw IOException("No se pudo crear el almacenamiento privado para la IA local.")
        }
        val files = listOf(MODEL, PROJECTOR)
        var requiredBytes = 0L
        for (file in files) {
            val target = File(modelDirectory, file.name)
            if (target.exists() && target.length() == file.size) continue
            if (target.exists() && !target.delete()) {
                throw IOException("No se pudo reemplazar el archivo local incompleto: ${file.name}.")
            }
            requiredBytes += file.size
        }
        val availableBytes = StatFs(modelDirectory.absolutePath).availableBytes
        if (availableBytes < requiredBytes) {
            val requiredGb = "%.2f".format(Locale.ROOT, requiredBytes / 1_000_000_000.0)
            val availableGb = "%.2f".format(Locale.ROOT, availableBytes / 1_000_000_000.0)
            throw IOException(
                "La IA local necesita $requiredGb GB libres y el teléfono tiene $availableGb GB disponibles."
            )
        }

        val totalBytes = files.sumOf { it.size }
        var completedBytes = files.sumOf { file ->
            File(modelDirectory, file.name).takeIf { it.length() == file.size }?.length() ?: 0L
        }
        for (file in files) {
            val target = File(modelDirectory, file.name)
            if (target.length() == file.size) continue
            downloadModelFile(file, target) { downloadedBytes ->
                val progress = (completedBytes + downloadedBytes).toFloat() / totalBytes
                notifyProgress(
                    onProgress,
                    "Descargando ${file.name}: %.0f%%".format(Locale.ROOT, progress * 100f),
                    progress.coerceIn(0f, 1f),
                )
            }
            completedBytes += file.size
        }
    }

    private suspend fun downloadModelFile(
        file: ModelFile,
        target: File,
        onBytesRead: (Long) -> Unit,
    ) {
        val partial = File(target.parentFile, "${target.name}.part")
        if (partial.exists() && !partial.delete()) {
            throw IOException("No se pudo limpiar una descarga incompleta de ${file.name}.")
        }
        val url = "$MODEL_BASE_URL/${file.name}"
        val call = httpClient.newCall(Request.Builder().url(url).get().build())
        activeCall = call
        val cancellation = currentCoroutineContext().job.invokeOnCompletion { cause ->
            if (cause is CancellationException) call.cancel()
        }
        var installed = false
        try {
            call.execute().use { response ->
                if (!response.isSuccessful) {
                    throw IOException("No se pudo descargar ${file.name} (HTTP ${response.code}).")
                }
                val body = response.body ?: throw IOException("La descarga de ${file.name} llegó vacía.")
                val digest = MessageDigest.getInstance("SHA-256")
                var received = 0L
                FileOutputStream(partial).use { output ->
                    body.byteStream().use { input ->
                        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                        while (true) {
                            currentCoroutineContext().ensureActive()
                            val count = input.read(buffer)
                            if (count < 0) break
                            output.write(buffer, 0, count)
                            digest.update(buffer, 0, count)
                            received += count
                            onBytesRead(received)
                        }
                    }
                    output.fd.sync()
                }
                if (received != file.size) {
                    throw IOException("La descarga de ${file.name} quedó incompleta ($received/${file.size} bytes).")
                }
                val actualSha256 = digest.digest().joinToString("") { "%02x".format(it) }
                if (!actualSha256.equals(file.sha256, ignoreCase = true)) {
                    throw IOException("La verificación SHA-256 de ${file.name} no coincide.")
                }
                if (!partial.renameTo(target)) {
                    throw IOException("No se pudo instalar ${file.name} en el almacenamiento privado.")
                }
                installed = true
            }
        } finally {
            cancellation.dispose()
            activeCall = null
            if (!installed) partial.delete()
        }
    }

    private fun readDocumentPages(uri: Uri): List<ByteArray> {
        val mimeType = appContext.contentResolver.getType(uri).orEmpty()
        if (mimeType.equals("application/pdf", ignoreCase = true)) {
            val descriptor = appContext.contentResolver.openFileDescriptor(uri, "r")
                ?: throw IOException("No se pudo abrir el PDF seleccionado.")
            descriptor.use { fileDescriptor ->
                PdfRenderer(fileDescriptor).use { renderer ->
                    if (renderer.pageCount == 0) throw IOException("El PDF no contiene páginas.")
                    val pageCount = minOf(renderer.pageCount, MAX_PAGES)
                    return (0 until pageCount).map { pageIndex ->
                        renderer.openPage(pageIndex).use { page ->
                            val scale = minOf(
                                MAX_IMAGE_SIDE.toFloat() / page.width,
                                MAX_IMAGE_SIDE.toFloat() / page.height,
                                1f,
                            )
                            val bitmap = Bitmap.createBitmap(
                                (page.width * scale).toInt().coerceAtLeast(1),
                                (page.height * scale).toInt().coerceAtLeast(1),
                                Bitmap.Config.ARGB_8888,
                            )
                            try {
                                page.render(bitmap, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                                bitmap.toJpeg()
                            } finally {
                                bitmap.recycle()
                            }
                        }
                    }
                }
            }
        }

        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        appContext.contentResolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, bounds)
        } ?: throw IOException("No se pudo abrir la imagen seleccionada.")
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
            throw IOException("El archivo seleccionado no es una imagen compatible ni un PDF.")
        }
        var sampleSize = 1
        while (bounds.outWidth / sampleSize > MAX_IMAGE_SIDE ||
            bounds.outHeight / sampleSize > MAX_IMAGE_SIDE
        ) {
            sampleSize *= 2
        }
        val bitmap = BitmapFactory.Options().run {
            inSampleSize = sampleSize
            appContext.contentResolver.openInputStream(uri)?.use {
                BitmapFactory.decodeStream(it, null, this)
            }
        } ?: throw IOException("No se pudo decodificar la imagen seleccionada.")
        return try {
            listOf(bitmap.toJpeg())
        } finally {
            bitmap.recycle()
        }
    }

    private suspend fun analyzePage(imageBytes: ByteArray): org.json.JSONObject =
        suspendCancellableCoroutine { continuation ->
            val response = StringBuilder()
            var callbackError: String? = null
            try {
                MultimodalBridge.analyzeImageBytesStream(
                    imageBytes,
                    EXTRACTION_PROMPT,
                    object : GenStream {
                        override fun onDelta(text: String) {
                            response.append(text)
                        }

                        override fun onComplete() = Unit

                        override fun onError(message: String) {
                            callbackError = message
                        }
                    },
                )
                val error = callbackError
                if (error != null) {
                    continuation.resumeWithException(IOException("Falló el análisis visual local: $error"))
                } else {
                    val output = response.toString()
                    val firstBrace = output.indexOf('{')
                    val lastBrace = output.lastIndexOf('}')
                    if (firstBrace < 0 || lastBrace <= firstBrace) {
                        continuation.resumeWithException(
                            IOException("La IA local no devolvió los campos en el formato esperado.")
                        )
                    } else {
                        continuation.resume(org.json.JSONObject(output.substring(firstBrace, lastBrace + 1)))
                    }
                }
            } catch (error: Exception) {
                if (continuation.isActive) continuation.resumeWithException(error)
            }
        }

    private fun notifyProgress(
        callback: (String, Float?) -> Unit,
        message: String,
        fraction: Float?,
    ) {
        mainHandler.post { callback(message, fraction) }
    }

    private fun Bitmap.toJpeg(): ByteArray =
        ByteArrayOutputStream().use { output ->
            if (!compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, output)) {
                throw IOException("No se pudo preparar la página para el análisis visual.")
            }
            output.toByteArray()
        }

    private companion object {
        const val MAX_PAGES = 5
        const val MAX_IMAGE_SIDE = 1536
        const val JPEG_QUALITY = 82
        const val MODEL_BASE_URL =
            "https://huggingface.co/mradermacher/Qwen2.5-VL-3B-Instruct-GGUF/resolve/d7e3d6cde3a5f736a9deba10c58e5e1e2069c0d2"
        const val EXTRACTION_PROMPT =
            "Analiza esta página de una petición administrativa colombiana de desvinculación de vehículo. " +
                "Extrae solo datos que sean legibles y estén explícitos. Devuelve exclusivamente un objeto JSON " +
                "con estas claves: radicado_padre, placa, fecha_solicitud. Usa cadenas vacías si un dato no aparece. " +
                "fecha_solicitud debe estar en formato AAAA-MM-DD; no inventes ni infieras datos."

        val MODEL = ModelFile(
            name = "Qwen2.5-VL-3B-Instruct.Q3_K_M.gguf",
            size = 1_590_475_584L,
            sha256 = "4b4a6bca2cb738975edc9bf98ec54f7cb382e1aae31a22d953554466ed64eb7a",
        )
        val PROJECTOR = ModelFile(
            name = "Qwen2.5-VL-3B-Instruct.mmproj-fp16.gguf",
            size = 1_338_428_544L,
            sha256 = "747ca564db62e0903006a6d9bd31a0d55f85ed6afd919c7b0e55496983705e75",
        )
    }
}
