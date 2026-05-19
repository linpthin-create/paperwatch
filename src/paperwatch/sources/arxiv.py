from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, time as dt_time, timezone

from paperwatch.models import ArxivConfig, Interest, Paper


ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
ARXIV_NS = {"arxiv": "http://arxiv.org/schemas/atom"}


class ArxivSource:
    def __init__(self, config: ArxivConfig) -> None:
        self.config = config

    def fetch(self, interest: Interest, start_date: date, end_date: date) -> list[Paper]:
        query = self._build_query(interest, start_date, end_date)
        return self.fetch_query(query)

    def fetch_all(self, start_date: date, end_date: date) -> list[Paper]:
        query = self._build_date_query(start_date, end_date)
        return self.fetch_query(query)

    def fetch_query(self, query: str) -> list[Paper]:
        params = {
            "search_query": query,
            "start": "0",
            "max_results": str(self.config.max_results_per_interest),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "paperwatch/0.1 (daily research paper watcher)"},
        )
        payload = self._open_with_retries(request)
        time.sleep(3.0)
        return self._parse_feed(payload)

    def _open_with_retries(self, request: urllib.request.Request) -> bytes:
        waits = [5, 15, 45]
        for attempt in range(len(waits) + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == len(waits):
                    raise RuntimeError(f"arXiv request failed with HTTP {exc.code}: {exc.reason}") from exc
                retry_after = exc.headers.get("Retry-After")
                wait_seconds = int(retry_after) if retry_after and retry_after.isdigit() else waits[attempt]
                time.sleep(wait_seconds)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt == len(waits):
                    reason = getattr(exc, "reason", exc)
                    raise RuntimeError(f"arXiv request failed: {reason}") from exc
                time.sleep(waits[attempt])
        raise RuntimeError("arXiv request failed after retries")

    def _build_query(self, interest: Interest, start_date: date, end_date: date) -> str:
        parts: list[str] = []
        if interest.arxiv_categories:
            category_terms = [f"cat:{category}" for category in interest.arxiv_categories]
            parts.append(_or_group(category_terms))

        if interest.keywords:
            keyword_terms = []
            for keyword in interest.keywords:
                escaped = _quote_phrase(keyword)
                keyword_terms.append(f'ti:"{escaped}"')
                keyword_terms.append(f'abs:"{escaped}"')
            parts.append(_or_group(keyword_terms))

        range_clause = (
            f"submittedDate:[{_format_arxiv_date(start_date, False)} "
            f"TO {_format_arxiv_date(end_date, True)}]"
        )
        parts.append(range_clause)
        return " AND ".join(f"({part})" for part in parts if part)

    def _build_date_query(self, start_date: date, end_date: date) -> str:
        return (
            f"submittedDate:[{_format_arxiv_date(start_date, False)} "
            f"TO {_format_arxiv_date(end_date, True)}]"
        )

    def _parse_feed(self, payload: bytes) -> list[Paper]:
        root = ET.fromstring(payload)
        papers: list[Paper] = []
        for entry in root.findall("atom:entry", ATOM_NS):
            paper_id = _short_id(_text(entry, "atom:id"))
            title = _clean_text(_text(entry, "atom:title"))
            abstract = _clean_text(_text(entry, "atom:summary"))
            authors = [
                _clean_text(author.findtext("atom:name", default="", namespaces=ATOM_NS))
                for author in entry.findall("atom:author", ATOM_NS)
            ]
            published = _parse_datetime(_text(entry, "atom:published"))
            updated_text = entry.findtext("atom:updated", default="", namespaces=ATOM_NS)
            updated = _parse_datetime(updated_text) if updated_text else None
            categories = [
                item.attrib.get("term", "")
                for item in entry.findall("atom:category", ATOM_NS)
                if item.attrib.get("term")
            ]
            pdf_url = None
            for link in entry.findall("atom:link", ATOM_NS):
                if link.attrib.get("title") == "pdf":
                    pdf_url = link.attrib.get("href")
                    break
            doi = entry.findtext("arxiv:doi", default=None, namespaces=ARXIV_NS)
            papers.append(
                Paper(
                    source="arxiv",
                    paper_id=paper_id,
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    published_at=published,
                    updated_at=updated,
                    url=_text(entry, "atom:id"),
                    pdf_url=pdf_url,
                    doi=doi,
                    venue=None,
                    categories=categories,
                )
            )
        return papers


def _or_group(terms: list[str]) -> str:
    return " OR ".join(terms)


def _quote_phrase(value: str) -> str:
    return value.replace('"', "").strip()


def _format_arxiv_date(value: date, end_of_day: bool) -> str:
    suffix = "2359" if end_of_day else "0000"
    return f"{value.year:04d}{value.month:02d}{value.day:02d}{suffix}"


def _text(entry: ET.Element, path: str) -> str:
    return entry.findtext(path, default="", namespaces=ATOM_NS).strip()


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _short_id(entry_id: str) -> str:
    tail = entry_id.rstrip("/").split("/")[-1]
    return tail.split("v")[0]


def to_date(value: datetime) -> date:
    return value.astimezone(timezone.utc).date()


def day_bounds(days: int, today: date | None = None) -> tuple[date, date]:
    current = today or datetime.combine(date.today(), dt_time.min).date()
    return current.fromordinal(current.toordinal() - max(days, 1)), current
