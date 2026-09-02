"""ccxt is stubbed: no network in tests."""

import ccxt
import pytest

from core.data.candles import timeframe_ms
from core.instruments.crypto import CcxtCryptoAdapter
from tests.conftest import make_rows

STEP = timeframe_ms("4h")


class StubExchange:
    precisionMode = ccxt.TICK_SIZE  # noqa: N815 - ccxt attribute name

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def load_markets(self):
        return {
            "BTC/USDT": {"precision": {"price": 0.01, "amount": 1e-05}, "taker": 0.001},
        }

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.calls.append((since, limit))
        out = [r for r in self.rows if r[0] >= since][:limit]
        return out


def test_instrument_from_market(t0):
    adapter = CcxtCryptoAdapter(StubExchange([]), venue="binance")
    inst = adapter.instrument("BTC/USDT")
    assert inst.venue == "binance" and inst.asset_class == "crypto"
    assert inst.tick_size == 0.01 and inst.lot_size == 1e-05 and inst.fee_pct == 0.001
    assert inst.trading_hours is None
    with pytest.raises(KeyError):
        adapter.instrument("DOGE/USDT")


def test_decimal_places_precision_mode(t0):
    ex = StubExchange([])
    ex.precisionMode = ccxt.DECIMAL_PLACES
    ex.load_markets = lambda: {"X/Y": {"precision": {"price": 2, "amount": 3}, "taker": None}}
    inst = CcxtCryptoAdapter(ex, venue="v").instrument("X/Y")
    assert inst.tick_size == pytest.approx(0.01) and inst.lot_size == pytest.approx(0.001)
    assert inst.fee_pct == 0.001  # default when venue omits it


def test_fetch_candles_paginates_and_stops_at_until(t0):
    rows = make_rows(t0, 12)
    ex = StubExchange(rows)
    adapter = CcxtCryptoAdapter(ex, venue="binance", batch_limit=5)
    since = rows[0][0]
    until = rows[10][0]  # exclusive
    batches = list(adapter.fetch_candles("BTC/USDT", "4h", since, until))
    got = sum(b.height for b in batches)
    assert got == 10
    assert [c[0] for c in ex.calls] == [since, since + 5 * STEP, since + 10 * STEP][: len(ex.calls)]
    assert batches[-1]["ts"].dt.epoch("ms")[-1] == rows[9][0]


def test_fetch_candles_handles_empty_response(t0):
    adapter = CcxtCryptoAdapter(StubExchange([]), venue="binance")
    assert list(adapter.fetch_candles("BTC/USDT", "4h", 0, 10 * STEP)) == []
