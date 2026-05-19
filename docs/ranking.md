# Ranking Plan

PaperWatch currently uses a stable local keyword ranker. The intended ranking stack is:

1. Candidate retrieval: source/category/date filters reduce the daily paper set.
2. Fast local scoring: title, abstract, category, and negative keyword matching.
3. Embedding rerank: compare each paper abstract against each interest description and optional seed papers.
4. AI digestion: ask an LLM to summarize and assign reading priority only for the selected papers per interest.

This hybrid design is better than sending every paper to an LLM:

- It is cheaper and faster.
- It avoids noisy source batches dominating the context window.
- It keeps a deterministic fallback when the API is unavailable.
- It allows each interest direction to have its own ranked list.

Recommended future config shape:

```toml
[ranking]
mode = "embedding_ai"
candidate_limit_per_interest = 40

[embedding]
provider = "openai"
model = "text-embedding-3-small"

[ai]
provider = "openai"
model = "gpt-4.1-mini"
language = "Chinese"
```

Current implementation uses OpenAI-compatible HTTP endpoints. The provider can be OpenAI, SiliconFlow, OneAPI, LiteLLM, a local proxy, or another compatible service.

Concrete modes:

- `keyword`: no API dependency, current default
- `embedding`: semantic rerank after keyword candidate scoring
- `ai`: keyword ranking plus AI TL;DR/priority
- `embedding_ai`: semantic rerank plus AI TL;DR/priority

API configuration can live directly in `config.toml`:

```toml
[embedding]
api_key = "sk-..."
base_url = "https://api.openai.com/v1"
model = "text-embedding-3-small"

[ai]
api_key = "sk-..."
base_url = "https://api.openai.com/v1"
model = "gpt-4.1-mini"
```

If `api_key` is empty, PaperWatch reads `api_key_env`.

The LLM output should not replace ranking completely. It should produce:

- TL;DR
- why it matches the interest
- novelty/read priority
- possible code/data links
- concerns, such as weak evaluation or only marginal relevance
