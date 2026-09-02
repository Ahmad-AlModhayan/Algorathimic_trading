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
