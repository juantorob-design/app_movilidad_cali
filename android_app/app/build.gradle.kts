import java.net.URI

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

val apiBaseUrl = providers.gradleProperty("API_BASE_URL")
    .orElse("https://configure-your-api.example.invalid/")
    .get()
val googleWebClientId = providers.gradleProperty("GOOGLE_WEB_CLIENT_ID")
    .orElse("1019857870350-ccrqd53kcl0c6k799f0om2p5fnloviij.apps.googleusercontent.com")
    .get()
val spreadsheetId = providers.gradleProperty("SISTEMA_SPREADSHEET_ID")
    .orElse("1oQ5GnxSj4_gGA-p2NjlN3o0uDOLaIELZu4gpohLK6Uo")
    .get()
val driveFolderId = providers.gradleProperty("SISTEMA_DRIVE_FOLDER_ID")
    .orElse("1vwsw0RKXsoYYqXwhH2OZPaD-BrTiUUyl")
    .get()
val releaseStoreFile = providers.environmentVariable("ANDROID_RELEASE_STORE_FILE").orNull
val releaseKeyAlias = providers.environmentVariable("ANDROID_RELEASE_KEY_ALIAS").orNull
val releaseStorePassword = providers.environmentVariable("ANDROID_RELEASE_STORE_PASSWORD").orNull
val releaseKeyPassword = providers.environmentVariable("ANDROID_RELEASE_KEY_PASSWORD").orNull
val releaseSigningValues = listOf(
    releaseStoreFile,
    releaseKeyAlias,
    releaseStorePassword,
    releaseKeyPassword
)
val releaseSigningConfigured = releaseSigningValues.all { !it.isNullOrBlank() }

val validateReleaseApiUrl by tasks.registering {
    doLast {
        val apiUri = runCatching { URI(apiBaseUrl) }.getOrNull()
        require(
            apiUri != null &&
                apiUri.scheme == "https" &&
                !apiUri.host.isNullOrBlank() &&
                !apiUri.host.endsWith(".invalid", ignoreCase = true)
        ) {
            "Release builds require a real HTTPS API_BASE_URL; do not ship the placeholder URL."
        }
    }
}

val validateReleaseSigning by tasks.registering {
    doLast {
        require(releaseSigningConfigured) {
            "Release builds require ANDROID_RELEASE_STORE_FILE, ANDROID_RELEASE_KEY_ALIAS, " +
                "ANDROID_RELEASE_STORE_PASSWORD, and ANDROID_RELEASE_KEY_PASSWORD."
        }
        require(file(releaseStoreFile!!).isFile) {
            "The Android release keystore does not exist at ANDROID_RELEASE_STORE_FILE."
        }
    }
}

tasks.configureEach {
    if (
        name.startsWith("assembleRelease") ||
        name.startsWith("bundleRelease") ||
        name.startsWith("packageRelease")
    ) {
        dependsOn(validateReleaseApiUrl)
        dependsOn(validateReleaseSigning)
    }
}

android {
    namespace = "co.sistemadesvinculaciones.mobile"
    compileSdk = 36

    defaultConfig {
        applicationId = "co.sistemadesvinculaciones.mobile"
        minSdk = 26
        targetSdk = 35
        versionCode = 6
        versionName = "0.1.5"
        buildConfigField("String", "API_BASE_URL", "\"$apiBaseUrl\"")
        buildConfigField("String", "GOOGLE_WEB_CLIENT_ID", "\"$googleWebClientId\"")
        buildConfigField("String", "SPREADSHEET_ID", "\"$spreadsheetId\"")
        buildConfigField("String", "DRIVE_FOLDER_ID", "\"$driveFolderId\"")
    }

    if (releaseSigningConfigured) {
        signingConfigs {
            create("release") {
                storeFile = file(releaseStoreFile!!)
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        getByName("release") {
            if (releaseSigningConfigured) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
        compose = true
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.02.00"))
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.browser:browser:1.8.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.credentials:credentials:1.5.0")
    implementation("androidx.credentials:credentials-play-services-auth:1.5.0")
    implementation("com.google.android.libraries.identity.googleid:googleid:1.1.1")
    implementation("com.llamatik:library:1.10.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
