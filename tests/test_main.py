import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from datetime import datetime, timezone

from paperwatch.main import _dedupe, _is_no_rank, _run, _select_interests
from paperwatch.models import Interest, Paper


class MainSelectionTest(unittest.TestCase):
    def test_select_interests_uses_default_fetch_list(self):
        interests = [Interest(name="A"), Interest(name="B"), Interest(name="C")]
        selected = _select_interests(interests, None, ["A", "C"])
        self.assertEqual([item.name for item in selected], ["A", "C"])

    def test_select_interests_supports_requested_list(self):
        interests = [Interest(name="A"), Interest(name="B")]
        selected = _select_interests(interests, ["B"], ["A"])
        self.assertEqual([item.name for item in selected], ["B"])

    def test_select_interests_deduplicates_duplicate_names(self):
        interests = [Interest(name="A"), Interest(name="A"), Interest(name="B")]
        selected = _select_interests(interests, None, ["A"])
        self.assertEqual([item.name for item in selected], ["A"])

    def test_no_rank_accepts_list(self):
        self.assertTrue(_is_no_rank(["none"]))

    def test_dedupe_merges_cross_source_by_doi_and_title(self):
        arxiv = Paper(
            source="arxiv",
            paper_id="2601.00001",
            title="A Shared Paper",
            authors=[],
            abstract="",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=None,
            url="https://arxiv.org/abs/2601.00001",
            doi="10.0000/shared",
        )
        openalex = Paper(
            source="openalex",
            paper_id="W1",
            title="A Shared Paper",
            authors=[],
            abstract="",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=None,
            url="https://doi.org/10.0000/shared",
            doi="https://doi.org/10.0000/shared",
        )
        dblp = Paper(
            source="dblp",
            paper_id="conf/x/y",
            title="A Shared Paper.",
            authors=[],
            abstract="",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=None,
            url="https://dblp.org/rec/conf/x/y",
        )
        self.assertEqual(_dedupe([arxiv, openalex, dblp]), [arxiv])

    def test_run_writes_separate_reports_for_default_interests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.toml"
            digest_dir = root / "digests"
            config.write_text(
                f"""
timezone = "Asia/Shanghai"
daily_limit = 20
per_interest_limit = 2
database_path = "{root / 'papers.sqlite'}"
digest_dir = "{digest_dir}"

[ranking]
mode = "keyword"
candidate_limit_per_interest = 40

[embedding]
api_key = ""
api_key_env = "OPENAI_API_KEY"
base_url = ""
model = ""
timeout_seconds = 60

[ai]
api_key = ""
api_key_env = "OPENAI_API_KEY"
base_url = ""
model = ""
language = "Chinese"
max_papers_per_interest = 10
timeout_seconds = 90

[translation]
enabled = false
language = "Chinese"
translate_title = true
translate_abstract = true
max_papers_per_run = 20

[interest_ai]
api_key = ""
api_key_env = "OPENAI_API_KEY"
base_url = ""
model = ""
timeout_seconds = 90

[sources.arxiv]
enabled = false
max_results_per_interest = 80
include_cross_list = true
request_timeout_seconds = 30
default_fetch_interests = ["A", "B"]

[[interests]]
name = "A"
description = ""
arxiv_categories = ["cs.CV"]
keywords = ["image"]
negative_keywords = []

[[interests]]
name = "B"
description = ""
arxiv_categories = ["cs.LG"]
keywords = ["learning"]
negative_keywords = []
""",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                config=str(config),
                days=1,
                start_date=None,
                end_date=None,
                interest=None,
                interests=None,
                ranking_mode=None,
                limit=None,
                include_sent=False,
                no_mark_sent=True,
                timestamped=False,
                label=None,
            )

            with mock.patch("paperwatch.main.notify_digest"):
                self.assertEqual(_run(args), 0)
            names = sorted(path.name for path in digest_dir.glob("*.md"))
            self.assertEqual(len(names), 2)
            self.assertTrue(any(name.endswith("-a.md") for name in names))
            self.assertTrue(any(name.endswith("-b.md") for name in names))


if __name__ == "__main__":
    unittest.main()
