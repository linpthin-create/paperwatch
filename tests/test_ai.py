import unittest
from datetime import datetime, timezone

from paperwatch.ai import (
    _build_interest_prompt,
    _interest_payload_to_toml,
    _parse_insights,
    _parse_interest_payload,
    _parse_translations,
    generate_translations,
)
from paperwatch.models import AiConfig, Paper, ScoredPaper, TranslationConfig


class FakeTranslationClient:
    def __init__(self):
        self.available = True
        self.calls = 0

    def chat(self, model, messages, temperature=0.2):
        self.calls += 1
        user = messages[-1]["content"]
        if "2601.00001" in user:
            return '{"2601.00001": {"title": "标题一", "abstract": "摘要一"}}'
        return '{"2601.00002": {"title": "标题二", "abstract": "摘要二"}}'


class AiInsightTest(unittest.TestCase):
    def test_parse_insights_from_json_object(self):
        parsed = _parse_insights(
            '{"2601.00001": {"tldr": "Short summary", "relevance": "Highly relevant", "priority": "High"}}'
        )
        self.assertEqual(parsed["2601.00001"].priority, "High")
        self.assertEqual(parsed["2601.00001"].tldr, "Short summary")

    def test_parse_translations_from_json_object(self):
        parsed = _parse_translations(
            '{"2601.00001": {"title": "图像生成扩散模型", "abstract": "摘要翻译。"}}'
        )
        self.assertEqual(parsed["2601.00001"].title, "图像生成扩散模型")
        self.assertEqual(parsed["2601.00001"].abstract, "摘要翻译。")

    def test_parse_interest_payload_and_render_toml(self):
        payload = _parse_interest_payload(
            '{"name":"Test Direction","description":"A test direction.","arxiv_categories":["cs.CV"],'
            '"keywords":["diffusion model","image generation"],"negative_keywords":["segmentation"],'
            '"keyword_weights":{"diffusion model":2.5,"image generation":1.5},'
            '"seed_papers":["A Paper Title"]}'
        )
        toml = _interest_payload_to_toml(payload)
        self.assertIn("[[interests]]", toml)
        self.assertIn('name = "Test Direction"', toml)
        self.assertIn('"diffusion model"', toml)
        self.assertIn('keyword_weights = { "diffusion model" = 2.5, "image generation" = 1.5 }', toml)

    def test_build_interest_prompt_keeps_large_text_budget(self):
        prompt = _build_interest_prompt("x" * 60000)
        self.assertIn("x" * 60000, prompt)

    def test_build_interest_prompt_asks_for_reusable_domain_scope(self):
        prompt = _build_interest_prompt("paper")
        self.assertIn("stable research area", prompt)
        self.assertIn("not just the exact method", prompt)
        self.assertIn("keyword_weights", prompt)

    def test_generate_translations_batches_all_selected_papers(self):
        items = [
            ScoredPaper(_paper("2601.00001"), "A", 1.0, [], []),
            ScoredPaper(_paper("2601.00002"), "A", 1.0, [], []),
        ]
        client = FakeTranslationClient()
        translations = generate_translations(
            items,
            AiConfig(api_key="key", api_key_env="", base_url="https://example.test", model="m"),
            TranslationConfig(enabled=True, max_papers_per_run=1),
            client=client,
        )
        self.assertEqual(client.calls, 2)
        self.assertEqual(len(translations), 2)


def _paper(paper_id: str) -> Paper:
    return Paper(
        source="arxiv",
        paper_id=paper_id,
        title=f"Paper {paper_id}",
        authors=["A. Researcher"],
        abstract="Abstract text.",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=None,
        url=f"https://arxiv.org/abs/{paper_id}",
        categories=["cs.CV"],
    )


if __name__ == "__main__":
    unittest.main()
