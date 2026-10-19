"""Metrics for reviewed outputs; no model correctness is inferred."""
from __future__ import annotations
import argparse
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
try:
    from .validation import load_records, finite_number
except ImportError:
    from validation import load_records, finite_number

ARTICLES = {"a", "an", "the"}
SLICE_FIELDS = ("dataset_id", "dataset_version", "task_type", "split", "model", "model_revision", "length_policy", "seed", "experiment_id")
GROUP_FIELDS = SLICE_FIELDS + ("method", "config_hash", "condition_id", "metadata_state", "metadata_error_type", "replica_condition", "position_seed")

def load_jsonl(path):
    return load_records(path, "prediction")

def normalize_answer(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    chars = []
    for char in text:
        category = unicodedata.category(char)
        chars.append(char if category[0] in {"L", "N"} else " ")
    return " ".join(token for token in "".join(chars).split() if token not in ARTICLES)


def answer_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    # Keep contiguous Latin/digit words; score CJK ideographs character by character.
    tokens = re.findall(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]|[^\W\d_\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+", normalized)
    return [token for token in tokens if token not in ARTICLES]


def exact_match(prediction: str, references: list[str]) -> float:
    pred = normalize_answer(prediction)
    return float(any(pred == normalize_answer(ref) for ref in references))


def token_f1(prediction: str, reference: str) -> float:
    pred_tokens, ref_tokens = answer_tokens(prediction), answer_tokens(reference)
    if not pred_tokens or not ref_tokens:
        return float(pred_tokens == ref_tokens)
    pred_counts: dict[str, int] = defaultdict(int)
    ref_counts: dict[str, int] = defaultdict(int)
    for token in pred_tokens:
        pred_counts[token] += 1
    for token in ref_tokens:
        ref_counts[token] += 1
    overlap = sum(min(count, ref_counts[token]) for token, count in pred_counts.items())
    if overlap == 0:
        return 0.0
    precision, recall = overlap / len(pred_tokens), overlap / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)



def ratio(n, d):
    return n / d if d else None


def mean(values):
    values = [v for v in values if v is not None and math.isfinite(v)]
    return ratio(sum(values), len(values))


def row_quality(row):
    if row["task_type"] == "evidence_constrained_qa" and row["should_answer"] is False:
        return 0.0, 0.0
    if not row["references"]:
        return None, None
    if not row["answered"]:
        return 0.0, 0.0
    return exact_match(row["prediction"], row["references"]), max(token_f1(row["prediction"], ref) for ref in row["references"])


def risk_curve(rows, mode="candidate"):
    valid = [r for r in rows if r["status"] == "ok"]
    selected = valid if mode == "candidate" else [r for r in valid if r["answered"]]
    unavailable = {"mode": mode, "available": False, "points": [], "area": None, "max_coverage": None}
    if not valid or not selected:
        return dict(unavailable, reason="no_rankable_rows")
    scored = []
    for row in selected:
        label_key = "candidate_task_correct" if row["task_type"] == "evidence_constrained_qa" else "candidate_factual_correct"
        label = row.get(label_key) if mode == "candidate" else row["correct"]
        candidate = row.get("candidate_answer") if mode == "candidate" else row["prediction"]
        if not finite_number(row.get("selection_score")) or type(label) is not bool or not candidate:
            return dict(unavailable, reason="missing_candidate_label_or_score")
        scored.append((row["selection_score"], int(not label)))
    scored.sort(reverse=True)
    points = [{"coverage": 0.0, "risk": None, "accepted": 0, "score_threshold": None}]
    i = errors = 0
    area = 0.0
    while i < len(scored):
        j = i
        while j < len(scored) and scored[j][0] == scored[i][0]:
            errors += scored[j][1]
            j += 1
        risk = errors / j
        area += (j - i) / len(valid) * risk
        points.append({"coverage": j / len(valid), "risk": risk, "accepted": j, "score_threshold": scored[i][0]})
        i = j
    return {"mode": mode, "available": True, "reason": None, "points": points, "area": area,
            "max_coverage": len(scored) / len(valid), "denominator": len(valid)}


def aurc(rows):
    return risk_curve(rows)["area"]


def partial_area(curve, endpoint):
    if not curve["available"] or endpoint <= 0 or endpoint > curve["max_coverage"]:
        return None
    area, previous = 0.0, 0.0
    for point in curve["points"][1:]:
        right = min(point["coverage"], endpoint)
        area += (right - previous) * point["risk"]
        if point["coverage"] >= endpoint:
            break
        previous = point["coverage"]
    return area


def replica_metrics(rows):
    pairs = defaultdict(list)
    for r in rows:
        if r["status"] == "ok" and r["replica_condition"] in {"no_replica", "same_source_replica"}:
            key = tuple(r.get(k) for k in SLICE_FIELDS + ("base_question_id", "method", "metadata_state", "metadata_error_type", "pair_id"))
            pairs[key].append(r)
    valid, invalid = [], 0
    for group in pairs.values():
        a = [r for r in group if r["replica_condition"] == "no_replica"]
        b = [r for r in group if r["replica_condition"] == "same_source_replica"]
        if len(a) == len(b) == 1:
            valid.append((a[0], b[0]))
        else:
            invalid += 1
    both = [(a, b) for a, b in valid if a["answered"] and b["answered"]]
    n = len(valid)
    return {"valid_pairs": n, "invalid_pair_groups": invalid,
            "answer_text_change_rate": ratio(sum(a["prediction"] != b["prediction"] for a,b in valid), n),
            "normalized_answer_change_rate": ratio(sum(normalize_answer(a["prediction"] or "") != normalize_answer(b["prediction"] or "") for a,b in valid), n),
            "decision_change_rate": ratio(sum(a["answered"] != b["answered"] for a,b in valid), n),
            "both_answered_pairs": len(both),
            "improved_rate": ratio(sum(a["correct"] is False and b["correct"] is True for a,b in both), len(both)),
            "worsened_rate": ratio(sum(a["correct"] is True and b["correct"] is False for a,b in both), len(both)),
            "unchanged_correctness_rate": ratio(sum(a["correct"] == b["correct"] for a,b in both), len(both)),
            "note": "Correctness transitions use both-answered pairs; abstention changes are reported separately."}


def support_retention(rows):
    rates, numerator, denominator = [], 0, 0
    for r in rows:
        gold, kept = r.get("gold_independent_support_groups"), r.get("retained_independent_support_groups")
        if not isinstance(gold, list) or not gold or not isinstance(kept, list):
            continue
        retained = len(set(gold) & set(kept))
        rates.append(retained / len(set(gold)))
        numerator += retained
        denominator += len(set(gold))
    return {"eligible_rows": len(rates), "retained_groups": numerator, "gold_groups": denominator,
            "micro_rate": ratio(numerator, denominator), "macro_rate": mean(rates)}


def summarize(rows):
    valid = [r for r in rows if r["status"] == "ok"]
    answered = [r for r in valid if r["answered"]]
    yes = [r for r in valid if r["should_answer"] is True]
    no = [r for r in valid if r["should_answer"] is False]
    qualities = [row_quality(r) for r in valid]
    support = [r["answer_supported"] for r in answered if type(r.get("answer_supported")) is bool]
    all_citations = [r["citation_correct"] for r in answered if type(r.get("citation_correct")) is bool]
    citations = [v for r in answered for v in r.get("citation_labels", []) if type(v) is bool]
    cost = {}
    for field in ("input_tokens", "output_tokens", "calls", "latency_seconds"):
        values = [r[field] for r in rows if finite_number(r.get(field))]
        cost[field+"_sum"] = sum(values) if values else None
        cost[field+"_reported_rows"] = len(values)
    rc, partial = risk_curve(valid), risk_curve(valid, "answered")
    wrong = sum(r["correct"] is False for r in answered)
    return {"planned_n":len(rows), "n":len(valid), "failed_n":len(rows)-len(valid),
            "completion_rate":ratio(len(valid),len(rows)), "answered_n":len(answered), "wrong_answered_n":wrong,
            "coverage":ratio(len(answered),len(valid)), "selective_risk":ratio(wrong,len(answered)),
            "quality_eligible_n":sum(q[0] is not None for q in qualities), "quality_excluded_n":sum(q[0] is None for q in qualities),
            "em_all_rows":mean(q[0] for q in qualities), "token_f1_all_rows":mean(q[1] for q in qualities),
            "em_answered_only":mean(row_quality(r)[0] for r in answered),
            "token_f1_answered_only":mean(row_quality(r)[1] for r in answered),
            "em_answerable_only":mean(row_quality(r)[0] for r in yes),
            "should_answer_n":len(yes), "should_abstain_n":len(no),
            "unknown_should_answer_n":sum(r["should_answer"] is None for r in valid),
            "inappropriate_answer_rate":ratio(sum(r["answered"] for r in no),len(no)),
            "inappropriate_refusal_rate":ratio(sum(not r["answered"] for r in yes),len(yes)),
            "aurc":rc["area"], "aurc_status":rc["reason"],
            "partial_aurc_answered":partial["area"], "partial_aurc_max_coverage":partial["max_coverage"],
            "replica":replica_metrics(valid), "independent_support_retention":support_retention(valid),
            "evidence_support_rate":ratio(sum(support),len(support)), "evidence_reviewed_n":len(support),
            "citation_precision":ratio(sum(citations),len(citations)), "reviewed_citations_n":len(citations),
            "all_citations_correct_answer_rate":ratio(sum(all_citations),len(all_citations)),
            "all_citations_reviewed_answers_n":len(all_citations), "cost":cost}


def grouped_summaries(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(k) for k in GROUP_FIELDS)].append(row)
    return {"schema_version":"1.0", "group_fields":GROUP_FIELDS, "pooled_metrics":None,
            "groups":[{"slice":dict(zip(GROUP_FIELDS,key)), "metrics":summarize(group)} for key,group in groups.items()],
            "note":"No pooled result across methods, models, splits or conditions."}


def check_manifest(rows, manifest_path):
    manifest = [json.loads(line) for line in Path(manifest_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    expected = {r["run_id"]: r for r in manifest}
    actual = {r["run_id"]: r for r in rows}
    if len(expected) != len(manifest) or set(expected) != set(actual):
        raise ValueError("prediction/manifest run IDs missing, extra or duplicated")
    trace_fields = ("dataset_hash", "split_hash", "config_hash", "model", "model_revision", "method", "condition_id", "seed", "position_seed", "pair_id")
    for run_id, row in actual.items():
        for field in trace_fields:
            if field in expected[run_id] and expected[run_id][field] != row[field]:
                raise ValueError(f"manifest trace mismatch: {run_id}/{field}")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("--output")
    parser.add_argument("--manifest", help="verify complete planned run coverage and version trace")
    args=parser.parse_args()
    try:
        rows=load_jsonl(args.input)
        if args.manifest:
            check_manifest(rows, args.manifest)
        result=grouped_summaries(rows)
        result["manifest_checked"] = bool(args.manifest)
    except (ValueError,OSError,KeyError) as exc:
        print(str(exc),file=sys.stderr)
        return 2
    text=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)
    if args.output:
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        Path(args.output).write_text(text+"\n",encoding="utf-8")
    else:
        print(text)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
