-- Paid preorders from the merchant of record. Counted toward the gate when status='paid' and not test_mode.
CREATE TABLE IF NOT EXISTS preorders (
    id          TEXT PRIMARY KEY,               -- provider order id (idempotency key for webhooks)
    provider    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('paid', 'refunded')),
    test_mode   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL,
    doc         JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS preorders_status_idx ON preorders (status, test_mode);
