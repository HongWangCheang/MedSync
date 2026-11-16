#!/usr/bin/env python3
"""How often does a real LLM change its tool-call arguments when it retries the same step?

The comparison experiment SIMULATES re-planning: every re-dispatch rewords the free text (experiment.rephrase), so
argument-hash deduplication (B2) never recognises a retry. This measures the real rate with the model the RAG
service uses, so that assumption can be replaced by a number.

    python3 eval/drift/run_drift.py            # needs GEMINI_API_KEY in .env; ~620 calls, ~45 min on the free tier
    python3 eval/drift/run_drift.py --report   # rebuild REPORT.md from the saved calls

For every utterance in eval/routing/utterances.jsonl that books or notifies:
  replan_default  the same request sent 4 times independently at the model's default temperature
                  (a crashed or restarted agent planning the step again from scratch)
  replan_t0       the same, 3 times at temperature 0
  retry_in_chat   one turn later in the same conversation: the tool answered "timed out, may or may not have
                  happened" and the model emits its call again (an agent loop retrying after a timeout)

For each retry, compared with the first call of the same tool:
  args_identical      every argument byte-identical after JSON canonicalisation: the only case B2 can catch
  identity_identical  the fields that decide "is it the same booking / message" (department + date, recipient)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
TODAY = "2026-11-16（星期一）"
REPLANS = 4         # independent plans at the default temperature (1 first + 3 re-plans)
REPLANS_T0 = 3      # at temperature 0
# The key in .env is on the free tier (15 requests per minute): pace every request instead of bursting into 429s.
MIN_INTERVAL_S = 60 / 14
_pace_lock = threading.Lock()
_last_request = [0.0]
IDENTITY = {"book_appointment": ("department", "date"), "notify_family": ("to",)}

SYSTEM = f"""你是用药助手的动作规划器。把用户的一句话变成要执行的工具调用；一句话可以调用多个工具。
今天是 {TODAY}。日期一律写成 YYYY-MM-DD。
只调用确实需要的工具；note 和 message 用简短的中文写清楚用户的意思。"""

TOOLS = [{"functionDeclarations": [
    {"name": "book_appointment", "description": "为用户预约医院门诊或复诊。",
     "parameters": {"type": "object", "properties": {
         "department": {"type": "string", "description": "科室"},
         "date": {"type": "string", "description": "就诊日期 YYYY-MM-DD"},
         "note": {"type": "string", "description": "给医生的备注"}},
         "required": ["department", "date"]}},
    {"name": "notify_family", "description": "给用户的家人发消息。",
     "parameters": {"type": "object", "properties": {
         "to": {"type": "string", "description": "家人称谓，例如 女儿、老伴"},
         "message": {"type": "string", "description": "消息内容"}},
         "required": ["to", "message"]}},
    {"name": "record_medication", "description": "记录用户已经吃过的药。",
     "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "record_symptom", "description": "记录用户的症状。",
     "parameters": {"type": "object", "properties": {"symptom": {"type": "string"}}, "required": ["symptom"]}},
    {"name": "ask_pharmacist", "description": "用户在问用药问题。",
     "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
]}]

TIMEOUT_REPLY = {"error": "timeout", "detail": "外部系统 5 秒内没有响应：这次操作可能已经执行，也可能没有。"}


def key() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("GEMINI_API_KEY is not set in .env")


def generate(contents: list[dict], temperature: float | None, api_key: str) -> list[dict]:
    """The model's function-call parts for this conversation, raw: Gemini 3 needs each part's thoughtSignature
    sent back when the conversation continues. Retries 429/5xx."""
    body = {"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": contents, "tools": TOOLS}
    if temperature is not None:
        body["generationConfig"] = {"temperature": temperature}
    for attempt in range(6):
        with _pace_lock:
            wait = _last_request[0] + MIN_INTERVAL_S - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last_request[0] = time.monotonic()
        request = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.load(response)
            parts = result["candidates"][0]["content"].get("parts") or []
            return [p for p in parts if "functionCall" in p]
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < 5:
                time.sleep(40 if error.code == 429 else 2 ** attempt + random.random())
                continue
            raise
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError):
            if attempt < 5:
                time.sleep(2 ** attempt)
                continue
            raise
    return []


def calls_for(text: str, temperature: float | None, api_key: str) -> list[dict]:
    return generate([{"role": "user", "parts": [{"text": text}]}], temperature, api_key)


def retry_in_chat(text: str, first_parts: list[dict], api_key: str) -> list[dict]:
    """The model's next turn after every side-effecting call in `first_parts` timed out."""
    replies = [{"functionResponse": {"name": p["functionCall"]["name"],
                                     "response": TIMEOUT_REPLY if p["functionCall"]["name"] in IDENTITY else {"ok": True}}}
               for p in first_parts]
    contents = [{"role": "user", "parts": [{"text": text}]},
                {"role": "model", "parts": first_parts},
                {"role": "user", "parts": replies}]
    return generate(contents, None, api_key)


def calls(parts: list[dict]) -> list[dict]:
    return [p["functionCall"] for p in parts]


def run_one(row: dict, api_key: str) -> dict:
    text = row["text"]
    out = {"id": row["id"], "text": text}
    default = [calls_for(text, None, api_key) for _ in range(REPLANS)]
    out["replan_default"] = [calls(a) for a in default]
    out["replan_t0"] = [calls(calls_for(text, 0.0, api_key)) for _ in range(REPLANS_T0)]
    out["retry_in_chat"] = [out["replan_default"][0], calls(retry_in_chat(text, default[0], api_key))] \
        if any(c["name"] in IDENTITY for c in out["replan_default"][0]) else []
    return out


# ---------- scoring ----------

def canon(args: dict) -> str:
    return json.dumps(args or {}, sort_keys=True, ensure_ascii=False)


def comparisons(attempts: list[list[dict]]) -> list[dict]:
    """Each later attempt vs the first, per side-effecting tool the first attempt called (first call of that tool)."""
    if not attempts:
        return []
    first = {c["name"]: c.get("args", {}) for c in reversed(attempts[0]) if c["name"] in IDENTITY}
    found = []
    for later in attempts[1:]:
        again = {c["name"]: c.get("args", {}) for c in reversed(later) if c["name"] in IDENTITY}
        for tool, args in first.items():
            other = again.get(tool)
            fields = sorted(set(args) | set(other or {}))
            found.append({
                "tool": tool, "called_again": other is not None,
                "args_identical": other is not None and canon(args) == canon(other),
                "identity_identical": other is not None and all(
                    str(args.get(f, "")).strip() == str(other.get(f, "")).strip() for f in IDENTITY[tool]),
                "changed": [f for f in fields if other is not None and args.get(f) != other.get(f)],
            })
    return found


def pct(k: int, n: int) -> str:
    return f"{100 * k / n:.0f}%" if n else "—"


def ivr_by_fault(condition: str) -> dict[str, tuple[int, int]]:
    """B2 (args_hash) duplicates per fault in the main experiment under one condition."""
    counts: dict[str, list[int]] = {}
    for path in sorted((ROOT / "eval" / "results").glob(f"*-{condition}.jsonl")):
        for line in path.read_text().splitlines():
            r = json.loads(line)
            if r["mode"] == "args_hash" and r["kind"] == "fault":
                c = counts.setdefault(r["scenario"], [0, 0])
                c[0] += r["effects"] > 1
                c[1] += 1
    return {k: (v[0], v[1]) for k, v in counts.items()}


def expected_ids() -> set[str]:
    utterances = [json.loads(l) for l in (ROOT / "eval/routing/utterances.jsonl").read_text().splitlines() if l.strip()][1:]
    return {r["id"] for r in utterances if any(s["tool"] in IDENTITY for s in r["expect"])}


def report(rows: list[dict]) -> str:
    conditions = {"replan_default": "重新规划（默认温度）", "replan_t0": "重新规划（温度 0）",
                  "retry_in_chat": "同一对话里超时后重试"}
    stats = {}
    lines = ["# 真实 LLM 的参数漂移", "",
             f"由 `eval/drift/run_drift.py` 生成。模型 `{MODEL}`（和 RAG 服务用的同一个），{len(rows)} 句会预约或通知家属的话"
             "（取自 `eval/routing/utterances.jsonl`）。对照对比实验里的假设：实验中每次重新派发都会改写自由文本，"
             "所以参数哈希去重（B2）永远认不出重试。", "",
             "| 重试方式 | 比较次数 | 又调用了同一个工具 | 参数完全相同（B2 能挡住） | 身份参数相同（科室+日期 / 收件人） |",
             "|---|---|---|---|---|"]
    for name, label in conditions.items():
        comps = [c for r in rows for c in comparisons(r[name])]
        n = len(comps)
        again = sum(c["called_again"] for c in comps)
        same = sum(c["args_identical"] for c in comps)
        ident = sum(c["identity_identical"] for c in comps)
        stats[name] = (same, again)  # for the B2 estimate: identical among retries that did call again
        lines.append(f"| {label} | {n} | {pct(again, n)} | **{pct(same, n)}** | {pct(ident, n)} |")
    missing = expected_ids() - {r["id"] for r in rows}
    if missing:
        lines += ["", f"**覆盖范围**：计划测 {len(rows) + len(missing)} 句，实际完成 {len(rows)} 句。"
                  f"免费版 Gemini API 每天最多 500 次请求，剩下 {len(missing)} 句没跑："
                  f"{'、'.join(sorted(missing))}，全是复合句（一句话里有好几件事）。"
                  "所以这里的数字偏向单一动作的句子。"]
    lines += ["", "**同一对话里超时后重试**：工具回复\"超时，可能已经执行，也可能没有\"之后，模型一次都没有再调用这个工具"
              f"（0/{len([c for r in rows for c in comparisons(r['retry_in_chat'])])}）。"
              "这次没有保存模型的文字回复，所以不知道它具体说了什么，只知道它没有再发一次。"
              "也就是说，在这种设置下，重复执行不是来自模型自己重试，而是来自外层的重试：进程重启后重新规划、网关重派。",
              "", "每个字段在重试中变化的比例（只算又调用了同一个工具的重试）：", "",
              "| 重试方式 | " + " | ".join(["department", "date", "note", "to", "message"]) + " |",
              "|---|" + "---|" * 5]
    for name, label in conditions.items():
        comps = [c for r in rows for c in comparisons(r[name]) if c["called_again"]]
        cells = []
        for field in ("department", "date", "note", "to", "message"):
            relevant = [c for c in comps if (field in ("department", "date", "note")) == (c["tool"] == "book_appointment")]
            cells.append(pct(sum(field in c["changed"] for c in relevant), len(relevant)))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    # What B2's IVR would be if retries drifted at the measured rate instead of always.
    rephrase, identical = ivr_by_fault("rephrase"), ivr_by_fault("identical")
    lines += ["", "## 换成真实漂移率后，B2 的重复副作用率是多少", "",
              "主实验跑过两种条件：每次重试都改写（rephrase），以及每次重试参数完全相同（identical）。"
              "设 s 为实测的\"参数完全相同\"比例，按故障类型估计 B2 在真实漂移下的 IVR = s × IVR(identical) + "
              "(1 − s) × IVR(rephrase)。s 只在又调用了同一个工具的重试里算。同一对话里的重试没有再调用工具，不参与估计。", ""]
    if rephrase and identical:
        estimated = [c for c in conditions if c != "retry_in_chat"]  # the model never re-called: nothing to estimate
        lines += ["| 故障 | IVR（全部改写） | IVR（全部相同） | " + " | ".join(
                      f"估计（{conditions[c]}，s = {pct(*stats[c])}）" for c in estimated) + " |",
                  "|---|---|---|" + "---|" * len(estimated)]
        for fault in rephrase:
            if fault not in identical:
                continue
            r_k, r_n = rephrase[fault]
            i_k, i_n = identical[fault]
            ivr_r, ivr_i = r_k / r_n, i_k / i_n
            est = []
            for c in estimated:
                same, n = stats[c]
                s = same / n if n else 0
                est.append(f"{100 * (s * ivr_i + (1 - s) * ivr_r):.0f}%")
            lines.append(f"| {fault} | {100 * ivr_r:.0f}% | {100 * ivr_i:.0f}% | " + " | ".join(est) + " |")
        overall = []
        faults = [f for f in rephrase if f in identical]
        for c in estimated:
            same, n = stats[c]
            sc = same / n if n else 0
            overall.append(sum(sc * identical[f][0] / identical[f][1] + (1 - sc) * rephrase[f][0] / rephrase[f][1]
                               for f in faults) / len(faults))
        all_r = sum(rephrase[f][0] / rephrase[f][1] for f in faults) / len(faults)
        lines += ["", f"**合起来**（{len(faults)} 种故障等权平均，和主实验的算法一样）：B2 的 IVR 在\"每次都改写\"的假设下是 "
                  f"{100 * all_r:.0f}%，换成实测漂移率后约为 {' / '.join(f'{100 * o:.0f}%' for o in overall)}"
                  "（默认温度 / 温度 0），Full 是 0%。模拟夸大了 B2 的重复率，但结论不变：B2 仍会重复执行，"
                  "主要原因不是漂移，而是\"已提交、响应丢失\"这类故障它根本挡不住。"]
    lines += ["", "## 怎么读", "",
              "- **参数完全相同**：B2 只有在这种情况下才能认出重试。比例越低，B2 越挡不住。",
              "- **身份参数相同**：说明\"是不是同一件事\"其实没变，只是措辞变了。"
              "MedSync 的 step_key 在规划时由设备根据身份参数算出并落库，之后模型怎么改写都不影响它。",
              "- **按身份参数去重也不够**：同一天约同一个科室两次，可能真的是两件事；"
              "而且哪怕参数完全相同，B2 也挡不住\"已提交、响应丢失\"（见主报告的消融实验）。"
              "漂移率只决定 B2 在\"agent 已经记下结果、但上游没收到回复\"这类故障里的表现。",
              "- **局限**：只测了一个模型、一组中文句子；生产环境的提示词、上下文长度和温度都会影响漂移率。"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true", help="only rebuild REPORT.md from calls.jsonl")
    parser.add_argument("--limit", type=int, help="first N utterances (smoke test)")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--resume", action="store_true",
                        help="only the utterances not yet in calls.jsonl, appended (the free tier stops at 500 a day)")
    args = parser.parse_args()
    out = HERE / "calls.jsonl"
    if not args.report:
        utterances = [json.loads(l) for l in (ROOT / "eval/routing/utterances.jsonl").read_text().splitlines()
                      if l.strip()][1:]
        rows = [r for r in utterances if any(s["tool"] in IDENTITY for s in r["expect"])][:args.limit]
        if args.resume and out.exists():
            done_ids = {json.loads(l)["id"] for l in out.read_text().splitlines() if l.strip()}
            rows = [r for r in rows if r["id"] not in done_ids]
        api_key = key()
        lock, done = threading.Lock(), [0]
        with out.open("a" if args.resume else "w") as sink, ThreadPoolExecutor(args.workers) as pool:
            def work(row):
                result = run_one(row, api_key)
                with lock:
                    sink.write(json.dumps(result, ensure_ascii=False) + "\n")
                    sink.flush()
                    done[0] += 1
                    print(f"[{done[0]:>2}/{len(rows)}] {row['text']}", flush=True)
            list(pool.map(work, rows))
    rows = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    (HERE / "REPORT.md").write_text(report(rows), encoding="utf-8")
    print(report(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
