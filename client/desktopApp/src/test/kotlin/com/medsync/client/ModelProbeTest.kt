package com.medsync.client

import org.junit.Assume.assumeTrue
import org.junit.Test
import kotlin.time.measureTimedValue

/** MEDSYNC_PROBE=1 ./gradlew :desktopApp:test --tests '*ModelProbeTest*' — raw tool calls for a few sentences. */
class ModelProbeTest {
    @Test
    fun probe() {
        assumeTrue(System.getenv("MEDSYNC_PROBE") == "1")
        val router = LiteRtRouter()
        assumeTrue("model file missing", router.available)
        val load = kotlin.time.measureTime { router.calls("你好") }
        println("probe: first call incl. load ${load.inWholeMilliseconds} ms")
        // Sentences to try: one per line in desktopApp/build/probe.txt (env vars can be stale with the config cache).
        val custom = java.io.File("build/probe.txt").takeIf { it.isFile }?.readLines()?.filter { it.isNotBlank() }
        for (text in custom ?: listOf("吃了布洛芬和奥美拉唑", "吃了头孢能喝酒吗", "我吃了布洛芬，有点胃疼，帮我约周三消化科，告诉女儿",
                "没有头疼，也没有发烧", "告诉爸爸明天去复诊", "挂个下周一心内科的号", "你好", "腰疼")) {
            val (calls, time) = measureTimedValue { router.calls(text) }
            println("probe: ${time.inWholeMilliseconds} ms  $text → ${calls.joinToString { "${it.name}${it.arguments}" }}")
        }
        router.close()
    }
}
