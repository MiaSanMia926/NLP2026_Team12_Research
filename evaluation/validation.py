"""Validate our JSON contract and semantic invariants using the standard library.

Only the JSON Schema keywords present in our files are implemented here;
this is not a general-purpose JSON Schema engine.
"""
from __future__ import annotations
import argparse
import json
import math
import re
import sys
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_schema(value, schema, location="row"):
    predicates = {
        "null": lambda: value is None, "boolean": lambda: type(value) is bool,
        "string": lambda: isinstance(value, str), "integer": lambda: type(value) is int,
        "number": lambda: finite_number(value), "array": lambda: isinstance(value, list),
        "object": lambda: isinstance(value, dict),
    }
    kinds = schema.get("type", [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    if kinds and not any(predicates[k]() for k in kinds):
        raise ValueError(f"{location}: expected {kinds}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{location}: invalid enum value")
    if isinstance(value, str) and len(value.strip()) < schema.get("minLength", 0):
        raise ValueError(f"{location}: empty string")
    if isinstance(value, str) and "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
        raise ValueError(f"{location}: invalid format")
    if finite_number(value) and value < schema.get("minimum", -math.inf):
        raise ValueError(f"{location}: below minimum")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"{location}: too few items")
        if schema.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in value}) != len(value):
            raise ValueError(f"{location}: duplicate items")
        for i, item in enumerate(value):
            validate_schema(item, schema.get("items", {}), f"{location}[{i}]")
    if isinstance(value, dict):
        if schema.get("additionalProperties") is False:
            unexpected = set(value) - set(schema.get("properties", {}))
            if unexpected:
                raise ValueError(f"{location}: unexpected fields {sorted(unexpected)}")
        for field in schema.get("required", []):
            if field not in value:
                raise ValueError(f"{location}: missing {field}")
        for field, item in value.items():
            if field in schema.get("properties", {}):
                validate_schema(item, schema["properties"][field], f"{location}.{field}")


def validate_prediction(row):
    if row["status"] != "ok":
        if any(row.get(k) is not None for k in ("answered", "correct", "prediction", "selection_score")):
            raise ValueError("failed runs require null decision, correctness, prediction and score")
        return
    if type(row["answered"]) is not bool:
        raise ValueError("successful rows require boolean answered")
    if row["answered"]:
        if not isinstance(row["prediction"], str) or not row["prediction"].strip() or type(row["correct"]) is not bool:
            raise ValueError("answered rows require a nonempty prediction and boolean correct")
    elif row["prediction"] is not None or row["correct"] is not None:
        raise ValueError("abstentions require prediction=null, correct=null; save candidate separately")
    if (row["metadata_state"] == "incorrect") != (row["metadata_error_type"] != "none"):
        raise ValueError("incorrect metadata requires split/merge recipe; other states require none")
    if row["task_type"] == "evidence_constrained_qa":
        if type(row["should_answer"]) is not bool:
            raise ValueError("controlled tasks require should_answer")
        if row["should_answer"] and not row["references"]:
            raise ValueError("answerable controlled tasks require references")
        if row["should_answer"] is False and (row.get("correct") is True or row.get("candidate_task_correct") is True):
            raise ValueError("an answer to a should-abstain controlled task cannot be task-correct")
    for field in ("candidate_task_correct", "candidate_factual_correct"):
        if row.get(field) is not None and (not isinstance(row.get("candidate_answer"), str) or not row["candidate_answer"].strip()):
            raise ValueError("candidate correctness requires candidate_answer")


def load_records(path, kind="prediction"):
    schema = json.loads((SCHEMA_DIR / f"{kind}.schema.json").read_text(encoding="utf-8"))
    rows, seen, families, pair_specs = [], set(), {}, {}
    def reject_constant(value):
        raise ValueError(f"non-finite JSON number {value}")
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line, parse_constant=reject_constant)
                validate_schema(row, schema)
                if kind == "prediction":
                    validate_prediction(row)
                    controls = tuple(row[k] for k in ("dataset_id", "dataset_version", "dataset_hash", "split_hash", "experiment_id", "base_question_id", "family_id", "split", "task_type", "method", "config_hash", "model", "model_revision", "seed", "position_seed", "length_policy", "metadata_state", "metadata_error_type"))
                    if row["pair_id"] in pair_specs and pair_specs[row["pair_id"]] != controls:
                        raise ValueError("pair_id reused across incompatible controls")
                    pair_specs[row["pair_id"]] = controls
                if kind == "public_input":
                    evidence_ids = [e["evidence_id"] for e in row["evidence"]]
                    if len(set(evidence_ids)) != len(evidence_ids):
                        raise ValueError("duplicate evidence IDs")
                key = row["input_id"] if kind == "public_input" else row["run_id"] if kind == "prediction" else (row["dataset_id"], row["dataset_version"], row["base_question_id"])
                if key in seen:
                    raise ValueError(f"duplicate ID: {key}")
                seen.add(key)
                if kind != "public_input":
                    family = (row["dataset_id"], row["dataset_version"], row["family_id"])
                    if family in families and families[family] != row["split"]:
                        raise ValueError(f"family leaks across splits: {family}")
                    families[family] = row["split"]
                rows.append(row)
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
    if not rows:
        raise ValueError(f"{path}: no records")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("--kind", choices=["prediction", "question", "public_input"], default="prediction")
    args = parser.parse_args()
    try:
        rows = load_records(args.input, args.kind)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"status": "valid", "records": len(rows), "kind": args.kind}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
