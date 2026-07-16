"""Tool-level settings, all in one place.

Anything here is a value someone might reasonably want to change —
timeouts, the User-Agent we identify ourselves with, how long a
standfirst can get before we trim it. Keeping them together means
no hunting through logic files to tune behaviour.
"""

# How we identify ourselves to news sites. Descriptive and honest:
# a site owner reading their logs can see what fetched their feed.
USER_AGENT = "MediaMonitor/1.0 (local RSS media monitoring; https://github.com/ziadramley/media-monitoring)"

# Seconds to wait for a single feed before giving up on it.
FETCH_TIMEOUT_SECONDS = 15

# How many feeds to fetch at the same time.
MAX_CONCURRENT_FETCHES = 8

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
TRACKING_PARAM_PREFIXES = ("utm_", "ns_", "syn")
TRACKING_PARAM_NAMES = {"fbclid", "gclid", "cmp", "cmpid", "ito", "icid"}

# Output locations.
REPORTS_DIR = "reports"
REPORT_FILENAME_FORMAT = "report_%Y-%m-%d_%H-%M-%S.html"

# Default file names, relative to the working directory.
DEFAULT_CONFIG_PATH = "config.yaml"
DEFAULT_PUBLICATIONS_PATH = "publications.yaml"
