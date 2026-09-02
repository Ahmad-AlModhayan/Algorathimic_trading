from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from content.store import JsonFileStore
from core.data.store import ParquetCandleStore
from lab.api import app, get_candle_store, get_store, require_admin
from tests.backtest_helpers import bars

RULE = {
    "name": "mine",
    "style": "swing",
    "timeframe": "4h",
    "side": "long",
    "entry": [{"type": "breakout", "n": 5}],
    "filters": [],
    "stop": {"type": "atr", "n": 5, "mult": 2.0},
    "target": {"type": "fixed_r", "r": 2.0},
}


@pytest.fixture
def client(tmp_path):
    rows, price = [], 100.0
    for _ in range(700):
        rows += [(price, price + 1, price - 1, price)] * 5
        rows.append((price, price + 4, price - 1, price + 3))
        price += 3
    cs = ParquetCandleStore(tmp_path / "candles")
    cs.upsert("binance", "BTC/USDT", "4h", bars(rows, t0=datetime(2023, 1, 1, tzinfo=UTC)))
    app.dependency_overrides[get_candle_store] = lambda: cs
    app.dependency_overrides[get_store] = lambda: JsonFileStore(tmp_path / "s.json")
    app.dependency_overrides[require_admin] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_library_lists_three_styles(client):
    lib = client.get("/api/lab/library").json()
    assert {v["rule"]["style"] for v in lib.values()} == {"swing", "intraday", "scalp"}
    assert all(v["text_ar"] for v in lib.values())


def test_backtest_runs_user_rule_with_fixed_params(client):
    r = client.post("/api/lab/backtest", json={"rule": RULE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["instrument"] == "binance:BTC/USDT" and body["bars"] > 4000
    assert (
        body["rule_text"].startswith("close > high(5)")
        and "الإغلاق فوق أعلى 5" in body["rule_text_ar"]
    )
    assert len(body["folds"]) >= 4 and body["oos"]["n_trades"] > 0
    names = {c["name"] for c in body["criteria"]}
    assert names == {"profit_factor", "max_drawdown_pct", "n_trades", "positive_fold_share"}
    assert isinstance(body["meets_criteria"], bool)


def test_backtest_rejects_bad_rule_and_unknown_data(client):
    bad = dict(RULE, entry=[{"type": "ma_cross", "fast": 50, "slow": 20}])
    assert client.post("/api/lab/backtest", json={"rule": bad}).status_code == 422
    assert (
        client.post("/api/lab/backtest", json={"rule": RULE, "symbol": "DOGE/USDT"}).status_code
        == 404
    )
    assert (
        client.post("/api/lab/backtest", json={"rule": dict(RULE, timeframe="1h")}).status_code
        == 409
    )
