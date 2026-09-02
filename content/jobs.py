"""Scheduled jobs. Every run is recorded as a JobRun; failures are recorded, not raised.

03:00 ingest + run strategy list -> insights -> posts (pending_review)
every 15 min publish approved posts whose time has come
hourly collect_metrics · weekly score_templates
Nothing is posted without a human setting status=approved in the review queue.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from content.insights import extract_insights
from content.metrics import MetricsClient, collect_metrics, score_templates
from content.models import JobRun, now_utc
from content.publisher import Publisher, publish_due
from content.store import ContentStore
from content.strategy_list import STRATEGY_LIST, StrategyEntry
from content.templates import compose_all
from core.backtest.acceptance import evaluate_instrument
from core.backtest.walkforward import walk_forward
from core.data.backfill import backfill
from core.data.store import ParquetCandleStore
from core.instruments.base import MarketDataAdapter

log = logging.getLogger(__name__)


def run_job(store: ContentStore, name: str, fn: Callable[[], str]) -> JobRun:
    run = JobRun(job=name, started_at=now_utc())
    store.add_job_run(run)
    try:
        detail = fn()
        run = run.model_copy(update={"finished_at": now_utc(), "ok": True, "detail": detail})
    except Exception:  # noqa: BLE001
        run = run.model_copy(
            update={"finished_at": now_utc(), "ok": False, "detail": traceback.format_exc()[-1500:]}
        )
        log.exception("job %s failed", name)
    store.update_job_run(run)
    return run


def job_ingest(
    adapter: MarketDataAdapter,
    candles: ParquetCandleStore,
    years: float = 3.0,
    entries: list[StrategyEntry] | None = None,
) -> str:
    start = datetime.now(UTC) - timedelta(days=365.25 * years)
    lines = []
    seen = set()
    for e in entries or STRATEGY_LIST:
        for inst in e.instruments:
            if (inst.key, e.timeframe) in seen:
                continue
            seen.add((inst.key, e.timeframe))
            lines.append(backfill(adapter, candles, inst, e.timeframe, start).summary)
    return "\n".join(lines)


def job_run_strategies(
    store: ContentStore, candles: ParquetCandleStore, entries: list[StrategyEntry] | None = None
) -> str:
    """Walk-forward every (strategy, instrument), extract insights, compose posts for review."""
    n_posts = 0
    lines = []
    for e in entries or STRATEGY_LIST:
        for inst in e.instruments:
            df = candles.read(inst.venue, inst.symbol, e.timeframe)
            if df.height < 500:
                lines.append(f"{inst.key} {e.timeframe}: only {df.height} bars, skipped")
                continue
            wf = walk_forward(df, inst, e.factory, e.grid)
            report = evaluate_instrument(wf)
            insights = extract_insights(wf, e.timeframe, report)
            for ins in insights:
                store.add_insight(ins)
            posts = compose_all(insights)
            for p in posts:
                store.add_post(p)
            n_posts += len(posts)
            gate = "pass" if report.passed else "fail:" + ",".join(report.failures)
            lines.append(
                f"{e.name} {inst.key}: folds={len(wf.folds)} "
                f"oos_trades={wf.oos_metrics.n_trades} gate={gate} posts={len(posts)}"
            )
    return f"{n_posts} posts queued for review\n" + "\n".join(lines)


def job_publish(store: ContentStore, publisher: Publisher) -> str:
    touched = publish_due(store, publisher)
    ok = sum(p.status == "published" for p in touched)
    return f"published={ok} failed={len(touched) - ok}"


def job_collect_metrics(store: ContentStore, client: MetricsClient) -> str:
    return f"metrics rows added={collect_metrics(store, client)}"


def job_score_templates(store: ContentStore) -> str:
    scores = score_templates(store)
    return (
        "; ".join(f"{s.template_id}: er={s.mean_engagement_rate:.3%} n={s.n_posts}" for s in scores)
        or "no data"
    )


def build_scheduler(
    store: ContentStore,
    candles: ParquetCandleStore,
    adapter: MarketDataAdapter,
    publisher: Publisher,
    metrics_client: MetricsClient | None,
    timezone: str,
):
    """APScheduler wiring. Returns an unstarted BackgroundScheduler."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    sched = BackgroundScheduler(timezone=timezone)
    sched.add_job(
        lambda: run_job(store, "ingest", lambda: job_ingest(adapter, candles)),
        CronTrigger(hour=3, minute=0),
        id="ingest",
    )
    sched.add_job(
        lambda: run_job(store, "run_strategies", lambda: job_run_strategies(store, candles)),
        CronTrigger(hour=4, minute=0),
        id="run_strategies",
    )
    sched.add_job(
        lambda: run_job(store, "publish", lambda: job_publish(store, publisher)),
        CronTrigger(minute="*/15"),
        id="publish",
    )
    if metrics_client is not None:
        sched.add_job(
            lambda: run_job(
                store, "collect_metrics", lambda: job_collect_metrics(store, metrics_client)
            ),
            CronTrigger(minute=5),
            id="collect_metrics",
        )
    sched.add_job(
        lambda: run_job(store, "score_templates", lambda: job_score_templates(store)),
        CronTrigger(day_of_week="sun", hour=6, minute=0),
        id="score_templates",
    )
    return sched
