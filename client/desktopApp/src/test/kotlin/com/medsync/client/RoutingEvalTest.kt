package com.medsync.client

import com.medsync.client.agents.OnDeviceRouter
import com.medsync.client.agents.RuleBasedRouter
import kotlinx.coroutines.runBlocking
import kotlinx.datetime.LocalDate
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import kotlin.time.TimeSource

/**
 * Runs each router over eval/routing/utterances.jsonl and writes eval/routing/predictions/<router>.jsonl; scoring is
 * eval/routing/score.py, so every router (rules, models) is scored by the same code.
 *
 *     MEDSYNC_ROUTING_EVAL=1 ./gradlew :desktopApp:test --tests '*RoutingEvalTest*'
 *     python3 ../eval/routing/score.py
 */
class RoutingEvalTest {
    private val dir = File("../../eval/routing")

    /** Routers to score. The model is scored alone (no rule fallback) so its own accuracy is visible. */
    private fun routers(): List<OnDeviceRouter> = listOf(RuleBasedRouter, modelOnly(LiteRtRouter()))

    private fun modelOnly(model: LiteRtRouter) = object : OnDeviceRouter {
        override val name = model.name
        override suspend fun route(text: String, today: LocalDate, nowMs: Long) =
            model.tryRoute(text, today, nowMs) ?: error("model unavailable: ${model.name}")
    }

    @Test
    fun writePredictions() = runBlocking {
        assumeTrue(System.getenv("MEDSYNC_ROUTING_EVAL") == "1")
        val lines = File(dir, "utterances.jsonl").readLines().filter { it.isNotBlank() }
        val today = LocalDate.parse(Json.parseToJsonElement(lines.first()).jsonObject["today"]!!.jsonPrimitive.content)
        val rows = lines.drop(1).map { Json.parseToJsonElement(it).jsonObject }
        val only = System.getenv("MEDSYNC_ROUTERS")?.split(',')?.map { it.trim() }
        File(dir, "predictions").mkdirs()
        val split = System.getenv("MEDSYNC_SPLIT")  // "dev" while tuning; the test split is run once at the end
        for (router in routers().filter { only == null || it.name in only }) {
            val out = File(dir, "predictions/${router.name}.jsonl").bufferedWriter()
            for (row in rows.filter { split == null || it["split"]!!.jsonPrimitive.content == split }) {
                val text = row["text"]!!.jsonPrimitive.content
                val mark = TimeSource.Monotonic.markNow()
                val routed = router.route(text, today, 0L)
                val ms = mark.elapsedNow().inWholeMicroseconds / 1000.0
                val steps = JsonArray(routed.steps.map { JsonObject(mapOf("tool" to JsonPrimitive(it.tool)) + it.payload) })
                out.write(Json.encodeToString(JsonObject.serializer(), JsonObject(mapOf(
                    "id" to row["id"]!!, "steps" to steps, "ms" to JsonPrimitive(ms)))))
                out.newLine()
            }
            out.close()
            println("routing eval: ${router.name} done")
        }
    }

    @Suppress("unused")
    private fun JsonObject.str(key: String) = (this[key] as? JsonPrimitive)?.contentOrNull
}
