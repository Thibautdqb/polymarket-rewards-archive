"""pmrewards: collect, inspect and export the reward-configuration archive."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pmrewards import api
from pmrewards.store import Archive

log = logging.getLogger("pmrewards")


def snapshot_once(archive: Archive, http, raw_dir: Path | None) -> None:
    t0 = time.monotonic()
    ts = datetime.now(timezone.utc).replace(microsecond=0)
    markets = api.reward_markets(http)
    changed = archive.record(markets, ts)
    if raw_dir is not None:
        day = raw_dir / ts.strftime("%Y-%m-%d")
        day.mkdir(parents=True, exist_ok=True)
        with gzip.open(day / f"{ts:%H%M%S}.jsonl.gz", "wt") as f:
            for m in markets:
                f.write(json.dumps(m, separators=(",", ":")) + "\n")
    log.info("%d markets, %d period changes, %.1fs", len(markets), changed, time.monotonic() - t0)


def cmd_collect(args) -> None:
    archive = Archive(args.db)
    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    last_raw = 0.0
    with api.client() as http:
        while not stop:
            start = time.monotonic()
            raw = args.raw_dir if args.raw_dir and start - last_raw >= args.raw_every else None
            try:
                snapshot_once(archive, http, raw)
                if raw is not None:
                    last_raw = start
            except Exception:
                log.exception("snapshot failed; the archive is unchanged and the next one will retry")
            if args.once:
                break
            while not stop and time.monotonic() - start < args.every:
                time.sleep(1)
    archive.close()


def cmd_history(args) -> None:
    archive = Archive(args.db)
    for row in archive.history(args.condition_id):
        print(json.dumps(row))


def cmd_rate(args) -> None:
    archive = Archive(args.db)
    ts = datetime.fromisoformat(args.at).astimezone(timezone.utc)
    print(archive.rate_at(args.condition_id, ts))


def cmd_export(args) -> None:
    archive = Archive(args.db)
    q = """select p.*, m.market_slug, m.event_slug, m.question from periods p join markets m using (condition_id)
           where (? is null or coalesce(p.closed_at, p.last_seen) >= ?) and (? is null or p.first_seen < ?)
           order by p.first_seen"""
    cur = archive.db.execute(q, (args.since, args.since, args.until, args.until))
    names = [d[0] for d in cur.description]
    if args.format == "parquet":
        import pyarrow as pa
        import pyarrow.parquet as pq

        rows = cur.fetchall()
        pq.write_table(pa.table({n: [r[i] for r in rows] for i, n in enumerate(names)}), args.out)
        return
    out = open(args.out, "w", newline="") if args.out != "-" else sys.stdout
    w = csv.writer(out)
    w.writerow(names)
    w.writerows(cur)


def cmd_stats(args) -> None:
    archive = Archive(args.db)
    db = archive.db
    first, last, n = db.execute("select min(ts), max(ts), count(*) from snapshots").fetchone()
    print(f"snapshots   {n}  from {first} to {last}")
    print(f"markets     {db.execute('select count(*) from markets').fetchone()[0]}")
    print(f"periods     {db.execute('select count(*) from periods').fetchone()[0]}  "
          f"(current {db.execute('select count(*) from periods where closed_at is null').fetchone()[0]})")
    gaps = db.execute(
        """select ts, prev from (select ts, lag(ts) over (order by ts) prev from snapshots)
           where prev is not null and (julianday(ts) - julianday(prev)) * 86400 > ?""",
        (args.max_gap,),
    ).fetchall()
    print(f"gaps > {args.max_gap}s: {len(gaps)}")
    for ts, prev in gaps[-10:]:
        print(f"  {prev} -> {ts}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="pmrewards", description=__doc__)
    ap.add_argument("--db", type=Path, default=Path("data/rewards.db"))
    sub = ap.add_subparsers(required=True)

    c = sub.add_parser("collect", help="poll the reward list and fold every snapshot into the archive")
    c.add_argument("--every", type=int, default=300, help="seconds between snapshots (default 300)")
    c.add_argument("--raw-dir", type=Path, help="also keep full API responses (prices, competitiveness) as jsonl.gz")
    c.add_argument("--raw-every", type=int, default=3600, help="seconds between raw dumps (default 3600)")
    c.add_argument("--once", action="store_true", help="take one snapshot and exit (for cron)")
    c.set_defaults(func=cmd_collect)

    h = sub.add_parser("history", help="all recorded periods of one market, as json lines")
    h.add_argument("condition_id")
    h.set_defaults(func=cmd_history)

    r = sub.add_parser("rate", help="daily reward rate in force on a market at a past instant")
    r.add_argument("condition_id")
    r.add_argument("at", help="ISO-8601 time, e.g. 2026-11-08T12:00:00Z")
    r.set_defaults(func=cmd_rate)

    e = sub.add_parser("export", help="dump periods overlapping [since, until) to csv or parquet")
    e.add_argument("--since")
    e.add_argument("--until")
    e.add_argument("--format", choices=["csv", "parquet"], default="csv")
    e.add_argument("--out", default="-")
    e.set_defaults(func=cmd_export)

    s = sub.add_parser("stats", help="coverage of the archive and collection gaps")
    s.add_argument("--max-gap", type=int, default=900)
    s.set_defaults(func=cmd_stats)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if hasattr(args, "db"):
        args.db.parent.mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
