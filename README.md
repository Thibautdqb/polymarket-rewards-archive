# polymarket-rewards-archive

**The history of Polymarket liquidity rewards, market by market, that Polymarket itself does not keep.**

If you make markets on Polymarket for the liquidity rewards, the reward rate is half of your
P&L. The other half is your trading. Yet that rate is only visible *now*:

- the public API (`/rewards/markets/current`, `/rewards/markets/multi`) returns the configuration
  in force today, with no way to ask for yesterday;
- when a market closes, its reward configuration is usually wiped: `/rewards/markets/{condition_id}`
  comes back empty, `/markets/{condition_id}` reports `rates: null`, and Gamma drops `clobRewards`.
  On a sample of 10 closed markets, 9 had lost it, and the 10th kept only its final value;
- rates move all the time while a market is open, and every earlier value is overwritten.

How much they move: in its **first four hours**, this archive recorded **20,665 rate changes on
3,277 markets** (about a quarter of all rewarded markets). A typical change multiplies the rate
by 0.6 or 1.7. Daily temperature markets alone (`highest-` and `lowest-temperature`, about
1,050 markets) accounted for 7,473 of them, roughly ten changes per market in four hours.

`pmrewards` records every one of those changes, for every rewarded market, every five minutes,
and makes the rate in force on any market at any past instant a single lookup.

## What market makers use it for

- **Backtests that mean something.** A reward strategy earns `your share of the order-book score × the
  daily rate`. Replaying old order books against today's rates (or a guess) can be wrong by a factor of
  two on the markets that matter. With the archive you replay them against the rate that was really paid.
- **Picking markets.** See where Polymarket is moving its reward budget, how long a generous rate
  usually lasts, and which market families get re-priced intraday.
- **Reconciling payouts.** Your daily reward payment comes as one number. The archive tells you what each
  market you quoted was paying at the time, so you can tell a bad day from a rate cut.
- **Research.** How rewards relate to price, spread, volume and time to resolution, across all categories.

## Live feed

A hosted instance has been running continuously since **2026-11-08 21:20 UTC**: every rewarded market
(about 13,000), polled every five minutes, with full API responses kept every hour. It is the only
per-market history of these rates we know of. The public alternatives we found are current-state
screeners and scrapers, a dashboard that keeps only aggregate history, and leaderboards of rewards earned per wallet.

**Want the live stream of rate changes or the history so far?**
[Open an issue](https://github.com/Thibautdqb/polymarket-rewards-archive/issues) and say what you
need: markets or categories, update frequency, format. Or run your own collector with the code below.
It is the same code.

## What is recorded

For every market with a reward configuration in force:

| Field | Meaning |
|---|---|
| `rate_per_day` | daily reward pool for the market, in USDC |
| `max_spread` | reward band around the midpoint, in cents |
| `min_size` | minimum order size that earns rewards |
| `start_date`, `end_date` | the configuration's own dates |
| `market_slug`, `question`, tokens | looked up once per new market |

Each configuration is stored as a **validity period**: from the first snapshot that showed these values
(`first_seen`) to the first snapshot where they had changed or the market had left the list (`closed_at`).
Five-minute polling means one row per change, not one row per snapshot. A day of 13,000 markets
stays a few megabytes, and every rate is known to within five minutes.

## Run your own collector

```bash
uv tool install git+https://github.com/Thibautdqb/polymarket-rewards-archive
pmrewards --db data/rewards.db collect --every 300 --raw-dir data/raw
```

- Each snapshot reads `GET /rewards/markets/current` (about 12k markets, a few MB, about 30 s). The larger
  `/rewards/markets/multi` also returns about 200k markets whose rewards have ended and takes over ten
  minutes, so it is not used. Slugs, questions and tokens come from `GET /markets/{condition_id}`, once per new market.
- A snapshot is written only when **every** page arrives, so a network failure never fakes a rate change
  or a market closure.
- `--raw-dir` also keeps the complete API response every hour (`--raw-every`) as `jsonl.gz`, for any field
  the API adds later.
- `--once` takes a single snapshot, for cron.

To run it permanently, use `deploy/pmrewards.service` (systemd) or Docker:

```bash
docker build -t pmrewards . && docker run -d --restart=always -v $PWD/data:/data pmrewards
```

History only exists from the moment a collector starts, so start early and keep it running.

## Query

```bash
pmrewards rate 0x5691e3bc... 2026-11-08T12:00:00Z   # rate in force at that instant
pmrewards history 0x5691e3bc...                      # every period of one market, json lines
pmrewards export --since 2026-11-01 --format parquet --out rewards.parquet
pmrewards stats                                      # coverage, rate changes vs arrivals/departures, gaps
```

From Python:

```python
from datetime import datetime, timezone
from pmrewards.store import Archive

a = Archive("data/rewards.db")
a.rate_at("0x5691e3bc...", datetime(2026, 11, 8, 12, tzinfo=timezone.utc))
```

## Data model (SQLite)

| Table | One row per | Key columns |
|---|---|---|
| `markets` | market ever seen with rewards | `condition_id`, `market_slug`, `question`, tokens, `first_seen`, `last_seen` |
| `periods` | run of identical values of one reward configuration | `rate_per_day`, `max_spread`, `min_size`, `start_date`, `end_date`, `first_seen`, `last_seen`, `closed_at` |
| `snapshots` | successful poll | `ts`, market and configuration counts, total daily rate, number of changes |

- **Period boundaries.** A period holds from `first_seen` until `closed_at`. `closed_at` is null while the
  period is current.
- **Gaps.** `snapshots` records every successful poll, so outages are visible, and `pmrewards stats` lists
  them. Treat a period that spans a gap as uncertain inside it.

## Notes

- **Read-only and keyless.** Only public, unauthenticated endpoints are used. No wallet, key or account.
- **Not affiliated with Polymarket.** Check Polymarket's terms of service before redistributing collected
  data commercially.
- **Access.** Polymarket is blocked in some countries. Run the collector only from where accessing it is
  permitted.

## License

MIT
