from __future__ import annotations

from collections import defaultdict

from paperwatch.models import Interest, Paper, ScoredPaper


def score_papers_by_interest(papers: list[Paper], interests: list[Interest]) -> dict[str, list[ScoredPaper]]:
    grouped: dict[str, list[ScoredPaper]] = {}
    for interest in interests:
        scored = [score_paper(paper, interest) for paper in papers]
        grouped[interest.name] = sorted(
            [item for item in scored if _is_relevant_match(item, interest)],
            key=lambda item: (item.score, item.paper.published_at),
            reverse=True,
        )
    return grouped


def score_papers(papers: list[Paper], interests: list[Interest]) -> list[ScoredPaper]:
    best: dict[tuple[str, str], ScoredPaper] = {}
    for paper in papers:
        for interest in interests:
            scored = score_paper(paper, interest)
            if scored.score <= 0:
                continue
            if not _is_relevant_match(scored, interest):
                continue
            key = (paper.source, paper.paper_id)
            current = best.get(key)
            if current is None or scored.score > current.score:
                best[key] = scored
    return sorted(best.values(), key=lambda item: (item.score, item.paper.published_at), reverse=True)


def score_paper(paper: Paper, interest: Interest) -> ScoredPaper:
    title = paper.title.lower()
    abstract = paper.abstract.lower()
    categories = {item.lower() for item in paper.categories}
    matched: list[str] = []
    blocked: list[str] = []
    score = 0.0

    for keyword in interest.negative_keywords:
        needle = keyword.lower()
        if needle and (needle in title or needle in abstract):
            blocked.append(keyword)

    if blocked:
        return ScoredPaper(paper, interest.name, -100.0, matched, blocked)

    counts: defaultdict[str, float] = defaultdict(float)
    for keyword in interest.keywords:
        needle = keyword.lower()
        if not needle:
            continue
        weight = max(float(interest.keyword_weights.get(keyword, 1.0)), 0.0)
        if needle in title:
            counts[keyword] += 5.0 * weight
        if needle in abstract:
            counts[keyword] += 2.0 * weight

    for category in interest.arxiv_categories:
        if category.lower() in categories:
            score += 1.0

    for keyword, value in counts.items():
        matched.append(keyword)
        score += value

    if interest.description:
        for token in _important_tokens(interest.description):
            if token in title:
                score += 0.5
            elif token in abstract:
                score += 0.2

    return ScoredPaper(paper, interest.name, score, matched, blocked)


def _important_tokens(text: str) -> set[str]:
    stop = {"the", "and", "with", "including", "models", "model", "for", "your", "from"}
    return {
        token.strip(".,;:()[]{}").lower()
        for token in text.split()
        if len(token.strip(".,;:()[]{}")) >= 5 and token.lower() not in stop
    }


def _is_relevant_match(item: ScoredPaper, interest: Interest) -> bool:
    if item.score <= 0:
        return False
    if item.matched_keywords:
        return item.score >= 2.0
    return not interest.keywords and item.score > 0
