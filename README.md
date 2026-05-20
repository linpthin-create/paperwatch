# PaperWatch

PaperWatch is a local Web UI for tracking new research papers. It fetches papers from arXiv, OpenAlex, and dblp, ranks them by your interests, writes Markdown digests, can translate results, and can send reports to Feishu.

## Quick Start

Install directly from GitHub and open the Web UI:

```bash
python3 -m pip install "git+https://github.com/linpthin-create/paperwatch.git"
paperwatch ui --open
```

This install command needs outbound HTTPS access to GitHub. If your macOS firewall, company proxy, campus network, or Python environment blocks network installs, clone or download the repository first, then install locally:

```bash
git clone https://github.com/linpthin-create/paperwatch.git
cd paperwatch
python3 -m pip install -e .
paperwatch ui --open
```

The browser opens:

```text
http://127.0.0.1:8765
```

That is the main app. Use the `Config` page to edit interests, sources, translation APIs, Feishu, and scheduled fetch settings. Use the `Digests` page to view reports and manually send a report to Feishu.

If `paperwatch ui --open` cannot open the browser automatically, start the UI and open the address manually:

```bash
paperwatch ui
```

Then visit `http://127.0.0.1:8765`.

PaperWatch creates a clean `config.toml` automatically on first run. It does not ship with any API keys or Feishu webhook. Fetching papers and calling AI/translation APIs also require outbound HTTPS access to the selected services.

## Fast Setup In The UI

1. Open `Config`.
2. Add or edit your `Interests`.
3. Choose paper `Sources`, such as arXiv, OpenAlex, and dblp.
4. Optional: configure `Translation API`, `Digest AI API`, `Ranking Embedding API`, and `Interest Builder API`.
5. Optional: configure `Feishu`.
6. Optional: configure `Schedule`, then click `Install on this PC`.
7. Click `Run fetch` from the left panel to generate a report immediately.

## Features

- Local web UI for configuration, manual fetches, digest preview, deletion, and manual Feishu sending.
- Multiple paper interests, each with its own description, arXiv categories, positive keywords, and negative keywords.
- Multi-interest automatic fetches: select several daily interests and generate one report per interest.
- Multi-source fetches: arXiv, OpenAlex, and dblp can be selected independently.
- Source connectivity tests from the Config page.
- Ranking modes: local keyword, embedding rerank, AI digest, or embedding plus AI digest.
- Separate API settings for translation, digest AI, ranking embeddings, and interest building.
- Interest Builder: generate or refine an interest configuration from a paper title and abstract.
- Markdown digest output under `data/digests/`.
- SQLite storage for fetched papers and sent status under `data/papers.sqlite`.
- Feishu custom-bot notifications for scheduled runs and manual digest sending.

## Local Development Install

From the repository:

```bash
python3 -m pip install -e .
paperwatch ui
```

If you do not want to install the package, run commands with `PYTHONPATH=src`:

```bash
PYTHONPATH=src python3 -m paperwatch ui
PYTHONPATH=src python3 -m paperwatch run --days 1
```

Create a default config:

```bash
paperwatch init-config --output config.toml
```

## Build A Wheel

Build a wheel:

```bash
python3 -m pip wheel . -w dist --no-deps --no-build-isolation
```

Install the built wheel:

```bash
python3 -m pip install dist/paperwatch-0.1.0-py3-none-any.whl
```

After installation, the command-line entry point is:

```bash
paperwatch --help
```

## Common Commands

Start the local UI:

```bash
paperwatch ui --open
```

Run a scheduled-style daily fetch for yesterday:

```bash
paperwatch run --days 1
```

Run the last seven complete days:

```bash
paperwatch run --days 7 --limit 10
```

Run a date range:

```bash
paperwatch run --start-date 2026-05-01 --end-date 2026-05-07
```

Run selected interests:

```bash
paperwatch run --interests "CV Model Generation" "Robot Learning"
```

Fetch without ranking:

```bash
paperwatch run --interest none --timestamped --label all-papers
```

Useful flags:

- `--config`: path to the TOML config file.
- `--days`: number of complete days ending yesterday.
- `--start-date` / `--end-date`: inclusive manual backfill range.
- `--interest`: one interest name, or `none` for unranked fetch.
- `--interests`: multiple interest names.
- `--ranking-mode`: one-run override for ranking mode.
- `--limit`: maximum papers per interest.
- `--timestamped`: write a timestamped digest instead of the scheduled filename.
- `--include-sent`: include papers already marked as sent.
- `--no-mark-sent`: render without updating sent status.

## Web UI

Start the UI and open `http://127.0.0.1:8765`:

```bash
paperwatch ui --host 127.0.0.1 --port 8765
```

The UI has two main pages:

- `Digests`: view Markdown reports, delete a report, and send the selected report to Feishu.
- `Config`: edit automatic fetch settings, sources, interests, ranking, translation, and API settings.

Manual fetches run in the background. The UI shows progress, polls the active run, and refreshes the digest list after a successful run.

## Configuration

Main limits and paths:

```toml
timezone = "Asia/Shanghai"
daily_limit = 20
per_interest_limit = 10
database_path = "data/papers.sqlite"
digest_dir = "data/digests"
```

`per_interest_limit` controls the scheduled automatic output size per interest. In the UI, a blank manual limit means no maximum for that manual run.

## Automatic Fetch

The schedule itself is configured separately from the interest list:

```toml
[schedule]
enabled = true
hour = 12
minute = 30
days = 1
```

`hour` and `minute` use local machine time. `days = 1` means the run fetches yesterday's papers; larger values fetch more complete days ending yesterday.

Daily interests are stored in the config as `default_fetch_interests`:

```toml
[sources.arxiv]
enabled = true
max_results_per_interest = 80
include_cross_list = true
request_timeout_seconds = 30
default_fetch_interests = ["CV Model Generation", "Robot Learning"]
```

The UI exposes this as a check-list. Selecting several interests generates separate reports in one run.

After changing the schedule in the UI, click `Install on this PC` in Config -> Schedule, or run:

```bash
paperwatch schedule install --config config.toml
```

Each computer needs its own local schedule install because the generated job contains that computer's Python executable, config path, working directory, and log path.

## Sources

Enable or disable each source:

```toml
[sources.arxiv]
enabled = true
max_results_per_interest = 80
include_cross_list = true
request_timeout_seconds = 30

[sources.openalex]
enabled = false
max_results_per_interest = 40
request_timeout_seconds = 30
mailto = ""

[sources.dblp]
enabled = false
max_results_per_interest = 40
request_timeout_seconds = 30
```

Notes:

- arXiv is usually the most stable source for daily preprints.
- OpenAlex gives broader scholarly coverage and can find journal or conference records.
- dblp is useful for computer science publication metadata, but its public search endpoint can be intermittent and does not support a meaningful unranked "fetch all" mode.
- Setting `mailto` for OpenAlex is recommended for polite API usage.

Recommended additional sources to consider later:

- Crossref, for DOI-centered publisher metadata.
- Semantic Scholar, for citation-aware ranking and paper recommendations.
- PubMed, if biomedical or medical AI topics matter.
- IEEE Xplore, ACM Digital Library, or DBLP venue feeds, if you need formal venue coverage beyond preprints.

## Interests

Each interest is a TOML block:

```toml
[[interests]]
name = "CV Model Generation"
description = "Computer vision generative models, including diffusion, image generation, video generation, 3D generation, and multimodal generation."
arxiv_categories = ["cs.CV", "cs.AI", "cs.LG", "eess.IV"]
keywords = [
  "image generation",
  "video generation",
  "text-to-image",
  "diffusion model",
  "flow matching"
]
keyword_weights = {
  "image generation" = 2.5,
  "video generation" = 2.0,
  "text-to-image" = 1.5,
  "diffusion model" = 1.5,
  "flow matching" = 1.0
}
negative_keywords = [
  "medical image segmentation",
  "classification only"
]
```

The local ranker uses keyword matches, keyword weights, category matches, and negative keywords. In the UI, edit keywords as `keyword | weight`, one per line. Higher weights make a keyword count more strongly in ranking; omitted weights default to `1.0`. For configured interests with keywords, PaperWatch requires real keyword evidence so unrelated papers from a broad source query are less likely to appear.

The Config page supports adding, editing, deleting, and AI-building interests.

## Ranking

Ranking mode is configured here:

```toml
[ranking]
mode = "keyword"
candidate_limit_per_interest = 40
```

Modes:

- `keyword`: local deterministic ranking, no API key required.
- `embedding`: keyword candidates plus semantic reranking through `[embedding]`.
- `ai`: keyword ranking plus digest AI summaries through `[digest_ai]`.
- `embedding_ai`: semantic reranking plus digest AI summaries.

Ranking embedding API:

```toml
[embedding]
api_key = ""
api_key_env = "OPENAI_API_KEY"
base_url = "https://api.openai.com/v1"
model = "text-embedding-3-small"
timeout_seconds = 60
```

Digest AI API:

```toml
[digest_ai]
api_key = ""
api_key_env = "OPENAI_API_KEY"
base_url = "https://api.openai.com/v1"
model = "gpt-4.1-mini"
language = "Chinese"
max_papers_per_interest = 10
timeout_seconds = 90
```

The APIs are OpenAI-compatible HTTP endpoints. They can point to OpenAI, a proxy, LiteLLM, OneAPI, SiliconFlow, or another compatible service.

## Translation

Translation is separate from digest AI:

```toml
[translation]
enabled = true
language = "Chinese"
translate_title = true
translate_abstract = true
max_papers_per_run = 20

[ai]
api_key = ""
api_key_env = "OPENAI_API_KEY"
base_url = "https://api.openai.com/v1"
model = "gpt-4.1-mini"
language = "Chinese"
max_papers_per_interest = 10
timeout_seconds = 90
```

`[ai]` is the Translation API. If `api_key` is empty, PaperWatch reads the environment variable named by `api_key_env`.

## Interest Builder API

The Interest Builder has its own API block:

```toml
[interest_ai]
api_key = ""
api_key_env = "OPENAI_API_KEY"
base_url = "https://api.openai.com/v1"
model = "gpt-4.1-mini"
timeout_seconds = 90
```

Use it from Config -> Interests by pasting a paper title and abstract. The generated interest should describe the broader research area, not only the task or method of that one paper.

## Feishu

PaperWatch reads Feishu settings from `config.toml`. The same settings are available in Config -> Feishu.

```toml
[feishu]
enabled = true
send_on_schedule = true
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_WEBHOOK_ID"
secret = "optional-signature-secret"
timeout_seconds = 15
```

`enabled` controls all Feishu sending. `send_on_schedule` controls whether the automatic fetch result is sent after a successful scheduled run. Manual digest sending from the UI also requires `enabled = true` and a webhook URL.

Recommended Feishu setup:

1. Create a private group chat with only yourself, or use an existing notification group.
2. Add a group bot and choose Custom Bot.
3. Copy the webhook URL into `webhook_url`.
4. Enable signature verification in Feishu bot security settings.
5. Copy the signature secret into `secret`.

Scheduled runs send a compact summary automatically after success. In the UI, open a digest and click `Send Feishu` to send that report manually.

Custom webhook bots post into the group where they are installed. A true one-to-one direct-message bot requires a Feishu internal app with bot message permissions.

## macOS Schedule

Use the built-in schedule command instead of copying the repository plist by hand. It writes a launchd job for the current machine:

```bash
paperwatch schedule install --config config.toml
```

Check status:

```bash
paperwatch schedule status --config config.toml
```

Uninstall:

```bash
paperwatch schedule uninstall --config config.toml
```

The generated launchd plist is written to:

```text
~/Library/LaunchAgents/com.paperwatch.daily.plist
```

It uses the current Python executable and the absolute path to your selected `config.toml`, so it can be recreated on another Mac after installing PaperWatch there.

Run once through launchd:

```bash
launchctl kickstart -k gui/$(id -u)/com.paperwatch.daily
```

Logs are written under `~/Library/Logs/PaperWatch/`:

```bash
tail -f ~/Library/Logs/PaperWatch/paperwatch.out.log
tail -f ~/Library/Logs/PaperWatch/paperwatch.err.log
```

For another Mac or PC:

- Install the wheel or source package.
- Copy or recreate `config.toml` without leaking API keys.
- Open the UI, confirm Config -> Schedule and Config -> Feishu.
- Click `Install on this PC`, or run `paperwatch schedule install --config /path/to/config.toml`.
- macOS launchd install is automated. Linux/Windows currently require using the OS scheduler to run `paperwatch run --config /path/to/config.toml --days N`.

## GitHub Actions Schedule

PaperWatch can also run from GitHub Actions. This is the recommended setup when you want the daily fetch to run even if your local computer is off.

The bundled workflow is:

```text
.github/workflows/daily-paperwatch.yml
```

It runs every day at `04:30 UTC`, which is `12:30 Asia/Shanghai`, and can also be started manually from the GitHub Actions page. GitHub scheduled workflows use UTC cron and may be delayed under GitHub Actions load.

The workflow:

- installs PaperWatch,
- runs `paperwatch run --config config.toml --days 1 --include-sent --no-mark-sent`,
- deduplicates papers within that run across enabled sources,
- sends Feishu if Feishu secrets are configured,
- uploads generated digests as an Actions artifact,
- commits generated `data/digests/*.md` files back to the repository.

For a private operating repository, add these repository secrets:

```text
OPENAI_API_KEY
FEISHU_WEBHOOK_URL
FEISHU_SECRET
```

Feishu can be configured entirely from environment variables in GitHub Actions:

```text
FEISHU_ENABLED=true
FEISHU_WEBHOOK_URL=...
FEISHU_SECRET=...
FEISHU_SEND_ON_SCHEDULE=true
```

Do not commit API keys or Feishu webhooks to git, even in a private repository. Keep model names, source settings, interests, and non-secret routing options in `config.toml`; keep credentials in GitHub Secrets.

To view GitHub-generated digests locally:

```bash
git pull
paperwatch ui --open
```

## Development

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Compile-check source and tests:

```bash
PYTHONPATH=src python3 -m compileall -q src tests
```

The generated runtime files live under `data/`. Keep API keys out of commits; use placeholders in `config.toml` or environment variables for shared copies.

## Publish To GitHub

This directory needs to be a git repository before it can be pushed:

```bash
git init
git add README.md pyproject.toml src tests docs scripts launchd .gitignore
git commit -m "Prepare PaperWatch release"
```

With GitHub CLI installed and authenticated:

```bash
gh auth login
gh repo create YOUR_ACCOUNT/paperwatch --private --source=. --remote=origin --push
```

For an existing GitHub repository:

```bash
git remote add origin git@github.com:YOUR_ACCOUNT/paperwatch.git
git push -u origin main
```
