import math
from datetime import timedelta

import pytest

from core.journal import Journal, outcome_from
from core.models import Fill, Outcome
from tests.risk_helpers import ETH, STYLES, T0, plan, setup


def outcome(r: float, i: int) -> Outcome:
    return Outcome(
        exit_reason="target" if r > 0 else "stop",
        pnl=r * 100,
        r_multiple=r,
        closed_at=T0 + timedelta(hours=4 * (i + 1)),
        bars_held=1,
    )


def journal(rs, strategy="breakout", inst=None, user="u1", path=None):
    j = Journal(STYLES, path=path)
    for i, r in enumerate(rs):
        s = setup(strategy=strategy, inst=inst or ETH, ts=T0 + timedelta(hours=4 * i))
        j.record(plan(s, user=user), [], outcome(r, i))
    return j


def test_analytics_numbers_and_breakdowns():
    j = journal([2, -1, 2, -1, -1, 3])
    a = j.analytics("u1")
    assert a.n_trades == 6 and a.win_rate == 0.5 and a.total_r == 4
    assert a.expectancy_r == pytest.approx(4 / 6) and a.profit_factor == pytest.approx(7 / 3)
    assert a.max_drawdown_r == 2  # 2,1,3,2,1 -> peak 3, trough 1
    assert a.by_style == {"swing": pytest.approx(4 / 6)}
    assert a.by_instrument == {"binance:ETH/USDT": pytest.approx(4 / 6)}
    assert set(a.by_hour) == {0, 4, 8, 12, 16, 20}
    assert a.current_streak == 1
    assert j.analytics("nobody").n_trades == 0
    assert math.isinf(journal([1, 2]).analytics("u1").profit_factor)


def test_feedback_downgrade_on_losing_streak_and_pause_on_drawdown():
    assert journal([]).feedback("u1").kind == "none"
    assert journal([2, -1, -1, -1, -1]).feedback("u1").kind == "none"
    f = journal([2, -1, -1, -1, -1, -1]).feedback("u1")
    assert f.kind == "downgrade" and f.risk_multiplier == 0.5 and "5 consecutive" in f.reason
    f = journal([5, 5] + [-1] * 10).feedback("u1")  # peak 10, now 0 -> 10R drawdown
    assert f.kind == "pause" and f.risk_multiplier == 0.0
    recovered = journal([5, 5] + [-1] * 10 + [2, 2, 2, 2, 2, 2])  # back within 1R of the old peak
    assert recovered.feedback("u1").kind == "none"


def test_outcome_from_fills_long_and_short():
    p = plan(qty=2.0, risk=10.0)
    fills = [
        Fill(ts=T0, side="buy", price=100, qty=2, fee=0.2),
        Fill(ts=T0, side="sell", price=110, qty=2, fee=0.22),
    ]
    o = outcome_from(p, fills, "target", T0, 3)
    assert o.pnl == pytest.approx(20 - 0.42) and o.r_multiple == pytest.approx((20 - 0.42) / 10)
    ps = plan(setup(side="short", entry=100, stop=105, target=90), qty=2.0, risk=10.0)
    fills = [Fill(ts=T0, side="sell", price=100, qty=2), Fill(ts=T0, side="buy", price=90, qty=2)]
    assert outcome_from(ps, fills, "target", T0, 1).r_multiple == pytest.approx(2.0)


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "journal.json"
    journal([1, -1], path=path)
    j2 = Journal(STYLES, path=path)
    assert j2.analytics("u1").n_trades == 2
    j2.record(plan(setup(), user="u2"), [], outcome(1, 9))
    assert Journal(STYLES, path=path).analytics("u2").n_trades == 1
