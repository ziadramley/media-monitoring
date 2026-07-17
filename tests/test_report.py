"""Report pruning: run with  python -m unittest  from the repo root."""
import unittest
from datetime import datetime, timezone

from monitoring.models import Article
from monitoring.report import ReportSection, apply_removals, render_html

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


def make_article(key: str, title: str = "") -> Article:
    return Article(
        title=title or key, url=f"https://x.com/{key}", dedupe_key=key,
        publication_id="bbc", publication_name="BBC News",
        author=None, published=NOW, standfirst=None,
    )


def make_section(anchor: str, keys: list[str]) -> ReportSection:
    return ReportSection(
        name=anchor.upper(), anchor=anchor,
        articles=[make_article(k) for k in keys],
        range_label="past 24 hours", show_depth_note=False,
        keywords=["k"], match="any",
    )


class ApplyRemovals(unittest.TestCase):
    def test_removes_only_the_targeted_pair(self):
        # The same article (same dedupe_key) sits in BOTH sections;
        # removal from q1 must leave q2's copy alone.
        sections = [make_section("q1", ["a", "b"]), make_section("q2", ["a"])]
        pruned = apply_removals(sections, {("q1", "a")})
        self.assertEqual([x.dedupe_key for x in pruned[0].articles], ["b"])
        self.assertEqual([x.dedupe_key for x in pruned[1].articles], ["a"])

    def test_originals_never_mutated(self):
        sections = [make_section("q1", ["a", "b"])]
        apply_removals(sections, {("q1", "a")})
        self.assertEqual(len(sections[0].articles), 2)

    def test_empty_set_is_a_noop(self):
        sections = [make_section("q1", ["a"])]
        self.assertIs(apply_removals(sections, set()), sections)

    def test_unknown_key_is_a_noop(self):
        sections = [make_section("q1", ["a"])]
        pruned = apply_removals(sections, {("q1", "ghost"), ("q9", "a")})
        self.assertEqual(len(pruned[0].articles), 1)

    def test_fully_pruned_section_stays_present(self):
        sections = [make_section("q1", ["a"]), make_section("q2", ["b"])]
        pruned = apply_removals(sections, {("q1", "a")})
        self.assertEqual(len(pruned), 2)
        self.assertEqual(pruned[0].articles, [])


class PrunedRender(unittest.TestCase):
    def test_portable_file_reflects_pruning(self):
        sections = [make_section("q1", ["keep-me", "drop-me"])]
        pruned = apply_removals(sections, {("q1", "drop-me")})
        html = render_html(pruned, [], NOW, report_name="Pruned", publications=1)
        self.assertIn("keep-me", html)
        self.assertNotIn("drop-me", html)
        self.assertIn("1 result", html)  # count recomputed from pruned set

    def test_empty_after_pruning_says_no_matches(self):
        sections = [make_section("q1", ["only"])]
        pruned = apply_removals(sections, {("q1", "only")})
        html = render_html(pruned, [], NOW, report_name="Empty", publications=1)
        self.assertIn("No matching articles found", html)
        self.assertIn("0 results", html)


if __name__ == "__main__":
    unittest.main()
