"""One closed trade. Both engines (simulator and Nautilus) emit this, so metrics have one path."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from core.models import Side

ExitReason = Literal["stop", "target", "end"]


class Trade(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy: str
    venue: str
    symbol: str
    side: Side
    setup_ts: datetime  # bar on which the rule was met
    entry_ts: datetime  # bar on which the entry filled
    entry_price: float  # after slippage
    exit_ts: datetime
    exit_price: float  # after slippage
    exit_reason: ExitReason
    qty: float
    stop: float
    target: float
    fees: float  # total, in quote currency
    pnl: float  # net of fees, in quote currency
    r_multiple: float  # pnl / risk amount
    bars_held: int

    @property
    def won(self) -> bool:
        return self.pnl > 0
