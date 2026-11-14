package com.medsync.client

import com.medsync.client.data.ActionDao
import com.medsync.client.data.ActionEntity
import com.medsync.client.outbox.Planner
import com.medsync.client.outbox.StepDraft
import com.medsync.client.sync.GatewayApi
import com.medsync.client.sync.SubmitResult
import com.medsync.client.sync.SyncEngine
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

internal class FakeDao : ActionDao {
    val rows = MutableStateFlow<List<ActionEntity>>(emptyList())
    override fun observeAll(): Flow<List<ActionEntity>> = rows
    override suspend fun all() = rows.value
    override suspend fun insertAll(actions: List<ActionEntity>) { rows.value = rows.value + actions }
    override suspend fun update(action: ActionEntity) {
        rows.value = rows.value.map { if (it.actionId == action.actionId) action else it }
    }
    override suspend fun prune(before: Long) {}
    fun state(tool: String) = rows.value.single { it.tool == tool }.state
}

private class FakeApi(var next: (ActionEntity) -> SubmitResult = { SubmitResult.Done(null) }) : GatewayApi {
    val submitted = mutableListOf<String>()
    var status: SubmitResult = SubmitResult.Done(null)
    override suspend fun submit(action: ActionEntity): SubmitResult = next(action).also { submitted += action.stepKey }
    override suspend fun status(stepKey: String) = status
    override suspend fun resume(stepKey: String, decision: JsonObject) = SubmitResult.Done(null)
}

class SyncEngineTest {
    private val symptom = StepDraft("record_symptom", buildJsonObject { put("category", "胃疼"); put("recordedAt", 1L) })
    private val booking = StepDraft("book_appointment", buildJsonObject {
        put("patient_id", "self"); put("department", "消化内科"); put("date", "2026-11-18")
    }, dependsOn = listOf(0))

    private suspend fun setup(api: FakeApi): Pair<FakeDao, SyncEngine> {
        val dao = FakeDao()
        dao.insertAll(Planner.plan(listOf(symptom, booking), "dev", 0))
        return dao to SyncEngine(dao, api, Random(1))
    }

    @Test
    fun parentFinishingUnblocksChildInTheSamePass() = runTest {
        val api = FakeApi()
        val (dao, engine) = setup(api)
        val report = engine.drainOnce(0)
        assertEquals(2, report.done)
        assertEquals(2, api.submitted.size)
        assertEquals("DONE", dao.state("book_appointment"))
    }

    @Test
    fun transientErrorRetriesLaterWithTheSameStepKey() = runTest {
        var offline = true
        val api = FakeApi { if (offline) SubmitResult.Transient("timeout") else SubmitResult.Done(null) }
        val (dao, engine) = setup(api)

        engine.drainOnce(0)
        assertEquals("RETRY_WAIT", dao.state("record_symptom"))
        assertEquals("BLOCKED", dao.state("book_appointment"))
        engine.drainOnce(1)  // backoff not due yet: nothing is sent
        assertEquals(1, api.submitted.size)

        offline = false
        engine.drainOnce(60_000)
        assertEquals("DONE", dao.state("book_appointment"))
        assertEquals(api.submitted[0], api.submitted[1])  // same logical step, same key on retry
    }

    @Test
    fun failedParentSendsChildToTheUserInsteadOfRunningIt() = runTest {
        val api = FakeApi { if (it.tool == "record_symptom") SubmitResult.Failed("rejected") else SubmitResult.Done(null) }
        val (dao, engine) = setup(api)
        engine.drainOnce(0)
        assertEquals("NEEDS_USER", dao.state("book_appointment"))
        assertEquals(1, api.submitted.size)
    }

    @Test
    fun acceptedStepIsPolledUntilDone() = runTest {
        val api = FakeApi { SubmitResult.Accepted }
        val (dao, engine) = setup(api)
        engine.drainOnce(0)
        assertEquals("ACKED", dao.state("record_symptom"))
        api.status = SubmitResult.Done(null)
        engine.drainOnce(1)
        assertEquals("DONE", dao.state("record_symptom"))
    }

    @Test
    fun backoffGrowsAndIsCapped() {
        val r = Random(7)
        val first = SyncEngine.backoffMs(0, r)
        assertTrue(first in 1_600L..2_400L)
        assertTrue(SyncEngine.backoffMs(30, r) <= 360_000L)
    }
}
