// Top-level build file where you can add configuration options common to all sub-projects/modules.
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.compose) apply false
}

// OPTIONAL, per-machine: redirect build outputs outside the project folder. Needed on machines
// where the repo lives in a cloud-synced folder (e.g. OneDrive), which locks files inside build/
// while Gradle writes them, causing "Unable to delete directory" failures. This is opt-in so the
// committed config stays portable: set `incog.externalBuildDir=<abs path>` in your *local*
// gradle.properties (~/.gradle/gradle.properties, not committed) to enable it. Unset = default
// build/ dir, which is correct for anyone not affected.
val externalBuildDir = providers.gradleProperty("incog.externalBuildDir").orNull
if (externalBuildDir != null) {
    allprojects {
        layout.buildDirectory.set(file(externalBuildDir).resolve(name))
    }
}