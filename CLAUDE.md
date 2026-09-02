# Project brief — strategy lab & trade framework (brand name: TBD)

Read fully before touching code. Source of truth for scope, architecture, and non-negotiables.

## What this is
Two layers, one codebase:
1. **Core trade framework** (the real product): asset-agnostic engine for the full trade lifecycle — rules → backtest → walk-forward → paper → risk sizing → live setups → position management → journal → analytics → feedback into risk. Institutional-grade bar: **backtest/live parity**.
2. **Strategy lab** (the first sellable surface): Arabic no-code UI on top of the core. "Test before you risk." The buyer writes a rule, sees its real result after fees on 3 years of data. One-time license.

The same core also drives the **content engine** that publishes backtest results to the brand's X account — the first thing built, because it validates demand and none of it is throwaway.

We sell software that applies **the user's rules**. We never sell an opinion.

## Non-negotiables
1. No advice language anywhere (code, UI, posts, alerts). Never "buy", "recommend", "signal". Use "setup", "meets your rule", "result". `lint_language()` blocks banned words before anything is shown or posted.
2. `RiskEngine` gates every setup. Nothing bypasses it.
3. A strategy is `enabled=false` until it passes the walk-forward criteria below.
4. No auto-execution in V1. Read-only market data. No trade-permission API keys.
5. Asset-agnostic from day one: `Instrument` abstraction; crypto is the first adapter, not the design. No crypto-specific assumptions in `core/`.
6. Solo founder, 10–15 h/week. Every increment testable and shippable alone.

## Stack (modern, actively maintained — verify current versions on setup)
- Python 3.12+, `uv`, Ruff, Pydantic v2, Polars, DuckDB (analytics), `pytest`
- **NautilusTrader** — event-driven engine for backtest ↔ paper ↔ live parity (Rust core)
- **VectorBT** (OSS) — fast parameter sweeps in research only; results must be re-validated in Nautilus before enabling
- Postgres on Supabase (state, users, licenses), Parquet for candle archives
- Workers: APScheduler → migrate to a queue only when needed
- API: FastAPI. Frontend: Next.js (latest), Arabic RTL, Supabase Auth. Payments: Lemon Squeezy or Paddle (merchant of record)
- Publisher: X API (check current tier limits/pricing). Charts: Plotly static export
- Ask before adding any dependency not listed.

## Repository layout
```
core/
  instruments/   # Instrument, adapters: crypto (ccxt/Binance first), later equities
  data/          # ingestion, storage, corporate-action-safe candles
  strategies/    # each implements Strategy; rule DSL → Strategy compiler lives here
  risk/          # RiskTier, RiskEngine, PositionManager
  backtest/      # Nautilus runner, walk-forward, acceptance report
  journal/       # trades, outcomes, analytics, feedback → risk
  models.py
lab/             # FastAPI + Next.js: no-code rule builder, results, license
content/         # insight extraction, post composer, review queue, publisher, metrics
scripts/
tests/
```

## Core contracts (implement exactly; extend only via discussion)
```python
class Instrument(BaseModel):
    venue: str
    symbol: str
    asset_class: Literal["crypto", "equity", "fx"]
    tick_size: float
    lot_size: float
    fee_pct: float
    slippage_pct: float
    trading_hours: str | None  # None = 24/7


class Strategy(Protocol):
    name: str
    style: Literal["swing", "intraday", "scalp"]
    timeframe: str

    def generate(self, candles: pl.DataFrame) -> list[Setup]: ...


class Setup(BaseModel):
    strategy: str
    instrument: Instrument
    side: Literal["long", "short"]
    entry: float
    stop: float
    target: float  # stop required
    rule_text: str
    ts: datetime


class RiskTier(BaseModel):
    name: Literal["low", "medium", "high"]
    risk_per_trade_pct: float  # 0.5 / 1.0 / 2.0
    max_drawdown_pct: float  # 10 / 20 / 30
    max_leverage: float  # 1 / 3 / 5
    max_concurrent: int  # 2 / 4 / 6
    allowed_styles: list[str]  # low: swing; medium: +intraday; high: all


class RiskEngine:
    def size(
        self, setup: Setup, tier: RiskTier, equity: float, open_positions: list[Position]
    ) -> Plan | Rejected: ...


class PositionManager:
    """Manages an open position per its plan: initial stop, break-even move, trailing rule, partial exits, time stop."""

    def on_candle(self, position: Position, candle: Candle) -> list[Action]: ...


class Journal:
    def record(self, plan: Plan, fills: list[Fill], outcome: Outcome) -> None: ...
    def analytics(
        self, user_id
    ) -> Analytics: ...  # expectancy, R-distribution, by style/time/instrument
    def feedback(self, user_id) -> RiskAdjustment: ...  # e.g. losing streak → tier downgrade
```
`Rejected` always carries a reason and is logged — it is product behavior.

## Rule DSL (lab)
Arabic-readable rule → validated AST → compiled `Strategy`. Start with: breakout(N), MA cross, RSI threshold, trend filter, ATR stop, fixed-R target. No free-form code from users.

## Acceptance criteria — a strategy is enabled only if ALL hold on combined out-of-sample folds
- Walk-forward: train 6m / test 2m, rolling; no parameter reuse across folds
- Fees + slippage from `Instrument`; stop/target fills on the touching candle, worst case if both touch
- Profit factor ≥ 1.3 · Max DD ≤ 20% · ≥ 100 trades · positive expectancy in ≥ 70% of folds
- Holds on ≥ 3 instruments and across one bull and one bear period

## Content engine (built first — 2 weeks)
Scheduled jobs: 03:00 ingest + run community strategy list → 04:00 `extract_insight` → `compose_post` (templates, `lint_language`) → review queue → publish at schedule → hourly `collect_metrics` → weekly `score_templates`.
Human touch: **approval only**. Nothing posts without it.
Dashboard (Next.js, becomes the lab UI): review queue with preview, calendar, funnel (engagement → landing clicks → preorders), preorder counter vs target 20, job status.

## Build order
1. Weeks 1–2: `core/data`, Nautilus backtest runner with fees/slippage, walk-forward, one swing strategy, `content/` pipeline end to end, dashboard v0. First post.
2. Weeks 3–4: landing page + paid preorder. **Gate: 20 preorders, or revise the product before continuing.**
3. Months 2–3: RiskEngine, PositionManager, Journal, three styles. Rule DSL + lab UI + license.
4. Months 4–6: launch, journal analytics → risk feedback, second instrument adapter (equities) to prove asset-agnosticism.

## Working agreement
- Tests for new logic; `pytest` green; no network in tests (fixtures).
- Code/comments English; user-facing strings Arabic (RTL).
- When unsure whether wording is "advice", it is. Reword.
- Report gate outcomes honestly: a failed gate is a valid result.

## First task
Set up repo layout, `pyproject.toml` via `uv`, env-based Postgres config, `Instrument` + `candles` schema, Binance adapter with idempotent backfill of BTC/USDT 4h as smoke test. Stop and show me the Nautilus backtest runner plan before writing it.
