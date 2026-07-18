"""The local control-panel web server.

A thin HTTP layer over the same report pipeline the CLI uses. It has no
business logic of its own: it renders the editor, parses the search
cards the user submitted, hands a list of Queries to generate_report(),
and serves (or saves) the result.

Routes:
    GET  /                       the editor + saved-search list
    GET  /?new=1                 the editor, reset to one blank card
    GET  /report                 the in-app view of the last generated report
    POST /report/remove          prune one article from the current report
    POST /edit/<slug>            load a saved search into the editor
    POST /generate               build a report from the submitted cards
    POST /lucky                  roll a random search and run it ("I'm feeling lucky")
    POST /save                   save the submitted cards under a name
    POST /run/<slug>             run a saved search straight to a report
    POST /delete/<slug>          delete a saved search
    GET  /reports/<file>.html    serve the self-contained portable report file

Every request must carry a Host header naming this server (which blocks
DNS-rebinding attacks), and every POST must carry the per-server CSRF
token (which blocks other websites submitting forms at localhost). All
routes with side effects are POST for the same reason.

The editor and the report view share one page shell (templates/_shell.html.j2)
so the masthead + action nav are identical across both. The report file served
at /reports/ stays self-contained for download/print/email and the CLI.

The server binds to localhost only (see create_server) — it is never
reachable from your network.
"""
from __future__ import annotations

import logging
import re
import secrets
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from monitoring.constants import (
    DATE_RANGES,
    REPORTS_DIR,
    SEARCH_NAME_MAX_LEN,
    SEARCHES_DIR,
    WEB_HOST,
    WEB_PORT_SCAN_LIMIT,
)
from monitoring.models import Publication, Query
from monitoring.pipeline import generate_report
from monitoring.report import (
    apply_removals,
    format_datetime,
    format_day,
    render_html,
    write_report,
)
from monitoring.searches import (
    delete_search,
    list_searches,
    load_search,
    next_lucky_name,
    next_untitled_name,
    save_search,
    slugify,
)
from monitoring.config import ConfigError
from monitoring.lucky import lucky_queries

log = logging.getLogger("mimi")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# Only ever serve files that match the exact name shape write_report()
# produces. The pattern forbids slashes and dot-dots, so a crafted path
# like /reports/../config.yaml can't escape the reports folder. \Z (not $)
# anchors the true end — $ would also match before a trailing newline.
_REPORT_FILENAME_RE = re.compile(r"^report_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.html\Z")

# A hard cap on how much of a POST body we'll read, so a client that
# declares a huge Content-Length can't make us allocate unbounded memory.
_MAX_BODY_BYTES = 5_000_000

# Friendly headings for the outlet groups on the form.
_REGION_LABELS = {"UK": "United Kingdom", "US": "United States"}
_REGION_ORDER = ["UK", "US"]

_DEFAULT_RANGE = next(iter(DATE_RANGES))


def _jinja() -> Environment:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES_DIR),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    )
    env.filters["datefmt"] = format_datetime  # used by the shared sections macro
    return env


def _date_range_options() -> list[tuple[str, str]]:
    """(value, label) pairs for the timeframe dropdown, e.g.
    ('past_24_hours', 'Past 24 hours')."""
    return [(key, f"Past {hours} hours") for key, hours in DATE_RANGES.items()]


def _name_too_long_error() -> str:
    return f"Search name must be {SEARCH_NAME_MAX_LEN} characters or fewer."


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


# --- search cards: parsing, validation, and view models ----------------
# A "card" is one section of the report. The form submits each card's
# fields suffixed with a per-card token (keywords__c0, match__c0, …) plus
# a card_order field listing the tokens in display order.

def parse_cards(fields: dict[str, list[str]]) -> list[dict]:
    """Pull the raw submitted cards out of a parsed form body, in the
    order the user arranged them."""
    order = fields.get("card_order", [""])[0]
    tokens = [t for t in order.split(",") if t]
    cards = []
    for token in tokens:
        cards.append({
            "token": token,
            "name": (fields.get(f"name__{token}", [""])[0] or "").strip(),
            "keywords": fields.get(f"keywords__{token}", [""])[0],
            "match": fields.get(f"match__{token}", ["any"])[0],
            "date_range": fields.get(f"date_range__{token}", [_DEFAULT_RANGE])[0],
            "publications": list(fields.get(f"publications__{token}", [])),
        })
    return cards


def build_cards(
    cards: list[dict], publications: dict[str, Publication]
) -> tuple[list[Query], list[dict], bool]:
    """Validate raw cards into (queries, view_models, all_valid).

    view_models always covers every card — each carries an `error`
    message (or None) and the user's own input — so a rejected submission
    re-renders with nothing lost. queries holds only the valid cards, in
    order, ready for the report engine.
    """
    queries: list[Query] = []
    view: list[dict] = []
    all_valid = bool(cards)
    for card in cards:
        keywords = [k.strip() for k in re.split(r"[,\n]", card["keywords"]) if k.strip()]
        selected = [p for p in card["publications"] if p in publications]

        error = None
        if not card["name"]:
            error = "Give this query a name."
        elif not keywords:
            error = "Enter at least one keyword or phrase."
        elif card["match"] not in ("any", "all"):
            error = "Choose how to match keywords."
        elif card["date_range"] not in DATE_RANGES:
            error = "Choose a timeframe."
        elif not selected:
            error = "Select at least one publication."

        view.append({
            "token": card["token"],
            "name": card["name"],
            "keywords": card["keywords"],
            "match": card["match"] if card["match"] in ("any", "all") else "any",
            "date_range": card["date_range"] if card["date_range"] in DATE_RANGES else _DEFAULT_RANGE,
            "selected": set(selected),
            "error": error,
        })

        if error:
            all_valid = False
        else:
            queries.append(Query(
                name=card["name"],
                keywords=keywords,
                match=card["match"],
                date_range=card["date_range"],
                publications=selected,
            ))
    return queries, view, all_valid


def cards_from_queries(queries: list[Query]) -> list[dict]:
    """Turn stored/loaded Queries into editor card view models."""
    return [
        {
            "token": str(i),
            "name": q.name,
            "keywords": ", ".join(q.keywords),
            "match": q.match,
            "date_range": q.date_range,
            "selected": set(q.publications),
            "error": None,
        }
        for i, q in enumerate(queries)
    ]


def default_cards(publications: dict[str, Publication]) -> list[dict]:
    """A single blank card with every outlet ticked — the first-visit and
    'New search' state."""
    return [{
        "token": "0",
        "name": "",
        "keywords": "",
        "match": "any",
        "date_range": _DEFAULT_RANGE,
        "selected": set(publications),
        "error": None,
    }]


def make_handler(
    publications: dict[str, Publication],
    reports_dir: str | Path = REPORTS_DIR,
    searches_dir: str | Path = SEARCHES_DIR,
    lucky_keywords: list[str] | None = None,
):
    """Build the request handler class, closing over the registry, output
    folder, and saved-search storage so the server stays a plain object.
    `lucky_keywords` powers the I'm-feeling-lucky button; when empty the
    button is hidden and the route refuses politely."""
    reports_path = Path(reports_dir)
    lucky_keywords = lucky_keywords or []

    # In-memory recollection of the last search the user ran or loaded, so
    # returning to the editor restores it. Single-user localhost tool — a
    # plain dict is plenty. `flash` is a one-shot confirmation message;
    # `report` holds the last generated report so GET /report can re-render
    # it (post/redirect/get) without re-fetching.
    state: dict = {"cards": None, "search_name": "", "flash": None, "report": None}
    # The server is threaded (one thread per request): two browser tabs
    # must not interleave their reads and writes of the shared state.
    state_lock = threading.Lock()

    # One secret per server start, embedded in every form and checked on
    # every POST — a page on another website can't forge it, so it can't
    # make this server delete searches or generate reports.
    csrf_token = secrets.token_hex(16)

    class ControlPanelHandler(BaseHTTPRequestHandler):
        server_version = "Mimi/1.0"

        def log_message(self, fmt: str, *args) -> None:
            log.debug("http %s", fmt % args)

        # --- routing ---------------------------------------------------
        # do_GET/do_POST wrap the real routers so that any unhandled
        # exception becomes a logged 500 page, never a dropped connection.
        def do_GET(self) -> None:
            self._safely(self._route_get)

        def do_POST(self) -> None:
            self._safely(self._route_post)

        def _safely(self, route) -> None:
            try:
                if not self._host_allowed():
                    # A request addressed to some other hostname reached us:
                    # that's a DNS-rebinding attempt, not the user's browser.
                    log.warning("Rejected request with Host %r",
                                self.headers.get("Host"))
                    self._send_html("<h1>Forbidden</h1>", status=403)
                    return
                route()
            except Exception:
                log.error("Unhandled error for %s %s:\n%s",
                          self.command, self.path, traceback.format_exc())
                try:
                    self._send_html(
                        "<h1>Something went wrong.</h1>"
                        '<p><a href="/">Back to the control panel</a>.</p>',
                        status=500,
                    )
                except Exception:
                    pass  # response already partly sent — nothing we can do

        def _host_allowed(self) -> bool:
            """Only answer requests addressed to this server itself —
            127.0.0.1:<port> or localhost:<port>."""
            host = (self.headers.get("Host") or "").strip().lower()
            bound_host, bound_port = self.server.server_address[:2]
            return host in {
                f"{bound_host}:{bound_port}",
                f"localhost:{bound_port}",
            }

        def _route_get(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/":
                self._home(parse_qs(parsed.query))
            elif path == "/report":
                self._report()
            elif path.startswith("/reports/"):
                self._serve_report(path[len("/reports/"):])
            else:
                self._send_html("<h1>Not found</h1>", status=404)

        def _route_post(self) -> None:
            path = urlparse(self.path).path
            fields = self._read_form()
            if fields.get("csrf", [""])[0] != csrf_token:
                # A stale page from before a server restart, or a forged
                # cross-site form. Either way: refuse, explain, don't act.
                self._send_html(
                    "<h1>This form has expired.</h1>"
                    '<p>Please <a href="/">go back to the control panel</a> '
                    "and try again.</p>",
                    status=403,
                )
                return
            if path == "/generate":
                self._generate(fields)
            elif path == "/lucky":
                self._lucky()
            elif path == "/report/remove":
                self._remove_article(fields)
            elif path == "/save":
                self._save(fields)
            elif path.startswith("/edit/"):
                self._edit_saved(unquote(path[len("/edit/"):]))
            elif path.startswith("/run/"):
                self._run_saved(unquote(path[len("/run/"):]))
            elif path.startswith("/delete/"):
                self._delete_saved(unquote(path[len("/delete/"):]))
            else:
                self._send_html("<h1>Not found</h1>", status=404)

        # --- shared context --------------------------------------------
        def _saved(self) -> list:
            try:
                return list_searches(publications, searches_dir)
            except Exception:  # a storage hiccup shouldn't blank the panel
                log.error("Could not list saved searches:\n%s", traceback.format_exc())
                return []

        def _stash_report(self, name: str, result) -> None:
            """Remember the last report so GET /report can re-render it.
            `removed` collects (section anchor, dedupe_key) pairs as the
            user prunes articles; it starts empty for every new report."""
            with state_lock:
                state["report"] = {
                    "name": name,
                    "file": result.path.name,
                    "result": result,
                    "removed": set(),
                }

        # --- rendering the editor --------------------------------------
        def _render_editor(self, cards: list[dict], search_name: str, status: int,
                           top_error: str | None = None, flash: str | None = None) -> None:
            html = _jinja().get_template("control_panel.html.j2").render(
                cards=cards,
                grouped_publications=_grouped_publications(publications),
                date_ranges=_date_range_options(),
                all_pub_ids=set(publications),
                saved_searches=self._saved(),
                search_name=search_name,
                top_error=top_error,
                flash=flash,
                csrf=csrf_token,
                lucky=bool(lucky_keywords),
            )
            self._send_html(html, status=status)

        # --- rendering the in-app report view --------------------------
        def _report(self) -> None:
            with state_lock:
                rep = state.get("report")
                if rep:
                    removed = set(rep["removed"])  # snapshot: render outside the lock
            if not rep:  # nothing generated yet (fresh server / direct hit)
                self._redirect("/")
                return
            result = rep["result"]
            sections = apply_removals(result.sections, removed)
            html = _jinja().get_template("report_view.html.j2").render(
                saved_searches=self._saved(),
                flash=None,
                report_name=rep["name"],
                report_file=rep["file"],
                sections=sections,
                failed_feeds=result.failed,
                stale_feeds=result.stale,
                generated_at=result.generated_at,
                generated_day=format_day(result.generated_at),
                total_articles=sum(len(s.articles) for s in sections),
                publications=result.publications,
                csrf=csrf_token,
                lucky=bool(lucky_keywords),
            )
            self._send_html(html, status=200)

        # --- pruning articles from the report --------------------------
        def _remove_article(self, fields: dict[str, list[str]]) -> None:
            """Remove one article from the current report. The pruned
            report is immediately re-written to reports/ (same filename),
            so the archived file always matches what the user curated and
            the printable link stays a plain page-open."""
            anchor = fields.get("anchor", [""])[0]
            key = fields.get("key", [""])[0]
            with state_lock:
                rep = state.get("report")
                if rep:
                    result = rep["result"]
                    valid_anchors = {s.anchor for s in result.sections}
                    if anchor in valid_anchors and key:
                        rep["removed"].add((anchor, key))
                    removed = set(rep["removed"])  # snapshot: write outside the lock
            if not rep:
                self._redirect("/")
                return
            if anchor in valid_anchors and key:
                pruned = apply_removals(result.sections, removed)
                try:
                    html = render_html(pruned, [], result.generated_at,
                                       report_name=rep["name"],
                                       publications=result.publications)
                    write_report(html, result.generated_at, reports_path)
                except OSError:
                    log.error("Could not re-write pruned report:\n%s",
                              traceback.format_exc())
            self._redirect(f"/report#{anchor}" if anchor in valid_anchors else "/report")

        def _home(self, query: dict[str, list[str]]) -> None:
            with state_lock:
                if "new" in query:
                    state["cards"] = None
                    state["search_name"] = ""
                flash = state.pop("flash", None)
                state["flash"] = None
                cards = state["cards"] or default_cards(publications)
                search_name = state["search_name"]
            self._render_editor(cards, search_name, status=200, flash=flash)

        def _edit_saved(self, slug: str) -> None:
            try:
                search = load_search(slug, publications, searches_dir)
            except (ConfigError, ValueError) as exc:
                self._render_editor(default_cards(publications), "", status=404,
                                    top_error=str(exc))
                return
            with state_lock:
                state["cards"] = cards_from_queries(search.queries)
                state["search_name"] = search.name
            self._redirect("/")

        # --- generating and saving -------------------------------------
        def _generate(self, fields: dict[str, list[str]]) -> None:
            search_name = (fields.get("search_name", [""])[0] or "").strip()
            queries, view, ok = build_cards(parse_cards(fields), publications)
            if len(search_name) > SEARCH_NAME_MAX_LEN:
                self._render_editor(
                    view or default_cards(publications), search_name, status=400,
                    top_error=_name_too_long_error(),
                )
                return
            if not ok:
                self._render_editor(
                    view or default_cards(publications), search_name, status=400,
                    top_error="Please fix the highlighted queries before generating.",
                )
                return
            # Generating always saves the report. An unnamed report is saved
            # under an auto-assigned "Untitled Search N".
            if not slugify(search_name):
                search_name = next_untitled_name(searches_dir)
            try:
                save_search(search_name, queries, searches_dir)
            except (ValueError, OSError):
                log.error("Could not save report on generate:\n%s", traceback.format_exc())
                # Saving is best-effort here — still produce the report.
            with state_lock:
                state["cards"] = [{**c, "error": None} for c in view]
                state["search_name"] = search_name
            self._run_and_show(search_name, queries)

        def _run_and_show(self, search_name: str, queries: list[Query]) -> None:
            """The shared tail of every report-producing route: generate,
            stash for GET /report, and redirect there. Any failure becomes
            a logged 500 page, never a dropped connection."""
            log.info("Generating report %r from %d query(ies).", search_name, len(queries))
            try:
                result = generate_report(queries, publications, reports_dir=reports_path,
                                         report_name=search_name)
            except Exception:
                log.error("Report generation failed:\n%s", traceback.format_exc())
                self._send_html(
                    "<h1>Something went wrong generating the report.</h1>"
                    "<p>The details were printed to the terminal. "
                    '<a href="/">Back to the control panel</a>.</p>',
                    status=500,
                )
                return
            self._stash_report(search_name, result)
            self._redirect("/report")

        def _lucky(self) -> None:
            """The I'm-feeling-lucky button: roll a random search, save it
            like any generated search, and run it straight to a report."""
            if not lucky_keywords:  # button hidden, but refuse politely anyway
                self._redirect("/")
                return
            queries = lucky_queries(lucky_keywords, publications)
            search_name = next_lucky_name(searches_dir)
            try:
                save_search(search_name, queries, searches_dir)
            except (ValueError, OSError):
                log.error("Could not save lucky search:\n%s", traceback.format_exc())
                # Best-effort, same as _generate — still produce the report.
            with state_lock:
                state["cards"] = cards_from_queries(queries)
                state["search_name"] = search_name
            self._run_and_show(search_name, queries)

        def _save(self, fields: dict[str, list[str]]) -> None:
            # Saving only needs a name — the searches can be empty or
            # half-filled, so you can name and save a draft first and fill
            # it in later. Whatever valid searches exist are stored; cards
            # you started but left incomplete are reported, never dropped
            # silently.
            search_name = (fields.get("search_name", [""])[0] or "").strip()
            queries, view, _ok = build_cards(parse_cards(fields), publications)
            if len(search_name) > SEARCH_NAME_MAX_LEN:
                self._render_editor(
                    view or default_cards(publications), search_name, status=400,
                    top_error=_name_too_long_error(),
                )
                return
            if not slugify(search_name):
                self._render_editor(
                    view or default_cards(publications), search_name, status=400,
                    top_error="Give the search a name (letters or numbers) to save it.",
                )
                return
            try:
                save_search(search_name, queries, searches_dir)
            except (ValueError, OSError) as exc:
                self._render_editor(view or default_cards(publications), search_name,
                                    status=400, top_error=str(exc))
                return

            # A card is "incomplete" (worth flagging) if the user typed
            # keywords but it still failed validation — no name, no
            # publication selected… A card with no keywords is just an
            # empty slot.
            incomplete = sum(1 for c in view if c["error"] and c["keywords"].strip())
            n = len(queries)
            if n == 0 and incomplete == 0:
                flash = f'Saved “{search_name}” as an empty draft — add queries and save again.'
            else:
                flash = f'Saved “{search_name}” ({n} quer{"ies" if n != 1 else "y"}).'
                if incomplete:
                    flash += (f' {incomplete} incomplete quer{"ies" if incomplete != 1 else "y"} '
                              f'{"were" if incomplete != 1 else "was"} left out.')
            log.info("Saved search %r (%d query[ies], %d incomplete).", search_name, n, incomplete)

            # Store the cards without their error flags — the save succeeded.
            with state_lock:
                state["cards"] = [{**c, "error": None} for c in view]
                state["search_name"] = search_name
                state["flash"] = flash
            self._redirect("/")

        def _run_saved(self, slug: str) -> None:
            try:
                search = load_search(slug, publications, searches_dir)
            except (ConfigError, ValueError) as exc:
                self._render_editor(default_cards(publications), "", status=404,
                                    top_error=str(exc))
                return
            with state_lock:
                state["cards"] = cards_from_queries(search.queries)
                state["search_name"] = search.name
            if not search.queries:  # an empty draft — nothing to run yet
                self._render_editor(
                    default_cards(publications), search.name, status=200,
                    top_error=f"“{search.name}” has no queries yet — add some, then Generate.",
                )
                return
            self._run_and_show(search.name, search.queries)

        def _delete_saved(self, slug: str) -> None:
            try:
                delete_search(slug, searches_dir)
            except ValueError as exc:
                log.warning("Refused to delete %r: %s", slug, exc)
            self._redirect("/")

        # --- serving generated reports ---------------------------------
        def _serve_report(self, filename: str) -> None:
            if not _REPORT_FILENAME_RE.match(filename):
                self._send_html("<h1>Not found</h1>", status=404)
                return
            path = (reports_path / filename).resolve()
            if reports_path.resolve() not in path.parents or not path.is_file():
                self._send_html("<h1>Report not found</h1>", status=404)
                return
            try:
                html = path.read_text(encoding="utf-8")
            except OSError:  # deleted or unreadable between the check and the read
                self._send_html("<h1>Report not found</h1>", status=404)
                return
            self._send_html(html, status=200)

        # --- low-level helpers -----------------------------------------
        def _read_form(self) -> dict[str, list[str]]:
            try:
                length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                length = 0  # a garbled Content-Length is treated as no body
            length = max(0, min(length, _MAX_BODY_BYTES))
            # errors="replace" so a non-UTF-8 body degrades to a failed
            # validation rather than a dropped connection.
            body = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
            return parse_qs(body, keep_blank_values=True)

        def _redirect(self, location: str) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            self.end_headers()

        def _send_html(self, html: str, status: int) -> None:
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

    return ControlPanelHandler


def create_server(
    publications: dict[str, Publication],
    port: int,
    reports_dir: str | Path = REPORTS_DIR,
    searches_dir: str | Path = SEARCHES_DIR,
    host: str = WEB_HOST,
    lucky_keywords: list[str] | None = None,
) -> tuple[ThreadingHTTPServer, int]:
    """Bind the server to localhost, scanning upward for a free port if
    the requested one is busy. Returns (server, actual_port)."""
    handler = make_handler(publications, reports_dir, searches_dir, lucky_keywords)
    last_error: OSError | None = None
    for candidate in range(port, port + WEB_PORT_SCAN_LIMIT):
        try:
            server = ThreadingHTTPServer((host, candidate), handler)
        except OSError as exc:  # port in use — try the next one
            last_error = exc
            continue
        # Report the port actually bound (asking for port 0 lets the OS
        # pick one — used by the tests).
        return server, server.server_address[1]
    raise OSError(
        f"Could not find a free port between {port} and "
        f"{port + WEB_PORT_SCAN_LIMIT - 1}."
    ) from last_error
