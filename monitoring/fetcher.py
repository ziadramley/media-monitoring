"""Fetching feeds concurrently, but politely.

We fetch the bytes ourselves with urllib (so we control the timeout and
User-Agent) and hand them to feedparser to interpret. One feed failing
never stops the run: it becomes a warning in the terminal and a note in
the report.
"""
from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser

from monitoring.constants import (
    FETCH_RETRIES,
    FETCH_RETRY_DELAY_SECONDS,
    FETCH_TIMEOUT_SECONDS,
    FROZEN_FEED_THRESHOLD_HOURS,
    MAX_CONCURRENT_FETCHES,
    MAX_FEED_BYTES,
    USER_AGENT,
)
from monitoring.models import Article, FeedFetchResult, Publication
from monitoring.parser import entry_to_article

log = logging.getLogger("mimi")


class FeedTooLarge(Exception):
    """The response exceeded MAX_FEED_BYTES — not a real feed."""


def _fetch_bytes(url: str) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    })
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        # Read at most one byte over the cap: a full read() would let a
        # misconfigured URL (or a hostile server) allocate without limit.
        body = response.read(MAX_FEED_BYTES + 1)
        if len(body) > MAX_FEED_BYTES:
            raise FeedTooLarge()
        # feedparser uses these for encoding detection and resolving
        # relative URLs, so pass along what the server actually said.
        headers = {
            "content-location": response.geturl(),
            "content-type": response.headers.get("Content-Type", ""),
        }
    return body, headers


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, FeedTooLarge):
        return f"feed is too large (over {MAX_FEED_BYTES // 1_000_000} MB) — probably not a feed"
    if isinstance(exc, urllib.error.HTTPError):
        return f"server refused the request (HTTP {exc.code} {exc.reason})"
    if isinstance(exc, TimeoutError):
        return f"timed out after {FETCH_TIMEOUT_SECONDS}s"
    if isinstance(exc, urllib.error.URLError):
        if isinstance(exc.reason, TimeoutError):
            return f"timed out after {FETCH_TIMEOUT_SECONDS}s"
        return f"could not connect ({exc.reason})"
    return str(exc) or type(exc).__name__


def _is_retryable(exc: Exception) -> bool:
    """Transient failures worth one more try: timeouts, connection
    problems, server errors, and 403 (bot protection often refuses one
    request and accepts the next). Other 4xx (404, 410…) are permanent."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 403 or exc.code >= 500
    return isinstance(exc, (TimeoutError, urllib.error.URLError, ConnectionError))


def _fetch_bytes_with_retry(url: str) -> tuple[bytes, dict[str, str]]:
    for attempt in range(FETCH_RETRIES + 1):
        try:
            return _fetch_bytes(url)
        except Exception as exc:
            if attempt < FETCH_RETRIES and _is_retryable(exc):
                log.debug("%s: %s — retrying in %ds",
                          url, _friendly_error(exc), FETCH_RETRY_DELAY_SECONDS)
                time.sleep(FETCH_RETRY_DELAY_SECONDS)
                continue
            raise


def _looks_like_html(body: bytes) -> bool:
    head = body[:300].lstrip().lower()
    return head.startswith((b"<!doctype", b"<html"))


def fetch_feed(publication: Publication, feed_url: str) -> FeedFetchResult:
    """Fetch and parse a single feed. Never raises."""
    started = time.monotonic()
    result = FeedFetchResult(
        publication_id=publication.id,
        publication_name=publication.name,
        feed_url=feed_url,
        ok=False,
    )
    try:
        body, headers = _fetch_bytes_with_retry(feed_url)
    except Exception as exc:  # any network problem: report, don't crash
        result.error = _friendly_error(exc)
        result.fetch_seconds = time.monotonic() - started
        return result

    parsed = feedparser.parse(body, response_headers=headers)
    entries = parsed.get("entries") or []

    if not entries:
        # feedparser's "bozo" flag alone isn't failure — plenty of
        # slightly-malformed feeds parse fine. Zero entries is.
        if _looks_like_html(body):
            result.error = "returned a web page instead of an RSS feed"
        elif parsed.get("bozo"):
            result.error = f"feed could not be parsed ({parsed.get('bozo_exception')})"
        else:
            result.error = "feed contained no items"
        result.fetch_seconds = time.monotonic() - started
        return result

    if parsed.get("bozo"):
        log.debug(
            "%s: minor formatting issues but parsed fine (%s)",
            feed_url, parsed.get("bozo_exception"),
        )

    skipped_no_link = 0
    articles: list[Article] = []
    for entry in entries:
        article = entry_to_article(entry, publication)
        if article is None:
            skipped_no_link += 1
        else:
            articles.append(article)

    result.ok = True
    result.articles = articles
    result.fetch_seconds = time.monotonic() - started

    dates = [a.published for a in articles if a.published]
    if dates:
        newest = max(dates)
        now = datetime.now(timezone.utc).astimezone()
        result.newest_age_hours = (now - newest).total_seconds() / 3600

    if skipped_no_link:
        log.warning("%s: skipped %d item(s) with no usable link", feed_url, skipped_no_link)
    return result


def fetch_all(
    publications: list[Publication],
) -> tuple[dict[str, list[Article]], list[FeedFetchResult]]:
    """Fetch every feed of every publication concurrently.

    Returns (articles per publication id — merged across the
    publication's feeds with duplicates removed, all fetch results).
    """
    jobs = [(pub, url) for pub in publications for url in pub.feeds]
    log.info("Fetching %d feeds from %d publications…", len(jobs), len(publications))

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_FETCHES) as pool:
        results = list(pool.map(lambda job: fetch_feed(*job), jobs))

    articles_by_publication: dict[str, list[Article]] = {}
    seen_keys: dict[str, set[str]] = {}
    total = 0
    for res in results:
        if res.ok:
            age = ""
            if res.newest_age_hours is not None:
                age = f", newest item {res.newest_age_hours:.1f}h old"
            log.info(
                "  ok    %-58s %3d items in %.1fs%s",
                res.feed_url, len(res.articles), res.fetch_seconds, age,
            )
            if (res.newest_age_hours or 0) > FROZEN_FEED_THRESHOLD_HOURS:
                log.warning(
                    "  %s: newest item is %.0f days old — this feed may be "
                    "frozen or abandoned; consider replacing it in "
                    "publications.yaml",
                    res.feed_url, res.newest_age_hours / 24,
                )
        else:
            log.warning("  FAIL  %-58s %s", res.feed_url, res.error)

        bucket = articles_by_publication.setdefault(res.publication_id, [])
        seen = seen_keys.setdefault(res.publication_id, set())
        for article in res.articles:
            if article.dedupe_key in seen:
                continue
            seen.add(article.dedupe_key)
            bucket.append(article)
            total += 1

    failed = sum(1 for r in results if not r.ok)
    log.info(
        "Fetched %d unique articles from %d feeds (%d failed).",
        total, len(jobs) - failed, failed,
    )
    return articles_by_publication, results
