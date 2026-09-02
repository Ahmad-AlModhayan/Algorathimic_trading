# tradelab (brand name TBD)

Asset-agnostic trade framework and an Arabic no-code strategy lab on top of it.
We sell software that applies **the user's rules**. We never sell an opinion.
See `CLAUDE.md` for scope, architecture and non-negotiables.

## Setup

```bash
uv sync --group dev            # Python 3.12, all runtime + dev deps
cp .env.example .env           # fill DATABASE_URL, DATA_DIR
uv run pytest                  # no network in tests
uv run ruff check . && uv run ruff format --check .
```

Optional extras, installed on purpose, not by default:

```bash
uv sync --extra backtest       # nautilus_trader (after the runner plan is approved)
uv sync --extra research       # vectorbt (parameter sweeps only)
```

## Smoke test: idempotent Binance backfill

```bash
uv run python scripts/backfill.py                      # BTC/USDT 4h, last 3 years
uv run python scripts/backfill.py                      # second run must print inserted=0
```

Candles land in `$DATA_DIR/candles/binance/BTC-USDT/4h.parquet`. Only closed bars are stored.
Postgres schema is in `sql/`; apply with `core.db.apply_schema(core.db.connect())`.

## Backtest: walk-forward, acceptance, parity

```bash
uv run python scripts/run_backtest.py                  # breakout(N) on BTC/USDT 4h from the archive
uv run python scripts/run_backtest.py --no-parity      # simulator only
```

Two engines, one `Trade` record, one metrics path:

- `core/backtest/simulator.py` is the reference. It applies the acceptance rules exactly:
  entry at the setup bar close plus slippage, stop/target on the touching bar, worst case when
  both touch, fees both sides.
- `core/backtest/nautilus_runner.py` runs the same `Strategy` through NautilusTrader with the
  same bracket order paper/live will use. `core/backtest/parity.py` diffs the two and names
  every difference (`both_touch`, `slippage`, `downstream`); anything `unexplained` fails.

A strategy is `enabled` only when `core/backtest/acceptance.py` passes on combined
out-of-sample folds (`walkforward.py`: train 6 months, test 2 months, rolling), on at least
three instruments, and across one bull and one bear window.

## Content engine and dashboard v0

```bash
uv run python scripts/content_worker.py --once run_strategies   # walk-forward -> insights -> posts for review
uv run uvicorn lab.api:app --port 8000                          # review queue API
cd lab/dashboard && npm install && npm run dev                  # Arabic RTL dashboard on :3000
uv run python scripts/content_worker.py                         # scheduler: 03:00 ingest, 04:00 run, publish every 15 min
```

Nothing is posted without a human approving it in the review queue. Without X credentials in
`.env` the publisher is a dry run. Every post text passes `lint_language()` at composition,
again on edit, and once more at the publisher's door.

## Landing page and preorders

`lab/dashboard` serves the public landing page at `/` and the dashboard at `/admin`.
Preorders arrive through the Lemon Squeezy webhook (`/api/webhooks/lemonsqueezy`), are stored
idempotently, and count toward the gate of 20 only when paid and not in test mode.
See `docs/preorder_flow.md`. The admin API needs `LAB_ADMIN_TOKEN`.

## Layout

```
core/            engine: instruments, data, strategies, risk, backtest, journal, models.py
lab/             FastAPI + Next.js no-code rule builder (later)
content/         insight extraction, post composer, review queue, publisher (later)
scripts/         operational entry points
sql/             idempotent Postgres schema files, applied in name order
tests/           pytest, fixtures only
docs/            plans and decisions
```
