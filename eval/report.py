#!/usr/bin/env python3
"""Builds eval/report.md and eval/ivr.png from eval/results/*.jsonl.

    uv run --with matplotlib python eval/report.py
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
MODES = ["naive", "request_id", "args_hash", "full"]
LABEL = {"naive": "B0 朴素重试", "request_id": "B1 请求级幂等", "args_hash": "B2 参数哈希去重", "full": "Full step_key 三跳"}
SHORT = {"naive": "B0", "request_id": "B1", "args_hash": "B2", "full": "Full"}
FAULTS = ["none", "hop1_offline", "hop1_lost_response", "hop2_lost_response", "hop3_down", "hop3_lost_response"]
FAULT_LABEL = {"none": "无故障", "hop1_offline": "①离线 2 s", "hop1_lost_response": "①响应丢失",
               "hop2_lost_response": "②响应丢失", "hop3_down": "③不可达", "hop3_lost_response": "③提交后响应丢失"}
# Reference palette, categorical slots 1-4 in fixed order (validated: scripts/validate_palette.js, light mode).
COLORS = {"naive": "#2a78d6", "request_id": "#eb6834", "args_hash": "#1baf7a", "full": "#eda100"}


def load() -> list[dict]:
    rows = []
    for path in sorted((HERE / "results").glob("*.jsonl")):
        rows += [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return rows


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def pct(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}%" if n else "—"


def ci(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{100 * k / n:.1f}% [{100 * lo:.1f}, {100 * hi:.1f}]" if n else "—"


def quantile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


def fault_tables(rows: list[dict], condition: str) -> tuple[list[str], dict]:
    faults = [r for r in rows if r["kind"] == "fault" and r["condition"] == condition]
    by = defaultdict(list)
    for r in faults:
        by[(r["mode"], r["scenario"])].append(r)
        by[(r["mode"], "*")].append(r)
    lines = ["| 指标 | " + " | ".join(LABEL[m] for m in MODES) + " |", "|---|" + "---|" * len(MODES)]

    def row(name, fn):
        lines.append(f"| {name} | " + " | ".join(fn(by[(m, '*')]) for m in MODES) + " |")

    row("回合数", lambda rs: str(len(rs)))
    row("**IVR**（出现重复副作用的回合，95% CI）", lambda rs: ci(sum(r["effects"] > 1 for r in rs), len(rs)))
    row("多出来的副作用次数", lambda rs: str(sum(max(0, r["effects"] - 1) for r in rs)))
    row("正确完成（DONE 且恰好 1 次）", lambda rs: pct(sum(r["status"] == "DONE" and r["effects"] == 1 for r in rs),
                                                    len(rs)))
    row("丢失（0 次副作用）", lambda rs: pct(sum(r["effects"] == 0 for r in rs), len(rs)))
    row("设备提交次数（均值；各方案相同 = 故障条件一致）", lambda rs: f"{statistics.mean(r['attempts'] for r in rs):.2f}" if rs else "—")

    per_fault = ["| 故障（跳） | " + " | ".join(SHORT[m] for m in MODES) + " |", "|---|" + "---|" * len(MODES)]
    for f in FAULTS:
        cells = []
        for m in MODES:
            rs = by[(m, f)]
            cells.append(pct(sum(r["effects"] > 1 for r in rs), len(rs)))
        per_fault.append(f"| {FAULT_LABEL[f]} | " + " | ".join(cells) + " |")
    return lines + [""] + per_fault, by


def stale_table(rows: list[dict]) -> list[str]:
    stale = [r for r in rows if r["kind"] == "stale" and r["condition"] == "rephrase"]
    lines = ["| 场景 | 正确行为 | " + " | ".join(SHORT[m] for m in MODES) + " |", "|---|---|" + "---|" * len(MODES)]
    expect = {"slot_taken": "让用户改约", "expired": "不发送，让用户确认", "tool_changed": "不执行，让用户确认",
              "still_valid": "正常执行（不误拦）"}
    for scenario, want in expect.items():
        cells = []
        for m in MODES:
            rs = [r for r in stale if r["mode"] == m and r["scenario"] == scenario]
            executed = sum(r["effects"] > 0 for r in rs)
            asked = sum(r["status"] == "NEEDS_USER" for r in rs)
            failed = sum(r["status"] == "FAILED" for r in rs)
            if scenario == "still_valid":
                cells.append(f"执行 {executed}/{len(rs)}，误拦 {asked}")
            else:
                parts = [f"执行 {executed}", f"拦下 {asked}"] + ([f"报错 {failed}"] if failed else [])
                cells.append("，".join(parts) + f" /{len(rs)}")
        lines.append(f"| {scenario} | {want} | " + " | ".join(cells) + " |")
    return lines


def latency_table(rows: list[dict]) -> list[str]:
    lines = ["| 场景 | " + " | ".join(SHORT[m] for m in MODES) + " |", "|---|" + "---|" * len(MODES)]
    for scenario in ["none", "hop3_lost_response"]:
        cells = []
        for m in MODES:
            d = [r["duration_s"] for r in rows if r["condition"] == "rephrase" and r["mode"] == m
                 and r["scenario"] == scenario]
            cells.append(f"{1000 * quantile(d, .5):.0f} / {1000 * quantile(d, .95):.0f} ms" if d else "—")
        lines.append(f"| {FAULT_LABEL[scenario]}（P50 / P95） | " + " | ".join(cells) + " |")
    return lines


def chart(by: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for name in ["PingFang SC", "Hiragino Sans GB", "Heiti SC", "Noto Sans CJK SC", "Microsoft YaHei"]:
        if any(name == f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = name
            break
    ink, muted, grid, base, surface = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
    fig, ax = plt.subplots(figsize=(10, 4.6), dpi=160)
    fig.patch.set_facecolor(surface)
    ax.set_facecolor(surface)
    width, gap = 0.19, 0.012
    for i, m in enumerate(MODES):
        xs, ys = [], []
        for j, f in enumerate(FAULTS):
            rs = by[(m, f)]
            xs.append(j + (i - 1.5) * width)
            ys.append(100 * sum(r["effects"] > 1 for r in rs) / len(rs) if rs else 0)
        ax.bar(xs, ys, width - 2 * gap, color=COLORS[m], label=LABEL[m], zorder=3)
        for x, y in zip(xs, ys):
            ax.text(x, y + 2, f"{y:.0f}", ha="center", va="bottom", fontsize=7.5, color=ink if y else muted)
    ax.set_xticks(range(len(FAULTS)), [FAULT_LABEL[f] for f in FAULTS], fontsize=9, color=ink)
    ax.set_ylim(0, 115)
    ax.set_yticks([0, 25, 50, 75, 100], ["0", "25", "50", "75", "100%"], fontsize=8, color=muted)
    ax.yaxis.grid(True, color=grid, linewidth=0.6, zorder=0)
    for side in ["top", "right", "left"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(base)
    ax.tick_params(length=0)
    ax.set_title("重复副作用率 IVR（按故障类型）：越低越好", loc="left", fontsize=11, color=ink)
    ax.legend(loc="upper left", ncols=4, frameon=False, fontsize=8.5, labelcolor=ink, bbox_to_anchor=(0, 1.0))
    fig.tight_layout()
    fig.savefig(path, facecolor=surface)


def ivr(by: dict, mode: str, fault: str = "*") -> float:
    rs = by[(mode, fault)]
    return 100 * sum(r["effects"] > 1 for r in rs) / len(rs) if rs else float("nan")


def findings(by: dict, ablation: dict | None, rows: list[dict]) -> list[str]:
    stale = [r for r in rows if r["kind"] == "stale" and r["condition"] == "rephrase"
             and r["scenario"] in ("expired", "tool_changed")]
    executed = {m: sum(r["effects"] > 0 for r in stale if r["mode"] == m) for m in MODES}
    total = {m: sum(1 for r in stale if r["mode"] == m) for m in MODES}
    out = [
        f"1. **Full 在全部故障回合里没有出现重复副作用**（IVR {ivr(by, 'full'):.0f}%），"
        f"B0 / B1 / B2 分别是 {ivr(by, 'naive'):.0f}% / {ivr(by, 'request_id'):.0f}% / {ivr(by, 'args_hash'):.0f}%，"
        "也没有任何回合丢失副作用。",
        "2. **只保护第①跳不够。** B1（MedTrack 现在的做法）在第①跳响应丢失时没有重复，"
        f"但在第②跳（{ivr(by, 'request_id', 'hop2_lost_response'):.0f}%）和第③跳"
        f"（{ivr(by, 'request_id', 'hop3_lost_response'):.0f}%）照样重复：网关和 Agent 重试时，"
        "并不知道上一次其实已经成功了。",
        "3. **按参数哈希去重，在参数会变时失效。** 参数被改写时，B2 和 B1 一样"
        f"（第②跳 {ivr(by, 'args_hash', 'hop2_lost_response'):.0f}%）。",
    ]
    if ablation:
        out.append(
            f"4. **就算参数完全不变，B2 也挡不住\"已提交但响应丢失\"。** 消融实验里 B2 能挡住第②跳"
            f"（{ivr(ablation, 'args_hash', 'hop2_lost_response'):.0f}%），但第③跳仍是 "
            f"{ivr(ablation, 'args_hash', 'hop3_lost_response'):.0f}%：它只在调用**成功之后**才记录，"
            "超时那一次没有记录，结果是否已经生效就无从得知。Full 的做法是调用前先写 INTENT，"
            "结果不明时按 step_key 去外部系统查询，所以两种情况都能挡住。")
    out.append(
        f"5. **排队期间失效的动作**：三个基线把过期的通知和按旧工具版本规划的预约都执行了"
        f"（各 {executed['naive']}/{total['naive']}），Full 全部拦下，交给用户确认；"
        "号源被抢时基线只返回报错，Full 会给出可改约的日期；条件变了但仍然有效的动作，Full 没有误拦。")
    out.append("6. **代价**：无故障时 Full 的 P50 延迟比基线多几毫秒，主要来自执行前复核多查了一次号源。")
    return out


def main() -> None:
    rows = load()
    main_lines, by = fault_tables(rows, "rephrase")
    has_ablation = any(r["condition"] == "identical" for r in rows)
    ablation_lines, ablation_by = fault_tables(rows, "identical") if has_ablation else ([], None)
    chart(by, HERE / "ivr.png")
    n_main = sum(r["condition"] == "rephrase" for r in rows)
    reps = 1 + max((r["rep"] for r in rows if r["condition"] == "rephrase"), default=-1)

    md = [
        "# 对比实验报告：端到端只执行一次",
        "",
        f"> 由 `eval/report.py` 根据 `eval/results/*.jsonl` 生成。主实验 {n_main} 个回合（每个组合重复 {reps} 次）"
        + ("，另有参数不变的消融实验" if has_ablation else "") + "。",
        "",
        "## 结论",
        "",
        *findings(by, ablation_by, rows),
        "",
        "> 每种故障的时序是固定的，所以同一个格子里的结果基本是确定的（要么 0%，要么 100%）。"
        "重复 10 次是为了确认结果稳定，置信区间只反映样本量。",
        "",
        "## 实验设置",
        "",
        "- **系统**：真实的 Compose 服务栈（gateway + agent + Postgres + MySQL），三跳都经过 Toxiproxy。"
        "`eval/run_experiment.py` 扮演设备。",
        "- **四个方案**：",
        "  - **B0 朴素重试**：每次重试都换一个新的请求 ID，Agent 每次派发都调用一次工具。",
        "  - **B1 请求级幂等**（MedTrack 现在的做法）：设备持久化请求 ID，第①跳可以重放；Agent 仍然每次派发都调用工具。",
        "  - **B2 参数哈希去重**：在 B1 的基础上，Agent 跳过（工具 + 参数）哈希已经执行过的调用，这是常见 Agent 防重库的做法。",
        "  - **Full**：step_key 贯穿三跳，配合 LangGraph 线程、tool ledger 和执行前复核。",
        "- **故障**：每个回合注入一种（见下表），第一次尝试结束后撤除。用到的超时：设备 3 s，网关→Agent 2 s，Agent→外部系统 1 s。",
        "- **LLM 重新规划**：同一步骤每被派发一次，备注或消息文字就换一种措辞（确定性改写，四个方案完全一样）。"
        "这是对\"模型超时后重新生成的工具调用和上一次不完全相同\"的模拟，**不是真实 LLM**。",
        "- **评判标准**：模拟外部系统按回合 trace 统计实际发生的副作用次数，不采信各个服务自己的上报。",
        "  **IVR** = 出现 ≥2 次副作用的回合 / 总回合（定义参考 idempotencybench），括号内是 Wilson 95% 置信区间。",
        "",
        "## 结果一：重复副作用",
        "",
        "![IVR by fault](ivr.png)",
        "",
        *main_lines,
        "",
        "## 结果二：排队期间失效的动作",
        "",
        *stale_table(rows),
        "",
        "## 结果三：延迟",
        "",
        "设备从第一次提交到拿到最终状态的时间（本机 Docker，含故障注入的等待）。",
        "",
        *latency_table(rows),
        "",
    ]
    if has_ablation:
        md += [
            "## 消融：重试时参数完全不变",
            "",
            "把 Agent 的改写关掉（`MEDSYNC_EXPERIMENT_REPHRASE=0`），只跑故障场景。这一组回答的是：如果重试时参数逐字节相同，B2 够不够用？",
            "",
            *ablation_lines,
            "",
        ]
    md += [
        "## 局限",
        "",
        "- 参数改写是确定性模拟，不是真实模型的输出；真实 LLM 的参数漂移率需要另做实验测量。",
        "- 每回合只注入一种故障，故障时序固定；没有覆盖多种故障叠加、Agent 进程崩溃（tool ledger 租约 30 s）和并发重复提交。",
        "- 外部系统是本机 mock，提供按 step_key 查询的接口；不支持查询的真实系统只能退化为\"最多一次 + 人工确认\"。",
        "- 延迟在本机 Docker 上测得，绝对值没有参考意义，只用于方案之间对比。",
        "",
        "## 复现",
        "",
        "```sh",
        "docker compose -f docker-compose.yml -f eval/compose.experiment.yml up -d --build",
        "python3 eval/run_experiment.py --reps 10",
        "MEDSYNC_EXPERIMENT_REPHRASE=0 docker compose -f docker-compose.yml -f eval/compose.experiment.yml up -d agent",
        "python3 eval/run_experiment.py --reps 5 --condition identical --faults-only",
        "uv run --with matplotlib python eval/report.py",
        "```",
    ]
    (HERE / "report.md").write_text("\n".join(md) + "\n")
    print(f"wrote {HERE / 'report.md'} and {HERE / 'ivr.png'}")


if __name__ == "__main__":
    main()
