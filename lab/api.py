"""Lab API (FastAPI). V0 serves the content dashboard: review queue, calendar, funnel, jobs.

uv run uvicorn lab.api:app --reload --port 8000
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from content.models import Insight, JobRun, Post, PostStatus, TemplateScore, now_utc
from content.store import ContentStore, JsonFileStore, PostgresStore
from core.config import get_settings
from core.language import LanguageViolationError, lint_language

app = FastAPI(title="tradelab lab API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def _default_store() -> ContentStore:
    settings = get_settings()
    if settings.content_store == "postgres":
        from core.db import connect

        return PostgresStore(connect())
    return JsonFileStore(settings.content_state_path)


def get_store() -> ContentStore:
    return _default_store()


Store = Annotated[ContentStore, Depends(get_store)]


class ReviewItem(BaseModel):
    post: Post
    insight: Insight | None


class ApproveBody(BaseModel):
    scheduled_at: datetime | None = None
    text: str | None = None  # edited text; re-linted


class RejectBody(BaseModel):
    note: str = ""


class CounterBody(BaseModel):
    value: int


class Funnel(BaseModel):
    impressions: int
    engagements: int
    link_clicks: int
    preorders: int
    preorder_target: int
    posts_published: int
    posts_pending: int


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "time": now_utc()}


@app.get("/api/review", response_model=list[ReviewItem])
def review_queue(store: Store) -> list[ReviewItem]:
    return [
        ReviewItem(post=p, insight=store.get_insight(p.insight_id))
        for p in store.list_posts(status="pending_review")
    ]


@app.get("/api/posts", response_model=list[Post])
def list_posts(store: Store, status: PostStatus | None = None) -> list[Post]:
    return store.list_posts(status=status)


def _get(store: ContentStore, post_id: str) -> Post:
    post = store.get_post(post_id)
    if post is None:
        raise HTTPException(404, "post not found")
    return post


@app.post("/api/posts/{post_id}/approve", response_model=Post)
def approve(post_id: str, body: ApproveBody, store: Store) -> Post:
    post = _get(store, post_id)
    if post.status not in ("pending_review", "rejected", "failed"):
        raise HTTPException(409, f"cannot approve a post with status {post.status}")
    text = post.text
    if body.text is not None and body.text.strip():
        try:
            text = lint_language(body.text.strip())
        except LanguageViolationError as e:
            raise HTTPException(422, str(e)) from e
    post = post.model_copy(
        update={
            "text": text,
            "status": "approved",
            "scheduled_at": body.scheduled_at or now_utc(),
            "review_note": None,
            "error": None,
        }
    )
    store.update_post(post)
    return post


@app.post("/api/posts/{post_id}/reject", response_model=Post)
def reject(post_id: str, body: RejectBody, store: Store) -> Post:
    post = _get(store, post_id)
    if post.status == "published":
        raise HTTPException(409, "already published")
    post = post.model_copy(update={"status": "rejected", "review_note": body.note or None})
    store.update_post(post)
    return post


@app.get("/api/calendar")
def calendar(store: Store, days: int = 14) -> dict[str, list[Post]]:
    """Approved and published posts grouped by day (UTC) for the next/last `days`."""
    now = now_utc()
    lo, hi = now - timedelta(days=days), now + timedelta(days=days)
    out: dict[str, list[Post]] = defaultdict(list)
    for p in store.list_posts():
        when = p.published_at or p.scheduled_at
        if p.status in ("approved", "published") and when and lo <= when <= hi:
            out[when.strftime("%Y-%m-%d")].append(p)
    return dict(sorted(out.items()))


@app.get("/api/funnel", response_model=Funnel)
def funnel(store: Store) -> Funnel:
    latest = {}
    for m in store.list_metrics():
        if m.post_id not in latest or m.collected_at > latest[m.post_id].collected_at:
            latest[m.post_id] = m
    return Funnel(
        impressions=sum(m.impressions for m in latest.values()),
        engagements=sum(m.engagements for m in latest.values()),
        link_clicks=store.get_counter("landing_clicks"),
        preorders=store.get_counter("preorders"),
        preorder_target=get_settings().preorder_target,
        posts_published=len(store.list_posts(status="published")),
        posts_pending=len(store.list_posts(status="pending_review")),
    )


@app.put("/api/counters/{name}")
def set_counter(name: str, body: CounterBody, store: Store) -> dict:
    if name not in ("preorders", "landing_clicks"):
        raise HTTPException(404, "unknown counter")
    store.set_counter(name, body.value)
    return {"name": name, "value": body.value}


@app.get("/api/jobs", response_model=list[JobRun])
def jobs(store: Store, limit: int = 30) -> list[JobRun]:
    return store.list_job_runs(limit=limit)


@app.get("/api/templates/scores", response_model=list[TemplateScore])
def template_scores(store: Store) -> list[TemplateScore]:
    return store.list_template_scores()
