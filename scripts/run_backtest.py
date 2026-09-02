"""Walk-forward + acceptance + parity for one instrument from the local archive.

    uv run python scripts/run_backtest.py --symbol BTC/USDT --timeframe 4h
    uv run python scripts/run_backtest.py --no-parity   # simulator only, no Nautilus needed

Reports honestly: a failed criterion is printed as a result, not an error.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from core.backtest.acceptance import evaluate_instrument
from core.backtest.metrics import compute
from core.backtest.simulator import simulate
from core.backtest.walkforward import walk_forward
from core.config import get_settings
from core.data.store import ParquetCandleStore
from core.language import lint_language
from core.models import Instrument
from core.strategies.breakout import Breakout

GRID = {"n": [10, 20, 40], "atr_n": [14], "atr_mult": [1.5, 2.0, 3.0], "target_r": [1.5, 2.0, 3.0]}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--venue", default="binance")
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="4h")
    ap.add_argument("--fee-pct", type=float, default=0.001)
    ap.add_argument("--slippage-pct", type=float, default=0.0005)
    ap.add_argument("--tick", type=float, default=0.01)
    ap.add_argument("--lot", type=float, default=0.00001)
    ap.add_argument("--no-parity", action="store_true")
    args = ap.parse_args()

    store = ParquetCandleStore(get_settings().candles_dir)
    candles = store.read(args.venue, args.symbol, args.timeframe)
    if candles.is_empty():
        raise SystemExit(
            f"no candles for {args.venue} {args.symbol} {args.timeframe}; run scripts/backfill.py"
        )
    inst = Instrument(
        venue=args.venue,
        symbol=args.symbol,
        asset_class="crypto",
        tick_size=args.tick,
        lot_size=args.lot,
        fee_pct=args.fee_pct,
        slippage_pct=args.slippage_pct,
    )
    print(
        f"{inst.key} {args.timeframe}: {candles.height} bars "
        f"[{candles['ts'].min()} .. {candles['ts'].max()}]"
    )

    wf = walk_forward(candles, inst, Breakout, GRID)
    for f in wf.folds:
        print(
            f"fold {f.fold.index}: test {f.fold.test_start:%Y-%m-%d}..{f.fold.test_end:%Y-%m-%d} "
            f"params={f.params} trades={f.test_metrics.n_trades} "
            f"exp={f.test_metrics.expectancy_r:+.3f}R pf={f.test_metrics.profit_factor:.2f}"
        )
    m = wf.oos_metrics
    print(f"\nout-of-sample: {json.dumps(m.model_dump(), indent=None, default=str)}")
    rep = evaluate_instrument(wf)
    for c in rep.criteria:
        print(
            f"  {'PASS' if c.passed else 'FAIL'} {c.name}: {c.value:.3f} (threshold {c.threshold})"
        )
    outcome = "meets" if rep.passed else "does not meet"
    verdict = lint_language(f"result: {outcome} the acceptance criteria on this instrument")
    print(verdict)

    if not args.no_parity:
        try:
            from core.backtest.nautilus_runner import run_nautilus
            from core.backtest.parity import compare
        except ImportError:
            print("nautilus_trader not installed (uv sync --extra backtest); parity skipped")
            return
        params = wf.folds[-1].params if wf.folds else {}
        strat = Breakout(inst, timeframe=args.timeframe, **params)
        start = datetime.now(UTC).replace(year=datetime.now(UTC).year - 1)
        window = candles.filter(candles["ts"] >= start)
        sim = simulate(window, strat, inst, risk_amount=100.0)
        nt = run_nautilus(window, strat, inst, args.timeframe, risk_amount=100.0)
        print(f"\nparity on last 12 months, params={params}, sim trades={compute(sim).n_trades}")
        print(compare(sim, nt.trades, window, inst).summary)


if __name__ == "__main__":
    main()
