"""Content engine records. Posts only ever reach the publisher with status `approved`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

InsightKind = Literal["result_summary", "fees_impact", "gate_outcome", "fold_spread"]
PostStatus = Literal["pending_review", "approved", "rejected", "published", "failed"]


def _id() -> str:
    return uuid.uuid4().hex[:12]


def now_utc() -> datetime:
    return datetime.now(UTC)


class Insight(BaseModel):
    """Numbers extracted from a walk-forward result. No prose, no opinion."""

    id: str = Field(default_factory=_id)
    kind: InsightKind
    strategy: str
    instrument: str  # Instrument.key
    timeframe: str
    rule_text: str
    period_start: datetime
    period_end: datetime
    figures: dict[str, float | int | str | bool]
    created_at: datetime = Field(default_factory=now_utc)


class Post(BaseModel):
    id: str = Field(default_factory=_id)
    insight_id: str
    template_id: str
    text: str  # Arabic, already linted
    status: PostStatus = "pending_review"
    created_at: datetime = Field(default_factory=now_utc)
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    external_id: str | None = None  # id at the publisher (X)
    review_note: str | None = None
    error: str | None = None


class PostMetrics(BaseModel):
    post_id: str
    collected_at: datetime = Field(default_factory=now_utc)
    impressions: int = 0
    likes: int = 0
    reposts: int = 0
    replies: int = 0
    bookmarks: int = 0
    link_clicks: int = 0

    @property
    def engagements(self) -> int:
        return self.likes + self.reposts + self.replies + self.bookmarks

    @property
    def engagement_rate(self) -> float:
        return self.engagements / self.impressions if self.impressions else 0.0


class TemplateScore(BaseModel):
    template_id: str
    n_posts: int
    mean_impressions: float
    mean_engagement_rate: float
    scored_at: datetime = Field(default_factory=now_utc)


class JobRun(BaseModel):
    id: str = Field(default_factory=_id)
    job: str
    started_at: datetime
    finished_at: datetime | None = None
    ok: bool | None = None
    detail: str = ""
