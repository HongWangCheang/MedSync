"""Create a compact versioned snapshot from openFDA drug-label JSON or ZIP files."""

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from zipfile import ZipFile

DEFAULT_CORPUS = Path(__file__).with_name("data") / "openfda_labels.json"
SECTIONS = {
    "purpose": "Purpose",
    "indications_and_usage": "Indications and usage",
    "storage_and_handling": "Storage and handling",
    "other_safety_information": "Other safety information",
    "warnings": "Warnings",
    "boxed_warning": "Boxed warning",
    "warnings_and_cautions": "Warnings and precautions",
    "do_not_use": "Do not use",
    "stop_use": "When to stop use",
    "ask_doctor": "Ask a doctor before use",
    "ask_doctor_or_pharmacist": "Ask a doctor or pharmacist before use",
    "keep_out_of_reach_of_children": "Keep out of reach of children",
    "inactive_ingredient": "Inactive ingredients",
    "active_ingredient": "Active ingredients",
    "dosage_forms_and_strengths": "Dosage forms and strengths",
    "description": "Description",
    "information_for_patients": "Information for patients",
    "adverse_reactions": "Adverse reactions",
    "drug_interactions": "Drug interactions",
    "how_supplied": "How supplied",
    "pregnancy_or_breast_feeding": "Pregnancy or breast-feeding",
    "when_using": "When using this product",
    # OTC "Directions" and prescription "Dosage and administration" both live in this openFDA field.
    "dosage_and_administration": "Directions / dosage and administration",
}
METADATA = ("brand_name", "generic_name", "manufacturer_name", "dosage_form",
            "route", "product_ndc", "substance_name")


def read_dump(path):
    if path.suffix.casefold() == ".zip":
        with ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if name.endswith(".json"):
                    with archive.open(name) as stream:
                        yield json.load(stream)
    else:
        yield json.loads(path.read_text(encoding="utf-8"))


def make_snapshot(paths, selected, origin, retrieved):
    labels = {}
    upstream_dates = set()
    for path in paths:
        for payload in read_dump(path):
            updated = payload.get("meta", {}).get("last_updated")
            if updated:
                upstream_dates.add(updated)
            for raw in payload["results"]:
                metadata = raw.get("openfda") or {}
                label_id, version = raw.get("id"), raw.get("version")
                if not (label_id and version and metadata.get("brand_name")):
                    continue
                key = (label_id, str(version))
                if selected and key not in selected:
                    continue
                record = {field: raw[field] for field in SECTIONS if raw.get(field)}
                record.update(id=label_id, version=str(version), effective_time=raw.get("effective_time"),
                              set_id=raw.get("set_id"),
                              openfda={field: metadata[field] for field in METADATA if metadata.get(field)})
                labels[key] = record
    if selected and selected - labels.keys():
        missing = ", ".join("/".join(pair) for pair in sorted(selected - labels.keys()))
        raise ValueError(f"Requested label versions missing from input: {missing}")
    if not labels:
        raise ValueError("No eligible label records were found.")
    return {
        "origin": origin,
        "documentation": "https://open.fda.gov/apis/drug/label/download/",
        "retrieved_on": retrieved,
        "upstream_last_updated": sorted(upstream_dates),
        "results": [labels[key] for key in sorted(labels)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--selection", type=Path, help="Existing snapshot whose exact label IDs and versions to retain")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retrieved", default=date.today().isoformat())
    args = parser.parse_args()
    selected = set()
    if args.selection:
        selected = {(r["id"], r["version"]) for r in next(read_dump(args.selection))["results"]}
    snapshot = make_snapshot(args.files, selected, "openFDA drug-label JSON export", args.retrieved)
    content = (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    args.output.write_bytes(content)
    print(f"{len(snapshot['results'])} records, sha256 {hashlib.sha256(content).hexdigest()}")


if __name__ == "__main__":
    main()
