#!/usr/bin/env python3
"""Builds eval/extra/REPORT.md from eval/extra/*.jsonl (the supplementary scenarios of run_experiment.py --extra).

    python3 eval/report_extra.py

Same definitions as the main report (eval/report.py): IVR = share of episodes with more than one side effect,
counted by the mocks, never by the system under test.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from report import LABEL, MODES, ci, pct  # noqa: E402

HERE = Path(__file__).parent / "extra"
SCENARIOS = ["agent_crash", "tools_crash", "hop2_hop3_lost", "hop1_offline_hop3_down", "concurrent_5"]
SCENARIO_LABEL = {
    "agent_crash": "Agent 进程在外部调用途中被杀（SIGKILL）",
    "tools_crash": "MCP 工具服务在外部调用途中被杀",
    "hop2_hop3_lost": "②③ 同时丢响应",
    "hop1_offline_hop3_down": "① 离线 2 s + ③ 不可达 5 s",
    "concurrent_5": "同一步骤被 5 个 worker 同时提交",
}


NOTES = [
    "- **进程被杀**：外部调用已经提交，结果还没记下来，进程就没了。",
    "  - B0–B2 重启后都会再调用一次。B2 的参数哈希缓存在内存里，重启就丢了；放到 Redis 也没用，因为它只在调用成功之后才记录，挡不住\"已提交、未记录\"这个窗口。",
    "  - Full 不一样：调用之前就写了 INTENT，重启后按 step_key 去外部系统查到了这次调用，就不再调用。",
    "- **工具服务被杀**：只有 Full 经过 MCP 工具服务。对 B0–B2 来说，这个场景等同于\"③ 提交后响应丢失\"。",
    "  - 工具服务被杀时，账本里留下一条 INTENT。实验里租约设为 3 秒（`MEDSYNC_TOOL_LEASE_S`），过期后下一次尝试先查再决定；用默认的 30 秒，Full 要多等半分钟才能完成。",
    "- **同一步骤被并发提交**：",
    "  - B1 挡得住串行重试，挡不住并发：网关看到同一个 key 还在处理中，每次提交或轮询都会再派发一次，这是为了让卡住的步骤能被捞起来。B0–B2 每次派发都调用外部系统，所以 5 个 worker 就是 5 次。",
    "  - Full 在 agent 里对同一步骤互斥，另外一个 worker 拿到 PENDING；就算有多个 agent 副本，工具账本的租约也会让后来的尝试拿到 BUSY。",
    "- **① 离线 + ③ 不可达**：所有模式都没有重复，这是对照组。故障发生在提交之前，重试是安全的；危险的永远是\"已经执行、但调用方不知道\"。",
]


def main() -> None:
    rows = []
    for path in sorted(HERE.glob("*.jsonl")):
        rows += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    cells = defaultdict(list)
    for r in rows:
        cells[(r["scenario"], r["mode"])].append(r)
    reps = max(r["rep"] for r in rows) + 1
    lines = ["# 补充场景", "",
             f"由 `eval/report_extra.py` 根据 `eval/extra/*.jsonl` 生成。{len(rows)} 个回合：{len(SCENARIOS)} 个场景 × "
             f"2 种工具（预约、通知）× 4 种模式，每个组合重复 {reps} 次。和主实验（[../report.md](../report.md)）"
             "用同一套定义：IVR 是出现重复副作用的回合占比，副作用次数以模拟外部系统的计数为准。", "",
             "## IVR（出现重复副作用的回合，95% CI）", "",
             "| 场景 | " + " | ".join(LABEL[m] for m in MODES) + " |", "|---|" + "---|" * len(MODES)]
    for s in SCENARIOS:
        lines.append(f"| {SCENARIO_LABEL[s]} | " + " | ".join(
            ci(sum(r["effects"] > 1 for r in cells[(s, m)]), len(cells[(s, m)])) for m in MODES) + " |")
    lines += ["", "## 正确完成（DONE 且恰好 1 次副作用）/ 平均多出来的副作用次数", "",
              "| 场景 | " + " | ".join(LABEL[m] for m in MODES) + " |", "|---|" + "---|" * len(MODES)]
    for s in SCENARIOS:
        out = []
        for m in MODES:
            rs = cells[(s, m)]
            done = sum(r["status"] == "DONE" and r["effects"] == 1 for r in rs)
            extra = statistics.mean(max(0, r["effects"] - 1) for r in rs) if rs else 0
            out.append(f"{pct(done, len(rs))} / {extra:.1f}")
        lines.append(f"| {SCENARIO_LABEL[s]} | " + " | ".join(out) + " |")
    lines += ["", "## Full 模式的耗时（含重启被杀的进程）", "",
              "| 场景 | p50 | 最大 |", "|---|---|---|"]
    for s in SCENARIOS:
        d = sorted(r["duration_s"] for r in cells[(s, "full")])
        if d:
            lines.append(f"| {SCENARIO_LABEL[s]} | {statistics.median(d):.1f} s | {d[-1]:.1f} s |")
    lost = [r for r in rows if r["effects"] == 0]
    lines += ["", f"没有执行（0 次副作用）的回合：{len(lost)} 个。" +
              ("".join(f"\n- {r['mode']} × {r['scenario']} × {r['tool']}：{r['status']}" for r in lost) if lost else "")]
    lines += ["", "## 怎么读", "", *NOTES]
    (HERE / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
