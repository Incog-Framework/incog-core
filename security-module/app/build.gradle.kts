import java.util.Properties

plugins {
    alias(libs.plugins.android.application)

    id("org.jetbrains.kotlin.plugin.serialization") version "1.9.0"
}

// ---------------------------------------------------------------------------
// Shared AES-256-GCM evidence key (team DECISION 1).
//
// The real key is coordinated out-of-band with the backend and must NEVER be
// committed. Supply it through local.properties (gitignored - the Android
// equivalent of the backend's .env):
//
//     incog.evidenceKeyBase64=<base64 of 32 random bytes>
//
// ...or through the INCOG_EVIDENCE_KEY_BASE64 environment variable for CI.
//
// A clean checkout with neither set falls back to an obvious placeholder so
// the project still builds and the test suite runs. Anything encrypted under
// the placeholder will NOT decrypt on the backend - that is intentional, and
// CryptoManager logs a loud warning when it is in use.
// ---------------------------------------------------------------------------
val placeholderEvidenceKey = "SU5DT0ctUExBQ0VIT0xERVItS0VZLURPLU5PVC1VU0U="

val evidenceKeyBase64: String = run {
    val localProperties = Properties()
    val localPropertiesFile = rootProject.file("local.properties")

    if (localPropertiesFile.exists()) {
        localPropertiesFile.inputStream().use(localProperties::load)
    }

    localProperties.getProperty("incog.evidenceKeyBase64")
        ?: System.getenv("INCOG_EVIDENCE_KEY_BASE64")
        ?: placeholderEvidenceKey
}

android {
    namespace = "com.incog.incogsecuritycore"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "com.incog.incogsecuritycore"
        minSdk = 24
        targetSdk = 37
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // Injected, never hardcoded in source - see the note at the top of this file.
        buildConfigField("String", "EVIDENCE_KEY_BASE64", "\"$evidenceKeyBase64\"")
        buildConfigField(
            "boolean",
            "EVIDENCE_KEY_IS_PLACEHOLDER",
            (evidenceKeyBase64 == placeholderEvidenceKey).toString()
        )
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

// Robolectric 4.13's bundled ASM can't read class files produced by very new
// JDKs (e.g. JDK 25 -> "Unsupported class file major version 69") during its
// shadow teardown. Pin the test JVM to a known-compatible toolchain instead
// of relying on whatever JDK happens to be on the host's PATH.
kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.core.ktx)
    implementation(libs.material)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")

    // Pixel-level stego work is CPU-bound and must stay off the main thread
    // (ANR risk on real carrier images) - the orchestrator runs it on Dispatchers.Default.
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")

    // JVM-side Bitmap support for local Phase 7->10 pipeline tests (no emulator required).
    testImplementation("org.robolectric:robolectric:4.13")
    testImplementation("androidx.test:core:1.5.0")
}