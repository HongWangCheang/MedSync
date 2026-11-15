"""Scores the safety review against eval/safety_cases.json.

    python evaluate_safety.py            # prints the table and writes eval/safety/REPORT.md + results.json

Pair-level metrics: an expected pair counts as caught when the review raises an alert naming that existing
medication; any alert on a pair not in `expect` is a false alert. Cases marked "high" must also be graded high.
Recall matters most here (a missed interaction is worse than an extra prompt); precision is reported alongside.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from label_corpus import DEFAULT_CORPUS
from label_retrieval import LabelIndex, LabelSnapshot
from safety_review import HOUR_MS, SafetyChecker

HERE = Path(__file__).parent
CASES = HERE / "eval" / "safety_cases.json"
OUT = HERE / "eval" / "safety"
NOW = 1_800_000_000_000


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def run(checker: SafetyChecker, cases: list[dict]) -> list[dict]:
    rows = []
    for case in cases:
        meds = [{"name": m["name"], "last_taken_at": NOW - int(m.get("hours_ago", 2) * HOUR_MS)}
                for m in case["existing"]]
        review = checker.review(case["new"], meds, taken_at=NOW)
        alerted = {a["with"]: a for a in review["alerts"]}
        expected = set(case["expect"])
        rows.append({
            "id": case["id"], "new": case["new"], "existing": [m["name"] for m in case["existing"]],
            "expected": sorted(expected), "alerted": sorted(alerted),
            "caught": sorted(expected & alerted.keys()), "missed": sorted(expected - alerted.keys()),
            "false": sorted(alerted.keys() - expected),
            "high_ok": (not case.get("high")) or all(alerted.get(e, {}).get("severity") == "high" for e in expected),
            "status": review["status"], "unresolved": review["unresolved"],
            "medication": review["medication"],
            "findings": [{"with": a["with"], "severity": a["severity"], "summary": f["summary"],
                          "label": f["citation"].get("label"), "section": f["citation"].get("section"),
                          "excerpt": f["citation"].get("excerpt")}
                         for a in review["alerts"] for f in a["findings"]],
            "why": case.get("why"), "high": bool(case.get("high")),
        })
    return rows


def summarize(rows: list[dict]) -> dict:
    expected = sum(len(r["expected"]) for r in rows)
    caught = sum(len(r["caught"]) for r in rows)
    alerts = sum(len(r["alerted"]) for r in rows)
    false = sum(len(r["false"]) for r in rows)
    negatives = [r for r in rows if not r["expected"]]
    high_cases = [r for r in rows if r["high"]]
    return {
        "cases": len(rows), "expected_pairs": expected, "caught": caught, "recall": caught / expected if expected else 0,
        "recall_ci": wilson(caught, expected), "alerts": alerts, "false_alerts": false,
        "precision": (alerts - false) / alerts if alerts else 0, "precision_ci": wilson(alerts - false, alerts),
        "negative_cases": len(negatives), "negatives_clean": sum(1 for r in negatives if not r["alerted"]),
        "high_grading_ok": sum(1 for r in high_cases if r["high_ok"]), "high_cases": len(high_cases),
        "positive_cases": len(rows) - len(negatives),
    }


DEV_NOTE = [
    "**这是开发集，不是盲测。** 写检查器时用这批用例调过三处：过敏语境里的提及不算（“allergic to aspirin”）、"
    "否定句不算（Lipitor “no clinically significant effect … warfarin”）、同成分多个说明书时选有相互作用章节的那份。"
    "所以数字偏乐观，换一批新用例才是真实水平（见 [../safety_blind/REPORT.md](../safety_blind/REPORT.md)）。",
    "",
    "漏报都是数据或词表覆盖不到：说明书没写（布洛芬或奥美拉唑与氯吡格雷）、名字不在别名表（克拉霉素，会作为“未识别”"
    "明确告诉用户）、两种抗组胺药的说明书互不提及。检查器只说“说明书写了什么”，不凭常识补。",
]
BLIND_NOTE = [
    "**这是盲测集。** 用例在检查器规则定下之后按一般药理常识编写，先提交到 git、后运行，"
    "没有在这些药对上调过规则，结果出来以后也不改规则。所以这里的数字才是检查器在新数据上的水平。",
]


def report(rows: list[dict], summary: dict, blind: bool = False) -> str:
    pct = lambda x: f"{100 * x:.0f}%"
    ci = lambda pair: f"{pct(pair[0])}–{pct(pair[1])}"
    lines = [
        "# 安全审核评测：相互作用提醒" + ("（盲测）" if blind else ""),
        "",
        f"用例 {summary['cases']} 个（正例 {summary['positive_cases']}，负例 {summary['negative_cases']}），"
        "预期答案按一般药理常识预先写好，不是照着检查器的输出写的。",
        "",
        "| 指标 | 结果 |",
        "| --- | --- |",
        f"| 召回率（该提醒的对子有没有提醒） | {summary['caught']}/{summary['expected_pairs']} = "
        f"{pct(summary['recall'])}（95% CI {ci(summary['recall_ci'])}） |",
        f"| 精确率（提醒里有多少是对的） | {summary['alerts'] - summary['false_alerts']}/{summary['alerts']} = "
        f"{pct(summary['precision'])}（95% CI {ci(summary['precision_ci'])}） |",
        f"| 负例无误报 | {summary['negatives_clean']}/{summary['negative_cases']} |",
        f"| 标为 high 的用例判成 high | {summary['high_grading_ok']}/{summary['high_cases']} |",
        "",
        *(BLIND_NOTE if blind else DEV_NOTE),
        "",
        "## 逐条结果",
        "",
        "| 用例 | 新记录 | 已有记录 | 预期提醒 | 实际提醒 | 结论 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        if r["missed"]:
            verdict = "漏报" + (f"（未识别：{'、'.join(r['unresolved'])}）" if r["unresolved"] else "")
        elif r["false"]:
            verdict = "误报"
        elif not r["high_ok"]:
            verdict = "分级偏低"
        else:
            verdict = "✓"
        lines.append(f"| {r['id']} | {r['new']} | {'、'.join(r['existing'])} | {'、'.join(r['expected']) or '—'} | "
                     f"{'、'.join(r['alerted']) or '—'} | {verdict} |")
    lines += ["", "## 引用了哪段原文", ""]
    for r in rows:
        for f in r["findings"]:
            excerpt = (f["excerpt"] or "").replace("|", "/")
            lines.append(f"- **{r['id']}** [{f['severity']}] {f['summary']}  \n  {f['label']} · {f['section']}：“{excerpt}”")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--cases", default=str(CASES))
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--blind", action="store_true",
                        help="score eval/safety_blind_cases.json into eval/safety_blind/ (run once; do not tune on it)")
    args = parser.parse_args()
    records = json.loads(Path(args.corpus).read_text(encoding="utf-8"))["results"]
    checker = SafetyChecker(LabelIndex(LabelSnapshot(records, public=True), model=None))
    cases = HERE / "eval" / "safety_blind_cases.json" if args.blind else Path(args.cases)
    out = HERE / "eval" / "safety_blind" if args.blind else OUT
    rows = run(checker, json.loads(cases.read_text(encoding="utf-8"))["cases"])
    summary = summarize(rows)
    for r in rows:
        print(f"{r['id']:4} expected={r['expected']} alerted={r['alerted']} high_ok={r['high_ok']} "
              f"unresolved={r['unresolved']} med={r['medication']}")
    print(json.dumps({k: v for k, v in summary.items()}, ensure_ascii=False))
    if not args.no_write:
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2)
                                          + "\n", encoding="utf-8")
        (out / "REPORT.md").write_text(report(rows, summary, args.blind), encoding="utf-8")


if __name__ == "__main__":
    main()
