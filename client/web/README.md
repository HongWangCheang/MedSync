# MedSync Web（React）

浏览器版客户端，可以离线使用：断网时说的话先存在浏览器里，联网后按顺序同步。只执行一次的保证，和 Android、iOS、桌面端完全一样。

```sh
scripts/up.sh                          # 先启动后端（在仓库根目录）
cd client/web && npm install && npm run dev    # http://localhost:5173
npm test                               # 核心逻辑单元测试
npm run build && npm run preview       # 生产构建
```

开发服务器把 `/v1` 转发到网关的第①跳（Toxiproxy `:18081`）。网页和手机走同一条链路，也会遇到同样的故障注入。如果要连到别的网关，设置 `MEDSYNC_GATEWAY` 即可。

## 和 Kotlin 客户端的关系

核心逻辑从 `client/shared` 逐个移植过来，都放在 `src/core/`，和 UI 分开：

| 模块 | 对应的 Kotlin |
|---|---|
| `stepKey.ts`：规划时生成 step_key | `outbox/StepKey.kt` |
| `planner.ts`、`tools.ts`、`state.ts`：outbox 行、工具表、状态机 | `outbox/` |
| `store.ts`：IndexedDB；一句话拆出的所有动作在同一个事务里写入 | `data/Database.kt`（Room） |
| `sync.ts`：按依赖顺序上传、指数退避重试、父步骤失败时级联 | `sync/SyncEngine.kt` |
| `gateway.ts`：调用网关 | `sync/GatewayApi.kt` |
| `router.ts`：规则路由 | `agents/RuleRouter.kt` |
| `redflag.ts`：危险信号规则，包括心理危机护栏 | `agents/RedFlagDetector.kt` |
| `results.ts`：解析药学回答、安全审核、冲突和选项 | `agents/`、`ui/App.kt` |

**step_key 和 Kotlin 逐字节一致**：`core.test.ts` 和 `OutboxTest.kt` 用的是同一组测试向量，覆盖中文、数字、转义字符和键的顺序。同一个动作，不管在网页上还是手机上规划，算出来的键都一样，网关、Agent、工具三处都按它去重。

**和 App 的差别**：网页没有端侧模型，理解句子和判断危险信号都只靠规则，也就是路由评测里"规则"那一列的水平。

## 界面

- **时间线**：按"你说的那句话"分组，下面是拆出来的动作。动作之间的依赖画成连线，比如"等「记录服药」处理完再发"。
- **状态**：每个动作的状态用彩色标签表示。需要你确认的动作有单独的筛选标签，并显示数量。
- **危险信号**：置顶的红色横幅，可以一键拨打 120；涉及心理危机时还会给出 12356 热线。
- **离线**：顶栏和"断网时各项功能"面板会切换成离线配色，面板自动展开。
- **药学回答**：回答里的 [S1] 可以点开，看说明书原文。
- **安全审核**：提醒附上引用的原文，并说明对照了哪些药、哪些药没认出、哪些药没有说明书可查。
- **适配**：支持浅色和深色主题；手机宽度下单栏显示，1024 px 以上右侧显示说明栏。
