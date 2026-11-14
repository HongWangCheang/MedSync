"""Add label sections the snapshot did not keep, for the SAME label versions, from the public openFDA API.

    python backfill_sections.py dosage_and_administration            # updates data/openfda_labels.json in place
    python backfill_sections.py dosage_and_administration --dry-run  # only report what would change

Each record is fetched by its exact SPL document id and only used if openFDA still serves the same version; otherwise
it is reported and left untouched, so the snapshot never silently mixes label versions. Only the requested fields are
written. The run is recorded under `backfills` in the snapshot so its provenance stays visible.
"""

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from label_corpus import DEFAULT_CORPUS, SECTIONS

API = "https://api.fda.gov/drug/label.json"


def fetch(label_id, retries=3):
    query = urllib.parse.urlencode({"search": f'id:"{label_id}"', "limit": 1})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(f"{API}?{query}", timeout=20) as response:
                results = json.load(response).get("results") or []
                return results[0] if results else None
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None  # openFDA answers 404 when nothing matches
            if attempt == retries - 1:
                raise
        except urllib.error.URLError:
            if attempt == retries - 1:
                raise
        time.sleep(2 ** attempt)
    return None


def backfill(snapshot, fields, pause=0.3):
    report = {"filled": {f: 0 for f in fields}, "absent_upstream": [], "version_changed": [], "not_found": []}
    for record in snapshot["results"]:
        upstream = fetch(record["id"])
        time.sleep(pause)  # well under openFDA's 240 requests/minute without a key
        key = f"{record['id']}/{record['version']}"
        if upstream is None:
            report["not_found"].append(key)
            continue
        if str(upstream.get("version")) != record["version"]:
            report["version_changed"].append(f"{key} → {upstream.get('version')}")
            continue
        found = False
        for field in fields:
            if upstream.get(field):
                record[field] = upstream[field]
                report["filled"][field] += 1
                found = True
        if not found:
            report["absent_upstream"].append(key)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("fields", nargs="+", help="openFDA label fields to add, e.g. dosage_and_administration")
    parser.add_argument("--snapshot", default=str(DEFAULT_CORPUS))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    unknown = [f for f in args.fields if f not in SECTIONS]
    if unknown:
        parser.error(f"add {unknown} to label_corpus.SECTIONS first, so the index knows how to title them")

    with open(args.snapshot, encoding="utf-8") as stream:
        snapshot = json.load(stream)
    report = backfill(snapshot, args.fields)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.dry_run:
        return
    snapshot.setdefault("backfills", []).append({
        "fields": args.fields, "source": API, "retrieved_on": date.today().isoformat(),
        "rule": "same SPL document id and version only", **{k: v for k, v in report.items() if k != "filled"},
        "filled": report["filled"],
    })
    with open(args.snapshot, "w", encoding="utf-8") as stream:
        json.dump(snapshot, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
