# 安全审核评测：相互作用提醒

用例 32 个（正例 20，负例 12），预期答案按一般药理常识预先写好，不是照着检查器的输出写的。

| 指标 | 结果 |
| --- | --- |
| 召回率（该提醒的对子有没有提醒） | 16/20 = 80%（95% CI 58%–92%） |
| 精确率（提醒里有多少是对的） | 16/16 = 100%（95% CI 81%–100%） |
| 负例无误报 | 12/12 |
| 标为 high 的用例判成 high | 4/4 |

**这是开发集，不是盲测。** 写检查器时用这批用例调过三处：过敏语境里的提及不算（“allergic to aspirin”）、否定句不算（Lipitor “no clinically significant effect … warfarin”）、同成分多个说明书时选有相互作用章节的那份。所以数字偏乐观，换一批新用例才是真实水平（见 [../safety_blind/REPORT.md](../safety_blind/REPORT.md)）。

漏报都是数据或词表覆盖不到：说明书没写（布洛芬或奥美拉唑与氯吡格雷）、名字不在别名表（克拉霉素，会作为“未识别”明确告诉用户）、两种抗组胺药的说明书互不提及。检查器只说“说明书写了什么”，不凭常识补。

## 逐条结果

| 用例 | 新记录 | 已有记录 | 预期提醒 | 实际提醒 | 结论 |
| --- | --- | --- | --- | --- | --- |
| P01 | 布洛芬 | 华法林 | 华法林 | 华法林 | ✓ |
| P02 | 布洛芬 | 阿司匹林 | 阿司匹林 | 阿司匹林 | ✓ |
| P03 | 萘普生 | 布洛芬 | 布洛芬 | 布洛芬 | ✓ |
| P04 | 泰诺 | 华法林 | 华法林 | 华法林 | ✓ |
| P05 | 泰诺 | Advil Dual Action with Acetaminophen | Advil Dual Action with Acetaminophen | Advil Dual Action with Acetaminophen | ✓ |
| P06 | 对乙酰氨基酚 | FLONASE Headache and Allergy Relief | FLONASE Headache and Allergy Relief | FLONASE Headache and Allergy Relief | ✓ |
| P07 | 苯海拉明 | Benadryl Extra Strength Itch Relief | Benadryl Extra Strength Itch Relief | Benadryl Extra Strength Itch Relief | ✓ |
| P08 | 舍曲林 | 布洛芬 | 布洛芬 | 布洛芬 | ✓ |
| P09 | 布洛芬 | 舍曲林 | 舍曲林 | 舍曲林 | ✓ |
| P10 | 优甲乐 | 奥美拉唑 | 奥美拉唑 | 奥美拉唑 | ✓ |
| P11 | 碳酸钙 | 优甲乐 | 优甲乐 | 优甲乐 | ✓ |
| P12 | 布洛芬 | 泼尼松 | 泼尼松 | 泼尼松 | ✓ |
| P13 | ADVIL COLD AND SINUS | 舍曲林 | 舍曲林 | 舍曲林 | ✓ |
| P14 | 布洛芬 | 氯吡格雷 | 氯吡格雷 | — | 漏报 |
| P15 | 奥美拉唑 | 氯吡格雷 | 氯吡格雷 | — | 漏报 |
| P16 | 阿托伐他汀 | 克拉霉素 | 克拉霉素 | — | 漏报（未识别：克拉霉素） |
| P17 | 西替利嗪 | 苯海拉明 | 苯海拉明 | — | 漏报 |
| P18 | Aleve | 华法林 | 华法林 | 华法林 | ✓ |
| P19 | 布洛芬 | 华法林、氯雷他定 | 华法林 | 华法林 | ✓ |
| P20 | 芬必得 | Motrin IB | Motrin IB | Motrin IB | ✓ |
| N01 | 西替利嗪 | 法莫替丁 | — | — | ✓ |
| N02 | 泰诺 | 泰诺 | — | — | ✓ |
| N03 | 氯雷他定 | 奥美拉唑 | — | — | ✓ |
| N04 | 法莫替丁 | 阿托伐他汀 | — | — | ✓ |
| N05 | 优甲乐 | 阿托伐他汀 | — | — | ✓ |
| N06 | 阿托伐他汀 | 华法林 | — | — | ✓ |
| N07 | 布洛芬 | 泰诺 | — | — | ✓ |
| N08 | 氯雷他定 | 布洛芬 | — | — | ✓ |
| N09 | 布洛芬 | 氟替卡松 | — | — | ✓ |
| N10 | 苯海拉明 | 法莫替丁 | — | — | ✓ |
| N11 | 泰诺 | 对乙酰氨基酚 | — | — | ✓ |
| N12 | 布洛芬 | 华法林 | — | — | ✓ |

## 引用了哪段原文

- **P01** [moderate] 布洛芬（参照 Motrin IB Migraine 说明书）在「警告」里提到了抗凝药（华法林）。  
  Motrin IB Migraine · Warnings：“…you: are age 60 or older have had stomach ulcers or bleeding problems take a blood thinning (anticoagulant) or steroid drug take other drugs containing prescription or nonprescription NSAIDs (aspirin, ibuprofen, naproxen, or others) have 3 or more alcoholic drinks every day while…”
- **P02** [moderate] 布洛芬（参照 Motrin IB Migraine 说明书）在「用药前咨询医生或药师」里提到了阿司匹林。  
  Motrin IB Migraine · Ask a doctor or pharmacist before use：“…r or pharmacist before use if you are under a doctor's care for any serious condition taking aspirin for heart attack or stroke, because ibuprofen may decrease this benefit of aspirin taking any other drug”
- **P03** [moderate] 萘普生（参照 Aleve Gelcaps 说明书）在「警告」里提到了布洛芬。  
  Aleve Gelcaps · Warnings：“…or steroid drug take other drugs containing prescription or nonprescription NSAIDs (aspirin, ibuprofen, naproxen, or others) have 3 or more alcoholic drinks every day while using this product take more or for a longer time than directed Heart Attack and Stroke Warning NSAIDs, exc…”
- **P03** [moderate] 布洛芬（参照 Motrin IB Migraine 说明书）在「警告」里提到了萘普生。  
  Motrin IB Migraine · Warnings：“…drug take other drugs containing prescription or nonprescription NSAIDs (aspirin, ibuprofen, naproxen, or others) have 3 or more alcoholic drinks every day while using this product take more or for a longer time than directed Heart attack and stroke warning NSAIDs, except aspirin…”
- **P04** [moderate] 泰诺（参照 TYLENOL Regular Strength 说明书）在「用药前咨询医生或药师」里提到了华法林。  
  TYLENOL Regular Strength · Ask a doctor or pharmacist before use：“Ask a doctor or pharmacist before use if the user is taking the blood thinning drug warfarin”
- **P05** [high] 泰诺 和 Advil Dual Action with Acetaminophen 含有相同成分（对乙酰氨基酚），24 小时内一起用可能超过每日最大剂量；如果这是同一种药的两种叫法，可以忽略。  
  TYLENOL Regular Strength · Do not use：“Do not use with any other drug containing acetaminophen (prescription or nonprescription). If you are not sure whether a drug contains acetaminophen, ask a doctor or pharmacist. if you are allergic to acetaminophen or any of the inactive ingredients in this product”
- **P06** [high] 对乙酰氨基酚 和 FLONASE Headache and Allergy Relief 含有相同成分（对乙酰氨基酚），24 小时内一起用可能超过每日最大剂量；如果这是同一种药的两种叫法，可以忽略。  
  TYLENOL Regular Strength · Do not use：“Do not use with any other drug containing acetaminophen (prescription or nonprescription). If you are not sure whether a drug contains acetaminophen, ask a doctor or pharmacist. if you are allergic to acetaminophen or any of the inactive ingredients in this product”
- **P07** [high] 苯海拉明 和 Benadryl Extra Strength Itch Relief 含有相同成分（苯海拉明），24 小时内一起用可能超过每日最大剂量；如果这是同一种药的两种叫法，可以忽略。  
  Benadryl · Do not use：“Do not use to make a child sleepy with any other product containing diphenhydramine, even one used on skin”
- **P08** [moderate] 舍曲林（参照 Zoloft 说明书）在「警告与注意事项」里提到了非甾体抗炎药（布洛芬）。  
  Zoloft · Warnings and precautions：“…ncreased Risk of Bleeding: Concomitant use of aspirin, nonsteroidal anti-inflammatory drugs (NSAIDs), other antiplatelet drugs, warfarin, and other anticoagulants may increase this risk. ( 5.3 ) • Activation of Mania/Hypomania: Screen patients for bipolar disorder. ( 5.4 ) •”
- **P09** [moderate] 舍曲林（参照 Zoloft 说明书）在「警告与注意事项」里提到了非甾体抗炎药（布洛芬）。  
  Zoloft · Warnings and precautions：“…ncreased Risk of Bleeding: Concomitant use of aspirin, nonsteroidal anti-inflammatory drugs (NSAIDs), other antiplatelet drugs, warfarin, and other anticoagulants may increase this risk. ( 5.3 ) • Activation of Mania/Hypomania: Screen patients for bipolar disorder. ( 5.4 ) •”
- **P10** [moderate] 优甲乐（参照 Synthroid 说明书）在「药物相互作用」里提到了质子泵抑制剂（奥美拉唑）。  
  Synthroid · Drug interactions：“…bsorption. Administer SYNTHROID at least 4 hours prior to these drugs or monitor TSH levels. Proton Pump Inhibitors Sucralfate Antacids (e.g., aluminum & magnesium hydroxides, simethicone) Gastric acidity is an essential requirement for adequate absorption of levothyroxine.”
- **P11** [moderate] 优甲乐（参照 Synthroid 说明书）在「药物相互作用」里提到了碳酸钙。  
  Synthroid · Drug interactions：“…potentially resulting in hypothyroidism. Drug or Drug Class Effect Phosphate Binders (e.g., calcium carbonate, ferrous sulfate, sevelamer, lanthanum) Phosphate binders may bind to levothyroxine. Administer SYNTHROID at least 4 hours apart from these agents. Orlistat Monitor pati…”
- **P12** [moderate] 布洛芬（参照 Motrin IB Migraine 说明书）在「警告」里提到了糖皮质激素（泼尼松）。  
  Motrin IB Migraine · Warnings：“…older have had stomach ulcers or bleeding problems take a blood thinning (anticoagulant) or steroid drug take other drugs containing prescription or nonprescription NSAIDs (aspirin, ibuprofen, naproxen, or others) have 3 or more alcoholic drinks every day while using this produc…”
- **P13** [moderate] 舍曲林（参照 Zoloft 说明书）在「警告与注意事项」里提到了非甾体抗炎药（ADVIL COLD AND SINUS）。  
  Zoloft · Warnings and precautions：“…ncreased Risk of Bleeding: Concomitant use of aspirin, nonsteroidal anti-inflammatory drugs (NSAIDs), other antiplatelet drugs, warfarin, and other anticoagulants may increase this risk. ( 5.3 ) • Activation of Mania/Hypomania: Screen patients for bipolar disorder. ( 5.4 ) •”
- **P18** [moderate] Aleve 的说明书在「警告」里提到了抗凝药（华法林）。  
  Aleve · Warnings：“…you: are age 60 or older have had stomach ulcers or bleeding problems take a blood thinning (anticoagulant) or steroid drug take other drugs containing prescription or nonprescription NSAIDs (aspirin, ibuprofen, naproxen, or others) have 3 or more alcoholic drinks every day while…”
- **P19** [moderate] 布洛芬（参照 Motrin IB Migraine 说明书）在「警告」里提到了抗凝药（华法林）。  
  Motrin IB Migraine · Warnings：“…you: are age 60 or older have had stomach ulcers or bleeding problems take a blood thinning (anticoagulant) or steroid drug take other drugs containing prescription or nonprescription NSAIDs (aspirin, ibuprofen, naproxen, or others) have 3 or more alcoholic drinks every day while…”
- **P20** [high] 芬必得 和 Motrin IB 含有相同成分（布洛芬），24 小时内一起用可能超过每日最大剂量；如果这是同一种药的两种叫法，可以忽略。  
  Motrin IB Migraine · Warnings：“…or steroid drug take other drugs containing prescription or nonprescription NSAIDs (aspirin, ibuprofen, naproxen, or others) have 3 or more alcoholic drinks every day while using this product take more or for a longer time than directed Heart attack and stroke warning NSAIDs, exc…”
