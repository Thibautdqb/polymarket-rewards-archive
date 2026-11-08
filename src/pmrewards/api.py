"""Read live reward configurations and market metadata from the public Polymarket CLOB."""

from __future__ import annotations

import json
import time
from importlib.metadata import version
from typing import IO

import httpx

BASE_URL = "https://clob.polymarket.com"
END_CURSOR = "LTE="
MAX_PAGES = 1000


def client(timeout: float = 120.0) -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        timeout=timeout,
        headers={"User-Agent": f"pmrewards/{version('pmrewards')} (+https://github.com/Thibautdqb/polymarket-rewards-archive)"},
    )


def _get(http: httpx.Client, path: str, params: dict | None, retries: int) -> dict:
    for attempt in range(retries):
        try:
            r = http.get(path, params=params)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(min(60, 5 * 2**attempt))
    raise AssertionError("unreachable")


def current_rewards(http: httpx.Client, retries: int = 5, raw: IO[str] | None = None) -> list[dict]:
    """Every market with a reward configuration in force now, de-duplicated by condition id.

    `/rewards/markets/current` lists only live configurations (about 12k markets, a few MB).
    The larger `/rewards/markets/multi` also returns ~200k markets whose rewards have ended.
    With `raw`, the API records are streamed to that text file as JSON lines.
    """
    out: dict[str, dict] = {}
    cursor = ""
    for _ in range(MAX_PAGES):
        page = _get(http, "/rewards/markets/current", {"next_cursor": cursor} if cursor else None, retries)
        for m in page.get("data") or []:
            if raw is not None:
                raw.write(json.dumps(m, separators=(",", ":")) + "\n")
            out[m["condition_id"]] = m
        cursor = page.get("next_cursor") or END_CURSOR
        if cursor == END_CURSOR:
            return list(out.values())
    raise RuntimeError(f"reward list did not end after {MAX_PAGES} pages")


def market_meta(http: httpx.Client, condition_id: str, retries: int = 3) -> dict:
    """Slug, question and tokens of one market."""
    m = _get(http, f"/markets/{condition_id}", None, retries)
    return {
        "condition_id": condition_id,
        "market_slug": m.get("market_slug"),
        "question": m.get("question"),
        "tokens": [{"token_id": t.get("token_id"), "outcome": t.get("outcome")} for t in m.get("tokens") or []],
    }
