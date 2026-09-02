"""Turn a walk-forward result into Insights: figures only. Templates decide the wording."""

from __future__ import annotations

from content.models import Insight
from core.backtest.acceptance import InstrumentReport, evaluate_instrument
from core.backtest.walkforward import WalkForwardResult


def _r(x: float, nd: int = 2) -> float:
    return round(x, nd)


def extract_insights(
    wf: WalkForwardResult, timeframe: str, report: InstrumentReport | None = None
) -> list[Insight]:
    """One Insight per kind that the data supports. Empty when there are no folds."""
    if not wf.folds:
        return []
    report = report or evaluate_instrument(wf)
    trades = wf.oos_trades
    m = wf.oos_metrics
    rule_text = wf.rule_text or wf.strategy
    base = {
        "strategy": wf.strategy,
        "instrument": wf.instrument.key,
        "timeframe": timeframe,
        "rule_text": rule_text,
        "period_start": wf.folds[0].fold.test_start,
        "period_end": wf.folds[-1].fold.test_end,
    }
    out: list[Insight] = []
    if m.n_trades:
        out.append(
            Insight(
                kind="result_summary",
                **base,
                figures={
                    "n_trades": m.n_trades,
                    "win_rate_pct": _r(m.win_rate * 100, 1),
                    "profit_factor": _r(m.profit_factor)
                    if m.profit_factor != float("inf")
                    else 99.0,
                    "expectancy_r": _r(m.expectancy_r, 3),
                    "total_r": _r(m.total_r, 1),
                    "max_dd_pct": _r(m.max_drawdown_pct, 1),
                    "n_folds": len(wf.folds),
                },
            )
        )
        # Trades come from the simulator with risk_amount=1, so fees are already in R.
        fees_r = sum(t.fees for t in trades)
        gross_r = m.total_r + fees_r
        out.append(
            Insight(
                kind="fees_impact",
                **base,
                figures={
                    "gross_r": _r(gross_r, 1),
                    "fees_r": _r(fees_r, 1),
                    "net_r": _r(m.total_r, 1),
                    "fees_share_pct": _r(100 * fees_r / abs(gross_r), 1) if gross_r else 0.0,
                    "n_trades": m.n_trades,
                },
            )
        )
        folds = sorted(wf.folds, key=lambda f: f.test_metrics.expectancy_r)
        worst, best = folds[0], folds[-1]
        out.append(
            Insight(
                kind="fold_spread",
                **base,
                figures={
                    "n_folds": len(wf.folds),
                    "positive_folds": sum(f.test_metrics.expectancy_r > 0 for f in wf.folds),
                    "best_period": f"{best.fold.test_start:%Y-%m}",
                    "best_r": _r(best.test_metrics.total_r, 1),
                    "worst_period": f"{worst.fold.test_start:%Y-%m}",
                    "worst_r": _r(worst.test_metrics.total_r, 1),
                },
            )
        )
    out.append(
        Insight(
            kind="gate_outcome",
            **base,
            figures={
                "passed": report.passed,
                "failed": ", ".join(report.failures) or "-",
                **{f"{c.name}": _r(c.value, 2) for c in report.criteria},
                **{f"{c.name}_threshold": c.threshold for c in report.criteria},
            },
        )
    )
    return out
