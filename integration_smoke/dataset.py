"""Construct fictional questions, evidence variants and SEPARATE offline gold."""
from __future__ import annotations

import hashlib
import itertools
import json
import random
from pathlib import Path

from evaluation.scheduler import digest, make_manifest
from evaluation.validation import load_records
from .backend import INSTRUCTION, METHODS, prompt, token_count

PANELS = ("no_replica", "same_source_replica", "independent_support", "complementary_support")
CASES = ("consistent", "wrong_counterevidence", "unresolved_conflict", "insufficient")


def opaque(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:20]


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True, allow_nan=False)+"\n" for r in rows), encoding="utf-8")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def variant(index, panel, metadata, recipe):
    entity = "Object" + opaque(index)[:8]
    values = ("amber", "blue", "coral", "green", "ivory", "violet")
    correct, wrong = values[index % 6], values[(index+1) % 6]
    case = CASES[index % 4]
    # Internal tuples are construction truth; only the rendered evidence becomes public.
    facts = []
    def add(value, group, status="Verified", prop="color", paraphrase=False):
        text = (f"{status} record: the {prop} of {entity} is {value}." if paraphrase else
                f"{status}: {entity} has {prop} {value}.")
        facts.append((text, group, value, prop, status))
    if case in {"consistent", "wrong_counterevidence"}:
        add(correct, "a")
        add(correct, "b")
        if case == "wrong_counterevidence":
            add(wrong, "c", "Tentative")
    elif case == "unresolved_conflict":
        add(correct, "a")
        add(wrong, "c")
    else:
        add(correct, "a", prop="shape")
    if panel == "same_source_replica":
        original = facts[-1]
        for j in range(4):
            add(original[2], original[1], original[4], original[3], paraphrase=(index+j) % 2 == 1)
    elif panel == "independent_support":
        add(correct, "new")
    elif panel == "complementary_support":
        # A second property plus an explicit implication; the toy backend does not reason over implications.
        add(correct, "new", prop="pigment")
        facts.append((f"Rule: {entity} has color equal to its pigment.", "rule", correct, "implication", "Verified"))
    public_evidence, oracle = [], {}
    for n, (text, group, value, prop, status) in enumerate(facts):
        eid = "e" + opaque(index, panel, n)
        gold_group = "g" + opaque(index, group)
        visible = "s" + opaque(index, group)
        if metadata == "missing":
            visible = None
        elif metadata == "incorrect":
            visible = "s" + opaque(index, n) if recipe == "split_same_source" else "s" + opaque(index, "merged")
        public_evidence.append({"evidence_id": eid, "text": text, "visible_metadata": {"source_id": visible}})
        oracle[eid] = {"gold_group": gold_group, "value": value, "property": prop, "verified": status == "Verified"}
    random.Random(int(opaque(index, panel, "position"), 16)).shuffle(public_evidence)
    public = {"schema_version": "1.0", "input_id": "i"+opaque(index, panel, metadata),
              "base_question_id": "q"+opaque(index), "question": f"What is the color of {entity}?", "evidence": public_evidence}
    should_answer = case in {"consistent", "wrong_counterevidence"} or (case == "insufficient" and panel in {"independent_support", "complementary_support"})
    supports = sorted({r["gold_group"] for r in oracle.values() if r["value"] == correct and r["property"] in {"color", "pigment", "implication"} and r["verified"]}) if should_answer else []
    gold = {"input_id": public["input_id"], "case": case, "should_answer": should_answer,
            "references": [correct] if should_answer else [], "evidence_truth": oracle,
            "gold_independent_support_groups": supports}
    return public, gold


def build_dataset(directory, count=12, seed=20261031):
    if count < 8 or count % 4:
        raise ValueError("count must be a multiple of four, at least eight")
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("dataset directory must be new or empty")
    questions, inputs, golds, index_rows = [], [], [], []
    registry_hash = digest({"generator": "synthetic-registry-v1", "count": count, "seed": seed,
                            "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    split_hash = digest({i: "train" if i < 4 else "dev" for i in range(count)})
    lookup = {}
    for i in range(count):
        recipe = "split_same_source" if (i//4) % 2 == 0 else "merge_independent_sources"
        q = {"base_question_id": "q"+opaque(i), "family_id": "f"+opaque(i),
             "dataset_id": "SYNTHETIC_AB_SMOKE_ONLY", "dataset_version": "v1", "dataset_hash": registry_hash,
             "split_hash": split_hash, "split": "train" if i < 4 else "dev", "task_type": "evidence_constrained_qa",
             "incorrect_metadata_error_type": recipe}
        questions.append(q)
        for panel, meta in itertools.product(PANELS, ("complete", "missing", "incorrect")):
            public, gold = variant(i, panel, meta, recipe)
            inputs.append(public)
            golds.append(gold)
            lookup[(q["base_question_id"], panel, meta, "natural_length")] = public["input_id"]
    # Use the declared synthetic regex tokenizer on the COMPLETE serialized prompt.
    budget = max(token_count(prompt(public)) for public in inputs) + 64
    natural_inputs = list(inputs)
    gold_lookup = {g["input_id"]: g for g in golds}
    for public in natural_inputs:
        fixed = json.loads(json.dumps(public))
        fixed["input_id"] = "i"+opaque(public["input_id"], "budget")
        fixed["evidence"].append({"evidence_id": "padding", "text": ".", "visible_metadata": {"source_id": None}})
        remaining = budget-token_count(prompt(fixed))
        fixed["evidence"][-1]["text"] += " ." * remaining
        assert token_count(prompt(fixed)) == budget
        inputs.append(fixed)
        golds.append(dict(gold_lookup[public["input_id"]], input_id=fixed["input_id"]))
    content_hash = digest({"public_inputs": inputs, "gold": golds})
    for q in questions:
        q["dataset_hash"] = content_hash
    for (qid, panel, meta, _), input_id in list(lookup.items()):
        lookup[(qid, panel, meta, "fixed_token_budget")] = "i"+opaque(input_id, "budget")
    config = {"experiment_id": "offline-ab-c-smoke", "model": "REGEX_RULE_BACKEND_NOT_LLM",
              "model_revision": hashlib.sha256((Path(__file__).parent/"backend.py").read_bytes()).hexdigest(),
              "prompt_template_hash": digest(INSTRUCTION), "tokenizer_id": "synthetic-regex-v1-NOT-LLM-TOKENS",
              "generation": {"deterministic": True}, "seed": seed, "position_seed": 0, "fixed_token_budget": budget,
              "generator_recipe_hash": registry_hash}
    scaffold = make_manifest(questions, config, methods=["B0", "B1", "B2", "B3"], replica_conditions=PANELS)
    manifest = []
    for row in scaffold:
        # Reuse C's factorial scheduler, then bind explicitly named diagnostic algorithms.
        row["method"] = METHODS[int(row["method"][1:])]
        row["config_hash"] = digest(dict(config, method=row["method"]))
        identity = {k: row[k] for k in ("base_question_id", "family_id", "dataset_id", "dataset_version", "dataset_hash", "split_hash", "split", "task_type", "experiment_id", "model", "model_revision", "method", "metadata_state", "metadata_error_type", "length_policy", "seed", "position_seed", "config_hash")}
        row["pair_id"] = digest(identity)
        row["run_id"] = digest(dict(identity, replica_condition=row["replica_condition"]))
        input_id = lookup[(row["base_question_id"], row["replica_condition"], row["metadata_state"], row["length_policy"])]
        row["input_id"] = input_id
        index_rows.append({"run_id": row["run_id"], "input_id": input_id})
        manifest.append(row)
    directory.mkdir(parents=True, exist_ok=True)
    for name, rows in (("questions", questions), ("public_inputs", inputs), ("gold", golds), ("input_index", index_rows), ("manifest", manifest)):
        write_jsonl(directory/(name+".jsonl"), rows)
    (directory/"config.json").write_text(json.dumps(config, indent=2)+"\n", encoding="utf-8")
    load_records(directory/"questions.jsonl", "question")
    load_records(directory/"public_inputs.jsonl", "public_input")
    return {"base_questions": count, "public_inputs": len(inputs), "planned_runs": len(manifest), "budget": budget}
