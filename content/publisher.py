"""Publishing. Only `approved` posts whose schedule has arrived are ever sent, and every text
is linted again at the door. `XPublisher` talks to X API v2 with OAuth 1.0a user context
(no extra dependency: signing is stdlib)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import urllib.parse
from datetime import datetime
from typing import Protocol

import httpx

from content.models import Post, now_utc
from content.store import ContentStore
from core.language import lint_language

X_POST_URL = "https://api.x.com/2/tweets"


class Publisher(Protocol):
    def publish(self, post: Post) -> str:
        """Send the post; return the external id. Raise on failure."""
        ...


class DryRunPublisher:
    """Records what would have been sent. Default everywhere until X credentials exist."""

    def __init__(self) -> None:
        self.sent: list[Post] = []

    def publish(self, post: Post) -> str:
        self.sent.append(post)
        return f"dry-{len(self.sent)}"


def oauth1_header(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    token: str,
    token_secret: str,
    nonce: str | None = None,
    timestamp: int | None = None,
) -> str:
    """OAuth 1.0a HMAC-SHA1 Authorization header for a JSON-body request (no body params)."""
    params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(timestamp or int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    q = lambda s: urllib.parse.quote(str(s), safe="")  # noqa: E731
    norm = "&".join(f"{q(k)}={q(v)}" for k, v in sorted(params.items()))
    base = "&".join([method.upper(), q(url), q(norm)])
    key = f"{q(consumer_secret)}&{q(token_secret)}".encode()
    sig = base64.b64encode(hmac.new(key, base.encode(), hashlib.sha1).digest()).decode()
    params["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{q(k)}="{q(v)}"' for k, v in sorted(params.items()))


class XPublisher:
    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        access_token: str,
        access_secret: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._ck, self._cs, self._at, self._as = (
            consumer_key,
            consumer_secret,
            access_token,
            access_secret,
        )
        self._client = client or httpx.Client(timeout=20)

    def publish(self, post: Post) -> str:
        headers = {
            "Authorization": oauth1_header(
                "POST", X_POST_URL, self._ck, self._cs, self._at, self._as
            ),
            "Content-Type": "application/json",
        }
        r = self._client.post(X_POST_URL, json={"text": post.text}, headers=headers)
        if r.status_code >= 300:
            raise RuntimeError(f"X API {r.status_code}: {r.text[:200]}")
        return str(r.json()["data"]["id"])


def publish_due(
    store: ContentStore, publisher: Publisher, now: datetime | None = None
) -> list[Post]:
    """Publish approved posts whose `scheduled_at` <= now. Returns the posts touched."""
    now = now or now_utc()
    touched: list[Post] = []
    for post in store.list_posts(status="approved"):
        if post.scheduled_at is None or post.scheduled_at > now:
            continue
        try:
            lint_language(post.text)  # belt and braces: the text may have been edited in review
            ext = publisher.publish(post)
            post = post.model_copy(
                update={"status": "published", "published_at": now, "external_id": ext}
            )
        except Exception as e:  # noqa: BLE001 - failure is recorded, not raised
            post = post.model_copy(update={"status": "failed", "error": str(e)[:500]})
        store.update_post(post)
        touched.append(post)
    return touched
