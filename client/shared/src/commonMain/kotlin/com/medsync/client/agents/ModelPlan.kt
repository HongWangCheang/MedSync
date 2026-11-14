package com.medsync.client.agents

import com.medsync.client.outbox.StepDraft
import kotlinx.datetime.LocalDate
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Turns a model's tool calls into a plan. Platform-independent: the model (LiteRT-LM on Android / desktop, Swift on
 * iOS) only has to understand the sentence; everything a small model is bad at happens here, deterministically:
 *
 * - one intent at a time: a statement is split into clauses and each clause is routed on its own (a 0.6B model
 *   reliably makes one or two tool calls, not four); a sentence that asks something is routed whole
 * - dates: parsed from the user's own text by [RuleRouter.date]; the model never does calendar arithmetic
 * - grounding: a drug, symptom, relative or department must appear in the user's words, or it is dropped (or, for
 *   the department, inferred by the rules) instead of guessed
 * - negation: "还没吃降压药" records nothing; "没有头疼" is not a symptom
 * - names: departments, symptoms and relatives are mapped onto the app's vocabulary; quantities are stripped from
 *   drug names ("两片泰诺" → "泰诺"); "A和B" becomes two records
 * - structure: the same dependencies as [RuleRouter] (bookings and messages wait for the symptom record; messages
 *   also wait for medication records, so the safety review is on the server's board first)
 */
object ModelPlan {
    /** One tool call, and the clause it was made for (grounding is checked against that clause). */
    data class Call(val name: String, val arguments: Map<String, Any?>, val source: String = "")

    val TOOL_NAMES = listOf("record_medication", "record_symptom", "book_appointment", "notify_family", "ask_pharmacist")

    private val departments = mapOf(
        "消化内科" to listOf("消化内科", "消化科", "肠胃科", "胃肠科"),
        "心血管内科" to listOf("心血管内科", "心内科", "心血管科", "心脏科"),
        "神经内科" to listOf("神经内科", "神经科"),
        "呼吸内科" to listOf("呼吸内科", "呼吸科"),
        "内分泌科" to listOf("内分泌科", "内分泌"),
        "皮肤科" to listOf("皮肤科", "皮肤"),
        "耳鼻喉科" to listOf("耳鼻喉科", "耳鼻喉"),
        "骨科" to listOf("骨科"), "眼科" to listOf("眼科"), "全科" to listOf("全科", "普通门诊"),
    )
    private val symptoms = mapOf(
        "头晕" to listOf("头晕", "头昏", "晕"), "头痛" to listOf("头痛", "头疼"),
        "胃痛" to listOf("胃痛", "胃疼", "胃不舒服"), "腹痛" to listOf("腹痛", "肚子疼", "肚子痛"),
        "恶心" to listOf("恶心", "想吐", "反胃", "呕吐"), "发热" to listOf("发热", "发烧"), "咳嗽" to listOf("咳嗽", "咳"),
        "胸闷" to listOf("胸闷", "胸口闷"), "乏力" to listOf("乏力", "没劲", "没力气", "无力"), "失眠" to listOf("失眠", "睡不着"),
        "腹泻" to listOf("腹泻", "拉肚子"), "皮疹" to listOf("皮疹", "疹子", "红疹", "起疹"),
        "心悸" to listOf("心悸", "心慌", "心跳快", "心跳很快"), "咽痛" to listOf("咽痛", "嗓子疼", "喉咙痛", "嗓子痛", "喉咙疼"),
        "腰痛" to listOf("腰痛", "腰疼"), "关节痛" to listOf("关节痛", "关节疼"), "肌肉痛" to listOf("肌肉痛", "肌肉疼", "肌肉酸痛"),
        "出血" to listOf("出血", "流血"),
    )
    private val relatives = mapOf(
        "妈妈" to listOf("妈妈", "我妈", "老妈", "母亲"), "爸爸" to listOf("爸爸", "我爸", "老爸", "父亲"),
        "老婆" to listOf("老婆", "妻子", "媳妇"), "老公" to listOf("老公", "丈夫"),
    )
    private val drugSeparators = Regex("""和|、|跟|以及|及|还有|，|,""")
    private val negated = Regex("""^(没有|没|不)(?!舒服|适)""")  // not 无: "无力" is a symptom
    private val notTaken = Regex("""(没|没有|还没|忘了|忘|不想|别|不)(吃|服)""")
    private val clauseBreaks = Regex("""[，,。；;！!]+""")  // not spaces: "吃了 Tylenol" is one clause
    private val notADrug = Regex("""吃|服|药了|^[\d.]+|\d+度""")  // "已经吃药了", "38度5"
    private val questionMarks = listOf("吗", "？", "?", "能不能", "可不可以", "怎么", "多少", "多久", "几片", "几次", "什么",
        "哪些", "是否", "为什么", "要不要", "会不会", "有没有", "how", "what", "can i", "should")

    fun isQuestion(text: String): Boolean = text.lowercase().let { t -> questionMarks.any { it in t } }

    /**
     * Routes [text] with [model] (one call per clause, see the class comment) and turns the calls into a plan.
     * [model] returns the raw tool calls for one piece of text.
     */
    suspend fun plan(text: String, today: LocalDate, nowMs: Long,
                     model: suspend (String) -> List<Call>): RuleRouter.Routed {
        val clauses = text.split(clauseBreaks).map { it.trim() }.filter { it.length >= 2 }
        val calls = if (isQuestion(text) || clauses.size <= 1) model(text).map { it.copy(source = text) }
            else clauses.flatMap { clause -> model(clause).map { it.copy(source = clause) } }
        return toRouted(calls, text, today, nowMs)
    }

    private fun grounded(value: String, source: String, table: Map<String, List<String>>? = null): Boolean {
        if (value.isEmpty()) return false
        if (value.lowercase() in source.lowercase()) return true
        val synonyms = table?.get(canon(value, table)) ?: return false
        return synonyms.any { it in source }
    }
    // Kinship terms are a closed vocabulary: read them from the text, like dates, rather than trusting the model's copy.
    private val kin = listOf("女儿", "儿子", "老伴", "妈妈", "我妈", "老妈", "母亲", "爸爸", "我爸", "老爸", "父亲", "老婆", "妻子",
        "媳妇", "老公", "丈夫", "姐姐", "哥哥", "弟弟", "妹妹", "孙子", "孙女", "外孙", "家人")
    private val quantity = Regex("""^(?:[\d一二两三四五六七八九十半几]+\s*[片粒颗包支袋勺]|[片粒颗包支袋]|点)""")

    private fun canon(value: String, table: Map<String, List<String>>): String =
        table.entries.firstOrNull { (name, synonyms) -> value == name || synonyms.any { it in value } }?.key ?: value

    fun department(value: String): String = canon(value, departments)
    fun symptom(value: String): String = canon(value, symptoms)
    fun relative(value: String): String = canon(value.removePrefix("给"), relatives)  // keep 我: "我妈" → 妈妈
    fun drug(value: String): String = quantity.replace(value.trim(), "").trim()

    private fun Map<String, Any?>.text(key: String): String = (this[key] as? String)?.trim().orEmpty()

    fun toRouted(calls: List<Call>, text: String, today: LocalDate, nowMs: Long): RuleRouter.Routed {
        val steps = mutableListOf<StepDraft>()
        val medications = mutableListOf<Int>()
        var symptom: Int? = null
        val later = mutableListOf<Call>()  // bookings and messages go after the records they depend on
        val seen = mutableSetOf<String>()
        fun addSymptom(raw: String, source: String) {
            if (negated.containsMatchIn(raw) || !grounded(raw, source, symptoms)) return  // "没有头疼"; "腰疼" → 头痛
            val category = symptom(raw)
            if (category.isEmpty() || !seen.add("sym:$category")) return
            if (symptom == null) symptom = steps.size
            steps += StepDraft("record_symptom", buildJsonObject {
                put("category", category); put("severity", "moderate"); put("recordedAt", nowMs); put("note", text)
            })
        }
        for (call in calls.filter { it.name in TOOL_NAMES }) {
            val a = call.arguments
            val source = call.source.ifEmpty { text }
            when (call.name) {
                "record_medication" -> {
                    if (notTaken.containsMatchIn(source)) continue  // "今天还没吃降压药", "布洛芬我没吃"
                    // A small model sometimes puts "A和B" into one call: one record per drug.
                    for (part in a.text("name").split(drugSeparators)) {
                        val name = drug(part)
                        if (symptom(name) != name) { addSymptom(name, source); continue }  // "肌肉疼" is not a drug
                        if (notADrug.containsMatchIn(name) || !grounded(name, source) || !seen.add("med:$name")) continue
                        medications += steps.size
                        steps += StepDraft("record_medication", buildJsonObject {
                            put("name", name); put("takenAt", nowMs); put("note", text)
                        })
                    }
                }
                "record_symptom" -> addSymptom(a.text("symptom").ifEmpty { a.text("category") }, source)
                "book_appointment", "notify_family", "ask_pharmacist" -> later += call
            }
        }
        val after = listOfNotNull(symptom)
        for (call in later) {
            val a = call.arguments
            when (call.name) {
                "book_appointment" -> if (seen.add("book")) {
                    val named = a.text("department")
                    steps += StepDraft("book_appointment", buildJsonObject {
                        put("patient_id", "self")
                        // Only a department the user actually named; otherwise the rules infer one from symptoms.
                        put("department", if (grounded(named, text, departments)) department(named)
                            else RuleRouter.department(text))
                        put("date", RuleRouter.date(text, today).toString())  // parsed from the user's words
                        put("note", text)
                    }, dependsOn = after)
                }
                "notify_family" -> {
                    val said = a.text("to").takeIf { grounded(it, text, relatives) }
                        ?: kin.firstOrNull { it in text } ?: continue
                    val to = relative(said)
                    if (!seen.add("notify:$to")) continue
                    steps += StepDraft("notify_family", buildJsonObject {
                        put("to", to); put("message", text)
                    }, dependsOn = (medications + after).sorted())
                }
                "ask_pharmacist" -> if (isQuestion(text) && seen.add("ask")) {
                    steps += StepDraft("ask_pharmacist", buildJsonObject { put("question", text) },
                        preconditions = mapOf("needsEvidence" to JsonPrimitive(true)))
                }
            }
        }
        // A question that asks for no booking or message is a question for the pharmacist, whatever else the model
        // extracted: "吃了泰诺还能吃感冒灵吗" must not record 感冒灵.
        if (isQuestion(text) && steps.none { it.tool == "book_appointment" || it.tool == "notify_family" }) {
            return RuleRouter.Routed(listOf(StepDraft("ask_pharmacist", buildJsonObject { put("question", text) },
                preconditions = mapOf("needsEvidence" to JsonPrimitive(true)))), question = true)
        }
        return RuleRouter.Routed(steps, question = steps.singleOrNull()?.tool == "ask_pharmacist")
    }
}
