#!/usr/bin/env python3
"""Multi-agent scenarios × fault types: does the agents' COLLABORATION still come out right under each fault?

The comparison experiment (run_experiment.py) asks "did a side effect happen twice?". This asks more: under a fault,
does the safety review still raise its alert, does the conflict check still pause the queued message, does the
user's decision still send exactly one message with the warning attached, and does nothing slip out in between.

    docker compose -f docker-compose.yml -f eval/compose.experiment.yml up -d --build
    python3 eval/run_matrix.py --reps 3           # → eval/matrix/<timestamp>.jsonl + eval/matrix/REPORT.md

Scenarios (the real system, no experiment mode):
  safety_alert    warfarin recorded earlier; ibuprofen recorded now → moderate alert citing warfarin, one finding
  conflict_pause  paracetamol (泰诺) recorded earlier; plan "吃了对乙酰氨基酚，告诉女儿我没事":
                  record → high duplicate-ingredient alert; message → paused, nothing sent;
                  user picks "附上提醒再发" → exactly one message, warning attached

Faults are injected on every device action of the episode (record, message, decision) and lifted after its first
attempt, except where noted:
  hop1_lost       device → gateway: the gateway finishes, the device times out and retries
  hop2_lost       gateway → agent: the agent finishes, the gateway (2 s) times out
  hop2_down       gateway → agent unreachable for 2 s
  rag_down        the RAG service (safety review) stopped during the record, restarted afterwards
  mcp_lost        agent → MCP tool server: the server sends, the agent (3 s) times out (message and decision only)
  agent_crash     agent SIGKILLed mid-step: during the review (RAG held) and during the send (call in flight)
  tools_crash     MCP tool server SIGKILLed while the message is being sent (decision only)
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_experiment as rx  # noqa: E402  (same HTTP, fault and device helpers as the comparison experiment)

SCENARIOS = ["safety_alert", "conflict_pause"]
FAULTS = ["none", "hop1_lost", "hop2_lost", "hop2_down", "rag_down", "mcp_lost", "agent_crash", "tools_crash"]
# Faults that cannot touch a scenario: the safety alert makes no MCP call.
NOT_APPLICABLE = {("safety_alert", "mcp_lost"), ("safety_alert", "tools_crash")}
OUT = Path(__file__).parent / "matrix"
NOTE = "MedSync 用药提醒"


def psql(sql: str) -> str:
    return rx.compose("exec", "-T", "postgres", "psql", "-U", "medsync", "-d", "medsync", "-tAc", sql).strip()


def step(tool: str, payload: dict, plan: str, index: int, **extra) -> dict:
    return {"stepKey": rx.fresh_key(), "planId": plan, "stepIndex": index, "tool": tool,
            "toolClass": extra.pop("toolClass", "IRREVERSIBLE"), "identityArgs": {}, "payload": payload,
            "preconditions": {"toolVersion": "v1"}, "createdAtMs": int(time.time() * 1000), **extra}


def record(name: str, minutes_ago: int, plan: str | None = None) -> dict:
    taken = int(time.time() * 1000) - minutes_ago * 60_000
    return step("record_medication", {"name": name, "takenAt": taken, "note": ""}, plan or uuid.uuid4().hex, 0,
                toolClass="WRITE_IDEMPOTENT")


# ---------- faults ----------

def arm(fault: str, phase: str, scenario: str) -> tuple[callable, list[threading.Thread]]:
    """Injects `fault` for one device action; returns (lift after the first attempt, background threads to join)."""
    background: list[threading.Thread] = []

    def later(delay: float, fn, *args) -> None:
        t = threading.Timer(delay, fn, args)
        t.start()
        background.append(t)

    if fault == "hop1_lost":
        rx.latency("device_gateway", int((rx.CLIENT_TIMEOUT_S + 1) * 1000))
    elif fault == "hop2_lost":
        rx.latency("gateway_agent", 3000)
    elif fault == "hop2_down":
        rx.toxi("POST", "/proxies/gateway_agent", {"enabled": False})
        later(2.0, rx.toxi, "POST", "/proxies/gateway_agent", {"enabled": True})
        return (lambda: None), background
    elif fault == "rag_down" and phase == "record":
        rx.compose("stop", "rag")
        later(3.0, lambda: (rx.compose("start", "rag"), rx.wait_healthy("rag")))
        return (lambda: None), background
    elif fault == "mcp_lost" and phase in ("message", "decision"):
        rx.latency("agent_tools", 5000)
    elif fault == "agent_crash" and phase == "record":
        rx.compose("pause", "rag")                      # hold the safety review in flight…
        later(0.7, rx.crash, "agent")                   # …kill the agent in the middle of it…
        later(1.5, rx.compose, "unpause", "rag")        # …and let the review service answer again
        return (lambda: None), background
    elif fault in ("agent_crash", "tools_crash") and phase == "decision":
        rx.lost_after_commit("notify_family", 3)        # the message is sent at once, answered after 3 s
        later(0.7, rx.crash, "agent" if fault == "agent_crash" else "tools")
        return (lambda: None), background
    return rx.clear_faults, background


def settle(background: list[threading.Thread], fault: str) -> None:
    for t in background:
        t.join()
    if fault in ("agent_crash", "tools_crash", "rag_down"):
        for service in ("agent", "tools", "rag"):
            rx.wait_healthy(service)
    rx.clear_faults()


# ---------- the device ----------

def submit(token: str, s: dict, fault: str, phase: str, scenario: str) -> dict:
    """Submit a step like the device does (retries, polling) under `fault`; returns the gateway's final view."""
    lift, background = arm(fault, phase, scenario)
    try:
        outcome = rx.device_run("full", token, s, lift, rx.CRASH_BUDGET_S)
    finally:
        settle(background, fault)
    _, view = rx.http("GET", f"{rx.GATEWAY}/v1/actions/{s['stepKey']}", None, token)
    return {**(view or {}), "device_status": outcome["status"], "attempts": outcome["attempts"]}


def decide(token: str, key: str, decision: dict, fault: str) -> dict:
    """The user's choice, sent like the app does: retried on network errors; a step that is already moving on
    (409 "not waiting for the user") is polled instead."""
    lift, background = arm(fault, "decision", "conflict_pause")
    started, first, attempts, view = time.monotonic(), True, 0, None
    try:
        while time.monotonic() - started < rx.CRASH_BUDGET_S:
            attempts += 1
            try:
                code, view = rx.http("POST", f"{rx.GATEWAY}/v1/actions/{key}/resume", decision, token,
                                     rx.CLIENT_TIMEOUT_S)
            except rx.NetError:
                code = None
            if first:
                first = False
                lift()
            if code == 409:
                code, view = rx.http("GET", f"{rx.GATEWAY}/v1/actions/{key}", None, token)
            if view and view.get("status") in ("DONE", "FAILED", "CANCELLED"):
                break
            time.sleep(0.5)
    finally:
        settle(background, fault)
    return {**(view or {}), "attempts": attempts}


def sent(key: str) -> list[dict]:
    return rx.http("GET", f"{rx.MOCKS}/notify?ref={key}")[1] or []


def finding(account_key: str) -> str | None:
    return psql(f"SELECT string_agg(severity, ',') FROM agent_finding WHERE step_key = '{account_key}'") or None


# ---------- episodes ----------

def register() -> str:
    code, session = rx.http("POST", f"{rx.GATEWAY}/v1/auth/register",
                            {"username": f"mx_{uuid.uuid4().hex[:10]}", "password": "matrix-pass-1"})
    if code != 201:
        raise SystemExit(f"cannot register through {rx.GATEWAY} (HTTP {code}); is the experiment stack up?")
    return session["token"]


def safety_alert(fault: str) -> dict:
    token = register()  # a fresh medication history per episode
    submit(token, record("华法林", 60), "none", "setup", "safety_alert")
    s = record("布洛芬", 0)
    view = submit(token, s, fault, "record", "safety_alert")
    alerts = ((view.get("result") or {}).get("safety") or {}).get("alerts", [])
    checks = {
        "step_done": view.get("status") == "DONE",
        "alert_raised": view.get("reason") == "safety_alert_moderate" and any(a.get("with") == "华法林" for a in alerts),
        "finding_posted_once": finding(s["stepKey"]) == "moderate",
    }
    return {"checks": checks, "attempts": view.get("attempts"), "reason": view.get("reason")}


def conflict_pause(fault: str) -> dict:
    token = register()
    submit(token, record("泰诺", 30), "none", "setup", "conflict_pause")
    plan = uuid.uuid4().hex
    rec = record("对乙酰氨基酚", 0, plan)
    msg = step("notify_family", {"to": "女儿", "message": "吃了对乙酰氨基酚，告诉女儿我没事"}, plan, 1)
    reviewed = submit(token, rec, fault, "record", "conflict_pause")
    # The app sends the message only after the record is done (the message depends on it).
    paused = submit(token, msg, fault, "message", "conflict_pause")
    before = len(sent(msg["stepKey"]))
    done = decide(token, msg["stepKey"], {"decision": "send_with_note"}, fault) \
        if paused.get("status") == "NEEDS_USER" else paused
    messages = sent(msg["stepKey"])
    checks = {
        "alert_raised": reviewed.get("reason") == "safety_alert_high",
        "finding_posted_once": finding(rec["stepKey"]) == "high",
        "message_paused": paused.get("status") == "NEEDS_USER" and paused.get("reason") == "conflict_with_later_finding",
        "nothing_sent_while_paused": before == 0,
        "decision_done": done.get("status") == "DONE",
        "sent_exactly_once": len(messages) == 1,
        "warning_attached": bool(messages) and NOTE in messages[0].get("message", ""),
    }
    return {"checks": checks, "attempts": done.get("attempts"), "reason": done.get("reason"),
            "messages": len(messages)}


RUN = {"safety_alert": safety_alert, "conflict_pause": conflict_pause}

FOUND = [
    "## 这个矩阵发现并修好的问题", "",
    "第一次跑的时候，conflict_pause × agent_crash 和 conflict_pause × tools_crash 都是 0/3。消息确实只发出了 1 次，"
    "而且附上了提醒，但这一步一直停在\"需要你确认\"。",
    "",
    "**原因**：",
    "1. 用户选了\"附上提醒再发\"，发送途中 agent 或工具服务被杀，网关没拿到结果，就把这一步留在\"需要你确认\"。",
    "2. App 再发一次这个决定。重启后的 agent 发现决定已经用过了（没有待回答的问题，也还没有结果），就返回 409。",
    "3. \"需要你确认\"的步骤不会被重新派发，所以这一步卡住了。App 还会再给用户看一次选项，可是消息其实已经发出去了。",
    "",
    "**修复**（两边都改）：",
    "- 网关收到决定后，立刻把这一步改回\"处理中\"。agent 的结果丢了，下次轮询会重新派发，App 不会再给一个已经做过的决定显示选项（`ActionService.resume`）。",
    "- agent 收到重复的决定时，把第一次的决定执行完，而不是返回 409。第一次的决定可能已经在执行，不能换成另一个（`StepRunner._resume`）。",
    "",
    "两边都加了回归测试。上面的表是修复后重跑的结果。",
    "",
]


# ---------- report ----------

def report(rows: list[dict]) -> str:
    cells: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        cells[(r["scenario"], r["fault"])].append(r)
    reps = max(len(v) for v in cells.values())
    lines = ["# 多 Agent 场景 × 故障矩阵", "",
             f"由 `eval/run_matrix.py` 生成，每格重复 {reps} 次。格子里是“所有检查都通过”的回合数；"
             "没有全部通过的格子，下面列出没过的检查。方法见脚本开头的说明。", "",
             "| 场景 \\ 故障 | " + " | ".join(FAULTS) + " |", "|---|" + "---|" * len(FAULTS)]
    for scenario in SCENARIOS:
        row = []
        for fault in FAULTS:
            rs = cells.get((scenario, fault), [])
            if (scenario, fault) in NOT_APPLICABLE:
                row.append("—")
            elif not rs:
                row.append("")
            else:
                ok = sum(all(r["checks"].values()) for r in rs)
                row.append(f"{'✅' if ok == len(rs) else '❌'} {ok}/{len(rs)}")
        lines.append(f"| {scenario} | " + " | ".join(row) + " |")
    lines += ["", "— 表示这个故障碰不到这个场景（安全提醒不调用 MCP 工具）。", "", "每项检查的通过次数：", ""]
    for scenario in SCENARIOS:
        names = list(next(r for r in rows if r["scenario"] == scenario)["checks"])
        lines += [f"**{scenario}**", "", "| 故障 | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
        for fault in FAULTS:
            rs = cells.get((scenario, fault), [])
            if rs:
                lines.append(f"| {fault} | " + " | ".join(f"{sum(r['checks'][n] for r in rs)}/{len(rs)}"
                                                          for n in names) + " |")
        lines.append("")
    lines += FOUND
    failed = [r for r in rows if not all(r["checks"].values())]
    if failed:
        lines += ["没通过的回合：", ""]
        lines += [f"- {r['scenario']} × {r['fault']}（第 {r['rep'] + 1} 次）："
                  f"{', '.join(k for k, v in r['checks'].items() if not v)}；reason={r.get('reason')}" for r in failed]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--only", help="comma-separated faults (debugging)")
    parser.add_argument("--report", help="only rebuild REPORT.md from this results file")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    if args.report:
        rows = [json.loads(l) for l in Path(args.report).read_text().splitlines() if l.strip()]
        (OUT / "REPORT.md").write_text(report(rows), encoding="utf-8")
        return 0
    faults = args.only.split(",") if args.only else FAULTS
    out = OUT / f"{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    rows = []
    cells = [(s, f) for s in SCENARIOS for f in faults if (s, f) not in NOT_APPLICABLE]
    total, n = len(cells) * args.reps, 0
    with out.open("w") as sink:
        for rep in range(args.reps):
            for scenario, fault in cells:
                rx.clear_faults()
                started = time.monotonic()
                row = {"scenario": scenario, "fault": fault, "rep": rep, **RUN[scenario](fault),
                       "duration_s": round(time.monotonic() - started, 1)}
                rows.append(row)
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                sink.flush()
                n += 1
                bad = [k for k, v in row["checks"].items() if not v]
                print(f"[{n:>2}/{total}] {scenario:15} {fault:12} {'PASS' if not bad else 'FAIL ' + ','.join(bad)} "
                      f"{row['duration_s']}s", flush=True)
    if not args.only:
        (OUT / "REPORT.md").write_text(report(rows), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0 if all(all(r["checks"].values()) for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
