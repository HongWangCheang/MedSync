# MedTrack 说明书检索与问答

FastAPI 从固定的 openFDA 公开标签快照检索证据。选择具体产品版本后，可以用英文输入问题，对比三种模式：关键词（SQLite FTS5 / BM25）、混合检索（BM25 + BGE 向量检索，以加权 RRF 融合）、混合+重排（在混合检索前 30 个候选上用交叉编码器重新打分，`mode: "rerank"`）。答案使用原文摘录，附有章节和可打开的版本出处。找不到产品、需要选择同名产品、找不到支撑段落时返回不同状态。默认仍是关键词模式：它的引用正确率最高、延迟约 1.5 ms；重排模式答对的题最多，但 P95 约 200 ms。

## 启动

在 Android 工程根目录执行。建议用 Python 3.12。

```sh
python3.12 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -r backend/requirements-dev.txt
python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8765
```

首次启动下载 BAAI/bge-small-en-v1.5 向量模型和 Xenova/ms-marco-MiniLM-L-6-v2 重排模型并构建向量缓存，后续问答在本地执行。可以用 `MEDTRACK_CACHE_DIR` 指定其他缓存目录。API 文档位于 http://127.0.0.1:8765/docs。打开 Android 模拟器里的 Debug 版 **Coach**，搜 **Tylenol Extra Strength**，选一个版本后点击 **Storage**，再用两种检索分别提交同一个问题。演示页不读取患者记录。查询仅提供说明书摘录。通过 `MEDTRACK_SYNTHETIC_LABELS=1` 可单独用虚构标签演示，搜索 **MedTrack Demo**。

```sh
curl 'http://127.0.0.1:8765/v1/labels?q=Tylenol'
curl -X POST http://127.0.0.1:8765/v1/answer \
  -H 'Content-Type: application/json' \
  -d '{"drug_name":"Tylenol Extra Strength","question":"What does the label say about storage?","mode":"hybrid"}'
```

重名时返回 `needs_selection` 和候选。选中后用 `label_id` 与 `version` 替代 `drug_name`。响应中的 `retrieved` 可检查前五个候选段落，`sources` 是最终引用。`no_match` 表示当前快照无此产品或版本，`no_evidence` 表示未达到证据阈值。

## 数据和评测

- [快照](data/openfda_labels.json)包含 48 条版本记录，采集于 2026-11-13。数据取自 openFDA 药品标签 API 的公开样本，保留原始 ID、版本和选定章节。样本有意包含同名产品与不同厂商，覆盖范围以快照为准。
- [openFDA 官方下载](https://open.fda.gov/apis/drug/label/download/)提供同结构的批量 JSON。可用 `python backend/label_corpus.py --output /path/to/snapshot.json /path/to/drug-label.json.zip` 生成自定义快照，再用 `MEDTRACK_CORPUS=/path/to/snapshot.json` 启动。当前向量索引放在内存，建议先用 `--selection backend/data/openfda_labels.json` 或另一份同结构清单限定目标版本。
- **用法用量章节（MedSync 补采）**：MedTrack 原快照没有保留 `dosage_and_administration`（OTC 的 "Directions" 和处方药的用法用量都在这个字段）。`python backfill_sections.py dosage_and_administration` 按快照里的 id 和版本从 openFDA API 补采这一个字段，只有版本一致才写入，出处记录在快照的 `backfills` 里。48 个版本全部补上，段落数从 917 增加到 1020。
- [14 道用法用量题](eval/dosage_questions.json)：`python -B evaluate.py --questions eval/dosage_questions.json --output-dir eval/dosage` 写出 [报告](eval/dosage/REPORT.md)。补采前三种模式都是 0/14；补采后关键词 9/14、混合 13/14、重排 14/14。补采后固定 50 题的答对数不变，混合检索的 Recall@5 从 1.000 降到 0.969。
- [50 道固定题](eval/questions.json)包含 32 道可回答题和 18 道同名、无匹配及证据不足题。运行 `python -B backend/evaluate.py` 会重写 [结果报告](eval/REPORT.md) 和 [逐题 JSON](eval/results.json)。运行 `python -B -m unittest discover -s backend -v` 执行回归测试。模型需要已下载或可联网下载。
- 重排阈值只在 [30 道验证题](eval/validation.json)上选定。验证题使用的说明书与 50 道测试题不重叠，运行 `python -B backend/tune_rerank.py` 可复现阈值搜索。重排模型也是按验证集选的：MiniLM-L-6 通过 27/30，bge-reranker-base 通过 26/30 且慢约 5 倍。可用 `MEDTRACK_RERANK_MODEL`、`MEDTRACK_RERANK_MIN_SCORE`、`MEDTRACK_RERANK_POOL` 覆盖默认值。
- 三种模式共享同一套题目、标签和摘录逻辑。端到端手机网络、首次加载和外部模型调用延迟不在评测计时内。

## 既有接口

FastAPI 保留 `/labels`、`/answer` 和 `/clinician/insights` 以支持旧调用。Clinician Dashboard 的 Gemini 配置继续使用 `backend/.env.local` 或环境变量。新版说明书检索和评测无需 Gemini 密钥。`python3 backend/medtrack_server.py` 只启动旧版后端，它只有这三个旧接口，没有 `/v1/labels`、`/v1/answer` 和 `/v1/agent/chat`。新版 App 的说明书查询页和 Ask 页连上它会报 “Endpoint not found.”，请用上面的 uvicorn 命令或 `docker compose up -d` 启动。

## 用药问答 Agent

`POST /v1/agent/chat` 是一个基于 Gemini Function Calling 的多轮问答 Agent，以 SSE 流式返回事件。代码在 [agent.py](agent.py)。

```sh
curl -N -X POST http://127.0.0.1:8765/v1/agent/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Can I take Zoloft with an MAOI?"}'
```

- **工具**：`search_label` 复用上面的说明书检索（加载了重排模型时用 `rerank` 模式）；`get_my_medications` 带着用户的 `Authorization` 头读取 sync-server 里该用户的用药记录，token 不会发给模型；`check_interaction` 在一份说明书的禁用、询问医生、相互作用等章节里查找另一种药或其成分（会从快照里展开通用名），只报告“提到 / 未提到”。未提到时明确说明这不代表可以合用。
- **循环**：模型调用工具 → 执行 → 结果喂回模型，最多 5 步，超过就停止并拒答。
- **记忆**：会话存在 SQLite（`MEDTRACK_AGENT_DB`，默认在内存），按 token 的 SHA-256 绑定用户，别人拿到 `session_id` 也读不到。保留最近 6 轮原文，更早的轮次由 Gemini 压缩成摘要；当前讨论的药会写进系统提示，所以追问“它能和 X 一起吃吗”能指回上一个药。
- **引用校验**：工具返回的每个段落都会分到一个会话内编号（S1、S2…），模型只能用这些编号引用。回答引用了不存在的编号，或者本轮已检索到证据却不引用，或者一个工具都没调就直接回答，都会被替换成固定的拒答。
- **流式事件**：`session`、`tool_call`、`tool_result`、`answer`、`done`（出错时为 `error`）。工具调用进度实时推送；回答正文要先过引用校验，所以在校验通过后才整段发送，不按 token 流式输出。这是医疗场景下有意的取舍。
- **评测**：`python -B backend/eval_agent.py` 用真实 Gemini 跑 [12 段多轮对话](eval/agent_scenarios.json)，写出 [AGENT_REPORT.md](eval/AGENT_REPORT.md)。登录用户的用药记录用固定夹具代替 sync-server。单元测试 [test_agent.py](test_agent.py) 用脚本化的假模型覆盖工具调用、引用校验、记忆、会话隔离和 SSE。

## 微调嵌入模型

[finetune/](finetune/README.md) 里是在说明书语料上微调 bge-small 的完整流程：按说明书划分数据并去重防泄露、用 Gemini 生成训练问题、挖掘困难负样本、按验证集选轮数、导出 ONNX 接回 fastembed。hybrid 模式的引用正确率从 59.3% 提升到 65.4%（通过题数 32 → 33），rerank 模式不受影响。提升不显著，所以线上默认仍用基座模型。
