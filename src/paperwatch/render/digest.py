from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from paperwatch.ai import InsightKey, TranslationKey
from paperwatch.models import PaperInsight, PaperTranslation, ScoredPaper


def write_digest(
    scored: list[ScoredPaper],
    output_dir: str | Path,
    run_date: datetime | None = None,
    insights: dict[InsightKey, PaperInsight] | None = None,
    translations: dict[TranslationKey, PaperTranslation] | None = None,
    metadata: dict[str, str] | None = None,
    timestamped: bool = False,
    label: str | None = None,
) -> Path:
    now = run_date or datetime.now()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{now:%Y-%m-%d-%H%M%S}" if timestamped else f"{now:%Y-%m-%d}"
    if label:
        stem = f"{stem}-{_safe_label(label)}"
    path = out_dir / f"{stem}.md"
    path.write_text(
        render_markdown(scored, now, insights=insights, translations=translations, metadata=metadata),
        encoding="utf-8",
    )
    return path


def render_markdown(
    scored: list[ScoredPaper],
    run_date: datetime | None = None,
    insights: dict[InsightKey, PaperInsight] | None = None,
    translations: dict[TranslationKey, PaperTranslation] | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    now = run_date or datetime.now()
    lines = [
        f"# Daily Paper Digest - {now:%Y-%m-%d}",
        "",
        f"Total recommendations: {len(scored)}",
        "",
    ]
    if metadata:
        for key, value in metadata.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    if not scored:
        lines.append("No new matching papers found.")
        lines.append("")
        return "\n".join(lines)

    grouped: defaultdict[str, list[ScoredPaper]] = defaultdict(list)
    for item in scored:
        grouped[item.interest_name].append(item)

    for interest, items in grouped.items():
        lines.extend([f"## {interest}", ""])
        for index, item in enumerate(items, start=1):
            paper = item.paper
            authors = ", ".join(paper.authors[:4])
            if len(paper.authors) > 4:
                authors += ", et al."
            keywords = ", ".join(item.matched_keywords[:8]) or "category/description match"
            categories = ", ".join(paper.categories)
            insight = (insights or {}).get((item.interest_name, paper.source, paper.paper_id))
            translation = (translations or {}).get((item.interest_name, paper.source, paper.paper_id))
            is_unranked = item.interest_name == "All Papers" and item.score == 0 and not item.matched_keywords
            lines.extend(
                [
                    f"### {index}. {paper.title}",
                ]
            )
            if translation and translation.title:
                lines.append(f"### {translation.title}")
            lines.append("")
            if not is_unranked:
                lines.append(f"- Score: {item.score:.1f}")
            if item.semantic_score is not None:
                lines.append(f"- Semantic score: {item.semantic_score:.3f}")
            lines.extend(
                [
                    f"- Published: {paper.published_at.date().isoformat()}",
                    f"- Authors: {authors}",
                    f"- Categories: {categories}",
                    f"- Paper: {paper.url}",
                    f"- PDF: {paper.pdf_url or 'N/A'}",
                    "",
                ]
            )
            if not is_unranked:
                lines.insert(-3, f"- Matched: {keywords}")
            if insight:
                lines.extend(
                    [
                        f"- AI priority: {insight.priority or 'N/A'}",
                        "",
                        f"TL;DR: {insight.tldr}",
                        "",
                        f"Relevance: {insight.relevance}",
                        "",
                    ]
                )
            lines.extend(["Abstract:", "", paper.abstract, ""])
            if translation and translation.abstract:
                lines.extend(["摘要翻译:", "", translation.abstract, ""])
    return "\n".join(lines)


def _safe_label(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    return "-".join(part for part in cleaned.split("-") if part)[:60]
