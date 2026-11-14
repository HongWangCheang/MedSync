# 端侧路由评测

评测集：`utterances.jsonl`（210 句中文，今天 = 2026-11-16 周一）。dev 用来调规则和提示词，test 在最终对比前不看。指标定义见 `score.py`。

## dev

| 指标 | qwen3-0.6b | rules |
|---|---|---|
| 整句完全正确 | 93% | 53% |
| 工具选择正确 | 93% | 63% |
| record_medication F1 | 99% | 84% |
| record_symptom F1 | 93% | 71% |
| book_appointment F1 | 100% | 86% |
| notify_family F1 | 94% | 88% |
| ask_pharmacist F1 | 98% | 79% |
| 参数：drug_name | 98% | 77% |
| 参数：symptom | 100% | 100% |
| 参数：department | 100% | 33% |
| 参数：date | 100% | 100% |
| 参数：relative | 100% | 100% |
| 延迟 p50 / p95 (ms) | 1920.2 / 4041.5 | 0.0 / 0.1 |

按类别（整句完全正确）：

| 类别 | qwen3-0.6b | rules |
|---|---|---|
| book | 100% | 37% |
| combo | 80% | 40% |
| med | 100% | 65% |
| multi | 100% | 0% |
| none | 100% | 89% |
| notify | 85% | 69% |
| question | 95% | 68% |
| symptom | 90% | 45% |

## test

| 指标 | qwen3-0.6b | rules |
|---|---|---|
| 整句完全正确 | 87% | 48% |
| 工具选择正确 | 91% | 58% |
| record_medication F1 | 96% | 78% |
| record_symptom F1 | 92% | 70% |
| book_appointment F1 | 97% | 89% |
| notify_family F1 | 96% | 83% |
| ask_pharmacist F1 | 92% | 73% |
| 参数：drug_name | 100% | 70% |
| 参数：symptom | 96% | 100% |
| 参数：department | 100% | 50% |
| 参数：date | 95% | 94% |
| 参数：relative | 92% | 100% |
| 延迟 p50 / p95 (ms) | 1963.6 / 4069.1 | 0.0 / 0.1 |

按类别（整句完全正确）：

| 类别 | qwen3-0.6b | rules |
|---|---|---|
| book | 92% | 33% |
| combo | 92% | 58% |
| med | 92% | 42% |
| multi | 75% | 0% |
| none | 100% | 100% |
| notify | 62% | 38% |
| question | 86% | 57% |
| symptom | 92% | 50% |

## qwen3-0.6b 在 dev 上的错例（9 条）

- `symptom-26` 胸口闷闷的 → 期望 ['record_symptom']，得到 []
- `symptom-31` 腰疼 → 期望 ['record_symptom']，得到 []
- `notify-12` 告诉我妈我在吃药了 → 期望 ['notify_family']，得到 []
- `notify-16` 告诉哥哥别担心 → 期望 ['notify_family']，得到 []
- `combo-16` 吃了布洛芬，头还是疼 → 期望 ['record_medication', 'record_symptom']，得到 ['record_medication']
- `combo-22` 吃了华法林和阿司匹林，告诉儿子 → 期望 ['record_medication', 'record_medication', 'notify_family']，得到 ['record_medication', 'notify_family']；drug_name: expected 华法林 / got 阿司匹林
- `combo-23` 早上吃了降压药，现在头晕想吐 → 期望 ['record_medication', 'record_symptom', 'record_symptom']，得到 ['record_medication', 'record_symptom']
- `combo-32` 腰疼，帮我挂下周二骨科 → 期望 ['record_symptom', 'book_appointment']，得到 ['book_appointment']
- `question-03` 这个药饭前吃还是饭后吃 → 期望 ['ask_pharmacist']，得到 []

## rules 在 dev 上的错例（62 条）

- `med-06` 打了胰岛素 → 期望 ['record_medication']，得到 []
- `med-07` 用了一下氟替卡松喷剂 → 期望 ['record_medication']，得到 []
- `med-11` 刚刚把优甲乐吃了 → 期望 ['record_medication']，得到 ['record_medication']；drug_name: expected 优甲乐 / got 未注明药物
- `med-12` 已经吃药了，吃的是奥美拉唑 → 期望 ['record_medication']，得到 []
- `med-13` 二甲双胍吃过了 → 期望 ['record_medication']，得到 ['record_medication']；drug_name: expected 二甲双胍 / got 了
- `med-18` 今天的钙片吃了 → 期望 ['record_medication']，得到 ['record_medication']；drug_name: expected 钙片 / got 未注明药物
- `med-27` 吃了 Tylenol → 期望 ['record_medication']，得到 ['record_medication']；drug_name: expected Tylenol / got 未注明药物
- `multi-01` 吃了布洛芬和奥美拉唑 → 期望 ['record_medication', 'record_medication']，得到 ['record_medication']
- `multi-02` 早上吃了华法林、阿托伐他汀 → 期望 ['record_medication', 'record_medication']，得到 ['record_medication']；drug_name: expected 华法林 / got 华法林、阿托伐他汀
- `multi-03` 刚吃了泰诺，还吃了一片氯雷他定 → 期望 ['record_medication', 'record_medication']，得到 ['record_medication']
- `multi-06` 我吃了感冒灵和布洛芬 → 期望 ['record_medication', 'record_medication']，得到 ['record_medication']
- `multi-07` 服用了优甲乐，之后又吃了钙片 → 期望 ['record_medication', 'record_medication']，得到 ['record_medication']；drug_name: expected 优甲乐 / got 钙片
- `multi-08` 吃了舍曲林以及维生素D → 期望 ['record_medication', 'record_medication']，得到 ['record_medication']；drug_name: expected 舍曲林 / got 舍曲林以及维生素D
- `multi-11` 吃了布洛芬、泰诺和阿司匹林 → 期望 ['record_medication', 'record_medication', 'record_medication']，得到 ['record_medication']；drug_name: expected 布洛芬 / got 布洛芬、泰诺
- `multi-12` 午饭后吃了二甲双胍和阿托伐他汀 → 期望 ['record_medication', 'record_medication']，得到 ['record_medication']
- `none-12` 没有头疼，也没有发烧 → 期望 []，得到 ['record_symptom']
- `symptom-03` 胃不舒服 → 期望 ['record_symptom']，得到 []
- `symptom-11` 拉肚子 → 期望 ['record_symptom']，得到 []
- `symptom-12` 手臂上起了疹子 → 期望 ['record_symptom']，得到 []
- `symptom-21` 感觉心跳很快 → 期望 ['record_symptom']，得到 []
- `symptom-22` 喉咙痛 → 期望 ['record_symptom']，得到 []
- `symptom-23` 有点发热 → 期望 ['record_symptom']，得到 []
- `symptom-26` 胸口闷闷的 → 期望 ['record_symptom']，得到 []
- `symptom-27` 吃完饭肚子痛 → 期望 ['record_symptom']，得到 []
- `symptom-28` 身上痒还起了红疹 → 期望 ['record_symptom']，得到 []
- `symptom-31` 腰疼 → 期望 ['record_symptom']，得到 []
- `symptom-32` 关节疼得厉害 → 期望 ['record_symptom']，得到 []
- `book-02` 预约周三消化内科 → 期望 ['book_appointment']，得到 ['book_appointment']；department: expected 消化内科 / got 全科
- `book-03` 挂个下周一心内科的号 → 期望 ['book_appointment']，得到 []
- `book-07` 帮我预约下周三的呼吸科 → 期望 ['book_appointment']，得到 ['book_appointment']；department: expected 呼吸内科 / got 全科
- `book-08` 约个皮肤科，明天 → 期望 ['book_appointment']，得到 ['book_appointment']；department: expected 皮肤科 / got 全科
- `book-12` 帮我约内分泌科复查，周三 → 期望 ['book_appointment']，得到 ['book_appointment']；department: expected 内分泌科 / got 全科
- `book-13` 挂一个眼科的号 → 期望 ['book_appointment']，得到 []
- `book-18` 帮我约下周二的消化科 → 期望 ['book_appointment']，得到 ['book_appointment']；department: expected 消化内科 / got 全科
- `book-21` 我想挂心血管内科，11月25日 → 期望 ['book_appointment']，得到 []
- `book-22` 约个神经科的号，周四 → 期望 ['book_appointment']，得到 ['book_appointment']；department: expected 神经内科 / got 全科
- `book-27` 可不可以帮我挂周三呼吸内科 → 期望 ['book_appointment']，得到 ['ask_pharmacist']
- `book-28` 帮我挂个号看看皮肤 → 期望 ['book_appointment']，得到 []
- `book-31` 帮我约个明天上午的骨科 → 期望 ['book_appointment']，得到 ['book_appointment']；department: expected 骨科 / got 全科
- `notify-11` 跟姐姐说一声我没事 → 期望 ['notify_family']，得到 []
- `notify-12` 告诉我妈我在吃药了 → 期望 ['notify_family']，得到 []
- `notify-16` 告诉哥哥别担心 → 期望 ['notify_family']，得到 []
- `notify-18` 给老公打个招呼说我出门了 → 期望 ['notify_family']，得到 []
- `combo-08` 吃了二甲双胍和降压药，有点乏力，告诉儿子 → 期望 ['record_medication', 'record_medication', 'record_symptom', 'notify_family']，得到 ['record_medication', 'record_symptom', 'notify_family']
- `combo-12` 起疹子了，约皮肤科下周一 → 期望 ['record_symptom', 'book_appointment']，得到 ['book_appointment']；department: expected 皮肤科 / got 全科
- `combo-13` 吃了阿莫西林，还是嗓子疼 → 期望 ['record_medication', 'record_symptom']，得到 ['record_medication']
- `combo-16` 吃了布洛芬，头还是疼 → 期望 ['record_medication', 'record_symptom']，得到 ['record_medication']
- `combo-17` 我头晕，帮我挂明天的号 → 期望 ['record_symptom', 'book_appointment']，得到 ['record_symptom']
- `combo-18` 吃了感冒药，发烧还没退，约周四全科 → 期望 ['record_medication', 'record_symptom', 'book_appointment']，得到 ['record_medication', 'record_symptom', 'book_appointment']；department: expected 全科 / got 呼吸内科
- `combo-21` 头痛三天了，吃了布洛芬没用，帮我约神经科 → 期望 ['record_symptom', 'record_medication', 'book_appointment']，得到 ['record_medication', 'record_symptom', 'book_appointment']；drug_name: expected 布洛芬 / got 布洛芬没用
- `combo-22` 吃了华法林和阿司匹林，告诉儿子 → 期望 ['record_medication', 'record_medication', 'notify_family']，得到 ['record_medication', 'notify_family']
- `combo-23` 早上吃了降压药，现在头晕想吐 → 期望 ['record_medication', 'record_symptom', 'record_symptom']，得到 ['record_medication', 'record_symptom']
- `combo-26` 乏力，帮我约内分泌科 → 期望 ['record_symptom', 'book_appointment']，得到 ['record_symptom', 'book_appointment']；department: expected 内分泌科 / got 全科
- `combo-28` 吃过阿托伐他汀，肌肉疼，约下周一复诊 → 期望 ['record_medication', 'record_symptom', 'book_appointment']，得到 ['record_medication', 'book_appointment']
- `combo-32` 腰疼，帮我挂下周二骨科 → 期望 ['record_symptom', 'book_appointment']，得到 []
- `question-02` 泰诺一天最多吃几片 → 期望 ['ask_pharmacist']，得到 []
- `question-03` 这个药饭前吃还是饭后吃 → 期望 ['ask_pharmacist']，得到 []
- `question-07` 奥美拉唑要吃多久 → 期望 ['ask_pharmacist']，得到 []
- `question-11` 小孩发烧能吃对乙酰氨基酚吗 → 期望 ['ask_pharmacist']，得到 ['record_symptom']
- `question-17` 优甲乐和钙片要隔多久吃 → 期望 ['ask_pharmacist']，得到 []
- `question-28` 吃了泰诺还能吃感冒灵吗 → 期望 ['ask_pharmacist']，得到 ['record_medication']
- `question-33` 硝苯地平有哪些禁忌 → 期望 ['ask_pharmacist']，得到 []
