package com.medsync.client.outbox

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okio.ByteString.Companion.encodeUtf8

/**
 * The logical identity of a planned step, generated on the device at planning time and written to the outbox before
 * anything is sent. Every hop (gateway ledger, agent thread, tool ledger) keys on it, so retries, app restarts and
 * LLM re-planning all collapse onto one side effect.
 */
object StepKey {
    fun of(deviceId: String, planId: String, stepIndex: Int, tool: String, identityArgs: JsonObject): String =
        "$deviceId|$planId|$stepIndex|$tool|${canonical(identityArgs)}".encodeUtf8().sha256().hex()

    /** JSON with object keys sorted at every level, so field order never changes the key. */
    fun canonical(element: JsonElement): String = when (element) {
        is JsonObject -> element.entries.sortedBy { it.key }
            .joinToString(",", "{", "}") { (key, value) -> "${JsonPrimitive(key)}:${canonical(value)}" }
        is JsonArray -> element.joinToString(",", "[", "]") { canonical(it) }
        is JsonPrimitive -> element.toString()
        JsonNull -> "null"
    }

    fun identityArgs(tool: ToolSpec, payload: JsonObject): JsonObject =
        JsonObject(payload.filterKeys { it in tool.identityFields })
}
