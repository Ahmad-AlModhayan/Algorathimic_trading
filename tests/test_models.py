from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from core.models import RISK_TIERS, Candle, Instrument, Setup
from tests.conftest import BTC


def test_instrument_key_and_frozen():
    assert BTC.key == "test:BTC/USDT"
    with pytest.raises(ValidationError):
        BTC.tick_size = 1.0  # type: ignore[misc]


def test_instrument_rejects_bad_values():
    with pytest.raises(ValidationError):
        Instrument(
            venue="x",
            symbol="y",
            asset_class="crypto",
            tick_size=0,
            lot_size=1,
            fee_pct=0,
            slippage_pct=0,
        )
    with pytest.raises(ValidationError):
        Instrument(
            venue="x",
            symbol="y",
            asset_class="bond",
            tick_size=1,
            lot_size=1,  # type: ignore[arg-type]
            fee_pct=0,
            slippage_pct=0,
        )


def test_candle_requires_tz_and_consistent_ohlc():
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    Candle(ts=ts, open=1, high=2, low=0.5, close=1.5, volume=1)
    with pytest.raises(ValidationError):
        Candle(ts=datetime(2024, 1, 1), open=1, high=2, low=0.5, close=1.5, volume=1)
    with pytest.raises(ValidationError):
        Candle(ts=ts, open=1, high=0.9, low=0.5, close=1.5, volume=1)


def test_setup_geometry():
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    s = Setup(
        strategy="s",
        instrument=BTC,
        side="long",
        entry=100,
        stop=95,
        target=110,
        rule_text="close > high(20)",
        ts=ts,
    )
    assert s.risk_per_unit == 5 and s.reward_r == 2
    with pytest.raises(ValidationError):
        Setup(
            strategy="s",
            instrument=BTC,
            side="long",
            entry=100,
            stop=105,
            target=110,
            rule_text="r",
            ts=ts,
        )
    with pytest.raises(ValidationError):
        Setup(
            strategy="s",
            instrument=BTC,
            side="short",
            entry=100,
            stop=95,
            target=110,
            rule_text="r",
            ts=ts,
        )


def test_risk_tiers_match_brief():
    assert RISK_TIERS["low"].allowed_styles == ["swing"]
    assert RISK_TIERS["medium"].max_drawdown_pct == 20
    assert RISK_TIERS["high"].max_concurrent == 6
