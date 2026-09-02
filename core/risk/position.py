"""PositionManager: manages an open position per its plan on each closed candle.

Actions are instructions, not executions (V1). The manager also updates the Position in place
so callers do not have to replay actions.

Per candle, in this order:
  1. exits against the stop/target as they stood at the candle open (worst case if both touch)
  2. time stop
  3. partial exit at +N R, break-even move at +N R, trailing move (in R below highest close)
A stop moved during a candle cannot be hit by that same candle: that would be lookahead.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from core.models import Action, Candle, Plan, Position


def open_position(
    plan: Plan, entry_price: float, opened_at: datetime, qty: float | None = None
) -> Position:
    return Position(
        id=uuid.uuid4().hex[:12],
        plan=plan,
        qty=qty if qty is not None else plan.qty,
        entry_price=entry_price,
        opened_at=opened_at,
        stop=plan.setup.stop,
        target=plan.setup.target,
        highest_close=entry_price,
        lowest_close=entry_price,
    )


class PositionManager:
    def on_candle(self, position: Position, candle: Candle) -> list[Action]:
        if position.closed:
            return []
        p = position
        long = p.side == "long"
        r = p.r_per_unit
        rules = p.plan.management
        acts: list[Action] = []
        ts = candle.ts

        # 1. exits on the stop/target in force at candle open
        stop_hit = candle.low <= p.stop if long else candle.high >= p.stop
        target_hit = candle.high >= p.target if long else candle.low <= p.target
        if stop_hit:
            px = min(candle.open, p.stop) if long else max(candle.open, p.stop)
            reason = "stop" if not p.break_even_done and p.stop == p.plan.setup.stop else "trail"
            acts.append(Action(kind="exit", reason=reason, price=px, qty=p.qty, ts=ts))
            p.closed = True
            p.bars_held += 1
            return acts
        if target_hit:
            acts.append(Action(kind="exit", reason="target", price=p.target, qty=p.qty, ts=ts))
            p.closed = True
            p.bars_held += 1
            return acts

        p.bars_held += 1
        p.highest_close = max(p.highest_close, candle.close)
        p.lowest_close = min(p.lowest_close, candle.close)

        # 2. time stop
        if rules.time_stop_bars is not None and p.bars_held >= rules.time_stop_bars:
            acts.append(Action(kind="exit", reason="time", price=candle.close, qty=p.qty, ts=ts))
            p.closed = True
            return acts

        # 3. management moves, using this candle's extremes (they apply from the next candle)
        favorable = (candle.high - p.entry_price) if long else (p.entry_price - candle.low)
        reached_r = favorable / r if r > 0 else 0.0

        if (
            rules.partial_exit_at_r is not None
            and not p.partial_done
            and reached_r >= rules.partial_exit_at_r
        ):
            level = p.entry_price + (
                rules.partial_exit_at_r * r if long else -rules.partial_exit_at_r * r
            )
            part = p.qty * rules.partial_fraction
            acts.append(
                Action(
                    kind="partial_exit",
                    reason=f"+{rules.partial_exit_at_r}R",
                    price=level,
                    qty=part,
                    ts=ts,
                )
            )
            p.qty -= part
            p.partial_done = True

        be_ready = (
            rules.break_even_at_r is not None
            and not p.break_even_done
            and reached_r >= rules.break_even_at_r
        )
        if be_ready and (
            (long and p.entry_price > p.stop) or (not long and p.entry_price < p.stop)
        ):
            p.stop = p.entry_price
            p.break_even_done = True
            acts.append(Action(kind="move_stop", reason="break-even", price=p.stop, ts=ts))

        if rules.trail_r is not None:
            new_stop = (
                (p.highest_close - rules.trail_r * r)
                if long
                else (p.lowest_close + rules.trail_r * r)
            )
            if (long and new_stop > p.stop) or (not long and new_stop < p.stop):
                p.stop = new_stop
                acts.append(
                    Action(
                        kind="move_stop", reason=f"trail {rules.trail_r}R", price=new_stop, ts=ts
                    )
                )
        return acts
