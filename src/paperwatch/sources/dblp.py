from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

from paperwatch.models import DblpConfig, Interest, Paper


DBLP_API_URL = "https://dblp.org/search/publ/api"


class DblpSource:
    def __init__(self, config: DblpConfig) -> None:
        self.config = config

    def fetch(self, interest: Interest, start_date: date, end_date: date) -> list[Paper]:
        queries = [_safe_query(query) for query in (interest.keywords[:8] or [interest.name])]
        queries = [query for query in queries if query]
        per_query = max(1, self.config.max_results_per_interest // max(len(queries), 1))
        papers: list[Paper] = []
        failures: list[str] = []
        for query in queries:
            try:
                papers.extend(self._fetch_query(query, start_date.year, end_date.year, per_query))
            except RuntimeError as exc:
                failures.append(str(exc))
            time.sleep(0.2)
        if failures and not papers:
            raise RuntimeError("; ".join(failures[:2]))
        return _dedupe(papers)[: self.config.max_results_per_interest]

    def fetch_all(self, start_date: date, end_date: date) -> list[Paper]:
        return []

    def _fetch_query(self, query: str, start_year: int, end_year: int, limit: int) -> list[Paper]:
        params = {"q": query, "format": "json", "h": str(max(1, min(limit, 100)))}
        url = f"{DBLP_API_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": "paperwatch/0.1 (dblp source)"})
        try:
            with urllib.request.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"dblp request failed with HTTP {exc.code} for query {query!r}; try simpler keywords"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"dblp request failed: {reason}") from exc
        hits = payload.get("result", {}).get("hits", {}).get("hit", [])
        if isinstance(hits, dict):
            hits = [hits]
        papers = [_parse_hit(hit) for hit in hits if isinstance(hit, dict)]
        return [paper for paper in papers if start_year <= paper.published_at.year <= end_year]


def _parse_hit(hit: dict) -> Paper:
    info = hit.get("info") or {}
    key = str(info.get("key") or hit.get("@id") or info.get("url") or info.get("title") or "")
    title = _clean_title(str(info.get("title") or "Untitled"))
    authors = _parse_authors(info.get("authors") or {})
    year = _parse_year(info.get("year"))
    doi = str(info.get("doi")) if info.get("doi") else None
    ee = info.get("ee")
    if isinstance(ee, list):
        url = str(ee[0]) if ee else ""
    else:
        url = str(ee or info.get("url") or "")
    if not url and doi:
        url = f"https://doi.org/{doi}"
    return Paper(
        source="dblp",
        paper_id=key,
        title=title,
        authors=authors,
        abstract="Abstract unavailable from dblp metadata.",
        published_at=datetime(year, 1, 1, tzinfo=timezone.utc),
        updated_at=None,
        url=url or f"https://dblp.org/rec/{urllib.parse.quote(key)}",
        pdf_url=None,
        doi=doi,
        venue=str(info.get("venue")) if info.get("venue") else None,
        categories=[str(info.get("type"))] if info.get("type") else [],
    )


def _parse_authors(authors_payload) -> list[str]:
    authors = authors_payload.get("author", []) if isinstance(authors_payload, dict) else authors_payload
    if isinstance(authors, str):
        return [authors]
    if isinstance(authors, dict):
        return [str(authors.get("text") or authors.get("#text") or "").strip()]
    result = []
    if isinstance(authors, list):
        for item in authors:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                result.append(str(item.get("text") or item.get("#text") or "").strip())
    return [item for item in result if item]


def _parse_year(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return date.today().year


def _clean_title(value: str) -> str:
    return value.rstrip(".").strip()


def _safe_query(value: str) -> str:
    cleaned = " ".join(urllib.parse.unquote(value).replace("-", " ").replace("_", " ").split())
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in cleaned)
    return " ".join(cleaned.split()[:8])


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
