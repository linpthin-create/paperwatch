import tempfile
import unittest
from pathlib import Path
from unittest import mock

from paperwatch.config import DEFAULT_CONFIG
from paperwatch.ui import PaperWatchHandler
from paperwatch.ui import (
    _extract_arxiv_id,
    _extract_arxiv_ids,
    _fetch_arxiv_record,
    _parse_daily_cron,
    _preserve_nonempty_api_routing,
    _replace_daily_cron,
    _resolve_interest_builder_input,
    _shanghai_to_utc,
    _truncate_source_text,
    _utc_to_shanghai,
)


class FakeHandler(PaperWatchHandler):
    def __init__(self, config_path):
        self.config_path = Path(config_path)


class ConfigPostHandler(FakeHandler):
    def __init__(self, config_path, content):
        super().__init__(config_path)
        self.path = "/api/config"
        self._content = content
        self.response = None

    def _read_json(self):
        return {"content": self._content}

    def _send_json(self, payload):
        self.response = payload


class UiTest(unittest.TestCase):
    def test_list_read_and_delete_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            db = Path(tmp) / "papers.sqlite"
            digests = Path(tmp) / "digests"
            digests.mkdir()
            (digests / "2026-05-06.md").write_text("# Digest", encoding="utf-8")
            content = DEFAULT_CONFIG.replace('database_path = "data/papers.sqlite"', f'database_path = "{db}"')
            content = content.replace('digest_dir = "data/digests"', f'digest_dir = "{digests}"')
            cfg.write_text(content, encoding="utf-8")

            handler = FakeHandler(cfg)
            self.assertEqual(handler._list_digests(), ["2026-05-06.md"])
            self.assertEqual(handler._read_digest("2026-05-06.md"), "# Digest")
            handler._delete_digest("2026-05-06.md")
            self.assertEqual(handler._list_digests(), [])

    def test_index_html_is_present(self):
        from paperwatch.ui import INDEX_HTML

        self.assertIn("PaperWatch", INDEX_HTML)
        self.assertIn("/api/config", INDEX_HTML)
        self.assertIn("Date range", INDEX_HTML)
        self.assertIn("None / all arXiv papers", INDEX_HTML)
        self.assertIn("Maximum papers (blank = unlimited)", INDEX_HTML)
        self.assertIn("cfg-ranking-mode", INDEX_HTML)
        self.assertIn("config-raw-toggle", INDEX_HTML)
        self.assertIn("cfg-ai-key-env", INDEX_HTML)
        self.assertIn("cfg-embedding-key-env", INDEX_HTML)
        self.assertIn("cfg-interest-ai-key-env", INDEX_HTML)
        self.assertIn("cfg-digest-ai-key-env", INDEX_HTML)
        self.assertIn("cfg-default-fetch-interests", INDEX_HTML)
        self.assertIn("markdown-preview", INDEX_HTML)
        self.assertIn("markdownToHtml", INDEX_HTML)
        self.assertIn("keyword | weight", INDEX_HTML)
        self.assertIn("keyword_weights", INDEX_HTML)
        self.assertIn("cfg-schedule-enabled", INDEX_HTML)
        self.assertIn("cfg-schedule-hour", INDEX_HTML)
        self.assertIn("cfg-feishu-enabled", INDEX_HTML)
        self.assertIn("cfg-feishu-send-schedule", INDEX_HTML)
        self.assertIn("cfg-feishu-webhook", INDEX_HTML)
        self.assertIn("/api/schedule-status", INDEX_HTML)
        self.assertIn("scheduleAction('install')", INDEX_HTML)
        self.assertIn("check-list", INDEX_HTML)
        self.assertIn("populateDefaultFetchChecks", INDEX_HTML)
        self.assertIn("checkedValues('cfg-default-fetch-interests')", INDEX_HTML)
        self.assertIn("Interests", INDEX_HTML)
        self.assertIn("New interest", INDEX_HTML)
        self.assertIn("addBlankInterest", INDEX_HTML)
        self.assertIn("saveSelectedInterest", INDEX_HTML)
        self.assertIn("deleteSelectedInterest", INDEX_HTML)
        self.assertIn("Paper links / title / abstract / notes", INDEX_HTML)
        self.assertIn("/api/generate-interest-job", INDEX_HTML)
        self.assertIn("/api/generate-interest-status", INDEX_HTML)
        self.assertIn("/api/test-embedding", INDEX_HTML)
        self.assertIn("Ranking Embedding API", INDEX_HTML)
        self.assertIn("Test Ranking Embedding API", INDEX_HTML)
        self.assertIn("Digest AI API", INDEX_HTML)
        self.assertIn("Test Digest AI API", INDEX_HTML)
        self.assertIn("Translation API", INDEX_HTML)
        self.assertIn("/api/send-digest-feishu", INDEX_HTML)
        self.assertIn("Send Feishu", INDEX_HTML)
        self.assertIn("cfg-enabled-sources", INDEX_HTML)
        self.assertIn("cfg-arxiv-fetch-mode", INDEX_HTML)
        self.assertIn("OAI daily metadata", INDEX_HTML)
        self.assertIn("OpenAlex", INDEX_HTML)
        self.assertIn("dblp", INDEX_HTML)
        self.assertIn("/api/test-source", INDEX_HTML)
        self.assertIn("testSource('arxiv')", INDEX_HTML)
        self.assertIn("/api/run-status", INDEX_HTML)
        self.assertIn("pollRunStatus", INDEX_HTML)
        self.assertIn("config-nav", INDEX_HTML)
        self.assertIn("module-help", INDEX_HTML)
        self.assertIn("updateConfigNavActive", INDEX_HTML)
        self.assertIn("setConfigNavActive", INDEX_HTML)
        self.assertIn("data-target=\"cfg-auto\"", INDEX_HTML)
        self.assertIn("data-target=\"cfg-github\"", INDEX_HTML)
        self.assertIn("syncPrivateConfig", INDEX_HTML)
        self.assertIn("/api/sync-private-config", INDEX_HTML)
        self.assertIn("cfg-github-hour", INDEX_HTML)
        self.assertIn("cfg-github-minute", INDEX_HTML)
        self.assertIn("loadGithubSchedule", INDEX_HTML)
        self.assertIn("saveGithubSchedule", INDEX_HTML)
        self.assertIn("/api/github-schedule", INDEX_HTML)
        self.assertIn("scrollConfigModule", INDEX_HTML)
        self.assertIn("cfg-auto", INDEX_HTML)
        self.assertIn("sendCurrentDigestFeishu", INDEX_HTML)
        self.assertIn("deleteCurrentDigest", INDEX_HTML)
        self.assertNotIn("AI Chat API", INDEX_HTML)
        self.assertIn("/api/test-ai", INDEX_HTML)
        self.assertIn("/api/generate-interest", INDEX_HTML)
        self.assertIn("digest-row", INDEX_HTML)
        self.assertNotIn("Yesterday", INDEX_HTML)
        self.assertNotIn("Preview rerank", INDEX_HTML)
        self.assertIn("section(text, name)", INDEX_HTML)
        self.assertIn("line.trim() === header", INDEX_HTML)
        self.assertIn("lines.findIndex", INDEX_HTML)

    def test_section_parser_does_not_match_comment_mentions(self):
        from paperwatch.ui import INDEX_HTML

        self.assertIn("const header = `[${name}]`", INDEX_HTML)
        self.assertIn("return lines.slice(start + 1, end).join('\\n')", INDEX_HTML)

    def test_sync_private_config_runs_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "private"
            repo.mkdir()
            (repo / ".git").mkdir()
            cfg = Path(tmp) / "config.toml"
            cfg.write_text(
                DEFAULT_CONFIG.replace('api_key = ""', 'api_key = "secret-key"', 1)
                .replace('webhook_url = ""', 'webhook_url = "https://example.test/hook"', 1)
                .replace('secret = ""', 'secret = "signing-secret"', 1),
                encoding="utf-8",
            )
            handler = FakeHandler(cfg)

            with mock.patch.object(handler, "_run_git") as run_git:
                with mock.patch("paperwatch.ui.subprocess.run", return_value=subprocess_result(returncode=1)):
                    result = handler._sync_private_config(str(repo))

            self.assertEqual(result["message"], "Private config synced and pushed.")
            synced = (repo / "config.toml").read_text(encoding="utf-8")
            self.assertIn('api_key = ""', synced)
            self.assertIn('webhook_url = ""', synced)
            self.assertIn('secret = ""', synced)
            self.assertNotIn("secret-key", synced)
            self.assertEqual(run_git.call_count, 3)

    def test_sync_private_config_preserves_existing_api_routing_when_local_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "private"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / "config.toml").write_text(
                DEFAULT_CONFIG.replace('base_url = "https://api.openai.com/v1"', 'base_url = "https://example.test/v1"', 1)
                .replace('model = "text-embedding-3-small"', 'model = "embedding-model"', 1),
                encoding="utf-8",
            )
            cfg = Path(tmp) / "config.toml"
            cfg.write_text(
                DEFAULT_CONFIG.replace('base_url = "https://api.openai.com/v1"', 'base_url = ""', 1)
                .replace('model = "text-embedding-3-small"', 'model = ""', 1),
                encoding="utf-8",
            )
            handler = FakeHandler(cfg)

            with mock.patch.object(handler, "_run_git"):
                with mock.patch("paperwatch.ui.subprocess.run", return_value=subprocess_result(returncode=1)):
                    handler._sync_private_config(str(repo))

            synced = (repo / "config.toml").read_text(encoding="utf-8")
            self.assertIn('base_url = "https://example.test/v1"', synced)
            self.assertIn('model = "embedding-model"', synced)

    def test_save_config_preserves_existing_api_routing_when_submitted_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            current = DEFAULT_CONFIG.replace(
                'base_url = "https://api.openai.com/v1"',
                'base_url = "https://example.test/v1"',
                1,
            ).replace('model = "text-embedding-3-small"', 'model = "embedding-model"', 1)
            submitted = current.replace('base_url = "https://example.test/v1"', 'base_url = ""', 1).replace(
                'model = "embedding-model"',
                'model = ""',
                1,
            )
            cfg.write_text(current, encoding="utf-8")
            handler = ConfigPostHandler(cfg, submitted)

            handler.do_POST()

            saved = cfg.read_text(encoding="utf-8")
            self.assertEqual(handler.response, {"ok": True})
            self.assertIn('base_url = "https://example.test/v1"', saved)
            self.assertIn('model = "embedding-model"', saved)

    def test_test_arxiv_source_uses_single_lightweight_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text(DEFAULT_CONFIG, encoding="utf-8")
            handler = FakeHandler(cfg)

            with mock.patch("paperwatch.sources.arxiv.ArxivSource.fetch_query_once", return_value=[]) as fetch:
                result = handler._test_source(__import__("paperwatch.config").config.load_settings(cfg), "arxiv")

            self.assertEqual(result, {"count": 0})
            self.assertEqual(fetch.call_count, 1)

    def test_test_arxiv_source_reports_export_rate_limit_when_site_reachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text(DEFAULT_CONFIG, encoding="utf-8")
            handler = FakeHandler(cfg)

            with mock.patch("paperwatch.sources.arxiv.ArxivSource.fetch_query_once", side_effect=RuntimeError("arXiv request failed with HTTP 429: Unknown Error")):
                with mock.patch.object(handler, "_test_arxiv_abs_page"):
                    result = handler._test_source(__import__("paperwatch.config").config.load_settings(cfg), "arxiv")

            self.assertEqual(result["count"], 0)
            self.assertIn("rate-limited", result["warning"])

    def test_test_arxiv_source_uses_oai_when_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            cfg.write_text(DEFAULT_CONFIG.replace('fetch_mode = "search"', 'fetch_mode = "oai_daily"'), encoding="utf-8")
            handler = FakeHandler(cfg)

            with mock.patch.object(handler, "_test_arxiv_oai") as test_oai:
                result = handler._test_source(__import__("paperwatch.config").config.load_settings(cfg), "arxiv")

            self.assertIn("OAI-PMH", result["message"])
            self.assertEqual(test_oai.call_count, 1)

    def test_sync_private_config_reports_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "private"
            repo.mkdir()
            (repo / ".git").mkdir()
            cfg = Path(tmp) / "config.toml"
            cfg.write_text(DEFAULT_CONFIG, encoding="utf-8")
            handler = FakeHandler(cfg)

            with mock.patch.object(handler, "_run_git", side_effect=RuntimeError("push failed")):
                with self.assertRaises(RuntimeError) as raised:
                    handler._sync_private_config(str(repo))

            self.assertIn("push failed", str(raised.exception))

    def test_github_schedule_reads_beijing_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "private"
            workflow = repo / ".github" / "workflows"
            workflow.mkdir(parents=True)
            (repo / ".git").mkdir()
            (workflow / "daily-paperwatch.yml").write_text(
                'on:\n  schedule:\n    - cron: "30 4 * * *" # 12:30 Asia/Shanghai\n',
                encoding="utf-8",
            )
            cfg = Path(tmp) / "config.toml"
            cfg.write_text(DEFAULT_CONFIG, encoding="utf-8")

            schedule = FakeHandler(cfg)._github_schedule(str(repo))

            self.assertEqual(schedule["hour"], 12)
            self.assertEqual(schedule["minute"], 30)
            self.assertEqual(schedule["cron"], "30 4 * * *")

    def test_update_github_schedule_writes_utc_cron(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "private"
            workflow = repo / ".github" / "workflows"
            workflow.mkdir(parents=True)
            (repo / ".git").mkdir()
            path = workflow / "daily-paperwatch.yml"
            path.write_text(
                'on:\n  schedule:\n    - cron: "30 4 * * *" # 12:30 Asia/Shanghai\n',
                encoding="utf-8",
            )
            cfg = Path(tmp) / "config.toml"
            cfg.write_text(DEFAULT_CONFIG, encoding="utf-8")
            handler = FakeHandler(cfg)

            with mock.patch.object(handler, "_run_git") as run_git:
                result = handler._update_github_schedule(str(repo), 9, 5)

            self.assertIn('cron: "5 1 * * *" # 09:05 Asia/Shanghai', path.read_text(encoding="utf-8"))
            self.assertIn("09:05", result["message"])
            self.assertEqual(run_git.call_count, 3)

    def test_cron_helpers_convert_times(self):
        content = '    - cron: "0 15 * * *" # 23:00 Asia/Shanghai\n'
        self.assertEqual(_parse_daily_cron(content), (0, 15))
        self.assertEqual(_utc_to_shanghai(15, 0), (23, 0))
        self.assertEqual(_shanghai_to_utc(23, 0), (15, 0))
        updated = _replace_daily_cron(content, "0 1 * * *", "09:00 Asia/Shanghai")
        self.assertIn('cron: "0 1 * * *" # 09:00 Asia/Shanghai', updated)

    def test_preserve_nonempty_api_routing_keeps_old_when_new_blank(self):
        new = '[embedding]\napi_key_env = ""\nbase_url = ""\nmodel = ""\n'
        old = '[embedding]\napi_key_env = "RANKING_API_KEY"\nbase_url = "https://example.test/v1"\nmodel = "m"\n'
        merged = _preserve_nonempty_api_routing(new, old)
        self.assertIn('api_key_env = ""', merged)
        self.assertIn('base_url = "https://example.test/v1"', merged)
        self.assertIn('model = "m"', merged)

    def test_serve_ui_accepts_open_browser_argument(self):
        import inspect
        from paperwatch.ui import serve_ui

        self.assertIn("open_browser", inspect.signature(serve_ui).parameters)

    def test_extract_arxiv_id_from_abs_url(self):
        self.assertEqual(_extract_arxiv_id("https://arxiv.org/abs/2605.12345"), "2605.12345")
        self.assertEqual(_extract_arxiv_id("arXiv:2605.12345v2"), "2605.12345v2")

    def test_extract_multiple_arxiv_ids_from_links(self):
        text = "https://arxiv.org/abs/2605.12345\nhttps://arxiv.org/abs/2605.54321v2"
        self.assertEqual(_extract_arxiv_ids(text), ["2605.12345", "2605.54321v2"])

    def test_truncate_source_text_keeps_per_paper_budget(self):
        truncated = _truncate_source_text("x" * 20, 10)
        self.assertTrue(truncated.startswith("x" * 10))
        self.assertIn("Truncated for prompt budget", truncated)

    def test_fetch_arxiv_record_falls_back_to_abs_page_after_429(self):
        html = """
        <meta name="citation_title" content="Fallback Paper Title" />
        <meta name="citation_author" content="A. Researcher" />
        <meta name="citation_pdf_url" content="https://arxiv.org/pdf/2605.12345" />
        <blockquote class="abstract mathjax"><span class="descriptor">Abstract:</span>
        Fallback abstract text.</blockquote>
        <td class="tablecell subjects">Computer Vision and Pattern Recognition (cs.CV)</td>
        """
        with mock.patch(
            "paperwatch.ui._open_with_retries",
            side_effect=[RuntimeError("HTTP 429: Too Many Requests"), html.encode("utf-8")],
        ):
            record = _fetch_arxiv_record("2605.12345")
        self.assertEqual(record["title"], "Fallback Paper Title")
        self.assertEqual(record["abstract"], "Fallback abstract text.")
        self.assertEqual(record["authors"], ["A. Researcher"])
        self.assertEqual(record["categories"], ["cs.CV"])

    def test_resolve_interest_builder_input_keeps_going_when_pdf_unavailable(self):
        record = {
            "paper_id": "2605.12345",
            "title": "Fallback Paper Title",
            "abstract": "Abstract text.",
            "authors": ["A. Researcher"],
            "categories": ["cs.CV"],
            "published_at": "2026-05-18",
            "pdf_url": "https://arxiv.org/pdf/2605.12345",
        }
        with mock.patch("paperwatch.ui._fetch_arxiv_record", return_value=record):
            with mock.patch("paperwatch.ui._extract_arxiv_pdf_text", side_effect=RuntimeError("HTTP 429")):
                text = _resolve_interest_builder_input("https://arxiv.org/abs/2605.12345")
        self.assertIn("Fallback Paper Title", text)
        self.assertIn("Full text unavailable: HTTP 429", text)


if __name__ == "__main__":
    unittest.main()


def subprocess_result(returncode=0, stdout="", stderr=""):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)
