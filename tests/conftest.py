from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import polars as pl
import pytest

from core.data.candles import from_ohlcv_rows, timeframe_ms
from core.data.store import ParquetCandleStore
from core.models import Instrument

BTC = Instrument(
    venue="test",
    symbol="BTC/USDT",
    asset_class="crypto",
    tick_size=0.01,
    lot_size=0.00001,
    fee_pct=0.001,
    slippage_pct=0.0005,
)


def make_rows(
    start: datetime, n: int, timeframe: str = "4h", base: float = 100.0
) -> list[list[float]]:
    step = timeframe_ms(timeframe)
    t0 = int(start.timestamp() * 1000)
    rows = []
    for i in range(n):
        o = base + i
        rows.append([t0 + i * step, o, o + 2, o - 1, o + 1, 10.0 + i])
    return rows


class FakeAdapter:
    """Deterministic in-memory venue. Records every fetch so tests can assert on ranges."""

    venue = "test"

    def __init__(self, rows: list[list[float]], batch_limit: int = 5) -> None:
        self.rows = sorted(rows, key=lambda r: r[0])
        self.batch_limit = batch_limit
        self.calls: list[tuple[int, int]] = []

    def instrument(self, symbol: str) -> Instrument:
        return BTC

    def fetch_candles(
        self, symbol: str, timeframe: str, since_ms: int, until_ms: int
    ) -> Iterator[pl.DataFrame]:
        self.calls.append((since_ms, until_ms))
        selected = [r for r in self.rows if since_ms <= r[0] < until_ms]
        for i in range(0, len(selected), self.batch_limit):
            yield from_ohlcv_rows(selected[i : i + self.batch_limit])


@pytest.fixture
def store(tmp_path) -> ParquetCandleStore:
    return ParquetCandleStore(tmp_path / "candles")


@pytest.fixture
def t0() -> datetime:
    return datetime(2024, 1, 1, tzinfo=UTC)
