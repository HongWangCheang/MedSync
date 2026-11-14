# MedTrack Agent 多轮评测

12 段对话、18 轮，模型 `gemini-3.5-flash-lite`，检索模式 `rerank`。登录用户的用药记录来自固定夹具（PEPCID AC Maximum Strength、Benadryl Allergy Extra Strength Liqui-Gels）。每轮只跑一次，模型输出有随机性，重跑结果可能略有不同。

| 指标 | 结果 |
|---|---:|
| 整体通过 | 17/18 |
| 工具选择正确 | 18/18 |
| 需引用的轮次通过 | 12/13 |
| 引用精确率（引用落在期望标签且含关键证据） | 90.5% |
| 被校验拦下的回答 | 1 |
| 平均模型调用步数 | 2.22 |
| 每轮耗时 P50 / 最大 | 2.7 s / 4.7 s |
| 每轮平均 token（输入 / 输出） | 1484 / 106 |

判定规则：`cited` 要求回答通过引用校验，且至少一条引用来自期望标签并含关键词；`clarify` 要求重名时追问、不带引用；`uncited` 要求如实说明查不到；`not_safe_claim` 要求说明书未提及时不能说“安全”；`no_unsourced` 要求不凭记忆作答。

## 逐轮结果

| 轮次 | 期望 | 通过 | 调用工具 | 回答 |
|---|---|---|---|---|
| A01.1 | cited | ✅ | check_interaction | The Tylenol 8 Hr Arthritis Pain label states that you should ask a doctor or pharmacist before use if you are taking the blood thinning drug warfarin [S1, S2]. |
| A01.2 | cited | ✅ | check_interaction | The Tylenol 8 Hr Arthritis Pain label states: "Do not use with any other drug containing acetaminophen (prescription or nonprescription)." [S3, S4] It also note |
| A02.1 | cited | ❌ | search_label, check_interaction | The concomitant use of serotonergic drugs, such as MAOIs like phenelzine, with Zoloft increases the risk of serotonin syndrome [S2]. |
| A02.2 | cited | ✅ | check_interaction | Concomitant use of Zoloft with St. John's Wort increases the risk of serotonin syndrome, and patients should be monitored for signs and symptoms of serotonin sy |
| A03.1 | cited | ✅ | search_label | Consuming large quantities of grapefruit juice—specifically more than 1.2 liters daily—can raise the plasma levels of atorvastatin and may increase the risk of  |
| A03.2 | cited | ✅ | check_interaction | Concomitant use of gemfibrozil with Lipitor increases the risk of myopathy and rhabdomyolysis [S2]. The label states that the concurrent use of gemfibrozil with |
| A04.1 | cited | ✅ | search_label | When using Benadryl Allergy Extra Strength Liqui-Gels, marked drowsiness may occur, and you should be careful when driving a motor vehicle or operating machiner |
| A04.2 | cited | ✅ | check_interaction | You should ask a doctor or pharmacist before use if you are taking tranquilizers [S2, S3]. Sedatives and tranquilizers may increase the marked drowsiness that c |
| A05.1 | cited | ✅ | get_my_medications, check_interaction | The Motrin IB Migraine label states that you should ask a doctor or pharmacist before use if you are taking aspirin for heart attack or stroke, because ibuprofe |
| A06.1 | clarify | ✅ | search_label | Which Tylenol Extra Strength product do you mean? - Tylenol Extra Strength (Kenvue Brands LLC, version 2) - TYLENOL Extra Strength (Kenvue Brands LLC, version 1 |
| A06.2 | cited | ✅ | search_label, search_label, search_label | TYLENOL Extra Strength should be stored between 20-25°C (68-77°F) [S1]. |
| A07.1 | cited | ✅ | get_my_medications, search_label, search_label | For your medications: * **Benadryl Allergy Extra Strength Liqui-Gels:** The label warns to avoid alcoholic drinks [S2]. * **PEPCID AC Maximum Strength:** The pr |
| A08.1 | uncited | ✅ | get_my_medications | It looks like you are not signed in, so I can't view your medication records. Please sign in to your account to check your medications. |
| A09.1 | not_safe_claim | ✅ | check_interaction | The PEPCID AC Maximum Strength label does not mention ibuprofen. |
| A10.1 | uncited | ✅ | search_label | The product label does not contain information about pricing or costs at Walgreens. |
| A11.1 | no_unsourced | ✅ | — | I can't give a sourced answer to that. Please check the printed label or ask a pharmacist. |
| A12.1 | cited | ✅ | search_label | Children under 4 years of age should not use Children's Flonase Allergy Relief [S1]. |
| A12.2 | cited | ✅ | search_label | Yes, you should ask a doctor before use if you have or had glaucoma [S2]. |
