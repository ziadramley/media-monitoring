"""The local control-panel web server.

A thin HTTP layer over the same report pipeline the CLI uses. It has no
business logic of its own: it renders the form, parses what the user
submitted, hands a Query to generate_report(), and serves the result.

Routes:
    GET  /                      the control panel (a form)
    POST /generate              build a report from the submitted form
    GET  /reports/<file>.html   serve a generated report

The server binds to localhost only (see create_server) — it is never
reachable from your network.
"""
from __future__ import annotations

import logging
import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from monitoring.constants import (
    DATE_RANGES,
    REPORTS_DIR,
    WEB_HOST,
    WEB_PORT_SCAN_LIMIT,
)
from monitoring.models import Publication, Query
from monitoring.pipeline import generate_report

log = logging.getLogger("monitor")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# Only ever serve files that match the exact name shape write_report()
# produces. The pattern forbids slashes and dots-dots, so a crafted path
# like /reports/../config.yaml can't escape the reports folder.
_REPORT_FILENAME_RE = re.compile(r"^report_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.html$")

# Friendly headings for the outlet groups on the form.
_REGION_LABELS = {"UK": "United Kingdom", "US": "United States"}
_REGION_ORDER = ["UK", "US"]


def _jinja() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    )


def _date_range_options() -> list[tuple[str, str]]:
    """(value, label) pairs for the timeframe dropdown, e.g.
    ('past_24_hours', 'Past 24 hours')."""
    return [(key, f"Past {hours} hours") for key, hours in DATE_RANGES.items()]


def _grouped_publications(publications: dict[str, Publication]) -> list[tuple[str, list[Publication]]]:
    """Publications grouped by region for the checkbox columns."""
    groups: dict[str, list[Publication]] = {}
    for pub in publications.values():
        groups.setdefault(pub.region or "Other", []).append(pub)
    order = _REGION_ORDER + [k for k in groups if k not in _REGION_ORDER]
    return [
        (_REGION_LABELS.get(key, key), sorted(groups[key], key=lambda p: p.name))
        for key in order
        if key in groups
    ]


def make_handler(publications: dict[str, Publication], reports_dir: str | Path = REPORTS_DIR):
    """Build the request handler class, closing over the registry and
    output folder so the server stays a plain data-in/data-out object."""
    reports_path = Path(reports_dir)

    # Sensible defaults for a first visit: everything ticked, 24h window.
    default_form = {
        "name": "",
        "keywords": "",
        "match": "any",
        "date_range": next(iter(DATE_RANGES)),
    }
    all_ids = set(publications)

    class ControlPanelHandler(BaseHTTPRequestHandler):
        server_version = "MediaMonitor/1.0"

        # Route the noisy default access log through our logger at debug.
        def log_message(self, fmt: str, *args) -> None:
            log.debug("http %s", fmt % args)

        # --- routing ---------------------------------------------------
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                self._render_panel(default_form, selected=all_ids, status=200)
            elif path.startswith("/reports/"):
                self._serve_report(path[len("/reports/"):])
            else:
                self._send_html("<h1>Not found</h1>", status=404)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/generate":
                self._handle_generate()
            else:
                self._send_html("<h1>Not found</h1>", status=404)

        # --- control panel ---------------------------------------------
        def _render_panel(self, form: dict, selected: set[str], status: int, error: str | None = None) -> None:
            html = _jinja().get_template("control_panel.html.j2").render(
                grouped_publications=_grouped_publications(publications),
                date_ranges=_date_range_options(),
                form=form,
                selected_pubs=selected,
                error=error,
            )
            self._send_html(html, status=status)

        def _handle_generate(self) -> None:
            fields = self._read_form()
            form = {
                "name": (fields.get("name", [""])[0] or "").strip(),
                "keywords": fields.get("keywords", [""])[0],
                "match": fields.get("match", ["any"])[0],
                "date_range": fields.get("date_range", [next(iter(DATE_RANGES))])[0],
            }
            selected = [p for p in fields.get("publications", []) if p in publications]

            # Validation — re-show the form with a plain-English message
            # and everything the user already typed still in place.
            keywords = [k.strip() for k in re.split(r"[,\n]", form["keywords"]) if k.strip()]
            error = None
            if not keywords:
                error = "Please enter at least one keyword or phrase to search for."
            elif form["match"] not in ("any", "all"):
                error = "Please choose how to match keywords."
            elif form["date_range"] not in DATE_RANGES:
                error = "Please choose a timeframe."
            elif not selected:
                error = "Please select at least one publication to search."

            if error:
                log.info("Rejected form: %s", error)
                self._render_panel(form, selected=set(selected) or all_ids, status=400, error=error)
                return

            query = Query(
                name=form["name"] or "Search results",
                keywords=keywords,
                match=form["match"],
                date_range=form["date_range"],
                publications=selected,
            )
            log.info(
                "Generating: keywords=%s match=%s range=%s pubs=%d",
                keywords, form["match"], form["date_range"], len(selected),
            )
            try:
                result = generate_report([query], publications, reports_dir=reports_path)
            except Exception:  # never let one bad run kill the server
                log.error("Report generation failed:\n%s", traceback.format_exc())
                self._send_html(
                    "<h1>Something went wrong generating the report.</h1>"
                    "<p>The details were printed to the terminal. "
                    '<a href="/">Back to the control panel</a>.</p>',
                    status=500,
                )
                return

            # Post/redirect/get: a refresh re-shows the report, not re-runs it.
            self.send_response(303)
            self.send_header("Location", f"/reports/{result.path.name}")
            self.end_headers()

        # --- serving generated reports ---------------------------------
        def _serve_report(self, filename: str) -> None:
            if not _REPORT_FILENAME_RE.match(filename):
                self._send_html("<h1>Not found</h1>", status=404)
                return
            path = (reports_path / filename).resolve()
            if reports_path.resolve() not in path.parents or not path.is_file():
                self._send_html("<h1>Report not found</h1>", status=404)
                return
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # --- low-level helpers -----------------------------------------
        def _read_form(self) -> dict[str, list[str]]:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            return parse_qs(body, keep_blank_values=True)

        def _send_html(self, html: str, status: int) -> None:
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ControlPanelHandler


def create_server(
    publications: dict[str, Publication],
    port: int,
    reports_dir: str | Path = REPORTS_DIR,
    host: str = WEB_HOST,
) -> tuple[ThreadingHTTPServer, int]:
    """Bind the server to localhost, scanning upward for a free port if
    the requested one is busy. Returns (server, actual_port)."""
    handler = make_handler(publications, reports_dir)
    last_error: OSError | None = None
    for candidate in range(port, port + WEB_PORT_SCAN_LIMIT):
        try:
            server = ThreadingHTTPServer((host, candidate), handler)
        except OSError as exc:  # port in use — try the next one
            last_error = exc
            continue
        return server, candidate
    raise OSError(
        f"Could not find a free port between {port} and "
        f"{port + WEB_PORT_SCAN_LIMIT - 1}."
    ) from last_error
