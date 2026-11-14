package com.medsync.client.data

import androidx.room.ConstructedBy
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import androidx.room.RoomDatabaseConstructor
import androidx.room.Update
import androidx.room.Upsert
import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.IO
import kotlinx.coroutines.flow.Flow

/**
 * One planned step. The row (with its step_key) is written before anything is sent, in the same transaction as the
 * rest of its plan, so an app kill between "planned" and "sent" can never lose or duplicate a step.
 * JSON columns are stored as text to keep the schema identical on Android, iOS and desktop.
 */
@Entity(
    tableName = "action_outbox",
    indices = [Index(value = ["stepKey"], unique = true), Index("planId"), Index("state")],
)
data class ActionEntity(
    @PrimaryKey val actionId: String,
    val planId: String,
    val stepIndex: Int,
    val stepKey: String,
    val tool: String,
    val toolClass: String,
    val identityArgsJson: String,
    val payloadJson: String,
    val preconditionsJson: String,
    /** Comma-separated actionIds this step waits for (a DAG within its plan). */
    val dependsOn: String,
    val createdAtMs: Long,
    val expiresAtMs: Long?,
    val state: String,
    val attempt: Int = 0,
    val nextRetryAtMs: Long = 0,
    val reason: String? = null,
    val resultJson: String? = null,
) {
    val parents: List<String> get() = dependsOn.split(',').filter { it.isNotBlank() }
}

@Entity(tableName = "kv")
data class KvEntity(@PrimaryKey val key: String, val value: String)

@Dao
interface ActionDao {
    @Query("SELECT * FROM action_outbox ORDER BY createdAtMs, stepIndex")
    fun observeAll(): Flow<List<ActionEntity>>

    @Query("SELECT * FROM action_outbox ORDER BY createdAtMs, stepIndex")
    suspend fun all(): List<ActionEntity>

    /** A whole plan is inserted in one call, i.e. one transaction. */
    @Insert
    suspend fun insertAll(actions: List<ActionEntity>)

    @Update
    suspend fun update(action: ActionEntity)

    @Query("DELETE FROM action_outbox WHERE state IN ('DONE', 'CANCELLED') AND createdAtMs < :before")
    suspend fun prune(before: Long)
}

@Dao
interface KvDao {
    @Query("SELECT value FROM kv WHERE `key` = :key")
    suspend fun get(key: String): String?

    @Upsert
    suspend fun put(entry: KvEntity)
}

@Database(entities = [ActionEntity::class, KvEntity::class], version = 1)
@ConstructedBy(MedSyncDatabaseConstructor::class)
abstract class MedSyncDatabase : RoomDatabase() {
    abstract fun actions(): ActionDao
    abstract fun kv(): KvDao
}

// Room's KSP processor generates the `actual` for every platform.
@Suppress("KotlinNoActualForExpect")
expect object MedSyncDatabaseConstructor : RoomDatabaseConstructor<MedSyncDatabase> {
    override fun initialize(): MedSyncDatabase
}

fun buildDatabase(builder: RoomDatabase.Builder<MedSyncDatabase>): MedSyncDatabase = builder
    .setDriver(BundledSQLiteDriver())
    .setQueryCoroutineContext(Dispatchers.IO)
    .build()
