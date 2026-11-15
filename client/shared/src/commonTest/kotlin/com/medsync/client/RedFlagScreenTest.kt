package com.medsync.client

import com.medsync.client.agents.RedFlagDetector
import com.medsync.client.agents.RedFlagKind
import com.medsync.client.agents.RedFlagModel
import com.medsync.client.agents.RedFlagOpinion
import com.medsync.client.agents.RedFlagScreen
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** The guards on the model's second opinion, with a scripted "model" so no model file is needed. */
class RedFlagScreenTest {
    private class Script(private val answers: Map<String, RedFlagOpinion?>) : RedFlagModel {
        override val name = "script"
        val asked = mutableListOf<String>()
        override suspend fun assess(text: String): RedFlagOpinion? { asked += text; return answers[text] }
    }

    private fun emergency(evidence: String) = RedFlagOpinion(RedFlagKind.EMERGENCY, evidence)

    @Test
    fun rulesAnswerFirstAndTheModelIsNotAsked() = runTest {
        val model = Script(emptyMap())
        val flag = assertNotNull(RedFlagScreen(model).detect("突然胸痛"))
        assertEquals("rules", flag.source)
        assertTrue(model.asked.isEmpty())
    }

    @Test
    fun theModelAddsWhatTheRulesMissWithTheUsersOwnWords() = runTest {
        val text = "心口像压了块大石头，还出冷汗"
        assertNull(RedFlagDetector.detect(text))
        val flag = assertNotNull(RedFlagScreen(Script(mapOf(text to emergency("心口像压了块大石头")))).detect(text))
        assertEquals("心口像压了块大石头", flag.matched)
        assertEquals("script", flag.source)
        assertEquals(RedFlagDetector.EMERGENCY, flag.advice)
        val crisis = "活不下去了"
        val hotline = assertNotNull(RedFlagScreen(Script(mapOf(crisis to RedFlagOpinion(RedFlagKind.CRISIS, crisis))))
            .detect(crisis))
        assertEquals(RedFlagDetector.CRISIS, hotline.advice)
    }

    @Test
    fun evidenceMustBeInTheSentenceAndNotNegated() {
        // Not in the user's words: the model made it up.
        assertNull(RedFlagScreen.accept("吓死我了，原来是猫", emergency("想死"), "m"))
        // Negated in the user's words.
        assertNull(RedFlagScreen.accept("今天没有心口压着的感觉", emergency("心口压着"), "m"))
        // Punctuation changed and phrases joined: the first phrase really in the sentence is kept.
        assertEquals("憋气", RedFlagScreen.accept("憋气，嘴唇都发紫了", emergency("憋气,嘴唇都发紫了"), "m")?.matched)
        // One character says nothing.
        assertNull(RedFlagScreen.accept("头晕", emergency("晕"), "m"))
    }

    @Test
    fun everydayExaggerationIsNotAnAlarmButIntentIs() {
        assertNull(RedFlagScreen.accept("笑死我了", RedFlagOpinion(RedFlagKind.CRISIS, "笑死我了"), "m"))
        assertNull(RedFlagScreen.accept("这道题要我命", RedFlagOpinion(RedFlagKind.CRISIS, "要我命"), "m"))
        assertNotNull(RedFlagScreen.accept("这样活着还不如死了算了",
            RedFlagOpinion(RedFlagKind.CRISIS, "还不如死了算了"), "m"))
    }

    @Test
    fun takingADrugIsARecordUnlessThereIsTooMuchOrASymptom() {
        assertNull(RedFlagScreen.accept("我吃了华法林", emergency("吃了华法林"), "m"))
        assertNull(RedFlagScreen.accept("刚吃了两片泰诺", emergency("吃了两片泰诺"), "m"))
        assertNotNull(RedFlagScreen.accept("不小心多吃了五片安眠药", emergency("多吃了五片安眠药"), "m"))
        assertNotNull(RedFlagScreen.accept("把一个星期的降压药一次全吃了", emergency("一次全吃了"), "m"))
        assertNotNull(RedFlagScreen.accept("吃了药以后嗓子发紧", emergency("吃了药以后嗓子发紧"), "m"))
    }

    @Test
    fun aMissingSlowOrBrokenModelLeavesTheRulesAnswer() = runTest {
        val broken = object : RedFlagModel {
            override val name = "broken"
            override suspend fun assess(text: String): RedFlagOpinion? = error("boom")
        }
        val slow = object : RedFlagModel {
            override val name = "slow"
            override suspend fun assess(text: String): RedFlagOpinion? { delay(60_000); return emergency(text) }
        }
        for (model in listOf(broken, slow)) {
            val screen = RedFlagScreen(model, timeoutMs = 1_000)
            assertNull(screen.detect("心口像压了块大石头"))
            assertNotNull(screen.lastFailure)
            assertEquals("胸痛", screen.detect("突然胸痛")?.matched)  // the rules still answer
        }
        assertNull(RedFlagScreen().detect("心口像压了块大石头"))  // no model: rules only
    }
}
