plugins {
    alias(libs.plugins.android.library)

}
android {
    namespace = "com.haman.audio"
    compileSdk = 37
    compileSdkMinor = 2
    defaultConfig { minSdk = 26 }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlin { jvmToolchain(17) }
}
dependencies {
    api(project(":core-domain"))
    implementation(libs.androidx.core.ktx)
    implementation(libs.kotlinx.coroutines.android)
}
