from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class OpenAICompatibleClient:
    def __init__(self, api_key_env: str, base_url: str, timeout_seconds: int, api_key: str = "") -> None:
        self.api_key_env = api_key_env
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key or _resolve_key(api_key_env)

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def embeddings(self, model: str, inputs: list[str]) -> list[list[float]]:
        payload = {"model": model, "input": inputs}
        data = self._post_json("/embeddings", payload)
        rows = data.get("data", [])
        rows = sorted(rows, key=lambda item: item.get("index", 0))
        return [row["embedding"] for row in rows]

    def chat(self, model: str, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        payload = {"model": model, "messages": messages, "temperature": temperature}
        data = self._post_json("/chat/completions", payload)
        return data["choices"][0]["message"]["content"]

    def _post_json(self, path: str, payload: dict) -> dict:
        if not self.api_key:
            raise RuntimeError(f"API key is not configured; set api_key or {self.api_key_env}")
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "paperwatch/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"AI API HTTP {exc.code}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"AI API request failed: {exc.reason}") from exc


def _resolve_key(api_key_env: str) -> str | None:
    # Be forgiving: if the config field contains a key instead of an env var
    # name, use it directly. This keeps older UI edits from breaking runs.
    if api_key_env.startswith(("sk-", "sk_", "sess-")):
        return api_key_env
    return os.environ.get(api_key_env)
