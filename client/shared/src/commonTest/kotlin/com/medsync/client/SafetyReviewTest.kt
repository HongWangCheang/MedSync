package com.medsync.client

import com.medsync.client.agents.RuleRouter
import com.medsync.client.agents.SafetyReview
import kotlinx.datetime.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class SafetyReviewTest {
    private val result = """
        {"tool": "record_medication", "accepted": true, "safety": {
          "status": "ok", "medication": {"name": "布洛芬", "ingredients": ["ibuprofen"], "label": "ADVIL"},
          "checked": [{"name": "华法林", "ingredients": ["warfarin"], "label": null}],
          "unresolved": ["某草药"], "not_recent": [], "severity": "moderate",
          "alerts": [{"with": "华法林", "severity": "moderate", "kinds": ["label_warning"], "findings": [
            {"summary": "ADVIL 的说明书在「警告」里提到了抗凝药（华法林）。",
             "citation": {"label": "ADVIL", "section": "Warnings", "section_zh": "警告",
                          "excerpt": "take a blood thinning (anticoagulant) or steroid drug",
                          "source_url": "https://api.fda.gov/drug/label.json?x"}}]}],
          "note": "只根据说明书原文判断"}}
    """.trimIndent()

    @Test
    fun parsesAlertsCitationsAndCoverage() {
        val review = SafetyReview.parse(result)!!
        assertEquals("布洛芬", review.medication)
        assertFalse(review.high)
        val finding = review.alerts.single().findings.single()
        assertEquals("警告", finding.section)
        assertTrue("anticoagulant" in finding.excerpt)
        assertEquals(listOf("华法林"), review.checked)
        assertEquals(listOf("某草药"), review.unresolved)  // shown as "not checked", never as safe
    }

    @Test
    fun recordsWithoutAReviewAndSkippedReviewsParse() {
        assertNull(SafetyReview.parse("""{"tool": "record_medication", "accepted": true}"""))
        val skipped = SafetyReview.parse(
            """{"safety": {"status": "skipped", "reason": "no_medication_access"}}""")!!
        assertEquals("no_medication_access", skipped.skippedReason)
        assertTrue(skipped.alerts.isEmpty())
    }

    @Test
    fun askPharmacistQuestionIsAQuestionNotANewRecord() {
        val review = SafetyReview.parse(result)!!
        val routed = RuleRouter.route(review.question(review.alerts.single()), LocalDate(2026, 11, 14), 0L)
        assertEquals(listOf("ask_pharmacist"), routed.steps.map { it.tool })
    }
}
