"""Fit method-specific logistic gates on reviewed train candidates, calibrate on dev."""

import argparse
import math
from collections import defaultdict
from pathlib import Path

from evaluation.scheduler import digest
from integration_smoke.dataset import read_jsonl
from .methods import GATED
from .backend import file_hash


def sigmoid(value):
    exp = math.exp(-abs(value))
    return 1 / (1 + exp) if value >= 0 else exp / (1 + exp)


def score(gate, features):
    if set(gate["weights"]) != set(features):
        raise ValueError("gate feature names differ from inference features")
    return sigmoid(gate["bias"] + sum(gate["weights"][key] * value for key, value in features.items()))


def gate_context(config, method):
    method_config = config.get("method_configs", {}).get(method, {})
    return digest({
        "seed": config["seed"],
        "position_seed": config.get("position_seed"),
        "fixed_token_budget": config.get("fixed_token_budget"),
        "model": config["model"],
        "model_revision": config["model_revision"],
        "tokenizer_id": config["tokenizer_id"],
        "prompt_template_hash": config["prompt_template_hash"],
        "generation": config["generation"],
        "backend": config["backend"],
        "runtime": config["runtime"],
        "method_code_hash": config["method_code_hash"],
        "method_config": {key: value for key, value in method_config.items() if key != "gate"},
    })


def fit(method, rows, reviews, risk_limit, config):
    if not 0 <= risk_limit <= 1:
        raise ValueError("risk limit must be in [0,1]")
    families, partitions = {}, defaultdict(list)
    ids, provenance = set(), set()
    context = gate_context(config, method)
    for row in rows:
        if row["method"] != method:
            continue
        if row["split"] not in {"train", "dev"}:
            raise ValueError("gate fitting accepts only train/dev data")
        run_id, family, split = row["run_id"], row["family_id"], row["split"]
        if run_id in ids or families.setdefault(family, split) != split:
            raise ValueError("duplicate run or train/dev family overlap")
        if row["gate_context"] != context:
            raise ValueError("gate feature provenance differs from current config")
        ids.add(run_id)
        provenance.add((row["dataset_hash"], row["split_hash"]))
        if row["status"] != "ok":
            raise ValueError(f"unresolved execution failure in gate data: {run_id}")
        candidate = row["candidate_answer"]
        label = reviews.get(run_id, {}).get("candidate_task_correct")
        if (candidate is not None and type(label) is not bool) or (candidate is None and label is not None):
            raise ValueError(f"reviewed candidate label mismatch for {run_id}")
        partitions[split].append((row["features"], candidate is not None, label))
    if len(provenance) != 1:
        raise ValueError("gate data must come from a single dataset/split version")
    training = [(features, label) for features, viable, label in partitions["train"] if viable]
    if {label for _, label in training} != {False, True} or not partitions["dev"]:
        raise ValueError("need both reviewed classes in train and at least one dev run")
    keys = sorted(training[0][0])
    if any(sorted(features) != keys for partition in partitions.values() for features, _, _ in partition):
        raise ValueError("incompatible gate feature sets")
    bias, weights = 0.0, dict.fromkeys(keys, 0.0)
    for _ in range(400):
        errors = [sigmoid(bias + sum(weights[k] * features[k] for k in keys)) - label
                  for features, label in training]
        bias -= 0.2 * sum(errors) / len(training)
        for key in keys:
            grad = sum(error * features[key] for error, (features, _) in zip(errors, training))
            weights[key] -= 0.2 * (grad / len(training) + 0.01 * weights[key])
    model = dict(method=method, gate_context=context, bias=bias, weights=weights,
                 fit_split="train", calibration_split="dev", risk_limit=risk_limit,
                 train_n=len(partitions["train"]), train_labeled_n=len(training),
                 dev_n=len(partitions["dev"]), train_dev_dataset_hash=next(iter(provenance))[0],
                 train_dev_split_hash=next(iter(provenance))[1], family_ids=sorted(families))
    groups = defaultdict(list)
    for features, viable, label in partitions["dev"]:
        if viable:
            groups[score(model, features)].append(label)
    accepted = mistakes = 0
    model.update(threshold=2.0, dev_accepted=0, dev_risk=None, dev_coverage=0.0)
    for threshold in sorted(groups, reverse=True):
        accepted += len(groups[threshold])
        mistakes += sum(not label for label in groups[threshold])
        if mistakes / accepted <= risk_limit:
            model.update(threshold=threshold, dev_accepted=accepted, dev_risk=mistakes / accepted,
                         dev_coverage=accepted / len(partitions["dev"]))
    return model


def main():
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", required=True, choices=sorted(GATED))
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--risk-limit", type=float, default=0.1)
    args = parser.parse_args()
    review_rows = read_jsonl(args.reviews)
    reviews = {r["run_id"]: r for r in review_rows}
    if len(reviews) != len(review_rows):
        parser.error("duplicate review run IDs")
    try:
        config = json.loads(args.config.read_text())
        gate = fit(args.method, read_jsonl(args.predictions), reviews, args.risk_limit, config)
        gate["predictions_sha256"] = file_hash(args.predictions)
        gate["reviews_sha256"] = file_hash(args.reviews)
        artifact_hash = digest(gate)
        args.artifacts.mkdir(parents=True, exist_ok=True)
        path = args.artifacts / (artifact_hash + ".json")
        path.write_text(json.dumps(gate, indent=2, allow_nan=False) + "\n")
        print(json.dumps({"method": args.method, "artifact_hash": artifact_hash,
                          "fit_split": "train", "calibration_split": "dev", "threshold": gate["threshold"],
                          "dev_n": gate["dev_n"], "dev_coverage": gate["dev_coverage"], "dev_risk": gate["dev_risk"]}))
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
