package com.medsync.client.agents

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Danger-sign agent. Runs entirely on the device, rules first, because it must work offline and every decision must
 * be explainable. Recall matters more than precision: a false alarm costs a moment, a miss can cost a life.
 * It never diagnoses; it only tells the user to get help now. A small on-device model ([RedFlagScreen]) adds a
 * second opinion on top of these rules, never instead of them.
 */
data class RedFlag(
    /** The user's own words that triggered the alert, shown on the card so the alert explains itself. */
    val matched: String,
    val advice: String,
    val kind: RedFlagKind = RedFlagKind.EMERGENCY,
    /** "rules", or the model's name when only the model saw it. */
    val source: String = "rules",
)

enum class RedFlagKind { EMERGENCY, CRISIS }

object RedFlagDetector {
    const val EMERGENCY = "这可能是紧急情况。请立即拨打 120，或尽快前往最近的急诊。"
    const val CRISIS = "你现在可能很难受。请立即拨打 12356 心理援助热线；如有生命危险，请拨打 120 或 110。"

    private val emergency = listOf(
        "胸痛", "胸口痛", "胸口疼", "胸口压", "呼吸困难", "喘不上气", "喘不过气", "意识不清", "昏迷", "晕倒",
        "抽搐", "吐血", "咯血", "便血", "黑便", "剧烈头痛", "口角歪斜", "说话不清", "半边身体", "一侧肢体",
        "过量", "吃多了", "一整瓶", "吃了一瓶",
    )
    private val crisis = listOf("不想活", "自杀", "轻生", "结束生命")
    private val negations = listOf("没有", "没", "无", "不", "未")

    fun detect(text: String): RedFlag? {
        crisis.firstOrNull { hit(text, it) }?.let { return RedFlag(it, CRISIS, RedFlagKind.CRISIS) }
        emergency.firstOrNull { hit(text, it) }?.let { return RedFlag(it, EMERGENCY) }
        return null
    }

    /** True if [keyword] occurs at least once without a negation right before it ("没有胸痛" is not a hit). */
    fun hit(text: String, keyword: String): Boolean {
        var from = 0
        while (true) {
            val at = text.indexOf(keyword, from)
            if (at < 0) return false
            val before = text.substring(maxOf(0, at - 2), at)
            if (negations.none { before.endsWith(it) }) return true
            from = at + keyword.length
        }
    }
}

/** A small model's raw opinion: which kind of danger, and the words in the sentence that show it. */
data class RedFlagOpinion(val kind: RedFlagKind, val evidence: String)

/** On-device model asked "is this a danger sign?". Null means "no danger"; throwing means "could not tell". */
interface RedFlagModel {
    val name: String
    suspend fun assess(text: String): RedFlagOpinion?
}

/**
 * Rules first, then the model, for the sentences the rules let through. The model can only add an alert, never
 * withdraw one the rules raised; when it is missing, slow or fails, the rules' answer stands.
 *
 * The model's opinion is kept only if it can point at the user's words: the evidence must occur in the sentence
 * and must not be negated ("没有胸痛"). That keeps every alert explainable, the same as a rule hit.
 */
class RedFlagScreen(
    private val model: RedFlagModel? = null,
    private val timeoutMs: Long = 5_000,
) {
    val name: String get() = model?.let { "rules+${it.name}" } ?: "rules"
    val hasModel: Boolean get() = model != null

    /** Why the model gave no usable answer on the last call (null when it answered or was not asked). */
    var lastFailure: String? = null
        private set

    /** The rules alone: instant, so the card can show before the model has answered. */
    fun rules(text: String): RedFlag? = RedFlagDetector.detect(text)

    suspend fun detect(text: String): RedFlag? = rules(text) ?: second(text)

    /** The model's opinion after the guards, without the rules (for the eval). */
    suspend fun second(text: String): RedFlag? {
        lastFailure = null
        val model = model ?: return null
        // Wrapped in a list so "the model said no danger" (null inside) differs from "timed out" (null outside).
        val answered = try {
            withTimeoutOrNull(timeoutMs) { listOf(model.assess(text)) }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            lastFailure = e.toString()
            return null
        }
        if (answered == null) lastFailure = "no answer within $timeoutMs ms"
        val opinion = answered?.single() ?: return null
        return accept(text, opinion, model.name)
    }

    companion object {
        private val PHRASE = Regex("[，,。.！!？?、；;：:\\s「」\"“”]+")

        // Everyday exaggeration: 笑死我了, 累死了, 要我命. A fixed list of feelings and states, so "想死" and
        // "不如死了算了" (intent) never match; pain ("疼死了") is left to the model.
        private val HYPERBOLE = Regex("[笑吓累热冷饿渴困烦忙气急馋美乐愁丑懒]死(了|我了|人了|啦)|要(了)?我的?(老)?命")

        /** The guards on a model opinion; public for unit tests. */
        fun accept(text: String, opinion: RedFlagOpinion, source: String): RedFlag? {
            // Small models change punctuation and join phrases ("憋气,嘴唇都发紫了"): keep the first phrase that is
            // really in the sentence, not negated, and long enough to mean something.
            val evidence = opinion.evidence.split(PHRASE).map { it.trim() }
                .firstOrNull { it.length >= 2 && RedFlagDetector.hit(text, it) } ?: return null
            if (HYPERBOLE.containsMatchIn(evidence)) return null
            val advice = if (opinion.kind == RedFlagKind.CRISIS) RedFlagDetector.CRISIS else RedFlagDetector.EMERGENCY
            return RedFlag(evidence, advice, opinion.kind, source)
        }
    }
}
