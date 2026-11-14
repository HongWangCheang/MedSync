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

    // Headless UI walkthrough against the live stack (opt-in: MEDSYNC_WALKTHROUGH=1, see WalkthroughTest).
    testImplementation(compose.desktop.currentOs)
    testImplementation("org.jetbrains.compose.ui:ui-test-junit4:${libs.versions.compose.multiplatform.get()}")
    testImplementation("junit:junit:4.13.2")
}

tasks.test {
    environment("MEDSYNC_WALKTHROUGH", System.getenv("MEDSYNC_WALKTHROUGH") ?: "")
    outputs.upToDateWhen { false }
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
