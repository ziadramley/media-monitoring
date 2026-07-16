"""The data model: what a publication, query, and article look like.

These dataclasses are the contract between every other module —
the fetcher produces Articles, the matcher filters them, the report
displays them. If a field isn't here, it doesn't exist downstream.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Publication:
    """One outlet in the registry. A publication can have several
    feeds (front page + politics, say); their articles get merged."""
    id: str
    name: str
    feeds: list[str]


@dataclass
class Query:
    """One saved search from config.yaml."""
    name: str
    keywords: list[str]
    match: str                # "any" or "all"
    date_range: str           # key into constants.DATE_RANGES
    publications: list[str]   # resolved publication ids (never "all" here)


@dataclass
class Article:
    """One headline, normalized from whatever shape the feed had."""
    title: str
    url: str
    dedupe_key: str           # normalized URL used to spot duplicates
    publication_id: str
    publication_name: str
    author: str | None        # many feeds don't provide one
    published: datetime | None  # timezone-aware local time; None = unknown
    standfirst: str | None    # HTML-stripped, truncated summary


@dataclass
class FeedFetchResult:
    """What happened when we fetched one feed URL — kept for the
    terminal log and the report's warnings box."""
    publication_id: str
    publication_name: str
    feed_url: str
    ok: bool
    error: str | None = None
    articles: list[Article] = field(default_factory=list)
    fetch_seconds: float = 0.0
    newest_age_hours: float | None = None  # age of newest item; makes feed rot visible
