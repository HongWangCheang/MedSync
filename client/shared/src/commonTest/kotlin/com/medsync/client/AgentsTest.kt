package com.medsync.client

import com.medsync.client.agents.RedFlagDetector
import com.medsync.client.agents.RuleRouter
import kotlinx.datetime.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class AgentsTest {
    private val saturday = LocalDate(2026, 11, 14)
    private val monday = LocalDate(2026, 11, 16)

    @Test
    fun compoundSentenceBecomesADag() {
        val routed = RuleRouter.route("我吃了布洛芬，有点胃疼，帮我约周三复诊，顺便告诉我女儿", saturday, 0)
        assertEquals(listOf("record_medication", "record_symptom", "book_appointment", "notify_family"),
            routed.steps.map { it.tool })
        assertEquals("\"布洛芬\"", routed.steps[0].payload["name"].toString())
        assertEquals("\"消化内科\"", routed.steps[2].payload["department"].toString())
        assertEquals("\"2026-11-18\"", routed.steps[2].payload["date"].toString())
        assertEquals(listOf(1), routed.steps[2].dependsOn)
        assertEquals(listOf(1), routed.steps[3].dependsOn)
    }

    @Test
    fun questionsRouteToThePharmacistOnly() {
        val routed = RuleRouter.route("布洛芬能和阿司匹林一起吃吗？", saturday, 0)
        assertTrue(routed.question)
        assertEquals(listOf("ask_pharmacist"), routed.steps.map { it.tool })
    }

    @Test
    fun relativeDates() {
        assertEquals(LocalDate(2026, 11, 18), RuleRouter.date("周三", saturday))
        assertEquals(LocalDate(2026, 11, 18), RuleRouter.date("周三", monday))
        assertEquals(LocalDate(2026, 11, 25), RuleRouter.date("下周三", monday))
        assertEquals(LocalDate(2026, 11, 15), RuleRouter.date("明天", saturday))
        assertEquals(LocalDate(2026, 11, 20), RuleRouter.date("11月20号", saturday))
        assertEquals(LocalDate(2027, 1, 5), RuleRouter.date("1月5日", saturday))
    }

    @Test
    fun redFlagsRespectNegationAndPrioritiseCrisis() {
        assertEquals("胸口痛", RedFlagDetector.detect("突然胸口痛得厉害")?.matched)
        assertNull(RedFlagDetector.detect("今天没有胸痛，只是有点胃疼"))
        val crisis = assertNotNull(RedFlagDetector.detect("吃了一整瓶药，不想活了"))
        assertTrue("12356" in crisis.advice)
    }
}
