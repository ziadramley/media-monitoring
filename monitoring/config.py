"""Loading and validating config.yaml and publications.yaml.

Everything is checked up front with plain-English error messages —
a comms person editing YAML deserves better than a stack trace.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from monitoring.constants import DATE_RANGES
from monitoring.models import Publication, Query


class ConfigError(Exception):
    """A problem in one of the YAML files, described in plain English."""


def _load_yaml(path: str | Path, what: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise ConfigError(
            f"Can't find {what} at '{p}'. Are you running from the project "
            f"folder? (Expected a file called '{p.name}' there.)"
        )
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(
            f"'{p}' isn't a UTF-8 text file — please save it as plain UTF-8."
        ) from exc
    except OSError as exc:
        raise ConfigError(f"'{p}' could not be read: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"'{p}' isn't valid YAML: {exc}\n"
            "Tip: YAML is picky about indentation — use spaces, not tabs."
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(f"'{p}' should contain a YAML mapping, not {type(data).__name__}.")
    return data


def load_publications(path: str | Path) -> dict[str, Publication]:
    data = _load_yaml(path, "the publication registry")
    raw = data.get("publications")
    if not isinstance(raw, dict) or not raw:
        raise ConfigError(
            f"'{path}' must have a top-level 'publications:' mapping of "
            "short ids to outlets. See the README for the format."
        )

    publications: dict[str, Publication] = {}
    for pub_id, entry in raw.items():
        if not isinstance(entry, dict):
            raise ConfigError(f"Publication '{pub_id}' should be a mapping with 'name' and 'feeds'.")
        name = entry.get("name")
        feeds = entry.get("feeds")
        if not name or not isinstance(name, str):
            raise ConfigError(f"Publication '{pub_id}' is missing a 'name'.")
        if not isinstance(feeds, list) or not feeds or not all(
            isinstance(f, str) and f.startswith("http") for f in feeds
        ):
            raise ConfigError(
                f"Publication '{pub_id}' needs a 'feeds' list of one or more "
                "http(s) feed URLs."
            )
        region = entry.get("region")
        publications[str(pub_id)] = Publication(
            id=str(pub_id),
            name=name,
            feeds=feeds,
            region=region if isinstance(region, str) else None,
        )
    return publications


def load_queries(path: str | Path, publications: dict[str, Publication]) -> list[Query]:
    data = _load_yaml(path, "your search config")
    raw = data.get("queries")
    if not isinstance(raw, list) or not raw:
        raise ConfigError(
            f"'{path}' must have a top-level 'queries:' list with at least "
            "one query. See config.yaml in the repo for a working example."
        )
    return build_queries(raw, publications)


def build_queries(raw: list, publications: dict[str, Publication]) -> list[Query]:
    """Validate a list of raw query mappings into Query objects.

    Shared by config.yaml loading and saved-search loading, so both go
    through exactly the same validation rules. Raises ConfigError with a
    plain-English message on the first problem.
    """
    valid_ids = sorted(publications)
    queries: list[Query] = []
    for i, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise ConfigError(f"Query #{i} should be a mapping (name, keywords, ...).")
        name = entry.get("name") or f"Query {i}"

        keywords = entry.get("keywords")
        if not isinstance(keywords, list) or not keywords or not all(
            isinstance(k, str) and k.strip() for k in keywords
        ):
            raise ConfigError(
                f"Query '{name}' needs a 'keywords' list with at least one "
                "non-empty keyword or phrase."
            )
        keywords = [k.strip() for k in keywords]

        match = str(entry.get("match", "any")).lower()
        if match not in ("any", "all"):
            raise ConfigError(
                f"Query '{name}': 'match' must be 'any' or 'all', not '{match}'."
            )

        date_range = str(entry.get("date_range", "past_24_hours"))
        if date_range not in DATE_RANGES:
            options = ", ".join(sorted(DATE_RANGES))
            raise ConfigError(
                f"Query '{name}': 'date_range' must be one of {options}, "
                f"not '{date_range}'."
            )

        pubs = entry.get("publications", "all")
        if pubs == "all" or pubs == ["all"]:
            resolved = list(valid_ids)
        elif isinstance(pubs, list) and pubs and all(isinstance(p, str) for p in pubs):
            unknown = [p for p in pubs if p not in publications]
            if unknown:
                raise ConfigError(
                    f"Query '{name}' references unknown publication(s): "
                    f"{', '.join(unknown)}.\n"
                    f"Valid ids are: {', '.join(valid_ids)}."
                )
            resolved = pubs
        else:
            raise ConfigError(
                f"Query '{name}': 'publications' must be a list of publication "
                "ids, or the word 'all'."
            )

        queries.append(Query(
            name=str(name),
            keywords=keywords,
            match=match,
            date_range=date_range,
            publications=resolved,
        ))
    return queries


def load_config(
    config_path: str | Path, publications_path: str | Path
) -> tuple[list[Query], dict[str, Publication]]:
    """Load both files. Returns (queries, publications registry)."""
    publications = load_publications(publications_path)
    queries = load_queries(config_path, publications)
    return queries, publications
