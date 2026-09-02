"""Metrics over a list of Trades. Shared by both engines and by the content pipeline."""

from __future__ import annotations

import math

from pydantic import BaseModel

from core.backtest.trades import Trade


class Metrics(BaseModel):
    n_trades: int
    wins: int
    losses: int
    win_rate: float
    total_r: float
    expectancy_r: float  # mean R per trade
    avg_win_r: float
    avg_loss_r: float
    profit_factor: float  # gross profit / gross loss; inf when no losses; 0 when no trades
    max_drawdown_pct: float  # on a fixed-fraction equity curve (no compounding)
    r_p10: float
    r_p50: float
    r_p90: float
    stops: int
    targets: int
    ends: int


def compute(trades: list[Trade], risk_pct: float = 1.0) -> Metrics:
    """`risk_pct` is the account fraction risked per trade (1.0 = 1%); it turns R into equity
    for the drawdown figure. Nothing else depends on it."""
    n = len(trades)
    if n == 0:
        return Metrics(
            n_trades=0,
            wins=0,
            losses=0,
            win_rate=0.0,
            total_r=0.0,
            expectancy_r=0.0,
            avg_win_r=0.0,
            avg_loss_r=0.0,
            profit_factor=0.0,
            max_drawdown_pct=0.0,
            r_p10=0.0,
            r_p50=0.0,
            r_p90=0.0,
            stops=0,
            targets=0,
            ends=0,
        )
    rs = [t.r_multiple for t in trades]
    win_rs = [r for r in rs if r > 0]
    loss_rs = [r for r in rs if r <= 0]
    gross_profit = sum(win_rs)
    gross_loss = -sum(loss_rs)
    pf = math.inf if gross_loss == 0 else gross_profit / gross_loss

    equity = peak = 1.0
    max_dd = 0.0
    for r in rs:
        equity += r * risk_pct / 100.0
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)

    srt = sorted(rs)
    return Metrics(
        n_trades=n,
        wins=len(win_rs),
        losses=len(loss_rs),
        win_rate=len(win_rs) / n,
        total_r=sum(rs),
        expectancy_r=sum(rs) / n,
        avg_win_r=sum(win_rs) / len(win_rs) if win_rs else 0.0,
        avg_loss_r=sum(loss_rs) / len(loss_rs) if loss_rs else 0.0,
        profit_factor=pf,
        max_drawdown_pct=max_dd * 100.0,
        r_p10=_pct(srt, 0.10),
        r_p50=_pct(srt, 0.50),
        r_p90=_pct(srt, 0.90),
        stops=sum(t.exit_reason == "stop" for t in trades),
        targets=sum(t.exit_reason == "target" for t in trades),
        ends=sum(t.exit_reason == "end" for t in trades),
    )


def _pct(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)
