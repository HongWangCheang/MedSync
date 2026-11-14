package com.medsync.client

import com.medsync.client.agents.RuleRouter
import com.medsync.client.outbox.Planner
import com.medsync.client.sync.KtorGatewayApi
import com.medsync.client.sync.SyncEngine
import kotlinx.coroutines.runBlocking
import kotlinx.datetime.LocalDate
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.uuid.Uuid

/**
 * Real Ktor client → Toxiproxy hop ① → gateway → agent → mocks. Opt-in, needs `docker compose up`:
 *     MEDSYNC_LIVE=1 ./gradlew :shared:jvmTest --tests '*LiveGatewayTest*'
 */
class LiveGatewayTest {
    private val gateway = System.getenv("MEDSYNC_GATEWAY") ?: "http://127.0.0.1:18081"
    private val mocks = System.getenv("MEDSYNC_MOCKS") ?: "http://127.0.0.1:9100"

    /** Test setup call; HTTP/1.1 because the JDK client's default h2c upgrade is rejected by uvicorn. */
    private fun post(url: String, body: String) {
        val response = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build().send(
            HttpRequest.newBuilder(URI(url)).header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString())
        check(response.statusCode() == 200) { "setup failed: $url → HTTP ${response.statusCode()}" }
    }

    @Test
    fun sentenceToBookingThroughTheRealStack() = runBlocking {
        if (System.getenv("MEDSYNC_LIVE") == null) return@runBlocking
        var token: String? = null
        val api = KtorGatewayApi(gateway, { token?.ifBlank { null } }, { token = it },
            { "it_${Uuid.random().toHexString().take(10)}" to "integration-pass-1" })
        val dao = FakeDao()
        val engine = SyncEngine(dao, api)
        val saturday = LocalDate(2026, 11, 14)

        // 1. A compound sentence becomes a DAG and every step reaches DONE in one pass.
        dao.insertAll(Planner.plan(RuleRouter.route("我吃了布洛芬，有点胃疼，帮我约周三复诊", saturday, 0).steps,
            "it-device", System.currentTimeMillis()))
        engine.drainOnce(System.currentTimeMillis())
        assertEquals(listOf("DONE", "DONE", "DONE"), dao.rows.value.map { it.state })

        // 2. The slot is taken while the step is queued: NEEDS_USER with options, then the user picks another day.
        post("$mocks/admin/slots/2026-11-25", """{"available": 0}""")
        dao.rows.value = emptyList()
        dao.insertAll(Planner.plan(RuleRouter.route("帮我约下周三复诊", LocalDate(2026, 11, 16), 0).steps,
            "it-device", System.currentTimeMillis()))
        engine.drainOnce(System.currentTimeMillis())
        val waiting = dao.rows.value.single()
        assertEquals("NEEDS_USER" to "slot_full", waiting.state to waiting.reason)
        val choice = Json.parseToJsonElement(waiting.resultJson!!).jsonObject["options"]!!.jsonArray
            .map { it.jsonObject }.first { it["decision"]!!.jsonPrimitive.content == "choose" }
        val done = engine.resolve(waiting, buildJsonObject {
            put("decision", "choose"); put("date", choice["date"]!!.jsonPrimitive.content)
        }, System.currentTimeMillis())
        assertEquals("DONE", done.state)
    }
}
