"""Alternative chart geometries reuse paired observations and saved C statistics."""
import copy
import unittest
from pathlib import Path

from evaluation.chart_types import comparable_summary, comparison_data
from evaluation.report import compare
from evaluation.validation import load_records

ROOT = Path(__file__).resolve().parents[1]


class ChartTypeTests(unittest.TestCase):
    def setUp(self):
        self.rows = load_records(ROOT/"evaluation/examples/predictions.jsonl")

    def test_summary_reuses_all_conditions_and_exact_c_metrics(self):
        methods, stats, source, n = comparable_summary(self.rows)
        self.assertEqual(set(methods), {"B5", "B7"})
        self.assertEqual(n, 2)
        self.assertEqual(len(source), 4)
        self.assertEqual(stats["B5", "no_replica"]["coverage"], 1)
        self.assertEqual(stats["B7", "no_replica"]["coverage"], .5)

    def test_mixed_controls_or_method_configs_cannot_be_pooled(self):
        for field, value in (("metadata_state", "missing"), ("config_hash", "f"*64)):
            rows = copy.deepcopy(self.rows)
            rows[0][field] = value
            with self.assertRaises(ValueError):
                comparable_summary(rows)

    def test_missing_paired_question_is_rejected(self):
        with self.assertRaises(ValueError):
            comparable_summary(self.rows[:-1])

    def test_zero_answers_remain_undefined_not_zero_risk(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            if row["method"] == "B7":
                row.update(answered=False, prediction=None, correct=None)
        _, stats, _, _ = comparable_summary(rows)
        self.assertIsNone(stats["B7", "no_replica"]["selective_risk"])
        self.assertEqual(stats["B7", "no_replica"]["coverage"], 0)

    def test_forest_reads_saved_intervals_and_checks_estimate_identity(self):
        saved = compare(self.rows, "B7", "B5", 20, 7)
        a, b, source = comparison_data(saved, self.rows)
        self.assertEqual((a, b, len(source)), ("B7", "B5", 8))
        coverage = next(r for r in source if r["condition"] == "no_replica" and r["metric"] == "coverage")
        original = next(s for s in saved[0]["statistics"] if s["metric"] == "coverage")
        self.assertEqual([coverage["ci_low"], coverage["ci_high"]], original["ci_95"])
        saved[0]["statistics"][0]["observed_difference"] = 42
        with self.assertRaises(ValueError):
            comparison_data(saved, self.rows)


if __name__ == "__main__":
    unittest.main()
