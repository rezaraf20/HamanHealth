plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}
android {
    namespace = "com.haman.sleep"
    compileSdk = 37
    compileSdkMinor = 2
    defaultConfig {
        applicationId = "com.haman.sleep"
        minSdk = 26
        targetSdk = 36
        versionCode = 2
        versionName = "0.2.0"
        // On-device tests: the model wrapper and the database can only be exercised
        // against a real TFLite runtime and a real SQLite, not on the JVM.
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    buildTypes {
        release {
            // R8 stays off until keep rules for TFLite and kotlinx.serialization are
            // verified on device; a mis-shrunk model loader fails only at runtime.
            isMinifyEnabled = false
            // Signed with the debug key so the APK installs directly by sideloading, with
            // no keystore to manage. It is still a release build: not debuggable, so
            // `adb run-as` cannot copy the sleep log and clips off the phone, and the
            // debug-only raw audio dump is disabled. Use a real release key before any
            // store distribution.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    buildFeatures { compose = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlin { jvmToolchain(17) }
    // The .tflite model must not be compressed, or the interpreter cannot mmap it
    // and every load copies 15 MB into heap.
    androidResources { noCompress += "tflite" }
}
dependencies {
    implementation(project(":core-domain"))
    implementation(project(":core-audio"))
    implementation(project(":core-inference"))
    implementation(project(":core-data"))

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.service)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)

    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.material.icons)
    debugImplementation(libs.compose.ui.tooling)

    testImplementation(libs.junit)
    androidTestImplementation(libs.junit)
    androidTestImplementation(libs.androidx.test.junit)
    androidTestImplementation(libs.androidx.test.runner)
}
