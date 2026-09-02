"""Reference bar simulator. Implements the acceptance rules exactly:

- Entry: the setup bar closes, the order goes out, and it fills at `entry * (1 +/- slippage)`
  at that close. (Nautilus fills the same marketable limit at the close itself; the slippage
  is our conservative margin on top.)
- Exit: checked from the bar after entry. Stop/target fill on the touching bar. Both touched
  -> stop (worst case). Stops pay slippage and gap through (fill at min(open, stop) for longs).
  Targets fill at target.
- Fees from `Instrument.fee_pct` on both sides. One position per instrument at a time.
- Sizing: `risk_amount` per trade, so PnL is directly in R when risk_amount == 1.

Deterministic, no randomness, no lookahead beyond what the strategy itself does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import polars as pl

from core.backtest.trades import Trade
from core.models import Instrument, Setup
from core.strategies.base import Strategy


@dataclass
class _Open:
    setup: Setup
    entry_ts: datetime
    entry_price: float
    qty: float
    entry_fee: float
    entry_idx: int


def simulate(
    candles: pl.DataFrame,
    strategy: Strategy,
    instrument: Instrument,
    start: datetime | None = None,
    end: datetime | None = None,
    risk_amount: float = 1.0,
) -> list[Trade]:
    """Run `strategy` over `candles`. Setups are admitted only in [start, end); bars before
    `start` serve as warmup. An open position at the last bar closes at that bar's close."""
    if end is not None:
        candles = candles.filter(pl.col("ts") < end)
    setups_by_ts: dict[datetime, Setup] = {}
    for s in strategy.generate(candles):
        if (start is None or s.ts >= start) and s.ts not in setups_by_ts:
            setups_by_ts[s.ts] = s

    if start is not None:
        candles = candles.filter(pl.col("ts") >= start)
    if candles.is_empty():
        return []

    fee = instrument.fee_pct
    slip = instrument.slippage_pct
    trades: list[Trade] = []
    pos: _Open | None = None

    rows = candles.select("ts", "open", "high", "low", "close").iter_rows()
    last = None
    for i, (ts, o, h, lo, c) in enumerate(rows):
        last = (i, ts, c)
        # a) exits on bars after the entry bar
        if pos is not None and i > pos.entry_idx:
            done = _try_exit(pos, i, ts, o, h, lo, fee, slip, instrument, risk_amount)
            if done is not None:
                trades.append(done)
                pos = None
        # b) a setup on this bar enters at this bar's close
        if pos is None and ts in setups_by_ts:
            pos = _enter(setups_by_ts[ts], i, ts, fee, slip, risk_amount)

    if pos is not None and last is not None:
        i, ts, c = last
        if i > pos.entry_idx:
            trades.append(_close(pos, i, ts, c, "end", fee, instrument, risk_amount))
        else:  # entered on the very last bar: flat it at the same close
            trades.append(_close(pos, i, ts, c, "end", fee, instrument, risk_amount))
    return trades


def _enter(s: Setup, i: int, ts: datetime, fee: float, slip: float, risk: float) -> _Open | None:
    limit = s.entry * (1 + slip) if s.side == "long" else s.entry * (1 - slip)
    risk_per_unit = abs(limit - s.stop)
    if risk_per_unit <= 0:
        return None
    qty = risk / risk_per_unit
    return _Open(s, ts, limit, qty, limit * qty * fee, i)


def _try_exit(
    pos: _Open,
    i: int,
    ts: datetime,
    o: float,
    h: float,
    lo: float,
    fee: float,
    slip: float,
    inst: Instrument,
    risk: float,
) -> Trade | None:
    s = pos.setup
    if s.side == "long":
        stop_hit, target_hit = lo <= s.stop, h >= s.target
        if stop_hit:
            px = min(o, s.stop) * (1 - slip)
            return _close(pos, i, ts, px, "stop", fee, inst, risk)
        if target_hit:
            return _close(pos, i, ts, s.target, "target", fee, inst, risk)
    else:
        stop_hit, target_hit = h >= s.stop, lo <= s.target
        if stop_hit:
            px = max(o, s.stop) * (1 + slip)
            return _close(pos, i, ts, px, "stop", fee, inst, risk)
        if target_hit:
            return _close(pos, i, ts, s.target, "target", fee, inst, risk)
    return None


def _close(
    pos: _Open,
    i: int,
    ts: datetime,
    px: float,
    reason: str,
    fee: float,
    inst: Instrument,
    risk: float,
) -> Trade:
    s = pos.setup
    direction = 1 if s.side == "long" else -1
    exit_fee = px * pos.qty * fee
    fees = pos.entry_fee + exit_fee
    pnl = direction * (px - pos.entry_price) * pos.qty - fees
    return Trade(
        strategy=s.strategy,
        venue=inst.venue,
        symbol=inst.symbol,
        side=s.side,
        setup_ts=s.ts,
        entry_ts=pos.entry_ts,
        entry_price=pos.entry_price,
        exit_ts=ts,
        exit_price=px,
        exit_reason=reason,  # type: ignore[arg-type]
        qty=pos.qty,
        stop=s.stop,
        target=s.target,
        fees=fees,
        pnl=pnl,
        r_multiple=pnl / risk,
        bars_held=i - pos.entry_idx,
    )
