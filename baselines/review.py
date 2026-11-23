"""Join run predictions with A's gold and independent A/D reviews offline."""

import argparse
import json
from pathlib import Path

from evaluation.manifest import load_manifest
from evaluation.validation import SCHEMA_DIR, validate_prediction, validate_schema
from integration_smoke.dataset import read_jsonl, write_jsonl


def by_id(path, field):
    rows = read_jsonl(path)
    index = {row[field]: row for row in rows}
    if len(index) != len(rows):
        raise ValueError(f"{path}: duplicate {field}")
    return index


def join(rows, gold, reviews):
    result = []
    for row in rows:
        truth = gold[row["input_id"]]
        record = dict(row, should_answer=truth["should_answer"], references=truth["references"],
                      correct=None, candidate_task_correct=None, candidate_factual_correct=None)
        if row["status"] == "ok":
            if type(row["answered"]) is not bool:
                raise ValueError("gate feature collection rows are not final predictions")
            review = reviews[row["run_id"]]
            label = review.get("candidate_task_correct")
            factual = review.get("candidate_factual_correct")
            if row["candidate_answer"] is not None:
                field = "candidate_task_correct" if row["task_type"] == "evidence_constrained_qa" else "candidate_factual_correct"
                if type(review.get(field)) is not bool:
                    raise ValueError(f"review requires boolean {field} for {row['run_id']}")
            if not isinstance(review.get("label_origin"), str) or not review["label_origin"].strip():
                raise ValueError(f"missing label origin for {row['run_id']}")
            record.update(candidate_task_correct=label, candidate_factual_correct=factual,
                          correct=(label if row["task_type"] == "evidence_constrained_qa" else factual)
                          if row["answered"] else None, label_origin=review["label_origin"])
            for key in ("answer_supported", "citation_correct", "citation_labels"):
                if key in review:
                    record[key] = review[key]
            if "citation_labels" in review and len(review["citation_labels"]) != len(row["cited_evidence_ids"]):
                raise ValueError("citation labels must follow the cited evidence list")
            if "gold_independent_support_groups" in truth:
                evidence_truth = truth["evidence_truth"]
                retained = {evidence_truth[eid]["gold_group"] for eid in row["retained_evidence_ids"]
                            if eid in evidence_truth}
                record.update(gold_independent_support_groups=truth["gold_independent_support_groups"],
                              retained_independent_support_groups=sorted(retained))
        result.append(record)
    schema = json.loads((SCHEMA_DIR / "prediction.schema.json").read_text())
    for row in result:
        validate_schema(row, schema)
        validate_prediction(row)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("predictions", "manifest", "gold", "reviews", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("choose a fresh output file")
        rows = by_id(args.predictions, "run_id")
        reviewed = by_id(args.reviews, "run_id")
        manifest = load_manifest(args.manifest)
        if {row["run_id"] for row in manifest} != rows.keys():
            raise ValueError("predictions must cover the exact manifest")
        if any(rows[row["run_id"]]["input_id"] != row["input_id"] for row in manifest):
            raise ValueError("prediction input does not match the bound manifest")
        if {row["run_id"] for row in rows.values() if row["status"] == "ok"} != reviewed.keys():
            raise ValueError("supply one review per successful run ID")
        records = join(rows.values(), by_id(args.gold, "input_id"), reviewed)
        write_jsonl(args.output, records)
        print(json.dumps({"rows": len(records), "output": str(args.output)}))
    except (KeyError, OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
