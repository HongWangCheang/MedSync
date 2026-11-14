"""Leakage-safe training split shared by data generation and evaluation."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def held_out_labels(index):
    """Every label touched by the test or validation sets, including all same-name candidates."""
    held = set()
    for name in ("questions.json", "validation.json"):
        for case in json.loads((EVAL / name).read_text()):
            request = case["request"]
            if "label_id" in request:
                held.add(request["label_id"])
            if "drug_name" in request:
                held |= {label["id"] for label in index.catalog.search(request["drug_name"])["labels"]}
    return held


def training_passages(index):
    held = held_out_labels(index)
    held_text = {norm(p.text) for p in index.passages if p.label_id in held}
    # Many labels share boilerplate word for word; drop any passage whose text also appears in a held-out label.
    return [p for p in index.passages if p.label_id not in held and norm(p.text) not in held_text]
