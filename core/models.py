"""Core contracts. Implement exactly; extend only via discussion (see CLAUDE.md).

Only the models needed for the data layer live here today. Position, Plan, Rejected,
Fill and Outcome arrive with the RiskEngine / Journal milestones.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AssetClass = Literal["crypto", "equity", "fx"]
Side = Literal["long", "short"]
Style = Literal["swing", "intraday", "scalp"]


class Instrument(BaseModel):
    """Venue-agnostic description of a tradeable thing. Fees and slippage live here so
    every backtest and every live setup uses the same numbers."""

    model_config = ConfigDict(frozen=True)

    venue: str
    symbol: str
    asset_class: AssetClass
    tick_size: float = Field(gt=0)
    lot_size: float = Field(gt=0)
    fee_pct: float = Field(ge=0, description="Taker fee per side, as a fraction (0.001 = 0.1%).")
    slippage_pct: float = Field(ge=0, description="Assumed slippage per side, as a fraction.")
    trading_hours: str | None = None  # None = 24/7

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.symbol}"


class Candle(BaseModel):
    """One closed OHLCV bar. `ts` is the bar OPEN time, UTC."""

    model_config = ConfigDict(frozen=True)

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = Field(ge=0)

    @model_validator(mode="after")
    def _check(self) -> Candle:
        if self.ts.tzinfo is None:
            raise ValueError("candle ts must be timezone-aware (UTC)")
        if not (self.low <= min(self.open, self.close) and self.high >= max(self.open, self.close)):
            raise ValueError("candle OHLC is inconsistent")
        return self


class Setup(BaseModel):
    """A candle that met the user's rule. Never a recommendation."""

    strategy: str
    instrument: Instrument
    side: Side
    entry: float
    stop: float  # required: no setup without a stop
    target: float
    rule_text: str
    ts: datetime

    @model_validator(mode="after")
    def _geometry(self) -> Setup:
        if self.side == "long" and not (self.stop < self.entry < self.target):
            raise ValueError("long setup requires stop < entry < target")
        if self.side == "short" and not (self.target < self.entry < self.stop):
            raise ValueError("short setup requires target < entry < stop")
        return self

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward_r(self) -> float:
        return abs(self.target - self.entry) / self.risk_per_unit


class RiskTier(BaseModel):
    name: Literal["low", "medium", "high"]
    risk_per_trade_pct: float  # 0.5 / 1.0 / 2.0
    max_drawdown_pct: float  # 10 / 20 / 30
    max_leverage: float  # 1 / 3 / 5
    max_concurrent: int  # 2 / 4 / 6
    allowed_styles: list[Style]  # low: swing; medium: +intraday; high: all


RISK_TIERS: dict[str, RiskTier] = {
    "low": RiskTier(
        name="low",
        risk_per_trade_pct=0.5,
        max_drawdown_pct=10,
        max_leverage=1,
        max_concurrent=2,
        allowed_styles=["swing"],
    ),
    "medium": RiskTier(
        name="medium",
        risk_per_trade_pct=1.0,
        max_drawdown_pct=20,
        max_leverage=3,
        max_concurrent=4,
        allowed_styles=["swing", "intraday"],
    ),
    "high": RiskTier(
        name="high",
        risk_per_trade_pct=2.0,
        max_drawdown_pct=30,
        max_leverage=5,
        max_concurrent=6,
        allowed_styles=["swing", "intraday", "scalp"],
    ),
}
