"""Assembling and rendering the report.

The only module that touches Jinja2 — everything upstream deals in
plain data. Also builds the Markdown twin of the report, which is
embedded in the HTML so the download button works offline, even if
the file is emailed around on its own.
"""
from __future__ import annotations

import logging
import webbrowser
from dataclasses import dataclass
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


# --- Markdown twin -----------------------------------------------------
# Format contract: H1 title, one H2 per section with match count and
# range, one list item per article (bold headline, meta line, indented
# standfirst, bare URL). Failed feeds under a final H2.

def build_markdown(
    sections: list[ReportSection],
    failed_feeds: list[FeedFetchResult],
    generated_at: datetime,
    report_name: str | None = None,
    publications: int = 0,
) -> str:
    total = sum(len(s.articles) for s in sections)
    meta = f"Generated {format_day(generated_at)} at {generated_at.strftime('%H:%M')}"
    if publications:
        meta += f" · {publications} publication{'s' if publications != 1 else ''}"
    meta += f" · {total} result{'s' if total != 1 else ''}"
    lines: list[str] = [
        f"# {report_name or 'Media Monitoring'}",
        "",
        meta,
        "",
    ]
    for section in sections:
        count = len(section.articles)
        lines.append(f"## {section.name} ({count} match{'es' if count != 1 else ''}, {section.range_label})")
        lines.append("")
        keyword_list = ", ".join(f'"{k}"' for k in section.keywords)
        if keyword_list:
            lines.append(f"Keywords ({section.match}): {keyword_list}")
            lines.append("")
        if not section.articles:
            lines.append("No matching articles found.")
            lines.append("")
            continue
        for a in section.articles:
            meta = a.publication_name
            if a.author:
                meta += f" — {a.author}"
            meta += f" — {format_datetime(a.published)}"
            lines.append(f"- **{a.title}**  ")
            lines.append(f"  {meta}  ")
            if a.standfirst:
                lines.append(f"  {a.standfirst}  ")
            lines.append(f"  <{a.url}>")
            lines.append("")
    if failed_feeds:
        lines.append("## Feeds not reached this run")
        lines.append("")
        for f in failed_feeds:
            lines.append(f"- {f.publication_name}: {f.feed_url} ({f.error})")
        lines.append("")
    return "\n".join(lines)


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
    markdown_filename = generated_at.strftime(REPORT_FILENAME_FORMAT).replace(".html", ".md")
    return env.get_template("report.html.j2").render(
        sections=sections,
        failed_feeds=failed_feeds,
        generated_at=generated_at,
        generated_day=format_day(generated_at),
        total_articles=sum(len(s.articles) for s in sections),
        report_name=report_name or "Media Monitoring",
        publications=publications,
        markdown_payload=build_markdown(sections, failed_feeds, generated_at, report_name, publications),
        markdown_filename=markdown_filename,
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
