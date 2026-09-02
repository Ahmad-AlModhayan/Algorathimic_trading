"""Smoke test: idempotent backfill of Binance spot candles into the Parquet archive.

    uv run python scripts/backfill.py                 # BTC/USDT 4h, last 3 years
    uv run python scripts/backfill.py --symbol ETH/USDT --timeframe 1d --years 2

Run it twice: the second run must report inserted=0.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from core.config import get_settings
from core.data.backfill import backfill
from core.data.store import ParquetCandleStore
from core.instruments.crypto import binance_adapter


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="4h")
    ap.add_argument("--years", type=float, default=3.0)
    args = ap.parse_args()

    settings = get_settings()
    adapter = binance_adapter(settings.binance_api_key, settings.binance_api_secret)
    store = ParquetCandleStore(settings.candles_dir)

    instrument = adapter.instrument(args.symbol)
    print(f"instrument: {instrument.model_dump()}")

    start = datetime.now(UTC) - timedelta(days=365.25 * args.years)
    result = backfill(adapter, store, instrument, args.timeframe, start)
    print(result.summary)
    print(f"archive: {store.path(instrument.venue, instrument.symbol, args.timeframe)}")


if __name__ == "__main__":
    main()
