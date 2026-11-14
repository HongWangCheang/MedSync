# MedTrack 离线记录同步

Android 的 Debug 版在 Home 页面提供 **Connect sync**。它使用独立的同步账号，原有 MedTrack 本地账号仍负责进入 App。链接后，新建用药计划和症状记录先写入 Room，同一事务中持久化待发送记录和 UUID。WorkManager 在可联网时按序上传，网络失败、超时、限流或服务端错误会指数退避重试。页面显示待同步数、重试、暂停、登录过期和成功状态，也可以点 **Sync now** 拉取变化。

演示仅使用合成记录。未链接前的既有记录、每日服药勾选和提醒属于本地数据。当前同步协议处理新增，账号绑定后可以暂停或用同一账号恢复。下行变更使用每个账号的递增游标分页，写入本地记录与游标在同一个 Room 事务中完成。上行与下行共享记录 ID，拉回本机刚上传的记录时不会再次插入。

## 启动

需要 JDK 21 和 Docker Compose。仓库自带 Maven Wrapper。在工程根目录执行以下命令。

```sh
export MEDTRACK_SYNC_DB_PASSWORD="$(openssl rand -hex 16)"
docker compose -f sync-server/compose.yaml up -d --wait
./sync-server/mvnw -f sync-server/pom.xml spring-boot:run
```

首次初始化 MySQL 时创建用户密码。复用同一个 Docker 卷时请沿用最初设置的密码。已有 MySQL 时也可先建空库，设置 `MEDTRACK_SYNC_DB_URL`、`MEDTRACK_SYNC_DB_USER`、`MEDTRACK_SYNC_DB_PASSWORD`，再启动应用。服务端默认绑定宿主机 `127.0.0.1:8081`，Android 模拟器使用 `10.0.2.2:8081`。说明书问答仍通过独立的 FastAPI 服务运行，端口为 8765。

在模拟器安装 Debug App，用合成本地资料登录，进入 **Home → Connect sync → Create account**。连接后可在模拟器关网，添加一条用药计划和症状，返回 Home 查看队列。恢复网络后，待同步数应归零。同一同步账号在第二台模拟器登录，点击 **Sync now** 可以拉取这些记录。

## HTTP 接口

| 方法和路径 | 请求 | 响应 |
|---|---|---|
| `POST /v1/auth/register` | `{"username":"demo-user","password":"your-demo-password"}` | 201，`{"accountId":"…","token":"…"}`。重名 409。 |
| `POST /v1/auth/login` | 同注册 | 200，同上。凭据错误 401。 |
| `PUT /v1/sync/writes/{requestId}` | Bearer token、UUID 请求 ID 和下方记录 JSON | 200，`{"revision":1}`。同一请求和载荷重放返回原 revision，已用请求 ID 的不同载荷或重复记录 ID 返回 409。 |
| `GET /v1/sync/changes?after=0&limit=50` | Bearer token，非负游标，页大小 1–100 | 200，`{"changes":[{"recordId":"…","kind":"…","body":{},"revision":1}],"nextCursor":1,"hasMore":false}`。 |

```json
{
  "recordId": "9bc7aa13-00a7-43e5-82af-15e759d67fd3",
  "kind": "medication",
  "body": {
    "name": "Synthetic plan",
    "dosage": "fixture",
    "frequency": "fixture",
    "time": "09:00",
    "type": "fixture",
    "notes": ""
  }
}
```

`symptom` 的 `body` 含 `category`、`severity`、`dateTime`、`notes`，全部是字符串。登录 token 有效期 7 天，服务端存储其摘要，Android 用 Keystore 加密后保存。该 Demo 使用回环 HTTP，适用于本地合成数据演示。

## 超时重试测试

给集成测试准备一个独立的 MySQL 数据库和该库专用账号。测试会用随机账号写入合成记录，请勿指向业务库。设置 `MEDTRACK_SYNC_TEST_DB_URL`、`MEDTRACK_SYNC_TEST_DB_USER`、`MEDTRACK_SYNC_TEST_DB_PASSWORD`，然后在工程根目录运行以下命令。

```sh
./sync-server/mvnw -f sync-server/pom.xml test
```

测试通过真实 HTTP 和 MySQL 运行。第一次写入提交后，测试过滤器暂扣 HTTP 响应。它从另一条数据库连接查到记录已存在，等客户端收到超时异常，再用同一个请求 ID 重试。重试返回原 revision，MySQL 中只有一条业务记录和一条请求凭证，增量接口只返回一条变更。另一个测试验证并发重试、分页以及不同账号隔离。

数据库主键 `(account_id, request_id)` 约束请求唯一，主键 `(account_id, record_id)` 约束业务记录唯一。服务端将请求凭证、业务记录和游标更新放在同一个事务，并锁住账号行来串行分配 revision。Android 一直使用 Room 队列中的原始 UUID，收到服务端成功响应后才移除待发送项。

模拟器的端到端用例需要 Java 服务监听 8081。启动后可以运行 `./gradlew :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.hongwang.medtrack.SyncDeviceTest`。

本次验证使用 MySQL 8.4.11 和 Android API 36 模拟器。两个 Java 集成测试、两个 Android 设备测试以及 Android Debug 构建和单元测试均通过。Android 设备测试覆盖 Room 3→4 数据保留，以及暂停时排队、重新连接后上传并拉取另一端记录。
