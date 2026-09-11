import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// Backend config (team DECISION 1). Supplied per-machine via local.properties (gitignored):
//     incog.backendUrl=https://<host>/api/v1/sos
//     incog.agentKey=<X-Agent-Key value shared with the backend>
// ...or the INCOG_BACKEND_URL / INCOG_AGENT_KEY environment variables. Placeholders let a clean
// checkout still build; uploads won't reach a real backend until these are set.
val incogProps: Properties = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use(::load)
}
fun incogConfig(key: String, env: String, default: String): String =
    incogProps.getProperty(key) ?: System.getenv(env) ?: default

val backendUrl = incogConfig("incog.backendUrl", "INCOG_BACKEND_URL", "https://example.invalid/api/v1/sos")
val agentKey = incogConfig("incog.agentKey", "INCOG_AGENT_KEY", "PLACEHOLDER-AGENT-KEY")

// Release signing (gitignored keystore.properties). Absent on a clean checkout/CI — then the
// release build is simply left unsigned rather than failing.
val keystoreProps: Properties? = rootProject.file("keystore.properties").takeIf { it.exists() }
    ?.let { f -> Properties().apply { f.inputStream().use(::load) } }

android {
    namespace = "com.incog.mobileclient"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "com.incog.mobileclient"
        minSdk = 26
        targetSdk = 37
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        buildConfigField("String", "BACKEND_SOS_URL", "\"$backendUrl\"")
        buildConfigField("String", "AGENT_KEY", "\"$agentKey\"")
    }

    signingConfigs {
        if (keystoreProps != null) {
            create("release") {
                storeFile = rootProject.file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
            // Sign with the release key when keystore.properties is present (sideload-ready APK);
            // otherwise the release APK is left unsigned.
            if (keystoreProps != null) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }

    lint {
        // False positive: this rule targets Fragment's ActivityResult API needing fragment 1.3.0+,
        // but registerForActivityResult here is on a ComponentActivity (androidx.activity), where the
        // Fragment version is irrelevant. Left as an error it fails the release build's lintVital.
        disable += "InvalidFragmentVersionForActivityResult"
    }
}

dependencies {
    implementation(project(":security"))
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.play.services.location)
    implementation(libs.tensorflow.lite)
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    testImplementation(libs.junit)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
    debugImplementation(libs.androidx.compose.ui.tooling)
}