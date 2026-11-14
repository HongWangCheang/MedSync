# MedTrack 固定题评测（微调向量模型）

> 向量模型为 `finetune/models/bge-small-medtrack-onnx`，hybrid 作答阈值 `MEDTRACK_SEMANTIC_MIN_SCORE=0.46`（只在验证集上选定）。对照组是 [../REPORT.md](../REPORT.md) 里的基座模型（阈值 0.60）。说明见 [finetune/README.md](../../finetune/README.md)。

openFDA 快照含 48 条版本记录，索引 917 个段落。
共 50 题，每题每种模式运行 3 次。运行环境为 Darwin arm64, Python 3.12.16。

| 检索方式 | Recall@5 | 引用正确率 | P95 | 已选标签 P95 | 通过题数 |
|---|---:|---:|---:|---:|---:|
| keyword | 75.0% | 90.9% (10/11) | 1.49 ms | 1.43 ms | 28/50 |
| hybrid | 95.3% | 65.4% (17/26) | 4.95 ms | 4.97 ms | 33/50 |
| rerank | 93.8% | 85.7% (18/21) | 196.39 ms | 197.71 ms | 36/50 |

| 题型 | 总题数 | 关键词通过 | 混合通过 | 混合+重排通过 |
|---|---:|---:|---:|---:|
| answerable | 32 | 10 | 17 | 18 |
| same_name | 6 | 6 | 6 | 6 |
| no_match | 6 | 6 | 6 | 6 |
| insufficient_evidence | 6 | 6 | 4 | 6 |

Recall@5 为可回答题的相关段落召回率宏平均。引用正确率按实际返回的引用计，引用须命中预先标注的段落且包含标注原文。可回答题漏答由通过题数体现，单独报告以免高拒答率抬高引用正确率。
P95 用预热后的进程内 FastAPI 请求计时，包含检索、引用选择和序列化。已选标签 P95 只统计进入段落检索路径的题。
同名题要求返回候选，未命中题和证据不足题要求返回对应状态。评测衡量当前快照中的证据覆盖，不衡量医学结论。
重排模式在混合检索前 30 个候选上用交叉编码器 `Xenova/ms-marco-MiniLM-L-6-v2` 重新打分，分数低于 -8.46 时拒答。阈值只在 `eval/validation.json`（30 题，说明书与本题集不重叠）上选定，没有用本题集调参。

## 重排答对、混合检索未答对

- **Q03** Does the carton mention using a second acetaminophen product? · 标注 `do_not_use:1:1` · 关键词 `warnings:1:1` · 混合 `active_ingredient:1:1` · 混合+重排 `do_not_use:1:1`
- **Q09** What does the label say if the problem gets worse or persists for a week? · 标注 `stop_use:1:1` · 关键词 `no_evidence` · 混合 `no_evidence` · 混合+重排 `stop_use:1:1`
- **Q11** Which active ingredient is listed for the caplets? · 标注 `active_ingredient:1:1, active_ingredient:3:1` · 关键词 `active_ingredient:3:1` · 混合 `inactive_ingredient:3:1` · 混合+重排 `active_ingredient:3:1`
- **Q13** Where does the label mention dark stools? · 标注 `stop_use:1:1` · 关键词 `no_evidence` · 混合 `no_evidence` · 混合+重排 `stop_use:1:1`
- **Q14** What does the package say about damp conditions and extreme warmth? · 标注 `storage_and_handling:1:1` · 关键词 `no_evidence` · 混合 `no_evidence` · 混合+重排 `storage_and_handling:1:1`
- **Q26** Does the label mention discomfort from sour stomach? · 标注 `indications_and_usage:1:1` · 关键词 `indications_and_usage:1:1` · 混合 `ask_doctor:1:1` · 混合+重排 `indications_and_usage:1:1`
- **Q45** Which warehouse delivered this specific bottle? · 标注 `no_evidence` · 关键词 `no_evidence` · 混合 `inactive_ingredient:1:1` · 混合+重排 `no_evidence`
- **Q47** How many caplets did the store in Melbourne sell yesterday? · 标注 `no_evidence` · 关键词 `no_evidence` · 混合 `active_ingredient:3:1` · 混合+重排 `no_evidence`

## 混合检索答对、重排未答对

- **Q06** Which section mentions the red coloring? · 标注 `inactive_ingredient:1:1` · 关键词 `no_evidence` · 混合 `inactive_ingredient:1:1` · 混合+重排 `no_evidence`
- **Q07** Is this labeled to bring down a fever? · 标注 `purpose:1:1` · 关键词 `no_evidence` · 混合 `purpose:1:1` · 混合+重排 `no_evidence`
- **Q16** How does the label distinguish the two flavors for people with PKU? · 标注 `storage_and_handling:1:1` · 关键词 `no_evidence` · 混合 `storage_and_handling:1:1` · 混合+重排 `no_evidence`
- **Q18** Where does the label mention the seal being damaged? · 标注 `other_safety_information:1:1` · 关键词 `no_evidence` · 混合 `other_safety_information:1:1` · 混合+重排 `no_evidence`
- **Q21** Does the package mention becoming sleepy? · 标注 `when_using:1:1` · 关键词 `no_evidence` · 混合 `when_using:1:1` · 混合+重排 `no_evidence`

## 混合检索答对、关键词未答对

- **Q01** What temperature does the label say to store it at? · 标注 `storage_and_handling:1:1` · 关键词 `no_evidence` · 混合 `storage_and_handling:1:1` · 混合+重排 `storage_and_handling:1:1`
- **Q06** Which section mentions the red coloring? · 标注 `inactive_ingredient:1:1` · 关键词 `no_evidence` · 混合 `inactive_ingredient:1:1` · 混合+重排 `no_evidence`
- **Q07** Is this labeled to bring down a fever? · 标注 `purpose:1:1` · 关键词 `no_evidence` · 混合 `purpose:1:1` · 混合+重排 `no_evidence`
- **Q08** What is the recommended storage temperature range on this label? · 标注 `storage_and_handling:1:1` · 关键词 `no_evidence` · 混合 `storage_and_handling:1:1` · 混合+重排 `storage_and_handling:1:1`
- **Q16** How does the label distinguish the two flavors for people with PKU? · 标注 `storage_and_handling:1:1` · 关键词 `no_evidence` · 混合 `storage_and_handling:1:1` · 混合+重排 `no_evidence`
- **Q18** Where does the label mention the seal being damaged? · 标注 `other_safety_information:1:1` · 关键词 `no_evidence` · 混合 `other_safety_information:1:1` · 混合+重排 `no_evidence`
- **Q20** Does the label mention keeping it away from light and dampness? · 标注 `storage_and_handling:1:1` · 关键词 `no_evidence` · 混合 `storage_and_handling:1:1` · 混合+重排 `storage_and_handling:1:1`
- **Q21** Does the package mention becoming sleepy? · 标注 `when_using:1:1` · 关键词 `no_evidence` · 混合 `when_using:1:1` · 混合+重排 `no_evidence`
- **Q25** Does it say to keep the box? · 标注 `storage_and_handling:1:1` · 关键词 `no_evidence` · 混合 `storage_and_handling:1:1` · 混合+重排 `storage_and_handling:1:1`
- **Q29** Does the label discuss keeping it in a fridge or freezer? · 标注 `storage_and_handling:1:1` · 关键词 `no_evidence` · 混合 `storage_and_handling:1:1` · 混合+重排 `storage_and_handling:1:1`

## 关键词答对、混合检索未答对

- **Q11** Which active ingredient is listed for the caplets? · 标注 `active_ingredient:1:1, active_ingredient:3:1` · 关键词 `active_ingredient:3:1` · 混合 `inactive_ingredient:3:1` · 混合+重排 `active_ingredient:3:1`
- **Q26** Does the label mention discomfort from sour stomach? · 标注 `indications_and_usage:1:1` · 关键词 `indications_and_usage:1:1` · 混合 `ask_doctor:1:1` · 混合+重排 `indications_and_usage:1:1`
- **Q31** Which compound appears in the active ingredient list? · 标注 `active_ingredient:1:1` · 关键词 `active_ingredient:1:1` · 混合 `inactive_ingredient:1:1` · 混合+重排 `inactive_ingredient:1:1`
- **Q45** Which warehouse delivered this specific bottle? · 标注 `no_evidence` · 关键词 `no_evidence` · 混合 `inactive_ingredient:1:1` · 混合+重排 `no_evidence`
- **Q47** How many caplets did the store in Melbourne sell yesterday? · 标注 `no_evidence` · 关键词 `no_evidence` · 混合 `active_ingredient:3:1` · 混合+重排 `no_evidence`

## 三种方式都未通过

- **Q04** What does the label say about an elevated temperature that persists? · 标注 `stop_use:1:1` · 关键词 `no_evidence` · 混合 `no_evidence` · 混合+重排 `no_evidence`
- **Q05** How does the carton describe damaged packaging? · 标注 `storage_and_handling:1:1` · 关键词 `no_evidence` · 混合 `no_evidence` · 混合+重排 `no_evidence`
- **Q10** Is this described as a pain reliever applied to the skin? · 标注 `purpose:1:1` · 关键词 `no_evidence` · 混合 `indications_and_usage:1:1` · 混合+重排 `indications_and_usage:1:1`
- **Q12** What does the package say about the time around a cardiac operation? · 标注 `do_not_use:1:1` · 关键词 `no_evidence` · 混合 `no_evidence` · 混合+重排 `no_evidence`
- **Q17** What drug class or purpose does the chewable label list? · 标注 `purpose:1:1` · 关键词 `no_evidence` · 混合 `inactive_ingredient:1:1` · 混合+重排 `inactive_ingredient:1:1`
- **Q19** Which substance provides the intended effect? · 标注 `active_ingredient:1:1` · 关键词 `no_evidence` · 混合 `purpose:1:1` · 混合+重排 `no_evidence`
- **Q22** What does the package say about operating a car? · 标注 `when_using:1:1` · 关键词 `no_evidence` · 混合 `no_evidence` · 混合+重排 `no_evidence`
- **Q28** Does the label promise relief straight away? · 标注 `indications_and_usage:1:1` · 关键词 `no_evidence` · 混合 `no_evidence` · 混合+重排 `no_evidence`

向量模型 `medtrack/bge-small-finetuned@1e1a24cb2c06`。语料 SHA-256 `9e3c9778b8a003c4107369554f8310c62f0a7e4ee48021a0da57af0bc51d865f`。题集 SHA-256 `5e22d2123ca0c076eedbfea723de93d6e48c6649c16a1fd491c3884bede5a516`。
