package com.medsync.client.agents

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject

/** One label passage the answer cites, e.g. [S1] → Advil, "Ask a doctor or pharmacist before use if you are". */
data class Citation(val id: String, val label: String, val section: String, val excerpt: String, val url: String?)

/** A product the pharmacist could not choose between; label id + version make the user's pick exact. */
data class Choice(val labelId: String, val version: String, val name: String, val manufacturer: String?) {
    /** Two labels can share a name ("Tylenol Extra Strength"), so the button also shows maker and version. */
    val title: String get() = listOfNotNull(name, manufacturer?.takeIf { it.isNotBlank() }, "版本 $version")
        .joinToString(" · ")
}

/**
 * The pharmacist step's result as stored in the outbox row. `grounded == false` means the server replaced the
 * model's text with a refusal because it could not be tied to retrieved label passages.
 */
data class PharmacistAnswer(
    val text: String,
    val grounded: Boolean,
    val citations: List<Citation>,
    /** RAG conversation to continue, so "ADVIL" or "它能和酒一起吃吗" is understood in context. */
    val sessionId: String? = null,
    /** The pharmacist asked which product the user means; the next reply should continue this conversation. */
    val awaitingChoice: Boolean = false,
    val choices: List<Choice> = emptyList(),
) {
    /** Splits the answer into plain text and citation markers so the UI can highlight "[S1]". */
    fun segments(): List<Pair<String, Boolean>> {
        val out = mutableListOf<Pair<String, Boolean>>()
        var last = 0
        for (match in CITATION.findAll(text)) {
            if (match.range.first > last) out += text.substring(last, match.range.first) to false
            out += match.value to true
            last = match.range.last + 1
        }
        if (last < text.length) out += text.substring(last) to false
        return out
    }

    companion object {
        private val CITATION = Regex("""\[\s*S\d{1,4}(?:\s*[,;]\s*S\d{1,4})*\s*]""")

        fun parse(resultJson: String?): PharmacistAnswer? = runCatching {
            val root = Json.parseToJsonElement(resultJson!!).jsonObject
            val text = root.str("answer") ?: return null
            val citations = root["citations"]?.jsonArray.orEmpty().map { element ->
                val c = element.jsonObject
                Citation(c.str("id") ?: "?", c.str("label") ?: "", c.str("section") ?: "", c.str("excerpt") ?: "",
                    c.str("source_url"))
            }
            val choices = root["choices"]?.jsonArray.orEmpty().mapNotNull { element ->
                val c = element.jsonObject
                val id = c.str("label_id") ?: return@mapNotNull null
                val version = c.str("version") ?: return@mapNotNull null
                Choice(id, version, c.str("name") ?: id, c.str("manufacturer"))
            }
            PharmacistAnswer(text, (root["grounded"] as? JsonPrimitive)?.booleanOrNull == true, citations,
                root.str("session_id"), (root["awaiting_choice"] as? JsonPrimitive)?.booleanOrNull == true, choices)
        }.getOrNull()

        private const val FOLLOW_UP_WINDOW_MS = 10 * 60_000L

        /** The follow-up step sent when the user taps a candidate: same conversation, exact product. */
        fun choiceStep(choice: Choice, sessionId: String?): com.medsync.client.outbox.StepDraft =
            com.medsync.client.outbox.StepDraft("ask_pharmacist", JsonObject(buildMap {
                put("question", JsonPrimitive("我选：${choice.title}"))
                sessionId?.let { put("session_id", JsonPrimitive(it)) }
                put("selection", JsonObject(mapOf("label_id" to JsonPrimitive(choice.labelId),
                    "version" to JsonPrimitive(choice.version))))
            }))

        /**
         * The pharmacist conversation a new message should continue: the latest answered question, if it is recent.
         * Returns null when there is none, so an unrelated question starts fresh.
         */
        fun followUp(rows: List<com.medsync.client.data.ActionEntity>, nowMs: Long): PharmacistAnswer? = rows
            .filter { it.tool == "ask_pharmacist" && it.state == "DONE" && nowMs - it.createdAtMs <= FOLLOW_UP_WINDOW_MS }
            .maxByOrNull { it.createdAtMs }
            ?.let { parse(it.resultJson) }
            ?.takeIf { it.sessionId != null }

        private fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.contentOrNull
    }
}
