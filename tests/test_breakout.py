from core.strategies.breakout import Breakout
from tests.backtest_helpers import CLEAN, bars, ts


def _rows():
    rows = [(100, 101, 99, 100)] * 6  # flat: highs at 101
    rows.append((100, 103, 99, 102.5))  # close 102.5 > 101 -> long setup at index 6
    rows.append((102, 103, 101, 102))  # not above prev high 103
    return rows


def test_breakout_emits_long_setup_with_atr_stop_and_r_target():
    strat = Breakout(CLEAN, n=3, atr_n=3, atr_mult=2.0, target_r=2.0)
    setups = strat.generate(bars(_rows()))
    assert [s.ts for s in setups] == [ts(6)]
    s = setups[0]
    # ATR(3) over bars 4..6: TR = 2, 2, 4 -> mean 8/3
    atr = 8 / 3
    assert s.entry == 102.5
    assert abs(s.stop - round(102.5 - 2 * atr, 2)) < 0.011
    assert abs(s.target - (s.entry + 2 * (s.entry - s.stop))) < 0.011
    assert s.side == "long" and "high(3)" in s.rule_text


def test_warmup_returns_nothing():
    assert Breakout(CLEAN, n=20).generate(bars(_rows())) == []


def test_generate_is_causal():
    """Setups on a prefix must equal the prefix of setups on the full series."""
    rows = _rows() * 4
    strat = Breakout(CLEAN, n=3, atr_n=3)
    full = strat.generate(bars(rows))
    cut = ts(12)
    prefix = strat.generate(bars(rows).filter(__import__("polars").col("ts") <= cut))
    assert [s.ts for s in prefix] == [s.ts for s in full if s.ts <= cut]
    assert [(s.stop, s.target) for s in prefix] == [(s.stop, s.target) for s in full if s.ts <= cut]


def test_short_only_when_allowed():
    rows = [(100, 101, 99, 100)] * 6 + [(100, 101, 96, 96.5)]
    assert Breakout(CLEAN, n=3, atr_n=3).generate(bars(rows)) == []
    s = Breakout(CLEAN, n=3, atr_n=3, allow_short=True).generate(bars(rows))
    assert len(s) == 1 and s[0].side == "short" and s[0].target < s[0].entry < s[0].stop


def test_prices_on_tick_grid():
    inst = CLEAN.model_copy(update={"tick_size": 0.5})
    s = Breakout(inst, n=3, atr_n=3).generate(bars(_rows()))[0]
    for p in (s.entry, s.stop, s.target):
        assert (p / 0.5) == int(p / 0.5)
