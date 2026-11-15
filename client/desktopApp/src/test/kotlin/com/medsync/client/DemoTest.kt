package com.medsync.client

import androidx.compose.ui.graphics.toAwtImage
import androidx.compose.ui.test.DesktopComposeUiTest
import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.isToggleable
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.runDesktopComposeUiTest
import androidx.room.Room
import com.medsync.client.agents.FallbackRouter
import com.medsync.client.agents.RedFlagScreen
import com.medsync.client.app.MedSyncController
import com.medsync.client.data.MedSyncDatabase
import com.medsync.client.data.buildDatabase
import com.medsync.client.ui.App
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.net.HttpURLConnection
import java.net.URI
import javax.imageio.ImageIO

/**
 * The demo story in docs/demo.md, played on the real app against the running Compose stack with the on-device model.
 * Saves one frame per step plus its caption to desktopApp/build/demo; scripts/demo_gif.py turns them into
 * docs/demo.gif. It is also a test: every step asserts what the frame claims.
 *
 *     MEDSYNC_DEMO=1 ./gradlew --no-configuration-cache :desktopApp:test --tests '*DemoTest*'
 *     uv run --with pillow python scripts/demo_gif.py
 */
@OptIn(ExperimentalTestApi::class)
class DemoTest {
    private val gateway = System.getenv("MEDSYNC_GATEWAY") ?: DESKTOP_GATEWAY
    private val mocks = System.getenv("MEDSYNC_MOCKS") ?: "http://127.0.0.1:9100"
    private val out = File("build/demo").apply { deleteRecursively(); mkdirs() }
    private val captions = mutableListOf<Pair<String, String>>()

    private fun http(method: String, url: String, body: String? = null): String {
        val c = URI(url).toURL().openConnection() as HttpURLConnection
        c.requestMethod = method
        if (body != null) {
            c.doOutput = true; c.setRequestProperty("Content-Type", "application/json")
            c.outputStream.use { it.write(body.toByteArray()) }
        }
        check(c.responseCode in 200..299) { "$url → HTTP ${c.responseCode}" }
        return c.inputStream.bufferedReader().readText()
    }

    private fun DesktopComposeUiTest.frame(caption: String) {
        waitForIdle()
        val name = "%02d.png".format(captions.size + 1)
        ImageIO.write(onRoot().captureToImage().toAwtImage(), "png", File(out, name))
        captions += name to caption
    }

    private fun DesktopComposeUiTest.waitForText(text: String, timeoutMs: Long = 60_000) =
        waitUntil(timeoutMillis = timeoutMs) { onAllNodesWithText(text, substring = true).fetchSemanticsNodes().isNotEmpty() }

    private fun DesktopComposeUiTest.gone(text: String, timeoutMs: Long = 60_000) =
        waitUntil(timeoutMillis = timeoutMs) { onAllNodesWithText(text, substring = true).fetchSemanticsNodes().isEmpty() }

    private fun DesktopComposeUiTest.say(text: String) {
        onNode(hasSetTextAction()).performTextInput(text)
        onNodeWithText("发送").performClick()
    }

    @Test
    fun demo() = runDesktopComposeUiTest(width = 760, height = 1250) {
        assumeTrue(System.getenv("MEDSYNC_DEMO") == "1")
        val model = LiteRtRouter()
        assumeTrue("model file missing", model.available)
        val redFlag = LiteRtRedFlag(model)
        runBlocking { model.warmUp(); redFlag.warmUp() }  // main() does this while the window opens
        http("POST", "$mocks/admin/reset", "{}")
        val router = FallbackRouter(model)
        val file = File.createTempFile("demo", ".db").apply { delete(); deleteOnExit() }
        val app = MedSyncController(buildDatabase(Room.databaseBuilder<MedSyncDatabase>(name = file.absolutePath)),
            gateway, CoroutineScope(SupervisorJob() + Dispatchers.Default), router = router,
            redFlags = RedFlagScreen(redFlag))
        setContent { App(app) }
        frame("MedSync：断网也能用的用药助手。顶部一行说明断网时哪些功能仍然可用")

        say("我吃了华法林")
        waitForText("安全审核")
        frame("在线记录服药：同步到服务器，安全审核 Agent 对照最近 7 天的用药")

        onNode(isToggleable()).performClick()
        waitForText("现在离线")
        frame("断网：面板展开，标出每项功能是离线可用、联网后执行，还是需要联网")

        say("胸口像被人攥住一样，出了一身冷汗")
        waitForText("可能是危险信号")
        gone("本机模型理解中")
        frame("危险信号：关键词规则没命中，本机模型补充判断，并指出是原话里的哪几个字")

        say("我吃了布洛芬，告诉女儿我没事，帮我约明天的心内科")
        waitForText("已保存在本机")
        assertEquals("planned by the model, not the rules (${router.lastFailure})", model.name, router.lastSource)
        frame("断网时本机模型把一句话拆成 3 个动作：服药记录、通知女儿（等服药记录处理完）、预约，都存在本机队列")

        // While the phone is offline, someone else takes the last slot for tomorrow.
        val tomorrow = java.time.LocalDate.now().plusDays(1)
        http("POST", "$mocks/admin/slots/$tomorrow", """{"available": 0}""")
        onNode(isToggleable()).performClick()
        waitForText("已暂停")
        waitForText("原定日期号源已满")
        frame("联网后：布洛芬和华法林触发相互作用提醒；排队的“我没事”被暂停；明天的号已被抢，问你改约哪天")

        onNodeWithText("附上提醒再发").performClick()
        onAllNodesWithText("改约 ", substring = true)[0].performClick()
        gone("需要你确认")
        waitForText("MedSync 用药提醒")
        val effects = http("GET", "$mocks/metrics/side_effects")
        frame("你确认后才执行：消息附上提醒发出，预约改到后天。外部系统记录：预约 1 次、通知 1 次")
        // The caption above is the claim; the external system's own counter is the evidence.
        val counts = Json.parseToJsonElement(effects).jsonObject
        assertEquals(effects, 1, counts["bookings"]!!.jsonPrimitive.int)
        assertEquals(effects, 1, counts["notifications"]!!.jsonPrimitive.int)
        onNodeWithText("心血管内科 · ${tomorrow.plusDays(1)}", substring = true).assertExists()

        File(out, "captions.tsv").writeText(captions.joinToString("\n") { "${it.first}\t${it.second}" } + "\n")
        model.close()
    }
}
