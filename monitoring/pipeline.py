"""The end-to-end pipeline: queries in, a written report out.

Both the command-line tool (monitor.py) and the web control panel
(webapp.py) drive the exact same steps through here, so there's one
place — not two — where fetching, filtering, and rendering are wired
together.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from monitoring.constants import REPORTS_DIR
from monitoring.fetcher import fetch_all
from monitoring.matcher import filter_articles
from monitoring.models import FeedFetchResult, Publication, Query
from monitoring.report import (
    ReportSection,
    make_range_label,
    needs_depth_note,
    render_html,
    write_report,
)

log = logging.getLogger("monitor")


@dataclass
class ReportResult:
    path: Path
    sections: list[ReportSection]
    failed: list[FeedFetchResult]
    generated_at: datetime
    total_articles: int


def generate_report(
    queries: list[Query],
    publications: dict[str, Publication],
    now: datetime | None = None,
    reports_dir: str | Path = REPORTS_DIR,
) -> ReportResult:
    """Fetch the feeds the queries need, filter into sections, render
    and write the HTML report. Returns everything the caller needs to
    log a summary or point a browser at the file."""
    now = now or datetime.now().astimezone()

    # Only fetch publications some query actually uses.
    needed_ids = sorted({pub_id for q in queries for pub_id in q.publications})
    needed = [publications[pub_id] for pub_id in needed_ids if pub_id in publications]

    articles_by_publication, fetch_results = fetch_all(needed)

    sections: list[ReportSection] = []
    for i, query in enumerate(queries, start=1):
        matched = filter_articles(query, articles_by_publication, now)
        log.info("Query %-30r %3d match(es)", query.name, len(matched))
        sections.append(ReportSection(
            name=query.name,
            anchor=f"q{i}",
            articles=matched,
            range_label=make_range_label(query.date_range),
            show_depth_note=needs_depth_note(query.date_range),
            keywords=query.keywords,
            match=query.match,
        ))

    failed = [r for r in fetch_results if not r.ok]
    html = render_html(sections, failed, now)
    path = write_report(html, now, reports_dir)

    return ReportResult(
        path=path,
        sections=sections,
        failed=failed,
        generated_at=now,
        total_articles=sum(len(s.articles) for s in sections),
    )
