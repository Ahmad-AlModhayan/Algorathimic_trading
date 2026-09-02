"""Strategy contract and shared helpers. A strategy is a pure function of past candles.

`generate` must be causal: the setup at ts T may only depend on candles with ts <= T.
Both engines rely on that; the parity test catches violations.
"""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

import polars as pl

from core.models import Setup, Style


@runtime_checkable
class Strategy(Protocol):
    name: str
    style: Style
    timeframe: str
    warmup: int  # bars needed before the first setup can be produced

    def generate(self, candles: pl.DataFrame) -> list[Setup]: ...


def round_to_tick(price: float, tick_size: float) -> float:
    """Round to the instrument grid. Uses the tick's decimal places so 0.1 stays 0.1."""
    decimals = max(0, -int(math.floor(math.log10(tick_size)))) if tick_size < 1 else 0
    return round(round(price / tick_size) * tick_size, decimals)


def true_range(df: pl.DataFrame) -> pl.Expr:
    prev_close = pl.col("close").shift(1)
    return pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )


def atr(df: pl.DataFrame, n: int) -> pl.Expr:
    """Simple-average ATR over n bars (not Wilder). Deterministic and easy to reproduce."""
    return true_range(df).rolling_mean(window_size=n)
