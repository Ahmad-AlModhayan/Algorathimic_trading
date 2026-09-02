import pytest

from core.models import ManagementRules
from core.risk import PositionManager, open_position
from tests.risk_helpers import T0, candle, plan, setup

pm = PositionManager()


def pos(rules=None, side="long", **kw):
    s = (
        setup(side=side, **kw)
        if side == "long"
        else setup(side="short", entry=100, stop=105, target=90)
    )
    return open_position(plan(s, rules=rules), s.entry, T0)


def test_target_and_stop_exits_and_worst_case():
    p = pos()
    acts = pm.on_candle(p, candle(1, 100, 111, 99, 110))
    assert (
        [a.kind for a in acts] == ["exit"] and acts[0].reason == "target" and acts[0].price == 110
    )
    assert p.closed and pm.on_candle(p, candle(2, 100, 101, 99, 100)) == []
    p = pos()
    a = pm.on_candle(p, candle(1, 100, 101, 94, 96))[0]
    assert a.reason == "stop" and a.price == 95 and a.qty == 20.0
    p = pos()
    assert pm.on_candle(p, candle(1, 100, 120, 90, 100))[0].reason == "stop"
    p = pos()
    assert pm.on_candle(p, candle(1, 90, 91, 89, 90))[0].price == 90  # gap through stop


def test_break_even_moves_after_candle_not_within_it():
    p = pos(ManagementRules(break_even_at_r=1.0))
    # reaches +1R (105) and dips to 99 in the same candle: no exit, then stop moves to entry
    acts = pm.on_candle(p, candle(1, 100, 106, 99, 104))
    assert [a.kind for a in acts] == ["move_stop"] and acts[0].price == 100 and p.stop == 100
    assert p.break_even_done and not p.closed
    a = pm.on_candle(p, candle(2, 101, 102, 99.5, 101))[0]  # now the moved stop is hit
    assert a.kind == "exit" and a.reason == "trail" and a.price == 100


def test_partial_exit_then_target_on_remainder():
    p = pos(ManagementRules(break_even_at_r=None, partial_exit_at_r=1.0, partial_fraction=0.5))
    acts = pm.on_candle(p, candle(1, 100, 105.5, 99, 105))
    assert acts[0].kind == "partial_exit" and acts[0].qty == 10.0 and acts[0].price == 105
    assert p.qty == 10.0 and p.partial_done
    assert pm.on_candle(p, candle(2, 105, 105.6, 104, 105)) == []  # no second partial
    a = pm.on_candle(p, candle(3, 105, 111, 104, 110))[0]
    assert a.reason == "target" and a.qty == 10.0


def test_trailing_stop_only_ratchets_up():
    p = pos(ManagementRules(break_even_at_r=None, trail_r=1.0))
    first = pm.on_candle(p, candle(1, 100, 102, 99, 101))  # close 101 - 1R(5) = 96 > 95
    assert first[0].kind == "move_stop" and first[0].price == pytest.approx(96)
    p = pos(ManagementRules(break_even_at_r=None, trail_r=1.0))
    acts = pm.on_candle(p, candle(1, 100, 104, 99, 103))
    assert acts[0].kind == "move_stop" and acts[0].price == pytest.approx(98)
    assert pm.on_candle(p, candle(2, 103, 104, 101, 101)) == []  # lower close: no move down
    assert p.stop == pytest.approx(98)
    acts = pm.on_candle(p, candle(3, 101, 108, 101, 107))
    assert acts[-1].price == pytest.approx(102)
    a = pm.on_candle(p, candle(4, 106, 106, 101, 103))[0]
    assert a.kind == "exit" and a.reason == "trail" and a.price == pytest.approx(102)


def test_time_stop():
    p = pos(ManagementRules(break_even_at_r=None, time_stop_bars=3))
    assert pm.on_candle(p, candle(1, 100, 101, 99, 100)) == []
    assert pm.on_candle(p, candle(2, 100, 101, 99, 100)) == []
    a = pm.on_candle(p, candle(3, 100, 101, 99, 100.5))[0]
    assert a.reason == "time" and a.price == 100.5 and p.closed and p.bars_held == 3


def test_short_mirror():
    p = pos(side="short")
    assert pm.on_candle(p, candle(1, 100, 101, 89, 91))[0].reason == "target"
    p = pos(side="short")
    assert pm.on_candle(p, candle(1, 100, 106, 99, 104))[0].price == 105
    p = pos(ManagementRules(break_even_at_r=1.0), side="short")
    acts = pm.on_candle(p, candle(1, 100, 101, 94, 96))  # +1R for a short = 95
    assert acts[0].kind == "move_stop" and p.stop == 100
