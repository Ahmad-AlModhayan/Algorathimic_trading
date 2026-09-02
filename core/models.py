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


# ---- risk / position / journal ----------------------------------------------------------


class ManagementRules(BaseModel):
    """How an open position is managed, in R units so it is size- and price-independent."""

    break_even_at_r: float | None = 1.0  # move stop to entry once price reaches +N R
    trail_r: float | None = None  # trail stop N R below the highest close since entry
    partial_exit_at_r: float | None = None  # take `partial_fraction` off at +N R
    partial_fraction: float = Field(default=0.5, gt=0, lt=1)
    time_stop_bars: int | None = None  # exit at close after N bars regardless


class Plan(BaseModel):
    """A sized setup. Produced only by RiskEngine; nothing else may construct one for use."""

    model_config = ConfigDict(frozen=True)

    setup: Setup
    user_id: str = "default"
    tier: str
    qty: float
    risk_amount: float  # currency lost if the stop fills at the stop price
    risk_pct: float  # of equity
    notional: float
    leverage: float  # (this notional + open notionals) / equity
    reward_r: float
    management: ManagementRules = ManagementRules()
    notes: list[str] = []
    created_at: datetime

    @property
    def r_value(self) -> float:
        return self.risk_amount


RejectCode = Literal[
    "style_not_allowed",
    "unknown_strategy",
    "max_concurrent",
    "instrument_open",
    "drawdown_limit",
    "paused",
    "max_leverage",
    "qty_below_lot",
    "invalid_risk",
]


class Rejected(BaseModel):
    """Always carries a reason. It is product behavior, not an error, and is logged."""

    model_config = ConfigDict(frozen=True)

    setup: Setup
    code: RejectCode
    reason: str
    created_at: datetime


class Position(BaseModel):
    """An open position managed per its plan. Mutable: PositionManager updates it in place."""

    id: str
    plan: Plan
    qty: float  # remaining
    entry_price: float
    opened_at: datetime
    stop: float
    target: float
    bars_held: int = 0
    highest_close: float
    lowest_close: float
    break_even_done: bool = False
    partial_done: bool = False
    closed: bool = False

    @property
    def side(self) -> Side:
        return self.plan.setup.side

    @property
    def instrument(self) -> Instrument:
        return self.plan.setup.instrument

    @property
    def r_per_unit(self) -> float:
        return abs(self.entry_price - self.plan.setup.stop)

    @property
    def notional(self) -> float:
        return self.qty * self.entry_price


ActionKind = Literal["move_stop", "partial_exit", "exit"]


class Action(BaseModel):
    """An instruction for the user (V1 has no auto-execution)."""

    model_config = ConfigDict(frozen=True)

    kind: ActionKind
    reason: str
    price: float | None = None
    qty: float | None = None
    ts: datetime


class Fill(BaseModel):
    model_config = ConfigDict(frozen=True)

    ts: datetime
    side: Literal["buy", "sell"]
    price: float
    qty: float
    fee: float = 0.0


class Outcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    exit_reason: Literal["stop", "target", "time", "manual", "trail", "partial+stop", "end"]
    pnl: float
    r_multiple: float
    closed_at: datetime
    bars_held: int


class Analytics(BaseModel):
    n_trades: int
    win_rate: float
    expectancy_r: float
    total_r: float
    profit_factor: float
    max_drawdown_r: float  # peak-to-trough in cumulative R
    r_p10: float
    r_p50: float
    r_p90: float
    by_style: dict[str, float]  # expectancy R
    by_instrument: dict[str, float]
    by_hour: dict[int, float]  # entry hour (UTC)
    current_streak: int  # >0 wins, <0 losses


class RiskAdjustment(BaseModel):
    kind: Literal["none", "downgrade", "pause"]
    reason: str
    risk_multiplier: float = 1.0  # applied to risk_per_trade_pct
    tier_override: Literal["low", "medium", "high"] | None = None
