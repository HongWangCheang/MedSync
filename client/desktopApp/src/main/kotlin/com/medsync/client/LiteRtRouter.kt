package com.medsync.client

import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Conversation
import com.google.ai.edge.litertlm.ConversationConfig
import com.google.ai.edge.litertlm.Contents
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.LogSeverity
import com.google.ai.edge.litertlm.Message
import com.google.ai.edge.litertlm.OpenApiTool
import com.google.ai.edge.litertlm.SamplerConfig
import com.google.ai.edge.litertlm.ThinkingConfig
import com.google.ai.edge.litertlm.tool
import com.medsync.client.agents.ModelPlan
import com.medsync.client.agents.ModelRouter
import com.medsync.client.agents.RuleRouter
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.datetime.LocalDate
import java.io.File

/**
 * On-device router running a small model through LiteRT-LM's JVM runtime (the same Kotlin API as litertlm-android;
 * on this Mac it stands in for the phone). The model only picks tools and copies arguments out of the sentence;
 * [ModelPlan] turns that into a plan. Returns null (→ rule fallback) when the model is missing or the call fails.
 *
 * Default model: Qwen3-0.6B int4 (litert-community, Apache-2.0) in ~/.medsync/models.
 */
class LiteRtRouter(
    private val modelPath: String = defaultModelPath(),
    override val name: String = "qwen3-0.6b",
    private val backend: Backend = if (System.getenv("MEDSYNC_BACKEND") == "gpu") Backend.GPU() else Backend.CPU(),
) : ModelRouter {
    private var engine: Engine? = null
    // Instructions + tool schemas already prefilled, one per task (routing, red flags); cloned per sentence.
    private val bases = mutableMapOf<String, Conversation>()
    private val lock = Mutex()  // one inference at a time; the engine is not shared across threads

    val available: Boolean get() = File(modelPath).isFile

    /**
     * Loads the model and prefills the instructions now instead of on the first sentence (about 7 s on this Mac's
     * CPU). Without it the first sentence can exceed [com.medsync.client.agents.FallbackRouter]'s limit and fall back.
     */
    suspend fun warmUp() = exclusive { routing() }

    /** Runs [block] with the engine to itself: one inference at a time, off the caller's thread. */
    internal suspend fun <T> exclusive(block: () -> T): T = lock.withLock { withContext(Dispatchers.IO) { block() } }

    private fun engineOrLoad(): Engine = engine ?: run {
        Engine.setNativeMinLogSeverity(LogSeverity.ERROR)
        val cache = File(System.getProperty("user.home"), ".medsync/models/cache").apply { mkdirs() }
        Engine(EngineConfig(modelPath, backend, cacheDir = cache.absolutePath)).also {
            it.initialize()
            engine = it
        }
    }

    override suspend fun tryRoute(text: String, today: LocalDate, nowMs: Long): RuleRouter.Routed? {
        if (!available) return null
        return ModelPlan.plan(text, today, nowMs) { piece ->
            exclusive { calls(piece) }
        }
    }

    /** The raw tool calls, for the eval's error analysis. */
    fun calls(text: String): List<ModelPlan.Call> {
        // The instructions and tool schemas are the same every time: prefill them once and clone that state, so a
        // sentence only pays for its own tokens.
        return send(routing(), text).toolCalls.map { ModelPlan.Call(it.name, it.arguments) }
    }

    private fun routing() = prefilled("routing", SYSTEM, TOOLS)

    /** One message on a fresh copy of [base]; call inside [exclusive]. */
    internal fun send(base: Conversation, text: String): Message = base.clone().use { it.sendMessage(text) }

    /** The conversation for [key] with [system] and [tools] prefilled, created on first use; call inside [exclusive]. */
    internal fun prefilled(key: String, system: String, tools: List<OpenApiTool>): Conversation = bases.getOrPut(key) {
        engineOrLoad().createConversation(ConversationConfig(
            systemInstruction = Contents.of(system),
            tools = tools.map { tool(it) },
            samplerConfig = SamplerConfig(topK = 1, topP = 1.0, temperature = 0.0, seed = 0),
            automaticToolCalling = false,
            prefillPrefaceOnInit = true,
            thinkingConfig = ThinkingConfig(enableThinking = false),
        ))
    }

    fun close() {
        bases.values.forEach { it.close() }
        bases.clear()
        engine?.close()
        engine = null
    }

    internal class Spec(private val json: String) : OpenApiTool {
        override fun getToolDescriptionJsonString() = json
        override fun execute(paramsJsonString: String) = "{}"  // never called: automaticToolCalling = false
    }

    companion object {
        fun defaultModelPath(): String = System.getenv("MEDSYNC_MODEL")
            ?: File(System.getProperty("user.home"), ".medsync/models/Qwen3-0.6B_dynamic_wi4b32_afp32.litertlm").path

        // The examples are written for this prompt and do not appear in eval/routing/utterances.jsonl.
        val SYSTEM = """
            你是用药助手的指令解析器。把用户的一句话拆成要做的事，调用对应的工具；一句话可以调用多个工具，每种药、每个症状各调用一次。
            规则：
            1. 用户在提问（能不能、可以吗、怎么吃、吃多少、多久、有什么副作用、吗、？）时，只调用 ask_pharmacist，不要记录服药或症状。
            2. 只有用户说已经用过药（吃了、服用了、打了、喷了、滴了、吃过、喝了）才调用 record_medication；没吃、忘了吃、不想吃都不记录。
            3. 用户说自己有不舒服才调用 record_symptom；“没有头疼”这种否定不记录。
            4. 用户要挂号、预约、复诊时调用 book_appointment；只是告诉家人要去复诊不算预约。
            5. 用户要告诉、通知、跟家人说时调用 notify_family。
            6. 问候、闲聊不调用任何工具。
            示例：
            用户：刚吃了阿莫西林和维生素B → record_medication(name=阿莫西林)，record_medication(name=维生素B)
            用户：我早上的药还没吃 → 不调用工具
            用户：没有咳嗽，就是有点鼻塞 → record_symptom(symptom=鼻塞)
            用户：告诉儿子我下周去体检 → notify_family(to=儿子)
            用户：饭后能吃阿莫西林吗 → ask_pharmacist(question=饭后能吃阿莫西林吗)
            用户：吃了阿莫西林可以喝咖啡吗 → ask_pharmacist(question=吃了阿莫西林可以喝咖啡吗)
            用户：帮我挂周六的眼科 → book_appointment(department=眼科)
            用户：头晕，吃了降压药，约明天心内科，跟老伴说一声 → record_symptom(symptom=头晕)，record_medication(name=降压药)，book_appointment(department=心内科)，notify_family(to=老伴)
            用户：早上好呀 → 不调用工具
        """.trimIndent()

        internal fun spec(name: String, description: String, properties: String, required: String) = Spec(
            """{"name":"$name","description":"$description","parameters":{"type":"object","properties":{$properties},"required":[$required]}}"""
        )

        val TOOLS: List<OpenApiTool> = listOf(
            spec("record_medication", "记录用户已经用过的一种药。",
                """"name":{"type":"string","description":"药名，照用户原话，例如 布洛芬、泰诺、降压药"}""", "\"name\""),
            spec("record_symptom", "记录用户现在的一个不舒服的症状。",
                """"symptom":{"type":"string","description":"症状，例如 头晕、胃疼、发烧、咳嗽"}""", "\"symptom\""),
            spec("book_appointment", "帮用户预约挂号或复诊。",
                """"department":{"type":"string","description":"科室，用户说了才填，例如 消化内科、心内科"}""",
                ""),
            spec("notify_family", "给用户的家人发消息。",
                """"to":{"type":"string","description":"家人，例如 女儿、儿子、老伴、妈妈"},"message":{"type":"string","description":"要转告的内容"}""",
                "\"to\""),
            spec("ask_pharmacist", "用户在问用药问题，交给药师根据说明书回答。",
                """"question":{"type":"string","description":"用户的问题原文"}""", "\"question\""),
        )
    }
}
