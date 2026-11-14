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

    private fun controller(): MedSyncController {
        val file = File.createTempFile("walkthrough", ".db").apply { delete(); deleteOnExit() }
        val db = buildDatabase(Room.databaseBuilder<MedSyncDatabase>(name = file.absolutePath))
        return MedSyncController(db, gateway, CoroutineScope(SupervisorJob() + Dispatchers.Default))
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
        // The user's own word for the drug, with the label it was read from (on the alert and on the pause).
        assertTrue(onAllNodesWithText("布洛芬（参照", substring = true).fetchSemanticsNodes().size >= 2)
        onNodeWithText("照原样发送").assertExists()
        shot("6-alert-and-paused-message")

        onNodeWithText("点开看原文", substring = true).performClick()
        shot("7-excerpt-open")

        onNodeWithText("附上提醒再发").performClick()
        waitUntil(timeoutMillis = 30_000) { onAllNodesWithText("需要你确认").fetchSemanticsNodes().isEmpty() }
        // The card shows the message as sent, warning included.
        onNodeWithText("MedSync 用药提醒", substring = true).assertExists()
        shot("8-sent-with-note")
    }
}
