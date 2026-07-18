"""Feed fetching without the network: run with  python -m unittest .

_fetch_bytes is stubbed with canned bytes (or canned failures) so every
error path the fetcher promises — HTML instead of a feed, unparseable
XML, timeouts, oversized responses, the retry — is actually exercised.
"""
import io
import unittest
import urllib.error
from unittest.mock import patch

from monitoring.constants import FETCH_RETRIES
from monitoring.fetcher import FeedTooLarge, _is_retryable, fetch_feed
from monitoring.models import Publication

PUB = Publication(id="pub", name="The Pub", feeds=["https://x.com/rss"])
URL = "https://x.com/rss"


def http_error(code: int, reason: str) -> urllib.error.HTTPError:
    # A real body object, so cleanup doesn't raise ResourceWarnings.
    return urllib.error.HTTPError(URL, code, reason, None, io.BytesIO(b""))

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
<item><title>Budget rises</title><link>https://x.com/1</link>
<pubDate>Thu, 16 Jul 2026 10:00:00 GMT</pubDate></item>
<item><title>No link, gets skipped</title></item>
</channel></rss>"""

HEADERS = {"content-location": URL, "content-type": "application/rss+xml"}


def fetch_with(side_effect):
    """Run fetch_feed with _fetch_bytes stubbed and retry sleeps skipped."""
    with patch("monitoring.fetcher._fetch_bytes", side_effect=side_effect) as stub, \
         patch("monitoring.fetcher.time.sleep"):
        result = fetch_feed(PUB, URL)
    return result, stub


class FetchFeed(unittest.TestCase):
    def test_valid_feed_parses(self):
        result, _ = fetch_with([(RSS, HEADERS)])
        self.assertTrue(result.ok)
        self.assertEqual([a.title for a in result.articles], ["Budget rises"])
        self.assertIsNotNone(result.newest_age_hours)
        self.assertGreater(result.newest_age_hours, 0)

    def test_html_page_is_a_clear_error(self):
        result, _ = fetch_with([(b"<!DOCTYPE html><html><body>news site</body></html>", HEADERS)])
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "returned a web page instead of an RSS feed")

    def test_unparseable_body_is_a_clear_error(self):
        result, _ = fetch_with([(b"certainly not a feed", HEADERS)])
        self.assertFalse(result.ok)
        self.assertIn("could not be parsed", result.error)

    def test_timeout_becomes_friendly_error(self):
        result, stub = fetch_with(TimeoutError())
        self.assertFalse(result.ok)
        self.assertIn("timed out", result.error)
        # A timeout is transient, so it was retried before giving up.
        self.assertEqual(stub.call_count, FETCH_RETRIES + 1)

    def test_http_404_fails_without_retry(self):
        result, stub = fetch_with(http_error(404, "Not Found"))
        self.assertFalse(result.ok)
        self.assertIn("HTTP 404", result.error)
        self.assertEqual(stub.call_count, 1)

    def test_oversized_response_fails_without_retry(self):
        result, stub = fetch_with(FeedTooLarge())
        self.assertFalse(result.ok)
        self.assertIn("too large", result.error)
        self.assertEqual(stub.call_count, 1)

    def test_transient_failure_then_success(self):
        result, stub = fetch_with([TimeoutError(), (RSS, HEADERS)])
        self.assertTrue(result.ok)
        self.assertEqual(len(result.articles), 1)
        self.assertEqual(stub.call_count, 2)


class Retryability(unittest.TestCase):
    def test_transient_errors_are_retryable(self):
        for exc in (
            TimeoutError(),
            urllib.error.URLError(ConnectionResetError()),
            http_error(403, "Forbidden"),
            http_error(503, "Unavailable"),
        ):
            self.assertTrue(_is_retryable(exc), exc)

    def test_permanent_errors_are_not(self):
        for exc in (
            http_error(404, "Not Found"),
            http_error(410, "Gone"),
            FeedTooLarge(),
            ValueError("boom"),
        ):
            self.assertFalse(_is_retryable(exc), exc)


if __name__ == "__main__":
    unittest.main()
