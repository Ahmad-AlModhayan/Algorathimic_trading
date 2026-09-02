"""The 'community strategy list': what the nightly job runs. Plain rules, plain instruments.
Extend here; nothing else in the pipeline needs to change."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import Instrument
from core.strategies.breakout import Breakout

DEFAULT_SLIPPAGE = 0.0005
DEFAULT_FEE = 0.001


def binance_spot(symbol: str, tick: float, lot: float) -> Instrument:
    return Instrument(
        venue="binance",
        symbol=symbol,
        asset_class="crypto",
        tick_size=tick,
        lot_size=lot,
        fee_pct=DEFAULT_FEE,
        slippage_pct=DEFAULT_SLIPPAGE,
    )


@dataclass(frozen=True)
class StrategyEntry:
    name: str
    factory: Any  # StrategyFactory
    grid: dict[str, list]
    timeframe: str = "4h"
    instruments: list[Instrument] = field(default_factory=list)


INSTRUMENTS = [
    binance_spot("BTC/USDT", 0.01, 0.00001),
    binance_spot("ETH/USDT", 0.01, 0.0001),
    binance_spot("SOL/USDT", 0.01, 0.001),
]

STRATEGY_LIST: list[StrategyEntry] = [
    StrategyEntry(
        name="breakout",
        factory=Breakout,
        grid={
            "n": [10, 20, 40],
            "atr_n": [14],
            "atr_mult": [1.5, 2.0, 3.0],
            "target_r": [1.5, 2.0, 3.0],
        },
        instruments=INSTRUMENTS,
    ),
]
