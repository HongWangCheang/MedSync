# 微调 bge-small 嵌入模型

结论先说：**微调带来小幅提升，但不显著，线上默认仍用基座模型**。下面是完整过程和数字。

## 防止数据泄露

- **按说明书划分**（[split.py](split.py)）：测试集和验证集用到的说明书一律不参与训练，同名题可能匹配到的所有候选说明书也算在内。48 份说明书里留出 33 份。
- **按原文去重**：很多说明书的文字逐字相同（比如好几个版本的 Tylenol），所以训练段落只要和留出的说明书里任何一段原文相同，也一并剔除。最后剩下 15 份说明书、238 个段落。
- **训练问题**（[make_training_data.py](make_training_data.py)）：用 Gemini 为每个段落生成 3 个患者口吻的问题，要求改写、不照抄说明书原文。和任意一道测试题或验证题的词重合度（Jaccard）≥ 0.6 的问题会被剔除。最终 712 条，剔除了 2 条。

## 训练

[train.py](train.py)：

- 损失函数用 `MultipleNegativesRankingLoss`，每条样本配一个困难负样本：在同一份说明书里，基座模型认为最像、但其实是错的那个段落。
- 同一个段落有 3 个问题，用 `NO_DUPLICATES` 采样，避免同一个段落在一个 batch 里同时充当正样本和负样本。
- 训练轮数只按验证集上的 MRR 来选。
- 在 Apple GPU（MPS）上，反向传播出现了死锁，所以改用 CPU 训练，4 种轮数配置合计约 15 分钟。

| 验证集（24 道可回答题） | Recall@1 | Recall@5 | MRR |
|---|---:|---:|---:|
| 基座模型 | 79.2% | 91.7% | 0.853 |
| 1 轮 | 83.3% | 95.8% | 0.884 |
| 4 轮（选中） | 83.3% | 95.8% | 0.889 |

1–4 轮的结果几乎一样，选中 4 轮只是因为 MRR 高了 0.001，在 24 道题上可以看作噪声。

## 测试集结果

**只看向量检索**（[compare.py](compare.py)，在所选说明书内部排序，测试集 32 道可回答题）：

| | Recall@1 | Recall@5 | MRR |
|---|---:|---:|---:|
| 基座模型 | 65.6% | 96.9% | 0.765 |
| 微调后 | 65.6% | 90.6% | 0.768 |

验证集上的提升没有迁移到测试集。

**放进完整系统**（`evaluate.py`，50 道题，报告在 [eval/finetuned/REPORT.md](../eval/finetuned/REPORT.md)）：

| 模式 | 基座模型 | 微调模型 |
|---|---:|---:|
| hybrid 引用正确率 | 59.3%（16/27） | 65.4%（17/26） |
| hybrid 通过题数 | 32/50 | 33/50 |
| rerank 通过题数 | 36/50 | 36/50 |

- **阈值要重新校准**：hybrid 模式在“相似度 ≥ 0.60”时才作答，这个阈值是按基座模型的分数分布定的。微调后分数分布变了，直接沿用 0.60 时，验证集只能通过 20/30。为此用 [tune_semantic.py](tune_semantic.py) 只在验证集上重新选阈值，选出 0.46（通过 25/30）；基座模型的最优值仍是 0.60。如果不重新校准，测试集会显示“引用正确率 84.6%、通过题数 29/50”。这个数字看着高，其实只是因为拒答多了、回答少了，并不是检索变好了。
- **rerank 不受影响**：重排的候选池是混合检索的前 30 个段落，几乎覆盖整份说明书，所以换哪个向量模型，候选池都差不多。

## 为什么默认不切换

- 只多答对 1 道题，在 50 道题上说明不了问题。
- fp32 的 ONNX 有 133 MB，而基座模型是 67 MB 的量化版。
- 训练数据只有 15 份说明书，覆盖面窄。

更值得做的方向是扩大语料（openFDA 有十几万份说明书）以及测试集的规模，而不是在这 238 个段落上继续调。

## 复现

```sh
python3.12 -m venv backend/finetune/.venv
backend/finetune/.venv/bin/pip install -r backend/finetune/requirements.txt
cd backend
.venv/bin/python -B finetune/make_training_data.py        # 需要 GEMINI_API_KEY；结果已提交在 data/train.jsonl
finetune/.venv/bin/python -B finetune/train.py            # 选轮数，结果写入 data/epoch_selection.json
finetune/.venv/bin/python -B finetune/compare.py          # 只比较向量检索
finetune/.venv/bin/python -B finetune/export_onnx.py      # 导出 ONNX，并检查与 PyTorch 输出一致
MEDTRACK_EMBED_MODEL_PATH=$PWD/finetune/models/bge-small-medtrack-onnx .venv/bin/python -B finetune/tune_semantic.py
MEDTRACK_EMBED_MODEL_PATH=$PWD/finetune/models/bge-small-medtrack-onnx MEDTRACK_SEMANTIC_MIN_SCORE=0.46 \
  .venv/bin/python -B evaluate.py --output-dir eval/finetuned
```

服务里要换成微调模型，设置 `MEDTRACK_EMBED_MODEL_PATH` 和 `MEDTRACK_SEMANTIC_MIN_SCORE` 两个环境变量即可。向量缓存按模型文件的哈希区分，不会误用另一个模型算出来的向量。
