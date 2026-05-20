import unittest
import tempfile
from pathlib import Path

from paperwatch.config import DEFAULT_CONFIG, load_settings


class ConfigTest(unittest.TestCase):
    def test_load_default_config_with_ranking_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(DEFAULT_CONFIG, encoding="utf-8")
            settings = load_settings(path)
        self.assertEqual(settings.ranking.mode, "keyword")
        self.assertTrue(settings.embedding.model)
        self.assertEqual(settings.embedding.api_key, "")
        self.assertEqual(settings.embedding.api_key_env, "RANKING_API_KEY")
        self.assertEqual(settings.ai.language, "Chinese")
        self.assertEqual(settings.ai.api_key_env, "TRANSLATION_API_KEY")
        self.assertEqual(settings.digest_ai.language, "Chinese")
        self.assertEqual(settings.digest_ai.api_key_env, "DIGEST_AI_API_KEY")
        self.assertTrue(settings.interest_ai.model)
        self.assertEqual(settings.interest_ai.api_key_env, "INTEREST_BUILDER_API_KEY")
        self.assertTrue(settings.translation.enabled)
        self.assertTrue(settings.translation.translate_title)
        self.assertFalse(settings.schedule.enabled)
        self.assertEqual(settings.schedule.hour, 12)
        self.assertEqual(settings.schedule.minute, 30)
        self.assertFalse(settings.feishu.enabled)
        self.assertTrue(settings.feishu.send_on_schedule)
        self.assertFalse(settings.openalex.enabled)
        self.assertEqual(settings.arxiv.fetch_mode, "search")
        self.assertEqual(settings.openalex.max_results_per_interest, 40)
        self.assertFalse(settings.dblp.enabled)
        self.assertEqual(settings.dblp.max_results_per_interest, 40)
        self.assertGreaterEqual(len(settings.interests), 1)
        self.assertIn("CV Model Generation", settings.default_fetch_interests)
        self.assertEqual(settings.interests[0].keyword_weights["image generation"], 1.0)

    def test_zero_per_interest_limit_means_unlimited(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(DEFAULT_CONFIG.replace("per_interest_limit = 10", "per_interest_limit = 0"), encoding="utf-8")
            settings = load_settings(path)
        self.assertIsNone(settings.per_interest_limit)

    def test_rejects_invalid_schedule_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(DEFAULT_CONFIG.replace("hour = 12", "hour = 25"), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_settings(path)

    def test_loads_keyword_weights(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            content = DEFAULT_CONFIG.replace(
                "keyword_weights = {}",
                'keyword_weights = { "image generation" = 2.5, "diffusion model" = 1.7 }',
            )
            path.write_text(content, encoding="utf-8")
            settings = load_settings(path)
        self.assertEqual(settings.interests[0].keyword_weights["image generation"], 2.5)
        self.assertEqual(settings.interests[0].keyword_weights["diffusion model"], 1.7)


if __name__ == "__main__":
    unittest.main()
