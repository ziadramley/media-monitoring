"""Assembling and rendering a report — the output of running a search
at a specific date and time.

The only module that touches Jinja2 — everything upstream deals in
plain data.
"""
from __future__ import annotations

import logging
import webbrowser
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from monitoring.constants import (
    DATE_RANGES,
    DEPTH_CAVEAT_RANGES,
    REPORT_FILENAME_FORMAT,
    REPORTS_DIR,
)
from monitoring.models import Article, FeedFetchResult

log = logging.getLogger("monitor")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


@dataclass
class ReportSection:
    """One rendered section of the report (normally one query)."""
    name: str
    anchor: str
    articles: list[Article]
    range_label: str        # e.g. "past 24 hours"
    show_depth_note: bool
    keywords: list[str]
    match: str              # "any" or "all"


def make_range_label(date_range: str) -> str:
    return f"past {DATE_RANGES[date_range]} hours"


def needs_depth_note(date_range: str) -> bool:
    return date_range in DEPTH_CAVEAT_RANGES


def format_datetime(value: datetime | None, with_time: bool = True) -> str:
    """'16 July 2026, 14:02' — built without %-d, which Windows lacks."""
    if value is None:
        return "date unknown"
    text = f"{value.day} {value.strftime('%B %Y')}"
    if with_time:
        text += value.strftime(", %H:%M")
    return text


def format_day(value: datetime) -> str:
    return f"{value.strftime('%A')} {value.day} {value.strftime('%B %Y')}"


# --- pruning -----------------------------------------------------------

def apply_removals(
    sections: list[ReportSection],
    removed: set[tuple[str, str]],
) -> list[ReportSection]:
    """Sections with the user's removed articles filtered out.

    `removed` holds (section anchor, article dedupe_key) pairs — the pair
    is needed because the same article can legitimately appear in two
    sections and removal targets just one. Returns shallow copies; the
    originals (the stashed report) are never mutated. A fully-pruned
    section stays present so the report still says
    "No matching articles found" rather than losing the section.
    """
    if not removed:
        return sections
    return [
        replace(section, articles=[
            a for a in section.articles
            if (section.anchor, a.dedupe_key) not in removed
        ])
        for section in sections
    ]


# --- HTML --------------------------------------------------------------

def render_html(
    sections: list[ReportSection],
    failed_feeds: list[FeedFetchResult],
    generated_at: datetime,
    report_name: str | None = None,
    publications: int = 0,
) -> str:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    )
    env.filters["datefmt"] = format_datetime
    return env.get_template("report.html.j2").render(
        sections=sections,
        failed_feeds=failed_feeds,
        generated_at=generated_at,
        generated_day=format_day(generated_at),
        total_articles=sum(len(s.articles) for s in sections),
        report_name=report_name or "Media Monitoring",
        publications=publications,
    )


def write_report(html: str, generated_at: datetime, reports_dir: str | Path = REPORTS_DIR) -> Path:
    out_dir = Path(reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / generated_at.strftime(REPORT_FILENAME_FORMAT)
    path.write_text(html, encoding="utf-8")
    log.info("Report written to %s", path)
    return path


def open_in_browser(path: Path) -> None:
    opened = False
    try:
        opened = webbrowser.open(path.resolve().as_uri())
    except Exception as exc:
        log.warning("Could not open a browser (%s).", exc)
    if not opened:
        log.info("Open the report manually: %s", path.resolve())
