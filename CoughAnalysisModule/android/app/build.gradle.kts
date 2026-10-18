plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}
android {
    namespace = "com.haman.sleep"
    compileSdk = 37
    compileSdkMinor = 2
    defaultConfig {
        applicationId = "com.haman.sleep"
        minSdk = 26
        targetSdk = 36
        versionCode = 4
        versionName = "0.3.1"
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
    // Room's exported schemas, for MigrationTestHelper in the instrumented tests.
    sourceSets.getByName("androidTest").assets.directories.add("$rootDir/core-data/schemas")
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

    // The web interface runs in a Capacitor WebView; the cough module is its "CoughSession"
    // plugin. Same major as @capacitor/core in web/package.json.
    implementation(libs.capacitor.android)
    implementation(libs.androidx.appcompat) // BridgeActivity's superclass
    // Background upload of finished nights and clips (sync/).
    implementation(libs.androidx.work.runtime.ktx)
    implementation(libs.okhttp)

    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.material.icons)
    debugImplementation(libs.compose.ui.tooling)

    testImplementation(libs.junit)
    testImplementation(libs.okhttp.mockwebserver)
    testImplementation(libs.kotlinx.coroutines.test)
    androidTestImplementation(libs.junit)
    androidTestImplementation(libs.room.testing)
    androidTestImplementation(libs.androidx.test.junit)
    androidTestImplementation(libs.androidx.test.runner)
}

// ── Capacitor web assets ──────────────────────────────────────────────────────
// What `npx cap copy android` would produce, without needing node: the bundled web
// directory (web/native-shell: index.html + the offline page) as assets/public, and
// web/capacitor.config.json as assets/capacitor.config.json. The interface itself is
// loaded live from server.url in that config, so the web app is not built here.
abstract class CapacitorAssets : DefaultTask() {
    @get:InputDirectory abstract val webDir: DirectoryProperty
    @get:InputFile abstract val config: RegularFileProperty
    @get:OutputDirectory abstract val output: DirectoryProperty

    @TaskAction
    fun copy() {
        val out = output.get().asFile
        out.deleteRecursively()
        webDir.get().asFile.copyRecursively(File(out, "public"))
        config.get().asFile.copyTo(File(out, "capacitor.config.json"))
        // npm-installed plugins would be listed here; ours is registered in MainActivity.
        File(out, "capacitor.plugins.json").writeText("[]\n")
    }
}

val webProject = rootProject.layout.projectDirectory.dir("../../web")
val capacitorAssets = tasks.register<CapacitorAssets>("capacitorAssets") {
    webDir.set(webProject.dir("native-shell"))
    config.set(webProject.file("capacitor.config.json"))
    output.set(layout.buildDirectory.dir("generated/capacitor"))
}

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(capacitorAssets, CapacitorAssets::output)
    }
}
