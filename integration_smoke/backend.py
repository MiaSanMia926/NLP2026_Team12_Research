"""Rule-based backend. Receives public_input only; never reads gold or conditions."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from evaluation.validation import SCHEMA_DIR, validate_schema

METHODS = ("SMOKE_vote", "SMOKE_exact", "SMOKE_source", "SMOKE_gate")
INSTRUCTION = "Read the registry evidence and answer the requested property. Abstention is permitted."
SCHEMA = json.loads((SCHEMA_DIR / "public_input.schema.json").read_text(encoding="utf-8"))


def prompt(public):
    validate_schema(public, SCHEMA)
    # Opaque input/base IDs remain routing fields, not prompt text.
    return INSTRUCTION + "\n" + json.dumps({k: public[k] for k in ("question", "evidence")}, sort_keys=True, ensure_ascii=False)


def token_count(text):
    """Actual tokenizer for this rule backend ONLY; not any LLM's tokenizer."""
    return len(re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE))


def claim(text):
    a = re.fullmatch(r"(Verified|Tentative): (\w+) has (\w+) (\w+)\.", text)
    if a:
        status, entity, prop, value = a.groups()
        return entity, prop, value, status == "Verified"
    b = re.fullmatch(r"(Verified|Tentative) record: the (\w+) of (\w+) is (\w+)\.", text)
    if b:
        status, prop, entity, value = b.groups()
        return entity, prop, value, status == "Verified"
    return None


def predict(public, method):
    validate_schema(public, SCHEMA)
    if method not in METHODS:
        raise ValueError("unknown smoke method")
    query = re.fullmatch(r"What is the (\w+) of (\w+)\?", public["question"])
    if not query:
        raise ValueError("unsupported synthetic question grammar")
    prop, entity = query.groups()
    retained, seen_text = [], set()
    for evidence in public["evidence"]:
        parsed = claim(evidence["text"])
        if not parsed or parsed[:2] != (entity, prop):
            continue
        if method == "SMOKE_gate" and not parsed[3]:
            continue
        normalized = " ".join(evidence["text"].lower().split())
        if method == "SMOKE_exact" and normalized in seen_text:
            continue
        seen_text.add(normalized)
        retained.append((evidence, parsed[2]))
    weights = Counter()
    sources = defaultdict(set)
    for evidence, value in retained:
        source = evidence["visible_metadata"].get("source_id")
        if method == "SMOKE_gate":
            # Unknown is a single uncertainty bucket per candidate, not independent support.
            key = source or "UNKNOWN"
        else:
            key = source or evidence["evidence_id"]
        sources[value].add(key)
        weights[value] += 1
    if method in {"SMOKE_source", "SMOKE_gate"}:
        weights = Counter({value: len(groups) for value, groups in sources.items()})
    ranking = sorted(weights, key=lambda value: (-weights[value], value))
    candidate = ranking[0] if ranking else "unknown"
    total = sum(weights.values())
    score = weights[candidate] / total if total else 0.0
    if method == "SMOKE_gate":
        # Frozen rule, deliberately not a fitted B7 gate.
        score = score if weights[candidate] >= 2 else min(score, .49)
        answered = bool(ranking) and score >= .75
    else:
        answered = bool(ranking)
    return {"candidate_answer": candidate, "selection_score": score, "answered": answered,
            "prediction": candidate if answered else None,
            "retained_evidence_ids": [e["evidence_id"] for e, _ in retained],
            "cited_evidence_ids": [e["evidence_id"] for e, v in retained if answered and v == candidate],
            "source_support_counts": dict(weights)}
