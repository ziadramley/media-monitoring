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
    build_cards,
    cards_from_queries,
    parse_cards,
)
from monitoring.models import Query

_PUBS = {
    "bbc": Publication("bbc", "BBC News", ["https://x"], region="UK"),
    "nyt": Publication("nyt", "The New York Times", ["https://y"], region="US"),
}


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


class ParseCards(unittest.TestCase):
    def test_reads_cards_in_declared_order(self):
        fields = {
            "card_order": ["1,0"],  # deliberately not sorted
            "keywords__0": ["budget"], "match__0": ["any"],
            "date_range__0": ["past_24_hours"], "publications__0": ["bbc"], "name__0": ["A"],
            "keywords__1": ["congress"], "match__1": ["all"],
            "date_range__1": ["past_48_hours"], "publications__1": ["nyt"], "name__1": ["B"],
        }
        cards = parse_cards(fields)
        self.assertEqual([c["token"] for c in cards], ["1", "0"])
        self.assertEqual(cards[0]["keywords"], "congress")

    def test_missing_card_order_gives_no_cards(self):
        self.assertEqual(parse_cards({}), [])


class BuildCards(unittest.TestCase):
    def _cards(self, **over):
        base = {"token": "0", "name": "", "keywords": "budget", "match": "any",
                "date_range": "past_24_hours", "publications": ["bbc"]}
        base.update(over)
        return [base]

    def test_valid_card_makes_a_query(self):
        queries, view, ok = build_cards(self._cards(), _PUBS)
        self.assertTrue(ok)
        self.assertEqual(len(queries), 1)
        self.assertIsNone(view[0]["error"])

    def test_empty_keywords_flagged_and_preserved(self):
        queries, view, ok = build_cards(self._cards(keywords="   "), _PUBS)
        self.assertFalse(ok)
        self.assertEqual(queries, [])
        self.assertIn("keyword", view[0]["error"])

    def test_unknown_publications_dropped(self):
        queries, view, ok = build_cards(self._cards(publications=["bbc", "ghost"]), _PUBS)
        self.assertTrue(ok)
        self.assertEqual(queries[0].publications, ["bbc"])

    def test_no_publications_flagged(self):
        _, view, ok = build_cards(self._cards(publications=[]), _PUBS)
        self.assertFalse(ok)
        self.assertIn("publication", view[0]["error"])

    def test_default_section_name_when_blank(self):
        queries, _, _ = build_cards(self._cards(name=""), _PUBS)
        self.assertEqual(queries[0].name, "Search 1")

    def test_no_cards_is_not_valid(self):
        _, _, ok = build_cards([], _PUBS)
        self.assertFalse(ok)


class CardsFromQueries(unittest.TestCase):
    def test_keywords_joined_and_pubs_as_set(self):
        q = Query(name="UK", keywords=["a", "b"], match="all",
                  date_range="past_72_hours", publications=["bbc", "nyt"])
        [card] = cards_from_queries([q])
        self.assertEqual(card["keywords"], "a, b")
        self.assertEqual(card["selected"], {"bbc", "nyt"})
        self.assertEqual(card["match"], "all")


class ReportNameThreading(unittest.TestCase):
    """The report name and publications count reach the portable file."""

    def _render(self, **over):
        from datetime import datetime, timezone
        from monitoring.report import ReportSection, render_html
        from monitoring.models import Article
        now = datetime(2026, 7, 17, 16, 28, tzinfo=timezone.utc)
        art = Article(title="H", url="https://x/a", dedupe_key="k", publication_id="bbc",
                      publication_name="BBC News", author=None, published=now, standfirst=None)
        secs = [
            ReportSection("Alpha", "q1", [art], "past 24 hours", False, ["a"], "any"),
            ReportSection("Beta", "q2", [], "past 24 hours", False, ["b"], "any"),
        ]
        kw = {"report_name": "My Report", "publications": 3}
        kw.update(over)
        return render_html(secs, [], now, **kw)

    def test_name_and_metadata_present(self):
        html = self._render()
        self.assertIn("<h1>My Report</h1>", html)
        self.assertIn("3 publications", html)
        self.assertIn("1 result", html)

    def test_toc_only_with_multiple_sections(self):
        self.assertIn('class="toc', self._render())            # 2 sections
        from datetime import datetime, timezone
        from monitoring.report import ReportSection, render_html
        one = [ReportSection("Solo", "q1", [], "past 24 hours", False, ["a"], "any")]
        html = render_html(one, [], datetime(2026, 7, 17, tzinfo=timezone.utc),
                           report_name="Solo", publications=1)
        self.assertNotIn('class="toc', html)


if __name__ == "__main__":
    unittest.main()
