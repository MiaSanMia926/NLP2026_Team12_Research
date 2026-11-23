"""Execute C's bound manifest using only A's public inputs."""

import argparse
import json
import os
import platform
import re
import sqlite3
import sys
import time
from importlib.metadata import version
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from evaluation.manifest import load_manifest
from evaluation.scheduler import ABLATIONS, digest
from evaluation.validation import load_records
from integration_smoke.dataset import read_jsonl, write_jsonl
from . import backend, gates, methods

RUN_FIELDS = (
    "base_question_id", "family_id", "dataset_id", "dataset_version", "dataset_hash",
    "split_hash", "split", "task_type", "experiment_id", "model", "model_revision",
    "method", "metadata_state", "metadata_error_type", "length_policy", "seed",
    "position_seed", "config_hash"
)
MODEL_FIELDS = (
    "experiment_id", "model", "model_revision", "prompt_template_hash",
    "tokenizer_id", "generation", "seed", "position_seed"
)


def runtime_versions(config):
    packages = {"transformers": ("transformers", "torch"),
                "mlx_vlm": ("mlx-vlm", "mlx", "transformers"),
                "openai_compatible": ()}[config["backend"]]
    packages = set(packages)
    if any(config["method_configs"].get(method) for method in ("B3", "B5")):
        packages.add("sentence-transformers")
    return {"python": platform.python_version(), **{p: version(p) for p in sorted(packages)}}


def load_plan(args, config):
    public = {row["input_id"]: row for row in load_records(args.public, "public_input")}
    plan = load_manifest(args.manifest)
    lineage = {}
    if args.oracle_lineage:
        if any(r["method"] != "B6" for r in plan):
            raise ValueError("provide oracle lineage only to a separate B6-only manifest")
        for row in read_jsonl(args.oracle_lineage):
            if set(row) != {"input_id", "evidence_groups"} or row["input_id"] in lineage:
                raise ValueError("oracle input only permits input_id and evidence_groups")
            if not isinstance(row["evidence_groups"], dict):
                raise ValueError("evidence_groups must be an evidence-ID to source-ID mapping")
            lineage[row["input_id"]] = row["evidence_groups"]
    if config["prompt_template_hash"] != methods.PROMPT_HASH:
        raise ValueError("prompt_template_hash does not match current prompts")
    if config["method_code_hash"] != backend.file_hash(methods.__file__):
        raise ValueError("method implementation differs from config")
    if config["runtime"] != runtime_versions(config):
        raise ValueError("runtime package versions do not match config")
    if type(config["max_attempts"]) is not int or config["max_attempts"] < 1:
        raise ValueError("max_attempts must be a positive integer")
    if config["backend"] != "openai_compatible":
        params = config["generation"]
        if (set(params) != {"temperature", "max_tokens"} or type(params["max_tokens"]) is not int
                or params["max_tokens"] < 1 or type(params["temperature"]) not in (int, float)
                or not 0 <= params["temperature"] <= 2):
            raise ValueError("local generation needs max_tokens and temperature")
    artifacts = {}
    for run in plan:
        method, run_id = run["method"], run["run_id"]
        if method not in methods.METHODS or run["status"] != "planned":
            raise ValueError(f"invalid or blocked run {run_id}")
        input_id = run["input_id"]
        if input_id not in public or public[input_id]["base_question_id"] != run["base_question_id"]:
            raise ValueError(f"missing or mismatched public input for {run_id}")
        if method == "B6" and (input_id not in lineage or run.get("input_permission") != "oracle_lineage_only"):
            raise ValueError("B6 expects an explicit oracle plan and separate lineage-only input")
        if method != "B6" and run.get("input_permission") != "public_input_only":
            raise ValueError("practical methods require public_input_only")
        method_config = config["method_configs"].get(method, {})
        if method in ABLATIONS and method_config.get("disabled_features") != [ABLATIONS[method]]:
            raise ValueError(f"invalid ablation config for {method}")
        if (any(config[field] != run[field] for field in MODEL_FIELDS)
                or run["config_hash"] != digest(dict(config, method=method))
                or run["method_config"] != method_config):
            raise ValueError(f"config differs from scheduler for {run_id}")
        identity = {field: run[field] for field in RUN_FIELDS}
        if (digest(identity) != run["pair_id"]
                or digest(dict(identity, replica_condition=run["replica_condition"])) != run_id):
            raise ValueError(f"bad run or pair identity for {run_id}")
        if run["length_policy"] == "fixed_token_budget":
            budget = run["fixed_token_budget"]
            if type(budget) is not int or budget < 1 or budget != config["fixed_token_budget"]:
                raise ValueError(f"invalid fixed budget for {run_id}")
            if config["backend"] == "openai_compatible":
                raise ValueError("fixed-budget plans require the local backend's exact preflight tokenizer")
        if args.collect_gate_features and run["split"] not in {"train", "dev"}:
            raise ValueError("gate feature collection accepts train/dev only")
        if method in methods.GATED and not args.collect_gate_features:
            if method not in artifacts:
                gate_config = method_config.get("gate", {})
                key = gate_config.get("artifact_hash", "")
                if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
                    raise ValueError(f"{method} requires a frozen gate artifact")
                gate = json.loads((args.artifacts / (key + ".json")).read_text())
                if (digest(gate) != key or gate["method"] != method
                        or gate["gate_context"] != gates.gate_context(config, method)
                        or gate["threshold"] != gate_config.get("threshold")
                        or gate_config.get("fit_split") != "train" or gate_config.get("calibration_split") != "dev"):
                    raise ValueError(f"incorrect artifact for {method}")
                artifacts[method] = gate
            if run["split"] == "test" and run["family_id"] in artifacts[method]["family_ids"]:
                raise ValueError("test family overlaps gate training/calibration")
    return [(run, public[run["input_id"]], lineage.get(run["input_id"])) for run in plan], artifacts


def fit_prompt(model, method, payload, target):
    value = methods.prompt(method, payload)
    if target is None:
        return value, 0
    count = model.count(value)
    if count > target:
        raise ValueError(f"prompt has {count} tokens, exceeding fixed budget {target}")
    if count == target:
        return value, 0
    for unit in (" .", " ~", " §"):
        lo, hi = 1, (target - count + 64) * 4
        while lo <= hi:
            n = (hi + lo) // 2
            trial = methods.prompt(method, payload, unit * n)
            actual = model.count(trial)
            if actual == target:
                return trial, n
            if actual < target:
                lo = n + 1
            else:
                hi = n - 1
    raise ValueError(f"could not neutral-pad prompt to exactly {target} tokenizer tokens")


def attempt(run, attempt_index, model, request, payload, groups, padding):
    start = time.perf_counter()
    record = dict(run_id=run["run_id"], attempt=attempt_index, input_id=run["input_id"],
                  request_sha256=digest(request), prompt=request, padding_repetitions=padding,
                  input_tokens=None, output_tokens=None, raw_response=None, provider_response=None,
                  calls=1, started_unix=time.time())
    try:
        content, tokens_in, tokens_out, raw = model.generate(request, run["generation"], run["seed"])
        record.update(raw_response=content, provider_response=raw,
                      input_tokens=tokens_in, output_tokens=tokens_out)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, IndexError) as exc:
        record.update(status="api_error", error=str(exc))
    else:
        try:
            if run["fixed_token_budget"] is not None and tokens_in != run["fixed_token_budget"]:
                record.update(status="blocked_budget", error="backend actual input tokens differ from budget")
            else:
                record.update(status="ok", parsed=methods.parse(run["method"], content, payload, groups))
        except (ValueError, TypeError, AttributeError) as exc:
            record.update(status="parse_error", error=str(exc))
    pricing = getattr(model, "config", {}).get("api_usd_per_million_tokens")
    if pricing is not None:
        tokens = [record[k + "_tokens"] for k in ("input", "output")]
        record["estimated_usd"] = (sum(value * pricing[k] for k, value in zip(("input", "output"), tokens)) / 1e6
                                   if all(value is not None for value in tokens) else None)
    return dict(record, latency_seconds=time.perf_counter() - start)


def atomic_jsonl(path, rows):
    temp = path.with_suffix(".tmp")
    write_jsonl(temp, rows)
    temp.replace(path)


def export(plan, journal, artifacts, output, feature_only):
    by_run = defaultdict(list)
    for record in journal:
        by_run[record["run_id"]].append(record)
    predictions = []
    for run, _, _ in plan:
        records = by_run[run["run_id"]]
        if not records:
            continue
        final = records[-1]
        parsed = final.get("parsed", {})
        answered = parsed.get("answered")
        candidate = parsed.get("candidate_answer")
        citations = parsed.get("candidate_cited_evidence_ids", [])
        selection_score = None
        if final["status"] == "ok" and run["method"] in methods.GATED and not feature_only:
            gate = artifacts[run["method"]]
            selection_score = gates.score(gate, parsed["features"])
            answered = candidate is not None and selection_score >= gate["threshold"]
        latencies = [r["latency_seconds"] for r in records]
        result = dict(run, schema_version="1.0", status=final["status"], answered=answered,
                      candidate_answer=candidate, prediction=candidate if answered else None,
                      candidate_cited_evidence_ids=citations, cited_evidence_ids=citations if answered else [],
                      selection_score=selection_score, retained_evidence_ids=parsed.get("retained_evidence_ids", []),
                      features=parsed.get("features", {}), calls=sum(r["calls"] for r in records),
                      latency_seconds=sum(latencies) if all(v is not None for v in latencies) else None,
                      raw_log_id=f"attempts.jsonl#{run['run_id']}:{final['attempt']}")
        if final["status"] != "ok":
            result["error"] = final.get("error")
        for field in ("input_tokens", "output_tokens"):
            values = [record[field] for record in records]
            result[field] = sum(values) if all(value is not None for value in values) else None
            result["known_" + field] = sum(value for value in values if value is not None)
        charges = [r.get("estimated_usd", 0 if r["calls"] == 0 else None) for r in records]
        if any("estimated_usd" in r for r in records):
            result["estimated_usd"] = sum(charges) if all(v is not None for v in charges) else None
        result["embedding_passages"] = sum(r.get("embedding_passages", 0) for r in records)
        result["preprocess_seconds"] = sum(r.get("preprocess_seconds", 0) for r in records)
        if "gate_context" in final:
            result["gate_context"] = final["gate_context"]
        predictions.append(result)
    atomic_jsonl(output / "attempts.jsonl", journal)
    atomic_jsonl(output / "predictions.jsonl", predictions)
    return predictions


def run(args):
    config = json.loads(args.config.read_text())
    plan, artifacts = load_plan(args, config)
    args.output.mkdir(parents=True, exist_ok=True)
    identity = {key: backend.file_hash(getattr(args, key)) for key in ("manifest", "public", "config")}
    identity.update(runner={p.name: backend.file_hash(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
                    oracle_lineage=backend.file_hash(args.oracle_lineage) if args.oracle_lineage else None,
                    collect_gate_features=args.collect_gate_features)
    with closing(sqlite3.connect(args.output / "lock.sqlite", timeout=0)) as lock:
        lock.execute("BEGIN EXCLUSIVE")
        with closing(sqlite3.connect(args.output / "journal.sqlite")) as db:
            db.execute("CREATE TABLE IF NOT EXISTS metadata (identity TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS attempts (run_id TEXT, n INTEGER, value TEXT, PRIMARY KEY(run_id, n))")
            prior = db.execute("SELECT identity FROM metadata").fetchone()
            serialized = json.dumps(identity, sort_keys=True)
            if prior and prior[0] != serialized:
                raise ValueError("resume config, input or source differs; use a fresh output directory")
            if not prior:
                db.execute("INSERT INTO metadata VALUES (?)", (serialized,))
                db.commit()
            grouped = defaultdict(list)
            for (value,) in db.execute("SELECT value FROM attempts ORDER BY rowid"):
                record = json.loads(value)
                if record["status"] == "in_flight":
                    record.update(status="api_error", error="interrupted call; usage unknown",
                                  latency_seconds=None)
                    save_attempt(db, record, replace=True)
                grouped[record["run_id"]].append(record)
            pending = [(r, p, l) for r, p, l in plan
                       if not grouped[r["run_id"]] or (
                           grouped[r["run_id"]][-1]["status"] in {"api_error", "parse_error"}
                           and len(grouped[r["run_id"]]) < config["max_attempts"])]
            if pending:
                model = backend.ChatBackend(config)
                encoders = {}
                for spec, public, lineage in pending:
                    method, run_id = spec["method"], spec["run_id"]
                    method_config = spec["method_config"]
                    previous = grouped[run_id]
                    context = gates.gate_context(config, method)
                    if method in {"B3", "B5"}:
                        encoder_key = tuple(method_config.get(k) for k in
                                            ("embedding_model", "embedding_revision", "embedding_device"))
                        if encoder_key not in encoders:
                            encoders[encoder_key] = methods.make_encoder(method_config)
                    else:
                        encoder_key = None
                    preprocessing_started = time.perf_counter()
                    payload, groups = methods.prepare(method, public, method_config,
                                                       encoders.get(encoder_key), lineage)
                    preprocessing = dict(preprocess_seconds=time.perf_counter() - preprocessing_started,
                                         embedding_passages=len(public["evidence"]) if encoder_key else 0)
                    try:
                        request, padding = fit_prompt(model, method, payload, spec["fixed_token_budget"])
                    except ValueError as exc:
                        record = dict(run_id=run_id, input_id=spec["input_id"], attempt=len(previous),
                                      status="blocked_budget", calls=0, input_tokens=0, output_tokens=0,
                                      latency_seconds=0, error=str(exc), gate_context=context)
                        save_attempt(db, dict(record, **preprocessing))
                    else:
                        for index in range(len(previous), config["max_attempts"]):
                            reserved = dict(run_id=run_id, input_id=spec["input_id"], attempt=index,
                                            status="in_flight", calls=1, started_unix=time.time(),
                                            input_tokens=None, output_tokens=None, latency_seconds=None,
                                            request_sha256=digest(request), prompt=request,
                                            padding_repetitions=padding, gate_context=context)
                            if index == len(previous):
                                reserved.update(preprocessing)
                            save_attempt(db, reserved)
                            record = attempt(spec, index, model, request, payload, groups, padding)
                            record["gate_context"] = context
                            if index == len(previous):
                                record.update(preprocessing)
                            save_attempt(db, record, replace=True)
                            if record["status"] not in {"api_error", "parse_error"}:
                                break
            journal = [json.loads(r[0]) for r in db.execute("SELECT value FROM attempts ORDER BY rowid")]
            predictions = export(plan, journal, artifacts, args.output, args.collect_gate_features)
    ok = sum(row["status"] == "ok" for row in predictions)
    print(json.dumps(dict(planned=len(plan), ok=ok, failed=len(plan) - ok, attempts=len(journal))))
    return int(ok != len(plan))


def save_attempt(db, record, replace=False):
    payload = json.dumps(record, ensure_ascii=False, allow_nan=False)
    if replace:
        db.execute("UPDATE attempts SET value = ? WHERE run_id = ? AND n = ?",
                   (payload, record["run_id"], record["attempt"]))
    else:
        db.execute("INSERT INTO attempts VALUES (?, ?, ?)", (record["run_id"], record["attempt"], payload))
    db.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "public", "config", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, default=Path("runs/gates"))
    parser.add_argument("--oracle-lineage", type=Path)
    parser.add_argument("--collect-gate-features", action="store_true")
    args = parser.parse_args()
    try:
        return run(args)
    except (OSError, RuntimeError, ValueError, KeyError, ImportError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
