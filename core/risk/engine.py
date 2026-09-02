"""RiskEngine: gates every setup. Nothing bypasses it (non-negotiable #2).

Order of checks, first failure wins:
  paused -> unknown strategy -> style not allowed by tier -> drawdown limit -> max concurrent
  -> instrument already open -> invalid risk -> leverage (qty is scaled down to fit; rejected
  only if that leaves less than one lot) -> qty below lot
"""

from __future__ import annotations

import logging
import math
from datetime import datetime

from core.models import (
    ManagementRules,
    Plan,
    Position,
    Rejected,
    RiskAdjustment,
    RiskTier,
    Setup,
    Style,
)

log = logging.getLogger(__name__)


def _floor_to_lot(qty: float, lot: float) -> float:
    steps = math.floor(qty / lot + 1e-9)
    decimals = max(0, -int(math.floor(math.log10(lot)))) if lot < 1 else 0
    return round(steps * lot, decimals)


class RiskEngine:
    def __init__(
        self,
        strategy_styles: dict[str, Style],
        management: ManagementRules | None = None,
        peak_equity: float | None = None,
    ) -> None:
        self.strategy_styles = dict(strategy_styles)
        self.management = management or ManagementRules()
        self.peak_equity = peak_equity
        self.adjustment = RiskAdjustment(kind="none", reason="")

    def register(self, name: str, style: Style) -> None:
        self.strategy_styles[name] = style

    def apply(self, adjustment: RiskAdjustment) -> None:
        """Feedback from the Journal: tier downgrade, risk multiplier, or pause."""
        self.adjustment = adjustment

    def size(
        self, setup: Setup, tier: RiskTier, equity: float, open_positions: list[Position]
    ) -> Plan | Rejected:
        now = setup.ts
        self.peak_equity = max(self.peak_equity or equity, equity)

        if self.adjustment.kind == "pause":
            return self._reject(setup, "paused", self.adjustment.reason or "risk paused", now)

        style = self.strategy_styles.get(setup.strategy)
        if style is None:
            return self._reject(
                setup, "unknown_strategy", f"no style registered for {setup.strategy}", now
            )
        if style not in tier.allowed_styles:
            return self._reject(
                setup, "style_not_allowed", f"{style} not allowed in tier {tier.name}", now
            )

        drawdown_pct = (
            100.0 * (self.peak_equity - equity) / self.peak_equity if self.peak_equity else 0.0
        )
        if drawdown_pct >= tier.max_drawdown_pct:
            return self._reject(
                setup,
                "drawdown_limit",
                f"drawdown {drawdown_pct:.1f}% >= tier limit {tier.max_drawdown_pct}%",
                now,
            )

        live = [p for p in open_positions if not p.closed]
        if len(live) >= tier.max_concurrent:
            return self._reject(
                setup, "max_concurrent", f"{len(live)} open >= tier max {tier.max_concurrent}", now
            )
        if any(p.instrument.key == setup.instrument.key for p in live):
            return self._reject(
                setup, "instrument_open", f"{setup.instrument.key} already open", now
            )

        risk_per_unit = setup.risk_per_unit
        if risk_per_unit <= 0 or equity <= 0:
            return self._reject(setup, "invalid_risk", "stop equals entry or equity is zero", now)

        risk_pct = tier.risk_per_trade_pct * self.adjustment.risk_multiplier
        risk_amount = equity * risk_pct / 100.0
        qty = risk_amount / risk_per_unit
        notes: list[str] = []
        if self.adjustment.kind == "downgrade":
            notes.append(f"risk reduced: {self.adjustment.reason}")

        open_notional = sum(p.notional for p in live)
        max_notional = tier.max_leverage * equity - open_notional
        if qty * setup.entry > max_notional:
            if max_notional <= 0:
                return self._reject(
                    setup,
                    "max_leverage",
                    f"open notional already at tier leverage {tier.max_leverage}x",
                    now,
                )
            qty = max_notional / setup.entry
            notes.append(f"qty scaled down to respect leverage {tier.max_leverage}x")

        lot = setup.instrument.lot_size
        qty = _floor_to_lot(qty, lot)
        if qty < lot or qty <= 0:
            return self._reject(setup, "qty_below_lot", f"size below one lot ({lot})", now)

        notional = qty * setup.entry
        plan = Plan(
            setup=setup,
            tier=tier.name,
            qty=qty,
            risk_amount=qty * risk_per_unit,
            risk_pct=100.0 * qty * risk_per_unit / equity,
            notional=notional,
            leverage=(notional + open_notional) / equity,
            reward_r=setup.reward_r,
            management=self.management,
            notes=notes,
            created_at=now,
        )
        log.info(
            "plan %s %s qty=%s risk=%.2f",
            setup.strategy,
            setup.instrument.key,
            qty,
            plan.risk_amount,
        )
        return plan

    @staticmethod
    def _reject(setup: Setup, code: str, reason: str, now: datetime) -> Rejected:
        r = Rejected(setup=setup, code=code, reason=reason, created_at=now)  # type: ignore[arg-type]
        log.info("rejected %s %s: %s", setup.strategy, setup.instrument.key, reason)
        return r
