from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time as dt_time, timezone

from paperwatch.models import Interest, OpenAlexConfig, Paper


OPENALEX_API_URL = "https://api.openalex.org/works"


class OpenAlexSource:
    def __init__(self, config: OpenAlexConfig) -> None:
        self.config = config

    def fetch(self, interest: Interest, start_date: date, end_date: date) -> list[Paper]:
        keywords = interest.keywords[:8] or [interest.name]
        per_query = max(1, self.config.max_results_per_interest // max(len(keywords), 1))
        papers: list[Paper] = []
        for keyword in keywords:
            papers.extend(self._fetch_query(keyword, start_date, end_date, per_query))
            time.sleep(0.2)
        return _dedupe(papers)[: self.config.max_results_per_interest]

    def fetch_all(self, start_date: date, end_date: date) -> list[Paper]:
        return self._fetch_query("", start_date, end_date, self.config.max_results_per_interest)

    def _fetch_query(self, query: str, start_date: date, end_date: date, per_page: int) -> list[Paper]:
        filters = [
            f"from_publication_date:{start_date.isoformat()}",
            f"to_publication_date:{end_date.isoformat()}",
        ]
        params = {
            "filter": ",".join(filters),
            "per-page": str(max(1, min(per_page, 200))),
            "sort": "publication_date:desc",
        }
        if query:
            params["search"] = query
        if self.config.mailto:
            params["mailto"] = self.config.mailto
        url = f"{OPENALEX_API_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": "paperwatch/0.1 (openalex source)"})
        try:
            with urllib.request.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAlex request failed with HTTP {exc.code}: {detail[:200]}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"OpenAlex request failed: {reason}") from exc
        return [_parse_work(item) for item in payload.get("results", []) if isinstance(item, dict)]


def _parse_work(item: dict) -> Paper:
    work_id = str(item.get("id", "")).rstrip("/").split("/")[-1] or str(item.get("doi", ""))
    title = str(item.get("title") or item.get("display_name") or "Untitled")
    abstract = _inverted_index_to_text(item.get("abstract_inverted_index") or {})
    authorships = item.get("authorships") or []
    authors = []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        if isinstance(author, dict) and author.get("display_name"):
            authors.append(str(author["display_name"]))
    publication_date = str(item.get("publication_date") or "")
    published = _parse_date(publication_date)
    concepts = item.get("concepts") or []
    categories = [
        str(concept.get("display_name"))
        for concept in concepts
        if isinstance(concept, dict) and concept.get("display_name")
    ][:8]
    primary_location = item.get("primary_location") or {}
    source = primary_location.get("source") if isinstance(primary_location, dict) else None
    venue = str(source.get("display_name")) if isinstance(source, dict) and source.get("display_name") else None
    pdf_url = None
    if isinstance(primary_location, dict):
        pdf_url = primary_location.get("pdf_url") or None
    return Paper(
        source="openalex",
        paper_id=work_id,
        title=title,
        authors=authors,
        abstract=abstract or "Abstract unavailable from OpenAlex.",
        published_at=published,
        updated_at=None,
        url=str(item.get("doi") or item.get("id") or ""),
        pdf_url=str(pdf_url) if pdf_url else None,
        doi=str(item.get("doi")) if item.get("doi") else None,
        venue=venue,
        categories=categories,
    )


def _inverted_index_to_text(index: dict) -> str:
    if not index:
        return ""
    positions: dict[int, str] = {}
    for word, offsets in index.items():
        if not isinstance(offsets, list):
            continue
        for offset in offsets:
            if isinstance(offset, int):
                positions[offset] = str(word)
    return " ".join(positions[index] for index in sorted(positions))


def _parse_date(value: str) -> datetime:
    if not value:
        return datetime.combine(date.today(), dt_time.min, tzinfo=timezone.utc)
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _dedupe(papers: list[Paper]) -> list[Paper]:
    seen = set()
    result = []
    for paper in papers:
        key = (paper.source, paper.paper_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(paper)
    return result
