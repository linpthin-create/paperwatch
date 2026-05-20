from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, time as dt_time, timezone

from paperwatch.models import ArxivConfig, Interest, Paper


ARXIV_OAI_URL = "https://export.arxiv.org/oai2"
OAI_NS = {"oai": "http://www.openarchives.org/OAI/2.0/"}
ARXIV_OAI_NS = {"ax": "http://arxiv.org/OAI/arXiv/"}


class ArxivOaiSource:
    def __init__(self, config: ArxivConfig) -> None:
        self.config = config

    def fetch(self, interest: Interest, start_date: date, end_date: date) -> list[Paper]:
        return self.fetch_all(start_date, end_date)

    def fetch_all(self, start_date: date, end_date: date) -> list[Paper]:
        papers: list[Paper] = []
        token = ""
        while True:
            payload = self._fetch_page(start_date, end_date, token)
            root = ET.fromstring(payload)
            error = root.find("oai:error", OAI_NS)
            if error is not None:
                code = error.attrib.get("code", "unknown")
                if code == "noRecordsMatch":
                    return papers
                raise RuntimeError(f"arXiv OAI request failed: {code}: {_clean_text(error.text or '')}")
            papers.extend(self._parse_records(root))
            token_el = root.find(".//oai:resumptionToken", OAI_NS)
            token = (token_el.text or "").strip() if token_el is not None else ""
            if not token:
                return papers
            time.sleep(3.0)

    def _fetch_page(self, start_date: date, end_date: date, token: str = "") -> bytes:
        if token:
            params = {"verb": "ListRecords", "resumptionToken": token}
        else:
            params = {
                "verb": "ListRecords",
                "metadataPrefix": "arXiv",
                "from": start_date.isoformat(),
                "until": end_date.isoformat(),
            }
        url = f"{ARXIV_OAI_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": "paperwatch/0.1 (arxiv oai daily source)"})
        try:
            with urllib.request.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"arXiv OAI request failed with HTTP {exc.code}: {detail[:200]}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"arXiv OAI request failed: {reason}") from exc

    def _parse_records(self, root: ET.Element) -> list[Paper]:
        papers: list[Paper] = []
        for record in root.findall(".//oai:record", OAI_NS):
            metadata = record.find("oai:metadata", OAI_NS)
            if metadata is None:
                continue
            item = metadata.find("ax:arXiv", ARXIV_OAI_NS)
            if item is None:
                continue
            paper_id = _text(item, "ax:id")
            if not paper_id:
                continue
            created = _parse_date(_text(item, "ax:created"))
            updated_text = _text(item, "ax:updated")
            updated = _parse_date(updated_text) if updated_text else None
            categories = _text(item, "ax:categories").split()
            papers.append(
                Paper(
                    source="arxiv",
                    paper_id=paper_id.split("v")[0],
                    title=_clean_text(_text(item, "ax:title")),
                    authors=_parse_authors(item),
                    abstract=_clean_text(_text(item, "ax:abstract")),
                    published_at=created,
                    updated_at=updated,
                    url=f"https://arxiv.org/abs/{paper_id}",
                    pdf_url=f"https://arxiv.org/pdf/{paper_id}",
                    doi=_text(item, "ax:doi") or None,
                    venue=_text(item, "ax:journal-ref") or None,
                    categories=categories,
                )
            )
        return papers


def _parse_authors(item: ET.Element) -> list[str]:
    authors = []
    for author in item.findall(".//ax:author", ARXIV_OAI_NS):
        forenames = _clean_text(author.findtext("ax:forenames", default="", namespaces=ARXIV_OAI_NS))
        keyname = _clean_text(author.findtext("ax:keyname", default="", namespaces=ARXIV_OAI_NS))
        name = " ".join(part for part in [forenames, keyname] if part)
        if name:
            authors.append(name)
    return authors


def _text(entry: ET.Element, path: str) -> str:
    return entry.findtext(path, default="", namespaces=ARXIV_OAI_NS).strip()


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _parse_date(value: str) -> datetime:
    if not value:
        return datetime.combine(date.today(), dt_time.min, tzinfo=timezone.utc)
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
