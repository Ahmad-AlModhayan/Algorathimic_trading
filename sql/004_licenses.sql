-- License keys issued by the merchant of record (Lemon Squeezy license_key_* events).
CREATE TABLE IF NOT EXISTS licenses (
    key         TEXT PRIMARY KEY,
    status      TEXT NOT NULL CHECK (status IN ('active','inactive','disabled','expired')),
    created_at  TIMESTAMPTZ NOT NULL,
    doc         JSONB NOT NULL
);
