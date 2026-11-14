package com.medsync.client

import android.content.Context
import androidx.room.Room
import androidx.room.RoomDatabase
import com.medsync.client.data.MedSyncDatabase

/** The Android emulator reaches the host's Toxiproxy hop ① at 10.0.2.2. On a real phone use the computer's LAN IP. */
const val ANDROID_EMULATOR_GATEWAY = "http://10.0.2.2:18081"

fun androidDatabaseBuilder(context: Context): RoomDatabase.Builder<MedSyncDatabase> {
    val app = context.applicationContext
    return Room.databaseBuilder<MedSyncDatabase>(context = app, name = app.getDatabasePath("medsync.db").absolutePath)
}
