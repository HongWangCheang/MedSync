package com.medsync.client.app

import com.medsync.client.agents.PharmacistAnswer
import com.medsync.client.agents.RedFlag
import com.medsync.client.agents.RedFlagScreen
import com.medsync.client.agents.OnDeviceRouter
import com.medsync.client.agents.RuleBasedRouter
import com.medsync.client.agents.RuleRouter
import com.medsync.client.data.ActionEntity
import com.medsync.client.data.KvEntity
import com.medsync.client.data.MedSyncDatabase
import com.medsync.client.data.buildDatabase
import com.medsync.client.outbox.ActionEvent
import com.medsync.client.outbox.ActionState
import com.medsync.client.outbox.ActionStateMachine
import com.medsync.client.outbox.Planner
import com.medsync.client.outbox.StepDraft
import com.medsync.client.sync.DrainReport
import com.medsync.client.sync.GatewayApi
import com.medsync.client.sync.KtorGatewayApi
import com.medsync.client.sync.SyncEngine
import androidx.room.RoomDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlin.time.Clock
import kotlin.time.Instant
import kotlin.uuid.Uuid

/** Everything the UI needs; identical on Android, iOS and desktop. */
class MedSyncController(
    db: MedSyncDatabase,
    gatewayUrl: String,
    private val scope: CoroutineScope,
    private val clock: () -> Long = { Clock.System.now().toEpochMilliseconds() },
    api: GatewayApi? = null,
    /** On-device router: rules by default; a platform can pass a model with rule fallback ([FallbackRouter]). */
    private val router: OnDeviceRouter = RuleBasedRouter,
    /** Danger signs: rules alone by default; a platform can add its on-device model as a second opinion. */
    private val redFlags: RedFlagScreen = RedFlagScreen(),
) {
    private val dao = db.actions()
    private val kv = db.kv()
    private val api: GatewayApi = api ?: KtorGatewayApi(
        baseUrl = gatewayUrl,
        loadToken = { kv.get("token")?.ifBlank { null } },
        saveToken = { kv.put(KvEntity("token", it)) },
        newCredentials = { "dev_${Uuid.random().toHexString().take(12)}" to Uuid.random().toString() },
    )
    val engine = SyncEngine(dao, this.api)

    val actions: Flow<List<ActionEntity>> = dao.observeAll()
    private val _offline = MutableStateFlow(false)
    val offline: StateFlow<Boolean> = _offline
    val redFlag = MutableStateFlow<RedFlag?>(null)
    /** What works offline, for the panel under the title. */
    val capabilities: List<Capability> =
        Capabilities.of(router.takeIf { it !== RuleBasedRouter }?.name?.substringBefore('+'))
    val notice = MutableStateFlow<String?>(null)
    val lastSync = MutableStateFlow<DrainReport?>(null)

    private suspend fun deviceId(): String =
        kv.get("device_id") ?: Uuid.random().toString().also { kv.put(KvEntity("device_id", it)) }

    fun submit(text: String) = scope.launch {
        val input = text.trim()
        if (input.isEmpty()) return@launch
        // Danger signs first, fully offline, before anything else happens: the rules at once, then the model for
        // what the rules let through. The model can add an alert, never remove one.
        redFlag.value = redFlags.rules(input)
        if (redFlag.value == null && redFlags.hasModel) {
            notice.value = CHECKING
            redFlag.value = redFlags.second(input)
            if (notice.value == CHECKING) notice.value = null
        }
        val now = clock()
        val today = Instant.fromEpochMilliseconds(now).toLocalDateTime(TimeZone.currentSystemDefault()).date
        val conversation = PharmacistAnswer.followUp(dao.all(), now)
        if (router !== RuleBasedRouter) notice.value = "本机模型理解中…"
        var routed = router.route(input, today, now)
        if (notice.value == "本机模型理解中…") notice.value = null
        if (routed.steps.isEmpty() && conversation?.awaitingChoice == true) {
            // The pharmacist asked "which product?"; a bare reply like "ADVIL" answers that question.
            routed = RuleRouter.Routed(listOf(StepDraft("ask_pharmacist", JsonObject(mapOf(
                "question" to JsonPrimitive(input))))), question = true)
        }
        if (routed.question && conversation != null) {
            val step = routed.steps.single()
            routed = routed.copy(steps = listOf(step.copy(payload = JsonObject(
                step.payload + ("session_id" to JsonPrimitive(conversation.sessionId))))))
        }
        when {
            routed.steps.isEmpty() -> notice.value = if (redFlag.value != null) null
                else "没有识别出要做的事。可以试试：“我吃了布洛芬，有点胃疼，帮我约周三复诊”"
            routed.question && _offline.value -> notice.value =
                "用药问答需要联网检索说明书。离线时不回答，避免给出没有依据的建议。"
            else -> {
                dao.insertAll(Planner.plan(routed.steps, deviceId(), now))  // one transaction for the whole plan
                notice.value = if (_offline.value) SAVED_OFFLINE else null
                if (!_offline.value) drain()
            }
        }
    }

    /** The user tapped one of the products the pharmacist offered. */
    fun choose(answer: PharmacistAnswer, choice: com.medsync.client.agents.Choice) = scope.launch {
        if (_offline.value) {
            notice.value = "用药问答需要联网检索说明书。"
            return@launch
        }
        dao.insertAll(Planner.plan(listOf(PharmacistAnswer.choiceStep(choice, answer.sessionId)), deviceId(), clock()))
        drain()
    }

    fun setOffline(value: Boolean) {
        _offline.value = value
        if (!value) {
            if (notice.value == SAVED_OFFLINE) notice.value = null  // stale once the queue starts syncing
            syncNow()
        }
    }

    fun syncNow() = scope.launch { drain() }

    /** Server-side NEEDS_USER (has options) goes back through the gateway; a local cascade is cancelled locally. */
    fun resolve(action: ActionEntity, decision: JsonObject?) = scope.launch {
        if (decision == null) {
            val next = ActionStateMachine.next(ActionState.valueOf(action.state), ActionEvent.Cancelled)
            dao.update(action.copy(state = next.name, reason = "cancelled_by_user"))
            return@launch
        }
        if (_offline.value) {
            notice.value = "需要联网才能提交你的选择"
            return@launch
        }
        engine.resolve(action, decision, clock())
        drain()
    }

    fun startLoop(intervalMs: Long = 10_000) = scope.launch {
        while (isActive) {
            drain()
            delay(intervalMs)
        }
    }

    private suspend fun drain() {
        if (_offline.value) return
        runCatching { engine.drainOnce(clock()) }
            .onSuccess { lastSync.value = it }
            .onFailure { notice.value = "同步出错：${it.message}" }
    }
}

private const val SAVED_OFFLINE = "已保存在本机，联网后自动同步"
private const val CHECKING = "本机模型检查危险信号…"

/** One controller per process, shared by the UI and background schedulers (e.g. Android WorkManager). */
object MedSyncApp {
    var controller: MedSyncController? = null
        private set

    fun init(builder: RoomDatabase.Builder<MedSyncDatabase>, gatewayUrl: String,
             router: OnDeviceRouter = RuleBasedRouter, redFlags: RedFlagScreen = RedFlagScreen()): MedSyncController =
        controller ?: MedSyncController(
            db = buildDatabase(builder),
            gatewayUrl = gatewayUrl,
            scope = CoroutineScope(SupervisorJob() + Dispatchers.Default),
            router = router,
            redFlags = redFlags,
        ).also {
            controller = it
            it.startLoop()
        }
}
