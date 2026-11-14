package com.medsync.client

import androidx.room.Room
import androidx.room.RoomDatabase
import com.medsync.client.data.MedSyncDatabase
import java.io.File

const val DESKTOP_GATEWAY = "http://127.0.0.1:18081"

/** macOS / Windows / Linux: ~/.medsync/medsync.db */
fun desktopDatabaseBuilder(): RoomDatabase.Builder<MedSyncDatabase> {
    val dir = File(System.getProperty("user.home"), ".medsync").apply { mkdirs() }
    return Room.databaseBuilder<MedSyncDatabase>(name = File(dir, "medsync.db").absolutePath)
}
