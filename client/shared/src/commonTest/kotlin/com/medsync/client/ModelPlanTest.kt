package com.medsync.client

import com.medsync.client.agents.FallbackRouter
import com.medsync.client.agents.ModelPlan
import com.medsync.client.agents.ModelPlan.Call
import com.medsync.client.agents.ModelRouter
import com.medsync.client.agents.RuleRouter
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.runTest
import kotlinx.datetime.LocalDate
import kotlinx.serialization.json.JsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** ModelPlan's guards, with a scripted "model" so no model file is needed. */
class ModelPlanTest {
    private val monday = LocalDate(2026, 11, 16)

    /** Answers per piece of text it is asked about; records what it was asked. */
    private class Script(private val answers: Map<String, List<Call>>) {
        val asked = mutableListOf<String>()
        suspend fun call(text: String): List<Call> { asked += text; return answers[text].orEmpty() }
    }

    private suspend fun plan(text: String, vararg answers: Pair<String, List<Call>>): Pair<RuleRouter.Routed, Script> {
        val script = Script(answers.toMap())
        return ModelPlan.plan(text, monday, 0L, script::call) to script
    }

    private fun RuleRouter.Routed.tools() = steps.map { it.tool }
    private fun RuleRouter.Routed.arg(index: Int, key: String) = (steps[index].payload[key] as JsonPrimitive).content

    @Test
    fun statementsAreRoutedClauseByClauseAndMerged() = runTest {
        val (routed, script) = plan("我吃了布洛芬，有点胃疼，帮我约周三消化科，告诉女儿",
            "我吃了布洛芬" to listOf(Call("record_medication", mapOf("name" to "布洛芬"))),
            "有点胃疼" to listOf(Call("record_symptom", mapOf("symptom" to "胃疼"))),
            "帮我约周三消化科" to listOf(Call("book_appointment", mapOf("department" to "消化科"))),
            "告诉女儿" to listOf(Call("notify_family", mapOf("to" to "女儿"))))
        assertEquals(4, script.asked.size)
        assertEquals(listOf("record_medication", "record_symptom", "book_appointment", "notify_family"), routed.tools())
        assertEquals("胃痛", routed.arg(1, "category"))
        assertEquals("消化内科", routed.arg(2, "department"))
        assertEquals("2026-11-18", routed.arg(2, "date"))  // from the user's words, not the model
        assertEquals(listOf(1), routed.steps[2].dependsOn)
        assertEquals(listOf(0, 1), routed.steps[3].dependsOn)
    }

    @Test
    fun questionsAreRoutedWholeAndNeverRecordAnything() = runTest {
        val (routed, script) = plan("吃了泰诺还能吃感冒灵吗",
            "吃了泰诺还能吃感冒灵吗" to listOf(Call("record_medication", mapOf("name" to "感冒灵"))))
        assertEquals(listOf("吃了泰诺还能吃感冒灵吗"), script.asked)
        assertEquals(listOf("ask_pharmacist"), routed.tools())
        assertTrue(routed.question)
        // A booking phrased as a question is still a booking.
        val (booking, _) = plan("能帮我约明天的心内科吗",
            "能帮我约明天的心内科吗" to listOf(Call("book_appointment", mapOf("department" to "心内科"))))
        assertEquals(listOf("book_appointment"), booking.tools())
        assertEquals("2026-11-17", booking.arg(0, "date"))
    }

    @Test
    fun ungroundedArgumentsAreDroppedNotGuessed() = runTest {
        // "腰疼" → the model said 头痛: not in the user's words, so nothing is recorded.
        assertEquals(emptyList(), plan("腰疼", "腰疼" to listOf(Call("record_symptom", mapOf("symptom" to "头痛")))).first.tools())
        // A department the user never named is inferred by the rules instead.
        val (booking, _) = plan("我头晕，帮我挂明天的号",
            "我头晕" to listOf(Call("record_symptom", mapOf("symptom" to "头晕"))),
            "帮我挂明天的号" to listOf(Call("book_appointment", mapOf("department" to "心血管内科"))))
        assertEquals("神经内科", booking.arg(1, "department"))
        // The relative is read from the text when the model copies the wrong one.
        val (notify, _) = plan("告诉老公我到医院了",
            "告诉老公我到医院了" to listOf(Call("notify_family", mapOf("to" to "老伴"))))
        assertEquals("老公", notify.arg(0, "to"))
        val (mom, _) = plan("给我妈发个消息说我很好",
            "给我妈发个消息说我很好" to listOf(Call("notify_family", mapOf("to" to "我妈"))))
        assertEquals("妈妈", mom.arg(0, "to"))
    }

    @Test
    fun negationsAndNonDrugsAreNotRecorded() = runTest {
        assertEquals(emptyList(), plan("今天还没吃降压药",
            "今天还没吃降压药" to listOf(Call("record_medication", mapOf("name" to "降压药")))).first.tools())
        assertEquals(emptyList(), plan("没有头疼也没有发烧",
            "没有头疼也没有发烧" to listOf(Call("record_symptom", mapOf("symptom" to "没有头疼")))).first.tools())
        val (fever, _) = plan("发烧了，38度5",
            "发烧了" to listOf(Call("record_symptom", mapOf("symptom" to "发烧"))),
            "38度5" to listOf(Call("record_medication", mapOf("name" to "38度5"))))
        assertEquals(listOf("record_symptom"), fever.tools())
        // "吃了布洛芬没用" is not a negation of taking it.
        val (useless, _) = plan("吃了布洛芬没用",
            "吃了布洛芬没用" to listOf(Call("record_medication", mapOf("name" to "布洛芬"))))
        assertEquals(listOf("record_medication"), useless.tools())
    }

    @Test
    fun aBodyPartAloneIsReadWithWhatTheUserSaysAboutIt() = runTest {
        // Seen in the demo: "胸口像被人攥住一样" was recorded as the symptom "胸口".
        val (squeezed, _) = plan("胸口像被人攥住一样", "胸口像被人攥住一样" to listOf(Call("record_symptom", mapOf("symptom" to "胸口"))))
        assertEquals("胸闷", squeezed.arg(0, "category"))
        val (aching, _) = plan("心口疼", "心口疼" to listOf(Call("record_symptom", mapOf("symptom" to "心口"))))
        assertEquals("胸痛", aching.arg(0, "category"))
        // The description can come first: "拉肚子" (the model says "肚子").
        val (runs, _) = plan("拉肚子", "拉肚子" to listOf(Call("record_symptom", mapOf("symptom" to "肚子"))))
        assertEquals("腹泻", runs.arg(0, "category"))
        // Nothing recognisable said about it: no symptom rather than one called "胸口".
        assertEquals(emptyList(), plan("胸口那里贴了膏药",
            "胸口那里贴了膏药" to listOf(Call("record_symptom", mapOf("symptom" to "胸口")))).first.tools())
    }

    @Test
    fun oneCallWithTwoDrugsBecomesTwoRecords() = runTest {
        val (routed, _) = plan("吃了两片泰诺和奥美拉唑",
            "吃了两片泰诺和奥美拉唑" to listOf(Call("record_medication", mapOf("name" to "两片泰诺和奥美拉唑"))))
        assertEquals(listOf("泰诺", "奥美拉唑"), routed.steps.map { (it.payload["name"] as JsonPrimitive).content })
    }

    @Test
    fun fallsBackToRulesWhenTheModelFailsOrIsTooSlow() = runTest {
        val broken = object : ModelRouter {
            override val name = "broken"
            override suspend fun tryRoute(text: String, today: LocalDate, nowMs: Long): RuleRouter.Routed? = error("boom")
        }
        val slow = object : ModelRouter {
            override val name = "slow"
            override suspend fun tryRoute(text: String, today: LocalDate, nowMs: Long): RuleRouter.Routed? {
                delay(60_000); return null
            }
        }
        for (model in listOf(broken, slow)) {
            val router = FallbackRouter(model, timeoutMs = 1_000)
            assertEquals(listOf("record_medication"), router.route("我吃了布洛芬", monday, 0L).steps.map { it.tool })
            assertEquals("rules", router.lastSource)
        }
    }

    @Test
    fun dateParserReadsYiXiaAsThisWeek() {
        assertEquals(LocalDate(2026, 11, 17), RuleRouter.date("约一下周二复诊", monday))
        assertEquals(LocalDate(2026, 11, 24), RuleRouter.date("约下周二复诊", monday))
    }
}
