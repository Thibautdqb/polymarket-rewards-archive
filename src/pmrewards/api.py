"""Read the public list of reward-eligible markets from the Polymarket CLOB."""

from __future__ import annotations

import time
from importlib.metadata import version

import httpx

BASE_URL = "https://clob.polymarket.com"
PAGE_SIZE = 500
END_CURSOR = "LTE="


def client(timeout: float = 120.0) -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        timeout=timeout,
        headers={"User-Agent": f"pmrewards/{version('pmrewards')} (+https://github.com/Thibautdqb/polymarket-rewards-archive)"},
    )


def _get(http: httpx.Client, path: str, params: dict, retries: int) -> dict:
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


def reward_markets(http: httpx.Client, retries: int = 5) -> list[dict]:
    """Every market currently carrying a reward configuration, as returned by the API."""
    out: list[dict] = []
    cursor = ""
    while cursor != END_CURSOR:
        params = {"page_size": PAGE_SIZE, "order_by": "rate_per_day", "position": "DESC"}
        if cursor:
            params["next_cursor"] = cursor
        page = _get(http, "/rewards/markets/multi", params, retries)
        out += page.get("data") or []
        cursor = page.get("next_cursor") or END_CURSOR
    return out
