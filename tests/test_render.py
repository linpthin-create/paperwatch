from datetime import datetime, timezone
import unittest

from paperwatch.models import Paper, PaperTranslation, ScoredPaper
from paperwatch.render.digest import render_markdown


class DigestRenderTest(unittest.TestCase):
    def test_render_markdown_contains_title_and_link(self):
        paper = Paper(
            source="arxiv",
            paper_id="2601.00001",
            title="A Diffusion Model for Image Generation",
            authors=["A. Researcher"],
            abstract="Abstract text.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=None,
            url="https://arxiv.org/abs/2601.00001",
            pdf_url="https://arxiv.org/pdf/2601.00001",
            categories=["cs.CV"],
        )
        digest = render_markdown(
            [ScoredPaper(paper, "CV Model Generation", 10.0, ["diffusion model"], [])],
            datetime(2026, 1, 2),
        )
        self.assertIn("A Diffusion Model for Image Generation", digest)
        self.assertIn("https://arxiv.org/abs/2601.00001", digest)

    def test_render_markdown_places_translation_under_original(self):
        paper = Paper(
            source="arxiv",
            paper_id="2601.00001",
            title="A Diffusion Model for Image Generation",
            authors=["A. Researcher"],
            abstract="Abstract text.",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=None,
            url="https://arxiv.org/abs/2601.00001",
            categories=["cs.CV"],
        )
        digest = render_markdown(
            [ScoredPaper(paper, "CV Model Generation", 10.0, ["diffusion model"], [])],
            datetime(2026, 1, 2),
            translations={
                ("CV Model Generation", "arxiv", "2601.00001"): PaperTranslation(
                    title="用于图像生成的扩散模型",
                    abstract="摘要文本。",
                )
            },
        )
        self.assertIn("### 1. A Diffusion Model for Image Generation\n### 用于图像生成的扩散模型", digest)
        self.assertIn("Abstract:\n\nAbstract text.\n\n摘要翻译:\n\n摘要文本。", digest)


if __name__ == "__main__":
    unittest.main()
