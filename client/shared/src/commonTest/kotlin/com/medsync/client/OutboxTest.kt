package com.medsync.client

import com.medsync.client.outbox.ActionEvent
import com.medsync.client.outbox.ActionState
import com.medsync.client.outbox.ActionStateMachine
import com.medsync.client.outbox.IllegalTransition
import com.medsync.client.outbox.Planner
import com.medsync.client.outbox.StepDraft
import com.medsync.client.outbox.StepKey
import com.medsync.client.outbox.Tools
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

class OutboxTest {
    private val booking = buildJsonObject {
        put("patient_id", "self"); put("department", "消化内科"); put("date", "2026-11-18"); put("note", "胃疼")
    }

    @Test
    fun stepKeyIgnoresFieldOrderAndFreeText() {
        val spec = Tools["book_appointment"]
        val reordered = buildJsonObject {
            put("note", "LLM re-planned: stomach ache"); put("date", "2026-11-18"); put("department", "消化内科")
            put("patient_id", "self")
        }
        val a = StepKey.of("dev", "plan", 0, spec.name, StepKey.identityArgs(spec, booking))
        val b = StepKey.of("dev", "plan", 0, spec.name, StepKey.identityArgs(spec, reordered))
        assertEquals(a, b)
        assertEquals(64, a.length)
    }

    @Test
    fun stepKeyChangesWithIdentityOrPosition() {
        val spec = Tools["book_appointment"]
        val base = StepKey.of("dev", "plan", 0, spec.name, StepKey.identityArgs(spec, booking))
        val otherDay = buildJsonObject { booking.forEach { (k, v) -> put(k, v) }; put("date", "2026-11-19") }
        assertNotEquals(base, StepKey.of("dev", "plan", 0, spec.name, StepKey.identityArgs(spec, otherDay)))
        assertNotEquals(base, StepKey.of("dev", "plan", 1, spec.name, StepKey.identityArgs(spec, booking)))
    }

    @Test
    fun plannerBlocksDependentStepsAndSetsTtl() {
        val symptom = buildJsonObject { put("category", "胃疼"); put("recordedAt", 1L) }
        val notify = buildJsonObject { put("to", "女儿"); put("message", "胃疼") }
        val rows = Planner.plan(
            listOf(StepDraft("record_symptom", symptom), StepDraft("notify_family", notify, dependsOn = listOf(0))),
            deviceId = "dev", nowMs = 1_000,
        )
        assertEquals(listOf("PENDING", "BLOCKED"), rows.map { it.state })
        assertEquals(listOf(rows[0].actionId), rows[1].parents)
        assertEquals(1_000 + 6 * 3_600_000L, rows[1].expiresAtMs)
        assertTrue(rows.all { it.preconditionsJson.contains("\"toolVersion\":\"v1\"") })
    }

    @Test
    fun plannerRejectsForwardDependencies() {
        assertFailsWith<IllegalArgumentException> {
            Planner.plan(listOf(StepDraft("book_appointment", booking, dependsOn = listOf(1))), "dev", 0)
        }
    }

    @Test
    fun terminalStatesNeverMove() {
        for (state in listOf(ActionState.DONE, ActionState.FAILED, ActionState.CANCELLED)) {
            assertFailsWith<IllegalTransition> { ActionStateMachine.next(state, ActionEvent.Send) }
        }
        assertEquals(ActionState.PENDING, ActionStateMachine.next(ActionState.NEEDS_USER, ActionEvent.UserConfirmed))
        assertEquals(ActionState.ACKED, ActionStateMachine.next(ActionState.ACKED, ActionEvent.TransientError))
    }
}
