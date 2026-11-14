import org.jetbrains.compose.desktop.application.dsl.TargetFormat

plugins {
    alias(libs.plugins.kotlinJvm)
    alias(libs.plugins.composeMultiplatform)
    alias(libs.plugins.composeCompiler)
}

dependencies {
    implementation(projects.shared)
    implementation(compose.desktop.currentOs)
    implementation(libs.kotlinx.coroutines.swing)
    // On-device router: LiteRT-LM's JVM runtime stands in for the phone's (same Kotlin API as litertlm-android).
    implementation(libs.litertlm.jvm)
    implementation(libs.kotlinx.datetime)

    // Headless UI walkthrough against the live stack (opt-in: MEDSYNC_WALKTHROUGH=1, see WalkthroughTest).
    testImplementation(compose.desktop.currentOs)
    testImplementation("org.jetbrains.compose.ui:ui-test-junit4:${libs.versions.compose.multiplatform.get()}")
    testImplementation("junit:junit:4.13.2")
    testImplementation(libs.ktor.serialization.kotlinx.json)  // brings kotlinx-serialization-json
}

tasks.test {
    // Opt-in live checks read MEDSYNC_* (walkthrough, routing eval); pass them through to the test JVM.
    System.getenv().filterKeys { it.startsWith("MEDSYNC_") }.forEach { (key, value) -> environment(key, value) }
    outputs.upToDateWhen { false }
    testLogging { showStandardStreams = true }
}

compose.desktop {
    application {
        mainClass = "com.medsync.client.MainKt"
        nativeDistributions {
            // macOS .dmg, Windows .msi, Linux .deb
            targetFormats(TargetFormat.Dmg, TargetFormat.Msi, TargetFormat.Deb)
            packageName = "MedSync"
            packageVersion = "1.0.0"
        }
    }
}
