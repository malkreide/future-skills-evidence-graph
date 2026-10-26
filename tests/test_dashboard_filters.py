"""Tests for the dashboard's per-dimension filters (site/index.html + app.js).

The filter controls are static markup, but what they can express is a
property of the data. A filter offering fewer options than the data has
values does not fail loudly -- it silently makes the unlisted records
unreachable, which is the worst outcome for a catalogue whose whole point
is that everything is inspectable.

So these tests pin the two together: every value the data can take must
have a control that can select it, and the index must carry the fields
the filters read.

The interaction itself (combining thresholds, the empty state, the shared
URL) is exercised in a browser, not here.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common import load_records  # noqa: E402

INDEX_HTML = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "site" / "assets" / "app.js").read_text(encoding="utf-8")

LEHRPLAN21 = "Lehrplan 21"


def select_options(select_id: str) -> set[str]:
    """The values a <select> can take, straight from the shipped markup."""
    block = re.search(
        rf'<select id="{select_id}".*?</select>', INDEX_HTML, re.DOTALL
    )
    assert block, f"no <select id={select_id}> in site/index.html"
    return set(re.findall(r'<option value="([^"]*)"', block.group(0)))


def lp21_mappings() -> list[dict]:
    return [
        mapping
        for mapping in load_records("frameworks")
        if mapping.get("framework") == LEHRPLAN21
    ]


class FilterVocabularyTests(unittest.TestCase):
    def test_every_coverage_label_in_the_data_can_be_selected(self) -> None:
        # A label the control does not offer makes those skills unreachable
        # through the Lehrplan-21 filter without any error appearing.
        labels = {mapping["coverage_label"] for mapping in lp21_mappings()}
        self.assertTrue(labels)
        missing = labels - select_options("lp21CoverageFilter")
        self.assertEqual(missing, set(), f"coverage_label(s) without a filter option: {missing}")

    def test_every_trend_in_the_schema_can_be_selected(self) -> None:
        schema = json.loads((ROOT / "schemas" / "skill.schema.json").read_text(encoding="utf-8"))
        trends = set(schema["properties"]["trend"]["enum"])
        missing = trends - select_options("trendFilter")
        self.assertEqual(missing, set(), f"trend value(s) without a filter option: {missing}")

    def test_every_status_in_the_schema_can_be_selected(self) -> None:
        schema = json.loads((ROOT / "schemas" / "skill.schema.json").read_text(encoding="utf-8"))
        statuses = set(schema["properties"]["status"]["enum"])
        missing = statuses - select_options("statusFilter")
        self.assertEqual(missing, set(), f"status value(s) without a filter option: {missing}")

    def test_every_cycle_in_the_data_has_a_filter_option_and_matrix_column(self) -> None:
        # The coverage matrix builds its columns from the cycle filter's
        # options. A cycle the filter lacks would vanish from both, so the
        # skills addressed only there would show as "nicht adressiert".
        cycles = {cycle for mapping in lp21_mappings() for cycle in mapping.get("cycles", [])}
        self.assertTrue(cycles)
        missing = cycles - select_options("lp21CycleFilter")
        self.assertEqual(missing, set(), f"cycle(s) without a filter option: {missing}")
        body = re.search(r"function lp21CycleColumns\(\) \{(.*?)\n\}", APP_JS, re.DOTALL)
        self.assertIsNotNone(body, "lp21CycleColumns not found in app.js")
        self.assertIn("els.lp21CycleFilter.options", body.group(1))

    def test_claim_count_thresholds_stay_reachable(self) -> None:
        # A threshold no skill can meet is a dead option. The largest offered
        # step must still select something, or the control lies about what the
        # catalogue contains.
        offered = {int(value) for value in select_options("claimCountFilter")}
        largest = max(offered)
        counts = [
            len(skill.get("supporting_claim_ids", []))
            for skill in load_records("skills")
            if skill["status"] == "active"
        ]
        self.assertGreaterEqual(max(counts), largest)


class FilterDataShapeTests(unittest.TestCase):
    def test_lehrplan21_mappings_resolve_by_skill_id(self) -> None:
        # The filter reads coverage through mapping.skill_id, not through the
        # skill's framework_mapping_ids: only 4 of 16 skills list their LP21
        # mapping there, so the other direction would drop most of them.
        skill_ids = {skill["id"] for skill in load_records("skills")}
        for mapping in lp21_mappings():
            self.assertIn(mapping["skill_id"], skill_ids, mapping["id"])
        # Scoped to the filter's own function: the same selector appears in the
        # detail pane too, so a search across the whole file would pass even if
        # the filter itself switched to the wrong direction.
        body = re.search(
            r"function lp21CoverageLabel\(skill\) \{(.*?)\n\}", APP_JS, re.DOTALL
        )
        self.assertIsNotNone(body, "lp21CoverageLabel not found in app.js")
        self.assertIn("mapping.skill_id === skill.id", body.group(1))

    def test_active_learner_skills_all_carry_a_coverage_label(self) -> None:
        by_skill = {mapping["skill_id"] for mapping in lp21_mappings()}
        for skill in load_records("skills"):
            if skill["status"] != "active":
                continue
            if (skill.get("audience") or "learner") == "learner":
                self.assertIn(skill["id"], by_skill, f"{skill['id']} has no Lehrplan 21 mapping")
            else:
                # Educators are anchored to the UNESCO framework; the control is
                # disabled in that view rather than quietly matching nothing.
                self.assertNotIn(skill["id"], by_skill, skill["id"])

    def test_gap_tile_counts_the_stored_label_not_its_own_threshold(self) -> None:
        # The label thresholds live only in common.lp21_coverage_label. The
        # tile once counted coverage_score < 2 and reported 8 gaps next to a
        # matrix and a table showing 3 "Zukunftslücke" labels.
        body = re.search(
            r"function renderLp21Comparison\(\) \{(.*?)\n\}", APP_JS, re.DOTALL
        )
        self.assertIsNotNone(body, "renderLp21Comparison not found in app.js")
        gap_line = re.search(r"const gapCount = (.*?);", body.group(1), re.DOTALL)
        self.assertIsNotNone(gap_line, "gapCount not found in renderLp21Comparison")
        self.assertIn('coverage_label === "Zukunftsluecke"', gap_line.group(1))
        self.assertNotIn("coverage_score", gap_line.group(1))

    def test_index_carries_the_fields_the_filters_read(self) -> None:
        import build_site

        for skill in build_site.build_index()["skills"]:
            context = skill.get("score_context")
            self.assertIsNotNone(context, skill["id"])
            self.assertIn("supporting_claims", context)
            self.assertIn("claim_quality", context)


class FilterWiringTests(unittest.TestCase):
    def test_every_control_has_a_default_a_url_param_and_a_reset(self) -> None:
        # A control missing from any of the three lists half-works: it filters
        # but does not reset, or does not survive a shared link.
        controls = [
            "lp21CoverageFilter",
            "claimCountFilter",
            "qualityFilter",
            "trendFilter",
            "sortFilter",
        ]
        defaults = re.search(r"const FILTER_DEFAULTS = \{(.*?)\};", APP_JS, re.DOTALL).group(1)
        url_map = re.search(r"const URL_PARAM_MAP = \{(.*?)\};", APP_JS, re.DOTALL).group(1)
        reset = re.search(r"function resetFilters\(\) \{(.*?)\n\}", APP_JS, re.DOTALL).group(1)
        values = re.search(
            r"function currentControlValues\(\) \{(.*?)\n\}", APP_JS, re.DOTALL
        ).group(1)
        for control in controls:
            with self.subTest(control):
                self.assertIn(control, url_map, "missing from URL_PARAM_MAP")
                self.assertIn(control, reset, "missing from resetFilters")
                self.assertIn(control, values, "missing from currentControlValues")
                key = re.search(rf'(\w+): "{control}"', url_map).group(1)
                self.assertRegex(defaults, rf"\b{key}:", "missing from FILTER_DEFAULTS")


if __name__ == "__main__":
    unittest.main()
