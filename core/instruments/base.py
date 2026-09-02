"""Adapter contract. `core/` never assumes a venue; adapters translate venue specifics
into `Instrument` and canonical candle frames."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

import polars as pl

from core.models import Instrument


class MarketDataAdapter(Protocol):
    venue: str

    def instrument(self, symbol: str) -> Instrument:
        """Resolve venue metadata (tick, lot, fee) into an Instrument."""
        ...

    def fetch_candles(
        self, symbol: str, timeframe: str, since_ms: int, until_ms: int
    ) -> Iterator[pl.DataFrame]:
        """Yield canonical candle frames covering [since_ms, until_ms), oldest first.
        Batches may overlap; the store de-duplicates by ts."""
        ...
