"""Read the public list of reward-eligible markets from the Polymarket CLOB."""

from __future__ import annotations

import time
from importlib.metadata import version

import httpx

BASE_URL = "https://clob.polymarket.com"
PAGE_SIZE = 500
END_CURSOR = "LTE="
MAX_PAGES = 2000


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
    """Every market currently carrying a reward configuration, as returned by the API.

    Pages are read in the API's default order: sorting by rate is not stable across pages
    (ties move between requests), which both repeats and skips markets.
    """
    out: dict[str, dict] = {}
    cursor = ""
    for _ in range(MAX_PAGES):
        params = {"page_size": PAGE_SIZE}
        if cursor:
            params["next_cursor"] = cursor
        page = _get(http, "/rewards/markets/multi", params, retries)
        for m in page.get("data") or []:
            out[m["condition_id"]] = m
        cursor = page.get("next_cursor") or END_CURSOR
        if cursor == END_CURSOR:
            return list(out.values())
    raise RuntimeError(f"reward list did not end after {MAX_PAGES} pages")
