# 安全审核评测：相互作用提醒（盲测）

用例 32 个（正例 21，负例 11），预期答案按一般药理常识预先写好，不是照着检查器的输出写的。

| 指标 | 结果 |
| --- | --- |
| 召回率（该提醒的对子有没有提醒） | 8/21 = 38%（95% CI 21%–59%） |
| 精确率（提醒里有多少是对的） | 8/8 = 100%（95% CI 68%–100%） |
| 负例无误报 | 11/11 |
| 标为 high 的用例判成 high | 0/2 |

**这是盲测集。** 用例在检查器规则定下之后按一般药理常识编写，先提交到 git、后运行，没有在这些药对上调过规则，结果出来以后也不改规则。所以这里的数字才是检查器在新数据上的水平。

## 逐条结果

| 用例 | 新记录 | 已有记录 | 预期提醒 | 实际提醒 | 结论 |
| --- | --- | --- | --- | --- | --- |
| B01 | 双氯芬酸 | 华法林 | 华法林 | — | 漏报 |
| B02 | 阿司匹林 | 利伐沙班 | 利伐沙班 | — | 漏报 |
| B03 | 布洛芬 | 呋塞米 | 呋塞米 | 呋塞米 | ✓ |
| B04 | 萘普生 | 氢氯噻嗪 | 氢氯噻嗪 | 氢氯噻嗪 | ✓ |
| B05 | 氟西汀 | 阿司匹林 | 阿司匹林 | — | 漏报 |
| B06 | 萘普生 | 泼尼松 | 泼尼松 | 泼尼松 | ✓ |
| B07 | 埃索美拉唑 | 氯吡格雷 | 氯吡格雷 | — | 漏报 |
| B08 | 伪麻黄碱 | 去氧肾上腺素 | 去氧肾上腺素 | — | 漏报 |
| B09 | 氯苯那敏 | 苯海拉明 | 苯海拉明 | — | 漏报 |
| B10 | 地塞米松 | 布洛芬 | 布洛芬 | 布洛芬 | ✓ |
| B11 | 舍曲林 | 氟西汀 | 氟西汀 | 氟西汀 | ✓ |
| B12 | 白加黑 | 泰诺 | 泰诺 | — | 漏报 |
| B13 | 新康泰克 | 苯海拉明 | 苯海拉明 | — | 漏报 |
| B14 | 感冒灵颗粒 | 对乙酰氨基酚 | 对乙酰氨基酚 | — | 漏报 |
| B15 | 华法林 | 阿司匹林 | 阿司匹林 | — | 漏报 |
| B16 | 利伐沙班 | 萘普生 | 萘普生 | 萘普生 | ✓ |
| B17 | 左甲状腺素 | 埃索美拉唑 | 埃索美拉唑 | 埃索美拉唑 | ✓ |
| B18 | 辛伐他汀 | 克拉霉素 | 克拉霉素 | — | 漏报 |
| B19 | 甲硝唑 | 华法林 | 华法林 | — | 漏报 |
| B20 | 地高辛 | 呋塞米 | 呋塞米 | — | 漏报 |
| B21 | 双氯芬酸 | 舍曲林 | 舍曲林 | 舍曲林 | ✓ |
| BN01 | 氯雷他定 | 碳酸钙 | — | — | ✓ |
| BN02 | 西替利嗪 | 阿托伐他汀 | — | — | ✓ |
| BN03 | 法莫替丁 | 布洛芬 | — | — | ✓ |
| BN04 | 泰诺 | 氯雷他定 | — | — | ✓ |
| BN05 | 埃索美拉唑 | 氯雷他定 | — | — | ✓ |
| BN06 | 呋塞米 | 法莫替丁 | — | — | ✓ |
| BN07 | 二甲双胍 | 阿托伐他汀 | — | — | ✓ |
| BN08 | 对乙酰氨基酚 | 萘普生 | — | — | ✓ |
| BN09 | 双氯芬酸 | 华法林 | — | — | ✓ |
| BN10 | 苯海拉明 | 对乙酰氨基酚 | — | — | ✓ |
| BN11 | 芬必得 | 布洛芬 | — | — | ✓ |

## 引用了哪段原文

- **B03** [moderate] 布洛芬（参照 Motrin IB Migraine 说明书）在「用药前咨询医生」里提到了利尿剂（呋塞米）。  
  Motrin IB Migraine · Ask a doctor before use：“…re, heart disease, liver cirrhosis, kidney disease, asthma, or had a stroke you are taking a diuretic”
- **B04** [moderate] 萘普生（参照 Aleve Gelcaps 说明书）在「用药前咨询医生」里提到了利尿剂（氢氯噻嗪）。  
  Aleve Gelcaps · Ask a doctor before use：“…re, heart disease, liver cirrhosis, kidney disease, asthma, or had a stroke you are taking a diuretic you have problems or serious side effects from taking pain relievers or fever reducers”
- **B06** [moderate] 萘普生（参照 Aleve Gelcaps 说明书）在「警告」里提到了糖皮质激素（泼尼松）。  
  Aleve Gelcaps · Warnings：“…older have had stomach ulcers or bleeding problems take a blood thinning (anticoagulant) or steroid drug take other drugs containing prescription or nonprescription NSAIDs (aspirin, ibuprofen, naproxen, or others) have 3 or more alcoholic drinks every day while using this produc…”
- **B10** [moderate] 布洛芬（参照 Motrin IB Migraine 说明书）在「警告」里提到了糖皮质激素（地塞米松）。  
  Motrin IB Migraine · Warnings：“…older have had stomach ulcers or bleeding problems take a blood thinning (anticoagulant) or steroid drug take other drugs containing prescription or nonprescription NSAIDs (aspirin, ibuprofen, naproxen, or others) have 3 or more alcoholic drinks every day while using this produc…”
- **B11** [moderate] 舍曲林（参照 Zoloft 说明书）在「药物相互作用」里提到了抗抑郁药（SSRI）（氟西汀）。  
  Zoloft · Drug interactions：“…ons with ZOLOFT Monoamine Oxidase Inhibitors (MAOIs) Clinical Impact: The concomitant use of SSRIs including ZOLOFT and MAOIs increases the risk of serotonin syndrome. Intervention: ZOLOFT is contraindicated in patients taking MAOIs, including MAOIs such as linezolid or intraveno…”
- **B16** [moderate] 萘普生（参照 Aleve Gelcaps 说明书）在「警告」里提到了抗凝药（利伐沙班）。  
  Aleve Gelcaps · Warnings：“…you: are age 60 or older have had stomach ulcers or bleeding problems take a blood thinning (anticoagulant) or steroid drug take other drugs containing prescription or nonprescription NSAIDs (aspirin, ibuprofen, naproxen, or others) have 3 or more alcoholic drinks every day while…”
- **B17** [moderate] 左甲状腺素（参照 Synthroid 说明书）在「药物相互作用」里提到了质子泵抑制剂（埃索美拉唑）。  
  Synthroid · Drug interactions：“…bsorption. Administer SYNTHROID at least 4 hours prior to these drugs or monitor TSH levels. Proton Pump Inhibitors Sucralfate Antacids (e.g., aluminum & magnesium hydroxides, simethicone) Gastric acidity is an essential requirement for adequate absorption of levothyroxine.”
- **B21** [moderate] 舍曲林（参照 Zoloft 说明书）在「警告与注意事项」里提到了非甾体抗炎药（双氯芬酸）。  
  Zoloft · Warnings and precautions：“…ncreased Risk of Bleeding: Concomitant use of aspirin, nonsteroidal anti-inflammatory drugs (NSAIDs), other antiplatelet drugs, warfarin, and other anticoagulants may increase this risk. ( 5.3 ) • Activation of Mania/Hypomania: Screen patients for bipolar disorder. ( 5.4 ) •”
