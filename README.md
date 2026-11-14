# MedSync

弱网环境下端云协同的用药管理多智能体系统。客户端是一套 Kotlin Multiplatform 代码，覆盖 **Android、iOS 和桌面（macOS / Windows / Linux）**。

核心问题：Agent 有副作用的操作，在**断网、超时、重试、进程被杀、LLM 重新推理**时，要做到端到端**只执行一次**；排队期间情况变了的动作，要能被拦下来。

```
客户端 (Android / iOS / 桌面，KMP 共享代码)
  路由 Agent · 危险信号 Agent · Room outbox（step_key 在规划时生成并落库）
        │ ① Toxiproxy :18081
        ▼
gateway (Spring Boot + MyBatis + MySQL + Redis)        action_ledger：同 key 同内容→重放，同 key 不同内容→409
        │ ② Toxiproxy :18000
        ▼
agent (FastAPI + LangGraph + Postgres)                 一个 step = 一个 LangGraph 线程；revalidate → executor
        │ ③ Toxiproxy :19000                           tool_ledger：INTENT → COMMITTED，结果不明时先按 step_key 查
        ▼
mocks (模拟医院预约 / 家属通知)                         故意不去重；/metrics/side_effects 是评测的唯一依据
```

## 目录

| 目录 | 内容 |
|---|---|
| [client/](client/) | KMP 客户端：`shared`（业务逻辑 + Compose UI）、`androidApp`、`iosApp`、`desktopApp` |
| [services/gateway/](services/gateway/) | 同步网关，在 MedTrack sync-server 基础上新增 `action_ledger` 和 `/v1/actions` |
| [services/agent/](services/agent/) | Agent 服务：LangGraph 图、tool ledger、MCP Server |
| [services/mocks/](services/mocks/) | 模拟外部系统，带副作用计数和"提交后响应丢失"故障 |
| [services/rag/](services/rag/) | 从 MedTrack 拷贝的说明书 RAG + Gemini 问答 Agent，供药学问答步骤调用 |
| [chaos/](chaos/) | Toxiproxy 三跳配置和故障注入脚本 |
| [scripts/smoke.py](scripts/smoke.py) | 端到端冒烟测试 |
| [eval/](eval/) | 对比实验：B0 朴素重试 / B1 请求级幂等 / B2 参数哈希去重 / Full，报告见 [eval/report.md](eval/report.md) |
| [docs/开发计划.md](docs/开发计划.md) | 分阶段开发计划 |

## 启动服务端

```sh
cp .env.example .env          # 填三个数据库密码；要回答用药问题再填 GEMINI_API_KEY
docker compose up --build -d
python3 scripts/smoke.py      # 6 项检查：重放、409、响应丢失、Agent 不可达、号源被抢、无重复副作用
```

| 地址 | 用途 |
|---|---|
| `127.0.0.1:18081` | 客户端入口（经过 Toxiproxy 第①跳）。Android 模拟器用 `10.0.2.2:18081` |
| `127.0.0.1:8474` | Toxiproxy 控制 API，`python3 chaos/toxic.py list` |
| `127.0.0.1:9100` | mocks，直连无故障，评测用来读真实副作用 |
| `127.0.0.1:8091` / `8100` | gateway / agent 直连，仅调试 |

端口避开了 MedTrack（8081、8765），两套可以同时运行。

### 故障注入

```sh
python3 chaos/toxic.py down gateway_agent          # 第②跳断开
python3 chaos/toxic.py latency device_gateway 3000 # 第①跳慢网
python3 chaos/toxic.py reset agent_external        # 第③跳连接被重置
python3 chaos/toxic.py clear
# "医院已提交、响应丢失"：Toxiproxy 无法只针对单个接口，所以这个故障由 mocks 提供
curl -X POST 127.0.0.1:9100/admin/faults -H 'Content-Type: application/json' \
     -d '{"path": "/hospital/bookings", "delay_s": 8}'
```

## 对比实验

640 个故障注入回合，以模拟外部系统记录的实际副作用次数为准：

| | B0 朴素重试 | B1 请求级幂等 | B2 参数哈希去重 | **Full** |
|---|---|---|---|---|
| 重复副作用率 IVR | 50% | 33% | 33% | **0%** |
| 过期 / 契约变更的动作被执行 | 20/20 | 20/20 | 20/20 | **0/20** |

完整结果、消融实验和局限见 [eval/report.md](eval/report.md)，复现：

```sh
docker compose -f docker-compose.yml -f eval/compose.experiment.yml up -d --build
python3 eval/run_experiment.py --reps 10
uv run --with matplotlib python eval/report.py
```

## 运行客户端

需要 JDK 21。

```sh
cd client
./gradlew :desktopApp:run                 # 桌面端（macOS / Windows / Linux）
./gradlew :androidApp:installDebug        # Android（先启动模拟器）
./gradlew :desktopApp:packageDistributionForCurrentOS   # 打包 .dmg / .msi / .deb
./gradlew :shared:jvmTest                 # 共享逻辑的单元测试
```

**iOS**：需要完整的 Xcode（只有 Command Line Tools 不够）。用 Xcode 打开 `client/iosApp/iosApp.xcodeproj` 运行即可，构建时会自动调用 Gradle 编译 `shared` 框架。真机运行需要在 `client/iosApp/Configuration/Config.xcconfig` 里填 `TEAM_ID`。

**用药问答**：例如输入"布洛芬能和阿司匹林一起吃吗？"。在线时，这个问题由 `services/rag` 检索 openFDA 说明书后回答，答案里的 [S1] 会高亮，点开能看到原文摘录。找不到可引用的原文时会直接拒答。

同一个药名可能对应多个产品，这时会先反问是哪一款；直接回复产品名（例如 `ADVIL`）就会接着回答。10 分钟内的追问（例如"它一天最多吃几片？"）也会接着同一段对话。没有配置 `GEMINI_API_KEY` 时，这一步会失败并显示"药学服务未配置"。

界面右上角的开关可以**模拟离线**。离线时：记录服药和症状会直接保存在本机；预约、通知家属进入队列；用药问答会被拒绝（没有说明书依据就不回答）；危险信号识别始终在本机完成。

## 测试

```sh
cd services/gateway && ./mvnw -q -Dtest='ActionLedgerTest,RedisFallbackTest' test   # 11 项
cd services/agent   && uv run pytest -q                                            # 31 项
cd services/mocks   && uv run pytest -q                                            # 4 项
cd client           && ./gradlew :shared:jvmTest                                   # 共享逻辑 18 项
python3 scripts/smoke.py                                                           # 端到端，需要 Compose 在运行
cd client && MEDSYNC_LIVE=1 ./gradlew :shared:jvmTest   # 再加 2 项：真实 Ktor 客户端 → 三跳 → mocks / RAG
```

## 来源

- `services/gateway`、`services/rag` 拷贝自 MedTrack，网关的包名改成了 `com.medsync.gateway`。
- `client/` 基于 JetBrains 官方 [Kotlin/KMP-App-Template](https://github.com/Kotlin/KMP-App-Template)（Apache 2.0，见 `client/LICENSE`），去掉了 Web 端和示例代码。
