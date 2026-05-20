from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta

from paperwatch.ai import generate_insights, generate_translations
from paperwatch.config import ensure_default_config, load_settings, write_default_config
from paperwatch.notify.feishu import DigestNotification, notify_digest
from paperwatch.rankers import score_papers_by_interest
from paperwatch.rankers.embedding import rerank_by_embedding
from paperwatch.render import write_digest
from paperwatch.sources import ArxivOaiSource, ArxivSource, DblpSource, OpenAlexSource
from paperwatch.storage import PaperStore
from paperwatch.ui import serve_ui


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paperwatch")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Fetch, rank, store, and render a daily paper digest.")
    run.add_argument("--config", default="config.toml", help="Path to TOML config.")
    run.add_argument("--days", type=int, default=1, help="Fetch this many complete days ending yesterday.")
    run.add_argument("--start-date", default=None, help="Inclusive fetch start date, YYYY-MM-DD.")
    run.add_argument("--end-date", default=None, help="Inclusive fetch end date, YYYY-MM-DD.")
    run.add_argument("--interest", default=None, help="Interest name to fetch, or 'none' to fetch all arXiv papers without ranking.")
    run.add_argument("--interests", nargs="*", default=None, help="Interest names to fetch; defaults to config-specified daily fetch interests.")
    run.add_argument("--ranking-mode", default=None, help="Override ranking mode for this run.")
    run.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum papers per interest; omitted timestamped manual runs are unlimited.",
    )
    run.add_argument("--include-sent", action="store_true", help="Include papers already sent before.")
    run.add_argument("--no-mark-sent", action="store_true", help="Do not mark rendered papers as sent.")
    run.add_argument("--timestamped", action="store_true", help="Write digest with timestamped filename.")
    run.add_argument("--label", default=None, help="Optional digest filename label.")

    init = sub.add_parser("init-config", help="Write a default config file.")
    init.add_argument("--output", default="config.toml")
    init.add_argument("--force", action="store_true")

    ui = sub.add_parser("ui", help="Start the local PaperWatch web UI.")
    ui.add_argument("--config", default="config.toml")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--open", action="store_true", help="Open the web UI in the default browser.")

    schedule = sub.add_parser("schedule", help="Install, uninstall, or inspect the local automatic fetch schedule.")
    schedule.add_argument("--config", default="config.toml")
    schedule_sub = schedule.add_subparsers(dest="schedule_command", required=True)
    for name, help_text in [
        ("install", "Install the configured schedule on this machine."),
        ("uninstall", "Uninstall the schedule from this machine."),
        ("status", "Show schedule config and local install status."),
    ]:
        schedule_cmd = schedule_sub.add_parser(name, help=help_text)
        schedule_cmd.add_argument("--config", default=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    if args.command == "init-config":
        path = write_default_config(args.output, overwrite=args.force)
        print(f"Wrote {path}")
        return 0
    if args.command == "run":
        return _run(args)
    if args.command == "ui":
        serve_ui(args.host, args.port, args.config, open_browser=args.open)
        return 0
    if args.command == "schedule":
        return _schedule(args)
    parser.error("unknown command")
    return 2


def _schedule(args: argparse.Namespace) -> int:
    from paperwatch.schedule import install_schedule, schedule_status, uninstall_schedule

    ensure_default_config(args.config)
    settings = load_settings(args.config)
    try:
        if args.schedule_command == "install":
            path = install_schedule(args.config, settings)
            print(f"Installed PaperWatch schedule: {path}")
            return 0
        if args.schedule_command == "uninstall":
            path = uninstall_schedule()
            print(f"Uninstalled PaperWatch schedule: {path}")
            return 0
        if args.schedule_command == "status":
            status = schedule_status(args.config, settings)
            for key, value in status.items():
                print(f"{key}: {value}")
            return 0
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    raise ValueError(f"unknown schedule command: {args.schedule_command}")


def _run(args: argparse.Namespace) -> int:
    ensure_default_config(args.config)
    settings = load_settings(args.config)
    limit = _resolve_limit(args, settings)
    start_date, end_date = _resolve_date_range(args)
    requested_interests = getattr(args, "interests", None)
    if requested_interests is None:
        requested_interests = args.interest
    selected_interests = _select_interests(settings.interests, requested_interests, settings.default_fetch_interests)
    no_rank = _is_no_rank(requested_interests)

    papers = []
    failures = []
    if settings.arxiv.enabled:
        source = _arxiv_source(settings.arxiv)
        if no_rank:
            print(f"Fetching arXiv {settings.arxiv.fetch_mode}: all papers ({start_date} to {end_date})")
            try:
                papers.extend(source.fetch_all(start_date, end_date))
            except RuntimeError as exc:
                failures.append(str(exc))
                print(f"Warning: {exc}", file=sys.stderr)
        else:
            if settings.arxiv.fetch_mode == "oai_daily":
                print(f"Fetching arXiv oai_daily: all papers ({start_date} to {end_date})")
                try:
                    papers.extend(source.fetch_all(start_date, end_date))
                except RuntimeError as exc:
                    failures.append(str(exc))
                    print(f"Warning: {exc}", file=sys.stderr)
            else:
                for interest in selected_interests:
                    print(f"Fetching arXiv search: {interest.name} ({start_date} to {end_date})")
                    try:
                        papers.extend(source.fetch(interest, start_date, end_date))
                    except RuntimeError as exc:
                        failures.append(str(exc))
                        print(f"Warning: {exc}", file=sys.stderr)
    if settings.openalex.enabled:
        source = OpenAlexSource(settings.openalex)
        if no_rank:
            print(f"Fetching OpenAlex: all works ({start_date} to {end_date})")
            try:
                papers.extend(source.fetch_all(start_date, end_date))
            except RuntimeError as exc:
                failures.append(str(exc))
                print(f"Warning: {exc}", file=sys.stderr)
        else:
            for interest in selected_interests:
                print(f"Fetching OpenAlex: {interest.name} ({start_date} to {end_date})")
                try:
                    papers.extend(source.fetch(interest, start_date, end_date))
                except RuntimeError as exc:
                    failures.append(str(exc))
                    print(f"Warning: {exc}", file=sys.stderr)
    if settings.dblp.enabled:
        source = DblpSource(settings.dblp)
        if no_rank:
            print(f"Fetching dblp: all publications is not supported; skipping.")
        else:
            for interest in selected_interests:
                print(f"Fetching dblp: {interest.name} ({start_date} to {end_date})")
                try:
                    papers.extend(source.fetch(interest, start_date, end_date))
                except RuntimeError as exc:
                    failures.append(str(exc))
                    print(f"Warning: {exc}", file=sys.stderr)

    if failures and not papers:
        print("No papers fetched because all enabled sources failed.", file=sys.stderr)
        return 1

    deduped = _dedupe(papers)
    digest_paths: list[str] = []
    notification_items = []
    total_recommendations = 0
    store = PaperStore(settings.database_path)
    try:
        inserted = store.save_papers(deduped)
        mode = (args.ranking_mode or settings.ranking.mode).lower()
        if no_rank:
            unranked_limit = args.limit if args.limit is not None else len(deduped)
            selected = [_as_unranked(paper) for paper in deduped[:unranked_limit]]
            metadata = {
                "Date range": f"{start_date.isoformat()} to {end_date.isoformat()}",
                "Interest": "None / all arXiv papers",
                "Ranking": "none",
                "Mode": "manual" if args.timestamped else "scheduled",
            }
            digest_path = write_digest(
                selected,
                settings.digest_dir,
                metadata=metadata,
                timestamped=args.timestamped,
                label=args.label or ("manual" if args.timestamped else None),
            )
            digest_paths.append(str(digest_path))
            total_recommendations = len(selected)
            notification_items.extend(selected)
        else:
            scored_by_interest = score_papers_by_interest(deduped, selected_interests)
            if mode in {"embedding", "embedding_ai"}:
                try:
                    scored_by_interest = rerank_by_embedding(
                        scored_by_interest,
                        selected_interests,
                        settings.embedding,
                        settings.ranking.candidate_limit_per_interest,
                    )
                    print("Embedding rerank enabled.")
                except RuntimeError as exc:
                    print(f"Warning: {exc}", file=sys.stderr)

            per_interest_selected = []
            for interest in selected_interests:
                scored = scored_by_interest.get(interest.name, [])
                if not args.include_sent:
                    scored = store.filter_unsent(scored)
                selected = scored if limit is None else scored[:limit]
                per_interest_selected.append((interest.name, selected))

            split_reports = len(selected_interests) > 1
            for interest_name, selected in per_interest_selected:
                insights = None
                if mode in {"ai", "embedding_ai"} and selected:
                    try:
                        insights = generate_insights(selected, settings.digest_ai)
                        print(f"AI insights enabled for {interest_name}.")
                    except RuntimeError as exc:
                        print(f"Warning: {exc}", file=sys.stderr)

                translations = None
                if settings.translation.enabled and selected:
                    try:
                        translations = generate_translations(selected, settings.ai, settings.translation)
                        print(f"AI translation enabled for {interest_name}.")
                    except RuntimeError as exc:
                        print(f"Warning: {exc}", file=sys.stderr)

                metadata = {
                    "Date range": f"{start_date.isoformat()} to {end_date.isoformat()}",
                    "Interest": interest_name,
                    "Ranking": mode,
                    "Mode": "manual" if args.timestamped else "scheduled",
                }
                digest_path = write_digest(
                    selected,
                    settings.digest_dir,
                    insights=insights,
                    translations=translations,
                    metadata=metadata,
                    timestamped=args.timestamped,
                    label=interest_name if split_reports else (args.label or ("manual" if args.timestamped else None)),
                )
                digest_paths.append(str(digest_path))
                total_recommendations += len(selected)
                notification_items.extend(selected)
                if not args.no_mark_sent and selected:
                    store.mark_sent(selected, str(digest_path))
    finally:
        store.close()

    print(f"Fetched {len(papers)} papers, {len(deduped)} unique, {inserted} new.")
    print(f"Wrote digest(s): {', '.join(digest_paths)}")
    print(f"Recommendations: {total_recommendations}")
    notify_digest(
        DigestNotification(
            date_range=f"{start_date.isoformat()} to {end_date.isoformat()}",
            interests=[interest.name for interest in selected_interests],
            ranking_mode=("none" if no_rank else (args.ranking_mode or settings.ranking.mode).lower()),
            mode="manual" if args.timestamped else "scheduled",
            fetched_count=len(papers),
            unique_count=len(deduped),
            inserted_count=inserted,
            recommendation_count=total_recommendations,
            digest_paths=digest_paths,
            top_papers=notification_items,
        ),
        config=settings.feishu,
    )
    return 0


def _dedupe(papers):
    seen = set()
    result = []
    for paper in papers:
        keys = _dedupe_keys(paper)
        if any(key in seen for key in keys):
            continue
        seen.update(keys)
        result.append(paper)
    return result


def _dedupe_keys(paper):
    keys = {("source", paper.source, paper.paper_id)}
    doi = _normalize_doi(paper.doi or paper.url)
    if doi:
        keys.add(("doi", doi))
    arxiv_id = _extract_arxiv_id(paper.url) or _extract_arxiv_id(paper.pdf_url or "") or (
        paper.paper_id if paper.source == "arxiv" else ""
    )
    if arxiv_id:
        keys.add(("arxiv", arxiv_id.lower()))
    title = _normalize_title(paper.title)
    if title:
        keys.add(("title", title))
    return keys


def _normalize_doi(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip().lower()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value)
    value = re.sub(r"^doi:\s*", "", value)
    return value if value.startswith("10.") else ""


def _extract_arxiv_id(value: str) -> str:
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", value, flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).removesuffix(".pdf").split("v")[0]


def _normalize_title(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return " ".join(value.split())


def _resolve_date_range(args: argparse.Namespace) -> tuple[date, date]:
    if args.start_date or args.end_date:
        if not args.start_date or not args.end_date:
            raise ValueError("--start-date and --end-date must be provided together")
        start_date = date.fromisoformat(args.start_date)
        end_date = date.fromisoformat(args.end_date)
        if start_date > end_date:
            raise ValueError("--start-date must be on or before --end-date")
        return start_date, end_date

    days = max(int(args.days), 1)
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=days - 1)
    return start_date, end_date


def _resolve_limit(args: argparse.Namespace, settings) -> int | None:
    if args.limit is not None:
        return int(args.limit)
    if getattr(args, "timestamped", False):
        return None
    return settings.per_interest_limit


def _arxiv_source(config):
    if config.fetch_mode == "oai_daily":
        return ArxivOaiSource(config)
    if config.fetch_mode == "search":
        return ArxivSource(config)
    raise ValueError(f"unknown arXiv fetch_mode: {config.fetch_mode}")


def _select_interests(interests, requested: str | list[str] | None, default_names: list[str]):
    if requested is None or requested == "" or requested == []:
        requested_names = default_names or [interest.name for interest in interests]
    elif isinstance(requested, list):
        requested_names = requested
    else:
        if _is_no_rank(requested):
            return []
        requested_names = [requested]
    if any(_is_no_rank(name) for name in requested_names):
        return []
    available = {interest.name: interest for interest in interests}
    missing = [name for name in requested_names if name not in available]
    if missing:
        available = ", ".join(interest.name for interest in interests)
        raise ValueError(f"unknown interest(s) {missing!r}; available: {available}")
    selected = []
    seen = set()
    for name in requested_names:
        if name in seen:
            continue
        seen.add(name)
        selected.append(available[name])
    return selected


def _is_no_rank(interest: str | list[str] | None) -> bool:
    if isinstance(interest, list):
        return any(_is_no_rank(item) for item in interest)
    return bool(interest and interest.lower() in {"none", "all", "no_rank", "no-rank"})


def _as_unranked(paper):
    from paperwatch.models import ScoredPaper

    return ScoredPaper(
        paper=paper,
        interest_name="All Papers",
        score=0.0,
        matched_keywords=[],
        blocked_keywords=[],
    )


if __name__ == "__main__":
    sys.exit(main())
