package com.medsync.client

import android.app.Application
import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.medsync.client.app.MedSyncApp
import java.util.concurrent.TimeUnit

class MedSyncApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        MedSyncApp.init(androidDatabaseBuilder(this), ANDROID_EMULATOR_GATEWAY)
        // Foreground: the shared 10 s loop. Background: WorkManager, only when there is a network.
        val request = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(this)
            .enqueueUniquePeriodicWork("medsync-outbox", ExistingPeriodicWorkPolicy.KEEP, request)
    }
}

class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val controller = MedSyncApp.controller
            ?: MedSyncApp.init(androidDatabaseBuilder(applicationContext), ANDROID_EMULATOR_GATEWAY)
        val report = controller.engine.drainOnce(System.currentTimeMillis())
        return if (report.waiting > 0) Result.retry() else Result.success()
    }
}
