package com.medsync.client

import androidx.compose.ui.graphics.toAwtImage
import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.SemanticsNodeInteractionsProvider
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.isToggleable
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.runDesktopComposeUiTest
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.DesktopComposeUiTest
import androidx.room.Room
import com.medsync.client.agents.FallbackRouter
import com.medsync.client.agents.RedFlagDetector
import com.medsync.client.agents.RedFlagScreen
import com.medsync.client.agents.OnDeviceRouter
import com.medsync.client.agents.RuleBasedRouter
import com.medsync.client.app.MedSyncController
import com.medsync.client.data.MedSyncDatabase
import com.medsync.client.data.buildDatabase
import com.medsync.client.ui.App
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.net.HttpURLConnection
import java.net.URI
import javax.imageio.ImageIO

/**
 * Drives the real desktop UI (same App composable, real controller, Room and Ktor) against the running Compose
 * stack, clicking and typing like a user and saving a screenshot after each step to desktopApp/build/walkthrough.
 *
 *     docker compose up -d && cd client && MEDSYNC_WALKTHROUGH=1 ./gradlew :desktopApp:test
 */
@OptIn(ExperimentalTestApi::class)
class WalkthroughTest {
    private val gateway = System.getenv("MEDSYNC_GATEWAY") ?: DESKTOP_GATEWAY
    private val mocks = System.getenv("MEDSYNC_MOCKS") ?: "http://127.0.0.1:9100"
    private val out = File("build/walkthrough").apply { mkdirs() }

    private fun controller(router: OnDeviceRouter = RuleBasedRouter,
                           redFlags: RedFlagScreen = RedFlagScreen()): MedSyncController {
        val file = File.createTempFile("walkthrough", ".db").apply { delete(); deleteOnExit() }
        val db = buildDatabase(Room.databaseBuilder<MedSyncDatabase>(name = file.absolutePath))
        return MedSyncController(db, gateway, CoroutineScope(SupervisorJob() + Dispatchers.Default), router = router,
            redFlags = redFlags)
    }

    private fun post(url: String, body: String = "{}") {
        val c = URI(url).toURL().openConnection() as HttpURLConnection
        c.requestMethod = "POST"; c.doOutput = true; c.setRequestProperty("Content-Type", "application/json")
        c.outputStream.use { it.write(body.toByteArray()) }
        check(c.responseCode in 200..299) { "$url → HTTP ${c.responseCode}" }
    }

    private fun DesktopComposeUiTest.shot(name: String) {
        waitForIdle()
        ImageIO.write(onRoot().captureToImage().toAwtImage(), "png", File(out, "$name.png"))
    }

    private fun DesktopComposeUiTest.waitForText(text: String, timeoutMs: Long = 30_000) =
        waitUntil(timeoutMillis = timeoutMs) { onAllNodesWithText(text, substring = true).fetchSemanticsNodes().isNotEmpty() }

    private fun DesktopComposeUiTest.say(text: String) {
        onNode(hasSetTextAction()).performTextInput(text)
        onNodeWithText("发送").performClick()
    }

    private fun SemanticsNodeInteractionsProvider.toggleOffline() = onNode(isToggleable()).performClick()

    @Test
    fun offlineBookingWhoseSlotIsTakenIsRescheduled() = runDesktopComposeUiTest(width = 760, height = 1100) {
        assumeTrue(System.getenv("MEDSYNC_WALKTHROUGH") == "1")
        post("$mocks/admin/reset")
        val app = controller()
        setContent { App(app) }

        toggleOffline()
        say("明天帮我约复诊")
        waitForText("已保存在本机")
        shot("1-offline-queued")

        // While the phone is offline, someone else takes the last slot for tomorrow.
        val tomorrow = java.time.LocalDate.now().plusDays(1)
        post("$mocks/admin/slots/$tomorrow", """{"available": 0}""")

        toggleOffline()
        waitForText("原定日期号源已满")
        assertTrue(onAllNodesWithText("已保存在本机", substring = true).fetchSemanticsNodes().isEmpty())
        shot("2-online-slot-taken")
        val chosen = tomorrow.plusDays(1).toString()
        onNodeWithText("改约 $chosen").performClick()
        waitForText("已完成")
        // The card shows the date actually booked, not the one planned offline.
        onNodeWithText("全科 · $chosen").assertExists()
        shot("3-rescheduled")
    }

    @Test
    fun onDeviceModelPlansACompoundSentence() = runDesktopComposeUiTest(width = 760, height = 1100) {
        assumeTrue(System.getenv("MEDSYNC_WALKTHROUGH") == "1")
        val model = LiteRtRouter()
        assumeTrue("model file missing", model.available)
        post("$mocks/admin/reset")
        kotlinx.coroutines.runBlocking { model.warmUp() }  // as main() does at startup; loading takes ~7 s
        val router = FallbackRouter(model)
        val app = controller(router)
        setContent { App(app) }

        toggleOffline()  // the model runs on the device: no network needed to plan
        say("吃了二甲双胍和降压药，有点乏力，告诉儿子")
        waitForText("已保存在本机", timeoutMs = 60_000)
        shot("9-on-device-model-plan")
        assertTrue("answered by ${router.lastSource}: ${router.lastFailure}", router.lastSource == model.name)
        // Two medication records (the rules only ever catch the first drug), a symptom, a message.
        onNodeWithText("药物：二甲双胍").assertExists()
        onNodeWithText("药物：降压药").assertExists()
        onNodeWithText("症状：乏力", substring = true).assertExists()
        onNodeWithText("发给儿子", substring = true).assertExists()
        model.close()
    }

    @Test
    fun onDeviceModelCatchesADangerSignTheRulesMiss() = runDesktopComposeUiTest(width = 760, height = 900) {
        assumeTrue(System.getenv("MEDSYNC_WALKTHROUGH") == "1")
        val model = LiteRtRouter()
        assumeTrue("model file missing", model.available)
        val redFlag = LiteRtRedFlag(model)
        kotlinx.coroutines.runBlocking { model.warmUp(); redFlag.warmUp() }
        val screen = RedFlagScreen(redFlag)
        val app = controller(FallbackRouter(model), screen)
        setContent { App(app) }

        toggleOffline()
        // Not in the eval set, and no rule keyword in it (no 胸痛, no 呼吸困难).
        val text = "胸口像被人攥住一样，出了一身冷汗"
        assertTrue(RedFlagDetector.detect(text) == null)
        say(text)
        waitForText("可能是危险信号", timeoutMs = 60_000)
        onNodeWithText("拨打 120", substring = true).assertExists()
        onNodeWithText("由本机模型判断", substring = true).assertExists()
        // The alert comes before routing; let routing finish too (it records the symptom) before the model closes.
        waitUntil(timeoutMillis = 60_000) { onAllNodesWithText("本机模型理解中", substring = true).fetchSemanticsNodes().isEmpty() }
        shot("10-model-red-flag")
        model.close()
    }

    @Test
    fun aPairWithNoLabelsIsNotShownAsCompared() = runDesktopComposeUiTest(width = 760, height = 900) {
        // Found by the blind test. Every single-ingredient drug in the table now has a label; two Chinese combination
        // products still have none, so only their shared ingredient (pseudoephedrine) can be checked.
        assumeTrue(System.getenv("MEDSYNC_WALKTHROUGH") == "1")
        val app = controller()
        setContent { App(app) }
        say("我吃了新康泰克")
        waitForText("无需对照")
        say("我吃了白加黑")
        waitForText("没有说明书可查（只核对了是否含相同成分）：新康泰克")
        onNodeWithText("有需要马上留意的提醒", substring = true).assertExists()  // same ingredient within a day
        assertTrue(onAllNodesWithText("已对照：新康泰克", substring = true).fetchSemanticsNodes().isEmpty())
        shot("11-no-label-pair")
    }

    @Test
    fun safetyAlertAndConflictPause() = runDesktopComposeUiTest(width = 760, height = 1400) {
        assumeTrue(System.getenv("MEDSYNC_WALKTHROUGH") == "1")
        post("$mocks/admin/reset")
        val app = controller()
        setContent { App(app) }

        say("我吃了华法林")
        waitForText("安全审核")
        onNodeWithText("无需对照", substring = true).assertExists()  // nothing to compare is not "no warning found"
        shot("4-first-record")

        toggleOffline()
        say("我吃了布洛芬，告诉女儿我没事")
        waitForText("已保存在本机")
        shot("5-offline-two-steps")

        toggleOffline()
        waitForText("已暂停", timeoutMs = 60_000)
        // The user's own word for the drug, with the label it was read from (on the alert and on the pause). Either
        // label may be cited: ibuprofen's names anticoagulants, warfarin's (prescription snapshot) lists NSAIDs.
        assertTrue(onAllNodesWithText("（参照", substring = true).fetchSemanticsNodes().size >= 2)
        onNodeWithText("照原样发送").assertExists()
        shot("6-alert-and-paused-message")

        onAllNodesWithText("点开看原文", substring = true)[0].performClick()  // both labels are cited now
        shot("7-excerpt-open")

        onNodeWithText("附上提醒再发").performClick()
        waitUntil(timeoutMillis = 30_000) { onAllNodesWithText("需要你确认").fetchSemanticsNodes().isEmpty() }
        // The card shows the message as sent, warning included.
        onNodeWithText("MedSync 用药提醒", substring = true).assertExists()
        shot("8-sent-with-note")
    }
}
