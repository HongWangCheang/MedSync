"""Re-pick the hybrid-mode semantic answer threshold for a given embedding model, on the validation set only."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import label_retrieval  # noqa: E402
from app import build_index  # noqa: E402

VALIDATION = Path(__file__).resolve().parent.parent / "eval" / "validation.json"


def main():
    index = build_index()
    rows = []
    for case in json.loads(VALIDATION.read_text()):
        req = case["request"]
        hits = index.retrieve(req["label_id"], req["version"], req["question"], "hybrid")
        top, sim = hits[0]
        tokens = label_retrieval.words(req["question"])
        matches = tokens & label_retrieval.words(top.searchable)
        lexical = bool(tokens) and len(matches) >= min(2, len(tokens)) and len(matches) / len(tokens) >= 0.34
        correct = (case["expected"] == "answered" and top.id in case["relevant_passages"]
                   and case["gold_excerpt"].casefold() in top.text.casefold())
        rows.append((case["expected"], lexical, sim, correct))

    def passed(t):
        return sum((lex or s >= t) and ok if exp == "answered" else not (lex or s >= t) for exp, lex, s, ok in rows)

    grid = [round(0.30 + 0.01 * i, 2) for i in range(61)]
    best = max(passed(t) for t in grid)
    plateau = [t for t in grid if passed(t) == best]
    print(f"model {label_retrieval.MODEL_NAME}: current {label_retrieval.SEMANTIC_MIN_SCORE} passes "
          f"{passed(label_retrieval.SEMANTIC_MIN_SCORE)}/{len(rows)}; best {best}/{len(rows)} for "
          f"{plateau[0]:.2f}..{plateau[-1]:.2f}; choose {(plateau[0] + plateau[-1]) / 2:.2f}")
    index.db.close()


if __name__ == "__main__":
    main()
