from __future__ import annotations

from datetime import UTC, datetime

from content.models import Insight
from core.backtest.metrics import compute
from core.backtest.walkforward import Fold, FoldResult, WalkForwardResult
from core.models import Instrument
from tests.backtest_helpers import trade

BTC = Instrument(
    venue="binance",
    symbol="BTC/USDT",
    asset_class="crypto",
    tick_size=0.01,
    lot_size=0.00001,
    fee_pct=0.001,
    slippage_pct=0.0005,
)
T = datetime(2024, 1, 1, tzinfo=UTC)


def wf_result(fold_rs: list[list[float]] | None = None) -> WalkForwardResult:
    fold_rs = fold_rs or [[2, -1, 2, -1, 0.5]] * 3
    wf = WalkForwardResult(
        strategy="breakout",
        instrument=BTC,
        rule_text="close > high(20) | stop = close - 2.0*ATR(14) | target = 2.0R",
    )
    for i, rs in enumerate(fold_rs):
        trades = [trade(r, i=i * 10 + j) for j, r in enumerate(rs)]
        fold = Fold(i, T.replace(month=1 + i), T.replace(month=7 + i), T.replace(month=9 + i))
        wf.folds.append(FoldResult(fold, {"n": 20}, compute([]), trades, compute(trades)))
    return wf


def sample_insight(kind: str = "result_summary") -> Insight:
    figures = {
        "result_summary": {
            "n_trades": 137,
            "win_rate_pct": 41.6,
            "profit_factor": 1.42,
            "expectancy_r": 0.21,
            "total_r": 28.7,
            "max_dd_pct": 12.3,
            "n_folds": 9,
        },
        "fees_impact": {
            "gross_r": 41.2,
            "fees_r": 12.5,
            "net_r": 28.7,
            "fees_share_pct": 30.3,
            "n_trades": 137,
        },
        "gate_outcome": {
            "passed": False,
            "failed": "n_trades",
            "profit_factor": 1.42,
            "max_drawdown_pct": 12.3,
            "n_trades": 87,
            "positive_fold_share": 0.78,
            "profit_factor_threshold": 1.3,
            "max_drawdown_pct_threshold": 20.0,
            "n_trades_threshold": 100,
            "positive_fold_share_threshold": 0.7,
        },
        "fold_spread": {
            "n_folds": 9,
            "positive_folds": 7,
            "best_period": "2024-11",
            "best_r": 9.1,
            "worst_period": "2025-03",
            "worst_r": -4.2,
        },
    }[kind]
    return Insight(
        kind=kind,
        strategy="breakout",
        instrument="binance:BTC/USDT",
        timeframe="4h",  # type: ignore[arg-type]
        rule_text="close > high(20) | stop = close - 2.0*ATR(14) | target = 2.0R",
        period_start=T,
        period_end=T.replace(year=2025),
        figures=figures,
    )
