"""Builds data/openfda_rx_labels.json: one label for every ingredient the safety review knows but the main snapshot
has no label for (mostly prescription drugs such as warfarin, digoxin, clarithromycin).

    python fetch_rx_labels.py            # public openFDA API, no key needed (~60 requests)

Selection is mechanical, so the snapshot is not tuned to any test case: for each ingredient in safety_review.INGREDIENTS
without a single-ingredient label in data/openfda_labels.json, take the openFDA label whose only active substance is
that ingredient: oral forms first, then the most interaction-related sections, then the newest version. Only the sections
the app reads are kept. The safety review reads this snapshot alongside the main one; the pharmacist does not (its
retrieval evaluation is pinned to the main snapshot).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from agent import INTERACTION_SECTIONS, plain
from label_corpus import DEFAULT_CORPUS, METADATA, SECTIONS

API = "https://api.fda.gov/drug/label.json"
OUT = DEFAULT_CORPUS.with_name("openfda_rx_labels.json")


def search(ingredient: str) -> list[dict]:
    query = urllib.parse.urlencode({"search": f'openfda.generic_name:"{ingredient}"', "limit": 100})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(f"{API}?{query}", timeout=30) as response:
                return json.load(response).get("results") or []
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return []
            if attempt == 3:
                raise
        except urllib.error.URLError:
            if attempt == 3:
                raise
        time.sleep(2 ** attempt)
    return []


def single(raw: dict, ingredient: str) -> bool:
    substances = (raw.get("openfda") or {}).get("substance_name") or []
    return len(substances) == 1 and plain(ingredient) in plain(substances[0])


def record(raw: dict) -> dict:
    metadata = raw.get("openfda") or {}
    kept = {field: raw[field] for field in SECTIONS if raw.get(field)}
    kept.update(id=raw["id"], version=str(raw["version"]), effective_time=raw.get("effective_time"),
                set_id=raw.get("set_id"), openfda={f: metadata[f] for f in METADATA if metadata.get(f)})
    return kept


def main() -> None:
    from safety_review import INGREDIENTS, SafetyChecker
    from label_retrieval import LabelIndex, LabelSnapshot

    base = json.loads(DEFAULT_CORPUS.read_text(encoding="utf-8"))
    checker = SafetyChecker(LabelIndex(LabelSnapshot(base["results"], public=True), model=None))
    covered = {next(iter(ing)) for ing in checker._ingredients.values() if len(ing) == 1}
    wanted = sorted(k for k in INGREDIENTS if k not in covered)
    labels, missing = [], []
    for ingredient in wanted:
        candidates = [r for r in search(ingredient) if single(r, ingredient) and r.get("id") and r.get("version")
                      and (r.get("openfda") or {}).get("brand_name")]
        if not candidates:
            missing.append(ingredient)
            print(f"  -  {ingredient}: no single-ingredient label")
            continue
        oral = lambda r: "ORAL" in ((r.get("openfda") or {}).get("route") or [])  # what users take at home
        best = max(candidates, key=lambda r: (oral(r), sum(bool(r.get(f)) for f in INTERACTION_SECTIONS),
                                              r.get("effective_time") or "", r["id"]))
        labels.append(record(best))
        print(f"  +  {ingredient}: {best['openfda'].get('brand_name', ['?'])[0]} ({best.get('effective_time')})")
        time.sleep(0.3)
    snapshot = {
        "origin": "openFDA drug-label API, one label per ingredient (fetch_rx_labels.py)",
        "documentation": "https://open.fda.gov/apis/drug/label/",
        "retrieved_on": date.today().isoformat(),
        "sampling": "For every ingredient in safety_review.INGREDIENTS without a single-ingredient label in "
                    "openfda_labels.json: the single-substance label, oral first, then the most interaction-related "
                    "sections, then the newest version.",
        "missing": missing,
        "results": sorted(labels, key=lambda r: (r["id"], r["version"])),
    }
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(labels)} labels, {len(missing)} missing → {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
