package com.medsync.client.outbox

import com.medsync.client.data.ActionEntity
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlin.uuid.Uuid

/** One step as proposed by a router (rules today, the on-device model in phase 2). */
data class StepDraft(
    val tool: String,
    val payload: JsonObject,
    /** Indices of earlier steps in the same plan that must be DONE first. */
    val dependsOn: List<Int> = emptyList(),
    val preconditions: Map<String, JsonPrimitive> = emptyMap(),
)

object Planner {
    /**
     * Turns drafts into outbox rows with step keys. Pure: the caller inserts the returned list in one transaction.
     * Dependencies may only point backwards, which makes plan order a valid topological order.
     */
    fun plan(drafts: List<StepDraft>, deviceId: String, nowMs: Long, planId: String = Uuid.random().toString()):
        List<ActionEntity> {
        val ids = drafts.map { Uuid.random().toString() }
        return drafts.mapIndexed { index, draft ->
            require(draft.dependsOn.all { it in 0 until index }) { "step $index depends on a later or unknown step" }
            val spec = Tools[draft.tool]
            val identity = StepKey.identityArgs(spec, draft.payload)
            val preconditions = JsonObject(draft.preconditions + ("toolVersion" to JsonPrimitive(spec.version)))
            ActionEntity(
                actionId = ids[index],
                planId = planId,
                stepIndex = index,
                stepKey = StepKey.of(deviceId, planId, index, spec.name, identity),
                tool = spec.name,
                toolClass = spec.toolClass.name,
                identityArgsJson = StepKey.canonical(identity),
                payloadJson = StepKey.canonical(draft.payload),
                preconditionsJson = StepKey.canonical(preconditions),
                dependsOn = draft.dependsOn.joinToString(",") { ids[it] },
                createdAtMs = nowMs,
                expiresAtMs = spec.ttlMs?.let { nowMs + it },
                state = (if (draft.dependsOn.isEmpty()) ActionState.PENDING else ActionState.BLOCKED).name,
            )
        }
    }
}
