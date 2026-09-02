"""Rule DSL: validated AST -> compiled Strategy. No free-form code from users.

Primitives (per the brief): breakout(N), MA cross, RSI threshold, trend filter, ATR stop,
fixed-R target. A rule is JSON the no-code UI builds; `to_arabic()` renders it for display and
`to_text()` gives the English rule_text that lands on setups and posts.

Short side mirrors every condition: breakout below the lowest low, fast MA crossing below the
slow, RSI on the mirrored level (100 - level, operator flipped), trend below the MA.
"""

from __future__ import annotations

from typing import Annotated, Literal

import polars as pl
from pydantic import BaseModel, Field, model_validator

from core.data.candles import timeframe_ms
from core.models import Instrument, Setup, Style
from core.strategies.base import atr, round_to_tick

STYLE_AR = {"swing": "متأرجح", "intraday": "يومي", "scalp": "سريع"}


class Breakout(BaseModel):
    type: Literal["breakout"] = "breakout"
    n: int = Field(ge=2, le=500)

    @property
    def warmup(self) -> int:
        return self.n + 1

    def long_expr(self, side: str) -> pl.Expr:
        if side == "long":
            return pl.col("close") > pl.col("high").shift(1).rolling_max(window_size=self.n)
        return pl.col("close") < pl.col("low").shift(1).rolling_min(window_size=self.n)

    def to_arabic(self, side: str) -> str:
        return (
            f"الإغلاق فوق أعلى {self.n} شمعة"
            if side == "long"
            else f"الإغلاق تحت أدنى {self.n} شمعة"
        )

    def to_text(self, side: str) -> str:
        return f"close > high({self.n})" if side == "long" else f"close < low({self.n})"


def _ma(col: str, n: int, kind: str) -> pl.Expr:
    c = pl.col(col)
    return c.ewm_mean(span=n, adjust=False) if kind == "ema" else c.rolling_mean(window_size=n)


class MACross(BaseModel):
    type: Literal["ma_cross"] = "ma_cross"
    fast: int = Field(ge=2, le=500)
    slow: int = Field(ge=3, le=1000)
    kind: Literal["sma", "ema"] = "sma"

    @model_validator(mode="after")
    def _order(self) -> MACross:
        if self.fast >= self.slow:
            raise ValueError("fast MA must be shorter than slow MA")
        return self

    @property
    def warmup(self) -> int:
        return self.slow + 2

    def long_expr(self, side: str) -> pl.Expr:
        f, s = _ma("close", self.fast, self.kind), _ma("close", self.slow, self.kind)
        if side == "long":
            return (f > s) & (f.shift(1) <= s.shift(1))
        return (f < s) & (f.shift(1) >= s.shift(1))

    def to_arabic(self, side: str) -> str:
        k = "البسيط" if self.kind == "sma" else "الأسي"
        d = "فوق" if side == "long" else "تحت"
        return f"تقاطع المتوسط {k} {self.fast} {d} المتوسط {self.slow}"

    def to_text(self, side: str) -> str:
        op = "crosses above" if side == "long" else "crosses below"
        return f"{self.kind.upper()}({self.fast}) {op} {self.kind.upper()}({self.slow})"


def rsi_expr(n: int) -> pl.Expr:
    """Cutler's RSI (simple averages). Deterministic and warmup-exact."""
    delta = pl.col("close").diff()
    gain = pl.when(delta > 0).then(delta).otherwise(0.0).rolling_mean(window_size=n)
    loss = pl.when(delta < 0).then(-delta).otherwise(0.0).rolling_mean(window_size=n)
    return pl.when(loss == 0).then(100.0).otherwise(100.0 - 100.0 / (1.0 + gain / loss))


class RSIThreshold(BaseModel):
    type: Literal["rsi"] = "rsi"
    n: int = Field(default=14, ge=2, le=200)
    level: float = Field(gt=0, lt=100)
    op: Literal["<", ">"] = "<"

    @property
    def warmup(self) -> int:
        return self.n + 2

    def _mirrored(self, side: str) -> tuple[float, str]:
        if side == "long":
            return self.level, self.op
        return 100.0 - self.level, (">" if self.op == "<" else "<")

    def long_expr(self, side: str) -> pl.Expr:
        level, op = self._mirrored(side)
        r = rsi_expr(self.n)
        return r < level if op == "<" else r > level

    def to_arabic(self, side: str) -> str:
        level, op = self._mirrored(side)
        return f"مؤشر القوة النسبية({self.n}) {'أقل من' if op == '<' else 'أكبر من'} {level:g}"

    def to_text(self, side: str) -> str:
        level, op = self._mirrored(side)
        return f"RSI({self.n}) {op} {level:g}"


class TrendFilter(BaseModel):
    type: Literal["trend"] = "trend"
    n: int = Field(ge=2, le=1000)
    kind: Literal["sma", "ema"] = "sma"

    @property
    def warmup(self) -> int:
        return self.n + 1

    def long_expr(self, side: str) -> pl.Expr:
        m = _ma("close", self.n, self.kind)
        return pl.col("close") > m if side == "long" else pl.col("close") < m

    def to_arabic(self, side: str) -> str:
        return f"الإغلاق {'فوق' if side == 'long' else 'تحت'} المتوسط {self.n}"

    def to_text(self, side: str) -> str:
        return f"close {'>' if side == 'long' else '<'} {self.kind.upper()}({self.n})"


Condition = Annotated[Breakout | MACross | RSIThreshold, Field(discriminator="type")]


class ATRStop(BaseModel):
    type: Literal["atr"] = "atr"
    n: int = Field(default=14, ge=2, le=200)
    mult: float = Field(gt=0, le=10)

    @property
    def warmup(self) -> int:
        return self.n + 1

    def to_arabic(self) -> str:
        return f"وقف {self.mult:g}×ATR({self.n})"

    def to_text(self) -> str:
        return f"stop = close -/+ {self.mult:g}*ATR({self.n})"


class PctStop(BaseModel):
    type: Literal["pct"] = "pct"
    pct: float = Field(gt=0, le=50)

    @property
    def warmup(self) -> int:
        return 1

    def to_arabic(self) -> str:
        return f"وقف {self.pct:g}٪"

    def to_text(self) -> str:
        return f"stop = close -/+ {self.pct:g}%"


Stop = Annotated[ATRStop | PctStop, Field(discriminator="type")]


class FixedRTarget(BaseModel):
    type: Literal["fixed_r"] = "fixed_r"
    r: float = Field(gt=0, le=20)

    def to_arabic(self) -> str:
        return f"هدف {self.r:g}R"

    def to_text(self) -> str:
        return f"target = {self.r:g}R"


class Rule(BaseModel):
    """A complete, validated user rule."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    style: Style
    timeframe: str
    side: Literal["long", "short", "both"] = "long"
    entry: list[Condition] = Field(min_length=1, max_length=4)
    filters: list[TrendFilter] = Field(default_factory=list, max_length=2)
    stop: Stop
    target: FixedRTarget

    @model_validator(mode="after")
    def _timeframe(self) -> Rule:
        timeframe_ms(self.timeframe)  # raises on junk
        return self

    @property
    def warmup(self) -> int:
        parts = (
            [c.warmup for c in self.entry] + [f.warmup for f in self.filters] + [self.stop.warmup]
        )
        return max(parts) + 1

    @property
    def sides(self) -> list[str]:
        return ["long", "short"] if self.side == "both" else [self.side]

    def to_text(self) -> str:
        side = self.sides[0]
        entry = " & ".join(c.to_text(side) for c in self.entry)
        flt = "".join(f" | filter {f.to_text(side)}" for f in self.filters)
        both = " (both sides)" if self.side == "both" else ""
        return f"{entry}{flt} | {self.stop.to_text()} | {self.target.to_text()}{both}"

    def to_arabic(self) -> str:
        side = self.sides[0]
        entry = " و ".join(c.to_arabic(side) for c in self.entry)
        flt = "".join(f" · فلتر: {f.to_arabic(side)}" for f in self.filters)
        both = " · الاتجاهان" if self.side == "both" else ""
        return (
            f"{STYLE_AR[self.style]} · {self.timeframe} · دخول: {entry}{flt} · "
            f"{self.stop.to_arabic()} · {self.target.to_arabic()}{both}"
        )


class CompiledStrategy:
    """Implements the Strategy protocol from a Rule. Causal by construction: every
    expression uses only the current and earlier rows."""

    def __init__(self, rule: Rule, instrument: Instrument) -> None:
        self.rule = rule
        self.instrument = instrument
        self.name = rule.name
        self.style = rule.style
        self.timeframe = rule.timeframe
        self.warmup = rule.warmup
        self.rule_text = rule.to_text()

    def generate(self, candles: pl.DataFrame) -> list[Setup]:
        if candles.height < self.warmup:
            return []
        rule = self.rule
        cols: dict[str, pl.Expr] = {}
        for side in rule.sides:
            ok = pl.lit(True)
            for c in rule.entry:
                ok = ok & c.long_expr(side)
            for f in rule.filters:
                ok = ok & f.long_expr(side)
            cols[f"{side}_ok"] = ok.fill_null(False)
        if isinstance(rule.stop, ATRStop):
            cols["dist"] = rule.stop.mult * atr(candles, rule.stop.n)
        else:
            cols["dist"] = pl.col("close") * rule.stop.pct / 100.0
        df = candles.with_columns(**cols)
        tick = self.instrument.tick_size
        setups: list[Setup] = []
        for row in df.select("ts", "close", "dist", *(f"{s}_ok" for s in rule.sides)).iter_rows(
            named=True
        ):
            dist = row["dist"]
            if dist is None or dist <= 0:
                continue
            entry = round_to_tick(row["close"], tick)
            for side in rule.sides:
                if not row[f"{side}_ok"]:
                    continue
                if side == "long":
                    stop = round_to_tick(entry - dist, tick)
                    target = round_to_tick(entry + rule.target.r * (entry - stop), tick)
                    valid = stop < entry < target
                else:
                    stop = round_to_tick(entry + dist, tick)
                    target = round_to_tick(entry - rule.target.r * (stop - entry), tick)
                    valid = target < entry < stop
                if valid:
                    setups.append(
                        Setup(
                            strategy=self.name,
                            instrument=self.instrument,
                            side=side,  # type: ignore[arg-type]
                            entry=entry,
                            stop=stop,
                            target=target,
                            rule_text=self.rule_text,
                            ts=row["ts"],
                        )
                    )
                    break  # one setup per bar; long wins if both fire
        return setups


def compile_rule(rule: Rule, instrument: Instrument) -> CompiledStrategy:
    return CompiledStrategy(rule, instrument)


def rule_from_json(data: dict) -> Rule:
    return Rule.model_validate(data)
