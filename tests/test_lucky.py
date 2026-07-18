"""The I'm-feeling-lucky roll: run with  python -m unittest .

The rng is injected, so every rule — query count, distinct keywords,
whole-region publication scopes, valid timeframes — is tested
deterministically. Also sanity-checks the real lucky.yaml so a bad edit
(or an accidental truncation) fails the suite, not the button.
"""
import random
import tempfile
import unittest
from pathlib import Path

from monitoring.config import ConfigError
from monitoring.constants import DATE_RANGES, LUCKY_MAX_QUERIES, LUCKY_MIN_QUERIES
from monitoring.lucky import _region_options, load_keywords, lucky_queries
from monitoring.models import Publication

KEYWORDS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]

UK_US = {
    "bbc": Publication("bbc", "BBC News", ["https://x"], region="UK"),
    "sky": Publication("sky", "Sky News", ["https://y"], region="UK"),
    "nyt": Publication("nyt", "The New York Times", ["https://z"], region="US"),
    "wapo": Publication("wapo", "The Washington Post", ["https://w"], region="US"),
}

THREE_REGIONS = dict(UK_US, cbc=Publication("cbc", "CBC News", ["https://c"], region="Canada"))


class LuckyQueries(unittest.TestCase):
    def test_deterministic_under_a_seed(self):
        a = lucky_queries(KEYWORDS, UK_US, random.Random(7))
        b = lucky_queries(KEYWORDS, UK_US, random.Random(7))
        self.assertEqual(a, b)

    def test_count_always_between_min_and_max(self):
        for seed in range(200):
            n = len(lucky_queries(KEYWORDS, UK_US, random.Random(seed)))
            self.assertTrue(LUCKY_MIN_QUERIES <= n <= LUCKY_MAX_QUERIES, n)

    def test_query_name_is_its_single_keyword(self):
        for q in lucky_queries(KEYWORDS, UK_US, random.Random(1)):
            self.assertEqual(q.keywords, [q.name])
            self.assertIn(q.name, KEYWORDS)
            self.assertEqual(q.match, "any")

    def test_keywords_never_repeat_within_one_roll(self):
        for seed in range(100):
            names = [q.name for q in lucky_queries(KEYWORDS, UK_US, random.Random(seed))]
            self.assertEqual(len(names), len(set(names)))

    def test_timeframe_is_always_a_real_range(self):
        for seed in range(50):
            for q in lucky_queries(KEYWORDS, UK_US, random.Random(seed)):
                self.assertIn(q.date_range, DATE_RANGES)

    def test_publications_are_a_whole_region_or_everything(self):
        allowed = {tuple(opt) for opt in _region_options(UK_US)}
        self.assertEqual(allowed, {("bbc", "sky"), ("nyt", "wapo"),
                                   ("bbc", "nyt", "sky", "wapo")})
        for seed in range(100):
            for q in lucky_queries(KEYWORDS, UK_US, random.Random(seed)):
                self.assertIn(tuple(q.publications), allowed)

    def test_region_options_scale_beyond_two_regions(self):
        # Adding a third region needs no logic change: R regions → R+1 options.
        allowed = {tuple(opt) for opt in _region_options(THREE_REGIONS)}
        self.assertEqual(allowed, {
            ("cbc",),                              # all Canada
            ("bbc", "sky"),                        # all UK
            ("nyt", "wapo"),                       # all US
            ("bbc", "cbc", "nyt", "sky", "wapo"),  # everything
        })

    def test_all_region_choices_actually_occur(self):
        seen = {tuple(q.publications)
                for seed in range(300)
                for q in lucky_queries(KEYWORDS, UK_US, random.Random(seed))}
        self.assertEqual(len(seen), 3)  # UK-only, US-only, and both all roll

    def test_small_pool_never_asks_for_more_than_it_has(self):
        queries = lucky_queries(["only", "two"], UK_US, random.Random(0))
        self.assertLessEqual(len(queries), 2)


class LoadKeywords(unittest.TestCase):
    def _write(self, text: str) -> Path:
        d = tempfile.mkdtemp()
        p = Path(d) / "lucky.yaml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_flattens_categories_and_dedupes_case_insensitively(self):
        p = self._write(
            "keywords:\n"
            "  topics: [economy, AI]\n"
            "  leaders: [Andy Burnham, economy]\n"   # dupe across categories
        )
        self.assertEqual(load_keywords(p), ["economy", "AI", "Andy Burnham"])

    def test_missing_keywords_mapping_is_a_config_error(self):
        with self.assertRaises(ConfigError):
            load_keywords(self._write("topics: [economy]\n"))

    def test_non_list_category_is_a_config_error(self):
        with self.assertRaises(ConfigError):
            load_keywords(self._write("keywords:\n  topics: economy\n"))

    def test_missing_file_is_a_config_error(self):
        with self.assertRaises(ConfigError):
            load_keywords("does-not-exist.yaml")


class ShippedPool(unittest.TestCase):
    """Guards the real lucky.yaml at the repo root."""

    POOL = Path(__file__).resolve().parent.parent / "lucky.yaml"

    def test_loads_and_is_big_enough(self):
        keywords = load_keywords(self.POOL)
        self.assertGreaterEqual(len(keywords), 800)
        self.assertEqual(len(keywords), len({k.casefold() for k in keywords}))

    def test_contains_the_promised_entries(self):
        keywords = load_keywords(self.POOL)
        for expected in ("Andy Burnham", "Donald Trump", "climate change",
                         "economy", "technology", "AI", "video games"):
            self.assertIn(expected, keywords)


if __name__ == "__main__":
    unittest.main()
