package com.medsync.client.agents

import com.medsync.client.outbox.StepDraft
import kotlinx.datetime.DatePeriod
import kotlinx.datetime.LocalDate
import kotlinx.datetime.isoDayNumber
import kotlinx.datetime.plus
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Phase-1 router: deterministic Chinese rules that turn one utterance into a small plan (a DAG of steps).
 * Phase 2 swaps in an on-device model (LiteRT-LM) behind the same output type, and this class stays as the fallback
 * and as the baseline the model has to beat on the routing eval set.
 */
object RuleRouter {
    private val stops = listOf("，", ",", "。", "；", ";", "！", "!", "？", "?", " ", "然后", "有点", "帮我", "顺便", "还", "和", "后")
    private val takeVerbs = listOf("吃了", "服用了", "服了", "吃过")
    private val symptoms = listOf("头晕", "头疼", "头痛", "胃疼", "胃痛", "肚子疼", "恶心", "发烧", "咳嗽", "胸闷",
        "乏力", "失眠", "腹泻", "皮疹", "心慌")
    private val relatives = listOf("女儿", "儿子", "老伴", "妈妈", "爸爸", "家人", "老婆", "老公")
    private val weekdays = mapOf('一' to 1, '二' to 2, '三' to 3, '四' to 4, '五' to 5, '六' to 6, '日' to 7, '天' to 7)

    data class Routed(val steps: List<StepDraft>, val question: Boolean)

    fun route(text: String, today: LocalDate, nowMs: Long): Routed {
        val steps = mutableListOf<StepDraft>()
        var symptomIndex: Int? = null
        var medicationIndex: Int? = null

        medication(text)?.let { name ->
            medicationIndex = steps.size
            steps += StepDraft("record_medication", buildJsonObject {
                put("name", name); put("takenAt", nowMs); put("note", text)
            })
        }
        symptoms.firstOrNull { it in text }?.let { category ->
            val severity = when {
                listOf("很", "特别", "严重", "剧烈").any { it in text } -> "severe"
                "有点" in text || "有些" in text -> "mild"
                else -> "moderate"
            }
            symptomIndex = steps.size
            steps += StepDraft("record_symptom", buildJsonObject {
                put("category", category); put("severity", severity); put("recordedAt", nowMs); put("note", text)
            })
        }
        val after = listOfNotNull(symptomIndex)
        if (listOf("约", "挂号", "复诊", "预约").any { it in text }) {
            steps += StepDraft("book_appointment", buildJsonObject {
                put("patient_id", "self")
                put("department", department(text))
                put("date", date(text, today).toString())
                put("note", text)
            }, dependsOn = after)
        }
        val relative = relatives.firstOrNull { it in text }
        if (relative != null && listOf("告诉", "通知", "跟", "说一声").any { it in text }) {
            // The message also waits for the medication record: the server's safety review of that record has to
            // be on the findings board before the message is checked against it (agent conflicts.py).
            steps += StepDraft("notify_family", buildJsonObject {
                put("to", relative); put("message", text)
            }, dependsOn = (listOfNotNull(medicationIndex) + after).sorted())
        }
        val asks = listOf("能不能", "可不可以", "能一起", "一起吃", "副作用", "怎么吃", "吃多少", "吗", "？", "?")
            .any { it in text }
        if (steps.isEmpty() && asks) {
            steps += StepDraft("ask_pharmacist", buildJsonObject { put("question", text) },
                preconditions = mapOf("needsEvidence" to JsonPrimitive(true)))
        }
        return Routed(steps, question = steps.singleOrNull()?.tool == "ask_pharmacist")
    }

    internal fun medication(text: String): String? {
        val verb = takeVerbs.firstOrNull { it in text } ?: return null
        val rest = text.substringAfter(verb)
        val end = stops.map { rest.indexOf(it) }.filter { it >= 0 }.minOrNull() ?: rest.length
        // Rules only catch the first drug in "吃了A和B"; the phase-2 model should do better on the eval set.
        return rest.substring(0, end).removeSuffix("药").trim().ifBlank { "未注明药物" }
    }

    internal fun department(text: String): String = when {
        "胃" in text || "肚子" in text || "腹泻" in text -> "消化内科"
        "胸" in text || "心" in text -> "心血管内科"
        "头" in text || "失眠" in text -> "神经内科"
        "咳" in text || "发烧" in text -> "呼吸内科"
        else -> "全科"
    }

    /** 今天/明天/后天/大后天、(下)周X/星期X/礼拜X、M月D日; defaults to tomorrow. */
    internal fun date(text: String, today: LocalDate): LocalDate {
        Regex("""(\d{1,2})月(\d{1,2})[日号]""").find(text)?.let { m ->
            val (month, day) = m.destructured
            val candidate = LocalDate(today.year, month.toInt(), day.toInt())
            return if (candidate < today) LocalDate(today.year + 1, month.toInt(), day.toInt()) else candidate
        }
        when {
            "大后天" in text -> return today.plus(DatePeriod(days = 3))
            "后天" in text -> return today.plus(DatePeriod(days = 2))
            "明天" in text -> return today.plus(DatePeriod(days = 1))
            "今天" in text -> return today
        }
        // (?<!一): "约一下周二" is this coming Tuesday, not next week's.
        Regex("""(?<!一)(下)?(?:周|星期|礼拜)([一二三四五六日天])""").find(text)?.let { m ->
            val target = weekdays.getValue(m.groupValues[2][0])
            var days = (target - today.dayOfWeek.isoDayNumber + 7) % 7
            if (days == 0) days = 7
            if (m.groupValues[1].isNotEmpty() && days <= 7 - today.dayOfWeek.isoDayNumber) days += 7
            return today.plus(DatePeriod(days = days))
        }
        return today.plus(DatePeriod(days = 1))
    }
}
