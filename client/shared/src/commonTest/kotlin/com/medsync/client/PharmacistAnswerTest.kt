package com.medsync.client

import com.medsync.client.agents.PharmacistAnswer
import com.medsync.client.outbox.Planner
import com.medsync.client.outbox.StepDraft
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class PharmacistAnswerTest {
    private val json = """
        {"answer": "服用阿司匹林时，使用前应先询问医生或药师 [S1]。另见 [S1, S2]。", "grounded": true,
         "refusal_reason": null, "tools": ["check_interaction"],
         "citations": [{"id": "S1", "label": "Advil", "section": "Ask a doctor", "excerpt": "taking aspirin…",
                        "source_url": "https://api.fda.gov/x"},
                       {"id": "S2", "label": "Advil", "section": "Warnings", "excerpt": "stomach bleeding…",
                        "source_url": null}]}
    """.trimIndent()

    @Test
    fun parsesAnswerAndCitations() {
        val answer = PharmacistAnswer.parse(json)!!
        assertTrue(answer.grounded)
        assertEquals(listOf("S1", "S2"), answer.citations.map { it.id })
        assertNull(answer.citations[1].url)
    }

    @Test
    fun citationMarkersAreSplitOutForHighlighting() {
        val marked = PharmacistAnswer.parse(json)!!.segments().filter { it.second }.map { it.first }
        assertEquals(listOf("[S1]", "[S1, S2]"), marked)
    }

    @Test
    fun nonPharmacistResultsAndGarbageParseToNull() {
        assertNull(PharmacistAnswer.parse("""{"tool": "record_symptom", "accepted": true}"""))
        assertNull(PharmacistAnswer.parse("not json"))
        assertNull(PharmacistAnswer.parse(null))
    }

    private fun answered(createdAtMs: Long, result: String) =
        Planner.plan(listOf(StepDraft("ask_pharmacist", buildJsonObject { put("question", "布洛芬能和阿司匹林一起吃吗？") })),
            "dev", createdAtMs).single().copy(state = "DONE", resultJson = result)

    @Test
    fun followUpContinuesARecentConversationOnly() {
        val waiting = """{"answer": "请问您指的是哪一种？", "grounded": true, "citations": [],
            "session_id": "11111111-2222-3333-4444-555555555555", "awaiting_choice": true}"""
        val follow = PharmacistAnswer.followUp(listOf(answered(1_000, waiting)), nowMs = 60_000)!!
        assertTrue(follow.awaitingChoice)
        assertEquals("11111111-2222-3333-4444-555555555555", follow.sessionId)
        assertNull(PharmacistAnswer.followUp(listOf(answered(1_000, waiting)), nowMs = 1_000 + 11 * 60_000))
        assertNull(PharmacistAnswer.followUp(listOf(answered(1_000, """{"answer": "x", "grounded": true}""")), 2_000))
    }
}
