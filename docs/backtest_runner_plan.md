# Nautilus backtest runner: plan (option 1 approved and built)

Status: built. Findings from running Nautilus 1.231 that changed the details below:

- Nautilus fills a marketable limit **immediately at submission** against the last price
  (the setup bar close), not on the next bar. The simulator now enters at the setup bar close
  too, plus `slippage_pct`; the entry never expires, so the one-bar cancel in the bridge is a
  live-path safety net only.
- Stops fill exactly at the trigger; targets at the limit. Slippage on entries and stops is
  therefore a simulator-only conservatism, and the parity check names it `slippage`.
- Fill size is capped by bar volume (Nautilus's L1 book uses the synthetic tick size). Real
  4h volume is orders of magnitude above our sizes; synthetic tests must use large volume.
- With `OmsType.NETTING` one Position object is reopened per instrument and the closed history
  is lost. The runner uses `OmsType.HEDGING` so each entry is its own Position.
- Both-touch bars fill the target first on Nautilus's open-high-low-close replay. The
  simulator takes the stop. Parity classifies this as `both_touch` and any trade one engine
  took only because of an earlier divergence as `downstream`.


Target: `core/backtest/`. Nautilus 1.231.0 (Python >=3.12). Installed via `uv sync --extra backtest`.

## The one decision you need to make

The acceptance rule "stop/target fill on the touching candle, worst case if both touch" is not
what Nautilus does. Nautilus bar execution replays each bar as four synthetic ticks in a fixed
order (open, high, low, close; or an adaptive guess with `bar_adaptive_high_low_ordering`).
On a bar that touches both stop and target it fills whichever the ordering reaches first, which
is optimistic for longs on up-bars. There is no config for "worst case".

Options:

1. **Two layers, recommended.** A small deterministic bar simulator in `core/backtest/simulator.py`
   is the reference for acceptance criteria and the content engine. It implements the rules
   exactly (fees, slippage, touching candle, worst case) in ~300 lines of Polars and is trivially
   testable with hand-built candles. The Nautilus runner is the parity engine: it runs the same
   `Strategy` through the same code path that paper and live will use. A parity test runs both on
   the same data and reports the trade-by-trade diff. The known, quantified deviation is the set
   of both-touch bars. Strategies are enabled from the simulator's numbers; Nautilus proves the
   live path behaves the same outside those bars.
2. **Nautilus only.** Accept its ordering and document the deviation from the brief's rule. Fast
   to build, but the acceptance numbers are then optimistic by an unknown amount per strategy.
3. **Nautilus only with synthesized ticks.** Feed Nautilus our own tick sequence per bar in
   worst-case order. Worst case depends on the open position's side, which the data feed cannot
   know ahead of time. Needs a custom data client. Deferred unless you insist.

The rest of this plan assumes option 1.

## Components

| File | Responsibility |
|---|---|
| `core/backtest/simulator.py` | Reference engine. Entry at next bar open after a setup. Stop/target fills on the touching bar, worst case when both touch. Fees and slippage from `Instrument` on both sides. One position per instrument per strategy. Emits `Trade` records. |
| `core/backtest/nautilus_runner.py` | Builds a `BacktestEngine`: one venue per `Instrument.venue`, `CASH` account, `NETTING` OMS, `MakerTakerFeeModel` fed from `Instrument.fee_pct`, deterministic `FillModel` (seeded). Loads Parquet candles into Nautilus `Bar` objects. Runs `StrategyBridge`. Extracts fills and positions into the same `Trade` records. |
| `core/backtest/bridge.py` | `StrategyBridge(nautilus.Strategy)`: on each bar, calls our `Strategy.generate` on the trailing window and submits a bracket (entry + stop + target) for a new `Setup`. Slippage modeled deterministically: entry as a marketable limit at `entry * (1 +/- slippage_pct)`, so paper and live submit the identical order. |
| `core/backtest/metrics.py` | Profit factor, max drawdown, expectancy, R-distribution, trade count; computed from `Trade` records so both engines share one metrics path. |
| `core/backtest/walkforward.py` | Rolling folds: train 6 months, test 2 months, step 2 months. Parameter grid searched on train only (simulator, or VectorBT when installed), frozen for test. Combined out-of-sample trades feed the acceptance report. |
| `core/backtest/acceptance.py` | `AcceptanceReport`: each criterion with its value and pass/fail. `enabled` is true only when every criterion passes on combined OOS folds, on >=3 instruments, and across one bull and one bear window. A failed report is a normal, logged result. |
| `core/backtest/parity.py` | Runs simulator and Nautilus on the same strategy and data, aligns trades by entry timestamp, reports mismatches and classifies each as "both-touch bar" or "unexplained". Unexplained mismatches fail the test. |

## Instrument mapping (Nautilus needs these)

- `Instrument` -> `CurrencyPair`: `price_precision` from `tick_size`, `size_precision` from
  `lot_size`, `taker_fee = maker_fee = fee_pct`. Equity adapter later maps to `Equity` and sets
  trading hours; nothing in `core/backtest` reads venue-specific fields.
- Bars: `BarType` `{symbol}.{venue}-4-HOUR-LAST-EXTERNAL`. Loaded from our Parquet via Polars,
  converted with `BarDataWrangler` (pulls pandas in transitively; no new direct dependency).

## Tests (fixtures only)

- Simulator: hand-built 10-bar sequences covering entry next-open, stop touched, target touched,
  both touched (long and short), gap through stop, fees and slippage arithmetic.
- Walk-forward: fold boundaries on a 2-year synthetic range; no parameter leaks across folds.
- Acceptance: each criterion flips `enabled` independently.
- Nautilus runner: one synthetic instrument, one canned strategy, asserts trade count and PnL
  against the simulator within the both-touch tolerance. Marked `@pytest.mark.backtest` and
  skipped when `nautilus_trader` is not installed.

## Order of work (Weeks 1-2 remainder)

1. `simulator.py` + `metrics.py` + tests. Half a day.
2. `walkforward.py` + `acceptance.py` + tests. Half a day.
3. One swing strategy: breakout(N) with ATR stop and fixed-R target, under `core/strategies/`.
4. `nautilus_runner.py` + `bridge.py` + `parity.py`. One to two days, mostly Nautilus API surface.
5. Content pipeline consumes `AcceptanceReport` and `Trade` records.

## Not in this plan

- Position management beyond initial stop/target (break-even, trailing, time stop): month 2.
- Multiple concurrent positions and `RiskEngine` sizing: month 2. The simulator sizes 1R per
  trade so acceptance metrics are size-independent.
- Live/paper Nautilus nodes: after the preorder gate.
