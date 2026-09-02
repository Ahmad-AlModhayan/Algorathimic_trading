-- Idempotent. Mirrors core.models.Instrument and core.data.candles.CANDLE_SCHEMA.
-- Parquet is the candle archive; this table is the queryable copy used by the lab and content jobs.

CREATE TABLE IF NOT EXISTS instruments (
    venue           TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    asset_class     TEXT NOT NULL CHECK (asset_class IN ('crypto', 'equity', 'fx')),
    tick_size       DOUBLE PRECISION NOT NULL CHECK (tick_size > 0),
    lot_size        DOUBLE PRECISION NOT NULL CHECK (lot_size > 0),
    fee_pct         DOUBLE PRECISION NOT NULL CHECK (fee_pct >= 0),
    slippage_pct    DOUBLE PRECISION NOT NULL CHECK (slippage_pct >= 0),
    trading_hours   TEXT,                       -- NULL = 24/7
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (venue, symbol)
);

CREATE TABLE IF NOT EXISTS candles (
    venue       TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,                  -- '4h', '1d', ...
    ts          TIMESTAMPTZ NOT NULL,           -- bar open time, UTC
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      DOUBLE PRECISION NOT NULL CHECK (volume >= 0),
    PRIMARY KEY (venue, symbol, timeframe, ts)  -- makes any re-ingest a no-op
);

CREATE INDEX IF NOT EXISTS candles_lookup_idx ON candles (venue, symbol, timeframe, ts DESC);
