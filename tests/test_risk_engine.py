import pytest

from core.models import Plan, Rejected, RiskAdjustment
from core.risk import RiskEngine, open_position
from tests.risk_helpers import BTC, ETH, HIGH, LOW, MED, STYLES, T0, plan, setup


def engine(**kw):
    return RiskEngine(STYLES, **kw)


def test_basic_sizing_medium_tier():
    p = engine().size(setup(), MED, 10_000, [])
    assert isinstance(p, Plan)
    assert p.qty == pytest.approx(20.0) and p.risk_amount == pytest.approx(100.0)
    assert p.risk_pct == pytest.approx(1.0) and p.leverage == pytest.approx(0.2)
    assert p.reward_r == 2.0 and p.tier == "medium" and p.notes == []


def test_unknown_strategy_and_style_gating():
    r = engine().size(setup(strategy="mystery"), HIGH, 10_000, [])
    assert isinstance(r, Rejected) and r.code == "unknown_strategy" and r.reason
    r = engine().size(setup(strategy="macross"), LOW, 10_000, [])
    assert r.code == "style_not_allowed" and "intraday" in r.reason
    assert isinstance(engine().size(setup(strategy="macross"), MED, 10_000, []), Plan)
    assert engine().size(setup(strategy="rsi"), MED, 10_000, []).code == "style_not_allowed"
    assert isinstance(engine().size(setup(strategy="rsi"), HIGH, 10_000, []), Plan)


def test_lot_rounding_and_below_lot():
    inst = BTC.model_copy(update={"lot_size": 1.0})
    p = engine().size(setup(inst=inst, stop=95.1), MED, 10_000, [])  # 100/4.9 = 20.4 -> 20
    assert p.qty == 20.0 and p.risk_amount == pytest.approx(20 * 4.9)
    r = engine().size(setup(inst=inst), MED, 10, [])  # risk 0.1 -> qty 0.02 < lot 1
    assert r.code == "qty_below_lot"


def test_leverage_scales_qty_then_rejects_when_full():
    # low tier: 1x. equity 1000, risk 5 (0.5%), stop 0.1 away -> qty 50 -> notional 5000 > 1000
    p = engine().size(setup(stop=99.9, target=100.3), LOW, 1_000, [])
    assert p.qty == pytest.approx(10.0) and p.notional == pytest.approx(1_000)
    assert p.leverage == pytest.approx(1.0) and "leverage" in p.notes[0]
    assert p.risk_amount == pytest.approx(1.0)  # risk shrank with the size
    full = open_position(plan(setup(inst=ETH), qty=10.0), 100.0, T0)  # notional 1000 = all of it
    r = engine().size(setup(stop=99.9, target=100.3), LOW, 1_000, [full])
    assert r.code == "max_leverage"


def test_concurrency_and_duplicate_instrument():
    a = open_position(plan(setup(inst=ETH)), 100.0, T0)
    b = open_position(plan(setup(inst=BTC.model_copy(update={"symbol": "SOL/USDT"}))), 100.0, T0)
    assert engine().size(setup(), LOW, 10_000, [a, b]).code == "max_concurrent"
    assert isinstance(engine().size(setup(), MED, 10_000, [a, b]), Plan)
    same = open_position(plan(setup()), 100.0, T0)
    assert engine().size(setup(), MED, 10_000, [same]).code == "instrument_open"
    same.closed = True
    assert isinstance(engine().size(setup(), MED, 10_000, [same]), Plan)


def test_drawdown_limit_uses_peak_equity():
    e = engine()
    assert isinstance(e.size(setup(), LOW, 10_000, []), Plan)
    r = e.size(setup(), LOW, 8_900, [])  # 11% below peak, low tier allows 10%
    assert r.code == "drawdown_limit" and "11.0%" in r.reason
    assert isinstance(e.size(setup(), MED, 8_900, []), Plan)  # medium allows 20%
    e2 = engine(peak_equity=10_000)
    assert e2.size(setup(), LOW, 9_000, []).code == "drawdown_limit"  # exactly at the limit


def test_feedback_adjustments():
    e = engine()
    e.apply(RiskAdjustment(kind="downgrade", reason="5 losses", risk_multiplier=0.5))
    p = e.size(setup(), MED, 10_000, [])
    assert p.risk_amount == pytest.approx(50.0) and "risk reduced" in p.notes[0]
    e.apply(RiskAdjustment(kind="pause", reason="drawdown", risk_multiplier=0.0))
    assert e.size(setup(), MED, 10_000, []).code == "paused"
    e.apply(RiskAdjustment(kind="none", reason=""))
    assert e.size(setup(), MED, 10_000, []).risk_amount == pytest.approx(100.0)


def test_invalid_risk():
    inst = BTC
    s = setup(inst=inst)
    assert engine().size(s, MED, 0, []).code == "invalid_risk"
