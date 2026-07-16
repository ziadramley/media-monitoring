#!/usr/bin/env python3
"""Media Monitor — fetch RSS headlines, filter against your saved
searches, and open an HTML report.

Usage:
    python monitor.py                     # config.yaml + publications.yaml
    python monitor.py --config my.yaml    # a different search config
    python monitor.py --no-open           # don't open the browser

This file is orchestration only: each step lives in its own module
under monitoring/.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from monitoring.config import ConfigError, load_config
from monitoring.constants import DEFAULT_CONFIG_PATH, DEFAULT_PUBLICATIONS_PATH
from monitoring.fetcher import fetch_all
from monitoring.matcher import filter_articles
from monitoring.report import (
    ReportSection,
    make_range_label,
    needs_depth_note,
    open_in_browser,
    render_html,
    write_report,
)

log = logging.getLogger("monitor")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch RSS headlines, filter them against the saved "
                    "searches in config.yaml, and open an HTML report.",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH,
                        help="path to your search config (default: config.yaml)")
    parser.add_argument("--publications", default=DEFAULT_PUBLICATIONS_PATH,
                        help="path to the publication registry (default: publications.yaml)")
    parser.add_argument("--no-open", action="store_true",
                        help="write the report but don't open a browser")
    parser.add_argument("--verbose", action="store_true",
                        help="show debug detail (per-feed parsing notes)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
    )

    try:
        queries, publications = load_config(args.config, args.publications)
    except ConfigError as exc:
        log.error("%s", exc)
        return 1

    # Only fetch publications some query actually uses.
    needed_ids = sorted({pub_id for q in queries for pub_id in q.publications})
    needed = [publications[pub_id] for pub_id in needed_ids]

    started = datetime.now().astimezone()
    articles_by_publication, fetch_results = fetch_all(needed)

    sections: list[ReportSection] = []
    for i, query in enumerate(queries, start=1):
        matched = filter_articles(query, articles_by_publication, started)
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
    html = render_html(sections, failed, started)
    path = write_report(html, started)

    total = sum(len(s.articles) for s in sections)
    elapsed = (datetime.now().astimezone() - started).total_seconds()
    log.info("Done in %.1fs: %d article(s) across %d section(s).", elapsed, total, len(sections))

    if args.no_open:
        log.info("Report: %s", path.resolve())
    else:
        open_in_browser(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
