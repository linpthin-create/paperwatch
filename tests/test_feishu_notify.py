import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from paperwatch.models import FeishuConfig, Paper, ScoredPaper
from paperwatch.notify.feishu import DigestNotification, load_config, notify_digest, render_digest_body


class FeishuNotifyTest(unittest.TestCase):
    def test_missing_config_is_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_config(Path(tmp) / "missing.json"))

    def test_render_digest_body_contains_summary_and_top_paper(self):
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
        body = render_digest_body(
            DigestNotification(
                date_range="2026-01-01 to 2026-01-01",
                interests=["CV Model Generation"],
                ranking_mode="keyword",
                mode="scheduled",
                fetched_count=3,
                unique_count=2,
                inserted_count=1,
                recommendation_count=1,
                digest_paths=["data/digests/2026-01-02.md"],
                top_papers=[ScoredPaper(paper, "CV Model Generation", 9.0, ["diffusion"], [])],
            )
        )
        self.assertIn("Recommendations: 1", body)
        self.assertIn("[A Diffusion Model for Image Generation](https://arxiv.org/abs/2601.00001)", body)

    def test_notify_digest_posts_signed_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "feishu.json"
            config_path.write_text(
                json.dumps(
                    {
                        "mode": "push",
                        "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
                        "secret": "secret",
                    }
                ),
                encoding="utf-8",
            )
            notification = DigestNotification(
                date_range="2026-01-01 to 2026-01-01",
                interests=[],
                ranking_mode="none",
                mode="scheduled",
                fetched_count=0,
                unique_count=0,
                inserted_count=0,
                recommendation_count=0,
                digest_paths=["data/digests/2026-01-02.md"],
                top_papers=[],
            )
            with mock.patch("paperwatch.notify.feishu._post_json") as post_json:
                self.assertTrue(notify_digest(notification, config_path=config_path))

            url, payload = post_json.call_args.args
            self.assertEqual(url, "https://open.feishu.cn/open-apis/bot/v2/hook/test")
            self.assertEqual(payload["msg_type"], "interactive")
            self.assertIn("timestamp", payload)
            self.assertIn("sign", payload)

    def test_notify_digest_respects_config_disabled(self):
        notification = DigestNotification(
            date_range="2026-01-01 to 2026-01-01",
            interests=[],
            ranking_mode="none",
            mode="scheduled",
            fetched_count=0,
            unique_count=0,
            inserted_count=0,
            recommendation_count=0,
            digest_paths=[],
            top_papers=[],
        )
        with mock.patch("paperwatch.notify.feishu._post_json") as post_json:
            sent = notify_digest(
                notification,
                config=FeishuConfig(enabled=False, webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test"),
            )
        self.assertFalse(sent)
        post_json.assert_not_called()

    def test_notify_digest_respects_send_on_schedule(self):
        notification = DigestNotification(
            date_range="2026-01-01 to 2026-01-01",
            interests=[],
            ranking_mode="none",
            mode="scheduled",
            fetched_count=0,
            unique_count=0,
            inserted_count=0,
            recommendation_count=0,
            digest_paths=[],
            top_papers=[],
        )
        with mock.patch("paperwatch.notify.feishu._post_json") as post_json:
            sent = notify_digest(
                notification,
                config=FeishuConfig(
                    enabled=True,
                    send_on_schedule=False,
                    webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
                ),
            )
        self.assertFalse(sent)
        post_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
