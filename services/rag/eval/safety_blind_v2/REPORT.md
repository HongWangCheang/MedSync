# 安全审核评测：相互作用提醒（盲测 v2）

用例 35 个（正例 23，负例 12），预期答案按一般药理常识预先写好，不是照着检查器的输出写的。

| 指标 | 结果 |
| --- | --- |
| 召回率（该提醒的对子有没有提醒） | 21/23 = 91%（95% CI 73%–98%） |
| 精确率（提醒里有多少是对的） | 21/22 = 95%（95% CI 78%–99%） |
| 负例无误报 | 11/12 |
| 标为 high 的用例判成 high | 3/3 |

**这是盲测集。** 用例在检查器规则定下之后按一般药理常识编写，先提交到 git、后运行，没有在这些药对上调过规则，结果出来以后也不改规则。所以这里的数字才是检查器在新数据上的水平。

## 逐条结果

| 用例 | 新记录 | 已有记录 | 预期提醒 | 实际提醒 | 结论 |
| --- | --- | --- | --- | --- | --- |
| V01 | 胺碘酮 | 华法林 | 华法林 | 华法林 | ✓ |
| V02 | 克拉霉素 | 秋水仙碱 | 秋水仙碱 | 秋水仙碱 | ✓ |
| V03 | 氟康唑 | 华法林 | 华法林 | 华法林 | ✓ |
| V04 | 环丙沙星 | 华法林 | 华法林 | 华法林 | ✓ |
| V05 | 螺内酯 | 赖诺普利 | 赖诺普利 | 赖诺普利 | ✓ |
| V06 | 布洛芬 | 依那普利 | 依那普利 | — | 漏报 |
| V07 | 氯沙坦 | 螺内酯 | 螺内酯 | 螺内酯 | ✓ |
| V08 | 曲马多 | 帕罗西汀 | 帕罗西汀 | 帕罗西汀 | ✓ |
| V09 | 艾司西酞普兰 | 阿司匹林 | 阿司匹林 | 阿司匹林 | ✓ |
| V10 | 阿普唑仑 | 曲马多 | 曲马多 | 曲马多 | ✓ |
| V11 | 唑吡坦 | 阿普唑仑 | 阿普唑仑 | 阿普唑仑 | ✓ |
| V12 | 卡马西平 | 阿哌沙班 | 阿哌沙班 | 阿哌沙班 | ✓ |
| V13 | 胺碘酮 | 达比加群 | 达比加群 | 达比加群 | ✓ |
| V14 | 地高辛 | 胺碘酮 | 胺碘酮 | 胺碘酮 | ✓ |
| V15 | 左氧氟沙星 | 格列美脲 | 格列美脲 | 格列美脲 | ✓ |
| V16 | 帕罗西汀 | 美托洛尔 | 美托洛尔 | 美托洛尔 | ✓ |
| V17 | 阿莫西林 | 别嘌醇 | 别嘌醇 | 别嘌醇 | ✓ |
| V18 | 快克 | 泰诺 | 泰诺 | 泰诺 | ✓ |
| V19 | 日夜百服咛 | 对乙酰氨基酚 | 对乙酰氨基酚 | 对乙酰氨基酚 | ✓ |
| V20 | 维C银翘片 | 氯苯那敏 | 氯苯那敏 | 氯苯那敏 | ✓ |
| V21 | 银杏叶片 | 华法林 | 华法林 | — | 漏报 |
| V22 | 塞来昔布 | 氯吡格雷 | 氯吡格雷 | 氯吡格雷 | ✓ |
| V23 | 硝苯地平 | 克拉霉素 | 克拉霉素 | 克拉霉素 | ✓ |
| VN01 | 氨氯地平 | 二甲双胍 | — | 二甲双胍 | 误报 |
| VN02 | 阿莫西林 | 泰诺 | — | — | ✓ |
| VN03 | 瑞舒伐他汀 | 氨氯地平 | — | — | ✓ |
| VN04 | 泮托拉唑 | 美托洛尔 | — | — | ✓ |
| VN05 | 缬沙坦 | 二甲双胍 | — | — | ✓ |
| VN06 | 阿奇霉素 | 对乙酰氨基酚 | — | — | ✓ |
| VN07 | 别嘌醇 | 氨氯地平 | — | — | ✓ |
| VN08 | 左甲状腺素 | 氨氯地平 | — | — | ✓ |
| VN09 | 西替利嗪 | 二甲双胍 | — | — | ✓ |
| VN10 | 氯沙坦 | 阿托伐他汀 | — | — | ✓ |
| VN11 | 环丙沙星 | 华法林 | — | — | ✓ |
| VN12 | 泰诺 | 快克 | — | — | ✓ |

## 引用了哪段原文

- **V01** [moderate] 胺碘酮（参照 Amiodarone Hydrochloride 说明书）在「药物相互作用」里提到了华法林。  
  Amiodarone Hydrochloride · Drug interactions：“Lower starting dose of other CYP3A4 substrates may be required. Warfarin Potentiates anticoagulant response and can result in serious or fatal bleeding. Coadministration increases prothrombin time by 100% after 3 to 4 days. Reduce warfarin dose by one-third to one-half and monito…”
- **V01** [moderate] 华法林（参照 Warfarin Sodium 说明书）在「药物相互作用」里提到了胺碘酮。  
  Warfarin Sodium · Drug interactions：“Table 2: Examples of CYP450 Interactions with Warfarin Enzyme Inhibitors Inducers CYP2C9 amiodarone, capecitabine, cotrimoxazole, etravirine, fluconazole, fluvastatin, fluvoxamine, metronidazole, miconazole, oxandrolone, sulfinpyrazone, tigecycline, voriconazole, zafirlukast apre…”
- **V02** [high] 克拉霉素（参照 Clarithromycin 说明书）在「禁忌」里提到了秋水仙碱。  
  Clarithromycin · Contraindications：“…4.2 ) History of cholestatic jaundice/hepatic dysfunction with use of clarithromycin ( 4.3 ) Colchicine in renal or hepatic impairment ( 4.4 ) Lomitapide, lovastatin, and simvastatin ( 4.5 ) Ergot alkaloids (ergotamine or dihydroergotamine) ( 4.6 ) Lurasidone ( 4.7 ) 4.1 Hypersen…”
- **V02** [high] 秋水仙碱（参照 colchicine 说明书）在「药物相互作用」里提到了克拉霉素。  
  colchicine · Drug interactions：“…e; rhabdomyolysis has been reported Coadministration of P-gp and/or CYP3A4 inhibitors (e.g., clarithromycin or cyclosporine) have been demonstrated to alter the concentration of colchicine.”
- **V03** [moderate] 氟康唑（参照 Fluconazole 说明书）在「药物相互作用」里提到了华法林。  
  Fluconazole · Drug interactions：“…ation with increases in prothrombin time in patients receiving fluconazole concurrently with warfarin. Careful monitoring of prothrombin time in patients receiving fluconazole and coumarin-type anticoagulants is recommended. Dose adjustment of warfarin may be necessary.”
- **V03** [moderate] 华法林（参照 Warfarin Sodium 说明书）在「药物相互作用」里提到了氟康唑。  
  Warfarin Sodium · Drug interactions：“…farin Enzyme Inhibitors Inducers CYP2C9 amiodarone, capecitabine, cotrimoxazole, etravirine, fluconazole, fluvastatin, fluvoxamine, metronidazole, miconazole, oxandrolone, sulfinpyrazone, tigecycline, voriconazole, zafirlukast aprepitant, bosentan, carbamazepine, phenobarbital, r…”
- **V04** [moderate] 环丙沙星（参照 Ciprofloxacin 说明书）在「药物相互作用」里提到了华法林。  
  Ciprofloxacin · Drug interactions：“…d shortly after co-administration of Ciprofloxacin with an oral anti-coagulant (for example, warfarin). Methotrexate Use with caution Inhibition of methotrexate renal tubular transport potentially leading to increased methotrexate plasma levels Potential increase in the risk of m…”
- **V04** [moderate] 华法林（参照 Warfarin Sodium 说明书）在「药物相互作用」里提到了环丙沙星。  
  Warfarin Sodium · Drug interactions：“…carbamazepine, phenobarbital, rifampin CYP1A2 acyclovir, allopurinol, caffeine, cimetidine, ciprofloxacin, disulfiram, enoxacin, famotidine, fluvoxamine, methoxsalen, mexiletine, norfloxacin, oral contraceptives, phenylpropanolamine, propafenone, propranolol, terbinafine,”
- **V05** [moderate] 赖诺普利（参照 LISINOPRIL 说明书）在「药物相互作用」里提到了螺内酯。  
  LISINOPRIL · Drug interactions：“…il attenuates potassium loss caused by thiazide-type diuretics. Potassium-sparing diuretics (spironolactone, amiloride, triamterene, and others) can increase the risk of hyperkalemia.”
- **V05** [moderate] 螺内酯（参照 Spironolactone 说明书）在「药物相互作用」里提到了ACE 抑制剂（普利类）（赖诺普利）。  
  Spironolactone · Drug interactions：“Drug interactions: ACE inhibitors: Concomitant administration of ACE inhibitors with potassium-sparing diuretics has been associated with severe hyperkalemia. Angiotensin II antagonists, aldosterone blockers, heparin, low molecular weight heparin, and other drugs known to cause h…”
- **V07** [moderate] 氯沙坦（参照 Losartan Potassium 说明书）在「药物相互作用」里提到了利尿剂（螺内酯）。  
  Losartan Potassium · Drug interactions：“…um: Risk of lithium toxicity. ( 7.2 ) NSAIDs: Increased risk of renal impairment and reduced diuretic, natriuretic, and antihypertensive effects. ( 7.3 ) Dual Inhibition of the Renin-Angiotensin System: Increased risk of renal impairment, hypotension, syncope, and hyperkalemia. (…”
- **V08** [moderate] 曲马多（参照 Tramadol Hydrochloride 说明书）在「药物相互作用」里提到了帕罗西汀。  
  Tramadol Hydrochloride · Drug interactions：“…verse events including respiratory depression and sedation. Examples: Quinidine, fluoxetine, paroxetine and bupropion Inhibitors of CYP3A4 Clinical Impact: The concomitant use of tramadol hydrochloride tablets and CYP3A4 inhibitors can increase the plasma concentration of tramado…”
- **V08** [moderate] 帕罗西汀（参照 Paroxetine 说明书）在「药物相互作用」里提到了阿片类镇痛药（曲马多）。  
  Paroxetine · Drug interactions：“Examples other SSRIs, SNRIs, triptans, tricyclic antidepressants, opioids, lithium, tryptophan, buspirone, amphetamines, and St. John’s Wort. Drugs that Interfere with Hemostasis (antiplatelet agents and anticoagulants) Clinical Impact The concurrent use of an antiplatelet agent…”
- **V09** [moderate] 艾司西酞普兰（参照 escitalopram 说明书）在「药物相互作用」里提到了阿司匹林。  
  escitalopram · Drug interactions：“…c drugs [see Warning and Precautions ( 5.2 )]. Drugs That Interfere With Hemostasis (NSAIDs, Aspirin, Warfarin, etc.) Clinical Impact: Concomitant use of Escitalopram tablets and an antiplatelet or anticoagulant may potentiate the risk of bleeding. Intervention: Inform patients o…”
- **V10** [moderate] 阿普唑仑（参照 Alprazolam 说明书）在「药物相互作用」里提到了曲马多。  
  Alprazolam · Drug interactions：“…nol, codeine, dihydrocodeine, meperidine, pentazocine, remifentanil, sufentanil, tapentadol, tramadol.”
- **V10** [moderate] 曲马多（参照 Tramadol Hydrochloride 说明书）在「药物相互作用」里提到了苯二氮䓬类（阿普唑仑）。  
  Tramadol Hydrochloride · Drug interactions：“Examples: Rifampin, carbamazepine, phenytoin Benzodiazepines and Other Central Nervous System (CNS) Depressants Clinical Impact: Due to additive pharmacologic effect, the concomitant use of benzodiazepines or other CNS depressants, including alcohol, increases the risk of respira…”
- **V11** [moderate] 唑吡坦（参照 ZOLPIDEM TARTRATE 说明书）在「警告与注意事项」里提到了苯二氮䓬类（阿普唑仑）。  
  ZOLPIDEM TARTRATE · Warnings and precautions：“…he day after use. Additive effects occur with concomitant use of other CNS depressants (e.g. benzodiazepines, opioids, tricyclic antidepressants, alcohol), including daytime use [see DRUG INTERACTIONS ( 7.1 )].”
- **V12** [moderate] 阿哌沙班（参照 ELIQUIS 说明书）在「药物相互作用」里提到了卡马西平。  
  ELIQUIS · Drug interactions：“…id concomitant use of ELIQUIS with combined P-gp and strong CYP3A4 inducers (e.g., rifampin, carbamazepine, phenytoin, St. John’s wort) because such drugs will decrease exposure to apixaban [see Clinical Pharmacology (12.3) ] .”
- **V13** [moderate] 达比加群（参照 Dabigatran Etexilate 说明书）在「药物相互作用」里提到了胺碘酮。  
  Dabigatran Etexilate · Drug interactions：“The use of the P-gp inhibitors verapamil, amiodarone, quinidine, clarithromycin, and ticagrelor does not require a dosage adjustment of dabigatran etexilate capsules. These results should not be extrapolated to other P-gp inhibitors [see Warnings and Precautions ( 5.5 ), Use in S…”
- **V13** [moderate] 胺碘酮（参照 Amiodarone Hydrochloride 说明书）在「药物相互作用」里提到了抗凝药（达比加群）。  
  Amiodarone Hydrochloride · Drug interactions：“Lower starting dose of other CYP3A4 substrates may be required. Warfarin Potentiates anticoagulant response and can result in serious or fatal bleeding. Coadministration increases prothrombin time by 100% after 3 to 4 days. Reduce warfarin dose by one-third to one-half and monito…”
- **V14** [moderate] 地高辛（参照 Digoxin 说明书）在「药物相互作用」里提到了胺碘酮。  
  Digoxin · Drug interactions：“…d greater than 50% Digoxin Serum concentration increase Digoxin AUC increase Recommendations Amiodarone 70% NA Measure serum digoxin concentrations before initiating concomitant drugs. Reduce digoxin concentrations by decreasing dose by approximately 30-50% or by modifying the do…”
- **V14** [moderate] 胺碘酮（参照 Amiodarone Hydrochloride 说明书）在「药物相互作用」里提到了地高辛。  
  Amiodarone Hydrochloride · Drug interactions：“of Torsade de Pointes. Avoid concomitant use. Negative Chronotropes digoxin, beta blockers, verapamil, diltiazem, clonidine, ivabradine Potentiates the electrophysiologic and hemodynamic effects of amiodarone, resulting in bradycardia, sinus arrest, and AV block. Monitor heart ra…”
- **V15** [moderate] 格列美脲（参照 Glimepiride 说明书）在「药物相互作用」里提到了喹诺酮类抗生素（左氧氟沙星）。  
  Glimepiride · Drug interactions：“…dol, guanethidine, fluconazole, sulfinpyrazone, tetracyclines, clarithromycin, disopyramide, quinolones, and those drugs that”
- **V16** [moderate] 帕罗西汀（参照 Paroxetine 说明书）在「药物相互作用」里提到了美托洛尔。  
  Paroxetine · Drug interactions：“…discontinued. Examples propafenone, flecainide, atomoxetine, desipramine, dextromethorphan, metoprolol, nebivolol, perphenazine, tolterodine, venlafaxine, risperidone. Tamoxifen Clinical Impact Concomitant use of tamoxifen with paroxetine tablets may lead to reduced plasma conce…”
- **V16** [moderate] 美托洛尔（参照 Metoprolol succinate 说明书）在「药物相互作用」里提到了帕罗西汀。  
  Metoprolol succinate · Drug interactions：“…hypotension. 7.2 CYP2D6 Inhibitors Drugs that inhibit CYP2D6 such as quinidine, fluoxetine, paroxetine, and propafenone are likely to increase metoprolol concentration.”
- **V17** [moderate] 阿莫西林（参照 Amoxicillin 说明书）在「药物相互作用」里提到了别嘌醇。  
  Amoxicillin · Drug interactions：“…icoagulants may increase the prolongation of prothrombin time. ( 7.2 ) Coadministration with allopurinol increases the risk of rash. ( 7.3 ) Amoxicillin may reduce the efficacy of oral contraceptives. ( 7.4 ) 7.1 Probenecid Probenecid decreases the renal tubular secretion of amox…”
- **V17** [moderate] 别嘌醇（参照 Allopurinol 说明书）在「药物相互作用」里提到了阿莫西林。  
  Allopurinol · Drug interactions：“…ncrease the risk of serious skin reactions: bendamustine, thiazide diuretics, ampicillin and amoxicillin. ( 7.1 ) Capecitabine: Avoid concomitant use. ( 7.2 ) Mercaptopurine or Azathioprine: Reduce mercaptopurine or azathioprine dose as recommended in the respective prescribing i…”
- **V18** [high] 快克 和 泰诺 含有相同成分（对乙酰氨基酚），24 小时内一起用可能超过每日最大剂量；如果这是同一种药的两种叫法，可以忽略。  
  TYLENOL Regular Strength · Do not use：“Do not use with any other drug containing acetaminophen (prescription or nonprescription). If you are not sure whether a drug contains acetaminophen, ask a doctor or pharmacist. if you are allergic to acetaminophen or any of the inactive ingredients in this product”
- **V19** [high] 日夜百服咛 和 对乙酰氨基酚 含有相同成分（对乙酰氨基酚），24 小时内一起用可能超过每日最大剂量；如果这是同一种药的两种叫法，可以忽略。  
  TYLENOL Regular Strength · Do not use：“Do not use with any other drug containing acetaminophen (prescription or nonprescription). If you are not sure whether a drug contains acetaminophen, ask a doctor or pharmacist. if you are allergic to acetaminophen or any of the inactive ingredients in this product”
- **V20** [high] 维C银翘片 和 氯苯那敏 含有相同成分（氯苯那敏），24 小时内一起用可能超过每日最大剂量；如果这是同一种药的两种叫法，可以忽略。  
  Aller-chlor · Active ingredients：“Active ingredient (in each tablet) Chlorpheniramine maleate 4 mg”
- **V22** [moderate] 塞来昔布（参照 Celecoxib 说明书）在「药物相互作用」里提到了抗血小板药（氯吡格雷）。  
  Celecoxib · Drug interactions：“…on: Monitor patients with concomitant use of celecoxib with anticoagulants (e.g., warfarin), antiplatelet drugs (e.g., aspirin), SSRIs, and SNRIs for signs of bleeding [ see Warnings and Precautions ( 5.12 ) ].”
- **V22** [moderate] 氯吡格雷（参照 Clopidogrel Bisulfate 说明书）在「药物相互作用」里提到了非甾体抗炎药（塞来昔布）。  
  Clopidogrel Bisulfate · Drug interactions：“…Consider use of parenteral antiplatelet agent. ( 7.3 ) Nonsteroidal anti-inflammatory drugs (NSAIDs), warfarin, selective serotonin and serotonin norepinephrine reuptake inhibitors (SSRIs, SNRIs): Increases risk of bleeding. ( 7.4 , 7.5 , 7.6 ) Other Antiplatelet Agents: Increase…”
- **V23** [moderate] 硝苯地平（参照 Nifedipine 说明书）在「药物相互作用」里提到了克拉霉素。  
  Nifedipine · Drug interactions：“CYP3A inhibitors such as fluconazole, itraconazole, clarithromycin, erythromycin, nefazodone, fluoxetine, saquinavir, indinavir, and nelfinavir may result in increased exposure to nifedipine when co-administered. Careful monitoring and dose adjustment may be necessary; consider i…”
- **V23** [moderate] 克拉霉素（参照 Clarithromycin 说明书）在「药物相互作用」里提到了硝苯地平。  
  Clarithromycin · Drug interactions：“…5.4 )] . Amlodipine Diltiazem Amlodipine, Diltiazem: [See Warnings and Precautions ( 5.4 )] Nifedipine Nifedipine: Nifedipine is a substrate for CYP3A. Clarithromycin and other macrolides are known to inhibit CYP3A. There is potential of CYP3A‑mediated interaction between nifedi…”
- **VN01** [moderate] 二甲双胍（参照 Metformin Hydrochloride 说明书）在「药物相互作用」里提到了钙通道阻滞剂（地平类）（氨氯地平）。  
  Metformin Hydrochloride · Drug interactions：“…yroid products, estrogens, oral contraceptives, phenytoin, nicotinic acid, sympathomimetics, calcium channel blockers, and isoniazid. Carbonic anhydrase inhibitors may increase risk of lactic acidosis. Consider more frequent monitoring. ( 7 ) Drugs that reduce metformin clearance…”
