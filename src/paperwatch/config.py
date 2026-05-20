from __future__ import annotations

import shutil
import tomllib
from pathlib import Path
from typing import Any

from paperwatch.models import (
    AiConfig,
    ArxivConfig,
    DblpConfig,
    EmbeddingConfig,
    FeishuConfig,
    Interest,
    InterestAiConfig,
    OpenAlexConfig,
    RankingConfig,
    ScheduleConfig,
    Settings,
    TranslationConfig,
)


DEFAULT_CONFIG = """timezone = "Asia/Shanghai"
daily_limit = 20
per_interest_limit = 10
database_path = "data/papers.sqlite"
digest_dir = "data/digests"

[schedule]
enabled = false
hour = 12
minute = 30
days = 1

[feishu]
enabled = false
send_on_schedule = true
webhook_url = ""
secret = ""
timeout_seconds = 15

[ranking]
mode = "keyword"
candidate_limit_per_interest = 40
# Modes:
# - "keyword": stable local ranker, no API key needed.
# - "embedding": semantic rerank using [embedding].
# - "ai": keyword ranking plus AI TL;DR/priority for selected papers.
# - "embedding_ai": semantic rerank plus AI TL;DR/priority.

[embedding]
api_key = ""
api_key_env = "RANKING_API_KEY"
base_url = "https://api.openai.com/v1"
model = "text-embedding-3-small"
timeout_seconds = 60

[ai]
api_key = ""
api_key_env = "TRANSLATION_API_KEY"
base_url = "https://api.openai.com/v1"
model = "gpt-4.1-mini"
language = "Chinese"
max_papers_per_interest = 10
timeout_seconds = 90

[digest_ai]
api_key = ""
api_key_env = "DIGEST_AI_API_KEY"
base_url = "https://api.openai.com/v1"
model = "gpt-4.1-mini"
language = "Chinese"
max_papers_per_interest = 10
timeout_seconds = 90

[translation]
enabled = true
language = "Chinese"
translate_title = true
translate_abstract = true
max_papers_per_run = 20

[interest_ai]
api_key = ""
api_key_env = "INTEREST_BUILDER_API_KEY"
base_url = "https://api.openai.com/v1"
model = "gpt-4.1-mini"
timeout_seconds = 90

[sources.arxiv]
enabled = true
fetch_mode = "search"
max_results_per_interest = 80
include_cross_list = true
request_timeout_seconds = 30
default_fetch_interests = ["CV Model Generation"]

[sources.openalex]
enabled = false
max_results_per_interest = 40
request_timeout_seconds = 30
mailto = ""

[sources.dblp]
enabled = false
max_results_per_interest = 40
request_timeout_seconds = 30

[[interests]]
name = "CV Model Generation"
description = "Computer vision generative models, including diffusion, autoregressive image generation, video generation, 3D generation, multimodal generation, controllable generation, and efficient generative modeling."
arxiv_categories = ["cs.CV", "cs.AI", "cs.LG", "eess.IV"]
keywords = [
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
  "3D generation",
  "text-to-3D",
  "multimodal generation",
  "visual generation",
  "autoregressive image",
  "flow matching",
  "rectified flow",
  "consistency model",
  "latent diffusion"
]
keyword_weights = {}
negative_keywords = [
  "medical image segmentation",
  "object detection only",
  "classification only"
]
"""


def load_settings(path: str | Path) -> Settings:
    config_path = Path(path)
    with config_path.open("rb") as f:
        raw = tomllib.load(f)

    sources = raw.get("sources", {})
    arxiv_raw = sources.get("arxiv", {})
    arxiv = ArxivConfig(
        enabled=bool(arxiv_raw.get("enabled", True)),
        fetch_mode=str(arxiv_raw.get("fetch_mode", "search")),
        max_results_per_interest=int(arxiv_raw.get("max_results_per_interest", 80)),
        include_cross_list=bool(arxiv_raw.get("include_cross_list", True)),
        request_timeout_seconds=int(arxiv_raw.get("request_timeout_seconds", 30)),
    )
    openalex_raw = sources.get("openalex", {})
    openalex = OpenAlexConfig(
        enabled=bool(openalex_raw.get("enabled", False)),
        max_results_per_interest=int(openalex_raw.get("max_results_per_interest", 40)),
        request_timeout_seconds=int(openalex_raw.get("request_timeout_seconds", 30)),
        mailto=str(openalex_raw.get("mailto", "")),
    )
    dblp_raw = sources.get("dblp", {})
    dblp = DblpConfig(
        enabled=bool(dblp_raw.get("enabled", False)),
        max_results_per_interest=int(dblp_raw.get("max_results_per_interest", 40)),
        request_timeout_seconds=int(dblp_raw.get("request_timeout_seconds", 30)),
    )
    ranking_raw = raw.get("ranking", {})
    ranking = RankingConfig(
        mode=str(ranking_raw.get("mode", "keyword")),
        candidate_limit_per_interest=int(ranking_raw.get("candidate_limit_per_interest", 40)),
    )
    embedding_raw = raw.get("embedding", {})
    embedding = EmbeddingConfig(
        api_key=str(embedding_raw.get("api_key", "")),
        api_key_env=str(embedding_raw.get("api_key_env", "OPENAI_API_KEY")),
        base_url=str(embedding_raw.get("base_url", "https://api.openai.com/v1")),
        model=str(embedding_raw.get("model", "text-embedding-3-small")),
        timeout_seconds=int(embedding_raw.get("timeout_seconds", 60)),
    )
    ai_raw = raw.get("ai", {})
    ai = AiConfig(
        api_key=str(ai_raw.get("api_key", "")),
        api_key_env=str(ai_raw.get("api_key_env", "OPENAI_API_KEY")),
        base_url=str(ai_raw.get("base_url", "https://api.openai.com/v1")),
        model=str(ai_raw.get("model", "gpt-4.1-mini")),
        language=str(ai_raw.get("language", "Chinese")),
        max_papers_per_interest=int(ai_raw.get("max_papers_per_interest", 10)),
        timeout_seconds=int(ai_raw.get("timeout_seconds", 90)),
    )
    digest_ai_raw = raw.get("digest_ai", ai_raw)
    digest_ai = AiConfig(
        api_key=str(digest_ai_raw.get("api_key", ai.api_key)),
        api_key_env=str(digest_ai_raw.get("api_key_env", ai.api_key_env)),
        base_url=str(digest_ai_raw.get("base_url", ai.base_url)),
        model=str(digest_ai_raw.get("model", ai.model)),
        language=str(digest_ai_raw.get("language", ai.language)),
        max_papers_per_interest=int(digest_ai_raw.get("max_papers_per_interest", ai.max_papers_per_interest)),
        timeout_seconds=int(digest_ai_raw.get("timeout_seconds", ai.timeout_seconds)),
    )
    interest_ai_raw = raw.get("interest_ai", {})
    interest_ai = InterestAiConfig(
        api_key=str(interest_ai_raw.get("api_key", ai.api_key)),
        api_key_env=str(interest_ai_raw.get("api_key_env", ai.api_key_env)),
        base_url=str(interest_ai_raw.get("base_url", ai.base_url)),
        model=str(interest_ai_raw.get("model", ai.model)),
        timeout_seconds=int(interest_ai_raw.get("timeout_seconds", ai.timeout_seconds)),
    )
    translation_raw = raw.get("translation", {})
    translation = TranslationConfig(
        enabled=bool(translation_raw.get("enabled", True)),
        language=str(translation_raw.get("language", "Chinese")),
        translate_title=bool(translation_raw.get("translate_title", True)),
        translate_abstract=bool(translation_raw.get("translate_abstract", True)),
        max_papers_per_run=int(translation_raw.get("max_papers_per_run", 20)),
    )
    schedule_raw = raw.get("schedule", {})
    schedule = ScheduleConfig(
        enabled=bool(schedule_raw.get("enabled", False)),
        hour=_parse_hour(schedule_raw.get("hour", 12)),
        minute=_parse_minute(schedule_raw.get("minute", 30)),
        days=max(1, int(schedule_raw.get("days", 1))),
    )
    feishu_raw = raw.get("feishu", {})
    feishu = FeishuConfig(
        enabled=bool(feishu_raw.get("enabled", False)),
        send_on_schedule=bool(feishu_raw.get("send_on_schedule", True)),
        webhook_url=str(feishu_raw.get("webhook_url", "")).strip(),
        secret=str(feishu_raw.get("secret", feishu_raw.get("sign_secret", ""))).strip(),
        timeout_seconds=max(1, int(feishu_raw.get("timeout_seconds", 15))),
        configured="feishu" in raw,
    )

    interests = [_parse_interest(item) for item in raw.get("interests", [])]
    if not interests:
        raise ValueError("config must define at least one [[interests]] section")
    default_fetch_interests = [str(x) for x in arxiv_raw.get("default_fetch_interests", [interest.name for interest in interests])]

    return Settings(
        timezone=str(raw.get("timezone", "Asia/Shanghai")),
        daily_limit=int(raw.get("daily_limit", 20)),
        per_interest_limit=_parse_optional_positive_int(raw.get("per_interest_limit", raw.get("daily_limit", 20))),
        database_path=str(raw.get("database_path", "data/papers.sqlite")),
        digest_dir=str(raw.get("digest_dir", "data/digests")),
        ranking=ranking,
        embedding=embedding,
        ai=ai,
        digest_ai=digest_ai,
        interest_ai=interest_ai,
        translation=translation,
        schedule=schedule,
        feishu=feishu,
        arxiv=arxiv,
        openalex=openalex,
        dblp=dblp,
        interests=interests,
        default_fetch_interests=default_fetch_interests,
    )


def write_default_config(output: str | Path, overwrite: bool = False) -> Path:
    out = Path(output)
    if out.exists() and not overwrite:
        raise FileExistsError(f"{out} already exists; pass --force to overwrite")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return out


def ensure_default_config(path: str | Path = "config.toml") -> Path:
    out = Path(path)
    if not out.exists():
        out.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return out


def copy_default_config_if_missing(source: str | Path, dest: str | Path) -> None:
    src = Path(source)
    dst = Path(dest)
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def _parse_interest(item: dict[str, Any]) -> Interest:
    keywords = _parse_keywords(item.get("keywords", []))
    return Interest(
        name=str(item["name"]),
        description=str(item.get("description", "")),
        keywords=keywords,
        keyword_weights=_parse_keyword_weights(item.get("keyword_weights", {}), keywords),
        negative_keywords=[str(x) for x in item.get("negative_keywords", [])],
        arxiv_categories=[str(x) for x in item.get("arxiv_categories", [])],
        seed_papers=[str(x) for x in item.get("seed_papers", [])],
    )


def _parse_optional_positive_int(value: Any) -> int | None:
    parsed = int(value)
    return parsed if parsed > 0 else None


def _parse_keywords(value: Any) -> list[str]:
    result: list[str] = []
    if not isinstance(value, list):
        return result
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("term", item.get("keyword", ""))).strip()
        else:
            text = str(item).strip()
        if text:
            result.append(text)
    return result


def _parse_keyword_weights(value: Any, keywords: list[str]) -> dict[str, float]:
    weights: dict[str, float] = {}
    if isinstance(value, dict):
        for key, raw_weight in value.items():
            term = str(key).strip()
            if not term:
                continue
            try:
                weight = float(raw_weight)
            except (TypeError, ValueError):
                continue
            if weight > 0:
                weights[term] = weight
    for keyword in keywords:
        weights.setdefault(keyword, 1.0)
    return weights


def _parse_hour(value: Any) -> int:
    hour = int(value)
    if hour < 0 or hour > 23:
        raise ValueError("schedule.hour must be between 0 and 23")
    return hour


def _parse_minute(value: Any) -> int:
    minute = int(value)
    if minute < 0 or minute > 59:
        raise ValueError("schedule.minute must be between 0 and 59")
    return minute
