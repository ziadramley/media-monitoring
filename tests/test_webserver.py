"""Control-panel server tests: run with  python -m unittest  from the repo root.

The first half covers the pure, security-sensitive bits (path guard,
grouping, option building). The LiveServer half stands up a real
in-process server — with report generation stubbed so nothing touches
the network — and drives the routes a browser would: the Host and CSRF
defences, validation errors, and the save → run → view → prune → delete
round trip.
"""
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from monitoring.models import Publication
from monitoring.webserver import (
    _REPORT_FILENAME_RE,
    _date_range_options,
    _grouped_publications,
    build_cards,
    cards_from_queries,
    create_server,
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
        base = {"token": "0", "name": "Q", "keywords": "budget", "match": "any",
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

    def test_blank_name_is_flagged(self):
        # The editor labels the name mandatory — the backend agrees.
        queries, view, ok = build_cards(self._cards(name=""), _PUBS)
        self.assertFalse(ok)
        self.assertEqual(queries, [])
        self.assertIn("name", view[0]["error"])

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

    def test_printable_carries_no_csrf_token(self):
        # The portable file gets emailed around — it must never leak the
        # server's CSRF token (the remove forms exist only in-app).
        self.assertNotIn("csrf", self._render())

    def test_printable_is_minimal(self):
        # The printable file must carry no TOC, no warnings box, no
        # markdown script, and no remove buttons — even with multiple
        # sections and failed feeds present.
        from monitoring.models import FeedFetchResult
        from datetime import datetime, timezone
        from monitoring.report import ReportSection, render_html
        failed = [FeedFetchResult("x", "X News", "https://x/rss", ok=False, error="boom")]
        secs = [
            ReportSection("Alpha", "q1", [], "past 24 hours", False, ["a"], "any"),
            ReportSection("Beta", "q2", [], "past 24 hours", False, ["b"], "any"),
        ]
        html = render_html(secs, failed, datetime(2026, 7, 17, tzinfo=timezone.utc),
                           report_name="Min", publications=1)
        self.assertNotIn('class="toc', html)
        self.assertNotIn("could not be reached", html)
        self.assertNotIn("REPORT_MARKDOWN", html)
        self.assertNotIn("remove-article", html)


def _fake_result(reports_dir: Path, name: str = "My Report"):
    """A ReportResult shaped exactly like generate_report's, minus the
    network: one section, one article, and a real file in reports/."""
    from monitoring.models import Article
    from monitoring.pipeline import ReportResult
    from monitoring.report import ReportSection

    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    article = Article(title="Budget rises", url="https://x.com/1", dedupe_key="k1",
                      publication_id="bbc", publication_name="BBC News",
                      author=None, published=now, standfirst=None)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / now.strftime("report_%Y-%m-%d_%H-%M-%S.html")
    path.write_text("<html>portable</html>", encoding="utf-8")
    section = ReportSection(name="Alpha", anchor="q1", articles=[article],
                            range_label="past 24 hours", show_depth_note=False,
                            keywords=["budget"], match="any")
    return ReportResult(path=path, sections=[section], failed=[], stale=[],
                        generated_at=now, total_articles=1,
                        report_name=name, publications=1)


class LiveServer(unittest.TestCase):
    """A real in-process server driven over HTTP. generate_report is
    stubbed, so these run without the network."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.reports_dir = base / "reports"
        self.searches_dir = base / "searches"
        # Port 0 lets the OS pick a free port — create_server returns it.
        self.server, self.port = create_server(
            _PUBS, 0, reports_dir=self.reports_dir, searches_dir=self.searches_dir,
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    # -- tiny HTTP client (urllib follows the 303s for us) --------------
    def _request(self, path, data=None, host=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        body = urllib.parse.urlencode(data, doseq=True).encode() if data is not None else None
        request = urllib.request.Request(url, data=body,
                                         headers={"Host": host} if host else {})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def _csrf(self):
        _, html = self._request("/")
        return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)

    def _card(self, csrf, name="UK politics", keywords="budget"):
        return {
            "csrf": csrf, "search_name": "Morning Briefing", "card_order": "0",
            "name__0": name, "keywords__0": keywords, "match__0": "any",
            "date_range__0": "past_24_hours", "publications__0": ["bbc"],
        }

    # -- the defences ----------------------------------------------------
    def test_editor_serves_and_embeds_csrf_token(self):
        status, html = self._request("/")
        self.assertEqual(status, 200)
        self.assertRegex(html, r'name="csrf" value="[0-9a-f]+"')

    def test_wrong_host_is_rejected(self):
        status, _ = self._request("/", host="evil.example")
        self.assertEqual(status, 403)
        status, _ = self._request("/generate", data={"x": "1"}, host="evil.example")
        self.assertEqual(status, 403)

    def test_post_without_csrf_is_rejected(self):
        status, html = self._request("/generate", data={"card_order": "0"})
        self.assertEqual(status, 403)
        self.assertIn("expired", html)

    def test_localhost_host_header_is_accepted(self):
        status, _ = self._request("/", host=f"localhost:{self.port}")
        self.assertEqual(status, 200)

    # -- validation ------------------------------------------------------
    def test_generate_with_blank_query_name_is_flagged(self):
        status, html = self._request("/generate", data=self._card(self._csrf(), name=""))
        self.assertEqual(status, 400)
        self.assertIn("Give this query a name.", html)

    def test_overlong_search_name_is_rejected_on_save(self):
        data = self._card(self._csrf()) | {"search_name": "x" * 25}
        status, html = self._request("/save", data=data)
        self.assertEqual(status, 400)
        self.assertIn("20 characters", html)

    def test_overlong_search_name_is_rejected_on_generate(self):
        data = self._card(self._csrf()) | {"search_name": "x" * 25}
        status, html = self._request("/generate", data=data)
        self.assertEqual(status, 400)
        self.assertIn("20 characters", html)

    # -- the collapsed saved-search menu ---------------------------------
    def test_saved_searches_collapse_into_one_menu(self):
        csrf = self._csrf()
        self._request("/save", data=self._card(csrf))
        status, html = self._request("/")
        self.assertEqual(status, 200)
        # One menu control with a count, and the name reachable inside it as
        # the Edit trigger — not a flat row of nav items. Run and Delete sit
        # alongside as their own actions.
        self.assertIn("nav-menu-label", html)
        self.assertIn("Saved searches", html)
        self.assertIn("(1)", html)
        self.assertIn("nav-row-name", html)
        self.assertIn("Morning Briefing", html)
        # Clicking the name opens the editor; Run is a separate action.
        self.assertIn('action="/edit/morning-briefing"', html)
        self.assertIn('action="/run/morning-briefing"', html)

    # -- the whole journey -----------------------------------------------
    def test_save_run_view_prune_delete_round_trip(self):
        csrf = self._csrf()

        # Save: redirected back to the editor, which confirms and lists it.
        status, html = self._request("/save", data=self._card(csrf))
        self.assertEqual(status, 200)
        self.assertIn("Saved “Morning Briefing”", html)
        self.assertIn("Morning Briefing", html)

        # Run it (report generation stubbed): lands on the in-app report.
        with patch("monitoring.webserver.generate_report",
                   return_value=_fake_result(self.reports_dir, "Morning Briefing")):
            status, html = self._request("/run/morning-briefing", data={"csrf": csrf})
        self.assertEqual(status, 200)
        self.assertIn("Budget rises", html)
        self.assertIn("Printable version", html)

        # Prune the only article: the report page now says so.
        status, html = self._request(
            "/report/remove", data={"csrf": csrf, "anchor": "q1", "key": "k1"})
        self.assertEqual(status, 200)
        self.assertIn("No matching articles found", html)
        self.assertNotIn("Budget rises", html)

        # Delete the saved search: the nav empties out.
        status, html = self._request("/delete/morning-briefing", data={"csrf": csrf})
        self.assertEqual(status, 200)
        self.assertIn("Saved searches will appear here.", html)

    def test_stale_feed_warning_shows_in_report_view(self):
        from monitoring.models import FeedFetchResult
        csrf = self._csrf()
        self._request("/save", data=self._card(csrf) | {"search_name": "Daily"})
        result = _fake_result(self.reports_dir, "Daily")
        result.stale.append(FeedFetchResult(
            "bbc", "BBC News", "https://x/rss", ok=True, newest_age_hours=720.0))
        with patch("monitoring.webserver.generate_report", return_value=result):
            status, html = self._request("/run/daily", data={"csrf": csrf})
        self.assertEqual(status, 200)
        self.assertIn("1 feed may be frozen", html)
        self.assertIn("newest item is 30 days old", html)

    def test_report_file_serving_and_traversal_guard(self):
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        good = "report_2026-07-17_12-00-00.html"
        (self.reports_dir / good).write_text("<html>archived</html>", encoding="utf-8")
        status, html = self._request(f"/reports/{good}")
        self.assertEqual(status, 200)
        self.assertIn("archived", html)
        status, _ = self._request("/reports/../config.yaml")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
