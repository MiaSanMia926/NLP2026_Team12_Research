"""Cross-module invariants of the offline A/B scaffold and C integration."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from evaluation.metrics import check_manifest, summarize
from evaluation.scheduler import digest
from integration_smoke.backend import predict, prompt, token_count
from integration_smoke.dataset import build_dataset, read_jsonl, variant, write_jsonl
from integration_smoke.runner import execute, score_outputs
from integration_smoke.run import probes

ROOT = Path(__file__).resolve().parents[1]


class SmokeTests(unittest.TestCase):
    def test_checked_in_examples_match_public_schema_and_separate_gold(self):
        from evaluation.validation import load_records
        folder = ROOT/"integration_smoke/examples"
        public = load_records(folder/"public_inputs.jsonl", "public_input")
        questions = load_records(folder/"questions.jsonl", "question")
        gold = read_jsonl(folder/"gold.jsonl")
        self.assertEqual((len(questions), len(public), len(gold)), (4, 8, 8))
        self.assertEqual({r["input_id"] for r in public}, {r["input_id"] for r in gold})
        self.assertEqual({r["base_question_id"] for r in public}, {r["base_question_id"] for r in questions})
        self.assertEqual({r["case"] for r in gold}, {"consistent", "wrong_counterevidence", "unresolved_conflict", "insufficient"})
        self.assertEqual(questions[0]["dataset_hash"], digest({"public_inputs": public, "gold": gold}))

    def test_backend_rejects_gold_and_condition_fields(self):
        public, gold = variant(0, "no_replica", "complete", "split_same_source")
        for key, value in (("references", gold["references"]), ("metadata_state", "complete"), ("should_answer", True)):
            with self.assertRaises(ValueError):
                predict(dict(public, **{key: value}), "SMOKE_gate")

    def test_predictions_depend_on_evidence_not_identifiers(self):
        public, _ = variant(0, "no_replica", "complete", "split_same_source")
        altered = dict(public, input_id="arbitrary", base_question_id="arbitrary")
        self.assertEqual(predict(public, "SMOKE_gate"), predict(altered, "SMOKE_gate"))
        self.assertEqual(prompt(public), prompt(altered))

    def test_replication_can_flip_vote_but_gate_retains_correct_candidate(self):
        a, truth = variant(1, "no_replica", "complete", "split_same_source")
        b, _ = variant(1, "same_source_replica", "complete", "split_same_source")
        self.assertIn(predict(a, "SMOKE_vote")["prediction"], truth["references"])
        self.assertNotIn(predict(b, "SMOKE_vote")["prediction"], truth["references"])
        self.assertIn(predict(b, "SMOKE_gate")["prediction"], truth["references"])

    def test_conflict_and_missing_metadata_produce_abstentions(self):
        for i, meta in ((2, "complete"), (0, "missing")):
            public, _ = variant(i, "no_replica", meta, "split_same_source")
            result = predict(public, "SMOKE_gate")
            self.assertFalse(result["answered"])
            self.assertIsNone(result["prediction"])
            self.assertIsNotNone(result["candidate_answer"])

    def test_exact_text_dedup_can_remove_independent_support(self):
        public, _ = variant(0, "independent_support", "complete", "split_same_source")
        self.assertEqual(len(predict(public, "SMOKE_exact")["retained_evidence_ids"]), 1)
        self.assertEqual(len(predict(public, "SMOKE_gate")["retained_evidence_ids"]), 3)

    def test_complete_data_runner_scoring_resume_and_fault_probes(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".eval-test-") as tmp:
            directory = Path(tmp)
            info = build_dataset(directory/"data", count=8)
            self.assertEqual(info["planned_runs"], 768)
            public = read_jsonl(directory/"data/public_inputs.jsonl")
            gold = read_jsonl(directory/"data/gold.jsonl")
            questions = read_jsonl(directory/"data/questions.jsonl")
            self.assertEqual(questions[0]["dataset_hash"], digest({"public_inputs": public, "gold": gold}))
            fixed = [r for r in public if any(e["evidence_id"] == "padding" for e in r["evidence"])]
            self.assertTrue(all(token_count(prompt(r)) == info["budget"] for r in fixed))
            manifest, inputs = directory/"data/manifest.jsonl", directory/"data/public_inputs.jsonl"
            journal = directory/"logs/attempts.jsonl"
            first = execute(manifest, inputs, journal)
            self.assertGreater(first["injected_retry_attempts"], 0)
            before = journal.read_bytes()
            resumed = execute(manifest, inputs, journal)
            self.assertEqual(resumed["executed_runs"], 0)
            self.assertEqual(journal.read_bytes(), before)
            rows = score_outputs(manifest, inputs, directory/"data/gold.jsonl", journal, directory/"scored.jsonl")
            check_manifest(rows, manifest)
            self.assertEqual(len(rows), 768)
            self.assertEqual(sum(r["calls"] for r in rows), 768+first["injected_retry_attempts"])
            self.assertTrue(all(r["method"].startswith("SMOKE_") for r in rows))
            self.assertEqual(len(probes(rows, manifest, directory/"probes")), 6)
            changed = read_jsonl(inputs)
            changed[0]["question"] += "Changed"
            write_jsonl(inputs, changed)
            with self.assertRaises(ValueError):
                execute(manifest, inputs, journal)

    def test_neutral_padding_does_not_change_rule_output(self):
        public, _ = variant(0, "no_replica", "complete", "split_same_source")
        padded = copy.deepcopy(public)
        padded["evidence"].append({"evidence_id": "padding", "text": ". . .", "visible_metadata": {"source_id": None}})
        self.assertEqual(predict(public, "SMOKE_gate"), predict(padded, "SMOKE_gate"))


if __name__ == "__main__":
    unittest.main()
