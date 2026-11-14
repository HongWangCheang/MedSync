package com.medsync.client

import androidx.compose.ui.window.ComposeUIViewController
import androidx.room.Room
import androidx.room.RoomDatabase
import com.medsync.client.app.MedSyncApp
import com.medsync.client.data.MedSyncDatabase
import com.medsync.client.ui.App
import kotlinx.cinterop.ExperimentalForeignApi
import platform.Foundation.NSDocumentDirectory
import platform.Foundation.NSFileManager
import platform.Foundation.NSUserDomainMask
import platform.UIKit.UIViewController

/** The iOS simulator shares the Mac's network, so localhost reaches Toxiproxy hop ①. */
const val IOS_SIMULATOR_GATEWAY = "http://127.0.0.1:18081"

@OptIn(ExperimentalForeignApi::class)
fun iosDatabaseBuilder(): RoomDatabase.Builder<MedSyncDatabase> {
    val documents = NSFileManager.defaultManager.URLForDirectory(
        directory = NSDocumentDirectory, inDomain = NSUserDomainMask, appropriateForURL = null, create = true,
        error = null,
    )
    return Room.databaseBuilder<MedSyncDatabase>(name = requireNotNull(documents?.path) + "/medsync.db")
}

/** Called from Swift (ContentView.swift). */
fun MainViewController(): UIViewController = ComposeUIViewController {
    App(MedSyncApp.init(iosDatabaseBuilder(), IOS_SIMULATOR_GATEWAY))
}
