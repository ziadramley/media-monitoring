#!/usr/bin/env python3
"""Mimi — control panel.

Starts a small web server on your own machine and opens a browser page
where you can set keywords, a timeframe, and which outlets to search,
then generate a report — no config file editing required.

Usage:
    python webapp.py                  # open the control panel
    python webapp.py --port 9000      # use a specific port
    python webapp.py --no-open        # start the server, don't open a browser

Stop it with Ctrl+C. For searches you run every day, save them in
config.yaml and use monitor.py instead.
"""
from __future__ import annotations

import argparse
import logging
import sys
import webbrowser

from monitoring.config import ConfigError, load_publications
from monitoring.constants import (
    DEFAULT_LUCKY_PATH,
    DEFAULT_PUBLICATIONS_PATH,
    REPORTS_DIR,
    SEARCHES_DIR,
    WEB_DEFAULT_PORT,
    WEB_HOST,
)
from monitoring.lucky import load_keywords
from monitoring.webserver import create_server

log = logging.getLogger("mimi")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Open the Mimi control panel in your browser.",
    )
    parser.add_argument("--publications", default=DEFAULT_PUBLICATIONS_PATH,
                        help="path to the publication registry (default: publications.yaml)")
    parser.add_argument("--lucky", default=DEFAULT_LUCKY_PATH,
                        help="path to the I'm-feeling-lucky keyword pool (default: lucky.yaml)")
    parser.add_argument("--port", type=int, default=WEB_DEFAULT_PORT,
                        help=f"port to serve on (default: {WEB_DEFAULT_PORT})")
    parser.add_argument("--no-open", action="store_true",
                        help="start the server without opening a browser")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    try:
        publications = load_publications(args.publications)
    except ConfigError as exc:
        log.error("%s", exc)
        return 1

    # The lucky button is optional garnish: a broken or missing pool file
    # gets a warning and a panel without the button, not a dead server.
    try:
        lucky_keywords = load_keywords(args.lucky)
    except ConfigError as exc:
        log.warning("I'm-feeling-lucky button disabled: %s", exc)
        lucky_keywords = []

    try:
        server, port = create_server(
            publications, args.port,
            reports_dir=REPORTS_DIR,
            searches_dir=SEARCHES_DIR,
            lucky_keywords=lucky_keywords,
        )
    except OSError as exc:
        log.error("%s", exc)
        return 1

    url = f"http://{WEB_HOST}:{port}/"
    log.info("Control panel running at %s", url)
    log.info("Loaded %d publications. Press Ctrl+C to stop.", len(publications))

    if not args.no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
