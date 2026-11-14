package com.medsync.client

import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.application
import androidx.compose.ui.window.rememberWindowState
import com.medsync.client.agents.FallbackRouter
import com.medsync.client.agents.RuleBasedRouter
import com.medsync.client.app.MedSyncApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import com.medsync.client.ui.App

fun main() {
    // On-device model when its file is present (~/.medsync/models, or MEDSYNC_MODEL); the rules otherwise.
    val model = LiteRtRouter().takeIf { it.available && System.getenv("MEDSYNC_ROUTER") != "rules" }
    val router = model?.let { FallbackRouter(it) } ?: RuleBasedRouter
    val controller = MedSyncApp.init(desktopDatabaseBuilder(), System.getenv("MEDSYNC_GATEWAY") ?: DESKTOP_GATEWAY,
        router)
    model?.let { CoroutineScope(Dispatchers.IO).launch { it.warmUp() } }  // load while the window opens
    application {
        Window(onCloseRequest = ::exitApplication, title = "MedSync",
            state = rememberWindowState(width = 760.dp, height = 820.dp)) {
            App(controller)
        }
    }
}
