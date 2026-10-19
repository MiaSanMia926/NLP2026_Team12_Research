"""Hand-computable scientific invariants; no real model output is used."""
import copy
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evaluation import metrics
from evaluation.bootstrap import paired_bootstrap, resample_clusters
from evaluation.plot_risk_coverage import coordinates
from evaluation.scheduler import make_manifest
from evaluation.validation import load_records, validate_prediction, validate_schema, SCHEMA_DIR

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "evaluation" / "examples"


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.rows = load_records(EXAMPLES / "predictions.jsonl")
        self.b5 = [r for r in self.rows if r["method"] == "B5"]
        self.b7 = [r for r in self.rows if r["method"] == "B7"]

    def test_hand_computed_answer_metrics(self):
        b5, b7 = metrics.summarize(self.b5), metrics.summarize(self.b7)
        self.assertEqual((b5["coverage"], b5["selective_risk"], b5["em_all_rows"]), (1, .75, .25))
        self.assertEqual((b7["coverage"], b7["selective_risk"], b7["em_all_rows"]), (.5, 0, .5))

    def test_full_aurc_includes_refused_candidates(self):
        self.assertAlmostEqual(metrics.aurc(self.b5), (0 + .5 + 2/3 + .75)/4)
        self.assertAlmostEqual(metrics.aurc(self.b7), (0 + 0 + 1/3 + .5)/4)
        self.assertEqual(coordinates(self.b7)[-1]["coverage"], 1)

    def test_partial_curve_has_explicit_endpoint(self):
        partial = metrics.risk_curve(self.b7, "answered")
        self.assertEqual(partial["max_coverage"], .5)
        self.assertEqual(partial["area"], 0)
        self.assertIsNone(metrics.partial_area(partial, .6))

    def test_score_ties_are_permutation_invariant(self):
        rows = copy.deepcopy(self.b5)
        for r in rows:
            r["selection_score"] = .5
        self.assertEqual(metrics.aurc(rows), .75)
        self.assertEqual(metrics.risk_curve(rows), metrics.risk_curve(rows[::-1]))

    def test_all_refused_is_not_zero_operating_risk(self):
        rows = copy.deepcopy(self.b7)
        for r in rows:
            r.update(answered=False, prediction=None, correct=None)
        result = metrics.summarize(rows)
        self.assertEqual(result["coverage"], 0)
        self.assertIsNone(result["selective_risk"])
        self.assertIsNotNone(result["aurc"])

    def test_missing_candidate_never_silently_dropped(self):
        rows = copy.deepcopy(self.b7)
        rows[0]["candidate_answer"] = None
        self.assertIsNone(metrics.aurc(rows))

    def test_no_score_means_no_curve(self):
        rows = copy.deepcopy(self.b5)
        for r in rows:
            r["selection_score"] = None
        self.assertIsNone(metrics.aurc(rows))

    def test_should_abstain_empty_references_counts_zero_quality(self):
        row = copy.deepcopy(self.b7[0])
        row.update(should_answer=False, references=[], answered=False, prediction=None,
                   correct=None, candidate_task_correct=False)
        validate_prediction(row)
        result = metrics.summarize([row])
        self.assertEqual((result["em_all_rows"], result["quality_eligible_n"]), (0, 1))
        self.assertEqual(result["inappropriate_answer_rate"], 0)

    def test_external_unknown_answerability_not_false(self):
        row = copy.deepcopy(self.b5[0])
        row.update(task_type="factual_qa", should_answer=None, candidate_factual_correct=True)
        validate_prediction(row)
        result = metrics.summarize([row])
        self.assertIsNone(result["inappropriate_answer_rate"])
        self.assertEqual(result["unknown_should_answer_n"], 1)

    def test_external_missing_reference_reports_exclusion(self):
        row = copy.deepcopy(self.b5[0])
        row.update(task_type="factual_qa", should_answer=None, references=[])
        result = metrics.summarize([row])
        self.assertEqual(result["quality_excluded_n"], 1)
        self.assertIsNone(result["em_all_rows"])

    def test_failed_run_not_refusal_and_cost_included(self):
        failed = copy.deepcopy(self.b5[0])
        failed.update(status="api_error", answered=None, correct=None, prediction=None,
                      selection_score=None, calls=3)
        validate_prediction(failed)
        result = metrics.summarize([self.b5[0], failed])
        self.assertEqual((result["planned_n"], result["failed_n"], result["coverage"]), (2, 1, 1))
        self.assertEqual(result["cost"]["calls_sum"], 3)

    def test_citation_entry_and_answer_denominators_differ(self):
        rows = copy.deepcopy(self.b5[:2])
        rows[0].update(citation_labels=[True, True], citation_correct=True)
        rows[1].update(citation_labels=[False], citation_correct=False)
        result = metrics.summarize(rows)
        self.assertAlmostEqual(result["citation_precision"], 2/3)
        self.assertEqual(result["all_citations_correct_answer_rate"], .5)

    def test_support_groups_deduplicated(self):
        row = dict(self.b5[0], gold_independent_support_groups=["g1", "g2"], retained_independent_support_groups=["g1"])
        self.assertEqual(metrics.support_retention([row])["micro_rate"], .5)

    def test_replica_outcomes_do_not_reward_refusal(self):
        self.assertEqual(metrics.replica_metrics(self.b5)["worsened_rate"], .5)
        self.assertEqual(metrics.replica_metrics(self.b7)["both_answered_pairs"], 1)

    def test_bootstrap_duplicate_draw_preserves_pairs(self):
        pair = {"fixture_q1": {m: [r for r in self.rows if r["base_question_id"] == "fixture_q1" and r["method"] == m] for m in ("B5", "B7")}}
        sampled = resample_clusters(pair, ["fixture_q1", "fixture_q1"])
        self.assertEqual(metrics.replica_metrics([r for r in sampled if r["method"] == "B5"])["valid_pairs"], 2)

    def test_bootstrap_reproducible_and_observed_delta(self):
        a = paired_bootstrap(self.rows, replicates=200, seed=17)
        b = paired_bootstrap(self.rows, replicates=200, seed=17)
        self.assertEqual(a, b)
        self.assertEqual(a["observed_difference"], -.75)
        self.assertGreater(a["undefined_replicates"], 0)

    def test_bootstrap_replica_metric_stays_defined(self):
        result = paired_bootstrap(self.rows, metric="replica.decision_change_rate", replicates=100)
        self.assertEqual(result["defined_replicates"], 100)
        self.assertEqual(result["ci_95"], [0, 0])

    def test_bootstrap_rejects_unpaired_or_mixed_slices(self):
        with self.assertRaises(ValueError):
            paired_bootstrap(self.rows[:-1])
        rows = copy.deepcopy(self.rows)
        rows[0]["model"] = "different-model"
        with self.assertRaises(ValueError):
            paired_bootstrap(rows)

    def test_bootstrap_reports_failed_cluster_exclusions(self):
        rows = copy.deepcopy(self.rows)
        rows[0].update(status="parse_error", prediction=None, answered=None, correct=None, selection_score=None)
        result = paired_bootstrap(rows, metric="coverage", replicates=20)
        self.assertEqual(result["excluded_failed_questions"], ["fixture_q1"])

    def test_grouping_never_pools_methods_or_conditions(self):
        result = metrics.grouped_summaries(self.rows)
        self.assertIsNone(result["pooled_metrics"])
        self.assertEqual(len(result["groups"]), 4)

    def test_nonfinite_or_boolean_score_rejected(self):
        schema = json.loads((SCHEMA_DIR / "prediction.schema.json").read_text())
        for value in (True, math.nan, math.inf):
            row = dict(self.b5[0], selection_score=value)
            with self.assertRaises(ValueError):
                validate_schema(row, schema)

    def test_duplicate_run_and_split_leakage_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".eval-test-") as tmp:
            self.assertTrue(Path(tmp).resolve().is_relative_to(ROOT.resolve()))
            path = Path(tmp) / "bad.jsonl"
            for rows in ([self.rows[0], self.rows[0]], [self.rows[0], dict(self.rows[1], split="test")]):
                path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_records(path)

    def test_pair_id_reuse_with_changed_controls_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".eval-test-") as tmp:
            self.assertTrue(Path(tmp).resolve().is_relative_to(ROOT.resolve()))
            path = Path(tmp) / "pair.jsonl"
            changed = dict(self.rows[1], position_seed=1)
            path.write_text(json.dumps(self.rows[0])+"\n"+json.dumps(changed)+"\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_records(path)

    def test_manifest_coverage_and_versions_checked(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".eval-test-") as tmp:
            self.assertTrue(Path(tmp).resolve().is_relative_to(ROOT.resolve()))
            path = Path(tmp) / "manifest.jsonl"
            path.write_text("".join(json.dumps(r)+"\n" for r in self.rows), encoding="utf-8")
            metrics.check_manifest(self.rows, path)
            with self.assertRaises(ValueError):
                metrics.check_manifest(self.rows[:-1], path)
            changed = copy.deepcopy(self.rows)
            changed[0]["model_revision"] = "wrong-version"
            with self.assertRaises(ValueError):
                metrics.check_manifest(changed, path)

    def test_manifest_counts_and_stability(self):
        questions = load_records(EXAMPLES / "questions.jsonl", "question")
        config = json.loads((EXAMPLES / "manifest_config.json").read_text())
        rows = make_manifest(questions, config)
        self.assertEqual(len(rows), 168)
        self.assertEqual(rows, make_manifest(questions[::-1], config))
        self.assertEqual(len({r["run_id"] for r in rows}), 168)
        self.assertNotIn("B6", {r["method"] for r in rows})
        self.assertEqual(len(make_manifest(questions, config, include_oracle=True)), 192)
        config.pop("fixed_token_budget")
        self.assertEqual(sum(r["status"] == "blocked" for r in make_manifest(questions, config)), 84)

    def test_manifest_pair_identity_and_config_change(self):
        questions = load_records(EXAMPLES / "questions.jsonl", "question")
        config = json.loads((EXAMPLES / "manifest_config.json").read_text())
        rows = make_manifest(questions, config, methods=["B7"])
        pairs = {}
        for row in rows:
            pairs.setdefault(row["pair_id"], []).append(row)
        self.assertTrue(all(len(group) == 2 for group in pairs.values()))
        changed = make_manifest(questions, dict(config, seed=2), methods=["B7"])
        self.assertNotEqual(rows[0]["run_id"], changed[0]["run_id"])

    def test_token_normalization_and_cjk_f1(self):
        self.assertEqual(metrics.exact_match("The Alpha!", ["alpha"]), 1)
        self.assertAlmostEqual(metrics.token_f1("北京", "北京市"), .8)

    def test_public_input_rejects_gold_and_condition_labels(self):
        schema = json.loads((SCHEMA_DIR / "public_input.schema.json").read_text())
        row = json.loads((EXAMPLES / "public_inputs.jsonl").read_text())
        validate_schema(row, schema)
        for field in ("gold_source_group_id", "references", "should_answer", "metadata_state"):
            with self.assertRaises(ValueError):
                validate_schema(dict(row, **{field: "not-model-visible"}), schema)
        nested = copy.deepcopy(row)
        nested["evidence"][0]["visible_metadata"]["gold_group"] = "g1"
        with self.assertRaises(ValueError):
            validate_schema(nested, schema)

    def test_metadata_error_recipe_required(self):
        row = dict(self.b5[0], metadata_state="incorrect", metadata_error_type="none")
        with self.assertRaises(ValueError):
            validate_prediction(row)

    def test_empty_and_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".eval-test-") as tmp:
            self.assertTrue(Path(tmp).resolve().is_relative_to(ROOT.resolve()))
            path = Path(tmp) / "bad.jsonl"
            for content in ("", json.dumps(dict(self.b5[0], selection_score=float("nan")))):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_records(path)

    def test_cli_pipeline_smoke(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".eval-test-") as tmp:
            self.assertTrue(Path(tmp).resolve().is_relative_to(ROOT.resolve()))
            for module, arguments in [
                ("evaluation.validation", [str(EXAMPLES / "predictions.jsonl")]),
                ("evaluation.validation", [str(EXAMPLES / "public_inputs.jsonl"), "--kind", "public_input"]),
                ("evaluation.metrics", [str(EXAMPLES / "predictions.jsonl"), "--output", str(Path(tmp) / "metrics.json")]),
                ("evaluation.plot_risk_coverage", [str(EXAMPLES / "predictions.jsonl"), "--output", str(Path(tmp) / "curves.csv")]),
                ("evaluation.bootstrap", [str(EXAMPLES / "predictions.jsonl"), "--replicates", "50", "--output", str(Path(tmp) / "ci.json")]),
                ("evaluation.scheduler", ["--questions", str(EXAMPLES / "questions.jsonl"), "--config", str(EXAMPLES / "manifest_config.json"), "--output", str(Path(tmp) / "manifest.jsonl")]),
            ]:
                run = subprocess.run([sys.executable, "-m", module] + arguments, cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == "__main__":
    unittest.main()
