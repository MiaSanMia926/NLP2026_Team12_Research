#!/usr/bin/env python3
"""Normalize common prediction exports into the evaluation package's canonical JSONL."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

try:
    from .metrics import exact_match
    from .validation import validate_prediction, validate_schema, SCHEMA_DIR, load_records as validate_file
except ImportError:
    from metrics import exact_match
    from validation import validate_prediction, validate_schema, SCHEMA_DIR, load_records as validate_file

PREDICTION_SCHEMA = json.loads((SCHEMA_DIR / "prediction.schema.json").read_text(encoding="utf-8"))


ALIASES = {
    "base_question_id": ("base_question_id", "base_id", "question_id", "qid"),
    "split": ("split", "partition", "dataset_split"),
    "condition_id": ("condition_id", "condition", "setting_id"),
    "replica_condition": ("replica_condition", "repetition_condition", "duplicate_condition"),
    "metadata_state": ("metadata_state", "metadata_condition", "source_metadata_state"),
    "method": ("method", "method_id", "system", "system_name"),
    "model": ("model", "model_id", "generator"),
    "length_policy": ("length_policy", "budget_setting"),
    "prediction": ("prediction", "predicted_answer", "model_answer", "output", "response"),
    "references": ("references", "reference_answers", "gold_answers", "gold_answer", "reference", "ground_truth", "target"),
    "answered": ("answered", "is_answered", "responded"),
    "should_answer": ("should_answer", "answerable", "is_answerable", "expected_answerable", "must_answer"),
    "correct": ("correct", "is_correct", "answer_correct", "exact_match_correct"),
    "selection_score": ("selection_score", "confidence", "answer_confidence", "gate_score"),
    "confidence": ("confidence", "answer_confidence"),
    "input_tokens": ("input_tokens", "prompt_tokens", "n_prompt_tokens"),
    "output_tokens": ("output_tokens", "completion_tokens", "n_completion_tokens"),
    "calls": ("calls", "api_calls", "num_calls"),
    "latency_seconds": ("latency_seconds", "latency", "elapsed_seconds"),
    "pair_id": ("pair_id", "pairing_id"),
    "answer_supported": ("answer_supported", "evidence_supported"),
    "citation_correct": ("citation_correct", "citations_correct"),
    "cited_evidence_ids": ("cited_evidence_ids", "citations", "cited_ids"),
    "supporting_evidence_ids": ("supporting_evidence_ids", "gold_supporting_ids"),
    "gold_independent_support_groups": ("gold_independent_support_groups", "gold_support_groups"),
    "retained_independent_support_groups": ("retained_independent_support_groups", "retained_support_groups"),
    "raw_log_id": ("raw_log_id", "log_id", "record_id"),
}
BOOL_FIELDS = {"answered", "should_answer", "correct", "answer_supported", "citation_correct"}
INVERTED_FIELDS = {"answered": ("abstained",), "should_answer": ("should_abstain", "expected_abstain")}
LIST_FIELDS = {"references", "cited_evidence_ids", "supporting_evidence_ids", "gold_independent_support_groups", "retained_independent_support_groups"}


def parse_mapping(items: list[str]) -> dict[str, str]:
    mapping = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"invalid --map {item!r}; expected TARGET=SOURCE_FIELD")
        target, source = item.split("=", 1)
        if target not in ALIASES:
            raise ValueError(f"unsupported target field {target!r}; choose from {', '.join(ALIASES)}")
        mapping[target] = source
    return mapping


def load_records(path: Path, records_key: str | None) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        records = []
        with path.open(encoding="utf-8-sig") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
                if not isinstance(item, dict):
                    raise ValueError(f"{path}:{line_no}: each JSONL record must be an object")
                records.append(item)
        return records
    if suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if records_key:
            for part in records_key.split("."):
                if not isinstance(value, dict) or part not in value:
                    raise ValueError(f"could not resolve --records-key {records_key!r}")
                value = value[part]
        elif isinstance(value, dict):
            for candidate in ("predictions", "results", "records", "data"):
                if isinstance(value.get(candidate), list):
                    value = value[candidate]
                    break
            else:
                raise ValueError("JSON object needs a list under predictions/results/records/data or an explicit --records-key")
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ValueError("JSON records must be a list of objects")
        return value
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f, delimiter=delimiter))
    raise ValueError(f"unsupported input format {suffix!r}; use JSONL, JSON, CSV, or TSV")


def get_path(record: dict[str, Any], path: str) -> Any:
    if path in record:
        return record[path]
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def find_value(record: dict[str, Any], target: str, mapping: dict[str, str]) -> tuple[Any, str | None]:
    if target in mapping:
        return get_path(record, mapping[target]), mapping[target]
    for alias in ALIASES[target]:
        value = get_path(record, alias)
        if value is not None and value != "":
            return value, alias
    inverse_aliases = INVERTED_FIELDS.get(target, ())
    for alias in inverse_aliases:
        value = get_path(record, alias)
        if value is not None and value != "":
            return value, alias
    return None, None


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "answered", "answer"}:
            return True
        if normalized in {"false", "0", "no", "n", "abstain", "abstained", "refuse", "refused"}:
            return False
    raise ValueError(f"cannot parse boolean from {value!r}")


def parse_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None or value == "":
        return []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
        return [value]
    return [value]


def convert_record(record: dict[str, Any], mapping: dict[str, str], default_method: str | None,
                   infer_answered: bool, derive_correct: bool) -> tuple[dict[str, Any], list[str], dict[str, str]]:
    result = dict(record)
    errors: list[str] = []
    used: dict[str, str] = {}
    for target in ALIASES:
        value, source = find_value(record, target, mapping)
        if source:
            used[target] = source
        if value is not None:
            try:
                if target in INVERTED_FIELDS and source in INVERTED_FIELDS[target]:
                    value = not parse_bool(value)
                if target in BOOL_FIELDS:
                    value = parse_bool(value)
                elif target in LIST_FIELDS:
                    value = parse_list(value)
                elif target in {"input_tokens", "output_tokens", "calls"}:
                    if type(value) is bool or not math.isfinite(float(value)) or float(value) < 0 or not float(value).is_integer():
                        raise ValueError("must be a nonnegative integer")
                    value = int(value) if isinstance(value, (int, float)) else int(float(value))
                elif target in {"latency_seconds", "selection_score", "confidence"}:
                    if type(value) is bool:
                        raise ValueError("boolean is not a numeric measurement")
                    value = float(value)
                    if not math.isfinite(value):
                        raise ValueError("must be finite")
                elif target in {"prediction", "method", "base_question_id", "model", "split", "metadata_state", "replica_condition", "condition_id", "length_policy", "pair_id", "raw_log_id"}:
                    value = str(value)
                result[target] = value
            except (TypeError, ValueError) as exc:
                errors.append(f"{target}: {exc}")
    if not result.get("method") and default_method:
        result["method"] = default_method
        used["method"] = "<default-method>"
    if "answered" not in result and infer_answered and result.get("prediction") is not None:
        result["answered"] = bool(str(result["prediction"]).strip())
        used["answered"] = "<inferred-from-nonempty-prediction>"
    if "correct" not in result and derive_correct and result.get("answered") and result.get("references"):
        result["correct"] = bool(exact_match(str(result.get("prediction", "")), [str(x) for x in result["references"]]))
        used["correct"] = "<derived-by-exact-match>"
    # Preserve explicit nulls. Neither missing trace fields nor abstentions are guessed.
    try:
        validate_schema(result, PREDICTION_SCHEMA)
        validate_prediction(result)
    except (ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    return result, errors, used


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="JSONL, JSON, CSV, or TSV prediction export")
    parser.add_argument("--output", required=True, help="canonical JSONL output")
    parser.add_argument("--report", help="JSON conversion report (default: OUTPUT.report.json)")
    parser.add_argument("--records-key", help="nested JSON key path for records, e.g. evaluation.predictions")
    parser.add_argument("--map", action="append", default=[], metavar="TARGET=SOURCE_FIELD", help="explicit field mapping; dotted source paths work")
    parser.add_argument("--default-method", help="method name to apply only when no method column exists")
    parser.add_argument("--infer-answered-from-prediction", action="store_true", help="infer answered from non-empty prediction text")
    parser.add_argument("--derive-correct-from-em", action="store_true", help="derive correctness by exact string match; not suitable for semantic or multilingual adjudication")
    args = parser.parse_args()
    if Path(args.output).exists():
        print("output already exists; choose a new path", file=sys.stderr)
        return 2
    report_path = Path(args.report) if args.report else Path(args.output).with_suffix(".report.json")
    if report_path.resolve() in {Path(args.input).resolve(), Path(args.output).resolve()}:
        print("conversion report must be separate from input and output", file=sys.stderr)
        return 2
    report: dict[str, Any] = {"input": args.input, "output": args.output, "errors": [], "warnings": [], "field_sources": {}, "record_count": 0}
    try:
        mapping = parse_mapping(args.map)
        records = load_records(Path(args.input), args.records_key)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report["errors"].append(str(exc))
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "failed", "report": str(report_path), "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    report["record_count"] = len(records)
    normalized = []
    for index, record in enumerate(records, 1):
        row, errors, used = convert_record(record, mapping, args.default_method,
                                           args.infer_answered_from_prediction, args.derive_correct_from_em)
        for field, source in used.items():
            report["field_sources"].setdefault(field, set()).add(source)
        if errors:
            report["errors"].append({"record": index, "base_question_id": row.get("base_question_id"), "issues": errors})
        normalized.append(row)
    report["field_sources"] = {key: sorted(values) for key, values in report["field_sources"].items()}
    if args.derive_correct_from_em:
        report["warnings"].append("Correctness was derived using exact-match normalization; verify this evaluator is appropriate before using results.")
    if args.infer_answered_from_prediction:
        report["warnings"].append("Answered/abstained status was inferred from non-empty prediction text.")
    if not records:
        report["errors"].append("input contains no records")
    report["status"] = "failed" if report["errors"] else "ok"
    report["normalized_count"] = len(normalized) if not report["errors"] else 0
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["errors"]:
        print(json.dumps({"status": "failed", "records": len(records), "issues": len(report["errors"]), "report": str(report_path)}, ensure_ascii=False), file=sys.stderr)
        return 2
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Validate cross-record split, pair and run invariants before publishing.
    import tempfile
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_path.parent, suffix=".tmp", delete=False) as stream:
            temp_name = Path(stream.name)
            stream.write("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in normalized))
        validate_file(temp_name)
        temp_name.replace(output_path)
    except (ValueError, OSError, TypeError) as exc:
        report.update(status="failed", normalized_count=0)
        report["errors"].append(str(exc))
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        if temp_name is not None and temp_name.exists():
            temp_name.unlink()
    print(json.dumps({"status": "ok", "records": len(normalized), "output": str(output_path), "report": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
