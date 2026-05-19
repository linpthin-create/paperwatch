#!/usr/bin/env python3
from __future__ import annotations

import html
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paperwatch.models import Paper, ScoredPaper  # noqa: E402
from paperwatch.notify.feishu import DigestNotification, notify_digest  # noqa: E402
from paperwatch.render import write_digest  # noqa: E402


CATEGORIES = ["cs.CV", "cs.AI", "cs.LG", "eess.IV"]
KEYWORDS = [
    "image generation",
    "video generation",
    "text-to-image",
    "text to image",
    "diffusion model",
    "diffusion models",
    "generative model",
    "generative models",
    "vision generation",
    "controllable generation",
    "image synthesis",
    "video synthesis",
    "3d generation",
    "text-to-3d",
    "multimodal generation",
    "visual generation",
    "autoregressive image",
    "flow matching",
    "rectified flow",
    "consistency model",
    "latent diffusion",
]


@dataclass(frozen=True)
class WebEntry:
    paper_id: str
    title: str
    authors: list[str]
    subjects: list[str]
    category: str


def main() -> int:
    target_label = "Mon, 18 May 2026"
    entries: dict[str, WebEntry] = {}
    for category in CATEGORIES:
        for entry in fetch_category_day(category, target_label):
            entries.setdefault(entry.paper_id, entry)

    scored = sorted(
        (score_entry(entry) for entry in entries.values()),
        key=lambda item: item.score,
        reverse=True,
    )
    selected = scored[:10]
    digest = write_digest(
        selected,
        ROOT / "data" / "digests",
        metadata={
            "Date range": "2026-05-18 to 2026-05-18",
            "Interest": "CV Model Generation",
            "Ranking": "web-fallback title keyword",
            "Mode": "manual",
            "Note": "arXiv API was rate-limited; this fallback uses arXiv HTML listing pages, so abstracts are unavailable.",
        },
        timestamped=True,
        label="web-fallback-20260518",
    )
    sent = notify_digest(
        DigestNotification(
            date_range="2026-05-18 to 2026-05-18",
            interests=["CV Model Generation"],
            ranking_mode="web-fallback title keyword",
            mode="manual",
            fetched_count=len(entries),
            unique_count=len(entries),
            inserted_count=0,
            recommendation_count=len(selected),
            digest_paths=[str(digest)],
            top_papers=selected,
        )
    )
    print(f"Fetched {len(entries)} unique web-list entries.")
    print(f"Wrote fallback digest: {digest}")
    print(f"Feishu sent: {sent}")
    return 0 if sent else 1


def fetch_category_day(category: str, day_label: str) -> list[WebEntry]:
    recent = fetch_text(f"https://arxiv.org/list/{category}/recent")
    match = re.search(
        rf"href=\"/list/{re.escape(category)}/recent\?skip=(\d+)&amp;show=50\">\s*{re.escape(day_label)}",
        recent,
    )
    if not match:
        return []
    skip = match.group(1)
    page = fetch_text(f"https://arxiv.org/list/{category}/recent?skip={skip}&show=250")
    return parse_entries(page, category)


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "paperwatch/0.1 (arxiv html fallback)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_entries(page: str, category: str) -> list[WebEntry]:
    entries: list[WebEntry] = []
    pattern = re.compile(r"<dt>(.*?)</dd>", re.DOTALL)
    for block in pattern.findall(page):
        id_match = re.search(r"/abs/([^\"']+)", block)
        title_match = re.search(r"<div class='list-title mathjax'>.*?</span>\s*(.*?)\s*</div>", block, re.DOTALL)
        authors_match = re.search(r"<div class='list-authors'>.*?</span>\s*(.*?)\s*</div>", block, re.DOTALL)
        subjects_match = re.search(r"<div class='list-subjects'>.*?</span>\s*(.*?)\s*</div>", block, re.DOTALL)
        if not id_match or not title_match:
            continue
        paper_id = clean(id_match.group(1))
        title = clean(title_match.group(1))
        authors = re.findall(r">([^<>]+)</a>", authors_match.group(1) if authors_match else "")
        subjects = split_subjects(clean(subjects_match.group(1) if subjects_match else ""))
        entries.append(WebEntry(paper_id, title, authors, subjects, category))
    return entries


def clean(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split())


def split_subjects(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def score_entry(entry: WebEntry) -> ScoredPaper:
    text = entry.title.lower()
    matched = [keyword for keyword in KEYWORDS if keyword in text]
    score = float(len(matched) * 10)
    if "generation" in text or "generative" in text:
        score += 5.0
    if "diffusion" in text or "flow" in text:
        score += 3.0
    paper = Paper(
        source="arxiv-web",
        paper_id=entry.paper_id,
        title=entry.title,
        authors=entry.authors,
        abstract="Abstract unavailable in arXiv HTML fallback mode.",
        published_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
        updated_at=None,
        url=f"https://arxiv.org/abs/{urllib.parse.quote(entry.paper_id)}",
        pdf_url=f"https://arxiv.org/pdf/{urllib.parse.quote(entry.paper_id)}",
        categories=[entry.category, *entry.subjects],
    )
    return ScoredPaper(paper, "CV Model Generation", score, matched, [])


if __name__ == "__main__":
    raise SystemExit(main())
