# Mimi, the media monitoring tool

A local media-monitoring tool for press and comms teams. Run one command and
get a clean, printable HTML report of recent headlines from major UK and US
outlets, filtered against searches you define.

Everything runs on your own machine. The only network traffic is fetching the
outlets' public RSS feeds. No personal data, performance data, or analytical data is collected.

**One user, one machine.** Mimi is a personal tool: one copy per
person, each with their own saved searches and reports. Organisations who want a team version can simply layer their own auth provider on top.

## What it does and doesn't

**It does:** fetch headlines, standfirsts (summary lines), publication names,
publication times, and article links from official publisher RSS feeds. filters
them against your saved searches. produces one self-contained HTML report
you can print, email, or archive.

**It doesn't:** scrape full article text, use AI, call any paid API, need any
account or key, or send your data off your machine. RSS feeds are what publishers
choose to make public; reading the full articles is what your subscriptions
are for.

## Quickstart (5 minutes)

You need Python 3.10 or newer (`python3 --version` to check).

```bash
git clone https://github.com/ziadramley/media-monitoring.git
cd media-monitoring

python3 -m venv .venv                      # a private sandbox for this tool
.venv/bin/pip install -r requirements.txt  # three small libraries
```

> On Windows, the `.venv/bin/...` commands below are `.venv\Scripts\pip` and
> `.venv\Scripts\python`.


### How to run it

```bash
.venv/bin/python webapp.py
```

**The control panel** 
A page opens in your browser where you build a search out of one or more queries, then click **Generate
report**.

In the panel you can:

- **Combine several queries into one report** — "+ Add a new query" gives you
  a second card (e.g. *UK politics* + *US economy*); each becomes its own
  section of the report, in order. Every query needs a name — it's the
  section heading.
- **Curate, then print** — the report opens on screen with a **Remove**
  button beside each article; prune the irrelevant ones, then use the
  **Printable version** link. Going back to the control panel restores your
  search so you can tweak and regenerate.
- **Save a search to run again** — name it (e.g. *Morning briefing*) and
  click **Save search**. Saved searches appear in the bar at the top of every
  page, each with **Run**, **Edit**, and **Delete**. Generating always saves
  too — an unnamed search is kept as *Untitled Search N* so no report is ever
  orphaned.

Leave it running and come back to the browser tab whenever you want another
search. Press `Ctrl+C` in the terminal to stop it.

**Feeling lucky?** The **I'm feeling lucky** button in the bar rolls a random search and runs it immediately: one to five queries, each drawing a random keyword from the ~900-entry pool in
[lucky.yaml](lucky.yaml) pointed at all-UK outlets, all-US
outlets, or everything, over a random timeframe. Each roll is saved as
*Lucky Search N* so a good one can be re-run or edited like any other search.
One caveat: the MP and senator rosters were **verified as of 18 July 2026**
and go stale with every election. Refresh the lists in `lucky.yaml` now and
then (the file header says where they came from).

Saved searches live in a `searches/` folder as small YAML files in the same
format as `config.yaml` — so a search you saved in the panel can *also* be run
from the command line: `python monitor.py --config searches/morning-briefing.yaml`.
(The panel and `config.yaml` are independent: the panel writes only to
`searches/` and never touches `config.yaml`, which stays yours to hand-edit for
the daily `python monitor.py` run.)

## Defining your searches

Searches live in [config.yaml](config.yaml). Each one becomes a section of
the report, in the order listed:

```yaml
queries:
  - name: "Budget announcement"          # the section heading
    keywords: ["budget", "spending review", "fiscal"]
    match: any                           # any = at least one keyword; all = every keyword
    date_range: past_24_hours            # past_24_hours | past_48_hours | past_72_hours
    publications: [bbc, guardian, ft]    # ids from publications.yaml, or "all"
```

Matching rules, in plain terms:

- Case doesn't matter.
- A keyword counts if it appears in the **headline or the standfirst**.
- Multi-word keywords are **phrases** — `"spending review"` will not match
  "spending under review".
- Whole words only — a search for `AI` won't light up every article
  containing the word "said".

A section with no matches still appears in the report. An absence of coverage is information too.

## Adding a publication

Open [publications.yaml](publications.yaml) and copy the pattern:

```yaml
  my_outlet:
    name: My Outlet
    feeds:
      - https://example.com/rss.xml
```

The id (`my_outlet`) is what you reference from `config.yaml`. A publication
can list several feeds (front page + politics, say); their articles are merged
and de-duplicated automatically. To find an outlet's feed, try searching
"*outlet name* RSS feed", or look for the RSS icon in its site footer.

Every feed shipped in the registry was verified working on 16 July 2026.

### Outlets you might expect but won't find

Four major outlets no longer offer usable public RSS feeds, so they are not
in the registry:

| Outlet | Why |
|---|---|
| The Times | Removed all its RSS feeds in 2023 |
| Reuters | Discontinued public RSS in June 2020 |
| Associated Press | Its only feed now requires authentication |
| CNN | Feeds still respond, but froze in April 2023. They look alive but aren't |

## An honest limitation: RSS depth

RSS feeds typically hold only the most recent 20–150 items. For busy outlets
that can be **less than a day of coverage** — during testing, one national
front-page feed turned over its entire 100-item feed in about four hours.

In practice: `past_24_hours` searches are reliable; `past_48_hours` and
`past_72_hours` searches may be missing older articles from high-volume
outlets (the report shows a note on those sections). If a rolling archive
matters to you, run the tool once or twice a day and keep the reports — the
`reports/` folder is your archive.

## Searches, queries, and reports

Three words with precise meanings in Mimi:

- A **query** is one set of parameters: keywords, match mode, timeframe,
  and which outlets to check.
- A **search** is a named combination of queries, saved as a YAML file in
  the `searches/` folder — the panel and the command line both read them.
- A **report** is the output of running a search at a specific date and
  time, saved in `reports/`.

## The report

- In the control panel, a report opens on screen with a **Remove** button
  beside each article — prune the irrelevant ones and the report (and its
  saved file) update immediately. Regenerate the report to start over.
- The **printable version** is a self-contained single HTML file in
  `reports/`, timestamped, nothing external — it survives being emailed or
  archived, and prints cleanly for a morning meeting. It carries only the
  curated articles: no buttons, no navigation, no error notes.
- Feeds that couldn't be reached — and feeds that answered but whose newest
  item is weeks old (a frozen feed, see the CNN story above) — are flagged
  in the on-screen report and the terminal log, so you know what the report
  *doesn't* cover.

## Command-line options

The saved-search runner (`monitor.py`):

```
.venv/bin/python monitor.py                    # default run
.venv/bin/python monitor.py --config my.yaml   # a different search file
.venv/bin/python monitor.py --no-open          # write the report, skip the browser
.venv/bin/python monitor.py --verbose          # per-feed parsing detail
```

The control panel (`webapp.py`):

```
.venv/bin/python webapp.py                      # open the panel in your browser
.venv/bin/python webapp.py --port 9000          # use a specific port
.venv/bin/python webapp.py --no-open            # start the server without opening a browser
```

The control panel runs a small web server bound to `127.0.0.1` (your own
machine only) — it is never reachable from your network or the internet.

## How it's put together

```
monitor.py                  saved-search runner — orchestration only
webapp.py                   control-panel launcher — starts the local server
monitoring/config.py        reads & validates the two YAML files
monitoring/fetcher.py       fetches feeds concurrently (15s timeout, honest User-Agent)
monitoring/parser.py        cleans feed entries: dates, HTML stripping, authors, URLs
monitoring/matcher.py       applies your keywords and date windows (pure logic, unit-tested)
monitoring/pipeline.py      the shared fetch → filter → render engine both entry points use
monitoring/report.py        renders reports and applies article removals
monitoring/webserver.py     the control panel's HTTP layer (form, generate, serve)
monitoring/searches.py      saving/loading named searches (path-safe file storage)
templates/_shell.html.j2    shared page shell (masthead + action nav) for the app
templates/control_panel.html.j2  the report editor (extends the shell)
templates/report_view.html.j2    the in-app report view (extends the shell)
templates/_report_sections.html.j2  shared article markup for both report surfaces
templates/report.html.j2    the self-contained, downloadable/printable report file
```

Run the tests with `.venv/bin/python -m unittest`.

## Troubleshooting

- **A feed fails with HTTP 403** — some outlets (the Telegraph, sometimes
  Politico) run aggressive bot protection that intermittently refuses even
  polite requests. Mimi retries once after a short pause, then carries on
  without them; they usually return.
- **YAML error on startup** — the error message names the file and problem.
  Most commonly it's a tab character; YAML only accepts spaces.
- **`date unknown` on an article** — its feed omitted or mangled the
  publication date. The article is kept and labeled rather than dropped.

## Licence

[MIT](LICENSE). Headlines, standfirsts, and links belong to their publishers;
this tool only rearranges what they publish in their public feeds and links
back to them.
