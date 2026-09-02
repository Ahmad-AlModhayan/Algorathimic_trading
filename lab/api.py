"""Lab API (FastAPI). Admin endpoints serve the dashboard and require the admin bearer token.
Public endpoints serve the landing page and the payment webhook.

    uv run uvicorn lab.api:app --reload --port 8000
"""

from __future__ import annotations

import hmac
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from content.models import (
    Insight,
    JobRun,
    License,
    Post,
    PostStatus,
    Preorder,
    TemplateScore,
    now_utc,
)
from content.store import ContentStore, JsonFileStore, PostgresStore, count_paid_preorders
from content.strategy_list import INSTRUMENTS
from core.backtest.acceptance import Criterion, evaluate_instrument
from core.backtest.metrics import Metrics
from core.backtest.walkforward import walk_forward
from core.config import get_settings
from core.data.store import ParquetCandleStore
from core.language import LanguageViolationError, lint_language
from core.models import Instrument
from core.strategies.dsl import Rule, compile_rule
from core.strategies.library import LIBRARY
from lab.payments import (
    EVENT_HEADER,
    SIGNATURE_HEADER,
    parse_lemonsqueezy,
    parse_lemonsqueezy_license,
    verify_lemonsqueezy,
)

app = FastAPI(title="tradelab lab API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
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


def get_candle_store() -> ParquetCandleStore:
    return ParquetCandleStore(get_settings().candles_dir)


Candles = Annotated[ParquetCandleStore, Depends(get_candle_store)]


def _admin_token() -> str | None:
    return get_settings().lab_admin_token


def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
    """Fail closed: no configured token means no admin access at all."""
    token = _admin_token()
    if not token:
        raise HTTPException(503, "LAB_ADMIN_TOKEN is not configured")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not supplied or not hmac.compare_digest(supplied, token):
        raise HTTPException(401, "invalid admin token")


Store = Annotated[ContentStore, Depends(get_store)]
Admin = Depends(require_admin)


def _aware(dt: datetime | None) -> datetime | None:
    """Naive datetimes from clients are taken as UTC so comparisons never blow up later."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


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
    preorders: int  # paid, non-test, from the merchant of record + manual adjustments
    preorders_manual: int
    preorder_target: int
    posts_published: int
    posts_pending: int


class LandingEvent(BaseModel):
    ref: str | None = Field(default=None, max_length=64)


class PublicResult(BaseModel):
    text: str
    published_at: datetime | None


# ---- public --------------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "time": now_utc()}


@app.get("/api/public/results", response_model=list[PublicResult])
def public_results(store: Store, limit: int = 3) -> list[PublicResult]:
    """Latest published posts, newest first. They are public on X already."""
    posts = [p for p in store.list_posts(status="published") if p.published_at]
    posts.sort(key=lambda p: p.published_at or now_utc(), reverse=True)
    return [
        PublicResult(text=p.text, published_at=p.published_at)
        for p in posts[: max(0, min(limit, 10))]
    ]


@app.post("/api/public/landing")
def landing_event(body: LandingEvent, store: Store) -> dict:
    """One landing-page view. No cookies, no identifiers; just a counter and the referrer tag."""
    total = store.increment_counter("landing_clicks")
    ref = "".join(ch for ch in (body.ref or "") if ch.isalnum() or ch in "-_")[:32]
    if ref:
        store.increment_counter(f"landing_clicks:{ref}")
    return {"landing_clicks": total}


@app.post("/api/webhooks/lemonsqueezy")
async def lemonsqueezy_webhook(request: Request, store: Store) -> dict:
    secret = get_settings().lemonsqueezy_signing_secret
    if not secret:
        raise HTTPException(503, "LEMONSQUEEZY_SIGNING_SECRET is not configured")
    raw = await request.body()
    if not verify_lemonsqueezy(raw, request.headers.get(SIGNATURE_HEADER), secret):
        raise HTTPException(401, "bad signature")
    try:
        payload = await request.json()
    except ValueError as e:
        raise HTTPException(400, "invalid JSON") from e
    lic = parse_lemonsqueezy_license(payload)
    if lic is not None:
        existing = store.get_license(lic.key)
        if existing is not None:
            lic = lic.model_copy(update={"created_at": existing.created_at})
        store.upsert_license(lic)
        return {"license": lic.key[-4:], "status": lic.status}
    preorder = parse_lemonsqueezy(payload)
    if preorder is None:
        return {
            "ignored": request.headers.get(EVENT_HEADER)
            or (payload.get("meta") or {}).get("event_name")
        }
    existing = store.get_preorder(preorder.id)
    if existing is not None:
        # keep the original creation time; a refund after a paid order must win, a replayed
        # order_created after a refund must not resurrect it
        status = "refunded" if "refunded" in (existing.status, preorder.status) else "paid"
        preorder = preorder.model_copy(update={"created_at": existing.created_at, "status": status})
    store.upsert_preorder(preorder)
    return {"id": preorder.id, "status": preorder.status, "counts": preorder.counts}


# ---- admin ---------------------------------------------------------------------------------


@app.get("/api/review", response_model=list[ReviewItem], dependencies=[Admin])
def review_queue(store: Store) -> list[ReviewItem]:
    return [
        ReviewItem(post=p, insight=store.get_insight(p.insight_id))
        for p in store.list_posts(status="pending_review")
    ]


@app.get("/api/posts", response_model=list[Post], dependencies=[Admin])
def list_posts(store: Store, status: PostStatus | None = None) -> list[Post]:
    return store.list_posts(status=status)


def _get(store: ContentStore, post_id: str) -> Post:
    post = store.get_post(post_id)
    if post is None:
        raise HTTPException(404, "post not found")
    return post


@app.post("/api/posts/{post_id}/approve", response_model=Post, dependencies=[Admin])
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
            "scheduled_at": _aware(body.scheduled_at) or now_utc(),
            "review_note": None,
            "error": None,
        }
    )
    store.update_post(post)
    return post


@app.post("/api/posts/{post_id}/reject", response_model=Post, dependencies=[Admin])
def reject(post_id: str, body: RejectBody, store: Store) -> Post:
    post = _get(store, post_id)
    if post.status == "published":
        raise HTTPException(409, "already published")
    post = post.model_copy(update={"status": "rejected", "review_note": body.note or None})
    store.update_post(post)
    return post


@app.get("/api/calendar", dependencies=[Admin])
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


@app.get("/api/funnel", response_model=Funnel, dependencies=[Admin])
def funnel(store: Store) -> Funnel:
    latest = {}
    for m in store.list_metrics():
        if m.post_id not in latest or m.collected_at > latest[m.post_id].collected_at:
            latest[m.post_id] = m
    manual = store.get_counter("preorders_manual")
    return Funnel(
        impressions=sum(m.impressions for m in latest.values()),
        engagements=sum(m.engagements for m in latest.values()),
        link_clicks=store.get_counter("landing_clicks"),
        preorders=count_paid_preorders(store) + manual,
        preorders_manual=manual,
        preorder_target=get_settings().preorder_target,
        posts_published=len(store.list_posts(status="published")),
        posts_pending=len(store.list_posts(status="pending_review")),
    )


@app.get("/api/preorders", response_model=list[Preorder], dependencies=[Admin])
def preorders(store: Store) -> list[Preorder]:
    return store.list_preorders()


@app.get("/api/licenses", response_model=list[License], dependencies=[Admin])
def licenses(store: Store) -> list[License]:
    return store.list_licenses()


@app.put("/api/counters/{name}", dependencies=[Admin])
def set_counter(name: str, body: CounterBody, store: Store) -> dict:
    if name not in ("preorders_manual", "landing_clicks"):
        raise HTTPException(404, "unknown counter")
    store.set_counter(name, body.value)
    return {"name": name, "value": body.value}


@app.get("/api/jobs", response_model=list[JobRun], dependencies=[Admin])
def jobs(store: Store, limit: int = 30) -> list[JobRun]:
    return store.list_job_runs(limit=limit)


@app.get("/api/templates/scores", response_model=list[TemplateScore], dependencies=[Admin])
def template_scores(store: Store) -> list[TemplateScore]:
    return store.list_template_scores()


# ---- lab (the no-code builder calls these) --------------------------------------------------


class BacktestRequest(BaseModel):
    rule: Rule
    venue: str = "binance"
    symbol: str = "BTC/USDT"


class FoldSummary(BaseModel):
    test_start: datetime
    test_end: datetime
    n_trades: int
    expectancy_r: float
    total_r: float


class BacktestResponse(BaseModel):
    rule_text: str
    rule_text_ar: str
    instrument: str
    timeframe: str
    bars: int
    folds: list[FoldSummary]
    oos: Metrics
    criteria: list[Criterion]
    meets_criteria: bool  # on this instrument only; enabling needs 3 instruments + regimes


def _instrument(venue: str, symbol: str) -> Instrument:
    for inst in INSTRUMENTS:
        if inst.venue == venue and inst.symbol == symbol:
            return inst
    raise HTTPException(404, f"unknown instrument {venue}:{symbol}")


@app.get("/api/lab/library", dependencies=[Admin])
def lab_library() -> dict[str, dict]:
    return {
        name: {"rule": r.model_dump(), "text": r.to_text(), "text_ar": r.to_arabic()}
        for name, r in LIBRARY.items()
    }


@app.post("/api/lab/backtest", response_model=BacktestResponse, dependencies=[Admin])
def lab_backtest(body: BacktestRequest, candles: Candles) -> BacktestResponse:
    """Walk-forward the user's rule with fixed parameters on the archive. Honest numbers,
    no parameter search: the user chose the parameters."""
    inst = _instrument(body.venue, body.symbol)
    df = candles.read(inst.venue, inst.symbol, body.rule.timeframe)
    if df.height < body.rule.warmup + 10:
        raise HTTPException(
            409, f"not enough {body.rule.timeframe} candles for {inst.key}: {df.height}"
        )
    rule = body.rule
    wf = walk_forward(df, inst, lambda instrument, **_: compile_rule(rule, instrument), {})
    if not wf.folds:
        raise HTTPException(409, "archive shorter than one train+test window (8 months)")
    report = evaluate_instrument(wf)
    return BacktestResponse(
        rule_text=rule.to_text(),
        rule_text_ar=lint_language(rule.to_arabic()),
        instrument=inst.key,
        timeframe=rule.timeframe,
        bars=df.height,
        folds=[
            FoldSummary(
                test_start=f.fold.test_start,
                test_end=f.fold.test_end,
                n_trades=f.test_metrics.n_trades,
                expectancy_r=f.test_metrics.expectancy_r,
                total_r=f.test_metrics.total_r,
            )
            for f in wf.folds
        ],
        oos=wf.oos_metrics,
        criteria=report.criteria,
        meets_criteria=report.passed,
    )


class ActivateBody(BaseModel):
    key: str = Field(min_length=8, max_length=128)


class ActivateResponse(BaseModel):
    valid: bool
    status: str
    email_hint: str  # masked; the UI shows it so the buyer recognizes the account


@app.post("/api/lab/activate", response_model=ActivateResponse)
def activate(body: ActivateBody, store: Store) -> ActivateResponse:
    """Local license check. Keys arrive through the webhook; nothing is looked up remotely."""
    lic = store.get_license(body.key.strip())
    if lic is None:
        return ActivateResponse(valid=False, status="unknown", email_hint="")
    name, _, domain = lic.email.partition("@")
    hint = f"{name[:2]}***@{domain}" if domain else ""
    return ActivateResponse(valid=lic.valid, status=lic.status, email_hint=hint)
