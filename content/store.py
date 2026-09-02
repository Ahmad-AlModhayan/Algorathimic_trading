"""Content state. `JsonFileStore` for local/dev and tests, `PostgresStore` for production.
Both implement the same `ContentStore` protocol."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from content.models import (
    Insight,
    JobRun,
    Post,
    PostMetrics,
    PostStatus,
    Preorder,
    TemplateScore,
)


class ContentStore(Protocol):
    def add_insight(self, insight: Insight) -> None: ...
    def get_insight(self, insight_id: str) -> Insight | None: ...
    def add_post(self, post: Post) -> None: ...
    def get_post(self, post_id: str) -> Post | None: ...
    def update_post(self, post: Post) -> None: ...
    def list_posts(self, status: PostStatus | None = None) -> list[Post]: ...
    def add_metrics(self, metrics: PostMetrics) -> None: ...
    def list_metrics(self, post_id: str | None = None) -> list[PostMetrics]: ...
    def add_template_scores(self, scores: Iterable[TemplateScore]) -> None: ...
    def list_template_scores(self) -> list[TemplateScore]: ...
    def add_job_run(self, run: JobRun) -> None: ...
    def update_job_run(self, run: JobRun) -> None: ...
    def list_job_runs(self, limit: int = 50) -> list[JobRun]: ...
    def get_counter(self, name: str) -> int: ...
    def set_counter(self, name: str, value: int) -> None: ...
    def increment_counter(self, name: str, by: int = 1) -> int: ...
    def upsert_preorder(self, preorder: Preorder) -> None: ...
    def get_preorder(self, preorder_id: str) -> Preorder | None: ...
    def list_preorders(self) -> list[Preorder]: ...


class JsonFileStore:
    """Single JSON file, reloaded before every operation and rewritten atomically on every
    change, so the API process and the worker process see each other's writes. Fine at
    this scale; `PostgresStore` is the path when it is not."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._d: dict[str, Any] = {
            "insights": {},
            "posts": {},
            "metrics": [],
            "template_scores": [],
            "job_runs": {},
            "counters": {},
            "preorders": {},
        }
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            self._d.update(json.loads(self.path.read_text(encoding="utf-8")))
        for key in ("insights", "posts", "job_runs", "counters", "preorders"):
            self._d.setdefault(key, {})
        for key in ("metrics", "template_scores"):
            self._d.setdefault(key, [])

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._d, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
        tmp.replace(self.path)

    def add_insight(self, insight: Insight) -> None:
        with self._lock:
            self._load()
            self._d["insights"][insight.id] = insight.model_dump(mode="json")
            self._save()

    def get_insight(self, insight_id: str) -> Insight | None:
        self._load()
        raw = self._d["insights"].get(insight_id)
        return Insight.model_validate(raw) if raw else None

    def add_post(self, post: Post) -> None:
        self.update_post(post)

    def get_post(self, post_id: str) -> Post | None:
        self._load()
        raw = self._d["posts"].get(post_id)
        return Post.model_validate(raw) if raw else None

    def update_post(self, post: Post) -> None:
        with self._lock:
            self._load()
            self._d["posts"][post.id] = post.model_dump(mode="json")
            self._save()

    def list_posts(self, status: PostStatus | None = None) -> list[Post]:
        self._load()
        posts = [Post.model_validate(p) for p in self._d["posts"].values()]
        if status:
            posts = [p for p in posts if p.status == status]
        return sorted(posts, key=lambda p: p.created_at)

    def add_metrics(self, metrics: PostMetrics) -> None:
        with self._lock:
            self._load()
            self._d["metrics"].append(metrics.model_dump(mode="json"))
            self._save()

    def list_metrics(self, post_id: str | None = None) -> list[PostMetrics]:
        self._load()
        ms = [PostMetrics.model_validate(m) for m in self._d["metrics"]]
        return [m for m in ms if post_id is None or m.post_id == post_id]

    def add_template_scores(self, scores: Iterable[TemplateScore]) -> None:
        with self._lock:
            self._load()
            self._d["template_scores"].extend(s.model_dump(mode="json") for s in scores)
            self._save()

    def list_template_scores(self) -> list[TemplateScore]:
        self._load()
        return [TemplateScore.model_validate(s) for s in self._d["template_scores"]]

    def add_job_run(self, run: JobRun) -> None:
        self.update_job_run(run)

    def update_job_run(self, run: JobRun) -> None:
        with self._lock:
            self._load()
            self._d["job_runs"][run.id] = run.model_dump(mode="json")
            self._save()

    def list_job_runs(self, limit: int = 50) -> list[JobRun]:
        self._load()
        runs = sorted(
            (JobRun.model_validate(r) for r in self._d["job_runs"].values()),
            key=lambda r: r.started_at,
            reverse=True,
        )
        return runs[:limit]

    def get_counter(self, name: str) -> int:
        self._load()
        return int(self._d["counters"].get(name, 0))

    def set_counter(self, name: str, value: int) -> None:
        with self._lock:
            self._load()
            self._d["counters"][name] = int(value)
            self._save()

    def increment_counter(self, name: str, by: int = 1) -> int:
        with self._lock:
            self._load()
            value = int(self._d["counters"].get(name, 0)) + by
            self._d["counters"][name] = value
            self._save()
            return value

    def upsert_preorder(self, preorder: Preorder) -> None:
        with self._lock:
            self._load()
            self._d["preorders"][preorder.id] = preorder.model_dump(mode="json")
            self._save()

    def get_preorder(self, preorder_id: str) -> Preorder | None:
        self._load()
        raw = self._d["preorders"].get(preorder_id)
        return Preorder.model_validate(raw) if raw else None

    def list_preorders(self) -> list[Preorder]:
        self._load()
        return sorted(
            (Preorder.model_validate(r) for r in self._d["preorders"].values()),
            key=lambda p: p.created_at,
        )


class PostgresStore:
    """Same protocol on Postgres (schema: sql/002_content.sql). Rows hold the model JSON
    plus the columns the dashboard filters on."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def _exec(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self.conn, self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else []

    def add_insight(self, insight: Insight) -> None:
        self._exec(
            "INSERT INTO content_insights (id, kind, created_at, doc) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET doc = EXCLUDED.doc",
            (insight.id, insight.kind, insight.created_at, insight.model_dump_json()),
        )

    def get_insight(self, insight_id: str) -> Insight | None:
        rows = self._exec("SELECT doc FROM content_insights WHERE id=%s", (insight_id,))
        return Insight.model_validate_json(rows[0][0]) if rows else None

    def add_post(self, post: Post) -> None:
        self.update_post(post)

    def get_post(self, post_id: str) -> Post | None:
        rows = self._exec("SELECT doc FROM content_posts WHERE id=%s", (post_id,))
        return Post.model_validate_json(rows[0][0]) if rows else None

    def update_post(self, post: Post) -> None:
        self._exec(
            "INSERT INTO content_posts (id, status, scheduled_at, created_at, doc) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET "
            "status=EXCLUDED.status, scheduled_at=EXCLUDED.scheduled_at, doc=EXCLUDED.doc",
            (post.id, post.status, post.scheduled_at, post.created_at, post.model_dump_json()),
        )

    def list_posts(self, status: PostStatus | None = None) -> list[Post]:
        if status:
            rows = self._exec(
                "SELECT doc FROM content_posts WHERE status=%s ORDER BY created_at", (status,)
            )
        else:
            rows = self._exec("SELECT doc FROM content_posts ORDER BY created_at")
        return [Post.model_validate_json(r[0]) for r in rows]

    def add_metrics(self, metrics: PostMetrics) -> None:
        self._exec(
            "INSERT INTO content_metrics (post_id, collected_at, doc) VALUES (%s,%s,%s)",
            (metrics.post_id, metrics.collected_at, metrics.model_dump_json()),
        )

    def list_metrics(self, post_id: str | None = None) -> list[PostMetrics]:
        if post_id:
            rows = self._exec(
                "SELECT doc FROM content_metrics WHERE post_id=%s ORDER BY collected_at", (post_id,)
            )
        else:
            rows = self._exec("SELECT doc FROM content_metrics ORDER BY collected_at")
        return [PostMetrics.model_validate_json(r[0]) for r in rows]

    def add_template_scores(self, scores: Iterable[TemplateScore]) -> None:
        for s in scores:
            self._exec(
                "INSERT INTO content_template_scores (template_id, scored_at, doc) "
                "VALUES (%s,%s,%s)",
                (s.template_id, s.scored_at, s.model_dump_json()),
            )

    def list_template_scores(self) -> list[TemplateScore]:
        rows = self._exec("SELECT doc FROM content_template_scores ORDER BY scored_at")
        return [TemplateScore.model_validate_json(r[0]) for r in rows]

    def add_job_run(self, run: JobRun) -> None:
        self.update_job_run(run)

    def update_job_run(self, run: JobRun) -> None:
        self._exec(
            "INSERT INTO content_job_runs (id, job, started_at, doc) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET doc=EXCLUDED.doc",
            (run.id, run.job, run.started_at, run.model_dump_json()),
        )

    def list_job_runs(self, limit: int = 50) -> list[JobRun]:
        rows = self._exec(
            "SELECT doc FROM content_job_runs ORDER BY started_at DESC LIMIT %s", (limit,)
        )
        return [JobRun.model_validate_json(r[0]) for r in rows]

    def get_counter(self, name: str) -> int:
        rows = self._exec("SELECT value FROM content_counters WHERE name=%s", (name,))
        return int(rows[0][0]) if rows else 0

    def set_counter(self, name: str, value: int) -> None:
        self._exec(
            "INSERT INTO content_counters (name, value) VALUES (%s,%s) "
            "ON CONFLICT (name) DO UPDATE SET value=EXCLUDED.value",
            (name, value),
        )

    def increment_counter(self, name: str, by: int = 1) -> int:
        rows = self._exec(
            "INSERT INTO content_counters (name, value) VALUES (%s,%s) "
            "ON CONFLICT (name) DO UPDATE SET value = content_counters.value + EXCLUDED.value "
            "RETURNING value",
            (name, by),
        )
        return int(rows[0][0])

    def upsert_preorder(self, preorder: Preorder) -> None:
        self._exec(
            "INSERT INTO preorders (id, provider, status, test_mode, created_at, doc) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET "
            "status=EXCLUDED.status, test_mode=EXCLUDED.test_mode, doc=EXCLUDED.doc",
            (
                preorder.id,
                preorder.provider,
                preorder.status,
                preorder.test_mode,
                preorder.created_at,
                preorder.model_dump_json(),
            ),
        )

    def get_preorder(self, preorder_id: str) -> Preorder | None:
        rows = self._exec("SELECT doc FROM preorders WHERE id=%s", (preorder_id,))
        return Preorder.model_validate_json(rows[0][0]) if rows else None

    def list_preorders(self) -> list[Preorder]:
        rows = self._exec("SELECT doc FROM preorders ORDER BY created_at")
        return [Preorder.model_validate_json(r[0]) for r in rows]


def parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def count_paid_preorders(store: ContentStore) -> int:
    return sum(p.counts for p in store.list_preorders())
