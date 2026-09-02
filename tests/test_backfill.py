from datetime import timedelta

from core.data.backfill import backfill
from core.data.candles import timeframe_ms
from tests.conftest import BTC, FakeAdapter, make_rows

STEP = timeframe_ms("4h")


def test_backfill_then_rerun_inserts_nothing(store, t0):
    rows = make_rows(t0, 30)
    now_ms = rows[-1][0] + 2 * STEP  # every row is closed
    adapter = FakeAdapter(rows, batch_limit=7)

    r1 = backfill(adapter, store, BTC, "4h", start=t0, now_ms=now_ms)
    assert (r1.fetched, r1.inserted) == (30, 30)
    assert r1.first_ts == t0 and r1.last_ts == t0 + timedelta(hours=4 * 29)

    r2 = backfill(adapter, store, BTC, "4h", start=t0, now_ms=now_ms)
    assert r2.inserted == 0
    assert r2.fetched == 1  # only the last archived bar is re-fetched
    assert adapter.calls[-1][0] == rows[-1][0]  # resumed from last archived ts
    assert store.read("test", "BTC/USDT", "4h").height == 30
    assert r2.first_ts == t0  # summary reflects the archive even with nothing new


def test_backfill_drops_unclosed_bar(store, t0):
    rows = make_rows(t0, 5)
    now_ms = rows[-1][0] + STEP // 2  # last bar still forming
    r = backfill(FakeAdapter(rows), store, BTC, "4h", start=t0, now_ms=now_ms)
    assert r.inserted == 4
    assert store.last_ts("test", "BTC/USDT", "4h") == t0 + timedelta(hours=12)


def test_backfill_resumes_and_extends(store, t0):
    rows = make_rows(t0, 20)
    adapter = FakeAdapter(rows[:10])
    now_ms = rows[-1][0] + STEP
    backfill(adapter, store, BTC, "4h", start=t0, now_ms=now_ms)
    adapter.rows = sorted(rows, key=lambda r: r[0])  # venue now has 10 more bars
    r = backfill(adapter, store, BTC, "4h", start=t0, now_ms=now_ms)
    assert r.inserted == 10
    assert store.read("test", "BTC/USDT", "4h").height == 20


def test_backfill_aligns_start_and_respects_end(store, t0):
    rows = make_rows(t0, 10)
    adapter = FakeAdapter(rows)
    start = t0 + timedelta(hours=5)  # inside bar 1 -> aligned down to bar 1
    end = t0 + timedelta(hours=4 * 6)
    r = backfill(adapter, store, BTC, "4h", start=start, end=end, now_ms=rows[-1][0] + STEP)
    assert adapter.calls[0] == (rows[1][0], rows[6][0])
    assert r.inserted == 5


def test_backfill_empty_venue(store, t0):
    r = backfill(
        FakeAdapter([]), store, BTC, "4h", start=t0, now_ms=int(t0.timestamp() * 1000) + 10 * STEP
    )
    assert (r.fetched, r.inserted, r.first_ts) == (0, 0, None)
