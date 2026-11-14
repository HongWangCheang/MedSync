package com.medsync.client.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeContentPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.medsync.client.app.MedSyncController
import com.medsync.client.data.ActionEntity
import com.medsync.client.outbox.ActionState
import com.medsync.client.outbox.Tools
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

@Composable
fun App(controller: MedSyncController) {
    val actions by controller.actions.collectAsState(emptyList())
    val offline by controller.offline.collectAsState()
    val redFlag by controller.redFlag.collectAsState()
    val notice by controller.notice.collectAsState()
    var input by remember { mutableStateOf("") }

    MaterialTheme {
        Surface(Modifier.fillMaxSize()) {
            Column(
                Modifier.fillMaxSize().safeContentPadding().padding(16.dp).widthIn(max = 720.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("MedSync", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
                    Text(if (offline) "离线（模拟）" else "在线", style = MaterialTheme.typography.labelLarge)
                    Spacer(Modifier.padding(4.dp))
                    Switch(checked = offline, onCheckedChange = controller::setOffline)
                    TextButton(onClick = { controller.syncNow() }) { Text("同步") }
                }

                redFlag?.let { flag ->
                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
                        Column(Modifier.padding(12.dp)) {
                            Text("检测到危险信号：「${flag.matched}」", style = MaterialTheme.typography.titleSmall)
                            Text(flag.advice)
                        }
                    }
                }

                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        value = input,
                        onValueChange = { input = it },
                        modifier = Modifier.weight(1f),
                        placeholder = { Text("例如：我吃了布洛芬，有点胃疼，帮我约周三复诊") },
                    )
                    Spacer(Modifier.padding(4.dp))
                    Button(onClick = { controller.submit(input); input = "" }, enabled = input.isNotBlank()) {
                        Text("发送")
                    }
                }
                notice?.let { Text(it, color = MaterialTheme.colorScheme.secondary) }

                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(actions.asReversed(), key = { it.actionId }) { action ->
                        ActionCard(action) { decision -> controller.resolve(action, decision) }
                    }
                }
            }
        }
    }
}

@Composable
private fun ActionCard(action: ActionEntity, onDecision: (JsonObject?) -> Unit) {
    val state = ActionState.valueOf(action.state)
    val payload = remember(action.payloadJson) { Json.parseToJsonElement(action.payloadJson).jsonObject }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(Tools.all[action.tool]?.label ?: action.tool, style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.weight(1f))
                AssistChip(onClick = {}, label = { Text(stateLabel(state)) })
            }
            Text(summary(action.tool, payload), style = MaterialTheme.typography.bodyMedium)
            val meta = buildList {
                if (action.attempt > 0) add("重试 ${action.attempt} 次")
                action.reason?.let { add(reasonLabel(it)) }
                add("step_key ${action.stepKey.take(10)}…")
            }
            Text(meta.joinToString(" · "), style = MaterialTheme.typography.labelSmall)
            if (state == ActionState.NEEDS_USER) {
                Spacer(Modifier.height(4.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    val options = remember(action.resultJson) { options(action.resultJson) }
                    if (options.isEmpty()) {
                        OutlinedButton(onClick = { onDecision(null) }) { Text("取消这一步") }
                    }
                    options.forEach { option ->
                        OutlinedButton(onClick = { onDecision(option) }) { Text(optionLabel(option)) }
                    }
                }
            }
        }
    }
}

private fun options(resultJson: String?): List<JsonObject> = runCatching {
    Json.parseToJsonElement(resultJson!!).jsonObject["options"]!!.jsonArray.map { it.jsonObject }
}.getOrDefault(emptyList())

private fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.contentOrNull

private fun summary(tool: String, p: JsonObject): String = when (tool) {
    "record_medication" -> "药物：${p.str("name")}"
    "record_symptom" -> "症状：${p.str("category")}（${p.str("severity")}）"
    "book_appointment" -> "${p.str("department")} · ${p.str("date")}"
    "notify_family" -> "发给${p.str("to")}：${p.str("message")}"
    "ask_pharmacist" -> p.str("question") ?: ""
    else -> p.toString()
}

private fun stateLabel(state: ActionState): String = when (state) {
    ActionState.PENDING -> "待发送"
    ActionState.BLOCKED -> "等待前一步"
    ActionState.SENDING -> "发送中"
    ActionState.RETRY_WAIT -> "等待重试"
    ActionState.ACKED -> "服务器处理中"
    ActionState.DONE -> "已完成"
    ActionState.NEEDS_USER -> "需要你确认"
    ActionState.FAILED -> "失败"
    ActionState.CANCELLED -> "已取消"
}

private fun reasonLabel(reason: String): String = when (reason) {
    "slot_full" -> "原定日期号源已满"
    "expired" -> "排队时间过长，请确认是否仍要执行"
    "tool_changed" -> "功能已更新，请重新确认"
    "parent_not_done" -> "前一步没有完成"
    "replayed", "reconciled" -> "已去重（$reason）"
    else -> reason
}

private fun optionLabel(option: JsonObject): String = when (option["decision"]?.jsonPrimitive?.contentOrNull) {
    "choose" -> "改约 ${option.str("date")}"
    "confirm" -> "仍然执行"
    "cancel" -> "取消"
    else -> option.toString()
}
