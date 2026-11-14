package com.medsync.client

import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState
import com.medsync.client.app.MedSyncApp
import com.medsync.client.ui.App

fun main() {
    val controller = MedSyncApp.init(desktopDatabaseBuilder(), System.getenv("MEDSYNC_GATEWAY") ?: DESKTOP_GATEWAY)
    application {
        Window(onCloseRequest = ::exitApplication, title = "MedSync",
            state = rememberWindowState(width = 760.dp, height = 820.dp)) {
            App(controller)
        }
    }
}
