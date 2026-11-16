# 药学问答：12 段多轮对话走 MedSync 全链路

由 `eval/pharmacist_chain/run_chain.py` 生成。同样的 12 段对话、同样的判定规则（见 `services/rag/eval_agent.py`），区别是每一轮都作为 `ask_pharmacist` 步骤，从设备经网关、agent 到 rag，多轮之间靠 session_id 接上；需要"我的用药"的那段对话，先通过网关记录用药，再由药学 Agent 用网关签发的临时只读令牌读回。

| 指标 | 全链路 | 进程内（同一索引） |
|---|---:|---:|
| 整体通过 | 17/18 | 18/18 |
| 工具选择正确 | 18/18 | 18/18 |
| 需引用的轮次通过 | 12/13 | 13/13 |
| 引用精确率 | 94.7% | 90.0% |
| 每轮耗时 P50 / 最大（含排队和轮询） | 8.5 s / 16.1 s | 8.4 s / 31.5 s |

每轮只跑一次，模型输出有随机性，两边的差异里有一部分是这次运行的随机差异。设备只保存每条引用的开头（摘录），所以关键句是对照摘录所在的说明书原段落检查的（本地快照与 rag 服务用的是同一份）。

## 逐轮结果

| 轮次 | 期望 | 状态 | 通过 | 调用工具 | 回答 |
|---|---|---|---|---|---|
| A01.1 | cited | DONE | ✅ | check_interaction | The TYLENOL 8 HR ARTHRITIS PAIN label states that you should ask a doctor or pharmacist before use if you are  |
| A01.2 | cited | DONE | ✅ | search_label | The label states: "Do not use with any other drug containing acetaminophen (prescription or nonprescription)." |
| A02.1 | cited | DONE | ✅ | search_label, check_interaction | The Zoloft label states that the concomitant use of serotonergic drugs with ZOLOFT increases the risk of serot |
| A02.2 | cited | DONE | ✅ | check_interaction | The Zoloft label states that the risk of serotonin syndrome is increased with the concomitant use of other ser |
| A03.1 | cited | DONE | ✅ | search_label | Consuming large quantities of grapefruit juice (more than 1.2 liters daily) can raise the plasma levels of ato |
| A03.2 | cited | DONE | ✅ | check_interaction | Concomitant use of gemfibrozil with Lipitor is not recommended [S2, S5]. Gemfibrozil significantly increases a |
| A04.1 | cited | DONE | ✅ | search_label | When using this product, marked drowsiness may occur [S1]. Alcohol, sedatives, and tranquilizers may increase  |
| A04.2 | cited | DONE | ✅ | check_interaction | You should ask a doctor or pharmacist before use if you are taking sedatives or tranquilizers [S2, S3]. Alcoho |
| A05.1 | cited | DONE | ✅ | get_my_medications, search_label | The Motrin IB Migraine label states that ibuprofen may decrease the benefit of aspirin taken for heart attack  |
| A06.1 | clarify | DONE | ✅ | search_label | Which Tylenol Extra Strength product do you mean? - Tylenol Extra Strength (Kenvue Brands LLC, version 2) - TY |
| A06.2 | cited | DONE | ❌ | search_label, search_label, search_label | Which Tylenol Extra Strength product do you mean? - Tylenol Extra Strength (Kenvue Brands LLC, version 2) - TY |
| A07.1 | cited | DONE | ✅ | get_my_medications, search_label, search_label | For **Benadryl Allergy Extra Strength Liqui-Gels**, the label warns to "avoid alcoholic drinks" [S2].   For ** |
| A08.1 | uncited | DONE | ✅ | get_my_medications | You are not currently taking any medications according to your records. |
| A09.1 | not_safe_claim | DONE | ✅ | check_interaction | The PEPCID AC Maximum Strength label does not mention ibuprofen. |
| A10.1 | uncited | DONE | ✅ | search_label | The drug label for Claritin Chewable Grape and Bubblegum does not mention pricing or cost information at Walgr |
| A11.1 | no_unsourced | DONE | ✅ |  | I can't give a sourced answer to that. Please check the printed label or ask a pharmacist. |
| A12.1 | cited | DONE | ✅ | search_label | Children under 4 years of age should not use Children's Flonase Allergy Relief [S1]. |
| A12.2 | cited | DONE | ✅ | search_label | Yes, you should ask a doctor before use if you have or had glaucoma [S2]. |
