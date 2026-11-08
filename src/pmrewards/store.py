"""SQLite archive of reward configurations as validity periods.

A period is a run of snapshots during which a configuration kept the same values. Polling
every few minutes therefore costs one row per change, not one row per snapshot, and the
rate in force at any past instant is a single indexed lookup.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA = """
create table if not exists markets (
    condition_id text primary key,
    market_id    text,
    market_slug  text,
    event_slug   text,
    question     text,
    tokens       text,          -- json [{token_id, outcome}]
    first_seen   text not null, -- ISO-8601 UTC
    last_seen    text not null
);
create table if not exists periods (
    id            integer primary key,
    condition_id  text not null,
    config_id     text not null,
    asset_address text,
    rate_per_day  real not null,
    total_rewards real,
    start_date    text,
    end_date      text,
    max_spread    real,
    min_size      real,
    first_seen    text not null, -- first snapshot showing these values
    last_seen     text not null, -- last snapshot showing them
    closed_at     text           -- first snapshot where they were gone; null while current
);
create index if not exists periods_market on periods (condition_id, first_seen);
create unique index if not exists periods_open on periods (condition_id, config_id) where closed_at is null;
create table if not exists snapshots (
    ts          text primary key,
    markets     integer not null,
    configs     integer not null,
    total_rate  real not null,
    changed     integer not null
);
"""

FIELDS = ("asset_address", "rate_per_day", "total_rewards", "start_date", "end_date", "max_spread", "min_size")


@dataclass(frozen=True)
class Config:
    condition_id: str
    config_id: str
    asset_address: str | None
    rate_per_day: float
    total_rewards: float | None
    start_date: str | None
    end_date: str | None
    max_spread: float | None
    min_size: float | None

    def values(self) -> tuple:
        return tuple(getattr(self, f) for f in FIELDS)


def _num(x) -> float | None:
    return None if x is None or x == "" else float(x)


def configs_of(market: dict) -> list[Config]:
    out = []
    for i, c in enumerate(market.get("rewards_config") or []):
        out.append(Config(
            condition_id=market["condition_id"],
            config_id=str(c.get("id") if c.get("id") is not None else f"#{i}"),
            asset_address=c.get("asset_address"),
            rate_per_day=float(c.get("rate_per_day") or 0),
            total_rewards=_num(c.get("total_rewards")),
            start_date=c.get("start_date"),
            end_date=c.get("end_date"),
            max_spread=_num(market.get("rewards_max_spread")),
            min_size=_num(market.get("rewards_min_size")),
        ))
    return out


class Archive:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def record(self, markets: list[dict], ts: datetime) -> int:
        """Fold one full snapshot into the archive; returns the number of periods opened or closed."""
        now = ts.isoformat()
        seen: dict[tuple[str, str], Config] = {}
        with self.db:
            for m in markets:
                tokens = json.dumps([{"token_id": t.get("token_id"), "outcome": t.get("outcome")} for t in m.get("tokens") or []])
                self.db.execute(
                    """insert into markets values (?,?,?,?,?,?,?,?)
                       on conflict (condition_id) do update set last_seen = excluded.last_seen,
                         market_slug = excluded.market_slug, event_slug = excluded.event_slug, question = excluded.question""",
                    (m["condition_id"], str(m.get("market_id") or ""), m.get("market_slug"), m.get("event_slug"),
                     m.get("question"), tokens, now, now),
                )
                for c in configs_of(m):
                    seen[(c.condition_id, c.config_id)] = c
            open_rows = {
                (r[1], r[2]): (r[0], r[3:])
                for r in self.db.execute(f"select id, condition_id, config_id, {', '.join(FIELDS)} from periods where closed_at is null")
            }
            changed = 0
            for key, (pid, vals) in open_rows.items():
                c = seen.get(key)
                if c is not None and c.values() == tuple(vals):
                    self.db.execute("update periods set last_seen = ? where id = ?", (now, pid))
                else:
                    self.db.execute("update periods set closed_at = ? where id = ?", (now, pid))
                    changed += 1
            for key, c in seen.items():
                prev = open_rows.get(key)
                if prev is None or c.values() != tuple(prev[1]):
                    self.db.execute(
                        f"insert into periods (condition_id, config_id, {', '.join(FIELDS)}, first_seen, last_seen) values (?,?,{','.join('?' * len(FIELDS))},?,?)",
                        (c.condition_id, c.config_id, *c.values(), now, now),
                    )
                    changed += 1
            self.db.execute(
                "insert or replace into snapshots values (?,?,?,?,?)",
                (now, len(markets), len(seen), sum(c.rate_per_day for c in seen.values()), changed),
            )
        return changed

    def rate_at(self, condition_id: str, ts: datetime) -> float | None:
        """Total daily reward rate in force on a market at ts, or None if it was not observed then.

        A period is taken to hold from its first sighting until the snapshot that saw it gone,
        so the answer is exact up to the polling interval.
        """
        t = ts.isoformat()
        covered = self.db.execute("select 1 from snapshots where ts <= ? limit 1", (t,)).fetchone()
        if covered is None:
            return None
        row = self.db.execute(
            """select sum(rate_per_day), count(*) from periods
               where condition_id = ? and first_seen <= ? and (closed_at is null or closed_at > ?)""",
            (condition_id, t, t),
        ).fetchone()
        return float(row[0]) if row[1] else 0.0

    def history(self, condition_id: str) -> list[dict]:
        cur = self.db.execute(
            f"select config_id, {', '.join(FIELDS)}, first_seen, last_seen, closed_at from periods where condition_id = ? order by first_seen",
            (condition_id,),
        )
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur]
