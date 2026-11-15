#!/usr/bin/env python3
"""Scores every eval/redflag/predictions/<detector>.jsonl against eval/redflag/cases.jsonl.

    python3 eval/redflag/score.py              # dev + test, writes REPORT.md and results.json
    python3 eval/redflag/score.py --split dev

Metrics (a "flag" is any alert, emergency or crisis):
- recall: danger sentences that raised a flag. The number that matters: a miss can cost a life.
- false-alarm rate: safe sentences that raised a flag. Accepted when it buys recall, but it is reported.
- crisis routed right: crisis sentences flagged as crisis (the hotline advice), not just as an emergency.
- per group: share of sentences flagged, so it is visible where each detector wins or loses.
- latency p50 / p95 per sentence, as measured by the harness.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "—"


def score(cases: list[dict], preds: dict[str, dict]) -> dict:
    pos = [c for c in cases if c["label"]]
    neg = [c for c in cases if not c["label"]]
    flagged = lambda c: bool(preds[c["id"]].get("flag"))
    crisis = [c for c in pos if c["label"] == "crisis"]
    ms = sorted(preds[c["id"]].get("ms", 0.0) for c in cases)
    groups = defaultdict(list)
    for c in cases:
        groups[c["group"]].append(flagged(c))
    return {
        "n": len(cases),
        "recall": [sum(map(flagged, pos)), len(pos)],
        "false_alarms": [sum(map(flagged, neg)), len(neg)],
        "crisis_routed": [sum(preds[c["id"]].get("flag") == "crisis" for c in crisis), len(crisis)],
        "groups": {g: [sum(v), len(v)] for g, v in groups.items()},
        "p50_ms": statistics.median(ms) if ms else 0.0,
        "p95_ms": ms[min(len(ms) - 1, int(0.95 * len(ms)))] if ms else 0.0,
        "misses": [c["id"] for c in pos if not flagged(c)],
        "false_alarm_ids": [c["id"] for c in neg if flagged(c)],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"])
    args = parser.parse_args()
    cases = load(HERE / "cases.jsonl")
    by_id = {c["id"]: c for c in cases}
    splits = [args.split] if args.split else ["dev", "test"]
    results: dict[str, dict] = {}
    lines = ["# 危险信号评测结果", "", "由 `python3 eval/redflag/score.py` 生成。方法和说明见 [README.md](README.md)。", ""]
    detectors = sorted(p.stem for p in (HERE / "predictions").glob("*.jsonl"))
    for split in splits:
        subset = [c for c in cases if c["split"] == split]
        lines += [f"## {split}（{len(subset)} 句）", "",
                  "| | " + " | ".join(detectors) + " |", "|---|" + "---|" * len(detectors)]
        per = {}
        for name in detectors:
            preds = {p["id"]: p for p in load(HERE / "predictions" / f"{name}.jsonl")}
            if not all(c["id"] in preds for c in subset):
                continue
            per[name] = score(subset, preds)
        results[split] = per
        names = list(per)
        row = lambda label, f: lines.append(f"| {label} | " + " | ".join(f(per[n]) for n in names) + " |")
        row("召回率（危险句被提醒）", lambda s: f"**{pct(*s['recall'])}** ({s['recall'][0]}/{s['recall'][1]})")
        row("误报率（安全句被提醒）", lambda s: f"{pct(*s['false_alarms'])} ({s['false_alarms'][0]}/{s['false_alarms'][1]})")
        row("心理危机给出热线", lambda s: f"{pct(*s['crisis_routed'])} ({s['crisis_routed'][0]}/{s['crisis_routed'][1]})")
        row("延迟 p50 / p95", lambda s: f"{s['p50_ms']:.0f} / {s['p95_ms']:.0f} ms")
        lines += ["", "按类别（被提醒的比例；前五类应提醒，后五类不应提醒）：", "",
                  "| 类别 | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
        for group in dict.fromkeys(c["group"] for c in subset):
            lines.append(f"| {group} | " + " | ".join(pct(*per[n]["groups"][group]) for n in names) + " |")
        for name in names:
            s = per[name]
            preds = {p["id"]: p for p in load(HERE / "predictions" / f"{name}.jsonl")}
            if s["misses"] or s["false_alarm_ids"]:
                lines += ["", f"**{name} 的错例**", ""]
                lines += [f"- 漏报 `{i}` {by_id[i]['text']}" for i in s["misses"]]
                lines += [f"- 误报 `{i}` {by_id[i]['text']} → {preds[i].get('flag')}「{preds[i].get('evidence', '')}」"
                          for i in s["false_alarm_ids"]]
        lines.append("")
    if not args.split:
        (HERE / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
        (HERE / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
