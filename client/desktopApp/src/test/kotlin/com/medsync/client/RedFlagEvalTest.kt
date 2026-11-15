package com.medsync.client

import com.medsync.client.agents.RedFlag
import com.medsync.client.agents.RedFlagDetector
import com.medsync.client.agents.RedFlagOpinion
import com.medsync.client.agents.RedFlagScreen
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import kotlin.time.TimeSource

/**
 * Runs the danger-sign detectors over eval/redflag/cases.jsonl and writes eval/redflag/predictions/<detector>.jsonl
 * for eval/redflag/score.py: the rules, the model alone (after its guards), and the two together as the app runs them.
 *
 *     MEDSYNC_REDFLAG_EVAL=1 ./gradlew --no-configuration-cache :desktopApp:test --tests '*RedFlagEvalTest*'
 */
class RedFlagEvalTest {
    private val dir = File("../../eval/redflag")

    @Test
    fun writePredictions() = runBlocking {
        assumeTrue(System.getenv("MEDSYNC_REDFLAG_EVAL") == "1")
        val llm = LiteRtRouter()
        assumeTrue("model file missing", llm.available)
        val model = LiteRtRedFlag(llm)
        model.warmUp()
        val split = System.getenv("MEDSYNC_SPLIT")  // "dev" while tuning; the test split is run once at the end
        val rows = File(dir, "cases.jsonl").readLines().filter { it.isNotBlank() }
            .map { Json.parseToJsonElement(it).jsonObject }
            .filter { split == null || it["split"]!!.jsonPrimitive.content == split }
        File(dir, "predictions").mkdirs()
        val outs = listOf("rules", model.name, "rules+${model.name}").associateWith {
            File(dir, "predictions/$it.jsonl").bufferedWriter()
        }
        for (row in rows) {
            val text = row["text"]!!.jsonPrimitive.content
            val id = row["id"]!!
            var mark = TimeSource.Monotonic.markNow()
            val rule = RedFlagDetector.detect(text)
            val ruleMs = mark.elapsedNow().inWholeMicroseconds / 1000.0
            mark = TimeSource.Monotonic.markNow()
            val opinion: RedFlagOpinion? = model.assess(text)
            val modelMs = mark.elapsedNow().inWholeMicroseconds / 1000.0
            val guarded = opinion?.let { RedFlagScreen.accept(text, it, model.name) }
            outs.getValue("rules").line(id, rule, ruleMs)
            outs.getValue(model.name).line(id, guarded, modelMs, opinion)
            outs.getValue("rules+${model.name}").line(id, rule ?: guarded, if (rule != null) ruleMs else ruleMs + modelMs)
            println("redflag: ${modelMs.toInt()} ms  $text → rules=${rule?.matched} model=${opinion?.kind}「${opinion?.evidence}」 kept=${guarded != null}")
        }
        outs.values.forEach { it.close() }
        llm.close()
    }

    private fun java.io.BufferedWriter.line(id: kotlinx.serialization.json.JsonElement, flag: RedFlag?, ms: Double,
                                            raw: RedFlagOpinion? = null) {
        val fields = mutableMapOf(
            "id" to id,
            "flag" to (flag?.let { JsonPrimitive(it.kind.name.lowercase()) } ?: JsonNull),
            "evidence" to (flag?.let { JsonPrimitive(it.matched) } ?: JsonNull),
            "ms" to JsonPrimitive(ms),
        )
        raw?.let { fields["raw"] = JsonPrimitive("${it.kind.name.lowercase()}「${it.evidence}」") }
        write(Json.encodeToString(JsonObject.serializer(), JsonObject(fields)))
        newLine()
    }
}
