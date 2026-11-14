#!/usr/bin/env python3
"""Scores every eval/routing/predictions/<router>.jsonl against eval/routing/utterances.jsonl.

    python3 eval/routing/score.py            # dev + test, writes REPORT.md and results.json
    python3 eval/routing/score.py --split dev

Metrics
- plan exact match: same tools (as a multiset) AND every checked argument right. The number that matters to a user.
- tool selection: same multiset of tools, arguments ignored.
- per tool precision / recall / F1 over (utterance, tool) instances.
- argument accuracy on matched instances: drug name, symptom category, department (only when the user named one),
  date (only when the user gave one), relative.
- latency p50 / p95 per utterance, as measured by the harness.

Lenient on purpose where downstream code is: "两片泰诺" counts as 泰诺 and "阿司匹林肠溶片" as 阿司匹林 (the safety
review resolves both the same way); synonyms are normalised (头疼 = 头痛, 心内科 = 心血管内科, 我妈 = 妈妈).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
TOOLS = ["record_medication", "record_symptom", "book_appointment", "notify_family", "ask_pharmacist"]

SYMPTOMS = {
    "头晕": ["头晕", "头昏", "晕"], "头痛": ["头痛", "头疼"], "胃痛": ["胃痛", "胃疼", "胃不舒服"],
    "腹痛": ["腹痛", "肚子疼", "肚子痛"], "恶心": ["恶心", "想吐", "反胃", "呕吐"], "发热": ["发热", "发烧"],
    "咳嗽": ["咳嗽", "咳"], "胸闷": ["胸闷"], "乏力": ["乏力", "没劲", "没力气", "无力"], "失眠": ["失眠", "睡不着"],
    "腹泻": ["腹泻", "拉肚子"], "皮疹": ["皮疹", "疹子", "红疹", "起疹"], "心悸": ["心悸", "心慌", "心跳快", "心跳很快"],
    "咽痛": ["咽痛", "嗓子疼", "喉咙痛", "嗓子痛", "喉咙疼"], "腰痛": ["腰痛", "腰疼"], "关节痛": ["关节痛", "关节疼"],
    "肌肉痛": ["肌肉痛", "肌肉疼", "肌肉酸痛"], "出血": ["出血", "流血"],
}
DEPARTMENTS = {
    "消化内科": ["消化内科", "消化科"], "心血管内科": ["心血管内科", "心内科", "心血管科"],
    "神经内科": ["神经内科", "神经科"], "呼吸内科": ["呼吸内科", "呼吸科"], "全科": ["全科"],
    "皮肤科": ["皮肤科", "皮肤"], "内分泌科": ["内分泌科", "内分泌"], "骨科": ["骨科"], "眼科": ["眼科"],
    "耳鼻喉科": ["耳鼻喉科", "耳鼻喉"],
}
RELATIVES = {"妈妈": ["妈妈", "我妈", "老妈", "母亲"], "爸爸": ["爸爸", "我爸", "老爸", "父亲"],
             "老婆": ["老婆", "妻子", "媳妇"], "老公": ["老公", "丈夫"]}
FORMS = ("肠溶片", "缓释胶囊", "缓释片", "胶囊", "片", "喷剂", "喷雾", "糖浆", "颗粒", "注射液", "滴眼液")
QUANTITY = re.compile(r"^(?:[\d一二两三四五六七八九十半几]+\s*[片粒颗包支袋勺]|[片粒颗包支袋]|点)")


def canon(value: str | None, table: dict[str, list[str]]) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    for name, synonyms in table.items():
        if text == name or any(s in text for s in sorted(synonyms, key=len, reverse=True)):
            return name
    return text


def drug(value: str | None) -> str:
    text = re.sub(r"\s+", "", str(value or "")).casefold()
    text = QUANTITY.sub("", text)
    return text[:-1] if text.endswith("药") and len(text) > 2 else text


def same_drug(expected: str, predicted: str | None) -> bool:
    e, p = drug(expected), drug(predicted)
    return e == p or (p.startswith(e) and p[len(e):] in FORMS)


def arg_checks(expected: dict, predicted: dict) -> dict[str, bool]:
    tool = expected["tool"]
    if tool == "record_medication":
        return {"drug_name": same_drug(expected["name"], predicted.get("name"))}
    if tool == "record_symptom":
        return {"symptom": canon(expected["category"], SYMPTOMS) == canon(predicted.get("category"), SYMPTOMS)}
    if tool == "book_appointment":
        checks = {}
        if expected.get("department"):
            checks["department"] = canon(expected["department"], DEPARTMENTS) == \
                canon(predicted.get("department"), DEPARTMENTS)
        if expected.get("date"):
            checks["date"] = expected["date"] == predicted.get("date")
        return checks
    if tool == "notify_family":
        return {"relative": canon(expected["to"], RELATIVES) == canon(predicted.get("to"), RELATIVES)}
    return {}


def match(expected: list[dict], predicted: list[dict]):
    """Pairs instances of the same tool, preferring pairs whose arguments agree (order-independent)."""
    pairs, left = [], list(predicted)
    for e in sorted(expected, key=lambda s: s["tool"]):
        candidates = [p for p in left if p.get("tool") == e["tool"]]
        if not candidates:
            continue
        best = max(candidates, key=lambda p: sum(arg_checks(e, p).values()))
        left.remove(best)
        pairs.append((e, best))
    return pairs


def score(rows: list[dict], predictions: dict[str, dict]) -> dict:
    tool_tp, tool_fp, tool_fn = Counter(), Counter(), Counter()
    args_ok, args_n = Counter(), Counter()
    exact = selection = 0
    by_group = defaultdict(lambda: [0, 0])
    failures, latencies = [], []
    for row in rows:
        pred = predictions.get(row["id"], {"steps": [], "ms": None})
        steps = [s for s in pred["steps"] if s.get("tool") in TOOLS]
        if pred.get("ms") is not None:
            latencies.append(pred["ms"])
        e_count, p_count = Counter(s["tool"] for s in row["expect"]), Counter(s["tool"] for s in steps)
        for tool in TOOLS:
            tp = min(e_count[tool], p_count[tool])
            tool_tp[tool] += tp
            tool_fp[tool] += p_count[tool] - tp
            tool_fn[tool] += e_count[tool] - tp
        same_tools = e_count == p_count
        all_args = True
        wrong_args = []
        for e, p in match(row["expect"], steps):
            for name, ok in arg_checks(e, p).items():
                args_n[name] += 1
                args_ok[name] += ok
                if not ok:
                    all_args = False
                    wrong_args.append(f"{name}: expected {e.get('name') or e.get('category') or e.get('department') if name != 'date' else e.get('date')}"
                                      f" / got {p.get('name') or p.get('category') or p.get('department') or p.get('to') if name != 'date' else p.get('date')}")
        selection += same_tools
        ok = same_tools and all_args
        exact += ok
        by_group[row["group"]][0] += ok
        by_group[row["group"]][1] += 1
        if not ok:
            failures.append({"id": row["id"], "text": row["text"],
                             "expected": [s["tool"] for s in row["expect"]], "got": [s["tool"] for s in steps],
                             "args": wrong_args})
    n = len(rows)
    per_tool = {}
    for tool in TOOLS:
        tp, fp, fn = tool_tp[tool], tool_fp[tool], tool_fn[tool]
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = 2 * precision * recall / (precision + recall) if precision and recall else 0.0
        per_tool[tool] = {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}
    lat = sorted(latencies)
    return {
        "n": n, "exact": exact / n, "selection": selection / n,
        "per_tool": per_tool,
        "args": {k: {"accuracy": args_ok[k] / args_n[k], "n": args_n[k]} for k in sorted(args_n)},
        "by_group": {g: v[0] / v[1] for g, v in sorted(by_group.items())},
        "latency_ms": {"p50": statistics.median(lat), "p95": lat[int(0.95 * (len(lat) - 1))]} if lat else None,
        "failures": failures,
    }


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def pct(x):
    return "—" if x is None else f"{100 * x:.0f}%"


def report(results: dict[str, dict[str, dict]]) -> str:
    routers = sorted(results)
    lines = ["# 端侧路由评测", "",
             "评测集：`utterances.jsonl`（210 句中文，今天 = 2026-11-16 周一）。dev 用来调规则和提示词，"
             "test 在最终对比前不看。指标定义见 `score.py`。", ""]
    for split in ("dev", "test"):
        lines += [f"## {split}", "", "| 指标 | " + " | ".join(routers) + " |", "|---|" + "---|" * len(routers)]
        r = {name: results[name][split] for name in routers}
        lines.append("| 整句完全正确 | " + " | ".join(pct(r[x]["exact"]) for x in routers) + " |")
        lines.append("| 工具选择正确 | " + " | ".join(pct(r[x]["selection"]) for x in routers) + " |")
        for tool in TOOLS:
            lines.append(f"| {tool} F1 | " + " | ".join(pct(r[x]["per_tool"][tool]["f1"]) for x in routers) + " |")
        for arg in ("drug_name", "symptom", "department", "date", "relative"):
            lines.append(f"| 参数：{arg} | " + " | ".join(
                pct(r[x]["args"].get(arg, {}).get("accuracy")) for x in routers) + " |")
        lines.append("| 延迟 p50 / p95 (ms) | " + " | ".join(
            f"{r[x]['latency_ms']['p50']:.1f} / {r[x]['latency_ms']['p95']:.1f}" if r[x]["latency_ms"] else "—"
            for x in routers) + " |")
        lines += ["", "按类别（整句完全正确）：", "", "| 类别 | " + " | ".join(routers) + " |",
                  "|---|" + "---|" * len(routers)]
        for group in r[routers[0]]["by_group"]:
            lines.append(f"| {group} | " + " | ".join(pct(r[x]["by_group"].get(group)) for x in routers) + " |")
        lines.append("")
    for name in routers:
        fails = results[name]["dev"]["failures"]
        lines += [f"## {name} 在 dev 上的错例（{len(fails)} 条）", ""]
        for f in fails:
            extra = f"；{'；'.join(f['args'])}" if f["args"] else ""
            lines.append(f"- `{f['id']}` {f['text']} → 期望 {f['expected']}，得到 {f['got']}{extra}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all")
    args = parser.parse_args()
    rows = load(HERE / "utterances.jsonl")[1:]
    results = {}
    for path in sorted((HERE / "predictions").glob("*.jsonl")):
        predictions = {p["id"]: p for p in load(path)}
        results[path.stem] = {split: score([r for r in rows if r["split"] == split], predictions)
                              for split in ("dev", "test")}
        for split in ("dev", "test") if args.split == "all" else (args.split,):
            s = results[path.stem][split]
            print(f"{path.stem:>12} {split:>4}: exact {pct(s['exact'])}  selection {pct(s['selection'])}  "
                  f"args {', '.join(f'{k} {pct(v['accuracy'])}' for k, v in s['args'].items())}")
    if args.split == "all":
        (HERE / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (HERE / "REPORT.md").write_text(report(results), encoding="utf-8")


if __name__ == "__main__":
    main()
