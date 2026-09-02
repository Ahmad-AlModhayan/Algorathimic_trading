"""Admin auth, payment webhook, landing events, public results."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from content.models import now_utc
from content.store import JsonFileStore
from content.templates import compose_post
from lab import api as lab_api
from lab.api import app, get_store
from lab.payments import parse_lemonsqueezy, verify_lemonsqueezy
from tests.content_helpers import sample_insight

SECRET = "whsec-test"
TOKEN = "admin-token-123"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def store(tmp_path):
    return JsonFileStore(tmp_path / "state.json")


@pytest.fixture
def client(store, monkeypatch):
    app.dependency_overrides[get_store] = lambda: store
    monkeypatch.setattr(lab_api, "_admin_token", lambda: TOKEN)
    monkeypatch.setattr(lab_api.get_settings(), "lemonsqueezy_signing_secret", SECRET)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _order(order_id="1001", event="order_created", **attrs):
    base = {
        "user_email": "a@b.c",
        "user_name": "A",
        "total": 29900,
        "currency": "SAR",
        "status": "paid",
        "refunded": False,
        "test_mode": False,
    }
    base.update(attrs)
    return {
        "meta": {"event_name": event},
        "data": {"type": "orders", "id": order_id, "attributes": base},
    }


def _signed(payload: dict, secret: str = SECRET) -> tuple[bytes, dict]:
    raw = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {
        "X-Signature": sig,
        "X-Event-Name": payload["meta"]["event_name"],
        "Content-Type": "application/json",
    }


# ---- admin auth ----------------------------------------------------------------------------


def test_admin_endpoints_require_token(client):
    assert client.get("/api/review").status_code == 401
    assert client.get("/api/funnel", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/review", headers=AUTH).status_code == 200
    assert client.get("/api/health").status_code == 200  # public


def test_admin_fails_closed_without_configured_token(client, monkeypatch):
    monkeypatch.setattr(lab_api, "_admin_token", lambda: None)
    assert client.get("/api/review", headers=AUTH).status_code == 503


def test_approve_normalizes_naive_datetime(client, store):
    ins = sample_insight()
    store.add_insight(ins)
    p = compose_post(ins)
    store.add_post(p)
    naive = (datetime.now() + timedelta(hours=1)).replace(microsecond=0).isoformat()
    r = client.post(f"/api/posts/{p.id}/approve", json={"scheduled_at": naive}, headers=AUTH)
    assert r.status_code == 200
    assert store.get_post(p.id).scheduled_at.tzinfo is not None
    assert store.get_post(p.id).scheduled_at > now_utc()  # comparable, no TypeError


# ---- webhook -------------------------------------------------------------------------------


def test_signature_verification():
    raw = b'{"a":1}'
    good = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert verify_lemonsqueezy(raw, good, SECRET)
    assert verify_lemonsqueezy(raw, good.upper(), SECRET)
    assert not verify_lemonsqueezy(raw, good, "other")
    assert not verify_lemonsqueezy(raw + b" ", good, SECRET)
    assert not verify_lemonsqueezy(raw, None, SECRET)
    assert not verify_lemonsqueezy(raw, good, "")


def test_parse_ignores_unrelated_events():
    assert parse_lemonsqueezy(_order(event="subscription_created")) is None
    assert parse_lemonsqueezy({"meta": {"event_name": "order_created"}, "data": {}}) is None
    p = parse_lemonsqueezy(_order())
    assert p.status == "paid" and p.amount_cents == 29900 and p.currency == "SAR" and p.counts
    assert not parse_lemonsqueezy(_order(test_mode=True)).counts
    assert parse_lemonsqueezy(_order(event="order_refunded")).status == "refunded"


def test_webhook_rejects_bad_signature_and_missing_secret(client, monkeypatch):
    raw, headers = _signed(_order(), secret="wrong")
    assert (
        client.post("/api/webhooks/lemonsqueezy", content=raw, headers=headers).status_code == 401
    )
    raw, headers = _signed(_order())
    headers.pop("X-Signature")
    assert (
        client.post("/api/webhooks/lemonsqueezy", content=raw, headers=headers).status_code == 401
    )
    monkeypatch.setattr(lab_api.get_settings(), "lemonsqueezy_signing_secret", None)
    raw, headers = _signed(_order())
    assert (
        client.post("/api/webhooks/lemonsqueezy", content=raw, headers=headers).status_code == 503
    )


def test_webhook_order_lifecycle_counts_toward_gate(client, store):
    def post(payload):
        raw, headers = _signed(payload)
        return client.post("/api/webhooks/lemonsqueezy", content=raw, headers=headers)

    assert post(_order("1")).json()["counts"] is True
    assert post(_order("1")).status_code == 200  # duplicate delivery is idempotent
    assert post(_order("2", test_mode=True)).json()["counts"] is False
    assert post(_order("3")).status_code == 200
    assert post({"meta": {"event_name": "license_key_created"}, "data": {"id": "9"}}).json() == {
        "ignored": "license_key_created"
    }
    funnel = client.get("/api/funnel", headers=AUTH).json()
    assert funnel["preorders"] == 2 and funnel["preorder_target"] == 20

    assert post(_order("3", event="order_refunded")).json()["status"] == "refunded"
    assert post(_order("3")).json()["status"] == "refunded"  # replayed create cannot resurrect
    assert client.get("/api/funnel", headers=AUTH).json()["preorders"] == 1

    client.put("/api/counters/preorders_manual", json={"value": 2}, headers=AUTH)
    f = client.get("/api/funnel", headers=AUTH).json()
    assert f["preorders"] == 3 and f["preorders_manual"] == 2
    listed = client.get("/api/preorders", headers=AUTH).json()
    assert {p["id"] for p in listed} == {"1", "2", "3"}
    assert client.get("/api/preorders").status_code == 401


# ---- landing + public results --------------------------------------------------------------


def test_landing_event_counts_and_tags_ref(client, store):
    assert (
        client.post("/api/public/landing", json={"ref": "x-post-12"}).json()["landing_clicks"] == 1
    )
    client.post("/api/public/landing", json={})
    client.post("/api/public/landing", json={"ref": "x-post-12; DROP TABLE"})
    assert store.get_counter("landing_clicks") == 3
    assert store.get_counter("landing_clicks:x-post-12") == 1
    assert store.get_counter("landing_clicks:x-post-12DROPTABLE") == 1
    assert client.get("/api/funnel", headers=AUTH).json()["link_clicks"] == 3


def test_public_results_only_published_newest_first(client, store):
    ins = sample_insight()
    store.add_insight(ins)
    old = compose_post(ins).model_copy(
        update={"status": "published", "published_at": now_utc() - timedelta(days=2)}
    )
    new = compose_post(ins).model_copy(
        update={"status": "published", "published_at": now_utc(), "text": "الأحدث"}
    )
    store.add_post(old)
    store.add_post(new)
    store.add_post(compose_post(ins))  # pending: must not leak
    r = client.get("/api/public/results").json()
    assert [x["text"] for x in r][0] == "الأحدث" and len(r) == 2
    assert len(client.get("/api/public/results?limit=1").json()) == 1
