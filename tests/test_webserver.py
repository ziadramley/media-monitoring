"""Control-panel server helpers: run with  python -m unittest  from the repo root.

These cover the pure, security-sensitive bits (path guard, grouping,
option building) without standing up a live server.
"""
import unittest

from monitoring.models import Publication
from monitoring.webserver import (
    _REPORT_FILENAME_RE,
    _date_range_options,
    _grouped_publications,
)


class ReportFilenameGuard(unittest.TestCase):
    def test_accepts_a_real_report_name(self):
        self.assertTrue(_REPORT_FILENAME_RE.match("report_2026-07-17_11-57-32.html"))

    def test_rejects_path_traversal(self):
        for bad in ("../config.yaml", "..%2fconfig.yaml", "report_x.html",
                    "report_2026-07-17_11-57-32.md", "/etc/passwd",
                    "report_2026-07-17_11-57-32.html/../x"):
            self.assertIsNone(_REPORT_FILENAME_RE.match(bad), bad)


class DateRangeOptions(unittest.TestCase):
    def test_value_label_pairs(self):
        options = _date_range_options()
        self.assertIn(("past_24_hours", "Past 24 hours"), options)
        self.assertIn(("past_72_hours", "Past 72 hours"), options)


class GroupedPublications(unittest.TestCase):
    def test_groups_by_region_uk_first(self):
        pubs = {
            "nyt": Publication("nyt", "The New York Times", [], region="US"),
            "bbc": Publication("bbc", "BBC News", [], region="UK"),
            "misc": Publication("misc", "Somewhere", [], region=None),
        }
        grouped = _grouped_publications(pubs)
        labels = [label for label, _ in grouped]
        self.assertEqual(labels[0], "United Kingdom")
        self.assertEqual(labels[1], "United States")
        self.assertIn("Other", labels)

    def test_publications_sorted_within_group(self):
        pubs = {
            "b": Publication("b", "Zephyr Times", [], region="UK"),
            "a": Publication("a", "Alpha News", [], region="UK"),
        }
        [(_, uk_pubs)] = _grouped_publications(pubs)
        self.assertEqual([p.name for p in uk_pubs], ["Alpha News", "Zephyr Times"])


if __name__ == "__main__":
    unittest.main()
