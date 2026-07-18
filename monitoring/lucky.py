"""The "I'm feeling lucky" random-search builder.

Pure logic plus one small loader: lucky.yaml holds a categorised pool of
~900 keywords (politicians, leaders, topics, companies); lucky_queries()
rolls 1–5 random queries from it. The random source is injectable so
every rule here is deterministic under test.

Region scaling: a lucky query searches either every outlet of ONE region
or every outlet of ALL regions. The options are built from whatever
regions exist in publications.yaml, so adding a third or fourth region
(Canada, Australia, …) changes nothing here — it simply becomes one more
possible roll.
"""
from __future__ import annotations

import random
from pathlib import Path

from monitoring.config import ConfigError, _load_yaml
from monitoring.constants import (
    DATE_RANGES,
    LUCKY_MAX_QUERIES,
    LUCKY_MIN_QUERIES,
)
from monitoring.models import Publication, Query


def load_keywords(path: str | Path) -> list[str]:
    """The flattened, deduplicated keyword pool from lucky.yaml.

    The file's categories (leaders, uk_mps, …) exist for maintainability
    only; the tool treats them as one pool. Raises ConfigError with a
    plain-English message on any problem.
    """
    data = _load_yaml(path, "the lucky keyword pool")
    raw = data.get("keywords")
    if not isinstance(raw, dict) or not raw:
        raise ConfigError(
            f"'{path}' must have a top-level 'keywords:' mapping of "
            "categories to keyword lists. See lucky.yaml in the repo."
        )
    seen: set[str] = set()
    keywords: list[str] = []
    for category, entries in raw.items():
        if not isinstance(entries, list) or not all(
            isinstance(k, str) and k.strip() for k in entries
        ):
            raise ConfigError(
                f"'{path}': category '{category}' should be a list of "
                "non-empty keywords."
            )
        for keyword in entries:
            keyword = keyword.strip()
            if keyword.casefold() not in seen:
                seen.add(keyword.casefold())
                keywords.append(keyword)
    if not keywords:
        raise ConfigError(f"'{path}' contains no keywords.")
    return keywords


def _region_options(publications: dict[str, Publication]) -> list[list[str]]:
    """The publication-id sets a lucky query may roll: every outlet of one
    region, or every outlet of all regions. With R regions that's R+1
    options — e.g. all-UK, all-US, or everything."""
    by_region: dict[str, list[str]] = {}
    for pub in publications.values():
        by_region.setdefault(pub.region or "Other", []).append(pub.id)
    options = [sorted(ids) for _, ids in sorted(by_region.items())]
    if len(options) > 1:
        options.append(sorted(publications))
    return options


def lucky_queries(
    keywords: list[str],
    publications: dict[str, Publication],
    rng: random.Random | None = None,
) -> list[Query]:
    """Roll a random search: 1–5 queries, each with one distinct keyword
    (doubling as the query's name), a random timeframe, and a randomly
    chosen region scope."""
    rng = rng or random.Random()
    count = rng.randint(LUCKY_MIN_QUERIES, min(LUCKY_MAX_QUERIES, len(keywords)))
    picks = rng.sample(keywords, count)
    regions = _region_options(publications)
    return [
        Query(
            name=keyword,
            keywords=[keyword],
            match="any",
            date_range=rng.choice(list(DATE_RANGES)),
            publications=rng.choice(regions),
        )
        for keyword in picks
    ]
