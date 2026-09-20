// PURE Kotlin/JVM on purpose. This module must never gain an Android dependency:
// it is the part that moves to iOS via Kotlin Multiplatform (see docs/ARCHITECTURE.md §7).
plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.serialization)
}
kotlin { jvmToolchain(17) }
dependencies {
    implementation(libs.kotlinx.serialization.json)
    testImplementation(libs.junit)
}
