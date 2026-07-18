"""Tool-level settings, all in one place.

Anything here is a value someone might reasonably want to change —
timeouts, the User-Agent we identify ourselves with, how long a
standfirst can get before we trim it. Keeping them together means
no hunting through logic files to tune behaviour.
"""

# How we identify ourselves to news sites. Descriptive and honest:
# a site owner reading their logs can see what fetched their feed.
USER_AGENT = "Mimi/1.0 (local RSS media monitoring; https://github.com/ziadramley/media-monitoring)"

# Seconds to wait for a single feed before giving up on it.
FETCH_TIMEOUT_SECONDS = 15

# How many feeds to fetch at the same time.
MAX_CONCURRENT_FETCHES = 8

# The most bytes we'll download for one feed. Real feeds are well under
# 1 MB; this stops a misconfigured URL (say, a video file) from eating
# unbounded memory. Matches the cap on POST bodies in the web server.
MAX_FEED_BYTES = 5_000_000

# A failed fetch (timeout, connection error, HTTP 403/5xx) is retried
# this many times, after a short pause — outlets with bot protection
# often refuse one request and accept the next.
FETCH_RETRIES = 1
FETCH_RETRY_DELAY_SECONDS = 2

# A feed whose newest item is older than this has probably been
# abandoned or frozen by the outlet (it happens — see the README).
# Flagged in the terminal log and the report's warnings widget.
FROZEN_FEED_THRESHOLD_HOURS = 14 * 24

# Standfirsts longer than this get trimmed at a word boundary.
STANDFIRST_MAX_CHARS = 300

# Trailing feed boilerplate stripped from standfirsts
# (compared case-insensitively at the end of the text).
STANDFIRST_BOILERPLATE = (
    "Continue reading...",
    "Continue reading…",
)

# Rolling windows, measured back from run time in the local timezone.
DATE_RANGES = {
    "past_24_hours": 24,
    "past_48_hours": 48,
    "past_72_hours": 72,
}

# Ranges long enough that RSS feed depth becomes a caveat worth
# showing in the report (feeds often hold only ~24h of items).
DEPTH_CAVEAT_RANGES = {"past_48_hours", "past_72_hours"}

# Tracking query parameters stripped when comparing URLs for duplicates.
# Deliberately a blocklist, not "strip everything": some sites use a
# query parameter (e.g. ?id=...) as the article identifier itself.
# Compared case-insensitively.
TRACKING_PARAM_PREFIXES = ("utm_", "ns_", "syn", "at_")
TRACKING_PARAM_NAMES = {"fbclid", "gclid", "cmp", "cmpid", "ito", "icid"}

# Output locations.
REPORTS_DIR = "reports"
REPORT_FILENAME_FORMAT = "report_%Y-%m-%d_%H-%M-%S.html"

# Where the control panel saves named searches (one YAML file each).
# Personal working data — gitignored like reports/.
SEARCHES_DIR = "searches"

# Default file names, relative to the working directory.
DEFAULT_CONFIG_PATH = "config.yaml"
DEFAULT_PUBLICATIONS_PATH = "publications.yaml"

# Local control-panel web server (webapp.py). Binds to localhost only —
# the panel is never reachable from your network or the internet.
WEB_HOST = "127.0.0.1"
WEB_DEFAULT_PORT = 8730
WEB_PORT_SCAN_LIMIT = 20  # if the port is busy, try this many ports above it
