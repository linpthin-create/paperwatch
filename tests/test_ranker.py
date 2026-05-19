from datetime import datetime, timezone
import unittest

from paperwatch.models import Interest, Paper
from paperwatch.rankers.keyword import score_paper, score_papers_by_interest


class KeywordRankerTest(unittest.TestCase):
    def test_keyword_score_prefers_title_matches(self):
        paper = Paper(
            source="arxiv",
            paper_id="2601.00001",
            title="A Diffusion Model for Controllable Image Generation",
            authors=["A. Researcher"],
            abstract="We study visual generation.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=None,
            url="https://arxiv.org/abs/2601.00001",
            categories=["cs.CV"],
        )
        interest = Interest(
            name="CV Model Generation",
            keywords=["diffusion model", "image generation"],
            negative_keywords=[],
            arxiv_categories=["cs.CV"],
        )
        scored = score_paper(paper, interest)
        self.assertGreaterEqual(scored.score, 11)
        self.assertIn("diffusion model", scored.matched_keywords)

    def test_negative_keyword_blocks_paper(self):
        paper = Paper(
            source="arxiv",
            paper_id="2601.00002",
            title="Medical Image Segmentation with Diffusion Models",
            authors=["A. Researcher"],
            abstract="A diffusion model for segmentation.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=None,
            url="https://arxiv.org/abs/2601.00002",
            categories=["cs.CV"],
        )
        interest = Interest(
            name="CV Model Generation",
            keywords=["diffusion model"],
            negative_keywords=["medical image segmentation"],
            arxiv_categories=["cs.CV"],
        )
        scored = score_paper(paper, interest)
        self.assertLess(scored.score, 0)

    def test_keyword_weights_scale_matches(self):
        paper = Paper(
            source="arxiv",
            paper_id="2601.00005",
            title="A Diffusion Model",
            authors=["A. Researcher"],
            abstract="A diffusion model for generation.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=None,
            url="https://arxiv.org/abs/2601.00005",
            categories=[],
        )
        base = Interest(name="Base", keywords=["diffusion model"])
        weighted = Interest(name="Weighted", keywords=["diffusion model"], keyword_weights={"diffusion model": 2.0})
        self.assertGreater(score_paper(paper, weighted).score, score_paper(paper, base).score)

    def test_score_papers_by_interest_keeps_independent_lists(self):
        paper = Paper(
            source="arxiv",
            paper_id="2601.00003",
            title="A Diffusion Model for Video Generation",
            authors=["A. Researcher"],
            abstract="We study image generation and video synthesis.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=None,
            url="https://arxiv.org/abs/2601.00003",
            categories=["cs.CV"],
        )
        interests = [
            Interest(name="Image Generation", keywords=["image generation"], arxiv_categories=["cs.CV"]),
            Interest(name="Video Generation", keywords=["video generation"], arxiv_categories=["cs.CV"]),
        ]
        grouped = score_papers_by_interest([paper], interests)
        self.assertEqual(len(grouped["Image Generation"]), 1)
        self.assertEqual(len(grouped["Video Generation"]), 1)

    def test_category_only_match_is_not_reported_when_keywords_exist(self):
        paper = Paper(
            source="arxiv",
            paper_id="2601.00004",
            title="Unrelated Vision Benchmark",
            authors=["A. Researcher"],
            abstract="A broad benchmark with no configured topic phrase.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=None,
            url="https://arxiv.org/abs/2601.00004",
            categories=["cs.CV"],
        )
        interest = Interest(name="Image Generation", keywords=["image generation"], arxiv_categories=["cs.CV"])
        grouped = score_papers_by_interest([paper], [interest])
        self.assertEqual(grouped["Image Generation"], [])


if __name__ == "__main__":
    unittest.main()
