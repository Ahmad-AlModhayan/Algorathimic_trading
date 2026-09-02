"""breakout(N): close above the highest high of the previous N bars. ATR stop, fixed-R target.

The first swing strategy. Parameters map 1:1 onto the rule DSL primitives (breakout(N),
ATR stop, fixed-R target) so the lab can compile the same thing later.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl

from core.models import Instrument, Setup
from core.strategies.base import atr, round_to_tick


class Breakout:
    name = "breakout"
    style = "swing"

    def __init__(
        self,
        instrument: Instrument,
        timeframe: str = "4h",
        n: int = 20,
        atr_n: int = 14,
        atr_mult: float = 2.0,
        target_r: float = 2.0,
        allow_short: bool = False,
    ) -> None:
        if n < 2 or atr_n < 1 or atr_mult <= 0 or target_r <= 0:
            raise ValueError("invalid breakout parameters")
        self.instrument = instrument
        self.timeframe = timeframe
        self.n = n
        self.atr_n = atr_n
        self.atr_mult = atr_mult
        self.target_r = target_r
        self.allow_short = allow_short

    @property
    def params(self) -> dict[str, float | int | bool]:
        return {
            "n": self.n,
            "atr_n": self.atr_n,
            "atr_mult": self.atr_mult,
            "target_r": self.target_r,
            "allow_short": self.allow_short,
        }

    @property
    def warmup(self) -> int:
        return max(self.n, self.atr_n) + 1

    @property
    def rule_text(self) -> str:
        return (
            f"close > high({self.n}) | stop = close - {self.atr_mult}*ATR({self.atr_n}) "
            f"| target = {self.target_r}R"
        )

    def generate(self, candles: pl.DataFrame) -> list[Setup]:
        if candles.height < self.warmup:
            return []
        df = candles.with_columns(
            prev_high=pl.col("high").shift(1).rolling_max(window_size=self.n),
            prev_low=pl.col("low").shift(1).rolling_min(window_size=self.n),
            atr=atr(candles, self.atr_n),
        ).with_columns(
            long_ok=(pl.col("close") > pl.col("prev_high")) & (pl.col("atr") > 0),
            short_ok=(pl.col("close") < pl.col("prev_low")) & (pl.col("atr") > 0),
        )
        tick = self.instrument.tick_size
        setups: list[Setup] = []
        for ts, close, a, long_ok, short_ok in df.select(
            "ts", "close", "atr", "long_ok", "short_ok"
        ).iter_rows():
            if long_ok:
                stop = round_to_tick(close - self.atr_mult * a, tick)
                entry = round_to_tick(close, tick)
                target = round_to_tick(entry + self.target_r * (entry - stop), tick)
                if stop < entry < target:
                    setups.append(self._setup("long", entry, stop, target, ts))
            elif short_ok and self.allow_short:
                stop = round_to_tick(close + self.atr_mult * a, tick)
                entry = round_to_tick(close, tick)
                target = round_to_tick(entry - self.target_r * (stop - entry), tick)
                if target < entry < stop:
                    setups.append(self._setup("short", entry, stop, target, ts))
        return setups

    def _setup(self, side: str, entry: float, stop: float, target: float, ts: datetime) -> Setup:
        return Setup(
            strategy=self.name,
            instrument=self.instrument,
            side=side,  # type: ignore[arg-type]
            entry=entry,
            stop=stop,
            target=target,
            rule_text=self.rule_text,
            ts=ts,
        )
