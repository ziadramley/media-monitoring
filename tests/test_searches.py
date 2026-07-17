"""Saved-search storage: run with  python -m unittest  from the repo root.

Covers the security-sensitive path handling and the round trip that
guarantees a saved search stays runnable from the command line.
"""
import tempfile
import unittest
from pathlib import Path

import yaml

from monitoring.config import ConfigError, load_queries
from monitoring.models import Publication, Query
from monitoring.searches import (
    _safe_path,
    delete_search,
    list_searches,
    load_search,
    next_untitled_name,
    save_search,
    slugify,
)

PUBS = {
    "bbc": Publication("bbc", "BBC News", ["https://x"], region="UK"),
    "nyt": Publication("nyt", "The New York Times", ["https://y"], region="US"),
}


def a_query(name="UK", keywords=("budget",), pubs=("bbc",)):
    return Query(name=name, keywords=list(keywords), match="any",
                 date_range="past_24_hours", publications=list(pubs))


class Slugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Morning Briefing"), "morning-briefing")

    def test_strips_punctuation_and_path_chars(self):
        self.assertEqual(slugify("../../etc/passwd"), "etc-passwd")
        self.assertEqual(slugify("A/B:C*D"), "a-b-c-d")

    def test_empty_when_nothing_usable(self):
        self.assertEqual(slugify("   "), "")
        self.assertEqual(slugify("!!!"), "")


class SafePath(unittest.TestCase):
    def test_rejects_traversal_and_bad_chars(self):
        # Includes a trailing newline: Python's $ would accept "foo\n";
        # the \Z anchor in _SLUG_RE must not.
        for bad in ("../config", "a/b", "foo.yaml", "..", "", "a b", "UPPER", "foo\n", "foo\nbar"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                _safe_path(bad, "searches")

    def test_accepts_clean_slug(self):
        p = _safe_path("morning-briefing", "searches")
        self.assertEqual(p.name, "morning-briefing.yaml")


class RoundTrip(unittest.TestCase):
    def test_save_load_list_delete(self):
        with tempfile.TemporaryDirectory() as d:
            slug = save_search("Morning Briefing", [a_query("UK"), a_query("US", pubs=("nyt",))], d)
            self.assertEqual(slug, "morning-briefing")

            loaded = load_search(slug, PUBS, d)
            self.assertEqual(loaded.name, "Morning Briefing")
            self.assertEqual([q.name for q in loaded.queries], ["UK", "US"])
            self.assertEqual(loaded.source, "saved")

            listed = list_searches(PUBS, d)
            self.assertEqual([s.slug for s in listed], ["morning-briefing"])

            self.assertTrue(delete_search(slug, d))
            self.assertEqual(list_searches(PUBS, d), [])

    def test_saved_file_is_cli_loadable(self):
        # The "both doors" promise: a saved search also runs via monitor.py.
        with tempfile.TemporaryDirectory() as d:
            save_search("Daily", [a_query()], d)
            queries = load_queries(Path(d) / "daily.yaml", PUBS)
            self.assertEqual(queries[0].keywords, ["budget"])

    def test_resaving_same_name_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            save_search("Daily", [a_query(keywords=("budget",))], d)
            save_search("Daily", [a_query(keywords=("tax",))], d)
            self.assertEqual(len(list_searches(PUBS, d)), 1)
            self.assertEqual(load_search("daily", PUBS, d).queries[0].keywords, ["tax"])

    def test_save_blank_name_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                save_search("   ", [a_query()], d)


class BrokenFiles(unittest.TestCase):
    def test_unparseable_file_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "good.yaml").write_text(
                yaml.safe_dump({"name": "Good", "queries": [
                    {"name": "q", "keywords": ["x"], "match": "any",
                     "date_range": "past_24_hours", "publications": ["bbc"]}]}))
            (Path(d) / "broken.yaml").write_text("name: [unclosed")
            listed = list_searches(PUBS, d)
            self.assertEqual([s.slug for s in listed], ["good"])

    def test_load_missing_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ConfigError):
                load_search("nope", PUBS, d)


class NextUntitled(unittest.TestCase):
    def test_starts_at_one(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(next_untitled_name(d), "Untitled Report 1")

    def test_increments_past_existing(self):
        with tempfile.TemporaryDirectory() as d:
            save_search("Untitled Report 1", [a_query()], d)
            save_search("Untitled Report 2", [a_query()], d)
            self.assertEqual(next_untitled_name(d), "Untitled Report 3")

    def test_fills_the_lowest_gap(self):
        with tempfile.TemporaryDirectory() as d:
            save_search("Untitled Report 1", [a_query()], d)
            save_search("Untitled Report 3", [a_query()], d)
            self.assertEqual(next_untitled_name(d), "Untitled Report 2")


if __name__ == "__main__":
    unittest.main()
