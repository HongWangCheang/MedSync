package com.medsync.client.agents

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject

/** One reason behind an alert, with the label text it rests on. */
data class SafetyFinding(val summary: String, val label: String, val section: String, val excerpt: String, val url: String?)

data class SafetyAlert(val with: String, val high: Boolean, val findings: List<SafetyFinding>)

/**
 * The safety review attached to a synced medication record (server: services/rag/safety_review.py).
 * `checked` / `unresolved` / `notRecent` say what the review actually covered, so "no alert" is never shown as
 * "safe": a name the server could not recognise is listed as not checked.
 */
data class SafetyReview(
    val status: String,
    val medication: String,
    val alerts: List<SafetyAlert>,
    val checked: List<String>,
    val unresolved: List<String>,
    val notRecent: List<String>,
    val note: String?,
    val skippedReason: String? = null,
) {
    val high: Boolean get() = alerts.any { it.high }

    /** What to ask the pharmacist about an alert; routed like any typed question (RuleRouter → ask_pharmacist). */
    fun question(alert: SafetyAlert): String = "我在用${alert.with}，现在加上${medication}，这两个能一起用吗？"

    companion object {
        fun parse(resultJson: String?): SafetyReview? = runCatching {
            val safety = Json.parseToJsonElement(resultJson!!).jsonObject["safety"] as? JsonObject ?: return null
            val status = safety.str("status") ?: return null
            val medication = (safety["medication"] as? JsonObject)?.str("name") ?: ""
            val alerts = safety.array("alerts").map { element ->
                val a = element.jsonObject
                SafetyAlert(a.str("with") ?: "", a.str("severity") == "high", a.array("findings").map { f ->
                    val finding = f.jsonObject
                    val c = finding["citation"] as? JsonObject ?: JsonObject(emptyMap())
                    SafetyFinding(finding.str("summary") ?: "", c.str("label") ?: "",
                        c.str("section_zh") ?: c.str("section") ?: "", c.str("excerpt") ?: "", c.str("source_url"))
                })
            }
            SafetyReview(
                status, medication, alerts,
                checked = safety.array("checked").mapNotNull { (it as? JsonObject)?.str("name") },
                unresolved = safety.array("unresolved").mapNotNull { (it as? JsonPrimitive)?.contentOrNull },
                notRecent = safety.array("not_recent").mapNotNull { (it as? JsonPrimitive)?.contentOrNull },
                note = safety.str("note"),
                skippedReason = safety.str("reason"),
            )
        }.getOrNull()

        private fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.contentOrNull
        private fun JsonObject.array(key: String): JsonArray = (this[key] as? JsonArray) ?: JsonArray(emptyList())
    }
}
