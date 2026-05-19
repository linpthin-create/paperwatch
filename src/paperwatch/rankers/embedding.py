from __future__ import annotations

import math
from dataclasses import replace

from paperwatch.clients import OpenAICompatibleClient
from paperwatch.models import EmbeddingConfig, Interest, ScoredPaper


def rerank_by_embedding(
    scored_by_interest: dict[str, list[ScoredPaper]],
    interests: list[Interest],
    config: EmbeddingConfig,
    candidate_limit: int,
    client: OpenAICompatibleClient | None = None,
) -> dict[str, list[ScoredPaper]]:
    api = client or OpenAICompatibleClient(
        config.api_key_env,
        config.base_url,
        config.timeout_seconds,
        api_key=config.api_key,
    )
    if not api.available:
        raise RuntimeError(f"API key is not configured; embedding rerank skipped")

    interest_by_name = {interest.name: interest for interest in interests}
    result: dict[str, list[ScoredPaper]] = {}
    for name, items in scored_by_interest.items():
        interest = interest_by_name[name]
        candidates = items[:candidate_limit]
        if not candidates:
            result[name] = []
            continue
        texts = [_interest_text(interest)] + [_paper_text(item) for item in candidates]
        vectors = api.embeddings(config.model, texts)
        query_vector = vectors[0]
        reranked = []
        for item, vector in zip(candidates, vectors[1:], strict=True):
            semantic = _cosine(query_vector, vector)
            combined = item.score + semantic * 20.0
            reranked.append(replace(item, score=combined, semantic_score=semantic))
        result[name] = sorted(reranked, key=lambda item: (item.score, item.paper.published_at), reverse=True)
    return result


def _interest_text(interest: Interest) -> str:
    parts = [
        interest.name,
        interest.description,
        "Keywords: " + ", ".join(interest.keywords),
        "Seed papers: " + " ".join(interest.seed_papers),
    ]
    return "\n".join(part for part in parts if part.strip())


def _paper_text(item: ScoredPaper) -> str:
    paper = item.paper
    return "\n".join(
        [
            paper.title,
            "Categories: " + ", ".join(paper.categories),
            paper.abstract,
        ]
    )


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
