"""Crypto adapter on ccxt. Binance is the first venue, not the design.
Read-only: never pass trade-permission keys."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import polars as pl

from core.data.candles import from_ohlcv_rows, timeframe_ms
from core.models import Instrument

DEFAULT_SLIPPAGE_PCT = 0.0005  # 5 bps per side; conservative for liquid spot pairs
DEFAULT_TAKER_FEE_PCT = 0.001  # Binance spot base tier


def _step_from_precision(value: Any, precision_mode: int, tick_size_mode: int) -> float:
    """ccxt reports precision either as a step (TICK_SIZE mode) or as decimal digits."""
    if value is None:
        raise ValueError("market precision missing")
    if precision_mode == tick_size_mode:
        return float(value)
    return 10.0 ** -int(value)


class CcxtCryptoAdapter:
    """Any ccxt spot exchange. Construct with an exchange instance so tests can stub it."""

    asset_class = "crypto"

    def __init__(
        self,
        exchange: Any,
        venue: str,
        slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
        batch_limit: int = 1000,
    ) -> None:
        self.exchange = exchange
        self.venue = venue
        self.slippage_pct = slippage_pct
        self.batch_limit = batch_limit

    def instrument(self, symbol: str) -> Instrument:
        markets = self.exchange.load_markets()
        if symbol not in markets:
            raise KeyError(f"{symbol} not listed on {self.venue}")
        m = markets[symbol]
        import ccxt  # local import keeps the constant lookup next to its use

        mode = getattr(self.exchange, "precisionMode", ccxt.TICK_SIZE)
        prec = m.get("precision") or {}
        fee = m.get("taker")
        return Instrument(
            venue=self.venue,
            symbol=symbol,
            asset_class="crypto",
            tick_size=_step_from_precision(prec.get("price"), mode, ccxt.TICK_SIZE),
            lot_size=_step_from_precision(prec.get("amount"), mode, ccxt.TICK_SIZE),
            fee_pct=float(fee) if fee is not None else DEFAULT_TAKER_FEE_PCT,
            slippage_pct=self.slippage_pct,
            trading_hours=None,
        )

    def fetch_candles(
        self, symbol: str, timeframe: str, since_ms: int, until_ms: int
    ) -> Iterator[pl.DataFrame]:
        step = timeframe_ms(timeframe)
        cursor = since_ms
        while cursor < until_ms:
            rows = self.exchange.fetch_ohlcv(
                symbol, timeframe, since=cursor, limit=self.batch_limit
            )
            if not rows:
                return
            rows = [r for r in rows if r[0] < until_ms]
            if not rows:
                return
            yield from_ohlcv_rows(rows)
            last_ts = int(rows[-1][0])
            if last_ts < cursor:  # defensive: venue returned nothing newer
                return
            cursor = last_ts + step


def binance_adapter(api_key: str | None = None, api_secret: str | None = None) -> CcxtCryptoAdapter:
    import ccxt

    exchange = ccxt.binance(
        {
            "apiKey": api_key or "",
            "secret": api_secret or "",
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )
    return CcxtCryptoAdapter(exchange, venue="binance")
