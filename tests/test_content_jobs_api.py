from datetime import UTC, datetime

import polars as pl
import pytest
from fastapi.testclient import TestClient

from content import jobs
from content.store import JsonFileStore
from content.strategy_list import StrategyEntry
from content.templates import compose_post
from core.data.store import ParquetCandleStore
from core.strategies.breakout import Breakout
from lab.api import app, get_store, require_admin
from tests.backtest_helpers import bars
from tests.conftest import FakeAdapter, make_rows
from tests.content_helpers import BTC, sample_insight


@pytest.fixture
def store(tmp_path):
    return JsonFileStore(tmp_path / "state.json")


@pytest.fixture
def client(store):
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[require_admin] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def _synthetic_archive(tmp_path) -> ParquetCandleStore:
    rows, price = [], 100.0
    for _ in range(700):
        rows += [(price, price + 1, price - 1, price)] * 5
        rows.append((price, price + 4, price - 1, price + 3))
        price += 3
    cs = ParquetCandleStore(tmp_path / "candles")
    cs.upsert("binance", "BTC/USDT", "4h", bars(rows, t0=datetime(2023, 1, 1, tzinfo=UTC)))
    return cs


def test_run_job_records_success_and_failure(store):
    ok = jobs.run_job(store, "a", lambda: "fine")
    bad = jobs.run_job(store, "b", lambda: 1 / 0)
    assert ok.ok and ok.detail == "fine" and ok.finished_at
    assert bad.ok is False and "ZeroDivisionError" in bad.detail
    assert [r.job for r in store.list_job_runs()] == ["b", "a"]


def test_job_ingest_uses_adapter_and_dedups(tmp_path, store):
    rows = make_rows(datetime(2024, 1, 1, tzinfo=UTC), 50)
    adapter = FakeAdapter(rows)
    cs = ParquetCandleStore(tmp_path / "c")
    inst = BTC.model_copy(update={"venue": "test"})
    entries = [
        StrategyEntry("breakout", Breakout, {"n": [3]}, instruments=[inst]),
        StrategyEntry("other", Breakout, {"n": [5]}, instruments=[inst]),
    ]
    detail = jobs.job_ingest(adapter, cs, years=10, entries=entries)
    assert detail.count("\n") == 0 and len(adapter.calls) == 1  # same instrument fetched once
    assert cs.read("test", "BTC/USDT", "4h").height > 0


def test_job_run_strategies_queues_posts_for_review(tmp_path, store):
    cs = _synthetic_archive(tmp_path)
    entry = StrategyEntry("breakout", Breakout, {"n": [3, 5], "atr_n": [3]}, instruments=[BTC])
    detail = jobs.job_run_strategies(store, cs, entries=[entry])
    pending = store.list_posts(status="pending_review")
    assert len(pending) == 4 and "posts queued for review" in detail
    assert all(store.get_insight(p.insight_id) for p in pending)
    small = StrategyEntry("breakout", Breakout, {"n": [3]}, timeframe="1d", instruments=[BTC])
    assert "skipped" in jobs.job_run_strategies(store, cs, entries=[small])


def test_build_scheduler_registers_jobs(tmp_path, store):
    class NoPub:
        def publish(self, post):
            return "x"

    sched = jobs.build_scheduler(
        store, ParquetCandleStore(tmp_path), FakeAdapter([]), NoPub(), None, "Asia/Riyadh"
    )
    ids = {j.id for j in sched.get_jobs()}
    assert ids == {"ingest", "run_strategies", "publish", "score_templates"}


def test_api_review_approve_reject_flow(client, store):
    ins = sample_insight()
    store.add_insight(ins)
    p1, p2 = compose_post(ins), compose_post(ins)
    store.add_post(p1)
    store.add_post(p2)

    r = client.get("/api/review")
    assert r.status_code == 200 and len(r.json()) == 2
    assert r.json()[0]["insight"]["kind"] == "result_summary"

    r = client.post(f"/api/posts/{p1.id}/approve", json={"text": "نص معدل: النتيجة بعد الرسوم 12٪"})
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["scheduled_at"]
    assert client.post(f"/api/posts/{p1.id}/approve", json={}).status_code == 409

    r = client.post(f"/api/posts/{p2.id}/approve", json={"text": "توصية: اشتري"})
    assert r.status_code == 422
    r = client.post(f"/api/posts/{p2.id}/reject", json={"note": "weak"})
    assert r.json()["status"] == "rejected" and r.json()["review_note"] == "weak"
    assert client.get("/api/review").json() == []
    assert client.post("/api/posts/nope/reject", json={}).status_code == 404

    cal = client.get("/api/calendar").json()
    assert sum(len(v) for v in cal.values()) == 1
    assert client.get("/api/posts", params={"status": "rejected"}).json()[0]["id"] == p2.id


def test_api_funnel_counters_and_jobs(client, store):
    assert client.put("/api/counters/preorders_manual", json={"value": 7}).status_code == 200
    assert client.put("/api/counters/bogus", json={"value": 1}).status_code == 404
    jobs.run_job(store, "publish", lambda: "published=0 failed=0")
    f = client.get("/api/funnel").json()
    assert f["preorders"] == 7 and f["preorder_target"] == 20 and f["impressions"] == 0
    j = client.get("/api/jobs").json()
    assert j[0]["job"] == "publish" and j[0]["ok"] is True
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/api/templates/scores").json() == []
    assert isinstance(pl.DataFrame(), pl.DataFrame)
