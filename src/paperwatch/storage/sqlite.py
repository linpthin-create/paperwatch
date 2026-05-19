from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from paperwatch.models import Paper, ScoredPaper


class PaperStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def save_papers(self, papers: list[Paper]) -> int:
        inserted = 0
        for paper in papers:
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO papers (
                    source, paper_id, title, authors_json, abstract, published_at,
                    updated_at, url, pdf_url, doi, venue, categories_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper.source,
                    paper.paper_id,
                    paper.title,
                    json.dumps(paper.authors, ensure_ascii=False),
                    paper.abstract,
                    paper.published_at.isoformat(),
                    paper.updated_at.isoformat() if paper.updated_at else None,
                    paper.url,
                    paper.pdf_url,
                    paper.doi,
                    paper.venue,
                    json.dumps(paper.categories, ensure_ascii=False),
                ),
            )
            inserted += cursor.rowcount
        self.conn.commit()
        return inserted

    def filter_unsent(self, scored: list[ScoredPaper]) -> list[ScoredPaper]:
        result: list[ScoredPaper] = []
        for item in scored:
            row = self.conn.execute(
                """
                SELECT 1
                FROM paper_deliveries
                WHERE source = ? AND paper_id = ? AND interest_name = ?
                """,
                (item.paper.source, item.paper.paper_id, item.interest_name),
            ).fetchone()
            if row is None:
                result.append(item)
        return result

    def mark_sent(self, scored: list[ScoredPaper], digest_path: str) -> None:
        for item in scored:
            self.conn.execute(
                """
                UPDATE papers
                SET sent_at = datetime('now'), last_score = ?, last_interest = ?, digest_path = ?
                WHERE source = ? AND paper_id = ?
                """,
                (
                    item.score,
                    item.interest_name,
                    digest_path,
                    item.paper.source,
                    item.paper.paper_id,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO paper_deliveries (
                    source, paper_id, interest_name, sent_at, score, digest_path
                ) VALUES (?, ?, ?, datetime('now'), ?, ?)
                ON CONFLICT(source, paper_id, interest_name)
                DO UPDATE SET
                    sent_at = excluded.sent_at,
                    score = excluded.score,
                    digest_path = excluded.digest_path
                """,
                (
                    item.paper.source,
                    item.paper.paper_id,
                    item.interest_name,
                    item.score,
                    digest_path,
                ),
            )
        self.conn.commit()

    def recent_papers(self, limit: int = 300) -> list[Paper]:
        rows = self.conn.execute(
            """
            SELECT source, paper_id, title, authors_json, abstract, published_at, updated_at,
                   url, pdf_url, doi, venue, categories_json
            FROM papers
            ORDER BY published_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_paper(row) for row in rows]

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                paper_id TEXT NOT NULL,
                title TEXT NOT NULL,
                authors_json TEXT NOT NULL,
                abstract TEXT NOT NULL,
                published_at TEXT NOT NULL,
                updated_at TEXT,
                url TEXT NOT NULL,
                pdf_url TEXT,
                doi TEXT,
                venue TEXT,
                categories_json TEXT NOT NULL,
                sent_at TEXT,
                last_score REAL,
                last_interest TEXT,
                digest_path TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(source, paper_id)
            )
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_sent_at ON papers(sent_at)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_published_at ON papers(published_at)")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_deliveries (
                source TEXT NOT NULL,
                paper_id TEXT NOT NULL,
                interest_name TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                score REAL,
                digest_path TEXT,
                PRIMARY KEY(source, paper_id, interest_name)
            )
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_deliveries_sent_at ON paper_deliveries(sent_at)")
        self.conn.execute(
            """
            INSERT OR IGNORE INTO paper_deliveries (
                source, paper_id, interest_name, sent_at, score, digest_path
            )
            SELECT source, paper_id, last_interest, sent_at, last_score, digest_path
            FROM papers
            WHERE sent_at IS NOT NULL AND last_interest IS NOT NULL AND last_interest != ''
            """
        )
        self.conn.commit()


def _row_to_paper(row: sqlite3.Row) -> Paper:
    return Paper(
        source=row["source"],
        paper_id=row["paper_id"],
        title=row["title"],
        authors=json.loads(row["authors_json"]),
        abstract=row["abstract"],
        published_at=datetime.fromisoformat(row["published_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        url=row["url"],
        pdf_url=row["pdf_url"],
        doi=row["doi"],
        venue=row["venue"],
        categories=json.loads(row["categories_json"]),
    )
