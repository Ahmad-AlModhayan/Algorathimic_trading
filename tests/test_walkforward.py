from datetime import UTC, datetime

import polars as pl

from core.backtest.walkforward import add_months, grid, make_folds, walk_forward
from core.strategies.breakout import Breakout
from tests.backtest_helpers import CLEAN, bars


def test_add_months_wraps_year():
    assert add_months(datetime(2024, 11, 1, tzinfo=UTC), 3) == datetime(2025, 2, 1, tzinfo=UTC)


def test_make_folds_tiles_range():
    folds = make_folds(datetime(2024, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC))
    assert len(folds) == 9
    assert folds[0].train_start == datetime(2024, 1, 1, tzinfo=UTC)
    assert folds[0].test_start == datetime(2024, 7, 1, tzinfo=UTC)
    assert folds[0].test_end == datetime(2024, 9, 1, tzinfo=UTC)
    assert folds[-1].test_end == datetime(2026, 1, 1, tzinfo=UTC)
    for a, b in zip(folds, folds[1:], strict=False):
        assert b.test_start == a.test_end  # no overlap, no gap


def test_grid():
    assert grid({"n": [1, 2], "k": ["a"]}) == [{"n": 1, "k": "a"}, {"n": 2, "k": "a"}]


def _synthetic_year() -> pl.DataFrame:
    """Sawtooth uptrend: 5 flat bars then a breakout bar, repeated; 4h bars for ~14 months."""
    rows = []
    price = 100.0
    for _ in range(430):
        rows += [(price, price + 1, price - 1, price)] * 5
        rows.append((price, price + 4, price - 1, price + 3))
        price += 3
    return bars(rows, t0=datetime(2024, 1, 1, tzinfo=UTC))


def test_walk_forward_selects_on_train_and_reports_oos():
    candles = _synthetic_year()
    res = walk_forward(
        candles, CLEAN, Breakout, {"n": [3, 5], "atr_n": [3], "target_r": [1.0, 2.0]}
    )
    assert res.strategy == "breakout" and "high(" in res.rule_text
    assert len(res.folds) == 4  # Jan 2024 .. ~Mar 2025 -> 4 complete folds
    for f in res.folds:
        assert f.params in grid({"n": [3, 5], "atr_n": [3], "target_r": [1.0, 2.0]})
        assert f.train_metrics.n_trades > 0
        for t in f.test_trades:
            assert f.fold.test_start <= t.setup_ts < f.fold.test_end
    assert len(res.oos_trades) == sum(len(f.test_trades) for f in res.folds)
    assert res.oos_metrics.n_trades == len(res.oos_trades)
    assert 0 <= res.positive_fold_share <= 1
