"""Rules of matching: run with  python -m unittest  from the repo root."""
import unittest
from datetime import datetime, timedelta, timezone

from monitoring.matcher import (
    article_matches,
    compile_keyword,
    filter_articles,
    sort_key,
    within_window,
)
from monitoring.models import Article, Query


def make_article(title="", standfirst=None, published=None, url="https://x.com/a",
                 dedupe_key=None, pub_id="pub", pub_name="Pub"):
    return Article(
        title=title, url=url, dedupe_key=dedupe_key or url,
        publication_id=pub_id, publication_name=pub_name,
        author=None, published=published, standfirst=standfirst,
    )


def matches(keyword, title, standfirst=None, match="any"):
    return article_matches(make_article(title, standfirst), [compile_keyword(keyword)], match)


class KeywordMatching(unittest.TestCase):
    def test_case_insensitive(self):
        self.assertTrue(matches("budget", "BUDGET day looms"))

    def test_phrase_must_be_exact(self):
        self.assertTrue(matches("spending review", "The Spending Review lands"))
        self.assertFalse(matches("spending review", "spending under review"))

    def test_whole_words_only(self):
        self.assertFalse(matches("AI", "The minister said so"))   # "said" contains "ai"
        self.assertTrue(matches("AI", "New AI rules proposed"))
        self.assertTrue(matches("AI", "An AI-powered tool"))       # hyphen is a boundary

    def test_keyword_with_symbols(self):
        self.assertTrue(matches("S&P", "S&P 500 rallies"))         # \b would fail here

    def test_curly_apostrophes_normalized(self):
        self.assertTrue(matches("labour's plan", "Labour’s plan under fire"))

    def test_matches_standfirst_too(self):
        self.assertTrue(matches("fiscal", "Quiet day", "A fiscal storm brews"))

    def test_phrase_tolerates_odd_whitespace(self):
        self.assertTrue(matches("spending review", "Spending review lands"))

    def test_any_vs_all(self):
        patterns = [compile_keyword("budget"), compile_keyword("fiscal")]
        a = make_article("Budget day", "A fiscal storm")
        b = make_article("Budget day", "Sunny outlook")
        self.assertTrue(article_matches(a, patterns, "all"))
        self.assertFalse(article_matches(b, patterns, "all"))
        self.assertTrue(article_matches(b, patterns, "any"))


class DateWindows(unittest.TestCase):
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)

    def window(self, hours):
        return self.now - timedelta(hours=hours)

    def test_inside_and_outside_window(self):
        fresh = make_article(published=self.now - timedelta(hours=23))
        stale = make_article(published=self.now - timedelta(hours=25))
        self.assertTrue(within_window(fresh, self.window(24)))
        self.assertFalse(within_window(stale, self.window(24)))

    def test_undated_articles_are_kept(self):
        self.assertTrue(within_window(make_article(published=None), self.window(24)))

    def test_future_dated_articles_are_kept(self):
        skewed = make_article(published=self.now + timedelta(hours=2))
        self.assertTrue(within_window(skewed, self.window(24)))


class FilteringAndSorting(unittest.TestCase):
    now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)

    def query(self, **overrides):
        base = dict(name="q", keywords=["budget"], match="any",
                    date_range="past_24_hours", publications=["pub"])
        base.update(overrides)
        return Query(**base)

    def test_deduplicates_by_key_within_section(self):
        a1 = make_article("Budget rises", published=self.now, dedupe_key="k1", url="https://x.com/1")
        a2 = make_article("Budget rises", published=self.now, dedupe_key="k1", url="https://x.com/1?utm_source=rss")
        result = filter_articles(self.query(), {"pub": [a1, a2]}, self.now)
        self.assertEqual(len(result), 1)

    def test_sorted_newest_first_undated_last(self):
        older = make_article("Budget A", published=self.now - timedelta(hours=3), dedupe_key="a")
        newer = make_article("Budget B", published=self.now - timedelta(hours=1), dedupe_key="b")
        undated = make_article("Budget C", published=None, dedupe_key="c")
        result = filter_articles(self.query(), {"pub": [older, undated, newer]}, self.now)
        self.assertEqual([a.title for a in result], ["Budget B", "Budget A", "Budget C"])

    def test_only_listed_publications_searched(self):
        a = make_article("Budget", published=self.now, pub_id="other")
        result = filter_articles(self.query(), {"other": [a]}, self.now)
        self.assertEqual(result, [])

    def test_sort_key_is_deterministic_for_ties(self):
        t = self.now
        a = make_article("Alpha", published=t, pub_name="AAA", dedupe_key="a")
        b = make_article("Beta", published=t, pub_name="BBB", dedupe_key="b")
        self.assertLess(sort_key(a), sort_key(b))


if __name__ == "__main__":
    unittest.main()
