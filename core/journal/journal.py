"""Journal: records what happened, computes analytics, feeds risk back.

Feedback rules (conservative, explicit):
- 5 consecutive losses -> downgrade: risk multiplier 0.5 until a win
- drawdown in cumulative R >= 10R -> pause until reviewed
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from core.models import Analytics, Fill, Outcome, Plan, RiskAdjustment, Style

LOSING_STREAK_FOR_DOWNGRADE = 5
DRAWDOWN_R_FOR_PAUSE = 10.0


class JournalEntry(BaseModel):
    user_id: str
    plan: Plan
    fills: list[Fill]
    outcome: Outcome

    @property
    def style(self) -> Style | None:
        return None  # resolved through the registry passed to Journal


@dataclass
class Journal:
    strategy_styles: dict[str, Style] = field(default_factory=dict)
    path: Path | None = None  # optional JSON persistence
    _entries: list[JournalEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.path and self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._entries = [JournalEntry.model_validate(e) for e in raw]

    def record(self, plan: Plan, fills: list[Fill], outcome: Outcome) -> None:
        self._entries.append(
            JournalEntry(user_id=plan.user_id, plan=plan, fills=fills, outcome=outcome)
        )
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps([e.model_dump(mode="json") for e in self._entries], ensure_ascii=False),
                encoding="utf-8",
            )

    def entries(self, user_id: str) -> list[JournalEntry]:
        return sorted(
            (e for e in self._entries if e.user_id == user_id), key=lambda e: e.outcome.closed_at
        )

    def analytics(self, user_id: str) -> Analytics:
        es = self.entries(user_id)
        rs = [e.outcome.r_multiple for e in es]
        n = len(rs)
        if n == 0:
            return Analytics(
                n_trades=0,
                win_rate=0.0,
                expectancy_r=0.0,
                total_r=0.0,
                profit_factor=0.0,
                max_drawdown_r=0.0,
                r_p10=0.0,
                r_p50=0.0,
                r_p90=0.0,
                by_style={},
                by_instrument={},
                by_hour={},
                current_streak=0,
            )
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        gross_loss = -sum(losses)
        cum = peak = dd = 0.0
        for r in rs:
            cum += r
            peak = max(peak, cum)
            dd = max(dd, peak - cum)
        groups: dict[str, dict[str, list[float]]] = {
            "style": defaultdict(list),
            "inst": defaultdict(list),
        }
        by_hour: dict[int, list[float]] = defaultdict(list)
        for e in es:
            style = self.strategy_styles.get(e.plan.setup.strategy, "unknown")
            groups["style"][style].append(e.outcome.r_multiple)
            groups["inst"][e.plan.setup.instrument.key].append(e.outcome.r_multiple)
            by_hour[e.plan.setup.ts.hour].append(e.outcome.r_multiple)
        srt = sorted(rs)
        return Analytics(
            n_trades=n,
            win_rate=len(wins) / n,
            expectancy_r=sum(rs) / n,
            total_r=sum(rs),
            profit_factor=math.inf if gross_loss == 0 else sum(wins) / gross_loss,
            max_drawdown_r=dd,
            r_p10=_pct(srt, 0.1),
            r_p50=_pct(srt, 0.5),
            r_p90=_pct(srt, 0.9),
            by_style={k: sum(v) / len(v) for k, v in groups["style"].items()},
            by_instrument={k: sum(v) / len(v) for k, v in groups["inst"].items()},
            by_hour={k: sum(v) / len(v) for k, v in sorted(by_hour.items())},
            current_streak=_streak(rs),
        )

    def feedback(self, user_id: str) -> RiskAdjustment:
        a = self.analytics(user_id)
        if a.n_trades == 0:
            return RiskAdjustment(kind="none", reason="no trades yet")
        if (
            a.max_drawdown_r >= DRAWDOWN_R_FOR_PAUSE
            and _trailing_drawdown(self.entries(user_id)) >= DRAWDOWN_R_FOR_PAUSE
        ):
            return RiskAdjustment(
                kind="pause",
                reason=f"drawdown {a.max_drawdown_r:.1f}R >= {DRAWDOWN_R_FOR_PAUSE}R",
                risk_multiplier=0.0,
            )
        if a.current_streak <= -LOSING_STREAK_FOR_DOWNGRADE:
            return RiskAdjustment(
                kind="downgrade",
                reason=f"{-a.current_streak} consecutive losses",
                risk_multiplier=0.5,
            )
        return RiskAdjustment(kind="none", reason="within limits")


def _streak(rs: list[float]) -> int:
    if not rs:
        return 0
    sign = 1 if rs[-1] > 0 else -1
    n = 0
    for r in reversed(rs):
        if (r > 0) == (sign > 0):
            n += 1
        else:
            break
    return n * sign


def _trailing_drawdown(es: list[JournalEntry]) -> float:
    """Current distance from the cumulative-R peak (not the historical max)."""
    cum = peak = 0.0
    for e in es:
        cum += e.outcome.r_multiple
        peak = max(peak, cum)
    return peak - cum


def _pct(sorted_vals: list[float], q: float) -> float:
    k = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def outcome_from(
    plan: Plan, fills: list[Fill], exit_reason: str, closed_at: datetime, bars_held: int
) -> Outcome:
    """Net PnL and R from fills: cash in from sells minus cash out for buys, minus fees.
    The sum of signed cash flows is the same formula for longs and shorts."""
    pnl = 0.0
    for f in fills:
        pnl += f.price * f.qty if f.side == "sell" else -f.price * f.qty
        pnl -= f.fee
    r = pnl / plan.risk_amount if plan.risk_amount else 0.0
    return Outcome(
        exit_reason=exit_reason, pnl=pnl, r_multiple=r, closed_at=closed_at, bars_held=bars_held
    )  # type: ignore[arg-type]
