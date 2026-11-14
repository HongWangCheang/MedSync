package com.medsync.client.agents

/**
 * Danger-sign agent. Runs entirely on the device, rules first, because it must work offline and every decision must
 * be explainable. Recall matters more than precision: a false alarm costs a moment, a miss can cost a life.
 * It never diagnoses; it only tells the user to get help now. Phase 2 adds a small model as a second opinion on top
 * of these rules, never instead of them.
 */
data class RedFlag(val matched: String, val advice: String)

object RedFlagDetector {
    private const val EMERGENCY = "这可能是紧急情况。请立即拨打 120，或尽快前往最近的急诊。"
    private const val CRISIS = "你现在可能很难受。请立即拨打 12356 心理援助热线；如有生命危险，请拨打 120 或 110。"

    private val emergency = listOf(
        "胸痛", "胸口痛", "胸口疼", "胸口压", "呼吸困难", "喘不上气", "喘不过气", "意识不清", "昏迷", "晕倒",
        "抽搐", "吐血", "咯血", "便血", "黑便", "剧烈头痛", "口角歪斜", "说话不清", "半边身体", "一侧肢体",
        "过量", "吃多了", "一整瓶", "吃了一瓶",
    )
    private val crisis = listOf("不想活", "自杀", "轻生", "结束生命")
    private val negations = listOf("没有", "没", "无", "不", "未")

    fun detect(text: String): RedFlag? {
        crisis.firstOrNull { hit(text, it) }?.let { return RedFlag(it, CRISIS) }
        emergency.firstOrNull { hit(text, it) }?.let { return RedFlag(it, EMERGENCY) }
        return null
    }

    /** True if [keyword] occurs at least once without a negation right before it ("没有胸痛" is not a hit). */
    private fun hit(text: String, keyword: String): Boolean {
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
