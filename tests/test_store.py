from datetime import datetime, timedelta, timezone

from pmrewards.store import Archive


def market(cid: str, rate: float, cfg_id: int = 1) -> dict:
    return {
        "condition_id": cid, "market_id": "1", "market_slug": f"slug-{cid}", "event_slug": "ev", "question": "q?",
        "rewards_max_spread": 4.5, "rewards_min_size": 20,
        "rewards_config": [{"id": cfg_id, "asset_address": "0xusdc", "rate_per_day": rate, "total_rewards": 0,
                            "start_date": "2026-11-01", "end_date": "2500-12-31"}],
        "tokens": [{"token_id": "1", "outcome": "Yes", "price": 0.4}, {"token_id": "2", "outcome": "No", "price": 0.6}],
    }


T0 = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
STEP = timedelta(minutes=5)


def test_unchanged_snapshots_extend_one_period():
    a = Archive(":memory:")
    for i in range(3):
        a.record([market("a", 10)], T0 + i * STEP)
    h = a.history("a")
    assert len(h) == 1
    assert h[0]["first_seen"] == T0.isoformat() and h[0]["last_seen"] == (T0 + 2 * STEP).isoformat()
    assert h[0]["closed_at"] is None


def test_rate_change_and_disappearance_close_periods():
    a = Archive(":memory:")
    a.record([market("a", 10)], T0)
    a.record([market("a", 25)], T0 + STEP)
    a.record([], T0 + 2 * STEP)  # market closed: config gone from the API
    h = a.history("a")
    assert [p["rate_per_day"] for p in h] == [10, 25]
    assert h[0]["closed_at"] == (T0 + STEP).isoformat()
    assert h[1]["closed_at"] == (T0 + 2 * STEP).isoformat()
    assert a.rate_at("a", T0 + timedelta(minutes=2)) == 10
    assert a.rate_at("a", T0 + STEP + timedelta(minutes=1)) == 25
    assert a.rate_at("a", T0 + 3 * STEP) == 0.0
    assert a.rate_at("a", T0 - STEP) is None  # before the archive starts


def test_reappearing_config_opens_a_new_period():
    a = Archive(":memory:")
    a.record([market("a", 10)], T0)
    a.record([], T0 + STEP)
    a.record([market("a", 10)], T0 + 2 * STEP)
    assert len(a.history("a")) == 2


def test_several_configs_add_up():
    a = Archive(":memory:")
    m = market("a", 10)
    m["rewards_config"].append({"id": 2, "rate_per_day": 5, "start_date": "2026-11-01", "end_date": "2500-12-31"})
    a.record([m], T0)
    assert a.rate_at("a", T0) == 15


def test_snapshots_without_metadata_keep_names():
    a = Archive(":memory:")
    bare = {k: v for k, v in market("a", 10).items() if k in ("condition_id", "rewards_config", "rewards_max_spread", "rewards_min_size")}
    a.record([bare], T0)
    assert a.missing_meta(10) == ["a"]
    a.set_meta({"condition_id": "a", "market_slug": "slug-a", "question": "q?", "tokens": [{"token_id": "1", "outcome": "Yes"}]})
    a.record([bare], T0 + STEP)
    assert a.missing_meta(10) == []
    assert a.db.execute("select market_slug from markets").fetchone()[0] == "slug-a"


def test_stats_separates_rate_changes_from_arrivals(capsys, tmp_path):
    from pmrewards.cli import main
    db = tmp_path / "r.db"
    a = Archive(db)
    a.record([market("a", 10)], T0)
    a.record([market("a", 25), market("b", 5)], T0 + STEP)
    a.record([market("b", 5)], T0 + 2 * STEP)
    a.close()
    main(["--db", str(db), "stats"])
    out = capsys.readouterr().out
    assert "value changes   1  (rate changes 1 on 1 markets)" in out
    assert "appeared        1" in out and "left the list   1" in out
