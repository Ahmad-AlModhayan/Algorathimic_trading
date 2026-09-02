"""Nautilus parity engine. Runs a `core.strategies.base.Strategy` through the same code path
paper and live will use: bars in, bracket orders out, fills from Nautilus's simulated exchange.

Requires the `backtest` extra (`uv sync --extra backtest`). Imports are local so `core/`
stays importable without it.

Design notes
- Bars carry the bar CLOSE as `ts_event` (Nautilus convention). Our candles use the open.
- Entry is a LIMIT at `entry * (1 +/- slippage)` valid for exactly one bar: if it has not
  filled when the next bar has been processed, the bridge cancels it. Paper/live submit the
  identical order, so slippage is modeled by the order itself, not by the engine.
- Exits are a STOP_MARKET (stop) and a LIMIT (target) in an OUO bracket.
- Nautilus replays each bar as open, high, low, close. On a bar that touches both stop and
  target it fills whichever the ordering reaches first. The simulator takes the worst case.
  `core.backtest.parity` quantifies exactly that difference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import polars as pl

from core.backtest.trades import Trade
from core.data.candles import CANDLE_COLUMNS, timeframe_ms
from core.models import Instrument, Setup
from core.strategies.base import Strategy, round_to_tick

_TF_TO_NAUTILUS = {"m": "MINUTE", "h": "HOUR", "d": "DAY", "w": "WEEK"}


def _precision(step: float) -> int:
    s = f"{step:.12f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


def bar_type_str(instrument: Instrument, timeframe: str) -> str:
    n, unit = int(timeframe[:-1]), _TF_TO_NAUTILUS[timeframe[-1]]
    return f"{nautilus_symbol(instrument)}.{instrument.venue.upper()}-{n}-{unit}-LAST-EXTERNAL"


def nautilus_symbol(instrument: Instrument) -> str:
    return instrument.symbol.replace("/", "")


def _currency(code: str):
    from nautilus_trader.model.enums import CurrencyType
    from nautilus_trader.model.objects import Currency

    try:
        return Currency.from_str(code)
    except (ValueError, KeyError):
        cur = Currency(
            code=code, precision=8, iso4217=0, name=code, currency_type=CurrencyType.CRYPTO
        )
        Currency.register(cur)
        return cur


def to_nautilus_instrument(instrument: Instrument):
    """Map our Instrument onto a Nautilus instrument. Crypto -> CurrencyPair; equities later."""
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
    from nautilus_trader.model.instruments import CurrencyPair
    from nautilus_trader.model.objects import Price, Quantity

    if instrument.asset_class != "crypto":
        raise NotImplementedError(f"asset_class {instrument.asset_class} not mapped yet")
    base, quote = instrument.symbol.split("/")
    pp, sp = _precision(instrument.tick_size), _precision(instrument.lot_size)
    return CurrencyPair(
        instrument_id=InstrumentId(
            Symbol(nautilus_symbol(instrument)), Venue(instrument.venue.upper())
        ),
        raw_symbol=Symbol(nautilus_symbol(instrument)),
        base_currency=_currency(base),
        quote_currency=_currency(quote),
        price_precision=pp,
        size_precision=sp,
        price_increment=Price(instrument.tick_size, pp),
        size_increment=Quantity(instrument.lot_size, sp),
        maker_fee=Decimal(str(instrument.fee_pct)),
        taker_fee=Decimal(str(instrument.fee_pct)),
        ts_event=0,
        ts_init=0,
    )


def to_bars(candles: pl.DataFrame, instrument: Instrument, timeframe: str, nt_instrument) -> list:
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.objects import Price, Quantity

    bt = BarType.from_str(bar_type_str(instrument, timeframe))
    pp, sp = nt_instrument.price_precision, nt_instrument.size_precision
    step_ns = timeframe_ms(timeframe) * 1_000_000
    out = []
    for ts_ms, o, h, lo, c, v in candles.select(
        pl.col("ts").dt.epoch("ms"), "open", "high", "low", "close", "volume"
    ).iter_rows():
        close_ns = ts_ms * 1_000_000 + step_ns
        out.append(
            Bar(
                bt,
                Price(o, pp),
                Price(h, pp),
                Price(lo, pp),
                Price(c, pp),
                Quantity(max(v, 0.0), sp),
                close_ns,
                close_ns,
            )
        )
    return out


def _make_bridge_class():
    """Built lazily so the module imports without nautilus_trader installed."""
    from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
    from nautilus_trader.model.objects import Price
    from nautilus_trader.trading.strategy import Strategy as NtStrategy

    class StrategyBridge(NtStrategy):
        def __init__(
            self,
            strategy: Strategy,
            instrument: Instrument,
            nt_instrument,
            timeframe: str,
            risk_amount: float,
            lookback: int,
        ) -> None:
            super().__init__()
            self._strategy = strategy
            self._inst = instrument
            self._nt = nt_instrument
            self._bar_type = None
            self._timeframe = timeframe
            self._risk = risk_amount
            self._lookback = max(lookback, strategy.warmup + 1)
            self._step_ms = timeframe_ms(timeframe)
            self._rows: list[tuple] = []
            self._entry_order_id = None
            self.setup_by_order: dict[str, Setup] = {}  # entry client_order_id -> Setup
            self.skipped_setups = 0

        def on_start(self) -> None:
            from nautilus_trader.model.data import BarType

            self._bar_type = BarType.from_str(bar_type_str(self._inst, self._timeframe))
            self.subscribe_bars(self._bar_type)

        def on_bar(self, bar) -> None:
            # The exchange has already matched this bar. An entry still open did not fill -> expire.
            if self._entry_order_id is not None:
                order = self.cache.order(self._entry_order_id)
                if order is not None and order.is_open:
                    self.cancel_order(order)
                self._entry_order_id = None

            open_ms = bar.ts_event // 1_000_000 - self._step_ms
            self._rows.append(
                (
                    open_ms,
                    bar.open.as_double(),
                    bar.high.as_double(),
                    bar.low.as_double(),
                    bar.close.as_double(),
                    bar.volume.as_double(),
                )
            )
            if len(self._rows) > self._lookback:
                del self._rows[: len(self._rows) - self._lookback]
            if len(self._rows) < self._strategy.warmup:
                return
            frame = pl.DataFrame(self._rows, schema=CANDLE_COLUMNS, orient="row").with_columns(
                pl.from_epoch("ts", time_unit="ms").dt.replace_time_zone("UTC")
            )
            bar_open = datetime.fromtimestamp(open_ms / 1000, tz=UTC)
            setups = [s for s in self._strategy.generate(frame) if s.ts == bar_open]
            if not setups:
                return
            if self.cache.positions_open(instrument_id=self._nt.id) or self.cache.orders_open(
                instrument_id=self._nt.id
            ):
                self.skipped_setups += 1
                return
            self._submit(setups[0])

        def _submit(self, s: Setup) -> None:
            slip = self._inst.slippage_pct
            long = s.side == "long"
            limit = round_to_tick(s.entry * (1 + slip if long else 1 - slip), self._inst.tick_size)
            risk_per_unit = abs(limit - s.stop)
            if risk_per_unit <= 0:
                self.skipped_setups += 1
                return
            qty = self._nt.make_qty(self._risk / risk_per_unit)
            if qty.as_double() <= 0:
                self.skipped_setups += 1
                return
            pp = self._nt.price_precision
            bracket = self.order_factory.bracket(
                instrument_id=self._nt.id,
                order_side=OrderSide.BUY if long else OrderSide.SELL,
                quantity=qty,
                entry_order_type=OrderType.LIMIT,
                entry_price=Price(limit, pp),
                time_in_force=TimeInForce.GTC,
                sl_trigger_price=Price(s.stop, pp),
                tp_price=Price(s.target, pp),
                tp_post_only=False,
            )
            self._entry_order_id = bracket.first.client_order_id
            self.setup_by_order[bracket.first.client_order_id.value] = s
            self.submit_order_list(bracket)

    return StrategyBridge


@dataclass
class NautilusRun:
    trades: list[Trade]
    skipped_setups: int
    orders: int
    fills: int
    log: list[str] = field(default_factory=list)


def run_nautilus(
    candles: pl.DataFrame,
    strategy: Strategy,
    instrument: Instrument,
    timeframe: str,
    risk_amount: float = 100.0,
    lookback: int = 500,
    starting_balance: float = 10_000_000.0,
) -> NautilusRun:
    """Run one strategy on one instrument through Nautilus and return Trades."""
    from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
    from nautilus_trader.backtest.models import FillModel, MakerTakerFeeModel
    from nautilus_trader.config import LoggingConfig
    from nautilus_trader.model.enums import AccountType, OmsType, OrderType
    from nautilus_trader.model.identifiers import TraderId, Venue
    from nautilus_trader.model.objects import Money

    nt_inst = to_nautilus_instrument(instrument)
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id=TraderId("LAB-001"), logging=LoggingConfig(bypass_logging=True)
        )
    )
    engine.add_venue(
        venue=Venue(instrument.venue.upper()),
        oms_type=OmsType.HEDGING,  # one Position per entry, so closed history survives
        account_type=AccountType.MARGIN,
        starting_balances=[Money(starting_balance, nt_inst.quote_currency)],
        default_leverage=Decimal(1),
        fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=0),
        fee_model=MakerTakerFeeModel(),
        bar_execution=True,
        bar_adaptive_high_low_ordering=False,
    )
    engine.add_instrument(nt_inst)
    bars = to_bars(candles, instrument, timeframe, nt_inst)
    engine.add_data(bars)
    bridge_cls = _make_bridge_class()
    bridge = bridge_cls(strategy, instrument, nt_inst, timeframe, risk_amount, lookback)
    engine.add_strategy(bridge)
    engine.run()

    step_ms = timeframe_ms(timeframe)
    trades: list[Trade] = []
    for pos in engine.cache.positions_closed(instrument_id=nt_inst.id):
        s = bridge.setup_by_order.get(pos.opening_order_id.value)
        closing = engine.cache.order(pos.closing_order_id) if pos.closing_order_id else None
        reason = (
            "stop"
            if closing is not None and closing.order_type == OrderType.STOP_MARKET
            else "target"
        )
        trades.append(_trade(pos, s, instrument, step_ms, reason, risk_amount, None, None))
    last = candles.row(-1, named=True)
    for pos in engine.cache.positions_open(instrument_id=nt_inst.id):
        s = bridge.setup_by_order.get(pos.opening_order_id.value)
        trades.append(
            _trade(pos, s, instrument, step_ms, "end", risk_amount, last["ts"], last["close"])
        )
    trades.sort(key=lambda t: t.entry_ts)
    result = NautilusRun(
        trades=trades,
        skipped_setups=bridge.skipped_setups,
        orders=len(engine.cache.orders(instrument_id=nt_inst.id)),
        fills=sum(
            o.filled_qty.as_double() > 0 for o in engine.cache.orders(instrument_id=nt_inst.id)
        ),
    )
    engine.dispose()
    return result


def _trade(
    pos: Any,
    s: Setup | None,
    inst: Instrument,
    step_ms: int,
    reason: str,
    risk: float,
    end_ts: datetime | None,
    end_px: float | None,
) -> Trade:
    if s is None:
        raise RuntimeError(f"position {pos.id} has no recorded setup")
    entry_ts = datetime.fromtimestamp((pos.ts_opened // 1_000_000 - step_ms) / 1000, tz=UTC)
    qty = pos.peak_qty.as_double()
    entry_px = pos.avg_px_open
    fees = sum(m.as_double() for m in pos.commissions())
    if reason == "end":
        exit_ts, exit_px = end_ts, float(end_px)
        fees += exit_px * qty * inst.fee_pct  # the closing fee paper/live would pay
        bars_held = int((exit_ts - entry_ts).total_seconds() * 1000 // step_ms)
    else:
        exit_ts = datetime.fromtimestamp((pos.ts_closed // 1_000_000 - step_ms) / 1000, tz=UTC)
        exit_px = pos.avg_px_close
        bars_held = int((pos.ts_closed - pos.ts_opened) // (step_ms * 1_000_000))
    direction = 1 if s.side == "long" else -1
    pnl = direction * (exit_px - entry_px) * qty - fees
    return Trade(
        strategy=s.strategy,
        venue=inst.venue,
        symbol=inst.symbol,
        side=s.side,
        setup_ts=s.ts,
        entry_ts=entry_ts,
        entry_price=entry_px,
        exit_ts=exit_ts,
        exit_price=exit_px,
        exit_reason=reason,
        qty=qty,
        stop=s.stop,
        target=s.target,  # type: ignore[arg-type]
        fees=fees,
        pnl=pnl,
        r_multiple=pnl / risk,
        bars_held=bars_held,
    )
