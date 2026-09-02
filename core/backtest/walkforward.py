"""Rolling walk-forward: train 6 months / test 2 months, stepping by the test length.

Parameters are chosen on the train window only, then frozen for the test window. Nothing
from one fold is reused in the next. Out-of-sample trades from all folds are concatenated
for the acceptance report.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

import polars as pl

from core.backtest.metrics import Metrics, compute
from core.backtest.simulator import simulate
from core.backtest.trades import Trade
from core.models import Instrument
from core.strategies.base import Strategy

StrategyFactory = Callable[..., Strategy]  # factory(instrument, **params) -> Strategy
Scorer = Callable[[Metrics], float]


@dataclass(frozen=True)
class Fold:
    index: int
    train_start: datetime
    train_end: datetime  # == test_start
    test_end: datetime

    @property
    def test_start(self) -> datetime:
        return self.train_end


@dataclass
class FoldResult:
    fold: Fold
    params: dict
    train_metrics: Metrics
    test_trades: list[Trade]
    test_metrics: Metrics


@dataclass
class WalkForwardResult:
    strategy: str
    instrument: Instrument
    folds: list[FoldResult] = field(default_factory=list)
    rule_text: str = ""  # rule of the most recent fold's chosen parameters

    @property
    def oos_trades(self) -> list[Trade]:
        return [t for f in self.folds for t in f.test_trades]

    @property
    def oos_metrics(self) -> Metrics:
        return compute(self.oos_trades)

    @property
    def positive_fold_share(self) -> float:
        if not self.folds:
            return 0.0
        return sum(f.test_metrics.expectancy_r > 0 for f in self.folds) / len(self.folds)


def add_months(dt: datetime, months: int) -> datetime:
    y, m = divmod(dt.month - 1 + months, 12)
    return dt.replace(year=dt.year + y, month=m + 1)


def make_folds(
    start: datetime,
    end: datetime,
    train_months: int = 6,
    test_months: int = 2,
    step_months: int | None = None,
) -> list[Fold]:
    """Folds whose test window ends at or before `end`. Steps by `test_months` by default,
    so test windows tile the range without overlap."""
    step = step_months or test_months
    folds: list[Fold] = []
    i = 0
    train_start = start
    while True:
        train_end = add_months(train_start, train_months)
        test_end = add_months(train_end, test_months)
        if test_end > end:
            break
        folds.append(Fold(i, train_start, train_end, test_end))
        i += 1
        train_start = add_months(train_start, step)
    return folds


def default_score(m: Metrics) -> float:
    """Net R, but a parameter set with too few train trades cannot win."""
    return m.total_r if m.n_trades >= 10 else float("-inf")


def grid(param_grid: dict[str, Iterable]) -> list[dict]:
    keys = list(param_grid)
    return [
        dict(zip(keys, combo, strict=True)) for combo in itertools.product(*param_grid.values())
    ]


def walk_forward(
    candles: pl.DataFrame,
    instrument: Instrument,
    factory: StrategyFactory,
    param_grid: dict[str, Iterable],
    folds: list[Fold] | None = None,
    train_months: int = 6,
    test_months: int = 2,
    score: Scorer = default_score,
) -> WalkForwardResult:
    if folds is None:
        folds = make_folds(candles["ts"].min(), candles["ts"].max(), train_months, test_months)
    combos = grid(param_grid) or [{}]  # empty grid = fixed parameters (a user rule)
    name = factory(instrument, **combos[0]).name
    result = WalkForwardResult(strategy=name, instrument=instrument)

    for fold in folds:
        best_params, best_metrics, best_score = None, None, float("-inf")
        for params in combos:
            strat = factory(instrument, **params)
            m = compute(simulate(candles, strat, instrument, fold.train_start, fold.train_end))
            sc = score(m)
            if sc > best_score:
                best_params, best_metrics, best_score = params, m, sc
        if best_params is None:  # every combo scored -inf: take the first, report honestly
            best_params = combos[0]
            best_metrics = compute(
                simulate(
                    candles,
                    factory(instrument, **best_params),
                    instrument,
                    fold.train_start,
                    fold.train_end,
                )
            )
        strat = factory(instrument, **best_params)
        result.rule_text = getattr(strat, "rule_text", "") or name
        test_trades = simulate(candles, strat, instrument, fold.test_start, fold.test_end)
        result.folds.append(
            FoldResult(fold, best_params, best_metrics, test_trades, compute(test_trades))
        )
    return result
