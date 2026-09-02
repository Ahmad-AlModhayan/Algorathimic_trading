-- Content engine state. Documents are stored as JSON next to the columns the dashboard filters on.

CREATE TABLE IF NOT EXISTS content_insights (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    doc         JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS content_posts (
    id            TEXT PRIMARY KEY,
    status        TEXT NOT NULL CHECK (status IN ('pending_review','approved','rejected','published','failed')),
    scheduled_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL,
    doc           JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS content_posts_status_idx ON content_posts (status, scheduled_at);

CREATE TABLE IF NOT EXISTS content_metrics (
    id            BIGSERIAL PRIMARY KEY,
    post_id       TEXT NOT NULL REFERENCES content_posts (id),
    collected_at  TIMESTAMPTZ NOT NULL,
    doc           JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS content_metrics_post_idx ON content_metrics (post_id, collected_at DESC);

CREATE TABLE IF NOT EXISTS content_template_scores (
    id           BIGSERIAL PRIMARY KEY,
    template_id  TEXT NOT NULL,
    scored_at    TIMESTAMPTZ NOT NULL,
    doc          JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS content_job_runs (
    id          TEXT PRIMARY KEY,
    job         TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    doc         JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS content_job_runs_started_idx ON content_job_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS content_counters (
    name   TEXT PRIMARY KEY,
    value  BIGINT NOT NULL DEFAULT 0
);
