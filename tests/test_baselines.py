import json
import re
import tempfile
import unittest
from argparse import Namespace
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from baselines import backend, gates, methods, runner
from baselines.review import join
from evaluation.manifest import audit_manifest
from evaluation.scheduler import ABLATIONS, CORE_METHODS, make_manifest
from integration_smoke.dataset import build_dataset, read_jsonl, write_jsonl


class FakeBackend:
    remaining_parse_failures = 1

    def __init__(self, config):
        self.config = config

    def count(self, text):
        return len(re.findall(r"\w+|[^\w\s]", text))

    def generate(self, prompt, params, seed):
        payload = json.loads(prompt[prompt.rindex('\n') + 1:])
        ids = [p["evidence_id"] for p in payload["evidence"]]
        result = {"candidate_answer": "blue"}
        if FakeBackend.remaining_parse_failures:
            FakeBackend.remaining_parse_failures -= 1
            content = "malformed"
        else:
            if methods.GATE in prompt:
                result.update(confidence=0.8, sufficiency=0.7, support_ids=ids[:1], conflict_ids=ids[1:2])
            else:
                result.update(answered=bool(ids), cited_evidence_ids=ids[:1])
            content = json.dumps(result)
        return content, self.count(prompt), self.count(content), None


class FakeEncoder:
    def encode(self, texts, **kwargs):
        class Unit:
            def __matmul__(self, other):
                return 1.0
        return [Unit() for _ in texts]


class BaselinesTest(unittest.TestCase):
    def test_preserve_independent_and_complementary_evidence(self):
        def passage(key, source, text):
            return {"evidence_id": key, "visible_metadata": {"source_id": source}, "text": text}
        public = {"question": "Question?", "evidence": [
            passage("a", "one", "Same fact."),
            passage("b", "one", "Same fact."),
            passage("c", "two", "Same fact."),
            passage("d", "one", "Complementary fact."),
            passage("e", None, "Same fact."),
        ]}
        b7, groups = methods.prepare("B7", public, {})
        self.assertEqual([e["evidence_id"] for e in b7["evidence"]], ["a", "c", "d", "e"])
        prediction = methods.parse("B7", json.dumps({
            "candidate_answer": "value", "confidence": 0.8, "sufficiency": 0.9,
            "support_ids": ["a", "c", "d", "e"], "conflict_ids": [],
        }), b7, groups)
        self.assertEqual(prediction["features"]["known_support_groups"], 2 / 3)
        self.assertEqual(prediction["features"]["unknown_support"], 1)
        no_source, _ = methods.prepare("B7_no_source", public, {})
        self.assertEqual([e["evidence_id"] for e in no_source["evidence"]], ["a", "d"])

    def test_gate_no_coverage_and_fit_isolation(self):
        config = {"seed": 0, "model": "FAKE", "model_revision": "mock",
                  "tokenizer_id": "mock", "backend": "openai_compatible", "runtime": {},
                  "generation": {}, "method_configs": {}, "prompt_template_hash": methods.PROMPT_HASH,
                  "method_code_hash": backend.file_hash(methods.__file__)}
        ctx = gates.gate_context(config, "B7")
        rows = [dict(run_id=str(i), family_id=str(i), split="train" if i < 2 else "dev",
                     dataset_hash="x", split_hash="y", method="B7", status="ok",
                     candidate_answer="test", features={"confidence": i / 3}, gate_context=ctx)
                for i in range(4)]
        labels = {str(i): {"candidate_task_correct": i == 1} for i in range(4)}
        gate = gates.fit("B7", rows, labels, 0.1, config)
        self.assertEqual(gate["dev_accepted"], 0)
        self.assertGreater(gate["threshold"], 1)
        rows[2]["family_id"] = rows[0]["family_id"]
        with self.assertRaisesRegex(ValueError, "overlap"):
            gates.fit("B7", rows, labels, 0.1, config)

    def test_all_methods_and_manifest_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_dataset(root / "fixture", 8)
            questions = read_jsonl(root / "fixture/questions.jsonl")
            public_path = root / "fixture/public_inputs.jsonl"
            gold = {row["input_id"]: row for row in read_jsonl(root / "fixture/gold.jsonl")}
            source_plan = read_jsonl(root / "fixture/manifest.jsonl")
            index = {(r["base_question_id"], r["replica_condition"], r["metadata_state"], r["length_policy"]):
                     r["input_id"] for r in source_plan}
            config_path, manifest = root / "config.json", root / "manifest.jsonl"
            config = dict(experiment_id="b-validation-fixture", backend="transformers", model="FAKE_TEST_BACKEND",
                          model_revision="mock", tokenizer_id="mock", prompt_template_hash=methods.PROMPT_HASH,
                          method_code_hash=backend.file_hash(methods.__file__), runtime={},
                          generation={"temperature": 0, "max_tokens": 256}, seed=1, position_seed=0,
                          fixed_token_budget=500, max_attempts=2, method_configs={
                              "B3": {"semantic_threshold": 0.85}, "B5": {"semantic_threshold": 0.85},
                              **{method: {"disabled_features": [feature]} for method, feature in ABLATIONS.items()}
                          })
            artifacts = root / "gates"
            artifacts.mkdir()

            def plan(config, selected, collect=False, oracle=False, length="natural_length"):
                runs = make_manifest(questions, config, selected, include_oracle=oracle,
                                     collect_gate_features=collect, replica_conditions=["no_replica"])
                return [dict(r, input_id=index[(r["base_question_id"], r["replica_condition"],
                                               r["metadata_state"], r["length_policy"])])
                        for r in runs if r["metadata_state"] == "complete" and r["length_policy"] == length]

            def execute(cfg, specs, destination, collect=False, oracle_path=None):
                c, m = config_path.with_stem(destination + "-config"), manifest.with_stem(destination + "-manifest")
                c.write_text(json.dumps(cfg))
                write_jsonl(m, specs)
                args = Namespace(config=c, manifest=m, public=public_path, output=root / destination,
                                 artifacts=artifacts, collect_gate_features=collect, oracle_lineage=oracle_path)
                with redirect_stdout(StringIO()):
                    self.assertEqual(runner.run(args), 0)
                return args, read_jsonl(args.output / "predictions.jsonl")

            practical = CORE_METHODS + list(ABLATIONS)
            calibration_methods = sorted(methods.GATED)
            with patch.object(runner, "runtime_versions", return_value={}), \
                 patch.object(backend, "ChatBackend", FakeBackend), \
                 patch.object(methods, "make_encoder", return_value=FakeEncoder()):
                FakeBackend.remaining_parse_failures = 1
                _, features = execute(config, plan(config, [
                    m for m in calibration_methods if m != "B6"], True), "features", True)
                oracle_specs = plan(config, ["B6"], True, True)
                oracle = root / "oracle.jsonl"
                write_jsonl(oracle, [{"input_id": spec["input_id"], "evidence_groups": {
                    eid: v["gold_group"] for eid, v in gold[spec["input_id"]]["evidence_truth"].items()}}
                    for spec in oracle_specs])
                _, oracle_features = execute(config, oracle_specs, "oracle-features", True, oracle)
                features += oracle_features
                reviews = {}
                # Ensure both classes occur per method in its train partition.
                for method in calibration_methods:
                    for i, row in enumerate(r for r in features if r["method"] == method):
                        reviews[row["run_id"]] = {"candidate_task_correct": i % 2 == 0}
                final_config = deepcopy(config)
                for method in calibration_methods:
                    gate = gates.fit(method, features, reviews, 1.0, config)
                    key = runner.digest(gate)
                    (artifacts / (key + ".json")).write_text(json.dumps(gate))
                    final_config["method_configs"].setdefault(method, {})["gate"] = {
                        "artifact_hash": key, "threshold": gate["threshold"], "fit_split": "train",
                        "calibration_split": "dev",
                    }

                args, predictions = execute(final_config, plan(final_config, practical), "final")
                with redirect_stdout(StringIO()):
                    self.assertEqual(runner.run(args), 0)  # No repeats on resume.
                self.assertEqual(len(read_jsonl(args.output / "attempts.jsonl")), 80)
                reviews = {r["run_id"]: {"candidate_task_correct": False, "label_origin": "synthetic-test"}
                           for r in predictions}
                reviewed = join(predictions, gold, reviews)
                self.assertEqual(audit_manifest(reviewed, args.manifest)["status"], "complete")
                self.assertTrue(all(r["selection_score"] is None for r in reviewed if r["method"] in {"B0", "B1", "B2", "B3"}))
                self.assertTrue(all(r["selection_score"] is not None for r in reviewed if r["method"] in methods.GATED))
                _, oracle_predictions = execute(final_config, plan(final_config, ["B6"], oracle=True),
                                                "oracle-final", oracle_path=oracle)
                self.assertTrue(all(r["oracle"] for r in oracle_predictions))
                fixed, _ = execute(final_config, plan(final_config, ["B0"], length="fixed_token_budget"), "fixed")
                self.assertEqual({r["input_tokens"] for r in read_jsonl(fixed.output / "attempts.jsonl")}, {500})
