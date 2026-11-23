"""Plot transformations must preserve all observations and empirical geometry."""
import copy
import unittest

from evaluation.publication import STYLE_PRESETS, curve_key, grouped_panels, overlap_groups, style_for


def curve(points):
    return {"available": True, "mode": "candidate", "points": [{"coverage": x, "risk": y} for x, y in points]}


class PublicationTests(unittest.TestCase):
    def test_equal_step_functions_merge_without_mutating_thresholds(self):
        a = curve([(0, None), (.5, 0), (1, .5)])
        b = curve([(0, None), (.25, 0), (.5, 0), (.75, .5), (1, .5)])
        original = copy.deepcopy(b)
        self.assertEqual(curve_key(a), curve_key(b))
        self.assertEqual(b, original)
        groups = overlap_groups([({"method": "B5"}, a), ({"method": "B7"}, b)])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

    def test_different_step_boundaries_and_partial_endpoints_never_merge(self):
        a = curve([(0, None), (.5, 0), (1, .5)])
        b = curve([(0, None), (.75, 0), (1, .5)])
        partial = curve([(0, None), (.5, 0)])
        self.assertNotEqual(curve_key(a), curve_key(b))
        self.assertNotEqual(curve_key(a), curve_key(partial))

    def test_method_display_is_stable_and_does_not_leak_config_hash(self):
        self.assertEqual(style_for("SMOKE_gate")[0], "Conservative gate")
        self.assertEqual(style_for("B7")[0], "B7")
        self.assertEqual(style_for("NewMethod"), style_for("NewMethod"))

    def test_unavailable_curve_remains_in_panel_but_is_not_drawn_as_zero(self):
        group = [({"method": "B0"}, {"available": False, "points": [], "area": None})]
        self.assertEqual(overlap_groups(group), [])

    def test_styles_change_appearance_without_changing_method_identity(self):
        colors = set()
        for style in STYLE_PRESETS:
            name, color, line = style_for("SMOKE_gate", style)
            self.assertEqual(name, "Conservative gate")
            self.assertEqual(line, "-")
            colors.add(color)
        self.assertEqual(len(colors), len(STYLE_PRESETS))

    def test_monochrome_uses_neutral_colors_and_retains_line_patterns(self):
        for method in ("SMOKE_vote", "SMOKE_exact", "SMOKE_source", "SMOKE_gate"):
            color = style_for(method, "monochrome")[1]
            self.assertEqual(color[1:3], color[3:5])
            self.assertEqual(color[3:5], color[5:7])
        self.assertEqual(len({style_for(m, "monochrome")[2] for m in ("SMOKE_vote", "SMOKE_exact", "SMOKE_source", "SMOKE_gate")}), 4)


if __name__ == "__main__":
    unittest.main()
