"""Compare both modes on the same fixed questions through the FastAPI routes."""

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import time
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

from app import app
from label_corpus import DEFAULT_CORPUS
from label_retrieval import MODEL_NAME, RERANK_MIN_SCORE, RERANK_MODEL, source_url

QUESTIONS = Path(__file__).with_name("eval") / "questions.json"
MODES = ("keyword", "hybrid", "rerank")
NAMES = {"keyword": "关键词", "hybrid": "混合", "rerank": "混合+重排"}


def percentile95(samples):
    return sorted(samples)[math.ceil(len(samples) * .95) - 1]


def measure(client, cases, repeats):
    outcomes = {case["id"]: {} for case in cases}
    for mode in MODES:
        client.post("/v1/answer", json={**cases[0]["request"], "mode": mode}).raise_for_status()
    for case in cases:
        for mode in MODES:
            samples = []
            result = None
            for _ in range(repeats):
                start = time.perf_counter_ns()
                response = client.post("/v1/answer", json={**case["request"], "mode": mode})
                samples.append((time.perf_counter_ns() - start) / 1e6)
                response.raise_for_status()
                data = response.json()
                if result is not None and result != data:
                    raise ValueError(f"Non-repeatable response for {case['id']} ({mode})")
                result = data
            relevant = set(case.get("relevant_passages", []))
            retrieved = [p["id"] for p in result["retrieved"]]
            cited = [p["id"] for p in result["sources"]]
            candidate_keys = sorted(f"{row['id']}/{row['version']}" for row in result["candidates"])
            exact_version = ("label_id" in case["request"] and result["source_url"] ==
                             source_url(case["request"]["label_id"], case["request"]["version"]))
            citation_hits = sum(exact_version and item["id"] in relevant and
                                case["gold_excerpt"].casefold() in item["text"].casefold()
                                for item in result["sources"])
            passed = result["status"] == case["expected"]
            if case["expected"] == "answered":
                passed = passed and bool(cited) and citation_hits == len(cited)
            else:
                passed = passed and not cited and candidate_keys == case.get("candidate_keys", [])
            outcomes[case["id"]][mode] = {
                "status": result["status"], "retrieved": retrieved, "citations": cited,
                "candidate_keys": candidate_keys,
                "citation_hits": citation_hits,
                "recall": len(relevant.intersection(retrieved)) / len(relevant) if relevant else None,
                "passed": passed, "latency_ms": samples,
            }
    return outcomes


def totals(cases, outcomes):
    result = {}
    for mode in MODES:
        rows = [outcomes[case["id"]][mode] for case in cases]
        recalls = [r["recall"] for r in rows if r["recall"] is not None]
        cited = sum(len(r["citations"]) for r in rows)
        citation_hits = sum(r["citation_hits"] for r in rows)
        latencies = [value for row in rows for value in row["latency_ms"]]
        label_latencies = [value for row, case in zip(rows, cases) if "label_id" in case["request"]
                           for value in row["latency_ms"]]
        result[mode] = {
            "recall_at_5": statistics.mean(recalls),
            "citation_accuracy": citation_hits / cited if cited else None,
            "correct_citations": citation_hits, "total_citations": cited,
            "p95_ms": percentile95(latencies),
            "selected_label_p95_ms": percentile95(label_latencies),
            "passed": sum(row["passed"] for row in rows),
            "by_category": dict(Counter(case["category"] for case, row in zip(cases, rows) if row["passed"])),
        }
    return result


def report(cases, outcomes, summary, metadata):
    text = [
        "# MedTrack 固定题评测", "",
        f"openFDA 快照含 {metadata['labels']} 条版本记录，索引 {metadata['passages']} 个段落。",
        f"共 {len(cases)} 题，每题每种模式运行 {metadata['repeats']} 次。运行环境为 {metadata['platform']}。",
        "", "| 检索方式 | Recall@5 | 引用正确率 | P95 | 已选标签 P95 | 通过题数 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for mode, row in summary.items():
        accuracy = f"{row['citation_accuracy']:.1%}" if row["citation_accuracy"] is not None else "N/A"
        text.append(f"| {mode} | {row['recall_at_5']:.1%} | {accuracy} ({row['correct_citations']}/{row['total_citations']}) | "
                    f"{row['p95_ms']:.2f} ms | {row['selected_label_p95_ms']:.2f} ms | {row['passed']}/{len(cases)} |")
    text += ["", "| 题型 | 总题数 | " + " | ".join(NAMES[m] + "通过" for m in MODES) + " |",
             "|---|---:|" + "---:|" * len(MODES)]
    for category, count in Counter(c["category"] for c in cases).items():
        text.append(f"| {category} | {count} | " + " | ".join(str(summary[m]["by_category"].get(category, 0)) for m in MODES) + " |")
    text += [
        "", "Recall@5 为可回答题的相关段落召回率宏平均。引用正确率按实际返回的引用计，引用须命中预先标注的段落且包含标注原文。"
        "可回答题漏答由通过题数体现，单独报告以免高拒答率抬高引用正确率。",
        "P95 用预热后的进程内 FastAPI 请求计时，包含检索、引用选择和序列化。已选标签 P95 只统计进入段落检索路径的题。",
        "同名题要求返回候选，未命中题和证据不足题要求返回对应状态。评测衡量当前快照中的证据覆盖，不衡量医学结论。",
        f"重排模式在混合检索前 30 个候选上用交叉编码器 `{RERANK_MODEL}` 重新打分，分数低于 {RERANK_MIN_SCORE} 时拒答。"
        "阈值只在 `eval/validation.json`（30 题，说明书与本题集不重叠）上选定，没有用本题集调参。",
    ]
    for title, predicate in (
        ("重排答对、混合检索未答对", lambda k, h, r: not h["passed"] and r["passed"]),
        ("混合检索答对、重排未答对", lambda k, h, r: h["passed"] and not r["passed"]),
        ("混合检索答对、关键词未答对", lambda k, h, r: not k["passed"] and h["passed"]),
        ("关键词答对、混合检索未答对", lambda k, h, r: k["passed"] and not h["passed"]),
        ("三种方式都未通过", lambda k, h, r: not (k["passed"] or h["passed"] or r["passed"])),
    ):
        text += ["", f"## {title}", ""]
        found = False
        for case in cases:
            rows = [outcomes[case["id"]][mode] for mode in MODES]
            if predicate(*rows):
                found = True
                gold = ", ".join(case.get("relevant_passages", [])) or case["expected"]
                got = " · ".join(f"{NAMES[m]} `{', '.join(r['citations']) or r['status']}`" for m, r in zip(MODES, rows))
                text.append(f"- **{case['id']}** {case['request']['question']} · 标注 `{gold}` · {got}")
        if not found:
            text.append("这组题中没有此类变化。")
    text += ["", f"向量模型 `{MODEL_NAME}`。语料 SHA-256 `{metadata['corpus_sha256']}`。"
             f"题集 SHA-256 `{metadata['questions_sha256']}`。", ""]
    return "\n".join(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=QUESTIONS.parent)
    parser.add_argument("--questions", type=Path, default=QUESTIONS,
                        help="question set; default is the fixed 50 (eval/questions.json)")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if os.getenv("MEDTRACK_CORPUS") or os.getenv("MEDTRACK_SYNTHETIC_LABELS") == "1":
        parser.error("Unset MEDTRACK_CORPUS and MEDTRACK_SYNTHETIC_LABELS to evaluate the bundled corpus")
    raw = args.questions.read_bytes()
    cases = json.loads(raw)
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Question IDs must be unique.")
    if args.questions.resolve() == QUESTIONS.resolve() and len(cases) != 50:
        raise ValueError("The fixed benchmark requires exactly 50 unique questions.")
    with TestClient(app) as client:
        health = client.get("/health").json()
        if health["corpus"] != "openFDA snapshot":
            raise ValueError("The benchmark requires the bundled openFDA snapshot.")
        outcomes = measure(client, cases, args.repeats)
    summary = totals(cases, outcomes)
    metadata = {
        "labels": health["labels"], "passages": health["passages"], "repeats": args.repeats,
        "platform": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "corpus_sha256": hashlib.sha256(DEFAULT_CORPUS.read_bytes()).hexdigest(),
        "questions_sha256": hashlib.sha256(raw).hexdigest(),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(dict(metadata=metadata, metrics=summary, questions=outcomes),
                                                            ensure_ascii=False, indent=2) + "\n")
    (args.output_dir / "REPORT.md").write_text(report(cases, outcomes, summary, metadata))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
