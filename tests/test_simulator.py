import pytest

from core.backtest.simulator import simulate
from tests.backtest_helpers import CLEAN, COSTLY, FixedSetups, bars, setup, ts

FLAT = (100, 100.5, 99.5, 100)  # setup bar: close 100


def run(rows, setups, inst=CLEAN, **kw):
    return simulate(bars(rows), FixedSetups(setups), inst, **kw)


def test_long_target_is_plus_target_r():
    trades = run([FLAT, (100, 111, 99, 110)], [setup(0)])
    assert len(trades) == 1
    t = trades[0]
    assert (t.setup_ts, t.entry_ts, t.entry_price) == (ts(0), ts(0), 100.0)
    assert (t.exit_ts, t.exit_price, t.exit_reason) == (ts(1), 110.0, "target")
    assert t.qty == pytest.approx(0.2) and t.r_multiple == pytest.approx(2.0)
    assert t.bars_held == 1


def test_long_stop_is_minus_one_r():
    t = run([FLAT, (100, 101, 94, 96)], [setup(0)])[0]
    assert (t.exit_price, t.exit_reason) == (95.0, "stop")
    assert t.r_multiple == pytest.approx(-1.0)


def test_both_touched_is_worst_case():
    t = run([FLAT, (100, 120, 90, 115)], [setup(0)])[0]
    assert t.exit_reason == "stop" and t.r_multiple == pytest.approx(-1.0)


def test_gap_through_stop_fills_at_open():
    t = run([FLAT, (90, 91, 89, 90)], [setup(0)])[0]
    assert t.exit_price == 90.0 and t.r_multiple == pytest.approx(-2.0)


def test_setup_bar_range_is_not_used_for_exits():
    # setup bar itself has low 90 (below stop) but entry happens at its close
    t = run([(100, 101, 90, 100), (100, 111, 99, 110)], [setup(0)])[0]
    assert t.exit_reason == "target"


def test_open_position_closes_at_end():
    t = run([FLAT, (100, 102, 99, 101)], [setup(0)])[0]
    assert (t.exit_reason, t.exit_price, t.exit_ts) == ("end", 101.0, ts(1))
    assert t.r_multiple == pytest.approx(0.2)


def test_setup_on_last_bar_is_flat_at_same_close():
    t = run([FLAT, FLAT], [setup(1)])[0]
    assert t.exit_reason == "end" and t.bars_held == 0 and t.pnl == 0


def test_short_mirror():
    s = setup(0, side="short", entry=100, stop=105, target=90)
    t = run([FLAT, (100, 101, 89, 91)], [s])[0]
    assert t.exit_reason == "target" and t.r_multiple == pytest.approx(2.0)
    t = run([FLAT, (100, 106, 99, 104)], [s])[0]
    assert t.exit_reason == "stop" and t.r_multiple == pytest.approx(-1.0)
    t = run([FLAT, (100, 120, 80, 100)], [s])[0]
    assert t.exit_reason == "stop"
    t = run([FLAT, (110, 111, 109, 110)], [s])[0]
    assert t.exit_price == 110.0 and t.r_multiple == pytest.approx(-2.0)


def test_fees_and_slippage_are_charged_both_sides():
    s = setup(0, inst=COSTLY)
    t = run([FLAT, (100, 111, 99, 110)], [s], inst=COSTLY)[0]
    entry = 100 * 1.001
    qty = 1 / (entry - 95)
    fees = entry * qty * 0.001 + 110 * qty * 0.001
    assert t.entry_price == pytest.approx(entry)
    assert t.fees == pytest.approx(fees)
    assert t.pnl == pytest.approx((110 - entry) * qty - fees)
    t = run([FLAT, (100, 101, 94, 96)], [s], inst=COSTLY)[0]
    assert t.exit_price == pytest.approx(95 * 0.999)


def test_one_position_at_a_time_and_reentry_after_exit():
    rows = [
        FLAT,
        (100, 101, 99, 100),
        (100, 111, 99, 110),
        (100, 101, 99, 100),
        (100, 111, 99, 110),
    ]
    trades = run(rows, [setup(0), setup(1), setup(2), setup(3)])
    # setup 0 enters; setups 1 ignored (in position); exit on bar 2 -> setup 2 enters same bar
    assert [t.setup_ts for t in trades] == [ts(0), ts(2)]
    assert [t.exit_reason for t in trades] == ["target", "target"]


def test_window_admits_setups_only_inside_and_closes_at_window_end():
    rows = [FLAT, (100, 101, 99, 100), FLAT, (100, 101, 99, 100), (100, 111, 99, 110)]
    trades = run(rows, [setup(0), setup(2)], start=ts(2), end=ts(4))
    assert len(trades) == 1
    assert trades[0].setup_ts == ts(2) and trades[0].exit_reason == "end"
    assert trades[0].exit_ts == ts(3)


def test_risk_amount_scales_qty_not_r():
    a = run([FLAT, (100, 111, 99, 110)], [setup(0)], risk_amount=1.0)[0]
    b = run([FLAT, (100, 111, 99, 110)], [setup(0)], risk_amount=100.0)[0]
    assert b.qty == pytest.approx(100 * a.qty) and b.r_multiple == pytest.approx(a.r_multiple)


def test_empty_inputs():
    assert run([], [setup(0)]) == []
    assert run([FLAT, FLAT], []) == []
