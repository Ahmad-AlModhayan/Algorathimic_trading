"""Parity check: simulator vs Nautilus on the same strategy and data.

Every difference must have a name. Known, accepted classes:
- both_touch: the exit bar touched both stop and target. Simulator takes the stop (worst
  case); Nautilus fills whichever its open-high-low-close replay reaches first.
- slippage: same bars, same exit reason, prices differ by at most `slippage_pct` (the
  simulator charges slippage on entries and stops; Nautilus fills at the market/trigger).
- downstream: a trade only one engine took because an earlier both_touch left the two
  engines in different positions.
Anything else is `unexplained`, and the check fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import polars as pl

from core.backtest.trades import Trade
from core.models import Instrument

Kind = str  # "both_touch" | "slippage" | "downstream" | "unexplained"


@dataclass(frozen=True)
class Mismatch:
    setup_ts: datetime
    kind: Kind
    detail: str


@dataclass
class ParityReport:
    n_sim: int
    n_nautilus: int
    matched: int = 0
    max_r_diff: float = 0.0
    total_r_sim: float = 0.0
    total_r_nautilus: float = 0.0
    mismatches: list[Mismatch] = field(default_factory=list)

    def count(self, kind: Kind) -> int:
        return sum(m.kind == kind for m in self.mismatches)

    @property
    def unexplained(self) -> list[Mismatch]:
        return [m for m in self.mismatches if m.kind == "unexplained"]

    @property
    def passed(self) -> bool:
        return not self.unexplained

    @property
    def summary(self) -> str:
        return (
            f"parity {'PASS' if self.passed else 'FAIL'}: "
            f"sim={self.n_sim} nautilus={self.n_nautilus} "
            f"matched={self.matched} both_touch={self.count('both_touch')} "
            f"slippage={self.count('slippage')} downstream={self.count('downstream')} "
            f"unexplained={len(self.unexplained)} | total R sim={self.total_r_sim:.2f} "
            f"nautilus={self.total_r_nautilus:.2f} max |dR|={self.max_r_diff:.3f}"
        )


def _both_touched(candles: pl.DataFrame, t: Trade, ts: datetime) -> bool:
    row = candles.filter(pl.col("ts") == ts)
    if row.is_empty():
        return False
    h, lo = row["high"][0], row["low"][0]
    return lo <= min(t.stop, t.target) and h >= max(t.stop, t.target)


def compare(
    sim: list[Trade], nautilus: list[Trade], candles: pl.DataFrame, instrument: Instrument
) -> ParityReport:
    tol = instrument.slippage_pct + 1e-9
    by_sim = {t.setup_ts: t for t in sim}
    by_nt = {t.setup_ts: t for t in nautilus}
    rep = ParityReport(
        n_sim=len(sim),
        n_nautilus=len(nautilus),
        total_r_sim=sum(t.r_multiple for t in sim),
        total_r_nautilus=sum(t.r_multiple for t in nautilus),
    )
    diverged_until: datetime | None = None

    for ts in sorted(set(by_sim) | set(by_nt)):
        a, b = by_sim.get(ts), by_nt.get(ts)
        if a is None or b is None:
            only = "nautilus" if a is None else "simulator"
            kind = (
                "downstream"
                if diverged_until is not None and ts < diverged_until
                else "unexplained"
            )
            rep.mismatches.append(Mismatch(ts, kind, f"trade only in {only}"))
            continue
        if a.side != b.side:
            rep.mismatches.append(Mismatch(ts, "unexplained", f"side {a.side} vs {b.side}"))
            continue
        if a.exit_ts != b.exit_ts or a.exit_reason != b.exit_reason:
            first_exit = min(a.exit_ts, b.exit_ts)
            if _both_touched(candles, a, first_exit):
                rep.mismatches.append(
                    Mismatch(
                        ts,
                        "both_touch",
                        f"{a.exit_reason}@{a.exit_ts:%Y-%m-%d %H:%M} vs "
                        f"{b.exit_reason}@{b.exit_ts:%Y-%m-%d %H:%M}",
                    )
                )
                diverged_until = max(a.exit_ts, b.exit_ts, diverged_until or a.exit_ts)
            else:
                rep.mismatches.append(
                    Mismatch(
                        ts,
                        "unexplained",
                        f"exit {a.exit_reason}@{a.exit_ts} vs {b.exit_reason}@{b.exit_ts}",
                    )
                )
            continue
        d_entry = abs(a.entry_price - b.entry_price) / a.entry_price
        d_exit = abs(a.exit_price - b.exit_price) / a.exit_price
        if d_entry > tol or d_exit > tol:
            rep.mismatches.append(
                Mismatch(
                    ts,
                    "unexplained",
                    f"prices entry {a.entry_price} vs {b.entry_price}, "
                    f"exit {a.exit_price} vs {b.exit_price}",
                )
            )
            continue
        rep.matched += 1
        rep.max_r_diff = max(rep.max_r_diff, abs(a.r_multiple - b.r_multiple))
        if d_entry > 0 or d_exit > 0:
            rep.mismatches.append(
                Mismatch(ts, "slippage", f"dR={a.r_multiple - b.r_multiple:+.4f}")
            )
    return rep
