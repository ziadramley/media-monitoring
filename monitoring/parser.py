"""Turning messy feed entries into clean Article objects.

RSS in the wild is inconsistent: HTML inside titles, three different
date fields, authors formatted as "email@host (Name)", tracking junk
on URLs. Everything defensive about reading feeds lives here.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from monitoring.constants import (
    STANDFIRST_BOILERPLATE,
    STANDFIRST_MAX_CHARS,
    TRACKING_PARAM_NAMES,
    TRACKING_PARAM_PREFIXES,
)
from monitoring.models import Article, Publication


# Tags that visually separate text: without this, stripping
# "<p>trip</p><p>They" would produce "tripThey".
_BLOCK_TAGS = {
    "p", "br", "div", "li", "ul", "ol", "tr", "td", "th", "table",
    "blockquote", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6",
}


class _TextExtractor(HTMLParser):
    """Collects the text content of HTML, skipping <script>/<style>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def strip_html(value: str | None) -> str:
    """Remove tags and collapse whitespace (feeds are full of newlines
    and non-breaking spaces)."""
    if not value:
        return ""
    extractor = _TextExtractor()
    extractor.feed(value)
    return re.sub(r"\s+", " ", extractor.text()).strip()


def truncate(value: str, limit: int = STANDFIRST_MAX_CHARS) -> str:
    """Trim at a word boundary with an ellipsis."""
    if len(value) <= limit:
        return value
    cut = value[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return cut + "…"


def parse_published(entry) -> datetime | None:
    """Best-effort publication time as an aware LOCAL datetime.

    feedparser normalizes whatever date format the feed used into a UTC
    struct_time under one of three keys (Atom feeds often only have
    'updated'). The tzinfo=utc step matters: naive conversion via
    time.mktime() would silently shift every timestamp by the local
    UTC offset.
    """
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc).astimezone()
            except (ValueError, TypeError):
                continue
    return None


_PARENTHESIZED_NAME = re.compile(r"\(([^)]+)\)\s*$")


def extract_author(entry) -> str | None:
    detail = entry.get("author_detail") or {}
    name = (detail.get("name") or entry.get("author") or "").strip()
    if not name:
        return None
    # RSS 2.0's <author> is formally an email: "a@b.com (Real Name)"
    if "@" in name:
        match = _PARENTHESIZED_NAME.search(name)
        if match:
            name = match.group(1).strip()
        elif " " not in name:
            return None  # a bare email address isn't a byline
    return name or None


def _is_tracking_param(name: str) -> bool:
    lowered = name.lower()
    return lowered in TRACKING_PARAM_NAMES or lowered.startswith(TRACKING_PARAM_PREFIXES)


def normalize_url(url: str) -> str:
    """Canonical form of a URL for duplicate detection.

    Lowercases the host, upgrades http to https, drops the fragment and
    known tracking parameters, and strips the trailing slash — so the
    same article syndicated into two feeds compares equal.
    """
    parts = urlsplit(url.strip())
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(key)
    ]
    return urlunsplit((scheme, netloc, path, urlencode(kept), ""))


def _strip_boilerplate(text: str) -> str:
    """Remove trailing feed boilerplate like the Guardian's
    'Continue reading...' link text."""
    for phrase in STANDFIRST_BOILERPLATE:
        if text.casefold().endswith(phrase.casefold()):
            text = text[: -len(phrase)].rstrip()
    return text


def entry_to_article(entry, publication: Publication) -> Article | None:
    """Normalize one feed entry. Returns None when the entry has no
    usable link (nothing to click means nothing to report)."""
    url = (entry.get("link") or "").strip()
    if not url.startswith("http"):
        return None

    title = strip_html(entry.get("title")) or "(untitled)"

    summary = entry.get("summary")
    if not summary:
        content = entry.get("content") or []
        if content:
            summary = content[0].get("value")
    standfirst = truncate(_strip_boilerplate(strip_html(summary))) or None
    if standfirst and standfirst.casefold() == title.casefold():
        standfirst = None  # some feeds repeat the headline as the summary

    author = extract_author(entry)
    if author and author.casefold() == publication.name.casefold():
        author = None  # some outlets credit themselves (e.g. NYT live blogs)

    return Article(
        title=title,
        url=url,
        dedupe_key=normalize_url(url),
        publication_id=publication.id,
        publication_name=publication.name,
        author=author,
        published=parse_published(entry),
        standfirst=standfirst,
    )
