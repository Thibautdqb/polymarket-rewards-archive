# polymarket-rewards-archive

A continuous archive of Polymarket **liquidity-reward configurations**.

Polymarket pays makers a daily reward pool per market (`rate_per_day`, `max_spread`,
`min_size`). The public CLOB API only shows the configuration **while a market is open**:
once it closes, `/rewards/markets/{condition_id}` comes back empty, `/markets/{condition_id}`
reports `rates: null`, and Gamma drops `clobRewards`. On some market families, such as daily
temperature markets, rates are also re-set several times a day. Nobody can tell, after the
fact, what a given market paid on a given day.

That missing history is exactly what you need to:

- backtest a market-making or reward-farming strategy on past order books (reward share × rate);
- attribute realised reward payouts to markets;
- study how Polymarket allocates and moves reward budgets across categories.

`pmrewards` polls the full reward list every few minutes and stores every configuration as a
**validity period**: one row per change, not per snapshot. The rate in force on any market at
any past instant is then a single lookup, accurate to the polling interval.

## Install

```bash
uv tool install git+https://github.com/Thibautdqb/polymarket-rewards-archive
# or, from a clone
uv sync && uv run pmrewards --help
```

## Collect

```bash
pmrewards --db data/rewards.db collect --every 300 --raw-dir data/raw
```

- Each snapshot reads all pages of `GET /rewards/markets/multi` (about 13k markets, around 30 requests).
- A snapshot is written only when **every** page arrives, so a network failure never fakes a market closure.
- `--raw-dir` also keeps the complete API response every hour (`--raw-every`) as `jsonl.gz`. These files hold token prices, competitiveness and anything else the API adds later.
- `--once` takes a single snapshot, for cron.

To run it permanently, use `deploy/pmrewards.service` (systemd) or the `Dockerfile`:

```bash
docker build -t pmrewards . && docker run -d --restart=always -v $PWD/data:/data pmrewards
```

## Query

```bash
pmrewards history 0x5691e3bc...            # every period of one market, json lines
pmrewards rate 0x5691e3bc... 2026-11-08T12:00:00Z
pmrewards export --since 2026-11-01 --format parquet --out rewards.parquet
pmrewards stats                            # coverage and collection gaps
```

From Python:

```python
from datetime import datetime, timezone
from pmrewards.store import Archive

a = Archive("data/rewards.db")
a.rate_at("0x5691e3bc...", datetime(2026, 11, 8, 12, tzinfo=timezone.utc))
```

## Data model (SQLite)

| table | one row per | key columns |
|---|---|---|
| `markets` | market ever seen with rewards | `condition_id`, slugs, question, tokens, `first_seen`, `last_seen` |
| `periods` | run of identical values of one reward config | `rate_per_day`, `max_spread`, `min_size`, `start_date`, `end_date`, `first_seen`, `last_seen`, `closed_at` |
| `snapshots` | successful poll | `ts`, market and config counts, total daily rate, number of changes |

- **Period boundaries.** A period holds from `first_seen` until `closed_at`, the first snapshot that no longer shows those values. `closed_at` is null while the period is current.
- **Gaps.** `snapshots` records every successful poll, so outages are visible. `pmrewards stats` lists them. Treat periods that span a gap as uncertain inside it.

## Notes

- **Read-only.** The archive uses only public, unauthenticated endpoints. It needs no keys, wallet or account.
- **Not affiliated with Polymarket.** Check Polymarket's terms of service before you redistribute collected data commercially.
- **Access.** Polymarket is DNS-blocked in some countries. Run the collector from a location where accessing it is permitted.

## License

MIT
