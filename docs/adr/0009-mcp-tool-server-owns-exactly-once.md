# 0009 executor 通过 MCP 调用工具，只执行一次的保证放在工具服务里

状态：已采用

## 背景

工具（预约、通知、查号源）原本已经通过 MCP Server 暴露，但 agent 的 executor 不经过它，而是在进程内直接调用，tool_ledger 也在 agent 进程里。这带来两个问题：
- **"工具通过 MCP 暴露"只是一句话**：真正被用到的路径不是 MCP。
- **别的调用方拿不到同样的保证**：比如另一个 LLM planner、Claude 或 Cursor 通过 MCP 调用时，用的是 MCP Server 进程里一份单独的内存账本，和 agent 的账本不是同一份。

## 决定

- **新增 `tools` 服务**：用 MCP streamable HTTP 运行 `medsync_agent.mcp_server`，它独占 `tool_ledger`（Postgres），对外提供三个工具：`book_appointment`、`notify_family`、`check_slot`。
- **executor 只做 MCP 客户端**（`McpTools`）：
  - 有副作用的调用都带上 step_key。
  - 读号源也走 MCP。
  - agent 进程不再接触外部系统，也不再持有工具账本。
- **MCP 连接本身也可能丢响应**：工具服务已经执行了，但 agent 没收到回复。处理方式和第③跳一样：
  - 没收到回复就算"结果未知"，这一步停在 executor。
  - 下次用同一个 step_key 重试，工具服务的账本已经是 COMMITTED，直接返回原结果。
- **agent → tools 这段连接也经过 Toxiproxy**（`agent_tools`），可以和其他跳一样注入断连、丢响应。
- **单元测试和对比实验的基线**：用 `LocalTools` 在进程内执行。基线（B0–B2）本来就是"没有账本"的对照组，仍然直接调用外部系统。

## 后果

- **只执行一次的保证属于工具，而不属于调用方**：任何 MCP 客户端，只要带上同一个 step_key，就不会重复执行。工具说明里写明了"PENDING 时用同一个 step_key 重试"。
- **验证结果**：
  - 冒烟测试新增 2 项（MCP 连接断开后恢复；MCP 响应在发送消息后丢失），都只发出 1 条消息。
  - 单元测试覆盖了 MCP 响应丢失、外部系统响应丢失、号源被抢、工具服务不可达。
  - 对比实验经 MCP 重跑了一个缩小版（每个组合 2 次，128 个回合，结果在 `eval/reruns/`）：Full 模式重复副作用 0/24；三个基线分别是 50%、33%、33%，和正式结果一致；过期、号源被抢、契约变更都被拦下，仍然有效的照常执行。
- **代价**：
  - 多了一个服务和一段网络连接。
  - 每次工具调用都新建一个 MCP 会话（无状态 HTTP）。本机测查号源：直连 p50 1.1 ms，经 MCP 8.2 ms，每次多约 7 ms，相比真实外部系统的耗时可以忽略。

## 放弃的方案

- **stdio 子进程**：agent 自己拉起 MCP Server。少一个服务，但工具服务没法单独部署和扩容，别的 MCP 客户端也连不上同一个实例。
- **账本留在 agent、MCP Server 只做转发**：其他 MCP 客户端就拿不到"只执行一次"的保证，等于没解决问题。
