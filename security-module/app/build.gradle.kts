plugins {
    alias(libs.plugins.android.application)

    id("org.jetbrains.kotlin.plugin.serialization") version "1.9.0"
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

    // JVM-side Bitmap support for local Phase 7->10 pipeline tests (no emulator required).
    testImplementation("org.robolectric:robolectric:4.13")
    testImplementation("androidx.test:core:1.5.0")
}