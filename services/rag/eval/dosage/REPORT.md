# MedTrack 固定题评测

openFDA 快照含 100 条版本记录，索引 4517 个段落。
共 14 题，每题每种模式运行 3 次。运行环境为 Darwin arm64, Python 3.12.16。

| 检索方式 | Recall@5 | 引用正确率 | P95 | 已选标签 P95 | 通过题数 |
|---|---:|---:|---:|---:|---:|
| keyword | 87.6% | 90.9% (10/11) | 3.18 ms | 3.18 ms | 10/14 |
| hybrid | 98.6% | 92.9% (13/14) | 7.14 ms | 7.14 ms | 13/14 |
| rerank | 100.0% | 100.0% (14/14) | 315.38 ms | 315.38 ms | 14/14 |

| 题型 | 总题数 | 关键词通过 | 混合通过 | 混合+重排通过 |
|---|---:|---:|---:|---:|
| dosage | 14 | 10 | 13 | 14 |

Recall@5 为可回答题的相关段落召回率宏平均。引用正确率按实际返回的引用计，引用须命中预先标注的段落且包含标注原文。可回答题漏答由通过题数体现，单独报告以免高拒答率抬高引用正确率。
P95 用预热后的进程内 FastAPI 请求计时，包含检索、引用选择和序列化。已选标签 P95 只统计进入段落检索路径的题。
同名题要求返回候选，未命中题和证据不足题要求返回对应状态。评测衡量当前快照中的证据覆盖，不衡量医学结论。
重排模式在混合检索前 30 个候选上用交叉编码器 `Xenova/ms-marco-MiniLM-L-6-v2` 重新打分，分数低于 -8.46 时拒答。阈值只在 `eval/validation.json`（30 题，说明书与本题集不重叠）上选定，没有用本题集调参。

## 重排答对、混合检索未答对

- **D10** What is the maximum daily dosage for major depressive disorder? · 标注 `dosage_and_administration:1:1, dosage_and_administration:1:3, dosage_and_administration:1:4` · 关键词 `indications_and_usage:1:1` · 混合 `dosage_and_administration:1:2` · 混合+重排 `dosage_and_administration:1:1`

## 混合检索答对、重排未答对

这组题中没有此类变化。

## 混合检索答对、关键词未答对

- **D03** How many capsules can an adult take per day? · 标注 `dosage_and_administration:1:1` · 关键词 `no_evidence` · 混合 `dosage_and_administration:1:1` · 混合+重排 `dosage_and_administration:1:1`
- **D06** What is the most I can take in one day? · 标注 `dosage_and_administration:1:1` · 关键词 `no_evidence` · 混合 `dosage_and_administration:1:1` · 混合+重排 `dosage_and_administration:1:1`
- **D11** When should it be taken in relation to breakfast? · 标注 `dosage_and_administration:1:1, dosage_and_administration:1:2` · 关键词 `no_evidence` · 混合 `dosage_and_administration:1:1` · 混合+重排 `dosage_and_administration:1:1`

## 关键词答对、混合检索未答对

这组题中没有此类变化。

## 三种方式都未通过

这组题中没有此类变化。

向量模型 `BAAI/bge-small-en-v1.5`。语料 SHA-256 `e80137d1d11381a34b28f185b6f5d16921eb1b20ac89e0379e4d0406d1087565`，处方药快照 SHA-256 `475f0ab9b6aa9cad4afceb5d1518ed262c81203e7e0d2b5ec491352f7c0ddf47`。题集 SHA-256 `996bf848b4fb5ac39c897b69bce1e8552f10ef664264940117ade65e632c5b14`。
