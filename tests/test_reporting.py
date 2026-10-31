"""Scientific integration checks for C handoff; fixtures are not experiment data."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evaluation.metrics import grouped_summaries, check_manifest
from evaluation.bootstrap import paired_bootstrap
from evaluation.normalize_input import convert_record
from evaluation.report import build_report, compare
from evaluation.scheduler import ABLATIONS, make_manifest
from evaluation.validation import load_records

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "evaluation/examples"


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.rows = load_records(EXAMPLES / "predictions.jsonl")
        self.questions = load_records(EXAMPLES / "questions.jsonl", "question")
        self.config = json.loads((EXAMPLES / "manifest_config.json").read_text())

    def test_sliced_comparison_has_hand_computed_delta_and_replica_ci(self):
        results = compare(self.rows, "B7", "B5", 40, 7)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["status"] == "ok" for r in results))
        coverage = [s for r in results for s in r["statistics"] if s["metric"] == "coverage"]
        self.assertEqual([s["observed_difference"] for s in coverage], [-.5, -.5])
        replica = compare(self.rows, "B7", "B5", 40, 7, replica=True)
        self.assertEqual(len(replica), 1)
        self.assertEqual(replica[0]["statistics"][0]["ci_95"], [0, 0])

    def test_missing_method_rows_are_explicit_and_not_compared(self):
        results = compare(self.rows[:-1], "B7", "B5", 10, 7)
        bad = [r for r in results if r["status"] != "ok"]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["missing_from_a"], ["fixture_q2"])
        self.assertEqual(bad[0]["statistics"], [])

    def test_replica_requires_both_conditions(self):
        rows = [r for r in self.rows if r["replica_condition"] == "no_replica"]
        result = compare(rows, "B7", "B5", 10, 7, replica=True)
        self.assertEqual(result[0]["status"], "not_comparable")

    def test_hash_and_position_mismatch_cannot_be_pooled(self):
        for field, value in (("dataset_hash", "f"*64), ("position_seed", 42)):
            rows = copy.deepcopy(self.rows)
            rows[0][field] = value
            with self.assertRaises(ValueError):
                paired_bootstrap(rows, replicates=10)
        rows = copy.deepcopy(self.rows)
        rows[0]["dataset_hash"] = "f"*64
        self.assertEqual(len(grouped_summaries(rows)["groups"]), 5)

    def test_manifest_rejects_wrong_condition_and_duplicate_prediction(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".eval-test-") as tmp:
            path = Path(tmp) / "manifest.jsonl"
            path.write_text("".join(json.dumps(r)+"\n" for r in self.rows), encoding="utf-8")
            changed = copy.deepcopy(self.rows)
            changed[0]["replica_condition"] = "independent_support"
            with self.assertRaises(ValueError):
                check_manifest(changed, path)
            with self.assertRaises(ValueError):
                check_manifest(self.rows+[self.rows[0]], path)

    def test_bundle_has_provenance_slices_and_no_silent_overwrite(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".eval-test-") as tmp:
            output = Path(tmp) / "bundle"
            result = build_report(EXAMPLES / "predictions.jsonl", output, replicates=10)
            self.assertEqual(result["manifest_status"], "unverified")
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(len(summary["groups"]), 4)
            provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(len(provenance["input_sha256"]), 64)
            self.assertIn("report.py", provenance["code_sha256"])
            with self.assertRaises(ValueError):
                build_report(EXAMPLES / "predictions.jsonl", output, replicates=10)

    def test_incomplete_manifest_bundle_records_missing_runs(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".eval-test-") as tmp:
            path = Path(tmp) / "manifest.jsonl"
            path.write_text("".join(json.dumps(r)+"\n" for r in self.rows+[dict(self.rows[0], run_id="missing-run")]), encoding="utf-8")
            output = Path(tmp) / "bundle"
            result = build_report(EXAMPLES / "predictions.jsonl", output, path, replicates=10)
            self.assertEqual(result["manifest_status"], "incomplete")
            audit = json.loads((output / "manifest_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["missing_run_ids"], ["missing-run"])

    def test_frozen_test_requires_manifest_and_test_split(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".eval-test-") as tmp:
            with self.assertRaises(ValueError):
                build_report(EXAMPLES / "predictions.jsonl", Path(tmp) / "bundle", label="frozen-test")
            manifest = Path(tmp) / "manifest.jsonl"
            manifest.write_text("".join(json.dumps(r)+"\n" for r in self.rows), encoding="utf-8-sig")
            with self.assertRaises(ValueError):
                build_report(EXAMPLES / "predictions.jsonl", Path(tmp) / "bundle", manifest, label="frozen-test")

    def test_ablations_block_until_independently_calibrated_and_versioned(self):
        rows = make_manifest(self.questions, self.config, include_ablations=True)
        ablations = [r for r in rows if r["method"] in ABLATIONS]
        self.assertEqual(len(ablations), 72)
        self.assertTrue(all(r["status"] == "blocked" for r in ablations))
        config = copy.deepcopy(self.config)
        config["method_configs"] = {method: {"disabled_features": [feature], "gate": {
            "fit_split": "train", "calibration_split": "dev", "artifact_hash": str(i)*64,
            "threshold": .5}} for i, (method, feature) in enumerate(ABLATIONS.items(), 1)}
        ready = make_manifest(self.questions, config, methods=list(ABLATIONS))
        self.assertTrue(all(r["status"] == "planned" for r in ready))
        changed = copy.deepcopy(config)
        changed["method_configs"]["B7_no_source"]["gate"]["threshold"] = .6
        self.assertNotEqual(ready[0]["run_id"], make_manifest(self.questions, changed, methods=list(ABLATIONS))[0]["run_id"])
        reused = copy.deepcopy(config)
        reused["method_configs"]["B7_no_unknown"]["gate"]["artifact_hash"] = "1"*64
        reused_rows = make_manifest(self.questions, reused, methods=["B7_no_source", "B7_no_unknown"])
        self.assertTrue(all("gate_artifact_reused_across_variants" in r["blocked_reasons"] for r in reused_rows))

    def test_h3_panels_are_opt_in_and_have_distinct_ids(self):
        rows = make_manifest(self.questions, self.config, methods=["B7"], replica_conditions=["independent_support", "complementary_support"])
        self.assertEqual(len(rows), 24)
        self.assertEqual(len({r["run_id"] for r in rows}), 24)
        with self.assertRaises(ValueError):
            make_manifest(self.questions, self.config, replica_conditions=["no_replica", "no_replica"])

    def test_normalizer_accepts_full_contract_nulls_and_rejects_partial_exports(self):
        for row in self.rows:
            result, errors, _ = convert_record(row, {}, None, False, False)
            self.assertEqual(errors, [])
            self.assertEqual(result, row)
        external = dict(self.rows[0], task_type="factual_qa", should_answer=None, references=[])
        self.assertEqual(convert_record(external, {}, None, False, False)[1], [])
        failed = dict(self.rows[0], status="api_error", answered=None, prediction=None, correct=None, selection_score=None)
        self.assertEqual(convert_record(failed, {}, None, False, False)[1], [])
        self.assertTrue(convert_record({"prediction": "x"}, {}, None, False, False)[1])
        self.assertTrue(convert_record(dict(self.rows[0], calls=1.5), {}, None, False, False)[1])

    def test_normalizer_cli_and_cross_record_checks(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".eval-test-") as tmp:
            output = Path(tmp) / "canonical.jsonl"
            command = [sys.executable, "-m", "evaluation.normalize_input", str(EXAMPLES / "predictions.jsonl"), "--output", str(output)]
            run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(load_records(output), self.rows)
            bad = Path(tmp) / "duplicate.jsonl"
            bad.write_text(json.dumps(self.rows[0])+"\n"+json.dumps(self.rows[0])+"\n", encoding="utf-8")
            invalid_output = Path(tmp) / "bad.jsonl"
            command[3] = str(bad)
            command[-1] = str(invalid_output)
            run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertFalse(invalid_output.exists())

    def test_report_cli_marks_incomplete_manifest_as_failure(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".eval-test-") as tmp:
            manifest = Path(tmp) / "manifest.jsonl"
            manifest.write_text(json.dumps(dict(self.rows[0], run_id="not-present"))+"\n", encoding="utf-8")
            run = subprocess.run([sys.executable, "-m", "evaluation.report", str(EXAMPLES / "predictions.jsonl"),
                                  "--output-dir", str(Path(tmp)/"bundle"), "--manifest", str(manifest), "--replicates", "10"],
                                 cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 2, run.stderr)


if __name__ == "__main__":
    unittest.main()
