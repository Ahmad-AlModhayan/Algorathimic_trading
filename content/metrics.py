"""Engagement metrics per post and weekly template scoring."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Protocol

import httpx

from content.models import PostMetrics, TemplateScore, now_utc
from content.store import ContentStore

X_LOOKUP_URL = "https://api.x.com/2/tweets"


class MetricsClient(Protocol):
    def fetch(self, external_ids: list[str]) -> dict[str, PostMetrics]:
        """external id -> metrics (post_id left empty; the caller fills it)."""
        ...


class XMetricsClient:
    def __init__(self, bearer_token: str, client: httpx.Client | None = None) -> None:
        self._bearer = bearer_token
        self._client = client or httpx.Client(timeout=20)

    def fetch(self, external_ids: list[str]) -> dict[str, PostMetrics]:
        out: dict[str, PostMetrics] = {}
        for i in range(0, len(external_ids), 100):
            batch = external_ids[i : i + 100]
            r = self._client.get(
                X_LOOKUP_URL,
                params={"ids": ",".join(batch), "tweet.fields": "public_metrics"},
                headers={"Authorization": f"Bearer {self._bearer}"},
            )
            r.raise_for_status()
            for row in r.json().get("data", []):
                pm = row.get("public_metrics", {})
                out[str(row["id"])] = PostMetrics(
                    post_id="",
                    impressions=pm.get("impression_count", 0),
                    likes=pm.get("like_count", 0),
                    reposts=pm.get("retweet_count", 0),
                    replies=pm.get("reply_count", 0),
                    bookmarks=pm.get("bookmark_count", 0),
                )
        return out


def collect_metrics(
    store: ContentStore, client: MetricsClient, now: datetime | None = None, max_age_days: int = 14
) -> int:
    """Fetch metrics for posts published in the last `max_age_days`. Returns rows added."""
    now = now or now_utc()
    cutoff = now - timedelta(days=max_age_days)
    posts = [
        p
        for p in store.list_posts(status="published")
        if p.external_id and p.published_at and p.published_at >= cutoff
    ]
    if not posts:
        return 0
    fetched = client.fetch([p.external_id for p in posts if p.external_id])
    n = 0
    for p in posts:
        m = fetched.get(p.external_id or "")
        if m is None:
            continue
        store.add_metrics(m.model_copy(update={"post_id": p.id, "collected_at": now}))
        n += 1
    return n


def score_templates(store: ContentStore, now: datetime | None = None) -> list[TemplateScore]:
    """Latest metrics per post, averaged per template. Persisted and returned."""
    now = now or now_utc()
    latest: dict[str, PostMetrics] = {}
    for m in store.list_metrics():
        if m.post_id not in latest or m.collected_at > latest[m.post_id].collected_at:
            latest[m.post_id] = m
    by_template: dict[str, list[PostMetrics]] = defaultdict(list)
    for post_id, m in latest.items():
        post = store.get_post(post_id)
        if post is not None:
            by_template[post.template_id].append(m)
    scores = [
        TemplateScore(
            template_id=tid,
            n_posts=len(ms),
            mean_impressions=sum(m.impressions for m in ms) / len(ms),
            mean_engagement_rate=sum(m.engagement_rate for m in ms) / len(ms),
            scored_at=now,
        )
        for tid, ms in sorted(by_template.items())
    ]
    store.add_template_scores(scores)
    return scores
