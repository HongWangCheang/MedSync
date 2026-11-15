# 多 Agent 场景 × 故障矩阵

由 `eval/run_matrix.py` 生成，每格重复 3 次。格子里是“所有检查都通过”的回合数；没有全部通过的格子，下面列出没过的检查。方法见脚本开头的说明。

| 场景 \ 故障 | none | hop1_lost | hop2_lost | hop2_down | rag_down | mcp_lost | agent_crash | tools_crash |
|---|---|---|---|---|---|---|---|---|
| safety_alert | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | — | ✅ 3/3 | — |
| conflict_pause | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |

— 表示这个故障碰不到这个场景（安全提醒不调用 MCP 工具）。

每项检查的通过次数：

**safety_alert**

| 故障 | step_done | alert_raised | finding_posted_once |
|---|---|---|---|
| none | 3/3 | 3/3 | 3/3 |
| hop1_lost | 3/3 | 3/3 | 3/3 |
| hop2_lost | 3/3 | 3/3 | 3/3 |
| hop2_down | 3/3 | 3/3 | 3/3 |
| rag_down | 3/3 | 3/3 | 3/3 |
| agent_crash | 3/3 | 3/3 | 3/3 |

**conflict_pause**

| 故障 | alert_raised | finding_posted_once | message_paused | nothing_sent_while_paused | decision_done | sent_exactly_once | warning_attached |
|---|---|---|---|---|---|---|---|
| none | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| hop1_lost | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| hop2_lost | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| hop2_down | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| rag_down | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| mcp_lost | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| agent_crash | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |
| tools_crash | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 |

## 这个矩阵发现并修好的问题

第一次跑的时候，conflict_pause × agent_crash 和 conflict_pause × tools_crash 都是 0/3。消息确实只发出了 1 次，而且附上了提醒，但这一步一直停在"需要你确认"。

**原因**：
1. 用户选了"附上提醒再发"，发送途中 agent 或工具服务被杀，网关没拿到结果，就把这一步留在"需要你确认"。
2. App 再发一次这个决定。重启后的 agent 发现决定已经用过了（没有待回答的问题，也还没有结果），就返回 409。
3. "需要你确认"的步骤不会被重新派发，所以这一步卡住了。App 还会再给用户看一次选项，可是消息其实已经发出去了。

**修复**（两边都改）：
- 网关收到决定后，立刻把这一步改回"处理中"。agent 的结果丢了，下次轮询会重新派发，App 不会再给一个已经做过的决定显示选项（`ActionService.resume`）。
- agent 收到重复的决定时，把第一次的决定执行完，而不是返回 409。第一次的决定可能已经在执行，不能换成另一个（`StepRunner._resume`）。

两边都加了回归测试。上面的表是修复后重跑的结果。

