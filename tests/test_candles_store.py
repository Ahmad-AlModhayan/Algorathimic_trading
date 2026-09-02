from datetime import UTC, datetime

import polars as pl
import pytest

from core.data.candles import CANDLE_SCHEMA, from_ohlcv_rows, normalize, timeframe_ms, validate
from tests.conftest import make_rows


def test_timeframe_ms():
    assert timeframe_ms("1m") == 60_000
    assert timeframe_ms("4h") == 4 * 3_600_000
    assert timeframe_ms("1d") == 86_400_000
    with pytest.raises(ValueError):
        timeframe_ms("4H")


def test_from_rows_schema_and_order(t0):
    rows = make_rows(t0, 3)
    df = from_ohlcv_rows(list(reversed(rows)))
    assert df.schema == pl.Schema(CANDLE_SCHEMA)
    assert df["ts"].is_sorted()
    assert df["ts"][0] == t0


def test_normalize_keeps_last_duplicate(t0):
    rows = make_rows(t0, 2)
    dup = list(rows[1])
    dup[4] = 999.0
    df = normalize(from_ohlcv_rows(rows + [dup]))
    assert df.height == 2
    assert df["close"][-1] == 999.0


def test_validate_rejects_misaligned_and_bad_ohlc(t0):
    df = from_ohlcv_rows(make_rows(t0, 2))
    validate(df, "4h")
    with pytest.raises(ValueError, match="aligned"):
        validate(df, "1d")
    bad = df.with_columns(pl.lit(0.0).alias("high"))
    with pytest.raises(ValueError, match="inconsistent"):
        validate(bad)


def test_store_upsert_is_idempotent(store, t0):
    df = from_ohlcv_rows(make_rows(t0, 10))
    assert store.upsert("test", "BTC/USDT", "4h", df) == 10
    assert store.upsert("test", "BTC/USDT", "4h", df) == 0
    assert store.read("test", "BTC/USDT", "4h").height == 10
    assert store.last_ts("test", "BTC/USDT", "4h") == df["ts"][-1]


def test_store_upsert_merges_overlap_and_replaces(store, t0):
    first = from_ohlcv_rows(make_rows(t0, 10))
    store.upsert("test", "BTC/USDT", "4h", first)
    overlap_rows = make_rows(t0, 15)[8:]  # bars 8..14 with new values
    for r in overlap_rows:
        r[5] = 555.0
    inserted = store.upsert("test", "BTC/USDT", "4h", from_ohlcv_rows(overlap_rows))
    assert inserted == 5
    out = store.read("test", "BTC/USDT", "4h")
    assert out.height == 15
    assert out["ts"].is_sorted() and out["ts"].n_unique() == 15
    assert out.filter(pl.col("volume") == 555.0).height == 7


def test_store_read_range(store, t0):
    store.upsert("test", "BTC/USDT", "4h", from_ohlcv_rows(make_rows(t0, 10)))
    start = datetime(2024, 1, 1, 8, tzinfo=UTC)
    end = datetime(2024, 1, 1, 16, tzinfo=UTC)
    assert store.read("test", "BTC/USDT", "4h", start=start, end=end).height == 2


def test_store_path_is_filesystem_safe(store):
    assert "/" not in store.path("binance", "BTC/USDT", "4h").name
    assert store.path("binance", "BTC/USDT", "4h").parent.name == "BTC-USDT"
