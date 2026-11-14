package com.medsync.client.agents

import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.datetime.LocalDate

/**
 * Turns one utterance into a plan, on the device, without the network. Implementations: [RuleBasedRouter] (always
 * available, the baseline) and an on-device model injected per platform (LiteRT-LM on Android / desktop, Swift on
 * iOS). Scored on the same set: eval/routing/utterances.jsonl.
 */
interface OnDeviceRouter {
    val name: String
    suspend fun route(text: String, today: LocalDate, nowMs: Long): RuleRouter.Routed
}

object RuleBasedRouter : OnDeviceRouter {
    override val name = "rules"
    override suspend fun route(text: String, today: LocalDate, nowMs: Long) = RuleRouter.route(text, today, nowMs)
}

/**
 * The model first; the rules when the model is missing, too slow, throws, or returns something that is not a valid
 * plan (signalled by returning null). The rules never fail, so a plan always comes back.
 */
class FallbackRouter(
    private val primary: ModelRouter,
    private val fallback: OnDeviceRouter = RuleBasedRouter,
    // Slowest warm call in the routing eval was 5.6 s (four clauses, CPU); past this the rules answer instead.
    private val timeoutMs: Long = 10_000,
) : OnDeviceRouter {
    override val name = "${primary.name}+${fallback.name}"

    /** How the last call was answered, for the UI and the latency log. */
    var lastSource: String = fallback.name
        private set

    /** Why the last call fell back (null when the model answered), for logs and tests. */
    var lastFailure: String? = null
        private set

    override suspend fun route(text: String, today: LocalDate, nowMs: Long): RuleRouter.Routed {
        val attempt = runCatching { withTimeoutOrNull(timeoutMs) { primary.tryRoute(text, today, nowMs) } }
        val routed = attempt.getOrNull()
        lastSource = if (routed != null) primary.name else fallback.name
        lastFailure = when {
            routed != null -> null
            attempt.isFailure -> attempt.exceptionOrNull().toString()
            else -> "no answer within ${timeoutMs} ms (or the model declined)"
        }
        return routed ?: fallback.route(text, today, nowMs)
    }
}

/** A router that may decline (null) instead of guessing, e.g. when the model's output does not parse. */
interface ModelRouter {
    val name: String
    suspend fun tryRoute(text: String, today: LocalDate, nowMs: Long): RuleRouter.Routed?
}
