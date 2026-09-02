from datetime import UTC, datetime

import polars as pl
import pytest
from pydantic import ValidationError

from core.language import lint_language
from core.strategies.breakout import Breakout as BreakoutStrategy
from core.strategies.dsl import (
    ATRStop,
    Breakout,
    FixedRTarget,
    MACross,
    PctStop,
    RSIThreshold,
    Rule,
    TrendFilter,
    compile_rule,
    rsi_expr,
    rule_from_json,
)
from core.strategies.library import LIBRARY, STRATEGY_STYLES
from tests.backtest_helpers import CLEAN, bars, ts


def _rule(**kw) -> Rule:
    base = dict(
        name="r1",
        style="swing",
        timeframe="4h",
        entry=[Breakout(n=3)],
        stop=ATRStop(n=3, mult=2.0),
        target=FixedRTarget(r=2.0),
    )
    base.update(kw)
    return Rule(**base)


def test_validation_rejects_bad_rules():
    with pytest.raises(ValidationError):
        _rule(entry=[])
    with pytest.raises(ValidationError):
        _rule(entry=[MACross(fast=50, slow=20)])
    with pytest.raises(ValidationError):
        _rule(timeframe="4H")
    with pytest.raises(ValidationError):
        _rule(name="Bad Name")
    with pytest.raises(ValidationError):
        rule_from_json(
            {
                "name": "x1",
                "style": "swing",
                "timeframe": "4h",
                "entry": [{"type": "magic"}],
                "stop": {"type": "atr", "mult": 2},
                "target": {"type": "fixed_r", "r": 2},
            }
        )


def test_json_roundtrip_and_texts():
    r = _rule(
        entry=[Breakout(n=20), RSIThreshold(level=30)], filters=[TrendFilter(n=50)], side="both"
    )
    again = rule_from_json(r.model_dump())
    assert again == r
    assert r.to_text() == (
        "close > high(20) & RSI(14) < 30 | filter close > SMA(50) | "
        "stop = close -/+ 2*ATR(3) | target = 2R (both sides)"
    )
    assert "الإغلاق فوق أعلى 20 شمعة" in r.to_arabic() and "الاتجاهان" in r.to_arabic()


@pytest.mark.parametrize("name", list(LIBRARY))
def test_library_rules_render_clean_arabic_and_register_styles(name):
    r = LIBRARY[name]
    lint_language(r.to_arabic())
    lint_language(r.to_text())
    assert STRATEGY_STYLES[name] == r.style
    assert r.warmup > 0


def _uptrend_breakouts():
    rows = [(100, 101, 99, 100)] * 6 + [(100, 103, 99, 102.5), (102, 103, 101, 102)]
    return bars(rows * 4)


def test_compiled_breakout_matches_breakout_class():
    candles = _uptrend_breakouts()
    ref = BreakoutStrategy(CLEAN, n=3, atr_n=3, atr_mult=2.0, target_r=2.0).generate(candles)
    got = compile_rule(_rule(), CLEAN).generate(candles)
    assert len(ref) == len(got) > 0
    for a, b in zip(ref, got, strict=True):
        assert (a.ts, a.side, a.entry, a.stop, a.target) == (
            b.ts,
            b.side,
            b.entry,
            b.stop,
            b.target,
        )
    assert got[0].strategy == "r1" and got[0].rule_text == _rule().to_text()


def test_pct_stop_and_short_side():
    r = _rule(stop=PctStop(pct=2.0), side="short")
    rows = [(100, 101, 99, 100)] * 6 + [(100, 101, 96, 96.5)]
    s = compile_rule(r, CLEAN).generate(bars(rows))
    assert len(s) == 1 and s[0].side == "short"
    assert s[0].stop == pytest.approx(96.5 * 1.02, abs=0.011)
    assert s[0].target == pytest.approx(96.5 - 2 * (s[0].stop - 96.5), abs=0.011)


def test_ma_cross_fires_only_on_the_crossing_bar():
    r = _rule(entry=[MACross(fast=2, slow=4)], stop=PctStop(pct=1.0))
    closes = [100, 100, 100, 100, 100, 100, 101, 103, 106, 110, 115]  # fast crosses above slow once
    rows = [(c, c + 0.5, c - 0.5, c) for c in closes]
    s = compile_rule(r, CLEAN).generate(bars(rows))
    assert [x.ts for x in s] == [ts(6)]
    down = closes + [110, 104, 98, 92]
    r2 = _rule(entry=[MACross(fast=2, slow=4)], stop=PctStop(pct=1.0), side="short")
    s2 = compile_rule(r2, CLEAN).generate(bars([(c, c + 0.5, c - 0.5, c) for c in down]))
    assert len(s2) == 1 and s2[0].side == "short" and s2[0].ts > ts(10)


def test_rsi_threshold_and_trend_filter():
    closes = [100 + i for i in range(20)] + [119 - 2 * i for i in range(6)]  # up, then a sharp dip
    rows = [(c, c + 0.5, c - 0.5, c) for c in closes]
    df = bars(rows).with_columns(rsi=rsi_expr(5))
    assert df["rsi"][19] == 100.0 and df["rsi"][-1] < 30
    r = _rule(entry=[RSIThreshold(n=5, level=30)], stop=PctStop(pct=1.0))
    s = compile_rule(r, CLEAN).generate(bars(rows))
    assert len(s) >= 1 and all(x.ts >= ts(20) for x in s)
    filtered = _rule(
        entry=[RSIThreshold(n=5, level=30)], filters=[TrendFilter(n=3)], stop=PctStop(pct=1.0)
    )
    assert compile_rule(filtered, CLEAN).generate(bars(rows)) == []  # dip is below the short MA


def test_compiled_is_causal():
    candles = _uptrend_breakouts()
    r = _rule(
        entry=[Breakout(n=3), RSIThreshold(n=3, level=90, op=">")], filters=[TrendFilter(n=3)]
    )
    strat = compile_rule(r, CLEAN)
    full = strat.generate(candles)
    cut = ts(14)
    prefix = strat.generate(candles.filter(pl.col("ts") <= cut))
    assert [(s.ts, s.stop) for s in prefix] == [(s.ts, s.stop) for s in full if s.ts <= cut]


def test_warmup_short_circuit():
    assert compile_rule(_rule(entry=[Breakout(n=50)]), CLEAN).generate(_uptrend_breakouts()) == []
    assert datetime(2024, 1, 1, tzinfo=UTC) == ts(0)
