"""Built-in rules, one per style. These are what the nightly job runs and what the lab shows
as starting points. All expressed in the DSL so the lab can edit them."""

from __future__ import annotations

from core.strategies.dsl import (
    ATRStop,
    Breakout,
    FixedRTarget,
    MACross,
    RSIThreshold,
    Rule,
    TrendFilter,
)

SWING_BREAKOUT = Rule(
    name="breakout",
    style="swing",
    timeframe="4h",
    side="long",
    entry=[Breakout(n=20)],
    stop=ATRStop(n=14, mult=2.0),
    target=FixedRTarget(r=2.0),
)

INTRADAY_MA_CROSS = Rule(
    name="ma_cross",
    style="intraday",
    timeframe="1h",
    side="long",
    entry=[MACross(fast=20, slow=50)],
    filters=[TrendFilter(n=200)],
    stop=ATRStop(n=14, mult=1.5),
    target=FixedRTarget(r=1.5),
)

SCALP_RSI = Rule(
    name="rsi_pullback",
    style="scalp",
    timeframe="15m",
    side="long",
    entry=[RSIThreshold(n=14, level=30, op="<")],
    filters=[TrendFilter(n=100)],
    stop=ATRStop(n=14, mult=1.0),
    target=FixedRTarget(r=1.0),
)

LIBRARY: dict[str, Rule] = {r.name: r for r in (SWING_BREAKOUT, INTRADAY_MA_CROSS, SCALP_RSI)}
STRATEGY_STYLES = {r.name: r.style for r in LIBRARY.values()}
