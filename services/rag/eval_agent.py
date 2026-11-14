"""Run the multi-turn agent scenarios against live Gemini and write eval/AGENT_REPORT.md.

The signed-in user's medications come from a fixed fixture instead of the sync server, so runs are repeatable.
"""

import argparse
import json
import os
import re
import statistics
import time
from pathlib import Path

from agent import LabelAgent, SessionStore
from app import build_index
from medtrack_server import DEFAULT_MODEL, ApiError, load_local_config

SCENARIOS = Path(__file__).with_name("eval") / "agent_scenarios.json"
SAFE_CLAIM = re.compile(r"\b(is|are|it's|it is|considered)\s+(completely\s+|totally\s+)?safe\b", re.I)
FIXTURE_MEDS = [
    {"name": "PEPCID AC Maximum Strength", "dosage": "20 mg", "frequency": "daily", "time": "08:00", "type": "tablet"},
    {"name": "Benadryl Allergy Extra Strength Liqui-Gels", "dosage": "50 mg", "frequency": "as needed",
     "time": "21:00", "type": "capsule"},
]


class FixtureMedications:
    def list(self, token):
        return FIXTURE_MEDS if token else None


def grade(turn, events):
    answer = events[-1][1]
    called = [d["name"] for e, d in events if e == "tool_call"]
    statuses = [d["status"] for e, d in events if e == "tool_result"]
    tool_ok = all(any(name in called for name in alt.split("|")) for alt in turn["expect_tools"])
    cites = list(answer["citations"].values())
    good = []
    if turn["expect"] == "cited":
        label = tuple(turn["label"])
        good = [c for c in cites if (c["label_id"], c["version"]) == label
                and any(term in c["text"].casefold() for term in turn["must_contain_any"])]
        ok = answer["grounded"] and bool(good)
    elif turn["expect"] == "clarify":
        ok = answer["grounded"] and not cites and "needs_selection" in statuses
    elif turn["expect"] == "uncited":
        ok = answer["grounded"] and not cites
    elif turn["expect"] == "not_safe_claim":
        ok = answer["grounded"] and "not_mentioned" in statuses and not SAFE_CLAIM.search(answer["text"])
    elif turn["expect"] == "no_unsourced":
        ok = (not answer["grounded"]) or bool(cites)
    else:
        raise ValueError(turn["expect"])
    return {"tool_ok": tool_ok, "passed": ok, "called": called, "statuses": statuses, "cited": len(cites),
            "good_citations": len(good) if turn["expect"] == "cited" else None, "grounded": answer["grounded"],
            "refusal_reason": answer["refusal_reason"], "steps": answer["steps"], "text": answer["text"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=SCENARIOS.parent)
    parser.add_argument("--pause", type=float, default=6.0, help="Seconds between turns (free-tier rate limits).")
    args = parser.parse_args()
    load_local_config()
    scenarios = json.loads(SCENARIOS.read_text())
    index = build_index()
    agent = LabelAgent(index, medications=FixtureMedications(), store=SessionStore())
    rows, usage = [], {"prompt": 0, "output": 0}
    for scenario in scenarios:
        token = "Bearer eval-user" if scenario["signed_in"] else None
        session_id, before = None, {"prompt": 0, "output": 0}
        for n, turn in enumerate(scenario["turns"], 1):
            for attempt in range(6):
                try:
                    start = time.perf_counter()
                    events = list(agent.run(turn["message"], session_id, token))
                    break
                except ApiError as error:  # free-tier quota: back off and retry the whole turn
                    if error.payload["code"] not in ("rate_limited", "timeout", "upstream_error") or attempt == 5:
                        raise
                    time.sleep(20 * (attempt + 1))
            elapsed = time.perf_counter() - start
            time.sleep(args.pause)
            session_id = events[0][1]["session_id"]
            result = grade(turn, events)
            result["rejected"] = agent.last_rejected
            total = events[-1][1]["usage"]
            result.update(id=f"{scenario['id']}.{n}", message=turn["message"], expect=turn["expect"],
                          seconds=round(elapsed, 2), prompt_tokens=total["prompt"] - before["prompt"],
                          output_tokens=total["output"] - before["output"])
            before = total
            rows.append(result)
            print(f"{result['id']} pass={result['passed']} tools={result['called']} {result['text'][:90]!r}")
        usage = {k: usage[k] + before[k] for k in usage}
    index.db.close()

    cited_rows = [r for r in rows if r["expect"] == "cited"]
    citations = sum(r["cited"] for r in cited_rows)
    metrics = {
        "turns": len(rows), "conversations": len(scenarios),
        "passed": sum(r["passed"] for r in rows),
        "tool_selection": sum(r["tool_ok"] for r in rows),
        "cited_turns_passed": sum(r["passed"] for r in cited_rows), "cited_turns": len(cited_rows),
        "citation_precision": sum(r["good_citations"] for r in cited_rows) / citations if citations else None,
        "refusals": sum(not r["grounded"] for r in rows),
        "mean_steps": statistics.mean(r["steps"] for r in rows),
        "p50_seconds": statistics.median(r["seconds"] for r in rows),
        "max_seconds": max(r["seconds"] for r in rows),
        "mean_prompt_tokens": statistics.mean(r["prompt_tokens"] for r in rows),
        "mean_output_tokens": statistics.mean(r["output_tokens"] for r in rows),
        "model": os.environ.get("GEMINI_MODEL", DEFAULT_MODEL), "retrieval_mode": agent.mode,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "agent_results.json").write_text(
        json.dumps({"metrics": metrics, "turns": rows}, ensure_ascii=False, indent=2) + "\n")
    m = metrics
    lines = [
        "# MedTrack Agent 多轮评测", "",
        f"{m['conversations']} 段对话、{m['turns']} 轮，模型 `{m['model']}`，检索模式 `{m['retrieval_mode']}`。"
        "登录用户的用药记录来自固定夹具（PEPCID AC Maximum Strength、Benadryl Allergy Extra Strength Liqui-Gels）。"
        "每轮只跑一次，模型输出有随机性，重跑结果可能略有不同。", "",
        "| 指标 | 结果 |", "|---|---:|",
        f"| 整体通过 | {m['passed']}/{m['turns']} |",
        f"| 工具选择正确 | {m['tool_selection']}/{m['turns']} |",
        f"| 需引用的轮次通过 | {m['cited_turns_passed']}/{m['cited_turns']} |",
        f"| 引用精确率（引用落在期望标签且含关键证据） | "
        f"{'N/A' if m['citation_precision'] is None else format(m['citation_precision'], '.1%')} |",
        f"| 被校验拦下的回答 | {m['refusals']} |",
        f"| 平均模型调用步数 | {m['mean_steps']:.2f} |",
        f"| 每轮耗时 P50 / 最大 | {m['p50_seconds']:.1f} s / {m['max_seconds']:.1f} s |",
        f"| 每轮平均 token（输入 / 输出） | {m['mean_prompt_tokens']:.0f} / {m['mean_output_tokens']:.0f} |",
        "", "判定规则：`cited` 要求回答通过引用校验，且至少一条引用来自期望标签并含关键词；`clarify` 要求重名时追问、不带引用；"
        "`uncited` 要求如实说明查不到；`not_safe_claim` 要求说明书未提及时不能说“安全”；`no_unsourced` 要求不凭记忆作答。",
        "", "## 逐轮结果", "", "| 轮次 | 期望 | 通过 | 调用工具 | 回答 |", "|---|---|---|---|---|",
    ]
    for r in rows:
        text = r["text"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['id']} | {r['expect']} | {'✅' if r['passed'] else '❌'} | {', '.join(r['called']) or '—'} | "
                     f"{text[:160]} |")
    (args.output_dir / "AGENT_REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
