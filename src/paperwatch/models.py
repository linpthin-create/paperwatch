from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Interest:
    name: str
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)
    arxiv_categories: list[str] = field(default_factory=list)
    seed_papers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ArxivConfig:
    enabled: bool = True
    max_results_per_interest: int = 80
    include_cross_list: bool = True
    request_timeout_seconds: int = 30


@dataclass(frozen=True)
class OpenAlexConfig:
    enabled: bool = False
    max_results_per_interest: int = 40
    request_timeout_seconds: int = 30
    mailto: str = ""


@dataclass(frozen=True)
class DblpConfig:
    enabled: bool = False
    max_results_per_interest: int = 40
    request_timeout_seconds: int = 30


@dataclass(frozen=True)
class RankingConfig:
    mode: str = "keyword"
    candidate_limit_per_interest: int = 40


@dataclass(frozen=True)
class EmbeddingConfig:
    api_key: str = ""
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = "https://api.openai.com/v1"
    model: str = "text-embedding-3-small"
    timeout_seconds: int = 60


@dataclass(frozen=True)
class AiConfig:
    api_key: str = ""
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4.1-mini"
    language: str = "Chinese"
    max_papers_per_interest: int = 10
    timeout_seconds: int = 90


@dataclass(frozen=True)
class InterestAiConfig:
    api_key: str = ""
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4.1-mini"
    timeout_seconds: int = 90


@dataclass(frozen=True)
class TranslationConfig:
    enabled: bool = True
    language: str = "Chinese"
    translate_title: bool = True
    translate_abstract: bool = True
    max_papers_per_run: int = 20


@dataclass(frozen=True)
class ScheduleConfig:
    enabled: bool = False
    hour: int = 12
    minute: int = 30
    days: int = 1


@dataclass(frozen=True)
class FeishuConfig:
    enabled: bool = False
    send_on_schedule: bool = True
    webhook_url: str = ""
    secret: str = ""
    timeout_seconds: int = 15
    configured: bool = True


@dataclass(frozen=True)
class Settings:
    timezone: str
    daily_limit: int
    per_interest_limit: int | None
    database_path: str
    digest_dir: str
    ranking: RankingConfig
    embedding: EmbeddingConfig
    ai: AiConfig
    digest_ai: AiConfig
    interest_ai: InterestAiConfig
    translation: TranslationConfig
    schedule: ScheduleConfig
    feishu: FeishuConfig
    arxiv: ArxivConfig
    openalex: OpenAlexConfig
    dblp: DblpConfig
    interests: list[Interest]
    default_fetch_interests: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Paper:
    source: str
    paper_id: str
    title: str
    authors: list[str]
    abstract: str
    published_at: datetime
    updated_at: datetime | None
    url: str
    pdf_url: str | None = None
    doi: str | None = None
    venue: str | None = None
    categories: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScoredPaper:
    paper: Paper
    interest_name: str
    score: float
    matched_keywords: list[str]
    blocked_keywords: list[str]
    semantic_score: float | None = None


@dataclass(frozen=True)
class PaperInsight:
    tldr: str
    relevance: str
    priority: str


@dataclass(frozen=True)
class PaperTranslation:
    title: str = ""
    abstract: str = ""
