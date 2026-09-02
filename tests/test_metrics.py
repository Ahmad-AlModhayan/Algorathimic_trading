import math

import pytest

from core.backtest.metrics import compute
from tests.backtest_helpers import trade


def test_empty():
    m = compute([])
    assert m.n_trades == 0 and m.profit_factor == 0.0 and m.max_drawdown_pct == 0.0


def test_basic_numbers():
    m = compute([trade(2), trade(-1), trade(2), trade(-1, reason="stop")])
    assert m.n_trades == 4 and m.wins == 2 and m.losses == 2
    assert m.win_rate == 0.5 and m.total_r == 2 and m.expectancy_r == 0.5
    assert m.profit_factor == pytest.approx(2.0)
    assert m.avg_win_r == 2 and m.avg_loss_r == -1
    assert (m.stops, m.targets, m.ends) == (1, 3, 0)


def test_profit_factor_inf_with_no_losses():
    assert math.isinf(compute([trade(1), trade(2)]).profit_factor)


def test_drawdown_fixed_fraction():
    # equity: 1.00 -> 1.02 -> 1.01 -> 1.00 -> 1.02 ; worst peak-to-trough 0.02/1.02
    m = compute([trade(2), trade(-1), trade(-1), trade(2)], risk_pct=1.0)
    assert m.max_drawdown_pct == pytest.approx(2 / 1.02, rel=1e-6)
    assert compute([trade(-1)] * 10, risk_pct=2.0).max_drawdown_pct == pytest.approx(20.0)


def test_percentiles():
    m = compute([trade(r) for r in [-1, -1, 0, 1, 2]])
    assert m.r_p50 == 0 and m.r_p10 == -1 and m.r_p90 == pytest.approx(1.6)
