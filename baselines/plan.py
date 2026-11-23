"""Bind C's manifest to A's public inputs and save an exact runnable subset."""

import argparse
import json
from pathlib import Path

from evaluation.manifest import load_manifest
from evaluation.validation import load_records
from integration_smoke.dataset import read_jsonl, write_jsonl


def variant_key(row):
    return tuple(row[key] for key in (
        "base_question_id", "replica_condition", "metadata_state",
        "metadata_error_type", "length_policy"
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--input-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--questions", nargs="+")
    parser.add_argument("--methods", nargs="+")
    parser.add_argument("--replicas", nargs="+")
    parser.add_argument("--metadata", nargs="+")
    parser.add_argument("--splits", nargs="+")
    parser.add_argument("--lengths", nargs="+")
    args = parser.parse_args()
    try:
        public = {r["input_id"]: r for r in load_records(args.public, "public_input")}
        index, by_variant = {}, {}
        for item in read_jsonl(args.input_index):
            registry, key = (index, item["run_id"]) if "run_id" in item else (by_variant, variant_key(item))
            if key in registry:
                raise ValueError(f"duplicate index key {key}")
            registry[key] = item["input_id"]
        selected = []
        for row in load_manifest(args.manifest):
            filters = ((args.questions, "base_question_id"), (args.methods, "method"),
                       (args.replicas, "replica_condition"), (args.metadata, "metadata_state"),
                       (args.splits, "split"), (args.lengths, "length_policy"))
            if any(values and row[key] not in values for values, key in filters):
                continue
            if row["status"] != "planned":
                raise ValueError(f"selected blocked run {row['run_id']}: {row['blocked_reasons']}")
            input_id = index.get(row["run_id"]) or by_variant.get(variant_key(row))
            if input_id not in public or public[input_id]["base_question_id"] != row["base_question_id"]:
                raise ValueError(f"missing or invalid input binding for {row['run_id']}")
            selected.append(dict(row, input_id=input_id))
        if not selected:
            raise ValueError("filters selected no runs")
        if args.output.exists():
            raise ValueError("output already exists")
        write_jsonl(args.output, selected)
        print(json.dumps({"runs": len(selected), "output": str(args.output)}))
    except (KeyError, ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
