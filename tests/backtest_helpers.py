"""Shared builders for backtest tests: hand-built bars, fixed-setup strategies, trades."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from core.backtest.trades import Trade
from core.data.candles import normalize
from core.models import Instrument, Setup

STEP = timedelta(hours=4)
T0 = datetime(2024, 1, 1, tzinfo=UTC)

CLEAN = Instrument(
    venue="test",
    symbol="X/USDT",
    asset_class="crypto",
    tick_size=0.01,
    lot_size=0.001,
    fee_pct=0.0,
    slippage_pct=0.0,
)
COSTLY = CLEAN.model_copy(update={"fee_pct": 0.001, "slippage_pct": 0.001})


def bars(rows: list[tuple[float, float, float, float]], t0: datetime = T0) -> pl.DataFrame:
    """rows of (open, high, low, close), 4h apart starting at t0."""
    schema = {
        "ts": pl.Datetime("us", "UTC"),
        "open": pl.Float64,
        "high": pl.Float64,
        "low": pl.Float64,
        "close": pl.Float64,
        "volume": pl.Float64,
    }
    return normalize(
        pl.DataFrame(
            {
                "ts": [t0 + i * STEP for i in range(len(rows))],
                "open": [float(r[0]) for r in rows],
                "high": [float(r[1]) for r in rows],
                "low": [float(r[2]) for r in rows],
                "close": [float(r[3]) for r in rows],
                "volume": [1.0] * len(rows),
            },
            schema=schema,
        )
    )


def ts(i: int, t0: datetime = T0) -> datetime:
    return t0 + i * STEP


class FixedSetups:
    """Strategy that emits exactly the given setups. Causal by construction."""

    name = "fixed"
    style = "swing"
    timeframe = "4h"
    warmup = 0

    def __init__(self, setups: list[Setup]) -> None:
        self.setups = setups

    def generate(self, candles: pl.DataFrame) -> list[Setup]:
        last = candles["ts"].max()
        return [s for s in self.setups if last is not None and s.ts <= last]


def setup(
    i: int,
    side: str = "long",
    entry: float = 100,
    stop: float = 95,
    target: float = 110,
    inst: Instrument = CLEAN,
) -> Setup:
    return Setup(
        strategy="fixed",
        instrument=inst,
        side=side,
        entry=entry,
        stop=stop,  # type: ignore[arg-type]
        target=target,
        rule_text="fixed",
        ts=ts(i),
    )


def trade(r: float, i: int = 0, reason: str = "target") -> Trade:
    return Trade(
        strategy="fixed",
        venue="test",
        symbol="X/USDT",
        side="long",
        setup_ts=ts(i),
        entry_ts=ts(i + 1),
        entry_price=100.0,
        exit_ts=ts(i + 2),
        exit_price=100.0 + 5 * r,
        exit_reason=reason,
        qty=0.2,
        stop=95.0,
        target=110.0,
        fees=0.0,
        pnl=r,  # type: ignore[arg-type]
        r_multiple=r,
        bars_held=1,
    )
