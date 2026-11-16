#!/usr/bin/env python3
"""The 12 multi-turn pharmacist dialogues from MedTrack (services/rag/eval/agent_scenarios.json), sent through the
whole MedSync chain instead of calling the agent in-process:

    device (this script) → gateway → agent (ask_pharmacist step, delegated token) → rag → Gemini

and graded with the same rules as services/rag/eval_agent.py, so the two can be compared turn by turn. The signed-in
dialogue reads "my medications" the MedSync way: the fixture medicines are recorded through the gateway first and
the pharmacist reads them back with the gateway's short-lived delegated token.

    scripts/up.sh && python3 eval/pharmacist_chain/run_chain.py      # needs GEMINI_API_KEY in .env (~40 model calls)

Differences from the in-process run, by construction: the device stores only the start of each cited passage
(EXCERPT_CHARS), so the key phrase is checked against the label paragraph that excerpt comes from, looked up in the
same local snapshots the rag service serves; and each turn is one dispatched step, so the gateway may retry a turn the
free-tier rate limit refused.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import smoke  # noqa: E402  (stdlib HTTP helpers and step builder)

SNAPSHOTS = [ROOT / "services/rag/data/openfda_labels.json", ROOT / "services/rag/data/openfda_rx_labels.json"]
SCENARIOS = ROOT / "services/rag/eval/agent_scenarios.json"
IN_PROCESS = ROOT / "services/rag/eval/agent_results.json"
FIXTURE_MEDS = ["PEPCID AC Maximum Strength", "Benadryl Allergy Extra Strength Liqui-Gels"]
SAFE_CLAIM = re.compile(r"\b(is|are|it's|it is|considered)\s+(completely\s+|totally\s+)?safe\b", re.I)
PAUSE_S = 6.0          # free-tier Gemini: ~15 requests a minute
TURN_BUDGET_S = 240.0  # a rate-limited turn is re-dispatched by the gateway until it gets through


def register() -> str:
    status, session = smoke.http("POST", f"{smoke.GATEWAY}/v1/auth/register",
                                 {"username": f"chain_{uuid.uuid4().hex[:8]}", "password": "chain-pass-1"})
    if status != 201:
        raise SystemExit(f"cannot register through {smoke.GATEWAY} (HTTP {status}); is the stack up?")
    return session["token"]


def settle(step: dict, token: str) -> dict:
    """Submit like the device does, then poll until the step is final."""
    started = time.monotonic()
    _, view = smoke.http("POST", f"{smoke.GATEWAY}/v1/actions", step, token, timeout=120)
    while (view or {}).get("status") in (None, "ACCEPTED", "PENDING") and time.monotonic() - started < TURN_BUDGET_S:
        time.sleep(2)
        _, view = smoke.http("GET", f"{smoke.GATEWAY}/v1/actions/{step['stepKey']}", token=token, timeout=120)
    return {**(view or {}), "seconds": round(time.monotonic() - started, 2)}


_PARAGRAPHS: dict[tuple[str, str], list[str]] = {}


def paragraph(citation: dict) -> str:
    """The label paragraph a stored excerpt was cut from (the excerpt itself when it cannot be found)."""
    if not _PARAGRAPHS:
        for path in SNAPSHOTS:
            if path.exists():
                for record in json.loads(path.read_text(encoding="utf-8"))["results"]:
                    _PARAGRAPHS[(record["id"], str(record["version"]))] = [
                        text for value in record.values() if isinstance(value, list)
                        for text in value if isinstance(text, str)]
    excerpt = (citation.get("excerpt") or "").strip("…").strip()
    head = " ".join(excerpt.split())[:60]
    for text in _PARAGRAPHS.get((citation.get("label_id"), str(citation.get("version"))), []):
        if head and head in " ".join(text.split()):
            return text
    return excerpt


def grade(turn: dict, result: dict) -> dict:
    """services/rag/eval_agent.py's rules, applied to what the device receives."""
    called, statuses = result.get("tools", []), result.get("tool_statuses", [])
    tool_ok = all(any(name in called for name in alt.split("|")) for alt in turn["expect_tools"])
    cites, grounded, text = result.get("citations", []), bool(result.get("grounded")), result.get("answer", "")
    good = []
    if turn["expect"] == "cited":
        label = tuple(turn["label"])
        good = [c for c in cites if (c.get("label_id"), c.get("version")) == label
                and any(term in paragraph(c).casefold() for term in turn["must_contain_any"])]
        ok = grounded and bool(good)
    elif turn["expect"] == "clarify":
        ok = grounded and not cites and "needs_selection" in statuses
    elif turn["expect"] == "uncited":
        ok = grounded and not cites
    elif turn["expect"] == "not_safe_claim":
        ok = grounded and "not_mentioned" in statuses and not SAFE_CLAIM.search(text)
    elif turn["expect"] == "no_unsourced":
        ok = (not grounded) or bool(cites)
    else:
        raise ValueError(turn["expect"])
    return {"tool_ok": tool_ok, "passed": ok, "called": called, "statuses": statuses,
            "citations": [{k: c.get(k) for k in ("label", "label_id", "version", "section", "excerpt")} for c in cites],
            "cited": len(cites), "good_citations": len(good) if turn["expect"] == "cited" else None,
            "grounded": grounded, "text": text}


def main() -> int:
    scenarios = json.loads(SCENARIOS.read_text())
    rows = []
    for scenario in scenarios:
        token = register()  # a fresh user per dialogue, as in the in-process run
        if scenario["signed_in"]:
            now = int(time.time() * 1000)
            for name in FIXTURE_MEDS:
                settle(smoke.step("record_medication", {"name": name, "takenAt": now - 3_600_000, "note": ""},
                                  toolClass="WRITE_IDEMPOTENT"), token)
        session_id, plan = None, uuid.uuid4().hex
        for n, turn in enumerate(scenario["turns"], 1):
            payload = {"question": turn["message"], **({"session_id": session_id} if session_id else {})}
            step = smoke.step("ask_pharmacist", payload, planId=plan, stepIndex=n - 1, toolClass="READ")
            view = settle(step, token)
            result = view.get("result") or {}
            session_id = result.get("session_id") or session_id
            row = {"id": f"{scenario['id']}.{n}", "expect": turn["expect"], "status": view.get("status"),
                   "reason": view.get("reason"), "seconds": view["seconds"], **grade(turn, result)}
            rows.append(row)
            print(f"{row['id']} {row['status']} pass={row['passed']} tools={row['called']} {row['text'][:80]!r}",
                  flush=True)
            time.sleep(PAUSE_S)
    (HERE / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (HERE / "REPORT.md").write_text(report(rows), encoding="utf-8")
    print(report(rows))
    return 0


def report(rows: list[dict]) -> str:
    cited = [r for r in rows if r["expect"] == "cited"]
    citations = sum(r["cited"] for r in cited)
    lines = ["# 药学问答：12 段多轮对话走 MedSync 全链路", "",
             "由 `eval/pharmacist_chain/run_chain.py` 生成。同样的 12 段对话、同样的判定规则（见 "
             "`services/rag/eval_agent.py`），区别是每一轮都作为 `ask_pharmacist` 步骤，从设备经网关、agent 到 rag，"
             "多轮之间靠 session_id 接上；需要\"我的用药\"的那段对话，先通过网关记录用药，再由药学 Agent 用网关签发的"
             "临时只读令牌读回。", "",
             "| 指标 | 全链路 | 进程内（同一索引） |", "|---|---:|---:|"]
    inproc = json.loads(IN_PROCESS.read_text()) if IN_PROCESS.exists() else None
    m = (inproc or {}).get("metrics", {})
    pair = lambda a, b: f"| {a} | {b} |"
    lines += [
        f"| 整体通过 | {sum(r['passed'] for r in rows)}/{len(rows)} | {m.get('passed', '—')}/{m.get('turns', '—')} |",
        f"| 工具选择正确 | {sum(r['tool_ok'] for r in rows)}/{len(rows)} | {m.get('tool_selection', '—')}/{m.get('turns', '—')} |",
        f"| 需引用的轮次通过 | {sum(r['passed'] for r in cited)}/{len(cited)} | "
        f"{m.get('cited_turns_passed', '—')}/{m.get('cited_turns', '—')} |",
        f"| 引用精确率 | {100 * sum(r['good_citations'] for r in cited) / citations:.1f}% | "
        f"{100 * m['citation_precision']:.1f}% |" if citations and m.get("citation_precision") is not None else
        "| 引用精确率 | — | — |",
        f"| 每轮耗时 P50 / 最大（含排队和轮询） | {statistics.median(r['seconds'] for r in rows):.1f} s / "
        f"{max(r['seconds'] for r in rows):.1f} s | {m.get('p50_seconds', 0):.1f} s / {m.get('max_seconds', 0):.1f} s |",
    ]
    lines += ["", "每轮只跑一次，模型输出有随机性，两边的差异里有一部分是这次运行的随机差异。设备只保存每条引用的开头"
              f"（摘录），所以关键句是对照摘录所在的说明书原段落检查的（本地快照与 rag 服务用的是同一份）。"]
    lines += ["", "## 逐轮结果", "", "| 轮次 | 期望 | 状态 | 通过 | 调用工具 | 回答 |", "|---|---|---|---|---|---|"]
    for r in rows:
        text = r["text"].replace("|", "/").replace("\n", " ")[:110]
        lines.append(f"| {r['id']} | {r['expect']} | {r['status']} | {'✅' if r['passed'] else '❌'} | "
                     f"{', '.join(r['called'])} | {text} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
