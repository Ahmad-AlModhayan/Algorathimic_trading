"""Content worker: scheduled jobs, or one job on demand.

    uv run python scripts/content_worker.py                  # run the scheduler (blocks)
    uv run python scripts/content_worker.py --once ingest
    uv run python scripts/content_worker.py --once run_strategies
    uv run python scripts/content_worker.py --once publish
    uv run python scripts/content_worker.py --once collect_metrics
    uv run python scripts/content_worker.py --once score_templates

Without X credentials in .env the publisher is a dry run and metrics are skipped.
"""

from __future__ import annotations

import argparse
import logging
import time

from content import jobs
from content.metrics import XMetricsClient
from content.publisher import DryRunPublisher, XPublisher
from content.store import JsonFileStore, PostgresStore
from core.config import get_settings
from core.data.store import ParquetCandleStore
from core.instruments.crypto import binance_adapter


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--once",
        choices=["ingest", "run_strategies", "publish", "collect_metrics", "score_templates"],
    )
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    s = get_settings()
    if s.content_store == "postgres":
        from core.db import connect

        store = PostgresStore(connect())
    else:
        store = JsonFileStore(s.content_state_path)
    candles = ParquetCandleStore(s.candles_dir)
    adapter = binance_adapter(s.binance_api_key, s.binance_api_secret)
    if s.x_consumer_key and s.x_consumer_secret and s.x_access_token and s.x_access_secret:
        publisher = XPublisher(
            s.x_consumer_key, s.x_consumer_secret, s.x_access_token, s.x_access_secret
        )
    else:
        publisher = DryRunPublisher()
        logging.warning("no X credentials: publisher is a dry run")
    metrics_client = XMetricsClient(s.x_bearer_token) if s.x_bearer_token else None

    if args.once:
        fn = {
            "ingest": lambda: jobs.job_ingest(adapter, candles),
            "run_strategies": lambda: jobs.job_run_strategies(store, candles),
            "publish": lambda: jobs.job_publish(store, publisher),
            "collect_metrics": lambda: (
                jobs.job_collect_metrics(store, metrics_client)
                if metrics_client
                else "no X bearer token"
            ),
            "score_templates": lambda: jobs.job_score_templates(store),
        }[args.once]
        run = jobs.run_job(store, args.once, fn)
        print(f"{run.job}: ok={run.ok}\n{run.detail}")
        return

    sched = jobs.build_scheduler(store, candles, adapter, publisher, metrics_client, s.timezone)
    sched.start()
    logging.info("scheduler running (%s); jobs: %s", s.timezone, [j.id for j in sched.get_jobs()])
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        sched.shutdown()


if __name__ == "__main__":
    main()
