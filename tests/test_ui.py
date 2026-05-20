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
    _resolve_interest_builder_input,
    _truncate_source_text,
)


class FakeHandler(PaperWatchHandler):
    def __init__(self, config_path):
        self.config_path = Path(config_path)


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
