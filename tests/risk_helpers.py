from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.models import RISK_TIERS, Candle, Instrument, ManagementRules, Plan, Setup

T0 = datetime(2024, 1, 1, tzinfo=UTC)
BTC = Instrument(
    venue="binance",
    symbol="BTC/USDT",
    asset_class="crypto",
    tick_size=0.01,
    lot_size=0.001,
    fee_pct=0.001,
    slippage_pct=0.0005,
)
ETH = BTC.model_copy(update={"symbol": "ETH/USDT"})
STYLES = {"breakout": "swing", "macross": "intraday", "rsi": "scalp"}
LOW, MED, HIGH = RISK_TIERS["low"], RISK_TIERS["medium"], RISK_TIERS["high"]


def setup(strategy="breakout", inst=BTC, side="long", entry=100.0, stop=95.0, target=110.0, ts=T0):
    return Setup(
        strategy=strategy,
        instrument=inst,
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        rule_text="r",
        ts=ts,
    )


def plan(
    s: Setup | None = None, qty=20.0, risk=100.0, rules: ManagementRules | None = None, user="u1"
):
    s = s or setup()
    return Plan(
        setup=s,
        user_id=user,
        tier="medium",
        qty=qty,
        risk_amount=risk,
        risk_pct=1.0,
        notional=qty * s.entry,
        leverage=0.2,
        reward_r=s.reward_r,
        management=rules or ManagementRules(),
        created_at=s.ts,
    )


def candle(i: int, o, h, lo, c, tf_hours=4) -> Candle:
    return Candle(ts=T0 + timedelta(hours=tf_hours * i), open=o, high=h, low=lo, close=c, volume=1)
