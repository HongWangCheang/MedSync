package com.medsync.client.sync

import com.medsync.client.data.ActionEntity
import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.client.statement.HttpResponse
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import kotlinx.io.IOException
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** What hop ① can answer. Transient means "nothing is known; try again later with the same step_key". */
sealed interface SubmitResult {
    data class Done(val result: JsonElement?) : SubmitResult
    data object Accepted : SubmitResult
    data class NeedsUser(val reason: String?, val result: JsonElement?) : SubmitResult
    data class Failed(val reason: String?) : SubmitResult
    data class Cancelled(val reason: String?) : SubmitResult
    data object Conflict : SubmitResult
    data class Transient(val message: String) : SubmitResult
}

interface GatewayApi {
    suspend fun submit(action: ActionEntity): SubmitResult
    suspend fun status(stepKey: String): SubmitResult
    suspend fun resume(stepKey: String, decision: JsonObject): SubmitResult
}

@Serializable
private data class View(val stepKey: String, val status: String, val result: JsonElement? = null,
                        val reason: String? = null)

@Serializable
private data class Session(val accountId: String, val token: String)

@Serializable
private data class Credentials(val username: String, val password: String)

/**
 * Ktor client for the gateway. `session` persists a development account (created on first use) so the demo works
 * out of the box; replace with real login + Keystore / Keychain storage before shipping.
 */
class KtorGatewayApi(
    private val baseUrl: String,
    private val loadToken: suspend () -> String?,
    private val saveToken: suspend (String) -> Unit,
    private val newCredentials: () -> Pair<String, String>,
) : GatewayApi {
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
    private val http = HttpClient {
        install(ContentNegotiation) { json(json) }
        install(HttpTimeout) {
            connectTimeoutMillis = 5_000
            requestTimeoutMillis = 20_000
        }
        expectSuccess = false
    }

    override suspend fun submit(action: ActionEntity): SubmitResult = call {
        http.post("$baseUrl/v1/actions") {
            auth(it)
            contentType(ContentType.Application.Json)
            setBody(wire(action))
        }
    }

    override suspend fun status(stepKey: String): SubmitResult = call {
        http.get("$baseUrl/v1/actions/$stepKey") { auth(it) }
    }

    override suspend fun resume(stepKey: String, decision: JsonObject): SubmitResult = call {
        http.post("$baseUrl/v1/actions/$stepKey/resume") {
            auth(it)
            contentType(ContentType.Application.Json)
            setBody(decision)
        }
    }

    private fun io.ktor.client.request.HttpRequestBuilder.auth(token: String) =
        header(HttpHeaders.Authorization, "Bearer $token")

    private suspend fun token(): String = loadToken() ?: run {
        val (user, password) = newCredentials()
        val response = http.post("$baseUrl/v1/auth/register") {
            contentType(ContentType.Application.Json)
            setBody(Credentials(user, password))
        }
        check(response.status.value == 201) { "register failed: HTTP ${response.status.value}" }
        response.body<Session>().token.also { saveToken(it) }
    }

    private suspend fun call(request: suspend (String) -> HttpResponse): SubmitResult = try {
        val response = request(token())
        when (val code = response.status.value) {
            200 -> response.body<View>().toResult()
            409 -> SubmitResult.Conflict
            401 -> SubmitResult.Transient("unauthorized").also { saveToken("") }
            in 400..499 -> if (code == 429) SubmitResult.Transient("rate limited") else SubmitResult.Failed("HTTP $code")
            else -> SubmitResult.Transient("HTTP $code")
        }
    } catch (error: IOException) {
        SubmitResult.Transient(error.message ?: "network error")
    } catch (error: Exception) {
        // Ktor timeouts and engine-specific connection errors don't share one type across platforms.
        SubmitResult.Transient(error.message ?: error::class.simpleName ?: "error")
    }

    private fun View.toResult(): SubmitResult = when (status) {
        "DONE" -> SubmitResult.Done(result)
        "ACCEPTED" -> SubmitResult.Accepted
        "NEEDS_USER" -> SubmitResult.NeedsUser(reason, result)
        "CANCELLED" -> SubmitResult.Cancelled(reason)
        else -> SubmitResult.Failed(reason ?: status)
    }

    private fun wire(action: ActionEntity): JsonObject = buildJsonObject {
        put("stepKey", action.stepKey)
        put("planId", action.planId)
        put("stepIndex", action.stepIndex)
        put("tool", action.tool)
        put("toolClass", action.toolClass)
        put("identityArgs", json.parseToJsonElement(action.identityArgsJson))
        put("payload", json.parseToJsonElement(action.payloadJson))
        put("preconditions", json.parseToJsonElement(action.preconditionsJson))
        put("createdAtMs", action.createdAtMs)
        action.expiresAtMs?.let { put("expiresAtMs", it) }
    }
}
