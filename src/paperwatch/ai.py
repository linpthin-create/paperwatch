from __future__ import annotations

import json
import sys
from collections import defaultdict

from paperwatch.clients import OpenAICompatibleClient
from paperwatch.models import AiConfig, InterestAiConfig, PaperInsight, PaperTranslation, ScoredPaper, TranslationConfig

InsightKey = tuple[str, str, str]
TranslationKey = tuple[str, str, str]


def generate_insights(
    selected: list[ScoredPaper],
    config: AiConfig,
    client: OpenAICompatibleClient | None = None,
) -> dict[InsightKey, PaperInsight]:
    api = client or OpenAICompatibleClient(
        config.api_key_env,
        config.base_url,
        config.timeout_seconds,
        api_key=config.api_key,
    )
    if not api.available:
        raise RuntimeError(f"API key is not configured; AI insights skipped")

    grouped: defaultdict[str, list[ScoredPaper]] = defaultdict(list)
    for item in selected:
        grouped[item.interest_name].append(item)

    insights: dict[InsightKey, PaperInsight] = {}
    for interest_name, items in grouped.items():
        batch = items[: config.max_papers_per_interest]
        prompt = _build_prompt(interest_name, batch, config.language)
        content = api.chat(
            config.model,
            [
                {"role": "system", "content": "You are a precise research-paper triage assistant. Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        for paper_id, insight in _parse_insights(content).items():
            for item in batch:
                if item.paper.paper_id == paper_id:
                    insights[(item.interest_name, item.paper.source, item.paper.paper_id)] = insight
                    break
    return insights


def generate_translations(
    selected: list[ScoredPaper],
    ai_config: AiConfig,
    translation_config: TranslationConfig,
    client: OpenAICompatibleClient | None = None,
) -> dict[TranslationKey, PaperTranslation]:
    if not translation_config.enabled:
        return {}
    api = client or OpenAICompatibleClient(
        ai_config.api_key_env,
        ai_config.base_url,
        ai_config.timeout_seconds,
        api_key=ai_config.api_key,
    )
    if not api.available:
        raise RuntimeError("API key is not configured; translations skipped")

    batch_size = max(int(translation_config.max_papers_per_run), 1)
    if not selected:
        return {}
    translations: dict[TranslationKey, PaperTranslation] = {}
    failures: list[str] = []
    for start in range(0, len(selected), batch_size):
        batch = selected[start : start + batch_size]
        prompt = _build_translation_prompt(batch, translation_config)
        try:
            content = api.chat(
                ai_config.model,
                [
                    {"role": "system", "content": "You are a precise academic translator. Return valid JSON only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
            parsed = _parse_translations(content)
        except RuntimeError as exc:
            failures.append(str(exc))
            continue
        for item in batch:
            translated = parsed.get(item.paper.paper_id)
            if translated:
                translations[(item.interest_name, item.paper.source, item.paper.paper_id)] = translated
    if failures and not translations:
        raise RuntimeError("; ".join(failures))
    for failure in failures:
        print(f"Warning: translation batch failed: {failure}", file=sys.stderr)
    return translations


def test_chat_config(config: AiConfig | InterestAiConfig, client: OpenAICompatibleClient | None = None) -> str:
    api = client or OpenAICompatibleClient(
        config.api_key_env,
        config.base_url,
        config.timeout_seconds,
        api_key=config.api_key,
    )
    if not api.available:
        raise RuntimeError("API key is not configured")
    return api.chat(
        config.model,
        [
            {"role": "system", "content": "Reply with exactly: ok"},
            {"role": "user", "content": "Connectivity test."},
        ],
        temperature=0,
    ).strip()


def generate_interest_from_paper(
    paper_text: str,
    config: InterestAiConfig,
    client: OpenAICompatibleClient | None = None,
) -> str:
    api = client or OpenAICompatibleClient(
        config.api_key_env,
        config.base_url,
        config.timeout_seconds,
        api_key=config.api_key,
    )
    if not api.available:
        raise RuntimeError("API key is not configured; interest generation skipped")
    content = api.chat(
        config.model,
        [
            {"role": "system", "content": "You convert research paper text into PaperWatch interest configuration. Return valid JSON only."},
            {"role": "user", "content": _build_interest_prompt(paper_text)},
        ],
        temperature=0.2,
    )
    payload = _parse_interest_payload(content)
    return _interest_payload_to_toml(payload)


def _build_prompt(interest_name: str, items: list[ScoredPaper], language: str) -> str:
    papers = []
    for item in items:
        paper = item.paper
        papers.append(
            {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "abstract": paper.abstract[:2500],
                "categories": paper.categories,
                "matched_keywords": item.matched_keywords,
                "score": item.score,
            }
        )
    return (
        f"Interest direction: {interest_name}\n"
        f"Language: {language}\n"
        "For each paper, judge relevance to the interest direction and produce concise reading guidance.\n"
        "Return a JSON object whose keys are paper_id and values have exactly these string fields: "
        "tldr, relevance, priority. priority must be one of High, Medium, Low.\n"
        f"Papers:\n{json.dumps(papers, ensure_ascii=False)}"
    )


def _build_translation_prompt(items: list[ScoredPaper], config: TranslationConfig) -> str:
    papers = []
    for item in items:
        papers.append(
            {
                "paper_id": item.paper.paper_id,
                "title": item.paper.title,
                "abstract": item.paper.abstract,
            }
        )
    fields = []
    if config.translate_title:
        fields.append("title")
    if config.translate_abstract:
        fields.append("abstract")
    return (
        f"Translate the requested fields into {config.language}.\n"
        "Keep technical terms accurate and preserve acronyms such as VLM, RLHF, Diffusion, Transformer when appropriate.\n"
        "Return a JSON object whose keys are paper_id and values are objects with these string fields: "
        f"{', '.join(fields)}.\n"
        "Do not add explanations outside JSON.\n"
        f"Papers:\n{json.dumps(papers, ensure_ascii=False)}"
    )


def _build_interest_prompt(paper_text: str) -> str:
    return (
        "Given the following single paper, multiple papers, or research notes, infer one reusable research-interest direction for paper monitoring.\n"
        "Infer the stable research area the user likely wants to follow, not just the exact method, dataset, benchmark, or task of the seed paper.\n"
        "Balance three levels: the application/domain area, the technical problem family, and representative methods.\n"
        "Avoid overfitting to one paper title; include adjacent terminology that would catch meaningful future work in the same field.\n"
        "Do not make the direction so broad that it becomes a generic category such as all computer vision, all robotics, or all LLMs.\n"
        "Return JSON with exactly these fields:\n"
        "name: short English name;\n"
        "description: one sentence that states the field/domain and the reusable monitoring scope;\n"
        "arxiv_categories: array of arXiv category strings;\n"
        "keywords: 12 to 24 precise English keyword phrases covering domain terms, problem-family terms, method terms, and dataset/evaluation terms when relevant;\n"
        "negative_keywords: 0 to 8 phrases for obvious false positives;\n"
        "seed_papers: array, include the given title if present.\n"
        "Prefer useful search keywords over overly broad words, but include the true parent field when it is needed to retrieve future work.\n"
        f"Paper text:\n{paper_text[:120000]}"
    )


def _parse_insights(content: str) -> dict[str, PaperInsight]:
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("AI response did not contain a JSON object")
    payload = json.loads(content[start : end + 1])
    result: dict[str, PaperInsight] = {}
    for paper_id, item in payload.items():
        if not isinstance(item, dict):
            continue
        result[str(paper_id)] = PaperInsight(
            tldr=str(item.get("tldr", "")).strip(),
            relevance=str(item.get("relevance", "")).strip(),
            priority=str(item.get("priority", "")).strip(),
        )
    return result


def _parse_translations(content: str) -> dict[str, PaperTranslation]:
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("AI response did not contain a JSON object")
    payload = json.loads(content[start : end + 1])
    result: dict[str, PaperTranslation] = {}
    for paper_id, item in payload.items():
        if not isinstance(item, dict):
            continue
        result[str(paper_id)] = PaperTranslation(
            title=str(item.get("title", "")).strip(),
            abstract=str(item.get("abstract", "")).strip(),
        )
    return result


def _parse_interest_payload(content: str) -> dict:
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("AI response did not contain a JSON object")
    payload = json.loads(content[start : end + 1])
    required = ["name", "description", "arxiv_categories", "keywords", "negative_keywords", "seed_papers"]
    for key in required:
        if key not in payload:
            raise RuntimeError(f"AI response missing field: {key}")
    return payload


def _interest_payload_to_toml(payload: dict) -> str:
    return "\n".join(
        [
            "[[interests]]",
            f'name = "{_toml_escape(str(payload["name"]))}"',
            f'description = "{_toml_escape(str(payload["description"]))}"',
            f"arxiv_categories = {_toml_list(payload.get('arxiv_categories', []))}",
            f"seed_papers = {_toml_list(payload.get('seed_papers', []))}",
            f"keywords = {_toml_list(payload.get('keywords', []))}",
            f"negative_keywords = {_toml_list(payload.get('negative_keywords', []))}",
            "",
        ]
    )


def _toml_list(values) -> str:
    return "[" + ", ".join(f'"{_toml_escape(str(value))}"' for value in values) + "]"


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
