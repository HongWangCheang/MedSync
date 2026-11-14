"""Dense-only retrieval metrics inside the chosen label, the way the app searches (Recall@1, Recall@5, MRR)."""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from finetune.split import EVAL  # noqa: E402
from label_retrieval import LabelIndex, LabelSnapshot  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def load_index():
    return LabelIndex(LabelSnapshot(json.loads((ROOT / "data" / "openfda_labels.json").read_text())["results"]), None)


def answerable(name):
    return [c for c in json.loads((EVAL / name).read_text()) if c["expected"] == "answered"]


def metrics(encode, index, cases):
    """encode(list[str]) -> L2-normalised np.ndarray. Relevant = any annotated passage for the question."""
    hits1 = hits5 = rr = 0.0
    for case in cases:
        scope = [index.passages[i] for i in index.by_label[(case["request"]["label_id"], case["request"]["version"])]]
        docs = encode([p.searchable for p in scope])
        query = encode([case["request"]["question"]])[0]
        order = np.argsort(-(docs @ query), kind="stable")
        ranks = [r for r, i in enumerate(order, 1) if scope[i].id in case["relevant_passages"]]
        best = min(ranks)
        hits1 += best == 1
        hits5 += best <= 5
        rr += 1 / best
    n = len(cases)
    return {"recall_at_1": hits1 / n, "recall_at_5": hits5 / n, "mrr": rr / n, "n": n}
