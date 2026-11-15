# 架构决定记录（ADR）

每篇记录一个关键决定：背景、决定、后果、放弃的方案。架构总览见 [../architecture.md](../architecture.md)。

- [0001](0001-step-key-across-three-hops.md) 一个 step_key 贯穿三跳
- [0002](0002-intent-committed-ledger.md) executor 双阶段记账：INTENT → COMMITTED
- [0003](0003-revalidate-with-interrupt.md) 排队的动作执行前先复核，有变化就问用户
- [0004](0004-small-model-understands-code-decides.md) 端侧小模型只负责理解，确定性的部分交给代码
- [0005](0005-red-flags-rules-first.md) 危险信号：规则先判断，模型只能补充
- [0006](0006-no-offline-medical-answers.md) 离线时不回答用药问题
- [0007](0007-findings-board-conflicts.md) 跨 Agent 冲突：发现板 + 不可逆动作前检查
- [0008](0008-delegated-read-token.md) 药学 Agent 用委托令牌读用药清单
- [0009](0009-mcp-tool-server-owns-exactly-once.md) executor 通过 MCP 调用工具，只执行一次的保证放在工具服务里
