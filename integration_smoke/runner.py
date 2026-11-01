"""Run public-input-only diagnostics; offline gold is read by score_outputs only."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from evaluation.scheduler import digest
from evaluation.validation import load_records
from .backend import claim, predict, prompt, token_count
from .dataset import read_jsonl, write_jsonl
from . import backend


def execute(manifest_path, public_path, journal_path, inject_retry=True):
    manifest = read_jsonl(manifest_path)
    public = {r["input_id"]: r for r in load_records(public_path, "public_input")}
    identity = {"manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "public_sha256": hashlib.sha256(public_path.read_bytes()).hexdigest(),
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "backend_sha256": hashlib.sha256(Path(backend.__file__).read_bytes()).hexdigest(),
                "inject_retry": inject_retry}
    metadata = journal_path.with_suffix(".metadata.json")
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    if metadata.exists():
        if json.loads(metadata.read_text(encoding="utf-8")) != identity:
            raise ValueError("resume input/config/runner changed; use a fresh journal")
    elif journal_path.exists():
        raise ValueError("existing journal has no trusted resume metadata")
    else:
        metadata.write_text(json.dumps(identity, indent=2)+"\n", encoding="utf-8")
    previous = read_jsonl(journal_path) if journal_path.exists() else []
    success_ids = [r["run_id"] for r in previous if r["status"] == "ok"]
    if len(set(success_ids)) != len(success_ids):
        raise ValueError("journal contains duplicate successes")
    planned = {r["run_id"] for r in manifest}
    if any(r["model_revision"] != identity["backend_sha256"] for r in manifest):
        raise ValueError("backend code changed since manifest creation")
    if len(planned) != len(manifest) or {r["run_id"] for r in previous}-planned:
        raise ValueError("duplicate plan or unexpected journal run")
    successful = set(success_ids)
    executed = retries = 0
    with journal_path.open("a", encoding="utf-8") as stream:
        for run in manifest:
            if run["run_id"] in successful:
                continue
            if run["status"] != "planned":
                raise ValueError("blocked manifest entry cannot be executed")
            request = public[run["input_id"]]
            serialized = prompt(request)
            tokens = token_count(serialized)
            if run["length_policy"] == "fixed_token_budget" and tokens != run["fixed_token_budget"]:
                raise ValueError("fixed complete prompt budget mismatch")
            start_attempt = max((r["attempt"] for r in previous if r["run_id"] == run["run_id"]), default=-1)+1
            if start_attempt >= 3:
                raise ValueError("three-attempt limit already reached")
            injected = inject_retry and start_attempt == 0 and int(run["run_id"][:4], 16) % 41 == 0
            for attempt in range(start_attempt, start_attempt+1+int(injected)):
                started = time.perf_counter()
                # Deliberately malformed output is an explicit injected parser failure, not an API call.
                response = "INJECTED_BAD_JSON" if injected and attempt == 0 else json.dumps(predict(request, run["method"]), sort_keys=True)
                status = "parse_error" if response == "INJECTED_BAD_JSON" else "ok"
                record = {"run_id": run["run_id"], "input_id": run["input_id"], "attempt": attempt,
                          "request_hash": digest(serialized), "status": status, "raw_response": response,
                          "backend_calls": 1, "input_tokens": tokens, "output_tokens": token_count(response),
                          "latency_seconds": time.perf_counter()-started,
                          "tokenizer_id": "synthetic-regex-v1-NOT-LLM-TOKENS",
                          "injected_failure": status != "ok"}
                stream.write(json.dumps(record, sort_keys=True)+"\n")
                stream.flush()
                if status == "ok":
                    executed += 1
                else:
                    retries += 1
    return {"executed_runs": executed, "skipped_successful_runs": len(successful), "injected_retry_attempts": retries}


def score_outputs(manifest_path, public_path, gold_path, journal_path, output_path):
    """Offline fixture oracle; labels are algorithmic synthetic truth, not human audits."""
    manifest = read_jsonl(manifest_path)
    public = {r["input_id"]: r for r in read_jsonl(public_path)}
    gold = {r["input_id"]: r for r in read_jsonl(gold_path)}
    attempts = read_jsonl(journal_path)
    groups = {}
    for attempt in attempts:
        groups.setdefault(attempt["run_id"], []).append(attempt)
    rows = []
    for run in manifest:
        log = groups.get(run["run_id"], [])
        successes = [r for r in log if r["status"] == "ok"]
        if len(successes) != 1:
            raise ValueError("require one successful selected attempt per smoke run")
        selected = successes[0]
        output = json.loads(selected["raw_response"])
        truth = gold[run["input_id"]]
        candidate_correct = truth["should_answer"] and output["candidate_answer"] in truth["references"]
        row = dict(run, schema_version="1.0", status="ok", raw_log_id=f"attempts.jsonl#{run['run_id']}:{selected['attempt']}",
                   should_answer=truth["should_answer"], references=truth["references"],
                   correct=bool(candidate_correct) if output["answered"] else None,
                   candidate_task_correct=bool(candidate_correct), **output)
        retained = {truth["evidence_truth"][eid]["gold_group"] for eid in output["retained_evidence_ids"] if eid in truth["evidence_truth"]}
        row.update(gold_independent_support_groups=truth["gold_independent_support_groups"],
                   retained_independent_support_groups=sorted(retained),
                   label_origin="synthetic-construction-oracle-NOT-human-reviewed",
                   calls=sum(a["backend_calls"] for a in log), input_tokens=sum(a["input_tokens"] for a in log),
                   output_tokens=sum(a["output_tokens"] for a in log), latency_seconds=sum(a["latency_seconds"] for a in log))
        # Textual entailment of the cited evidence; this is NOT a real-data citation audit.
        evidence = {e["evidence_id"]: e for e in public[run["input_id"]]["evidence"]}
        labels = []
        for eid in output["cited_evidence_ids"]:
            parsed = claim(evidence[eid]["text"])
            labels.append(bool(parsed and parsed[1] == "color" and parsed[2] == output["prediction"]))
        row["citation_labels"] = labels
        row["citation_correct"] = all(labels) if labels else None
        row["answer_supported"] = any(labels) if output["answered"] else None
        rows.append(row)
    write_jsonl(output_path, rows)
    load_records(output_path)
    return rows
