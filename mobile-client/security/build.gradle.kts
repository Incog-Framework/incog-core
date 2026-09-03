import java.util.Properties

plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.serialization)
}

// ---------------------------------------------------------------------------
// Shared AES-256-GCM evidence key (team DECISION 1).
//
// The real key is coordinated out-of-band with the backend and must NEVER be
// committed. Supply it through local.properties (gitignored):
//
//     incog.evidenceKeyBase64=<base64 of 32 random bytes>
//
// ...or the INCOG_EVIDENCE_KEY_BASE64 environment variable for CI. A clean
// checkout with neither set falls back to an obvious placeholder so the project
// still builds; anything encrypted under it will NOT decrypt on the backend
// (CryptoManager logs a loud warning when the placeholder is in use).
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
        minSdk = 24

        // Injected, never hardcoded in source.
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

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

// Robolectric 4.13's bundled ASM can't read class files from very new JDKs
// during shadow teardown — pin the test JVM to a compatible toolchain.
kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    // Stego/crypto work runs on Dispatchers.Default (off the main thread).
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    testImplementation(libs.junit)
    testImplementation("org.robolectric:robolectric:4.13")
    testImplementation("androidx.test:core:1.5.0")
}
