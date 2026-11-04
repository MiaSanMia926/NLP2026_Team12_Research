"""Audit planned runs, including absent slices and trace errors in partial batches."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

try:
    from .metrics import GROUP_FIELDS, ratio
    from .validation import SCHEMA_DIR, validate_schema
except ImportError:
    from metrics import GROUP_FIELDS, ratio
    from validation import SCHEMA_DIR, validate_schema

TRACE_FIELDS = tuple(dict.fromkeys(GROUP_FIELDS + ("base_question_id", "family_id", "pair_id")))


def load_manifest(path):
    """Require full run identity; a list of run IDs cannot verify provenance."""
    schema = json.loads((SCHEMA_DIR / "prediction.schema.json").read_text(encoding="utf-8"))
    fields = ("run_id", "status") + TRACE_FIELDS
    contract = {"type": "object", "required": list(fields),
                "properties": {k: schema["properties"][k] for k in fields}}
    # Prediction-shaped legacy fixtures remain usable; real schedulers use planned/blocked.
    contract["properties"]["status"] = {"type": "string", "enum": ["planned", "blocked"] + schema["properties"]["status"]["enum"]}
    rows, seen = [], set()
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                # The scheduler deliberately leaves an unavailable error recipe null.
                checked = row
                if (isinstance(row, dict) and row.get("status") == "blocked" and row.get("metadata_state") == "incorrect"
                        and row.get("metadata_error_type", "absent") is None):
                    checked = dict(row, metadata_error_type="none")
                validate_schema(checked, contract)
                if row["status"] == "blocked":
                    reasons = row.get("blocked_reasons")
                    if not isinstance(reasons, list) or not reasons or any(not isinstance(r, str) or not r.strip() for r in reasons):
                        raise ValueError("blocked manifest runs require nonempty blocked_reasons")
                if row["run_id"] in seen:
                    raise ValueError("duplicate manifest run IDs")
                seen.add(row["run_id"])
                rows.append(row)
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
    if not rows:
        raise ValueError("manifest must contain full run identities")
    return rows


def audit_manifest(rows, path):
    if path is None:
        return {"checked": False, "status": "unverified", "groups": [],
                "note": "planned_n counts supplied records only"}
    records = load_manifest(path)
    expected = {r["run_id"]: r for r in records}
    actual = {r["run_id"]: r for r in rows}
    if len(actual) != len(rows):
        raise ValueError("duplicate prediction run IDs")
    missing, extra = sorted(expected.keys()-actual.keys()), sorted(actual.keys()-expected.keys())
    mismatches = [{"run_id": run_id, "field": field,
                   "expected": expected[run_id][field], "actual": actual[run_id].get(field)}
                  for run_id in sorted(expected.keys() & actual.keys()) for field in TRACE_FIELDS
                  if expected[run_id][field] != actual[run_id].get(field)]
    bad_ids = {m["run_id"] for m in mismatches}
    blocked = sorted(r["run_id"] for r in records if r.get("status") == "blocked")
    groups = defaultdict(lambda: {"planned_n": 0, "provided_n": 0, "ok_n": 0,
                                 "failed_n": 0, "missing_n": 0, "extra_n": 0,
                                 "trace_mismatch_n": 0, "blocked_n": 0})
    for planned in records:
        counts = groups[tuple(planned[k] for k in GROUP_FIELDS)]
        counts["planned_n"] += 1
        counts["blocked_n"] += int(planned.get("status") == "blocked")
        result = actual.get(planned["run_id"])
        if result is None:
            counts["missing_n"] += 1
            continue
        counts["provided_n"] += 1
        if planned["run_id"] in bad_ids:
            counts["trace_mismatch_n"] += 1
        else:
            counts["ok_n" if result["status"] == "ok" else "failed_n"] += 1
    for run_id in extra:
        groups[tuple(actual[run_id][k] for k in GROUP_FIELDS)]["extra_n"] += 1
    coverage = [{"slice": dict(zip(GROUP_FIELDS, key)), **counts,
                 "completion_rate": ratio(counts["ok_n"], counts["planned_n"])}
                for key, counts in sorted(groups.items(), key=lambda x: repr(x[0]))]
    trace_error = (f"manifest trace mismatch: {mismatches[0]['run_id']}/{mismatches[0]['field']}" if mismatches else None)
    return {"checked": True, "status": "incomplete" if missing or extra or mismatches or blocked else "complete",
            "planned_n": len(records), "provided_n": len(rows), "missing_run_ids": missing,
            "extra_run_ids": extra, "trace_error": trace_error, "trace_mismatches": mismatches,
            "blocked_plan_run_ids": blocked, "groups": coverage,
            "ok_n": sum(g["ok_n"] for g in coverage), "failed_n": sum(g["failed_n"] for g in coverage),
            "note": "complete means all planned records accounted for with matching trace, not all successful or scientifically approved"}
