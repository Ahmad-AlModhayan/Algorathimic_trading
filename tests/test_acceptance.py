from datetime import UTC, datetime

from core.backtest.acceptance import Thresholds, evaluate, evaluate_instrument
from core.backtest.metrics import compute
from core.backtest.walkforward import Fold, FoldResult, WalkForwardResult
from tests.backtest_helpers import CLEAN, trade, ts

T = datetime(2024, 1, 1, tzinfo=UTC)


def _wf(fold_rs: list[list[float]], key: str = "test:X/USDT") -> WalkForwardResult:
    inst = CLEAN.model_copy(update={"symbol": key.split(":")[1]})
    wf = WalkForwardResult(strategy="fixed", instrument=inst)
    for i, rs in enumerate(fold_rs):
        trades = [trade(r, i=j) for j, r in enumerate(rs)]
        wf.folds.append(FoldResult(Fold(i, T, T, T), {}, compute([]), trades, compute(trades)))
    return wf


GOOD = [[2, -1] * 10] * 10  # 200 trades, PF 2, every fold positive


def test_passing_instrument():
    rep = evaluate_instrument(_wf(GOOD))
    assert rep.passed and rep.failures == []


def test_each_criterion_flips_independently():
    assert "n_trades" in evaluate_instrument(_wf([[2, -1] * 5] * 3)).failures
    assert "profit_factor" in evaluate_instrument(_wf([[1, -1] * 10] * 10)).failures
    bad_folds = [[2, -1] * 10] * 6 + [[-1, 2, -1, -1] * 5] * 4  # 6/10 positive
    assert "positive_fold_share" in evaluate_instrument(_wf(bad_folds)).failures
    dd = [[-1] * 25 + [2] * 20] * 10  # 25 straight losses at 1% -> ~25% DD
    assert "max_drawdown_pct" in evaluate_instrument(_wf(dd)).failures


def test_strategy_enabled_only_with_three_instruments_and_both_regimes():
    regimes = {"bull": (ts(0), ts(30)), "bear": (ts(0), ts(30))}
    three = [_wf(GOOD, f"test:{s}/USDT") for s in ("A", "B", "C")]
    rep = evaluate(three, regimes)
    assert rep.enabled and rep.reasons == []
    two = evaluate(three[:2], regimes)
    assert not two.enabled and any("instruments passing" in r for r in two.reasons)
    no_bear = evaluate(three, {"bull": (ts(0), ts(30))})
    assert not no_bear.enabled
    empty_bear = evaluate(three, {"bull": (ts(0), ts(30)), "bear": (ts(100), ts(200))})
    assert not empty_bear.enabled and any("regime bear" in r for r in empty_bear.reasons)


def test_thresholds_are_configurable():
    loose = Thresholds(min_trades=10, min_instruments=1)
    rep = evaluate(
        [_wf([[2, -1] * 5] * 3)], {"bull": (ts(0), ts(30)), "bear": (ts(0), ts(30))}, loose
    )
    assert rep.enabled
