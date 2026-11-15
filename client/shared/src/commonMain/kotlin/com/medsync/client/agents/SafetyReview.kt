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
 * `checked` / `noLabel` / `unresolved` / `notRecent` say what the review actually covered, so "no alert" is never
 * shown as "safe": a name the server could not recognise is listed as not checked, and a pair for which neither
 * label is in the snapshot is listed as such, not as compared.
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
    /** Recognised, but neither this drug's label nor the new one's is in the snapshot: only shared ingredients checked. */
    val noLabel: List<String> = emptyList(),
) {
    val high: Boolean get() = alerts.any { it.high }

    /** The card's title: what happened, never more than the review covered. */
    val headline: String get() = when {
        status == "skipped" -> "安全审核未执行（${skippedReason ?: "未知原因"}）"
        status == "unresolved_medication" -> "安全审核：没认出「$medication」，没有检查"
        high -> "安全审核：有需要马上留意的提醒"
        alerts.isNotEmpty() -> "安全审核：有用药提醒"
        checked.isEmpty() && noLabel.isEmpty() && unresolved.isEmpty() -> "安全审核：最近一周没有其他服药记录，无需对照"
        checked.isEmpty() && noLabel.isNotEmpty() -> "安全审核：没有可查的说明书，只核对了是否含相同成分"
        else -> "安全审核：说明书里没有找到相关提醒"
    }

    /** What was and was not compared, one clause each. */
    val coverage: List<String> get() = buildList {
        if (checked.isNotEmpty()) add("已对照：${checked.joinToString("、")}")
        if (noLabel.isNotEmpty()) add("没有说明书可查（只核对了是否含相同成分）：${noLabel.joinToString("、")}")
        if (unresolved.isNotEmpty()) add("没认出、未检查：${unresolved.joinToString("、")}")
        if (notRecent.isNotEmpty()) add("一周前的记录未对照：${notRecent.joinToString("、")}")
    }

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
                noLabel = safety.array("no_label").mapNotNull { (it as? JsonObject)?.str("name") },
            )
        }.getOrNull()

        private fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.contentOrNull
        private fun JsonObject.array(key: String): JsonArray = (this[key] as? JsonArray) ?: JsonArray(emptyList())
    }
}
