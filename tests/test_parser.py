"""Feed-entry normalization: run with  python -m unittest  from the repo root."""
import unittest

from monitoring.models import Publication
from monitoring.parser import (
    entry_to_article,
    extract_author,
    normalize_url,
    parse_published,
    strip_html,
    truncate,
)

PUB = Publication(id="pub", name="The Pub", feeds=[])


class StripHtml(unittest.TestCase):
    def test_paragraphs_do_not_collide(self):
        self.assertEqual(
            strip_html("<p>trip</p><p>They found</p>"),
            "trip They found",
        )

    def test_entities_decode(self):
        self.assertEqual(strip_html("Fish &amp; Chips &#8211; a review"), "Fish & Chips – a review")

    def test_script_and_style_dropped(self):
        self.assertEqual(strip_html("<script>alert(1)</script>News<style>p{}</style>"), "News")

    def test_whitespace_collapsed(self):
        self.assertEqual(strip_html("a\n\n  b  c"), "a b c")


class Truncate(unittest.TestCase):
    def test_short_text_untouched(self):
        self.assertEqual(truncate("short", 10), "short")

    def test_cuts_at_word_boundary_with_ellipsis(self):
        result = truncate("one two three four", 12)
        self.assertEqual(result, "one two…")


class Authors(unittest.TestCase):
    def test_rss2_email_format(self):
        self.assertEqual(extract_author({"author": "j.doe@example.com (Jane Doe)"}), "Jane Doe")

    def test_bare_email_is_not_a_byline(self):
        self.assertIsNone(extract_author({"author": "newsdesk@example.com"}))

    def test_author_detail_name_preferred(self):
        entry = {"author_detail": {"name": "Jane Doe"}, "author": "someone else"}
        self.assertEqual(extract_author(entry), "Jane Doe")

    def test_missing_author(self):
        self.assertIsNone(extract_author({}))

    def test_outlet_crediting_itself_suppressed(self):
        entry = {"title": "T", "link": "https://x.com/a", "author": "The Pub"}
        article = entry_to_article(entry, PUB)
        self.assertIsNone(article.author)


class NormalizeUrl(unittest.TestCase):
    def test_tracking_params_stripped_content_params_kept(self):
        self.assertEqual(
            normalize_url("http://X.com/story/?id=7&utm_source=rss&at_medium=RSS&ito=1490"),
            "https://x.com/story?id=7",
        )

    def test_equivalent_urls_compare_equal(self):
        a = normalize_url("https://x.com/story/")
        b = normalize_url("http://X.COM/story?utm_campaign=feed")
        self.assertEqual(a, b)


class Dates(unittest.TestCase):
    def test_fallback_chain_uses_updated(self):
        entry = {"updated_parsed": (2026, 7, 16, 10, 30, 0, 3, 197, 0)}
        parsed = parse_published(entry)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.astimezone().year, 2026)

    def test_no_dates_returns_none(self):
        self.assertIsNone(parse_published({}))


class EntryToArticle(unittest.TestCase):
    def test_entry_without_link_is_skipped(self):
        self.assertIsNone(entry_to_article({"title": "No link"}, PUB))

    def test_untitled_placeholder(self):
        article = entry_to_article({"link": "https://x.com/a"}, PUB)
        self.assertEqual(article.title, "(untitled)")

    def test_standfirst_equal_to_title_suppressed(self):
        entry = {"title": "Same text", "summary": "Same text", "link": "https://x.com/a"}
        self.assertIsNone(entry_to_article(entry, PUB).standfirst)

    def test_guardian_boilerplate_stripped(self):
        entry = {
            "title": "T",
            "summary": "<p>Real summary.</p> <a href='#'>Continue reading...</a>",
            "link": "https://x.com/a",
        }
        self.assertEqual(entry_to_article(entry, PUB).standfirst, "Real summary.")


if __name__ == "__main__":
    unittest.main()
