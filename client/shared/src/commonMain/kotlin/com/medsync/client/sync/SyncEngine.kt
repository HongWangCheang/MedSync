package com.medsync.client.sync

import com.medsync.client.data.ActionDao
import com.medsync.client.data.ActionEntity
import com.medsync.client.outbox.ActionEvent
import com.medsync.client.outbox.ActionState
import com.medsync.client.outbox.ActionStateMachine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonObject
import kotlin.math.min
import kotlin.random.Random

data class DrainReport(val sent: Int, val done: Int, val waiting: Int, val needsUser: Int)

/**
 * Drains the outbox over hop ①. Platform schedulers only decide WHEN to call [drainOnce]: Android WorkManager,
 * iOS BGTaskScheduler / foreground timer, desktop coroutine loop. The logic is shared and unit-tested once.
 *
 * Rows are visited in plan order, which is a topological order (dependencies only point backwards), so a parent
 * that finishes in this pass unblocks its children in the same pass.
 */
class SyncEngine(
    private val dao: ActionDao,
    private val api: GatewayApi,
    private val random: Random = Random.Default,
) {
    private val mutex = Mutex()

    suspend fun drainOnce(nowMs: Long): DrainReport = mutex.withLock {
        val rows = dao.all()
        val states = rows.associate { it.actionId to ActionState.valueOf(it.state) }.toMutableMap()
        var sent = 0
        for (original in rows) {
            var action = original
            var state = states.getValue(action.actionId)
            if (state.terminal) continue

            val parents = action.parents.map { states[it] ?: ActionState.DONE }
            if (parents.any { it == ActionState.FAILED || it == ActionState.CANCELLED }) {
                if (state != ActionState.NEEDS_USER) {
                    action = save(action, ActionEvent.ParentFailed, reason = "parent_not_done")
                    states[action.actionId] = ActionState.valueOf(action.state)
                }
                continue
            }
            if (state == ActionState.BLOCKED) {
                if (parents.any { it != ActionState.DONE }) continue
                action = save(action, ActionEvent.ParentDone)
                state = ActionState.PENDING
            }
            if (state == ActionState.RETRY_WAIT) {
                if (action.nextRetryAtMs > nowMs) continue
                action = save(action, ActionEvent.RetryDue)
                state = ActionState.PENDING
            }
            val result = when (state) {
                ActionState.PENDING -> {
                    action = save(action, ActionEvent.Send)
                    sent++
                    api.submit(action)
                }
                ActionState.ACKED -> api.status(action.stepKey)
                else -> continue  // NEEDS_USER waits for resolve(); SENDING only exists inside this pass
            }
            action = apply(action, result, nowMs)
            states[action.actionId] = ActionState.valueOf(action.state)
        }
        val final = states.values
        DrainReport(
            sent = sent,
            done = final.count { it == ActionState.DONE },
            waiting = final.count { !it.terminal && it != ActionState.NEEDS_USER },
            needsUser = final.count { it == ActionState.NEEDS_USER },
        )
    }

    /** The user answered a NEEDS_USER card (choose another date / confirm / cancel). Needs the network. */
    suspend fun resolve(action: ActionEntity, decision: JsonObject, nowMs: Long): ActionEntity = mutex.withLock {
        apply(action, api.resume(action.stepKey, decision), nowMs)
    }

    private suspend fun apply(action: ActionEntity, result: SubmitResult, nowMs: Long): ActionEntity = when (result) {
        is SubmitResult.Done -> save(action, ActionEvent.Done, resultJson = result.result?.toString(), reason = null)
        SubmitResult.Accepted -> save(action, ActionEvent.Accepted)
        is SubmitResult.NeedsUser ->
            save(action, ActionEvent.NeedsUser, reason = result.reason, resultJson = result.result?.toString())
        is SubmitResult.Failed -> save(action, ActionEvent.Failed, reason = result.reason)
        is SubmitResult.Cancelled -> save(action, ActionEvent.Cancelled, reason = result.reason)
        SubmitResult.Conflict -> save(action, ActionEvent.Failed, reason = "step_key reused for different content")
        is SubmitResult.Transient -> {
            if (ActionState.valueOf(action.state) == ActionState.NEEDS_USER) {
                action.copy(reason = "offline: answer will be sent when online").also { dao.update(it) }
            } else {
                val next = ActionStateMachine.next(ActionState.valueOf(action.state), ActionEvent.TransientError)
                action.copy(state = next.name, attempt = action.attempt + 1, reason = result.message,
                    nextRetryAtMs = nowMs + backoffMs(action.attempt, random)).also { dao.update(it) }
            }
        }
    }

    private suspend fun save(action: ActionEntity, event: ActionEvent, reason: String? = action.reason,
                             resultJson: String? = action.resultJson): ActionEntity {
        val next = ActionStateMachine.next(ActionState.valueOf(action.state), event)
        return action.copy(state = next.name, reason = reason, resultJson = resultJson).also { dao.update(it) }
    }

    companion object {
        /** 2 s, 4 s, 8 s … capped at 5 min, ±20 % jitter so a fleet of phones coming back online doesn't stampede. */
        fun backoffMs(attempt: Int, random: Random): Long {
            val base = min(2_000L shl min(attempt, 20), 300_000L)
            return (base * (0.8 + 0.4 * random.nextDouble())).toLong()
        }
    }
}
