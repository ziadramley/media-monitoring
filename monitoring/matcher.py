"""Deciding which articles match which queries.

Pure functions only — no network, no display — so every rule in here
is unit-testable. The matching rules:

* case-insensitive, in the headline OR the standfirst
* multi-word keywords are exact phrases
* whole words only ("AI" must not match inside "said"), implemented
  with lookarounds rather than \\b because \\b misfires when a keyword
  starts or ends with a non-word character ("C++", "S&P")
* curly quotes normalized to straight ones on both sides, so a keyword
  typed as "labour's" still matches a feed's typographic apostrophe
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from monitoring.constants import DATE_RANGES
from monitoring.models import Article, Query

_QUOTES = str.maketrans({
    "‘": "'", "’": "'",   # curly single quotes
    "“": '"', "”": '"',   # curly double quotes
})


def normalize_text(text: str) -> str:
    return text.translate(_QUOTES).casefold()


def compile_keyword(keyword: str) -> re.Pattern[str]:
    """One phrase pattern, tolerant of any whitespace between words
    (feeds contain non-breaking spaces and newlines)."""
    words = [re.escape(word) for word in normalize_text(keyword).split()]
    phrase = r"\s+".join(words)
    return re.compile(rf"(?<!\w){phrase}(?!\w)")


def article_matches(article: Article, patterns: list[re.Pattern[str]], match: str) -> bool:
    haystack = normalize_text(article.title)
    if article.standfirst:
        haystack += "\n" + normalize_text(article.standfirst)
    if match == "all":
        return all(p.search(haystack) for p in patterns)
    return any(p.search(haystack) for p in patterns)


def within_window(article: Article, window_start: datetime) -> bool:
    """Undated articles pass (they're labeled 'date unknown' rather
    than silently dropped). No upper bound: a future-dated article is
    publisher clock skew, not a reason to hide it."""
    if article.published is None:
        return True
    return article.published >= window_start


def sort_key(article: Article):
    """Newest first, undated last, then deterministic tie-breaks."""
    if article.published is None:
        return (1, 0.0, article.publication_name, article.title)
    return (0, -article.published.timestamp(), article.publication_name, article.title)


def filter_articles(
    query: Query,
    articles_by_publication: dict[str, list[Article]],
    now: datetime,
) -> list[Article]:
    """All articles matching one query, deduplicated and sorted."""
    patterns = [compile_keyword(k) for k in query.keywords]
    window_start = now - timedelta(hours=DATE_RANGES[query.date_range])

    matched: list[Article] = []
    seen: set[str] = set()
    for pub_id in query.publications:
        for article in articles_by_publication.get(pub_id, []):
            if not within_window(article, window_start):
                continue
            if not article_matches(article, patterns, query.match):
                continue
            if article.dedupe_key in seen:
                continue
            seen.add(article.dedupe_key)
            matched.append(article)
    return sorted(matched, key=sort_key)
