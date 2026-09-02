"""Nautilus parity. Skipped unless the `backtest` extra is installed."""

from datetime import UTC, datetime

import polars as pl
import pytest

from core.backtest.parity import compare
from core.backtest.simulator import simulate
from core.strategies.breakout import Breakout
from tests.backtest_helpers import CLEAN, COSTLY, FixedSetups, bars, setup, ts

nautilus = pytest.importorskip("nautilus_trader")
from core.backtest.nautilus_runner import run_nautilus  # noqa: E402

pytestmark = pytest.mark.backtest
FLAT = (100, 100.5, 99.5, 100)
VOL = 1e6  # Nautilus caps fill size by bar volume; keep synthetic volume large


def _bars(rows):
    return bars(rows).with_columns(pl.lit(VOL).alias("volume"))


def both(rows, setups, inst=CLEAN):
    c = _bars(rows)
    sim = simulate(c, FixedSetups(setups), inst, risk_amount=100.0)
    nt = run_nautilus(c, FixedSetups(setups), inst, "4h", risk_amount=100.0)
    return c, sim, nt


@pytest.mark.parametrize(
    "name,rows,reason,r",
    [
        ("target", [FLAT, (100, 111, 99, 110)], "target", 2.0),
        ("stop", [FLAT, (100, 101, 94, 96)], "stop", -1.0),
        ("gap", [FLAT, (90, 91, 89, 90)], "stop", -2.0),
        ("end", [FLAT, (100, 102, 99, 101)], "end", 0.2),
        (
            "later",
            [FLAT, (100, 101, 99, 100), (100, 101, 99, 100), (100, 111, 99, 110)],
            "target",
            2.0,
        ),
    ],
)
def test_nautilus_matches_simulator_on_clean_cases(name, rows, reason, r):
    c, sim, nt = both(rows, [setup(0)])
    assert len(nt.trades) == 1 and nt.skipped_setups == 0
    t = nt.trades[0]
    assert (t.setup_ts, t.entry_ts, t.exit_reason) == (ts(0), ts(0), reason)
    assert t.r_multiple == pytest.approx(r)
    rep = compare(sim, nt.trades, c, CLEAN)
    assert rep.passed and rep.matched == 1 and rep.mismatches == [], rep.summary


def test_short_matches():
    s = setup(0, side="short", entry=100, stop=105, target=90)
    c, sim, nt = both([FLAT, (100, 101, 89, 91)], [s])
    assert nt.trades[0].exit_reason == "target" and nt.trades[0].r_multiple == pytest.approx(2.0)
    assert compare(sim, nt.trades, c, CLEAN).passed


def test_both_touch_is_the_named_deviation():
    c, sim, nt = both([FLAT, (100, 120, 90, 115)], [setup(0)])
    assert sim[0].exit_reason == "stop" and nt.trades[0].exit_reason == "target"
    rep = compare(sim, nt.trades, c, CLEAN)
    assert rep.passed and rep.count("both_touch") == 1 and rep.matched == 0


def test_slippage_is_within_tolerance_and_named():
    s = setup(0, inst=COSTLY)
    c, sim, nt = both([FLAT, (100, 111, 99, 110)], [s], inst=COSTLY)
    t = nt.trades[0]
    assert t.entry_price == pytest.approx(100.0)  # Nautilus fills at the close, not the limit
    assert t.fees > 0
    rep = compare(sim, t and nt.trades, c, COSTLY)
    assert rep.passed and rep.count("slippage") == 1 and rep.matched == 1
    assert sim[0].r_multiple < t.r_multiple  # simulator is the conservative one


def test_unexplained_is_flagged():
    c, sim, nt = both([FLAT, (100, 111, 99, 110)], [setup(0)])
    rep = compare(sim, [], c, CLEAN)
    assert not rep.passed and rep.unexplained[0].detail == "trade only in simulator"


def _sawtooth(n_cycles: int = 60) -> pl.DataFrame:
    rows, price = [], 100.0
    for k in range(n_cycles):
        rows += [(price, price + 1, price - 1, price)] * 5
        rows.append((price, price + 4, price - 1, price + 3))
        if k % 7 == 6:  # occasional shakeout bar to produce stops and both-touch bars
            rows.append((price + 3, price + 12, price - 9, price + 3))
        price += 3
    return bars(rows, t0=datetime(2024, 1, 1, tzinfo=UTC)).with_columns(pl.lit(VOL).alias("volume"))


def test_breakout_parity_on_synthetic_series():
    c = _sawtooth()
    strat = Breakout(COSTLY, n=3, atr_n=3, atr_mult=2.0, target_r=1.5)
    sim = simulate(c, strat, COSTLY, risk_amount=100.0)
    nt = run_nautilus(c, strat, COSTLY, "4h", risk_amount=100.0)
    assert len(sim) > 10 and len(nt.trades) > 10
    rep = compare(sim, nt.trades, c, COSTLY)
    assert rep.passed, rep.summary
    assert rep.matched + rep.count("both_touch") + rep.count("downstream") >= min(
        len(sim), len(nt.trades)
    )
