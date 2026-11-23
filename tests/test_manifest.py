"""Acceptance regressions: partial batches must not hide wrong provenance."""
import copy
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evaluation.manifest import audit_manifest, load_manifest
from evaluation.metrics import check_manifest, summarize
from evaluation.report import build_report
from evaluation.scheduler import make_manifest
from evaluation.validation import load_records

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "evaluation/examples"


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT, prefix=".eval-test-")
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.rows = load_records(EXAMPLES / "predictions.jsonl")
        self.manifest = write_rows(self.directory / "manifest.jsonl", self.rows)

    def test_id_only_manifest_cannot_claim_trace_verification(self):
        write_rows(self.manifest, [{"run_id": r["run_id"]} for r in self.rows])
        with self.assertRaisesRegex(ValueError, "missing"):
            audit_manifest(self.rows, self.manifest)
        with self.assertRaises(ValueError):
            check_manifest(self.rows, self.manifest)

    def test_partial_batch_reports_all_trace_errors_as_well_as_missing_extra(self):
        rows = copy.deepcopy(self.rows[:-1])
        rows[0].update(model_revision="wrong", dataset_hash="f" * 64)
        rows.append(dict(self.rows[-1], run_id="unexpected"))
        audit = audit_manifest(rows, self.manifest)
        self.assertEqual(audit["status"], "incomplete")
        self.assertEqual(audit["missing_run_ids"], [self.rows[-1]["run_id"]])
        self.assertEqual(audit["extra_run_ids"], ["unexpected"])
        self.assertEqual({m["field"] for m in audit["trace_mismatches"]}, {"model_revision", "dataset_hash"})
        self.assertEqual(sum(g["trace_mismatch_n"] for g in audit["groups"]), 1)
        self.assertEqual(sum(g["extra_n"] for g in audit["groups"]), 1)

    def test_missing_whole_condition_is_visible_with_plan_denominator(self):
        rows = [r for r in self.rows if r["replica_condition"] == "no_replica"]
        audit = audit_manifest(rows, self.manifest)
        absent = [g for g in audit["groups"] if g["slice"]["replica_condition"] == "same_source_replica"]
        self.assertEqual(len(absent), 2)
        self.assertTrue(all((g["planned_n"], g["provided_n"], g["missing_n"], g["completion_rate"]) == (2, 0, 2, 0) for g in absent))
        # Existing summary counts only supplied rows; plan coverage has the other denominator.
        self.assertEqual(summarize(rows)["completion_rate"], 1)
        self.assertEqual(sum(g["ok_n"] for g in audit["groups"]) / audit["planned_n"], .5)

    def test_extra_only_slice_has_no_completion_denominator(self):
        audit = audit_manifest(self.rows + [dict(self.rows[0], run_id="extra", method="EXTRA")], self.manifest)
        extra = next(g for g in audit["groups"] if g["slice"]["method"] == "EXTRA")
        self.assertEqual((extra["planned_n"], extra["extra_n"]), (0, 1))
        self.assertIsNone(extra["completion_rate"])

    def test_accounted_failures_are_not_successes_or_missing_runs(self):
        rows = copy.deepcopy(self.rows)
        rows[0].update(status="api_error", prediction=None, answered=None, correct=None, selection_score=None)
        audit = audit_manifest(rows, self.manifest)
        self.assertEqual(audit["status"], "complete")
        self.assertEqual((audit["ok_n"], audit["failed_n"]), (7, 1))
        self.assertEqual(audit["missing_run_ids"], [])

    def test_scheduler_blocked_unknown_recipe_stays_auditable(self):
        questions = load_records(EXAMPLES / "questions.jsonl", "question")
        questions[0].pop("incorrect_metadata_error_type")
        config = json.loads((EXAMPLES / "manifest_config.json").read_text())
        planned = make_manifest(questions, config, methods=["B0"])
        write_rows(self.manifest, planned)
        self.assertEqual(load_manifest(self.manifest), planned)
        audit = audit_manifest([], self.manifest)
        self.assertEqual(len(audit["blocked_plan_run_ids"]), 4)
        self.assertEqual(sum(g["missing_n"] for g in audit["groups"]), 24)

    def test_blocked_plan_with_predictions_still_fails_check(self):
        planned = copy.deepcopy(self.rows)
        planned[0].update(status="blocked", blocked_reasons=["missing_token_budget"])
        write_rows(self.manifest, planned)
        self.assertEqual(audit_manifest(self.rows, self.manifest)["status"], "incomplete")
        with self.assertRaises(ValueError):
            check_manifest(self.rows, self.manifest)

    def test_invalid_manifest_types_status_and_duplicates_rejected(self):
        for rows in ([self.rows[0], self.rows[0]], [dict(self.rows[0], seed=True)],
                     [dict(self.rows[0], dataset_hash="bad")], [dict(self.rows[0], status="bloked")],
                     [dict(self.rows[0], status="blocked", blocked_reasons=[])]):
            with self.subTest(rows=rows):
                write_rows(self.manifest, rows)
                with self.assertRaises(ValueError):
                    load_manifest(self.manifest)
        with self.assertRaises(ValueError):
            audit_manifest(self.rows + [self.rows[0]], write_rows(self.manifest, self.rows))

    def test_audit_order_and_accounting_are_deterministic(self):
        a = audit_manifest(self.rows[:-1], self.manifest)
        write_rows(self.manifest, self.rows[::-1])
        self.assertEqual(audit_manifest(self.rows[-2::-1], self.manifest), a)
        for g in a["groups"]:
            self.assertEqual(g["planned_n"], g["missing_n"] + g["ok_n"] + g["failed_n"] + g["trace_mismatch_n"])

    def test_bundle_exports_plan_coverage_and_hashes_it(self):
        output = self.directory / "bundle"
        build_report(EXAMPLES / "predictions.jsonl", output, self.manifest, replicates=10)
        with (output / "manifest_coverage.csv").open(encoding="utf-8-sig", newline="") as stream:
            groups = list(csv.DictReader(stream))
        self.assertEqual(len(groups), 4)
        self.assertEqual(sum(int(g["planned_n"]) for g in groups), 8)
        hashes = json.loads((output / "bundle_hashes.json").read_text())
        self.assertIn("manifest_coverage.csv", hashes)

    def test_metrics_and_report_cli_agree_on_blocked_plan(self):
        planned = copy.deepcopy(self.rows)
        planned[0].update(status="blocked", blocked_reasons=["missing_token_budget"])
        write_rows(self.manifest, planned)
        for module, args in (("evaluation.metrics", []),
                             ("evaluation.report", ["--output-dir", str(self.directory / "bundle"), "--replicates", "10"])):
            run = subprocess.run([sys.executable, "-m", module, str(EXAMPLES / "predictions.jsonl"),
                                  "--manifest", str(self.manifest)] + args, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 2, run.stderr)


if __name__ == "__main__":
    unittest.main()
