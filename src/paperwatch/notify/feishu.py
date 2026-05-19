from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paperwatch.models import FeishuConfig, ScoredPaper


DEFAULT_CONFIG_PATH = Path.home() / ".codex" / "feishu.json"
MAX_CARD_CHARS = 7800
MAX_TOP_ITEMS = 10


@dataclass(frozen=True)
class DigestNotification:
    date_range: str
    interests: list[str]
    ranking_mode: str
    mode: str
    fetched_count: int
    unique_count: int
    inserted_count: int
    recommendation_count: int
    digest_paths: list[str]
    top_papers: list[ScoredPaper]


def notify_digest(
    notification: DigestNotification,
    config_path: Path | None = None,
    config: FeishuConfig | None = None,
) -> bool:
    """Send a PaperWatch digest notification to Feishu if configured.

    Missing or disabled config is a no-op. Network and webhook errors are logged
    as warnings and never raised to the caller, so scheduled runs keep working.
    """

    resolved = _resolve_config(config, config_path)
    if resolved is None:
        return False
    if notification.mode == "scheduled" and not resolved.send_on_schedule:
        return False

    title = f"PaperWatch Daily Digest: {notification.recommendation_count} recommendations"
    body = render_digest_body(notification)
    payload: dict[str, Any] = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
            "elements": [{"tag": "markdown", "content": body}],
        },
    }
    if resolved.secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = _sign(timestamp, resolved.secret)

    try:
        _post_json(resolved.webhook_url, payload, timeout_seconds=resolved.timeout_seconds)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
        print(f"Warning: Feishu notification failed: {exc}", file=sys.stderr)
        return False
    return True


def notify_digest_markdown(
    name: str,
    content: str,
    config_path: Path | None = None,
    config: FeishuConfig | None = None,
) -> bool:
    resolved = _resolve_config(config, config_path)
    if resolved is None:
        return False
    body = _trim_digest_markdown(content)
    payload: dict[str, Any] = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": f"PaperWatch Digest: {name}"}, "template": "blue"},
            "elements": [{"tag": "markdown", "content": body}],
        },
    }
    if resolved.secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = _sign(timestamp, resolved.secret)
    try:
        _post_json(resolved.webhook_url, payload, timeout_seconds=resolved.timeout_seconds)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
        print(f"Warning: Feishu notification failed: {exc}", file=sys.stderr)
        return False
    return True


def load_config(path: Path) -> FeishuConfig | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Warning: Feishu config is invalid: {exc}", file=sys.stderr)
        return None

    mode = str(raw.get("mode", "push")).lower()
    if mode == "off":
        return None
    if mode != "push":
        print(f"Warning: Feishu mode {mode!r} is not supported by PaperWatch; skipping.", file=sys.stderr)
        return None

    webhook_url = str(raw.get("webhook_url", "")).strip()
    if not webhook_url:
        return None
    secret = str(raw.get("secret", raw.get("sign_secret", ""))).strip()
    return FeishuConfig(enabled=True, webhook_url=webhook_url, secret=secret)


def _resolve_config(config: FeishuConfig | None, config_path: Path | None) -> FeishuConfig | None:
    if config is not None:
        if config.enabled and config.webhook_url.strip():
            return config
        if not config.configured:
            return load_config(config_path or DEFAULT_CONFIG_PATH)
        return None
    return load_config(config_path or DEFAULT_CONFIG_PATH)


def render_digest_body(notification: DigestNotification) -> str:
    lines = [
        "**PaperWatch scheduled result**",
        "",
        f"- Date range: {notification.date_range}",
        f"- Interests: {', '.join(notification.interests) or 'None / all arXiv papers'}",
        f"- Ranking: {notification.ranking_mode}",
        f"- Mode: {notification.mode}",
        f"- Fetched: {notification.fetched_count}",
        f"- Unique: {notification.unique_count}",
        f"- New in database: {notification.inserted_count}",
        f"- Recommendations: {notification.recommendation_count}",
        "",
        "**Digest files**",
    ]
    lines.extend(f"- `{path}`" for path in notification.digest_paths)

    if notification.top_papers:
        lines.extend(["", "**Top papers**"])
        for index, item in enumerate(notification.top_papers[:MAX_TOP_ITEMS], start=1):
            paper = item.paper
            score = "" if item.interest_name == "All Papers" and item.score == 0 else f" | score {item.score:.1f}"
            lines.append(f"{index}. [{paper.title}]({paper.url}) - {item.interest_name}{score}")
        remaining = len(notification.top_papers) - MAX_TOP_ITEMS
        if remaining > 0:
            lines.append(f"... and {remaining} more.")
    elif notification.recommendation_count == 0:
        lines.extend(["", "No new matching papers found."])

    body = "\n".join(lines)
    if len(body) <= MAX_CARD_CHARS:
        return body
    return body[: MAX_CARD_CHARS - 40].rstrip() + "\n\n... truncated; see digest file."


def _trim_digest_markdown(content: str) -> str:
    lines = []
    for line in content.splitlines():
        if line.startswith("Abstract:") or line.startswith("摘要翻译:"):
            lines.append(line)
            lines.append("")
            lines.append("...")
            continue
        lines.append(line)
        if len("\n".join(lines)) > MAX_CARD_CHARS:
            break
    body = "\n".join(lines).strip()
    if len(body) <= MAX_CARD_CHARS:
        return body
    return body[: MAX_CARD_CHARS - 40].rstrip() + "\n\n... truncated; see local digest."


def _sign(timestamp: str, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(string_to_sign, b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _post_json(url: str, payload: dict[str, Any], timeout_seconds: int = 15) -> None:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        response_body = response.read().decode("utf-8")
    if response_body:
        parsed = json.loads(response_body)
        code = parsed.get("code", parsed.get("StatusCode", 0))
        if code not in (0, "0"):
            message = parsed.get("msg", parsed.get("message", response_body))
            raise ValueError(f"Feishu webhook returned {code}: {message}")
