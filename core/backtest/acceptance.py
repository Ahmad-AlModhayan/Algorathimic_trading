"""Acceptance criteria. A strategy is enabled only if ALL hold on combined out-of-sample folds.
A failed report is a valid, logged result, not an error."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from core.backtest.metrics import compute
from core.backtest.trades import Trade
from core.backtest.walkforward import WalkForwardResult


class Thresholds(BaseModel):
    min_profit_factor: float = 1.3
    max_drawdown_pct: float = 20.0
    min_trades: int = 100
    min_positive_fold_share: float = 0.7
    min_instruments: int = 3


DEFAULT_THRESHOLDS = Thresholds()


class Criterion(BaseModel):
    name: str
    value: float
    threshold: float
    passed: bool


class InstrumentReport(BaseModel):
    strategy: str
    instrument: str
    n_folds: int
    criteria: list[Criterion]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.criteria)

    @property
    def failures(self) -> list[str]:
        return [c.name for c in self.criteria if not c.passed]


class RegimeReport(BaseModel):
    label: str  # "bull" | "bear"
    start: datetime
    end: datetime
    n_trades: int
    expectancy_r: float

    @property
    def passed(self) -> bool:
        return self.n_trades > 0 and self.expectancy_r > 0


class AcceptanceReport(BaseModel):
    strategy: str
    instruments: list[InstrumentReport]
    regimes: list[RegimeReport]
    thresholds: Thresholds
    enabled: bool
    reasons: list[str]  # empty when enabled


def evaluate_instrument(
    wf: WalkForwardResult, thresholds: Thresholds = DEFAULT_THRESHOLDS
) -> InstrumentReport:
    m = wf.oos_metrics
    share = wf.positive_fold_share
    criteria = [
        Criterion(
            name="profit_factor",
            value=m.profit_factor,
            threshold=thresholds.min_profit_factor,
            passed=m.profit_factor >= thresholds.min_profit_factor,
        ),
        Criterion(
            name="max_drawdown_pct",
            value=m.max_drawdown_pct,
            threshold=thresholds.max_drawdown_pct,
            passed=m.max_drawdown_pct <= thresholds.max_drawdown_pct,
        ),
        Criterion(
            name="n_trades",
            value=m.n_trades,
            threshold=thresholds.min_trades,
            passed=m.n_trades >= thresholds.min_trades,
        ),
        Criterion(
            name="positive_fold_share",
            value=share,
            threshold=thresholds.min_positive_fold_share,
            passed=share >= thresholds.min_positive_fold_share,
        ),
    ]
    return InstrumentReport(
        strategy=wf.strategy,
        instrument=wf.instrument.key,
        n_folds=len(wf.folds),
        criteria=criteria,
    )


def evaluate_regime(
    label: str, start: datetime, end: datetime, trades: list[Trade]
) -> RegimeReport:
    inside = [t for t in trades if start <= t.entry_ts < end]
    return RegimeReport(
        label=label,
        start=start,
        end=end,
        n_trades=len(inside),
        expectancy_r=compute(inside).expectancy_r,
    )


def evaluate(
    results: list[WalkForwardResult],
    regimes: dict[str, tuple[datetime, datetime]],
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> AcceptanceReport:
    """`regimes` must contain at least one 'bull' and one 'bear' window. Each is checked on
    the pooled out-of-sample trades across instruments."""
    if not results:
        raise ValueError("no walk-forward results")
    strategy = results[0].strategy
    inst_reports = [evaluate_instrument(r, thresholds) for r in results]
    pooled = [t for r in results for t in r.oos_trades]
    regime_reports = [evaluate_regime(k, s, e, pooled) for k, (s, e) in regimes.items()]

    reasons: list[str] = []
    passing = [r for r in inst_reports if r.passed]
    for r in inst_reports:
        if not r.passed:
            reasons.append(f"{r.instrument}: failed {', '.join(r.failures)}")
    if len(passing) < thresholds.min_instruments:
        reasons.append(f"instruments passing: {len(passing)} < {thresholds.min_instruments}")
    labels = {r.label for r in regime_reports}
    if not {"bull", "bear"} <= labels:
        reasons.append("regimes must include one bull and one bear window")
    for r in regime_reports:
        if not r.passed:
            reasons.append(
                f"regime {r.label}: expectancy {r.expectancy_r:.3f}R on {r.n_trades} trades"
            )

    return AcceptanceReport(
        strategy=strategy,
        instruments=inst_reports,
        regimes=regime_reports,
        thresholds=thresholds,
        enabled=not reasons,
        reasons=reasons,
    )
