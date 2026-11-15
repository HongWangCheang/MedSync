package com.medsync.client

import com.google.ai.edge.litertlm.LiteRtLmJniException
import com.google.ai.edge.litertlm.OpenApiTool
import com.medsync.client.agents.RedFlagKind
import com.medsync.client.agents.RedFlagModel
import com.medsync.client.agents.RedFlagOpinion

/**
 * Second opinion on danger signs from the same on-device model as routing (one engine, one model in memory). It
 * only sees the sentences the rules let through; [com.medsync.client.agents.RedFlagScreen] keeps its answer only
 * if the evidence is in the user's words. Throws when the model file is missing, so the rules' answer stands.
 */
class LiteRtRedFlag(private val llm: LiteRtRouter) : RedFlagModel {
    override val name: String = llm.name

    val available: Boolean get() = llm.available

    override suspend fun assess(text: String): RedFlagOpinion? {
        check(llm.available) { "model file missing" }
        return llm.exclusive { raw(text) }
    }

    /** The parsed tool call; call inside [LiteRtRouter.exclusive]. */
    private fun raw(text: String): RedFlagOpinion? {
        val (name, evidence) = try {
            val call = llm.send(llm.prefilled("red_flag", SYSTEM, TOOLS), text).toolCalls.firstOrNull() ?: return null
            call.name to call.arguments["evidence"]?.toString().orEmpty()
        } catch (e: LiteRtLmJniException) {
            // The 0.6B model sometimes closes its JSON with one brace too many and the runtime rejects the whole
            // reply; the call itself is still readable in the error, and a danger sign must not be lost to a typo.
            val found = MALFORMED.find(e.message.orEmpty()) ?: throw e
            found.groupValues[1] to found.groupValues[2]
        }
        val kind = when (name) {
            "report_suicide_risk" -> RedFlagKind.CRISIS
            "report_emergency" -> RedFlagKind.EMERGENCY
            else -> return null
        }
        return RedFlagOpinion(kind, evidence)
    }

    /** Loads the red-flag instructions ahead of the first sentence, like [LiteRtRouter.warmUp]. */
    suspend fun warmUp() = llm.exclusive { llm.prefilled("red_flag", SYSTEM, TOOLS) }

    companion object {
        // The examples are written for this prompt and do not appear in eval/redflag/cases.jsonl.
        val SYSTEM = """
            你判断用户这句话是不是在说一个需要马上打 120 或去急诊的情况（用户本人或家人）。大多数话都不是，这时不调用任何工具。
            调用 report_emergency 的情况：胸痛或胸部压迫感、呼吸困难、中风征象（口眼歪斜、一侧肢体无力、言语不清、突然看不见）、意识丧失或没有反应、抽搐、大出血（呕血、咯血、黑便、出血止不住）、药物过量或误服、严重过敏、突发的剧烈疼痛、高热伴神志改变、严重低血糖。
            调用 report_suicide_risk 的情况：用户本人有想死、自杀、自伤的念头或准备，包括这些预警信号：觉得活着没有意义或没有希望、觉得自己是别人的负担、交代后事或道别、囤积药物或准备自伤的工具、已经伤害了自己。
            不调用工具的情况：
            - 普通的、轻微的不舒服，例如腿酸、肩膀疼、打喷嚏、口干、起了个小疙瘩、胃口不好
            - 否定或已经好转，例如没有胸闷、不咳了
            - 口头禅和夸张，例如忙死了、烦死了、渴死了
            - 提问、科普、过去的病史
            - 日常的服药记录、症状记录和挂号，即使说了吃了几片药
            evidence 照抄用户原话里说明危险的那几个字，不要改写。
            示例：
            用户：突然天旋地转，左腿没力气 → report_emergency(evidence=左腿没力气)
            用户：吃了虾以后喉咙肿了 → report_emergency(evidence=喉咙肿了)
            用户：我每天都在想怎么死 → report_suicide_risk(evidence=想怎么死)
            用户：肩膀有点酸 → 不调用工具
            用户：打了几个喷嚏 → 不调用工具
            用户：没有胸闷，挺好的 → 不调用工具
            用户：今天忙死了 → 不调用工具
            用户：心梗是什么症状 → 不调用工具
            用户：刚吃了一片降压药 → 不调用工具
            用户：前年做过心脏支架 → 不调用工具
        """.trimIndent()

        private val MALFORMED = Regex(""""name":\s*"(report_\w+)".*?"evidence":\s*"([^"]*)"""", RegexOption.DOT_MATCHES_ALL)

        private const val EVIDENCE = """"evidence":{"type":"string","description":"用户原话里说明危险的那几个字，照抄"}"""

        val TOOLS: List<OpenApiTool> = listOf(
            LiteRtRouter.spec("report_emergency", "用户或家人现在可能有需要马上就医的危险情况。", EVIDENCE, "\"evidence\""),
            LiteRtRouter.spec("report_suicide_risk", "用户本人可能有自杀或伤害自己的想法。", EVIDENCE, "\"evidence\""),
        )
    }
}
