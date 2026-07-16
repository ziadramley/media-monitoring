# Media Monitor

A local media-monitoring tool for press and comms teams. Run one command and
get a clean, printable HTML report of recent headlines from major UK and US
outlets, filtered against searches you define — opened automatically in your
browser.

Everything runs on your own machine. The only network traffic is fetching the
outlets' public RSS feeds, exactly as a feed reader would.

## What it does — and deliberately doesn't

**It does:** fetch headlines, standfirsts (summary lines), author names,
publication times, and article links from official publisher RSS feeds, filter
them against your saved searches, and produce one self-contained HTML report
you can print, email, or archive.

**It doesn't:** scrape full article text, use AI, call any paid API, need any
account or key, or send anything anywhere. RSS feeds are what publishers
choose to make public; reading the full articles is what your subscriptions
are for.

## Quickstart (5 minutes)

You need Python 3.10 or newer (`python3 --version` to check).

```bash
git clone https://github.com/ziadramley/media-monitoring.git
cd media-monitoring

python3 -m venv .venv                      # a private sandbox for this tool
.venv/bin/pip install -r requirements.txt  # three small libraries

.venv/bin/python monitor.py
```

That's it — the report opens in your browser. The repo ships with three
example searches that work out of the box; edit `config.yaml` to make them
yours.

> On Windows, the two `.venv/bin/...` commands are `.venv\Scripts\pip` and
> `.venv\Scripts\python`.

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

A section with no matches still appears in the report, saying so — for a
comms team, the *absence* of coverage is information too.

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
| CNN | Feeds still respond, but froze in April 2023 — they look alive and aren't |

CNN is the cautionary tale: a feed can return valid XML forever while quietly
serving years-old news. That's why the terminal log prints the **age of each
feed's newest item** on every run — if a feed in your registry rots, you'll
see it.

## An honest limitation: RSS depth

RSS feeds typically hold only the most recent 20–150 items. For busy outlets
that can be **less than a day of coverage** — during testing, one national
front-page feed turned over its entire 100-item feed in about four hours.

In practice: `past_24_hours` searches are reliable; `past_48_hours` and
`past_72_hours` searches may be missing older articles from high-volume
outlets (the report shows a note on those sections). If a rolling archive
matters to you, run the tool once or twice a day and keep the reports — the
`reports/` folder is your archive.

## The report

- Self-contained single HTML file in `reports/`, timestamped, nothing external
  — it survives being emailed or archived.
- **Download as Markdown** button for pasting into email, Slack, or notes.
- Print-friendly — designed to be handed out at a morning meeting.
- Feeds that couldn't be reached are listed in a warnings box, so you know
  what the report *doesn't* cover.

## Command-line options

```
.venv/bin/python monitor.py                    # default run
.venv/bin/python monitor.py --config my.yaml   # a different search file
.venv/bin/python monitor.py --no-open          # write the report, skip the browser
.venv/bin/python monitor.py --verbose          # per-feed parsing detail
```

## How it's put together

```
monitor.py               orchestration only — the steps, in order
monitoring/config.py     reads & validates the two YAML files
monitoring/fetcher.py    fetches feeds concurrently (15s timeout, honest User-Agent)
monitoring/parser.py     cleans feed entries: dates, HTML stripping, authors, URLs
monitoring/matcher.py    applies your keywords and date windows (pure logic, unit-tested)
monitoring/report.py     renders the report and its Markdown twin
templates/report.html.j2 the report's entire appearance
```

Run the tests with `.venv/bin/python -m unittest`.

## Troubleshooting

- **A feed fails with HTTP 403** — some outlets (the Telegraph, sometimes
  Politico) run aggressive bot protection that intermittently refuses even
  polite requests. The run carries on without them; they usually return.
- **YAML error on startup** — the error message names the file and problem.
  Most commonly it's a tab character; YAML only accepts spaces.
- **`date unknown` on an article** — its feed omitted or mangled the
  publication date. The article is kept and labeled rather than dropped.

## Licence

[MIT](LICENSE). Headlines, standfirsts, and links belong to their publishers;
this tool only rearranges what they publish in their public feeds, and links
back to them.
