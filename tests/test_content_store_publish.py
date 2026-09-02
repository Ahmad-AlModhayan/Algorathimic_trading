from datetime import timedelta

import httpx
import pytest

from content.metrics import XMetricsClient, collect_metrics, score_templates
from content.models import JobRun, Post, PostMetrics, now_utc
from content.publisher import DryRunPublisher, XPublisher, oauth1_header, publish_due
from content.store import JsonFileStore
from content.templates import compose_post
from tests.content_helpers import sample_insight


@pytest.fixture
def store(tmp_path):
    return JsonFileStore(tmp_path / "content" / "state.json")


def _post(store, **updates) -> Post:
    ins = sample_insight()
    store.add_insight(ins)
    p = compose_post(ins).model_copy(update=updates)
    store.add_post(p)
    return p


def test_json_store_roundtrip_and_persistence(store, tmp_path):
    p = _post(store)
    assert store.get_post(p.id) == p
    assert store.get_insight(p.insight_id).kind == "result_summary"
    store.set_counter("preorders", 3)
    run = JobRun(job="x", started_at=now_utc())
    store.add_job_run(run)
    reopened = JsonFileStore(tmp_path / "content" / "state.json")
    assert reopened.get_post(p.id) == p and reopened.get_counter("preorders") == 3
    assert reopened.list_job_runs()[0].job == "x"
    assert reopened.list_posts(status="pending_review") == [p]


def test_publish_due_only_sends_approved_and_due(store):
    now = now_utc()
    pending = _post(store)
    approved_future = _post(store, status="approved", scheduled_at=now + timedelta(hours=1))
    approved_due = _post(store, status="approved", scheduled_at=now - timedelta(minutes=1))
    rejected = _post(store, status="rejected")
    pub = DryRunPublisher()
    touched = publish_due(store, pub, now)
    assert [t.id for t in touched] == [approved_due.id]
    assert [p.id for p in pub.sent] == [approved_due.id]
    assert store.get_post(approved_due.id).status == "published"
    assert store.get_post(approved_due.id).external_id == "dry-1"
    for p in (pending, approved_future, rejected):
        assert store.get_post(p.id).status == p.status
    assert publish_due(store, pub, now) == []  # nothing left


def test_publish_failure_is_recorded_not_raised(store):
    class Boom:
        def publish(self, post):
            raise RuntimeError("X down")

    p = _post(store, status="approved", scheduled_at=now_utc() - timedelta(minutes=1))
    publish_due(store, Boom())
    got = store.get_post(p.id)
    assert got.status == "failed" and "X down" in got.error


def test_edited_text_with_advice_words_never_publishes(store):
    p = _post(
        store,
        status="approved",
        scheduled_at=now_utc() - timedelta(minutes=1),
        text="توصية: اشتري الآن",
    )
    pub = DryRunPublisher()
    publish_due(store, pub)
    assert pub.sent == [] and store.get_post(p.id).status == "failed"


def test_oauth1_header_known_vector():
    # Twitter's documented example (https://developer.x.com/en/docs/authentication/oauth-1-0a/creating-a-signature)
    h = oauth1_header(
        "POST",
        "https://api.twitter.com/1.1/statuses/update.json",
        consumer_key="xvz1evFS4wEEPTGEFPHBog",
        consumer_secret="kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
        token="370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
        token_secret="LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
        nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg",
        timestamp=1318622958,
    )
    assert h.startswith("OAuth ")
    assert 'oauth_signature_method="HMAC-SHA1"' in h and 'oauth_version="1.0"' in h
    # No body params in our variant, so the signature differs from the doc's; check it is stable.
    assert h == oauth1_header(
        "POST",
        "https://api.twitter.com/1.1/statuses/update.json",
        "xvz1evFS4wEEPTGEFPHBog",
        "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
        "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
        "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
        nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg",
        timestamp=1318622958,
    )


def test_x_publisher_posts_json_with_oauth(store):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["json"] = request.read()
        return httpx.Response(201, json={"data": {"id": "1234567890", "text": "..."}})

    pub = XPublisher(
        "ck", "cs", "at", "as", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    p = _post(store)
    assert pub.publish(p) == "1234567890"
    assert seen["auth"].startswith("OAuth ") and b'"text"' in seen["json"]

    def fail(request):
        return httpx.Response(403, json={"detail": "forbidden"})

    pub = XPublisher(
        "ck", "cs", "at", "as", client=httpx.Client(transport=httpx.MockTransport(fail))
    )
    with pytest.raises(RuntimeError, match="403"):
        pub.publish(p)


class FakeMetrics:
    def __init__(self, data):
        self.data = data

    def fetch(self, ids):
        return {i: PostMetrics(post_id="", **self.data[i]) for i in ids if i in self.data}


def test_collect_metrics_and_score_templates(store):
    now = now_utc()
    a = _post(store, status="published", external_id="1", published_at=now - timedelta(days=1))
    b = _post(
        store,
        status="published",
        external_id="2",
        published_at=now - timedelta(days=2),
        template_id="result_v2",
    )
    _post(
        store, status="published", external_id="3", published_at=now - timedelta(days=40)
    )  # too old
    client = FakeMetrics(
        {
            "1": {"impressions": 1000, "likes": 30, "reposts": 10},
            "2": {"impressions": 500, "likes": 5},
        }
    )
    assert collect_metrics(store, client, now) == 2
    assert store.list_metrics(a.id)[0].engagement_rate == pytest.approx(0.04)
    # a second collection later supersedes the first for scoring
    client.data["1"]["likes"] = 70
    collect_metrics(store, client, now + timedelta(hours=1))
    scores = {s.template_id: s for s in score_templates(store, now + timedelta(hours=2))}
    assert scores["result_v1"].mean_engagement_rate == pytest.approx(0.08)
    assert scores["result_v2"].mean_impressions == 500 and scores["result_v2"].n_posts == 1
    assert store.list_template_scores() and b.template_id == "result_v2"


def test_x_metrics_client_parses_public_metrics():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok"
        assert "public_metrics" in str(request.url)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "1",
                        "public_metrics": {
                            "impression_count": 10,
                            "like_count": 2,
                            "retweet_count": 1,
                            "reply_count": 0,
                            "bookmark_count": 1,
                        },
                    }
                ]
            },
        )

    c = XMetricsClient("tok", client=httpx.Client(transport=httpx.MockTransport(handler)))
    m = c.fetch(["1"])["1"]
    assert (m.impressions, m.likes, m.reposts, m.bookmarks) == (10, 2, 1, 1)


def test_json_store_sees_writes_from_another_instance(tmp_path):
    path = tmp_path / "state.json"
    a, b = JsonFileStore(path), JsonFileStore(path)
    p = _post(a)
    assert b.get_post(p.id) == p  # b was created before the write and still sees it
    b.update_post(p.model_copy(update={"status": "approved", "scheduled_at": now_utc()}))
    assert a.get_post(p.id).status == "approved"
    assert publish_due(a, DryRunPublisher()) and a.get_post(p.id).status == "published"
