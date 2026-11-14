"""Pick RERANK_MIN_SCORE on the validation set only (eval/validation.json), never on the 50-question test set."""

import json
import sys
from pathlib import Path

from app import build_index

VALIDATION = Path(__file__).with_name("eval") / "validation.json"


def main():
    cases = json.loads(VALIDATION.read_text())
    test_labels = {c["request"].get("label_id") for c in json.loads((VALIDATION.parent / "questions.json").read_text())}
    if test_labels & {c["request"]["label_id"] for c in cases}:
        sys.exit("Validation questions must not use labels from the test set.")
    index = build_index()
    rows = []
    for case in cases:
        req = case["request"]
        top, score = index.retrieve(req["label_id"], req["version"], req["question"], "rerank")[0]
        correct = (case["expected"] == "answered" and top.id in case["relevant_passages"]
                   and case["gold_excerpt"].casefold() in top.text.casefold())
        rows.append((case, score, correct))
        print(f"{case['id']} {case['category'][:12]:12} score={score:7.3f} top={top.id:32} correct={correct}")
    index.db.close()

    def passed(t):
        return sum((s >= t and ok) if c["expected"] == "answered" else s < t for c, s, ok in rows)

    cuts = sorted({s for _, s, _ in rows})
    candidates = [cuts[0] - 1] + [(a + b) / 2 for a, b in zip(cuts, cuts[1:])] + [cuts[-1] + 1]
    best = max(passed(t) for t in candidates)
    plateau = [t for t in candidates if passed(t) == best]
    choice = (min(plateau) + max(plateau)) / 2
    print(f"\nbest passed {best}/{len(rows)} for thresholds {min(plateau):.3f}..{max(plateau):.3f}; choose {choice:.3f}")
    print(f"top-1 correct on answerable questions: {sum(ok for *_, ok in rows)}/"
          f"{sum(c['expected'] == 'answered' for c, *_ in rows)}")


if __name__ == "__main__":
    main()
