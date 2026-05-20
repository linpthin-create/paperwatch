from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import webbrowser
import contextlib
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from paperwatch.config import ensure_default_config, load_settings
from paperwatch.sources.arxiv import ARXIV_API_URL, ATOM_NS


ARXIV_ABS_URL_RE = re.compile(r"https?://arxiv\.org/abs/([^\s?#]+)", re.IGNORECASE)
ARXIV_ID_RE = re.compile(r"(?<!\w)((?:\d{4}\.\d{4,5}|[a-z\-]+/\d{7})(?:v\d+)?)(?!\w)", re.IGNORECASE)
MAX_INTEREST_SOURCE_PAPERS = 5
MAX_INTEREST_SOURCE_CHARS_PER_PAPER = 24000
ARXIV_RETRY_HTTP_CODES = {429, 500, 502, 503, 504}
ARXIV_RETRY_WAITS = [5, 15, 45]
_INTEREST_JOBS: dict[str, dict[str, object]] = {}
_INTEREST_JOBS_LOCK = threading.Lock()
_RUN_JOBS: dict[str, dict[str, object]] = {}
_RUN_JOBS_LOCK = threading.Lock()


def serve_ui(host: str, port: int, config_path: str, open_browser: bool = False) -> None:
    ensure_default_config(config_path)

    class Handler(PaperWatchHandler):
        pass

    Handler.config_path = Path(config_path)
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"PaperWatch UI: {url}")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    server.serve_forever()


class PaperWatchHandler(BaseHTTPRequestHandler):
    config_path = Path("config.toml")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(INDEX_HTML)
        elif parsed.path == "/api/config":
            self._send_json({"content": self.config_path.read_text(encoding="utf-8")})
        elif parsed.path == "/api/digests":
            self._send_json({"digests": self._list_digests()})
        elif parsed.path == "/api/digest":
            query = parse_qs(parsed.query)
            name = query.get("name", [""])[0]
            self._send_json({"content": self._read_digest(name)})
        elif parsed.path == "/api/generate-interest-status":
            query = parse_qs(parsed.query)
            job_id = query.get("job_id", [""])[0]
            self._send_json(_get_interest_job(job_id))
        elif parsed.path == "/api/run-status":
            query = parse_qs(parsed.query)
            job_id = query.get("job_id", [""])[0]
            self._send_json(_get_run_job(job_id))
        elif parsed.path == "/api/schedule-status":
            self._send_json(self._schedule_status())
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            body = self._read_json()
            content = str(body.get("content", ""))
            load_settings_from_text(content)
            self.config_path.write_text(content, encoding="utf-8")
            self._send_json({"ok": True})
        elif parsed.path == "/api/run":
            body = self._read_json()
            days = int(body.get("days", 1))
            limit = body.get("limit")
            args = argparse.Namespace(
                config=str(self.config_path),
                days=days,
                start_date=body.get("start_date") or None,
                end_date=body.get("end_date") or None,
                interest=body.get("interest") or None,
                ranking_mode=body.get("ranking_mode") or None,
                limit=int(limit) if limit else None,
                include_sent=bool(body.get("include_sent", True)),
                no_mark_sent=bool(body.get("no_mark_sent", True)),
                timestamped=True,
                label=body.get("label") or "manual",
            )
            job_id = _create_run_job()
            thread = threading.Thread(target=_run_fetch_job, args=(job_id, args), daemon=True)
            thread.start()
            self._send_json({"ok": True, "job_id": job_id, "message": "Run started."})
        elif parsed.path == "/api/delete-digest":
            body = self._read_json()
            self._delete_digest(str(body.get("name", "")))
            self._send_json({"ok": True})
        elif parsed.path == "/api/send-digest-feishu":
            body = self._read_json()
            try:
                sent = self._send_digest_to_feishu(str(body.get("name", "")))
                self._send_json({"ok": sent, "message": "Sent to Feishu." if sent else "Feishu is not configured or delivery failed."})
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)})
        elif parsed.path == "/api/test-ai":
            from paperwatch.ai import test_chat_config

            body = self._read_json()
            settings = load_settings(self.config_path)
            target = str(body.get("target", "ai"))
            if target == "interest_ai":
                config = settings.interest_ai
            elif target == "digest_ai":
                config = settings.digest_ai
            else:
                config = settings.ai
            try:
                reply = test_chat_config(config)
                self._send_json({"ok": True, "reply": reply})
            except RuntimeError as exc:
                self._send_json({"ok": False, "error": str(exc)})
        elif parsed.path == "/api/test-embedding":
            settings = load_settings(self.config_path)
            try:
                vector = self._test_embedding(settings)
                self._send_json({"ok": True, "dimensions": len(vector)})
            except RuntimeError as exc:
                self._send_json({"ok": False, "error": str(exc)})
        elif parsed.path == "/api/test-source":
            body = self._read_json()
            settings = load_settings(self.config_path)
            try:
                count = self._test_source(settings, str(body.get("target", "arxiv")))
                self._send_json({"ok": True, "count": count})
            except RuntimeError as exc:
                self._send_json({"ok": False, "error": str(exc)})
        elif parsed.path == "/api/schedule":
            body = self._read_json()
            try:
                result = self._schedule_action(str(body.get("action", "status")))
                self._send_json({"ok": True, **result})
            except RuntimeError as exc:
                self._send_json({"ok": False, "error": str(exc)})
        elif parsed.path == "/api/sync-private-config":
            body = self._read_json()
            try:
                result = self._sync_private_config(str(body.get("repo_path", "")))
                self._send_json({"ok": True, **result})
            except RuntimeError as exc:
                self._send_json({"ok": False, "error": str(exc)})
        elif parsed.path == "/api/generate-interest":
            from paperwatch.ai import generate_interest_from_paper

            body = self._read_json()
            settings = load_settings(self.config_path)
            try:
                paper_text = _resolve_interest_builder_input(str(body.get("paper_text", "")))
                toml = generate_interest_from_paper(paper_text, settings.interest_ai)
                self._send_json({"ok": True, "toml": toml})
            except RuntimeError as exc:
                self._send_json({"ok": False, "error": str(exc)})
        elif parsed.path == "/api/generate-interest-job":
            body = self._read_json()
            job_id = _create_interest_job()
            thread = threading.Thread(
                target=_run_interest_generation_job,
                args=(job_id, self.config_path, str(body.get("paper_text", ""))),
                daemon=True,
            )
            thread.start()
            self._send_json({"ok": True, "job_id": job_id})
        else:
            self.send_error(404)

    def log_message(self, format: str, *args) -> None:
        return

    def _list_digests(self) -> list[str]:
        settings = load_settings(self.config_path)
        digest_dir = Path(settings.digest_dir)
        if not digest_dir.exists():
            return []
        return sorted([path.name for path in digest_dir.glob("*.md")], reverse=True)

    def _read_digest(self, name: str) -> str:
        settings = load_settings(self.config_path)
        digest_dir = Path(settings.digest_dir).resolve()
        path = (digest_dir / name).resolve()
        if digest_dir not in path.parents and path != digest_dir:
            raise ValueError("invalid digest path")
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _delete_digest(self, name: str) -> None:
        settings = load_settings(self.config_path)
        digest_dir = Path(settings.digest_dir).resolve()
        path = (digest_dir / name).resolve()
        if digest_dir not in path.parents or path.suffix != ".md":
            raise ValueError("invalid digest path")
        if path.exists():
            path.unlink()

    def _send_digest_to_feishu(self, name: str) -> bool:
        from paperwatch.notify.feishu import notify_digest_markdown

        settings = load_settings(self.config_path)
        digest_dir = Path(settings.digest_dir).resolve()
        path = (digest_dir / name).resolve()
        if digest_dir not in path.parents or path.suffix != ".md":
            raise ValueError("invalid digest path")
        if not path.exists():
            raise ValueError("digest does not exist")
        return notify_digest_markdown(path.name, path.read_text(encoding="utf-8"), config=settings.feishu)

    def _test_embedding(self, settings) -> list[float]:
        from paperwatch.clients import OpenAICompatibleClient

        client = OpenAICompatibleClient(
            settings.embedding.api_key_env,
            settings.embedding.base_url,
            settings.embedding.timeout_seconds,
            api_key=settings.embedding.api_key,
        )
        if not client.available:
            raise RuntimeError("API key is not configured")
        vectors = client.embeddings(settings.embedding.model, ["PaperWatch embedding connectivity test."])
        if not vectors:
            raise RuntimeError("Embedding API returned no vectors")
        return vectors[0]

    def _test_source(self, settings, target: str) -> int:
        from datetime import date, timedelta
        from paperwatch.sources import ArxivSource, DblpSource, OpenAlexSource

        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=7)
        interest = settings.interests[0]
        if target == "arxiv":
            source = ArxivSource(settings.arxiv)
            return len(source.fetch(interest, start_date, end_date)[:1])
        if target == "openalex":
            source = OpenAlexSource(settings.openalex)
            return len(source.fetch(interest, start_date, end_date)[:1])
        if target == "dblp":
            source = DblpSource(settings.dblp)
            return len(source._fetch_query("machine learning", start_date.year, end_date.year, 1))
        raise RuntimeError(f"unknown source: {target}")

    def _schedule_status(self) -> dict:
        from paperwatch.schedule import schedule_status

        settings = load_settings(self.config_path)
        return {"ok": True, "status": schedule_status(self.config_path, settings)}

    def _schedule_action(self, action: str) -> dict:
        from paperwatch.schedule import install_schedule, schedule_status, uninstall_schedule

        settings = load_settings(self.config_path)
        if action == "install":
            path = install_schedule(self.config_path, settings)
            return {"message": f"Installed schedule at {path}", "status": schedule_status(self.config_path, settings)}
        if action == "uninstall":
            path = uninstall_schedule()
            return {"message": f"Uninstalled schedule at {path}", "status": schedule_status(self.config_path, settings)}
        if action == "status":
            return {"message": "Schedule status loaded.", "status": schedule_status(self.config_path, settings)}
        raise RuntimeError(f"unknown schedule action: {action}")

    def _sync_private_config(self, repo_path: str) -> dict:
        repo = Path(repo_path or os.environ.get("PAPERWATCH_PRIVATE_REPO", "/private/tmp/paperwatch-private")).expanduser()
        if not (repo / ".git").exists():
            raise RuntimeError(f"Private repository path is not a git checkout: {repo}")
        content = self.config_path.read_text(encoding="utf-8")
        content = re.sub(r'api_key = "[^"]*"', 'api_key = ""', content)
        content = re.sub(r'webhook_url = "[^"]*"', 'webhook_url = ""', content)
        content = re.sub(r'secret = "[^"]*"', 'secret = ""', content)
        target = repo / "config.toml"
        target.write_text(content, encoding="utf-8")

        self._run_git(repo, ["add", "config.toml"])
        diff = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet"], capture_output=True, text=True, timeout=30)
        if diff.returncode == 0:
            return {"message": "No config changes to sync."}
        if diff.returncode != 1:
            raise RuntimeError((diff.stdout + diff.stderr).strip() or "git diff failed")
        self._run_git(repo, ["commit", "-m", "Update private PaperWatch config"])
        self._run_git(repo, ["push"])
        return {"message": "Private config synced and pushed."}

    def _run_git(self, repo: Path, args: list[str]) -> None:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError((result.stdout + result.stderr).strip() or f"git {' '.join(args)} failed")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def _send_json(self, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def load_settings_from_text(content: str) -> None:
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".toml", encoding="utf-8", delete=True) as tmp:
        tmp.write(content)
        tmp.flush()
        load_settings(tmp.name)


def _create_interest_job() -> str:
    job_id = uuid.uuid4().hex
    with _INTEREST_JOBS_LOCK:
        _INTEREST_JOBS[job_id] = {
            "ok": True,
            "done": False,
            "step": "Queued.",
            "toml": "",
            "error": "",
        }
    return job_id


def _set_interest_job(job_id: str, **updates: object) -> None:
    with _INTEREST_JOBS_LOCK:
        job = _INTEREST_JOBS.setdefault(job_id, {"ok": True, "done": False, "step": ""})
        job.update(updates)


def _get_interest_job(job_id: str) -> dict[str, object]:
    with _INTEREST_JOBS_LOCK:
        job = dict(_INTEREST_JOBS.get(job_id, {}))
    if not job:
        return {"ok": False, "done": True, "error": "Unknown interest generation job"}
    return job


def _create_run_job() -> str:
    job_id = uuid.uuid4().hex
    with _RUN_JOBS_LOCK:
        _RUN_JOBS[job_id] = {
            "ok": True,
            "done": False,
            "step": "Queued.",
            "error": "",
            "output": "",
            "started_at": time.time(),
        }
    return job_id


def _set_run_job(job_id: str, **updates: object) -> None:
    with _RUN_JOBS_LOCK:
        job = _RUN_JOBS.setdefault(job_id, {"ok": True, "done": False, "step": ""})
        job.update(updates)


def _get_run_job(job_id: str) -> dict[str, object]:
    with _RUN_JOBS_LOCK:
        job = dict(_RUN_JOBS.get(job_id, {}))
    if not job:
        return {"ok": False, "done": True, "error": "Unknown fetch job"}
    if not job.get("done") and job.get("started_at"):
        elapsed = int(time.time() - float(job["started_at"]))
        job["elapsed_seconds"] = elapsed
        job["step"] = f"{job.get('step', 'Running...')} ({elapsed}s)"
    return job


def _run_fetch_job(job_id: str, args: argparse.Namespace) -> None:
    from paperwatch.main import _run

    out = io.StringIO()
    err = io.StringIO()
    try:
        _set_run_job(job_id, step="Fetching papers, ranking, rendering digest...")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = _run(args)
        output = (out.getvalue() + err.getvalue()).strip()
        if code == 0:
            _set_run_job(job_id, ok=True, done=True, step="Completed. Refreshing digests...", output=output)
        else:
            _set_run_job(job_id, ok=False, done=True, step="Failed.", error=output or f"run exited with code {code}")
    except Exception as exc:
        output = (out.getvalue() + err.getvalue()).strip()
        _set_run_job(job_id, ok=False, done=True, step="Failed.", error=str(exc), output=output)


def _run_interest_generation_job(job_id: str, config_path: Path, paper_text: str) -> None:
    from paperwatch.ai import generate_interest_from_paper

    def progress(step: str) -> None:
        _set_interest_job(job_id, step=step)

    try:
        progress("Loading Interest Builder API settings...")
        settings = load_settings(config_path)
        prompt_text = _resolve_interest_builder_input(paper_text, progress=progress)
        progress("Calling Interest Builder API...")
        toml = generate_interest_from_paper(prompt_text, settings.interest_ai)
        _set_interest_job(job_id, ok=True, done=True, step="Generated. Review it, then append to config.", toml=toml)
    except Exception as exc:
        _set_interest_job(job_id, ok=False, done=True, step="Failed.", error=str(exc))


def _resolve_interest_builder_input(paper_text: str, progress=None) -> str:
    text = paper_text.strip()
    if not text:
        return paper_text

    arxiv_ids = _extract_arxiv_ids(text)
    if not arxiv_ids:
        return paper_text
    if len(arxiv_ids) > MAX_INTEREST_SOURCE_PAPERS:
        raise RuntimeError(f"Paste at most {MAX_INTEREST_SOURCE_PAPERS} arXiv links at once")

    sections = ["Infer one reusable monitoring interest from these arXiv papers as a set."]
    if _strip_arxiv_refs(text):
        sections.extend(["", "User notes:", _strip_arxiv_refs(text)])
    for index, arxiv_id in enumerate(arxiv_ids, start=1):
        if progress:
            progress(f"Fetching arXiv metadata {index}/{len(arxiv_ids)}: {arxiv_id}")
        record = _fetch_arxiv_record(arxiv_id)
        if progress:
            progress(f"Downloading and extracting PDF text {index}/{len(arxiv_ids)}: {record['title']}")
        try:
            full_text = _extract_arxiv_pdf_text(record["pdf_url"], record["title"])
        except RuntimeError as exc:
            full_text = f"Full text unavailable: {exc}\n\nUsing title and abstract metadata only."
        full_text = _truncate_source_text(full_text, MAX_INTEREST_SOURCE_CHARS_PER_PAPER)
        sections.extend(["", _format_arxiv_paper_section(index, record, full_text)])
    return "\n".join(sections)


def _extract_arxiv_id(text: str) -> str | None:
    ids = _extract_arxiv_ids(text)
    return ids[0] if ids else None


def _extract_arxiv_ids(text: str) -> list[str]:
    candidate = text.strip()
    ids: list[str] = []
    for match in ARXIV_ABS_URL_RE.finditer(candidate):
        ids.append(unquote(match.group(1)).rstrip("/"))

    text_without_urls = ARXIV_ABS_URL_RE.sub(" ", candidate)
    for chunk in re.split(r"[\s,;]+", text_without_urls):
        value = chunk.strip().strip("()[]{}<>")
        if value.lower().startswith("arxiv:"):
            value = value.split(":", 1)[1].strip()
        match = ARXIV_ID_RE.fullmatch(value)
        if match:
            ids.append(match.group(1).rstrip("/"))

    result: list[str] = []
    seen = set()
    for arxiv_id in ids:
        key = arxiv_id.lower()
        if key not in seen:
            seen.add(key)
            result.append(arxiv_id)
    return result


def _strip_arxiv_refs(text: str) -> str:
    text = ARXIV_ABS_URL_RE.sub(" ", text)
    text = re.sub(r"\barxiv:\s*(?:\d{4}\.\d{4,5}|[a-z\-]+/\d{7})(?:v\d+)?", " ", text, flags=re.IGNORECASE)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()


def _format_arxiv_paper_section(index: int, record: dict[str, object], full_text: str) -> str:
    lines = [
        f"Paper {index}",
        f"arXiv ID: {record['paper_id']}",
        f"Title: {record['title']}",
    ]
    if record["authors"]:
        lines.append(f"Authors: {', '.join(record['authors'])}")
    if record["categories"]:
        lines.append(f"Categories: {', '.join(record['categories'])}")
    if record.get("published_at"):
        lines.append(f"Published: {record['published_at']}")
    if record.get("abstract"):
        lines.extend(["", "Abstract:", str(record["abstract"])])
    lines.extend(["", "Full text extracted from PDF:", full_text])
    return "\n".join(lines)


def _fetch_arxiv_record(arxiv_id: str) -> dict[str, object]:
    params = {"id_list": arxiv_id}
    url = f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "paperwatch/0.1 (interest builder)"})
    try:
        payload = _open_with_retries(request, 30, "arXiv metadata")
    except RuntimeError as exc:
        if "HTTP 429" not in str(exc):
            raise
        return _fetch_arxiv_record_from_abs_page(arxiv_id)

    root = ET.fromstring(payload)
    entry = root.find("atom:entry", ATOM_NS)
    if entry is None:
        raise RuntimeError(f"No arXiv record found for {arxiv_id}")

    pdf_url = ""
    for link in entry.findall("atom:link", ATOM_NS):
        if link.attrib.get("title") == "pdf":
            pdf_url = link.attrib.get("href", "")
            break

    return {
        "paper_id": _short_arxiv_id(_text(entry, "atom:id")),
        "title": _clean_text(_text(entry, "atom:title")),
        "abstract": _clean_text(_text(entry, "atom:summary")),
        "authors": [
            _clean_text(author.findtext("atom:name", default="", namespaces=ATOM_NS))
            for author in entry.findall("atom:author", ATOM_NS)
        ],
        "categories": [
            item.attrib.get("term", "")
            for item in entry.findall("atom:category", ATOM_NS)
            if item.attrib.get("term")
        ],
        "published_at": _text(entry, "atom:published"),
        "pdf_url": pdf_url or f"https://arxiv.org/pdf/{arxiv_id}.pdf",
    }


def _fetch_arxiv_record_from_abs_page(arxiv_id: str) -> dict[str, object]:
    url = f"https://arxiv.org/abs/{urllib.parse.quote(arxiv_id)}"
    request = urllib.request.Request(url, headers={"User-Agent": "paperwatch/0.1 (interest builder fallback)"})
    payload = _open_with_retries(request, 30, "arXiv abstract page")
    page = payload.decode("utf-8", errors="replace")

    title = _html_meta(page, "citation_title") or _html_block(page, r"<h1 class=\"title mathjax\">.*?</span>(.*?)</h1>")
    abstract = _html_block(page, r"<blockquote class=\"abstract mathjax\">.*?</span>(.*?)</blockquote>")
    authors = _html_meta_all(page, "citation_author") or _html_authors(page)
    categories = _html_categories(page)
    published_at = _html_meta(page, "citation_date") or ""
    pdf_url = _html_meta(page, "citation_pdf_url") or f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    if not title:
        raise RuntimeError(
            "Failed to fetch arXiv metadata: HTTP 429 from export API and fallback abstract page did not contain metadata"
        )

    return {
        "paper_id": _short_arxiv_id(arxiv_id),
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "categories": categories,
        "published_at": published_at,
        "pdf_url": pdf_url,
    }


def _extract_arxiv_pdf_text(pdf_url: str, title: str) -> str:
    tool = _find_pdftotext()
    if not tool:
        raise RuntimeError("pdftotext is not installed; cannot extract full text from arXiv PDF")

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "paper.pdf"
        txt_path = Path(tmpdir) / "paper.txt"
        request = urllib.request.Request(pdf_url, headers={"User-Agent": "paperwatch/0.1 (interest builder)"})
        try:
            pdf_path.write_bytes(_open_with_retries(request, 60, "arXiv PDF"))
        except RuntimeError as exc:
            raise RuntimeError(f"Failed to download arXiv PDF: {exc}") from exc

        result = subprocess.run(
            [tool, "-layout", "-nopgbrk", str(pdf_path), str(txt_path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise RuntimeError(f"pdftotext failed for {title!r}: {stderr}")
        if not txt_path.exists():
            raise RuntimeError(f"pdftotext did not produce extracted text for {title!r}")

        text = txt_path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            raise RuntimeError(f"Extracted arXiv PDF text was empty for {title!r}")
        return _collapse_whitespace(text)


def _open_with_retries(request: urllib.request.Request, timeout_seconds: int, label: str) -> bytes:
    for attempt in range(len(ARXIV_RETRY_WAITS) + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in ARXIV_RETRY_HTTP_CODES or attempt == len(ARXIV_RETRY_WAITS):
                raise RuntimeError(f"HTTP {exc.code}: {exc.reason}") from exc
            retry_after = exc.headers.get("Retry-After")
            wait_seconds = int(retry_after) if retry_after and retry_after.isdigit() else ARXIV_RETRY_WAITS[attempt]
            time.sleep(wait_seconds)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == len(ARXIV_RETRY_WAITS):
                reason = getattr(exc, "reason", exc)
                raise RuntimeError(f"{label} request failed: {reason}") from exc
            time.sleep(ARXIV_RETRY_WAITS[attempt])
    raise RuntimeError(f"{label} request failed after retries")


def _html_meta(page: str, name: str) -> str:
    pattern = rf'<meta\s+name=["\']{re.escape(name)}["\']\s+content=["\'](.*?)["\']\s*/?>'
    match = re.search(pattern, page, re.IGNORECASE | re.DOTALL)
    return _clean_html(match.group(1)) if match else ""


def _html_meta_all(page: str, name: str) -> list[str]:
    pattern = rf'<meta\s+name=["\']{re.escape(name)}["\']\s+content=["\'](.*?)["\']\s*/?>'
    return [_clean_html(match) for match in re.findall(pattern, page, re.IGNORECASE | re.DOTALL)]


def _html_block(page: str, pattern: str) -> str:
    match = re.search(pattern, page, re.IGNORECASE | re.DOTALL)
    return _clean_html(match.group(1)) if match else ""


def _html_authors(page: str) -> list[str]:
    block = _html_block(page, r"<div class=\"authors\">(.*?)</div>")
    if not block:
        return []
    return [part.strip() for part in block.replace("Authors:", "").split(",") if part.strip()]


def _html_categories(page: str) -> list[str]:
    subjects = _html_block(page, r"<td class=\"tablecell subjects\">(.*?)</td>")
    return re.findall(r"\(([^()]+)\)", subjects)


def _clean_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split())


def _find_pdftotext() -> str | None:
    found = shutil.which("pdftotext")
    if found:
        return found
    for path in ["/opt/homebrew/bin/pdftotext", "/usr/local/bin/pdftotext"]:
        if Path(path).exists():
            return path
    return None


def _collapse_whitespace(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def _truncate_source_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n[Truncated for prompt budget.]"


def _text(entry: ET.Element, path: str) -> str:
    return entry.findtext(path, default="", namespaces=ATOM_NS).strip()


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _short_arxiv_id(entry_id: str) -> str:
    tail = entry_id.rstrip("/").split("/")[-1]
    return tail.split("v")[0]


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PaperWatch</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    html, body { height: 100%; }
    body { margin: 0; background: #f6f7f9; color: #1f2933; overflow: hidden; }
    header { padding: 16px 24px; background: #16324f; color: white; display: flex; align-items: center; justify-content: space-between; }
    main { display: grid; grid-template-columns: 360px 1fr; gap: 18px; padding: 18px; height: calc(100vh - 72px); box-sizing: border-box; }
    aside, section { background: white; border: 1px solid #d8dee6; border-radius: 8px; padding: 14px; overflow: auto; min-height: 0; }
    button, select, input { font: inherit; }
    button { border: 1px solid #9aa8b6; background: #fff; border-radius: 6px; padding: 7px 10px; cursor: pointer; }
    button.primary { background: #2364aa; color: white; border-color: #2364aa; }
    button.danger { border-color: #b42318; color: #b42318; }
    button.subtle { background: #f8fafc; }
    textarea { width: 100%; min-height: 520px; box-sizing: border-box; font: 13px ui-monospace, SFMono-Regular, Menlo, monospace; border: 1px solid #c8d0d9; border-radius: 6px; padding: 10px; }
    .tabs { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
    .tab { background: #eef2f6; }
    .tab.active { background: #2364aa; color: white; border-color: #2364aa; }
    .row { display: flex; gap: 8px; margin: 8px 0; align-items: center; flex-wrap: wrap; }
    .field { display: grid; gap: 4px; margin: 10px 0; }
    .field label { font-size: 13px; color: #425466; }
    .field input, .field select { width: 100%; box-sizing: border-box; border: 1px solid #c8d0d9; border-radius: 6px; padding: 7px 8px; }
    .check-list { border: 1px solid #c8d0d9; border-radius: 6px; padding: 6px; max-height: 180px; overflow: auto; background: #fff; }
    .check-row { display: grid; grid-template-columns: 22px 1fr; gap: 6px; align-items: start; padding: 5px 4px; border-radius: 4px; }
    .check-row:hover { background: #f8fafc; }
    .check-row input { width: auto; margin-top: 2px; }
    .panel { border: 1px solid rgba(100,116,139,.18); border-radius: 8px; padding: 12px; margin-top: 12px; background: rgba(248,250,252,.72); }
    .toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 10px; }
    .form-grid { display: grid; grid-template-columns: repeat(2, minmax(220px, 1fr)); gap: 10px 14px; margin-bottom: 14px; }
    .config-nav { display: grid; gap: 6px; margin-top: 12px; }
    .config-nav button { text-align: left; background: #f8fafc; border-color: #d8dee6; color: #334155; }
    .config-nav button.active { background: #e8f1fb; border-color: #77a8d8; color: #16324f; font-weight: 700; }
    .form-block { border: 1px solid #d8dee6; border-radius: 8px; padding: 16px; margin-bottom: 16px; scroll-margin-top: 12px; }
    .form-block:nth-of-type(1) { background: #f8fbff; }
    .form-block:nth-of-type(2) { background: #f8fcfa; }
    .form-block:nth-of-type(3) { background: #fffaf3; }
    .form-block:nth-of-type(4) { background: #fbf9ff; }
    .form-block:nth-of-type(5) { background: #fff9fb; }
    .form-block:nth-of-type(6) { background: #f8fcff; }
    .form-block:nth-of-type(7) { background: #f9fbf4; }
    .form-block > h3 { margin: 0 0 4px; font-size: 19px; color: #16324f; }
    .module-help { margin: 0 0 12px; color: #64748b; font-size: 13px; }
    .panel h3 { margin: 0 0 8px; font-size: 14px; color: #425466; text-transform: uppercase; letter-spacing: .02em; }
    .digest-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; align-items: start; margin-bottom: 6px; }
    .list button { width: 100%; text-align: left; margin-bottom: 6px; overflow-wrap: anywhere; }
    .digest-row button { margin-bottom: 0; }
    .markdown-preview { background: #f8fafc; border: 1px solid #d8dee6; border-radius: 6px; padding: 12px 18px; max-height: 620px; overflow: auto; line-height: 1.5; }
    .markdown-preview h1, .markdown-preview h2, .markdown-preview h3 { color: #16324f; margin: 14px 0 8px; }
    .markdown-preview h1 { font-size: 24px; }
    .markdown-preview h2 { font-size: 19px; border-bottom: 1px solid #d8dee6; padding-bottom: 4px; }
    .markdown-preview h3 { font-size: 16px; }
    .markdown-preview p { margin: 8px 0; }
    .markdown-preview ul, .markdown-preview ol { margin: 8px 0 8px 24px; padding: 0; }
    .markdown-preview li { margin: 4px 0; }
    .markdown-preview code { background: #eef2f6; border-radius: 4px; padding: 1px 4px; }
    .markdown-preview a { color: #2364aa; }
    article { border-top: 1px solid #e1e6ec; padding: 12px 0; }
    article h3 { margin: 0 0 6px; font-size: 16px; }
    .muted { color: #64748b; font-size: 13px; }
    .status { min-height: 20px; color: #355070; }
    @media (max-width: 850px) { body { overflow: auto; } main { grid-template-columns: 1fr; height: auto; } textarea { min-height: 360px; } }
  </style>
</head>
<body>
  <header>
    <strong>PaperWatch</strong>
    <span class="muted" style="color:#d7e2ed">Local research digest control panel</span>
  </header>
  <main>
    <aside>
      <div class="tabs">
        <button class="tab active" onclick="showTab('digests', this)">Digests</button>
        <button class="tab" onclick="showTab('config', this)">Config</button>
      </div>
      <div id="side-digests">
        <div class="panel" style="border-top:0;margin-top:0;padding-top:0">
          <h3>Manual Fetch</h3>
          <div class="field">
            <label>Mode</label>
            <select id="run-mode" onchange="syncRunMode()">
              <option value="days">Last N complete days</option>
              <option value="range">Date range</option>
            </select>
          </div>
          <div class="field" id="run-days-wrap">
            <label>Complete days ending yesterday</label>
            <input id="run-days" type="number" value="1" min="1">
          </div>
          <div id="run-range-wrap" hidden>
            <div class="field"><label>Start date</label><input id="run-start-date" type="date"></div>
            <div class="field"><label>End date</label><input id="run-end-date" type="date"></div>
          </div>
          <div class="field">
            <label>Interest</label>
            <select id="run-interest"><option value="">Config default</option><option value="none">None / all arXiv papers</option></select>
          </div>
          <div class="field">
            <label>Ranking mode</label>
            <select id="run-ranking-mode">
              <option value="">Config default</option>
              <option value="keyword">Keyword ranking</option>
              <option value="embedding">Embedding rerank</option>
              <option value="ai">Keyword ranking + digest AI</option>
              <option value="embedding_ai">Embedding rerank + digest AI</option>
            </select>
          </div>
          <div class="field">
            <label>Maximum papers (blank = unlimited)</label>
            <input id="run-limit" type="number" min="1" placeholder="unlimited">
          </div>
          <div class="row">
            <button class="primary" onclick="runNow()">Run fetch</button>
            <button class="subtle" onclick="loadDigests()">Refresh</button>
          </div>
        </div>
        <p class="status" id="run-status"></p>
        <div class="panel"><h3>Digests</h3></div>
        <div class="list" id="digest-list"></div>
      </div>
      <div id="side-config" hidden>
        <h3>Configuration</h3>
        <button class="primary" onclick="saveConfig()">Save config</button>
        <p class="status" id="config-status"></p>
        <div class="config-nav">
          <button data-target="cfg-auto" onclick="scrollConfigModule('cfg-auto')">Automatic Fetch</button>
          <button data-target="cfg-schedule" onclick="scrollConfigModule('cfg-schedule')">Schedule</button>
          <button data-target="cfg-github" onclick="scrollConfigModule('cfg-github')">GitHub Actions</button>
          <button data-target="cfg-feishu" onclick="scrollConfigModule('cfg-feishu')">Feishu</button>
          <button data-target="cfg-sources" onclick="scrollConfigModule('cfg-sources')">Sources</button>
          <button data-target="cfg-interests" onclick="scrollConfigModule('cfg-interests')">Interests</button>
          <button data-target="cfg-ranking" onclick="scrollConfigModule('cfg-ranking')">Ranking</button>
          <button data-target="cfg-translation" onclick="scrollConfigModule('cfg-translation')">Translation</button>
        </div>
      </div>
    </aside>
    <section>
      <div id="view-digests">
        <div class="toolbar">
          <strong id="digest-title">Select a digest</strong>
          <span class="row" style="margin:0">
            <button class="subtle" id="digest-send-button" onclick="sendCurrentDigestFeishu()" disabled>Send Feishu</button>
            <button class="danger" id="digest-delete-button" onclick="deleteCurrentDigest()" disabled>Delete</button>
          </span>
        </div>
        <div id="digest-content" class="markdown-preview">Select a digest.</div>
      </div>
      <div id="view-config" hidden>
        <div class="toolbar">
          <strong>Configuration</strong>
          <label class="row" style="margin:0"><input id="config-raw-toggle" type="checkbox" onchange="showConfigMode(this.checked ? 'raw' : 'form')"> Raw</label>
        </div>
        <div id="config-form">
          <div class="form-block" id="cfg-auto">
            <h3>Automatic Fetch</h3>
            <p class="module-help">Choose which interests run on the daily schedule and how many ranked papers each report keeps.</p>
            <div class="form-grid">
              <div class="field"><label>Daily per-interest limit (blank or 0 = unlimited)</label><input id="cfg-per-interest-limit" type="number" min="0" placeholder="unlimited"></div>
              <div class="field"><label>Daily fetch interests</label><div id="cfg-default-fetch-interests" class="check-list"></div></div>
            </div>
          </div>
          <div class="form-block" id="cfg-schedule">
            <h3>Schedule</h3>
            <p class="module-help">macOS-only local launchd schedule. For Windows, Linux, or always-on runs, use GitHub Actions below.</p>
            <div class="form-grid">
              <div class="field"><label>Enable scheduled fetch</label><select id="cfg-schedule-enabled"><option value="true">true</option><option value="false">false</option></select></div>
              <div class="field"><label>Fetch days per run</label><input id="cfg-schedule-days" type="number" min="1"></div>
              <div class="field"><label>Hour (0-23)</label><input id="cfg-schedule-hour" type="number" min="0" max="23"></div>
              <div class="field"><label>Minute (0-59)</label><input id="cfg-schedule-minute" type="number" min="0" max="59"></div>
            </div>
            <div class="row">
              <button class="primary" onclick="scheduleAction('install')">Install on this PC</button>
              <button class="subtle" onclick="scheduleAction('status')">Status</button>
              <button class="danger" onclick="scheduleAction('uninstall')">Uninstall</button>
              <span class="muted" id="schedule-status"></span>
            </div>
          </div>
          <div class="form-block" id="cfg-github">
            <h3>GitHub Actions</h3>
            <p class="module-help">Sync the current config to a private repository. Credentials are stripped; update API keys and Feishu values in GitHub Secrets.</p>
            <div class="form-grid">
              <div class="field"><label>Private repo path</label><input id="cfg-private-repo-path" value="/private/tmp/paperwatch-private"></div>
              <div class="field"><label>Current workflow time</label><input value="12:30 Asia/Shanghai / 04:30 UTC / cron 30 4 * * *" disabled></div>
            </div>
            <div class="row">
              <button class="primary" onclick="syncPrivateConfig()">Sync config to private repo</button>
              <span class="muted" id="private-sync-status"></span>
            </div>
          </div>
          <div class="form-block" id="cfg-feishu">
            <h3>Feishu</h3>
            <p class="module-help">Configure the custom-bot webhook used by scheduled notifications and manual digest sending.</p>
            <div class="form-grid">
              <div class="field"><label>Enable Feishu sending</label><select id="cfg-feishu-enabled"><option value="true">true</option><option value="false">false</option></select></div>
              <div class="field"><label>Send scheduled fetch result</label><select id="cfg-feishu-send-schedule"><option value="true">true</option><option value="false">false</option></select></div>
              <div class="field"><label>Webhook URL</label><input id="cfg-feishu-webhook"></div>
              <div class="field"><label>Signature secret</label><input id="cfg-feishu-secret" type="password"></div>
            </div>
          </div>
          <div class="form-block" id="cfg-sources">
            <h3>Sources</h3>
            <p class="module-help">Enable paper metadata providers and test whether each source is reachable from this machine.</p>
            <div class="form-grid">
              <div class="field"><label>Enabled sources</label><div id="cfg-enabled-sources" class="check-list"></div></div>
              <div class="field"><label>Max results per interest</label><input id="cfg-arxiv-max" type="number" min="1"></div>
              <div class="field"><label>OpenAlex max results per interest</label><input id="cfg-openalex-max" type="number" min="1"></div>
              <div class="field"><label>OpenAlex mailto (optional)</label><input id="cfg-openalex-mailto"></div>
              <div class="field"><label>dblp max results per interest</label><input id="cfg-dblp-max" type="number" min="1"></div>
            </div>
            <div class="row">
              <button class="subtle" onclick="testSource('arxiv')">Test arXiv</button>
              <button class="subtle" onclick="testSource('openalex')">Test OpenAlex</button>
              <button class="subtle" onclick="testSource('dblp')">Test dblp</button>
              <span class="muted" id="source-test-status"></span>
            </div>
          </div>
          <div class="form-block" id="cfg-interests">
            <h3>Interests</h3>
            <p class="module-help">Create, edit, delete, or generate reusable monitoring directions from seed papers.</p>
            <div class="form-grid">
              <div class="field"><label>Interest</label><select id="interest-edit-select" size="7" onchange="loadSelectedInterest()"></select></div>
              <div>
                <div class="field"><label>Name</label><input id="interest-edit-name"></div>
                <div class="field"><label>Description</label><input id="interest-edit-description"></div>
                <div class="field"><label>arXiv categories (comma separated)</label><input id="interest-edit-categories"></div>
              </div>
            </div>
            <div class="field"><label>Keywords (one per line: keyword | weight)</label><textarea id="interest-edit-keywords" style="min-height:120px"></textarea></div>
            <div class="field"><label>Negative keywords (one per line)</label><textarea id="interest-edit-negative" style="min-height:80px"></textarea></div>
            <div class="field"><label>Seed papers (one per line)</label><textarea id="interest-edit-seeds" style="min-height:70px"></textarea></div>
            <div class="row">
              <button class="subtle" onclick="addBlankInterest()">New interest</button>
              <button class="primary" onclick="saveSelectedInterest()">Save interest edit</button>
              <button class="danger" onclick="deleteSelectedInterest()">Delete selected interest</button>
            </div>
            <p class="status" id="interest-edit-status"></p>
            <div class="panel">
              <h3>Build Interest From Paper</h3>
              <div class="field"><label>Paper links / title / abstract / notes</label><textarea id="interest-paper-text" style="min-height:140px"></textarea></div>
              <div class="row">
                <button class="subtle" id="generate-interest-button" onclick="generateInterest()">Generate interest block</button>
                <button class="primary" onclick="appendGeneratedInterest()">Append to config</button>
              </div>
              <p class="status" id="interest-generate-status"></p>
              <textarea id="generated-interest" style="min-height:150px"></textarea>
            </div>
            <div class="panel">
              <h3>Interest Builder API</h3>
              <div class="form-grid">
                <div class="field"><label>Base URL</label><input id="cfg-interest-ai-base"></div>
                <div class="field"><label>Model</label><input id="cfg-interest-ai-model"></div>
                <div class="field"><label>API key env name</label><input id="cfg-interest-ai-key-env"></div>
                <div class="field"><label>API key</label><input id="cfg-interest-ai-key" type="password"></div>
              </div>
              <div class="row"><button class="subtle" onclick="testAI('interest_ai')">Test Interest Builder API</button><span class="muted" id="interest-ai-test-status"></span></div>
            </div>
          </div>
          <div class="form-block" id="cfg-ranking">
            <h3>Ranking</h3>
            <p class="module-help">Control relevance ranking and optional digest-level AI summaries.</p>
            <div class="form-grid">
              <div class="field"><label>Ranking mode</label><select id="cfg-ranking-mode"><option value="keyword">Keyword ranking</option><option value="embedding">Embedding rerank</option><option value="ai">Keyword ranking + digest AI</option><option value="embedding_ai">Embedding rerank + digest AI</option></select></div>
            </div>
            <div class="panel">
              <h3>Ranking Embedding API</h3>
              <div class="form-grid">
                <div class="field"><label>Base URL</label><input id="cfg-embedding-base"></div>
                <div class="field"><label>Model</label><input id="cfg-embedding-model"></div>
                <div class="field"><label>API key env name</label><input id="cfg-embedding-key-env"></div>
                <div class="field"><label>API key</label><input id="cfg-embedding-key" type="password"></div>
              </div>
              <div class="row"><button class="subtle" onclick="testEmbedding()">Test Ranking Embedding API</button><span class="muted" id="embedding-test-status"></span></div>
            </div>
            <div class="panel">
              <h3>Digest AI API</h3>
              <div class="form-grid">
                <div class="field"><label>Base URL</label><input id="cfg-digest-ai-base"></div>
                <div class="field"><label>Model</label><input id="cfg-digest-ai-model"></div>
                <div class="field"><label>API key env name</label><input id="cfg-digest-ai-key-env"></div>
                <div class="field"><label>API key</label><input id="cfg-digest-ai-key" type="password"></div>
              </div>
              <div class="row"><button class="subtle" onclick="testAI('digest_ai')">Test Digest AI API</button><span class="muted" id="digest-ai-test-status"></span></div>
            </div>
          </div>
          <div class="form-block" id="cfg-translation">
            <h3>Translation</h3>
            <p class="module-help">Configure Chinese title and abstract translation for generated digests.</p>
            <div class="form-grid">
              <div class="field"><label>Enabled</label><select id="cfg-translation-enabled"><option value="true">true</option><option value="false">false</option></select></div>
              <div class="field"><label>Language</label><input id="cfg-translation-language"></div>
            </div>
            <div class="panel">
              <h3>Translation API</h3>
              <div class="form-grid">
                <div class="field"><label>Base URL</label><input id="cfg-ai-base"></div>
                <div class="field"><label>Model</label><input id="cfg-ai-model"></div>
                <div class="field"><label>API key env name</label><input id="cfg-ai-key-env"></div>
                <div class="field"><label>API key</label><input id="cfg-ai-key" type="password"></div>
              </div>
              <div class="row"><button class="subtle" onclick="testAI('ai')">Test Translation API</button><span class="muted" id="ai-test-status"></span></div>
            </div>
          </div>
        </div>
        <textarea id="config-editor" hidden></textarea>
      </div>
    </section>
  </main>
  <script>
    let currentDigest = '';
    let configMode = 'form';
    async function getJson(url) { const r = await fetch(url); return await r.json(); }
    async function postJson(url, body) {
      const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
      return await r.json();
    }
    function showTab(name, el) {
      document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
      el.classList.add('active');
      for (const id of ['digests','config']) {
        document.getElementById('side-' + id).hidden = id !== name;
        document.getElementById('view-' + id).hidden = id !== name;
      }
      if (name === 'config') setTimeout(updateConfigNavActive, 50);
    }
    async function loadConfig() {
      const data = await getJson('/api/config');
      const content = data.content;
      document.getElementById('config-editor').value = content;
      const interests = listInterestNames(content);
      const defaultFetch = readTomlArray(section(content, 'sources.arxiv'), 'default_fetch_interests', interests);
      populateRunInterestSelect(interests);
      populateDefaultFetchChecks(interests, defaultFetch);
      populateInterestEditor(content);
      populateConfigForm(content);
    }
    async function saveConfig() {
      const status = document.getElementById('config-status');
      status.textContent = 'Saving...';
      try {
        if (configMode === 'form') applyConfigForm();
        await postJson('/api/config', {content: document.getElementById('config-editor').value});
        status.textContent = 'Saved.';
        await loadConfig();
      } catch (e) { status.textContent = 'Save failed: ' + e; }
    }
    async function syncPrivateConfig() {
      if (configMode === 'form') applyConfigForm();
      const status = document.getElementById('private-sync-status');
      status.textContent = 'Saving and syncing...';
      try {
        await postJson('/api/config', {content: document.getElementById('config-editor').value});
        const data = await postJson('/api/sync-private-config', {
          repo_path: document.getElementById('cfg-private-repo-path').value
        });
        if (!data.ok) {
          status.textContent = 'Failed: ' + (data.error || 'unknown error');
          return;
        }
        status.textContent = data.message || 'Synced.';
      } catch (e) {
        status.textContent = 'Failed: ' + e;
      }
    }
    async function loadDigests() {
      const data = await getJson('/api/digests');
      const list = document.getElementById('digest-list');
      list.innerHTML = data.digests.map(name => `<div class="digest-row"><button onclick="openDigest('${name}')">${name}</button></div>`).join('') || '<p class="muted">No digests yet.</p>';
    }
    async function openDigest(name) {
      const data = await getJson('/api/digest?name=' + encodeURIComponent(name));
      currentDigest = name;
      document.getElementById('digest-title').textContent = name;
      renderDigest(data.content || 'Empty digest.');
      document.getElementById('digest-send-button').disabled = false;
      document.getElementById('digest-delete-button').disabled = false;
    }
    async function runNow() {
      const status = document.getElementById('run-status');
      status.textContent = 'Started...';
      const mode = document.getElementById('run-mode').value;
      const body = {};
      if (mode === 'range') {
        body.start_date = document.getElementById('run-start-date').value;
        body.end_date = document.getElementById('run-end-date').value;
        if (!body.start_date || !body.end_date) {
          status.textContent = 'Choose both start and end date.';
          return;
        }
      } else {
        body.days = Number(document.getElementById('run-days').value || 1);
      }
      body.interest = document.getElementById('run-interest').value;
      body.ranking_mode = document.getElementById('run-ranking-mode').value;
      const limit = document.getElementById('run-limit').value;
      if (limit) body.limit = Number(limit);
      const data = await postJson('/api/run', body);
      if (!data.ok) {
        status.textContent = 'Failed to start: ' + (data.error || 'unknown error');
        return;
      }
      status.textContent = data.message || 'Started.';
      await pollRunStatus(data.job_id);
    }
    async function pollRunStatus(jobId) {
      const status = document.getElementById('run-status');
      while (true) {
        await sleep(2000);
        const data = await getJson('/api/run-status?job_id=' + encodeURIComponent(jobId));
        if (!data.done) {
          status.textContent = data.step || 'Running...';
          continue;
        }
        if (data.ok) {
          status.textContent = 'Completed. Digests refreshed.';
          await loadDigests();
        } else {
          status.textContent = 'Failed: ' + (data.error || data.output || 'unknown error');
        }
        return;
      }
    }
    async function deleteDigest(name) {
      if (!confirm('Delete ' + name + '?')) return;
      await postJson('/api/delete-digest', {name});
      if (currentDigest === name) {
        currentDigest = '';
        document.getElementById('digest-title').textContent = 'Select a digest';
        renderDigest('Deleted ' + name);
        document.getElementById('digest-send-button').disabled = true;
        document.getElementById('digest-delete-button').disabled = true;
      }
      await loadDigests();
    }
    async function deleteCurrentDigest() {
      if (!currentDigest) return;
      await deleteDigest(currentDigest);
    }
    async function sendCurrentDigestFeishu() {
      if (!currentDigest) return;
      await sendDigestFeishu(currentDigest);
    }
    async function sendDigestFeishu(name) {
      const data = await postJson('/api/send-digest-feishu', {name});
      document.getElementById('run-status').textContent = data.ok ? `Sent ${name} to Feishu.` : `Feishu send failed: ${data.error || data.message}`;
    }
    function renderDigest(markdown) {
      document.getElementById('digest-content').innerHTML = markdownToHtml(markdown);
    }
    function markdownToHtml(markdown) {
      const lines = String(markdown || '').split(/\r?\n/);
      const output = [];
      let list = null;
      let paragraph = [];
      const flushParagraph = () => {
        if (!paragraph.length) return;
        output.push('<p>' + inlineMarkdown(paragraph.join(' ')) + '</p>');
        paragraph = [];
      };
      const closeList = () => {
        if (!list) return;
        output.push(`</${list}>`);
        list = null;
      };
      for (const raw of lines) {
        const line = raw.trim();
        if (!line) {
          flushParagraph();
          closeList();
          continue;
        }
        const heading = line.match(/^(#{1,3})\s+(.+)$/);
        if (heading) {
          flushParagraph();
          closeList();
          const level = heading[1].length;
          output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
          continue;
        }
        const bullet = line.match(/^[-*]\s+(.+)$/);
        if (bullet) {
          flushParagraph();
          if (list !== 'ul') {
            closeList();
            output.push('<ul>');
            list = 'ul';
          }
          output.push('<li>' + inlineMarkdown(bullet[1]) + '</li>');
          continue;
        }
        const numbered = line.match(/^\d+\.\s+(.+)$/);
        if (numbered) {
          flushParagraph();
          if (list !== 'ol') {
            closeList();
            output.push('<ol>');
            list = 'ol';
          }
          output.push('<li>' + inlineMarkdown(numbered[1]) + '</li>');
          continue;
        }
        closeList();
        paragraph.push(line);
      }
      flushParagraph();
      closeList();
      return output.join('\n');
    }
    function inlineMarkdown(value) {
      return htmlEscape(value)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    }
    function syncRunMode() {
      const mode = document.getElementById('run-mode').value;
      document.getElementById('run-days-wrap').hidden = mode !== 'days';
      document.getElementById('run-range-wrap').hidden = mode !== 'range';
    }
    function showConfigMode(mode) {
      configMode = mode;
      document.getElementById('config-form').hidden = mode !== 'form';
      document.getElementById('config-editor').hidden = mode !== 'raw';
      document.getElementById('config-raw-toggle').checked = mode === 'raw';
      if (mode === 'form') populateConfigForm(document.getElementById('config-editor').value);
    }
    function scrollConfigModule(id) {
      const target = document.getElementById(id);
      if (target) {
        target.scrollIntoView({behavior:'smooth', block:'start'});
        setConfigNavActive(id);
      }
    }
    function setConfigNavActive(id) {
      document.querySelectorAll('.config-nav button').forEach(button => {
        button.classList.toggle('active', button.dataset.target === id);
      });
    }
    function updateConfigNavActive() {
      const container = document.querySelector('section');
      if (!container || document.getElementById('view-config').hidden) return;
      const blocks = [...document.querySelectorAll('#config-form .form-block')];
      let current = blocks[0];
      const top = container.getBoundingClientRect().top + 24;
      for (const block of blocks) {
        if (block.getBoundingClientRect().top <= top) current = block;
      }
      if (current) setConfigNavActive(current.id);
    }
    function readTomlString(text, key, fallback='') {
      const m = text.match(new RegExp('^' + key.replace('.', '\\.') + '\\s*=\\s*"([^"]*)"', 'm'));
      return m ? m[1] : fallback;
    }
    function readTomlNumber(text, key, fallback='') {
      const m = text.match(new RegExp('^' + key.replace('.', '\\.') + '\\s*=\\s*([0-9]+)', 'm'));
      return m ? m[1] : fallback;
    }
    function readTomlBool(text, key, fallback='true') {
      const m = text.match(new RegExp('^' + key.replace('.', '\\.') + '\\s*=\\s*(true|false)', 'm'));
      return m ? m[1] : fallback;
    }
    function readTomlArray(text, key, fallback=[]) {
      const m = text.match(new RegExp('^' + key.replace('.', '\\.') + '\\s*=\\s*\\[([^\\]]*)\\]', 'm'));
      if (!m) return fallback;
      return [...m[1].matchAll(/"((?:[^"\\]|\\.)*)"/g)].map(x => x[1].replace(/\\"/g, '"').replace(/\\\\/g, '\\'));
    }
    function listInterestNames(text) {
      return [...text.matchAll(/^name\s*=\s*"([^"]+)"/gm)].map(m => m[1]);
    }
    function checkedValues(id) {
      return [...document.querySelectorAll(`#${id} input[type="checkbox"]:checked`)].map(x => x.value);
    }
    function populateRunInterestSelect(interests) {
      const select = document.getElementById('run-interest');
      const previous = select.value;
      select.innerHTML = '<option value="">Config default</option><option value="none">None / all arXiv papers</option>' + interests.map(x => `<option value="${htmlEscape(x)}">${htmlEscape(x)}</option>`).join('');
      if ([...select.options].some(option => option.value === previous)) select.value = previous;
    }
    function populateMultiSelect(id, values, selected) {
      const selectedSet = new Set(selected || []);
      const select = document.getElementById(id);
      select.innerHTML = values.map(value => `<option value="${htmlEscape(value)}">${htmlEscape(value)}</option>`).join('');
      [...select.options].forEach(option => { option.selected = selectedSet.has(option.value); });
    }
    function populateDefaultFetchChecks(values, selected) {
      const selectedSet = new Set(selected || []);
      const container = document.getElementById('cfg-default-fetch-interests');
      container.innerHTML = values.map((value, index) => {
        const id = `default-fetch-${index}`;
        const checked = selectedSet.has(value) ? ' checked' : '';
        return `<label class="check-row" for="${id}"><input id="${id}" type="checkbox" value="${htmlEscape(value)}"${checked}><span>${htmlEscape(value)}</span></label>`;
      }).join('') || '<p class="muted" style="margin:4px">No interests configured.</p>';
    }
    function htmlEscape(value) {
      return String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    function tomlEscape(value) {
      return String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    }
    function renderTomlArray(values) {
      return '[' + values.map(value => `"${tomlEscape(value)}"`).join(', ') + ']';
    }
    function section(text, name) {
      const re = new RegExp('\\[' + name + '\\]([\\s\\S]*?)(?=\\n\\[|$)');
      const m = text.match(re);
      return m ? m[1] : '';
    }
    function setInSection(text, sec, key, value, quoted=true) {
      const block = section(text, sec);
      const rendered = quoted ? `${key} = "${tomlEscape(value)}"` : `${key} = ${value}`;
      if (!block) return text + `\n[${sec}]\n${rendered}\n`;
      const re = new RegExp('(\\[' + sec + '\\][\\s\\S]*?^)' + key + '\\s*=\\s*.*$', 'm');
      if (re.test(text)) return text.replace(re, `$1${rendered}`);
      return text.replace(new RegExp('(\\[' + sec + '\\]\\n)'), `$1${rendered}\n`);
    }
    function setRoot(text, key, value, quoted=false) {
      const rendered = quoted ? `${key} = "${value}"` : `${key} = ${value}`;
      const re = new RegExp('^' + key + '\\s*=\\s*.*$', 'm');
      return re.test(text) ? text.replace(re, rendered) : rendered + '\n' + text;
    }
    function populateConfigForm(text) {
      document.getElementById('cfg-per-interest-limit').value = readTomlNumber(text, 'per_interest_limit', '');
      document.getElementById('cfg-schedule-enabled').value = readTomlBool(section(text, 'schedule'), 'enabled', 'false');
      document.getElementById('cfg-schedule-days').value = readTomlNumber(section(text, 'schedule'), 'days', '1');
      document.getElementById('cfg-schedule-hour').value = readTomlNumber(section(text, 'schedule'), 'hour', '12');
      document.getElementById('cfg-schedule-minute').value = readTomlNumber(section(text, 'schedule'), 'minute', '30');
      document.getElementById('cfg-feishu-enabled').value = readTomlBool(section(text, 'feishu'), 'enabled', 'false');
      document.getElementById('cfg-feishu-send-schedule').value = readTomlBool(section(text, 'feishu'), 'send_on_schedule', 'true');
      document.getElementById('cfg-feishu-webhook').value = readTomlString(section(text, 'feishu'), 'webhook_url', '');
      document.getElementById('cfg-feishu-secret').value = readTomlString(section(text, 'feishu'), 'secret', '');
      document.getElementById('cfg-ranking-mode').value = readTomlString(section(text, 'ranking'), 'mode', 'keyword');
      document.getElementById('cfg-arxiv-max').value = readTomlNumber(section(text, 'sources.arxiv'), 'max_results_per_interest', '80');
      document.getElementById('cfg-openalex-max').value = readTomlNumber(section(text, 'sources.openalex'), 'max_results_per_interest', '40');
      document.getElementById('cfg-openalex-mailto').value = readTomlString(section(text, 'sources.openalex'), 'mailto', '');
      document.getElementById('cfg-dblp-max').value = readTomlNumber(section(text, 'sources.dblp'), 'max_results_per_interest', '40');
      populateSourceChecks(text);
      const interestNames = listInterestNames(text);
      const defaultFetch = readTomlArray(section(text, 'sources.arxiv'), 'default_fetch_interests', interestNames);
      populateRunInterestSelect(interestNames);
      populateDefaultFetchChecks(interestNames, defaultFetch);
      populateInterestEditor(text);
      document.getElementById('cfg-embedding-base').value = readTomlString(section(text, 'embedding'), 'base_url', '');
      document.getElementById('cfg-embedding-model').value = readTomlString(section(text, 'embedding'), 'model', '');
      document.getElementById('cfg-embedding-key-env').value = readTomlString(section(text, 'embedding'), 'api_key_env', 'OPENAI_API_KEY');
      document.getElementById('cfg-embedding-key').value = readTomlString(section(text, 'embedding'), 'api_key', '');
      document.getElementById('cfg-ai-base').value = readTomlString(section(text, 'ai'), 'base_url', '');
      document.getElementById('cfg-ai-model').value = readTomlString(section(text, 'ai'), 'model', '');
      document.getElementById('cfg-ai-key-env').value = readTomlString(section(text, 'ai'), 'api_key_env', 'OPENAI_API_KEY');
      document.getElementById('cfg-ai-key').value = readTomlString(section(text, 'ai'), 'api_key', '');
      document.getElementById('cfg-digest-ai-base').value = readTomlString(section(text, 'digest_ai'), 'base_url', document.getElementById('cfg-ai-base').value);
      document.getElementById('cfg-digest-ai-model').value = readTomlString(section(text, 'digest_ai'), 'model', document.getElementById('cfg-ai-model').value);
      document.getElementById('cfg-digest-ai-key-env').value = readTomlString(section(text, 'digest_ai'), 'api_key_env', document.getElementById('cfg-ai-key-env').value);
      document.getElementById('cfg-digest-ai-key').value = readTomlString(section(text, 'digest_ai'), 'api_key', document.getElementById('cfg-ai-key').value);
      document.getElementById('cfg-interest-ai-base').value = readTomlString(section(text, 'interest_ai'), 'base_url', document.getElementById('cfg-ai-base').value);
      document.getElementById('cfg-interest-ai-model').value = readTomlString(section(text, 'interest_ai'), 'model', document.getElementById('cfg-ai-model').value);
      document.getElementById('cfg-interest-ai-key-env').value = readTomlString(section(text, 'interest_ai'), 'api_key_env', document.getElementById('cfg-ai-key-env').value);
      document.getElementById('cfg-interest-ai-key').value = readTomlString(section(text, 'interest_ai'), 'api_key', '');
      document.getElementById('cfg-translation-enabled').value = readTomlBool(section(text, 'translation'), 'enabled', 'true');
      document.getElementById('cfg-translation-language').value = readTomlString(section(text, 'translation'), 'language', 'Chinese');
    }
    function applyConfigForm() {
      let text = document.getElementById('config-editor').value;
      text = setRoot(text, 'per_interest_limit', document.getElementById('cfg-per-interest-limit').value || '0');
      text = setInSection(text, 'schedule', 'enabled', document.getElementById('cfg-schedule-enabled').value, false);
      text = setInSection(text, 'schedule', 'days', document.getElementById('cfg-schedule-days').value || '1', false);
      text = setInSection(text, 'schedule', 'hour', document.getElementById('cfg-schedule-hour').value || '12', false);
      text = setInSection(text, 'schedule', 'minute', document.getElementById('cfg-schedule-minute').value || '30', false);
      text = setInSection(text, 'feishu', 'enabled', document.getElementById('cfg-feishu-enabled').value, false);
      text = setInSection(text, 'feishu', 'send_on_schedule', document.getElementById('cfg-feishu-send-schedule').value, false);
      text = setInSection(text, 'feishu', 'webhook_url', document.getElementById('cfg-feishu-webhook').value);
      text = setInSection(text, 'feishu', 'secret', document.getElementById('cfg-feishu-secret').value);
      text = setInSection(text, 'feishu', 'timeout_seconds', '15', false);
      text = setInSection(text, 'ranking', 'mode', document.getElementById('cfg-ranking-mode').value);
      text = setInSection(text, 'sources.arxiv', 'max_results_per_interest', document.getElementById('cfg-arxiv-max').value || '80', false);
      text = setInSection(text, 'sources.arxiv', 'enabled', checkedValues('cfg-enabled-sources').includes('arxiv') ? 'true' : 'false', false);
      text = setInSection(text, 'sources.openalex', 'enabled', checkedValues('cfg-enabled-sources').includes('openalex') ? 'true' : 'false', false);
      text = setInSection(text, 'sources.openalex', 'max_results_per_interest', document.getElementById('cfg-openalex-max').value || '40', false);
      text = setInSection(text, 'sources.openalex', 'request_timeout_seconds', '30', false);
      text = setInSection(text, 'sources.openalex', 'mailto', document.getElementById('cfg-openalex-mailto').value);
      text = setInSection(text, 'sources.dblp', 'enabled', checkedValues('cfg-enabled-sources').includes('dblp') ? 'true' : 'false', false);
      text = setInSection(text, 'sources.dblp', 'max_results_per_interest', document.getElementById('cfg-dblp-max').value || '40', false);
      text = setInSection(text, 'sources.dblp', 'request_timeout_seconds', '30', false);
      text = setInSection(text, 'sources.arxiv', 'default_fetch_interests', renderTomlArray(checkedValues('cfg-default-fetch-interests')), false);
      text = setInSection(text, 'embedding', 'base_url', document.getElementById('cfg-embedding-base').value);
      text = setInSection(text, 'embedding', 'model', document.getElementById('cfg-embedding-model').value);
      text = setInSection(text, 'embedding', 'api_key_env', document.getElementById('cfg-embedding-key-env').value);
      text = setInSection(text, 'embedding', 'api_key', document.getElementById('cfg-embedding-key').value);
      text = setInSection(text, 'ai', 'base_url', document.getElementById('cfg-ai-base').value);
      text = setInSection(text, 'ai', 'model', document.getElementById('cfg-ai-model').value);
      text = setInSection(text, 'ai', 'api_key_env', document.getElementById('cfg-ai-key-env').value);
      text = setInSection(text, 'ai', 'api_key', document.getElementById('cfg-ai-key').value);
      text = setInSection(text, 'digest_ai', 'base_url', document.getElementById('cfg-digest-ai-base').value);
      text = setInSection(text, 'digest_ai', 'model', document.getElementById('cfg-digest-ai-model').value);
      text = setInSection(text, 'digest_ai', 'api_key_env', document.getElementById('cfg-digest-ai-key-env').value);
      text = setInSection(text, 'digest_ai', 'api_key', document.getElementById('cfg-digest-ai-key').value);
      text = setInSection(text, 'digest_ai', 'language', document.getElementById('cfg-translation-language').value);
      text = setInSection(text, 'digest_ai', 'max_papers_per_interest', '10', false);
      text = setInSection(text, 'digest_ai', 'timeout_seconds', '90', false);
      text = setInSection(text, 'interest_ai', 'base_url', document.getElementById('cfg-interest-ai-base').value);
      text = setInSection(text, 'interest_ai', 'model', document.getElementById('cfg-interest-ai-model').value);
      text = setInSection(text, 'interest_ai', 'api_key_env', document.getElementById('cfg-interest-ai-key-env').value);
      text = setInSection(text, 'interest_ai', 'api_key', document.getElementById('cfg-interest-ai-key').value);
      text = setInSection(text, 'translation', 'enabled', document.getElementById('cfg-translation-enabled').value, false);
      text = setInSection(text, 'translation', 'language', document.getElementById('cfg-translation-language').value);
      document.getElementById('config-editor').value = text;
      populateInterestEditor(text);
    }
    async function scheduleAction(action) {
      if (configMode === 'form') applyConfigForm();
      const status = document.getElementById('schedule-status');
      status.textContent = action === 'install' ? 'Saving and installing...' : (action === 'uninstall' ? 'Uninstalling...' : 'Loading status...');
      try {
        await postJson('/api/config', {content: document.getElementById('config-editor').value});
        const data = action === 'status' ? await getJson('/api/schedule-status') : await postJson('/api/schedule', {action});
        if (!data.ok) {
          status.textContent = 'Failed: ' + (data.error || 'unknown error');
          return;
        }
        const info = data.status || {};
        status.textContent = `${data.message || 'OK'} Enabled: ${info.enabled_in_config}; installed: ${info.installed}; time: ${info.time || ''}; Feishu: ${info.send_feishu}`;
      } catch (e) {
        status.textContent = 'Failed: ' + e;
      }
    }
    async function testAI(target) {
      if (configMode === 'form') applyConfigForm();
      const statusId = target === 'interest_ai' ? 'interest-ai-test-status' : (target === 'digest_ai' ? 'digest-ai-test-status' : 'ai-test-status');
      const status = document.getElementById(statusId);
      status.textContent = 'Testing...';
      await postJson('/api/config', {content: document.getElementById('config-editor').value});
      const data = await postJson('/api/test-ai', {target});
      status.textContent = data.ok ? `OK: ${data.reply}` : `Failed: ${data.error}`;
    }
    async function testEmbedding() {
      if (configMode === 'form') applyConfigForm();
      const status = document.getElementById('embedding-test-status');
      status.textContent = 'Testing...';
      await postJson('/api/config', {content: document.getElementById('config-editor').value});
      const data = await postJson('/api/test-embedding', {});
      status.textContent = data.ok ? `OK: ${data.dimensions} dimensions` : `Failed: ${data.error}`;
    }
    async function testSource(target) {
      if (configMode === 'form') applyConfigForm();
      const status = document.getElementById('source-test-status');
      status.textContent = `Testing ${target}...`;
      await postJson('/api/config', {content: document.getElementById('config-editor').value});
      const data = await postJson('/api/test-source', {target});
      status.textContent = data.ok ? `OK: ${target} returned ${data.count} item(s).` : `Failed: ${data.error}`;
    }
    async function generateInterest() {
      if (configMode === 'form') applyConfigForm();
      const status = document.getElementById('interest-generate-status');
      const button = document.getElementById('generate-interest-button');
      const paperText = document.getElementById('interest-paper-text').value;
      if (!paperText.trim()) {
        status.textContent = 'Paste paper links, a title, abstract, or notes first.';
        return;
      }
      status.textContent = 'Saving config...';
      button.disabled = true;
      await postJson('/api/config', {content: document.getElementById('config-editor').value});
      const started = await postJson('/api/generate-interest-job', {paper_text: paperText});
      if (!started.ok) {
        status.textContent = 'Failed to start: ' + (started.error || 'unknown error');
        button.disabled = false;
        return;
      }
      status.textContent = 'Queued...';
      while (true) {
        await sleep(1000);
        const data = await getJson('/api/generate-interest-status?job_id=' + encodeURIComponent(started.job_id));
        status.textContent = data.step || 'Working...';
        if (!data.done) continue;
        button.disabled = false;
        if (data.ok) {
          document.getElementById('generated-interest').value = data.toml || '';
        } else {
          status.textContent = 'Failed: ' + (data.error || 'unknown error');
        }
        return;
      }
    }
    function sleep(ms) {
      return new Promise(resolve => setTimeout(resolve, ms));
    }
    async function appendGeneratedInterest() {
      const block = document.getElementById('generated-interest').value.trim();
      if (!block) return;
      if (configMode === 'form') applyConfigForm();
      const editor = document.getElementById('config-editor');
      const generatedName = (block.match(/^name\s*=\s*"([^"]+)"/m) || [])[1];
      const existing = parseInterestBlocks(editor.value);
      const existingIndex = generatedName ? existing.findIndex(item => item.name === generatedName) : -1;
      if (existingIndex >= 0 && confirm('An interest named "' + generatedName + '" already exists. Replace it instead of adding a duplicate?')) {
        editor.value = replaceInterestBlock(editor.value, existing[existingIndex].index, block);
      } else {
        editor.value = editor.value.trimEnd() + '\n\n' + block + '\n';
      }
      if (generatedName) {
        const current = readTomlArray(section(editor.value, 'sources.arxiv'), 'default_fetch_interests', listInterestNames(editor.value));
        if (!current.includes(generatedName)) current.push(generatedName);
        editor.value = setInSection(editor.value, 'sources.arxiv', 'default_fetch_interests', renderTomlArray(current), false);
      }
      try {
        await postJson('/api/config', {content: editor.value});
        document.getElementById('interest-generate-status').textContent = 'Appended and saved.';
        await loadConfig();
      } catch (e) {
        document.getElementById('interest-generate-status').textContent = 'Append failed: ' + e;
      }
    }
    function parseInterestBlocks(text) {
      const starts = [...text.matchAll(/^\[\[interests\]\]\s*$/gm)].map(match => match.index);
      return starts.map((start, index) => {
        const end = index + 1 < starts.length ? starts[index + 1] : text.length;
        const block = text.slice(start, end).trim();
        return {
          index,
          start,
          end,
          block,
          name: readTomlString(block, 'name', '(unnamed)'),
          description: readTomlString(block, 'description', ''),
          categories: readTomlArrayFlexible(block, 'arxiv_categories', []),
          seeds: readTomlArrayFlexible(block, 'seed_papers', []),
          keywords: readTomlArrayFlexible(block, 'keywords', []),
          keywordWeights: readTomlNumberMap(block, 'keyword_weights', {}),
          negative: readTomlArrayFlexible(block, 'negative_keywords', []),
        };
      });
    }
    function readTomlArrayFlexible(text, key, fallback=[]) {
      const re = new RegExp('^' + key.replace('.', '\\.') + '\\s*=\\s*\\[([\\s\\S]*?)\\]', 'm');
      const m = text.match(re);
      if (!m) return fallback;
      return [...m[1].matchAll(/"((?:[^"\\]|\\.)*)"/g)].map(x => x[1].replace(/\\"/g, '"').replace(/\\\\/g, '\\'));
    }
    function readTomlNumberMap(text, key, fallback={}) {
      const re = new RegExp('^' + key.replace('.', '\\.') + '\\s*=\\s*\\{([\\s\\S]*?)\\}', 'm');
      const m = text.match(re);
      if (!m) return fallback;
      const result = {};
      for (const match of m[1].matchAll(/"((?:[^"\\]|\\.)*)"\s*=\s*([0-9]+(?:\.[0-9]+)?)/g)) {
        result[match[1].replace(/\\"/g, '"').replace(/\\\\/g, '\\')] = Number(match[2]);
      }
      return result;
    }
    function populateSourceChecks(text) {
      const selected = [];
      if (readTomlBool(section(text, 'sources.arxiv'), 'enabled', 'true') === 'true') selected.push('arxiv');
      if (readTomlBool(section(text, 'sources.openalex'), 'enabled', 'false') === 'true') selected.push('openalex');
      if (readTomlBool(section(text, 'sources.dblp'), 'enabled', 'false') === 'true') selected.push('dblp');
      const choices = [
        ['arxiv', 'arXiv'],
        ['openalex', 'OpenAlex'],
        ['dblp', 'dblp'],
      ];
      const selectedSet = new Set(selected);
      document.getElementById('cfg-enabled-sources').innerHTML = choices.map(([value, label], index) => {
        const id = `source-${index}`;
        const checked = selectedSet.has(value) ? ' checked' : '';
        return `<label class="check-row" for="${id}"><input id="${id}" type="checkbox" value="${value}"${checked}><span>${label}</span></label>`;
      }).join('');
    }
    function populateInterestEditor(text) {
      const select = document.getElementById('interest-edit-select');
      if (!select) return;
      const previous = select.value;
      const interests = parseInterestBlocks(text);
      const seen = {};
      select.innerHTML = interests.map(item => {
        seen[item.name] = (seen[item.name] || 0) + 1;
        const suffix = seen[item.name] > 1 ? ` (${seen[item.name]})` : '';
        return `<option value="${item.index}">${htmlEscape(item.name + suffix)}</option>`;
      }).join('');
      if (previous && [...select.options].some(option => option.value === previous)) select.value = previous;
      if (!select.value && select.options.length) select.value = select.options[0].value;
      loadSelectedInterest();
    }
    function loadSelectedInterest() {
      const select = document.getElementById('interest-edit-select');
      if (!select) return;
      const item = parseInterestBlocks(document.getElementById('config-editor').value).find(x => String(x.index) === select.value);
      document.getElementById('interest-edit-status').textContent = item ? '' : 'No interest selected.';
      document.getElementById('interest-edit-name').value = item ? item.name : '';
      document.getElementById('interest-edit-description').value = item ? item.description : '';
      document.getElementById('interest-edit-categories').value = item ? item.categories.join(', ') : '';
      document.getElementById('interest-edit-keywords').value = item ? renderKeywordLines(item.keywords, item.keywordWeights) : '';
      document.getElementById('interest-edit-negative').value = item ? item.negative.join('\n') : '';
      document.getElementById('interest-edit-seeds').value = item ? item.seeds.join('\n') : '';
    }
    function addBlankInterest() {
      const existing = new Set(listInterestNames(document.getElementById('config-editor').value));
      let name = 'New Interest';
      let index = 2;
      while (existing.has(name)) {
        name = `New Interest ${index}`;
        index += 1;
      }
      const block = renderInterestBlock({
        name,
        description: '',
        categories: ['cs.CV'],
        seeds: [],
        keywords: [],
        keywordWeights: {},
        negative: [],
      });
      const editor = document.getElementById('config-editor');
      editor.value = editor.value.trimEnd() + '\n\n' + block + '\n';
      populateConfigForm(editor.value);
      const interests = parseInterestBlocks(editor.value);
      const added = interests.find(item => item.name === name);
      if (added) document.getElementById('interest-edit-select').value = String(added.index);
      loadSelectedInterest();
      document.getElementById('interest-edit-status').textContent = 'Created. Fill it in, then click Save config to persist.';
    }
    function saveSelectedInterest() {
      const select = document.getElementById('interest-edit-select');
      const index = Number(select.value);
      const current = parseInterestBlocks(document.getElementById('config-editor').value).find(x => x.index === index);
      if (!current) return;
      const oldName = current.name;
      const name = document.getElementById('interest-edit-name').value.trim();
      if (!name) {
        document.getElementById('interest-edit-status').textContent = 'Name is required.';
        return;
      }
      const block = renderInterestBlock({
        name,
        description: document.getElementById('interest-edit-description').value.trim(),
        categories: csvValues(document.getElementById('interest-edit-categories').value),
        seeds: lineValues(document.getElementById('interest-edit-seeds').value),
        ...parseKeywordLines(document.getElementById('interest-edit-keywords').value),
        negative: lineValues(document.getElementById('interest-edit-negative').value),
      });
      let text = replaceInterestBlock(document.getElementById('config-editor').value, index, block);
      let defaults = readTomlArray(section(text, 'sources.arxiv'), 'default_fetch_interests', listInterestNames(text));
      defaults = defaults.map(value => value === oldName ? name : value);
      text = setInSection(text, 'sources.arxiv', 'default_fetch_interests', renderTomlArray(uniqueValues(defaults)), false);
      document.getElementById('config-editor').value = text;
      populateConfigForm(text);
      document.getElementById('interest-edit-status').textContent = 'Edited. Click Save config to persist.';
    }
    function deleteSelectedInterest() {
      const select = document.getElementById('interest-edit-select');
      const index = Number(select.value);
      const item = parseInterestBlocks(document.getElementById('config-editor').value).find(x => x.index === index);
      if (!item) return;
      if (!confirm('Delete interest "' + item.name + '"?')) return;
      let text = removeInterestBlock(document.getElementById('config-editor').value, index);
      const remainingNames = listInterestNames(text);
      const defaults = readTomlArray(section(text, 'sources.arxiv'), 'default_fetch_interests', remainingNames).filter(value => value !== item.name);
      text = setInSection(text, 'sources.arxiv', 'default_fetch_interests', renderTomlArray(defaults.filter(value => remainingNames.includes(value))), false);
      document.getElementById('config-editor').value = text;
      populateConfigForm(text);
      document.getElementById('interest-edit-status').textContent = 'Deleted. Click Save config to persist.';
    }
    function replaceInterestBlock(text, index, block) {
      const item = parseInterestBlocks(text).find(x => x.index === index);
      if (!item) return text;
      return text.slice(0, item.start).trimEnd() + '\n\n' + block.trim() + '\n\n' + text.slice(item.end).trimStart();
    }
    function removeInterestBlock(text, index) {
      const item = parseInterestBlocks(text).find(x => x.index === index);
      if (!item) return text;
      return (text.slice(0, item.start).trimEnd() + '\n\n' + text.slice(item.end).trimStart()).trim() + '\n';
    }
    function renderInterestBlock(item) {
      return [
        '[[interests]]',
        `name = "${tomlEscape(item.name)}"`,
        `description = "${tomlEscape(item.description)}"`,
        `arxiv_categories = ${renderTomlArray(item.categories)}`,
        `seed_papers = ${renderTomlArray(item.seeds)}`,
        `keywords = ${renderTomlArray(item.keywords)}`,
        `keyword_weights = ${renderTomlNumberMap(item.keywordWeights, item.keywords)}`,
        `negative_keywords = ${renderTomlArray(item.negative)}`,
      ].join('\n');
    }
    function renderKeywordLines(keywords, weights) {
      return (keywords || []).map(keyword => `${keyword} | ${Number((weights || {})[keyword] || 1)}`).join('\n');
    }
    function parseKeywordLines(value) {
      const keywords = [];
      const keywordWeights = {};
      for (const line of String(value).split(/\n+/)) {
        const raw = line.trim();
        if (!raw) continue;
        const parts = raw.split('|');
        const keyword = parts[0].trim();
        if (!keyword) continue;
        const parsed = parts.length > 1 ? Number(parts.slice(1).join('|').trim()) : 1;
        const weight = Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
        if (!keywords.includes(keyword)) keywords.push(keyword);
        keywordWeights[keyword] = weight;
      }
      return {keywords, keywordWeights};
    }
    function renderTomlNumberMap(values, keywords) {
      return '{ ' + (keywords || []).map(keyword => {
        const raw = Number((values || {})[keyword] || 1);
        const weight = Number.isFinite(raw) && raw > 0 ? raw : 1;
        return `"${tomlEscape(keyword)}" = ${weight}`;
      }).join(', ') + ' }';
    }
    function lineValues(value) {
      return uniqueValues(String(value).split(/\n+/).map(x => x.trim()).filter(Boolean));
    }
    function csvValues(value) {
      return uniqueValues(String(value).split(',').map(x => x.trim()).filter(Boolean));
    }
    function uniqueValues(values) {
      return [...new Set(values)];
    }
    document.querySelector('section').addEventListener('scroll', updateConfigNavActive, {passive:true});
    syncRunMode(); loadConfig(); loadDigests(); setConfigNavActive('cfg-auto');
  </script>
</body>
</html>
"""
