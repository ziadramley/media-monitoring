"""Saving, listing, and loading named searches.

A "saved search" is a whole stack of queries under one name (e.g.
"Morning briefing" = UK politics + US economy), stored as a single YAML
file in the searches/ folder. The file uses the SAME shape as
config.yaml, so a saved search can equally be run from the command line:

    python monitor.py --config searches/morning-briefing.yaml

Filenames come from user-typed names, so every path that touches disk
goes through _safe_path(), which refuses anything that isn't a plain
slug — a name like "../../config" can never escape the searches folder.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from monitoring.config import ConfigError, build_queries
from monitoring.constants import SEARCHES_DIR
from monitoring.models import Publication, Query

log = logging.getLogger("monitor")

# A slug is lowercase letters, digits and single hyphens — nothing that
# could form a path (no dots, slashes, or spaces). \Z (not $) anchors the
# very end: $ would also match just before a trailing newline, letting
# "foo\n" slip through the strict-slug gate.
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_SLUG_MAX_LEN = 60


@dataclass
class SavedSearch:
    slug: str
    name: str
    queries: list[Query]
    source: str  # "saved" (a file in searches/) or "config" (config.yaml)


def slugify(name: str) -> str:
    """Turn a display name into a safe filename stem. Returns '' if the
    name has nothing usable in it (the caller treats that as invalid)."""
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug[:_SLUG_MAX_LEN].strip("-")


def _safe_path(slug: str, searches_dir: str | Path) -> Path:
    """Resolve a slug to a file inside searches_dir, or raise. The slug
    is validated against a strict pattern AND the resolved path is
    confirmed to sit directly inside the folder — belt and braces."""
    if not _SLUG_RE.match(slug):
        raise ValueError(f"Unsafe or invalid search id: {slug!r}")
    base = Path(searches_dir).resolve()
    path = (base / f"{slug}.yaml").resolve()
    if path.parent != base:
        raise ValueError(f"Search id escapes the searches folder: {slug!r}")
    return path


def _queries_to_raw(queries: list[Query]) -> list[dict]:
    return [
        {
            "name": q.name,
            "keywords": list(q.keywords),
            "match": q.match,
            "date_range": q.date_range,
            "publications": list(q.publications),
        }
        for q in queries
    ]


def save_search(
    name: str, queries: list[Query], searches_dir: str | Path = SEARCHES_DIR
) -> str:
    """Write (or overwrite) a named search. Returns its slug."""
    slug = slugify(name)
    if not slug:
        raise ValueError("Please give the search a name using letters or numbers.")
    path = _safe_path(slug, searches_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"name": name.strip(), "queries": _queries_to_raw(queries)}
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return slug


def load_search(
    slug: str, publications: dict[str, Publication], searches_dir: str | Path = SEARCHES_DIR
) -> SavedSearch:
    """Load one saved search by slug, validating its queries through the
    same rules as config.yaml."""
    path = _safe_path(slug, searches_dir)
    if not path.is_file():
        raise ConfigError(f"No saved search called '{slug}'.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ConfigError(f"Saved search '{slug}' could not be read: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Saved search '{slug}' is not in the expected format.")
    queries = build_queries(data.get("queries") or [], publications)
    name = data.get("name") if isinstance(data.get("name"), str) else slug
    return SavedSearch(slug=slug, name=name, queries=queries, source="saved")


def list_searches(
    publications: dict[str, Publication], searches_dir: str | Path = SEARCHES_DIR
) -> list[SavedSearch]:
    """Every readable saved search, newest name first. Files that fail to
    parse are skipped rather than crashing the panel."""
    base = Path(searches_dir)
    if not base.is_dir():
        return []
    found: list[SavedSearch] = []
    for path in sorted(base.glob("*.yaml")):
        slug = path.stem
        if not _SLUG_RE.match(slug):
            continue
        try:
            found.append(load_search(slug, publications, searches_dir))
        except (ConfigError, ValueError, OSError, yaml.YAMLError):
            continue  # a broken file shouldn't take down the list
    found.sort(key=lambda s: s.name.casefold())
    return found


def delete_search(slug: str, searches_dir: str | Path = SEARCHES_DIR) -> bool:
    """Delete a saved search. Returns True if a file was removed."""
    path = _safe_path(slug, searches_dir)
    if path.is_file():
        path.unlink()
        return True
    return False


def config_as_search(
    config_path: str | Path, publications: dict[str, Publication]
) -> SavedSearch | None:
    """Expose the hand-edited config.yaml as a read-only, loadable search
    so its queries can be pulled into the editor as a starting point.
    Returns None if config.yaml is missing or unreadable."""
    from monitoring.config import load_queries  # local import avoids a cycle at import time

    try:
        queries = load_queries(config_path, publications)
    except Exception as exc:  # best-effort bridge — a bad config.yaml must not blank the panel
        log.warning("Could not offer %s in the editor: %s", config_path, exc)
        return None
    return SavedSearch(slug="__config__", name="config.yaml", queries=queries, source="config")
