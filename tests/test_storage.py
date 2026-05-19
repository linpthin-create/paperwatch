import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from paperwatch.models import Paper, ScoredPaper
from paperwatch.storage import PaperStore


def _paper() -> Paper:
    return Paper(
        source="arxiv",
        paper_id="2601.00001",
        title="A Paper",
        authors=["A. Researcher"],
        abstract="Abstract.",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=None,
        url="https://arxiv.org/abs/2601.00001",
        categories=["cs.CV"],
    )


class PaperStoreTest(unittest.TestCase):
    def test_sent_filter_is_interest_specific(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PaperStore(Path(tmp) / "papers.sqlite")
            paper = _paper()
            store.save_papers([paper])
            item_a = ScoredPaper(paper, "A", 1.0, ["paper"], [])
            item_b = ScoredPaper(paper, "B", 1.0, ["paper"], [])

            store.mark_sent([item_a], "a.md")

            self.assertEqual(store.filter_unsent([item_a]), [])
            self.assertEqual(store.filter_unsent([item_b]), [item_b])
            store.close()


if __name__ == "__main__":
    unittest.main()
