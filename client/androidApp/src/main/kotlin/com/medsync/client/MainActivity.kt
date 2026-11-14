package com.medsync.client

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.medsync.client.app.MedSyncApp
import com.medsync.client.ui.App

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val controller = MedSyncApp.init(androidDatabaseBuilder(this), ANDROID_EMULATOR_GATEWAY)
        setContent { App(controller) }
    }
}
