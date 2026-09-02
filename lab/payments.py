"""Merchant-of-record webhooks. Lemon Squeezy first; the provider-specific surface is these
two functions so switching to Paddle is a matter of replacing them.

UNVERIFIED AGAINST LIVE DOCS (network was blocked when written). Assumed contract:
- header `X-Signature`: hex HMAC-SHA256 of the raw body, keyed by the webhook signing secret
- header `X-Event-Name` duplicates `meta.event_name`
- events of interest: `order_created` (status paid), `order_refunded`
- payload: meta.event_name, data.id, data.attributes.{user_email,user_name,total,currency,
  status,refunded,test_mode}
Confirm at docs.lemonsqueezy.com/help/webhooks before going live; a test-mode order through
the real webhook is the check.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from content.models import Preorder, now_utc

SIGNATURE_HEADER = "X-Signature"
EVENT_HEADER = "X-Event-Name"


def verify_lemonsqueezy(raw_body: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def parse_lemonsqueezy(payload: dict[str, Any]) -> Preorder | None:
    """Return the Preorder state implied by this event, or None for events we ignore."""
    event = (payload.get("meta") or {}).get("event_name", "")
    data = payload.get("data") or {}
    attrs = data.get("attributes") or {}
    order_id = str(data.get("id") or "")
    if not order_id or event not in ("order_created", "order_refunded"):
        return None
    refunded = (
        event == "order_refunded"
        or bool(attrs.get("refunded"))
        or attrs.get("status") == "refunded"
    )
    return Preorder(
        id=order_id,
        provider="lemonsqueezy",
        email=str(attrs.get("user_email") or ""),
        name=attrs.get("user_name"),
        amount_cents=int(attrs.get("total") or 0),
        currency=str(attrs.get("currency") or "USD"),
        status="refunded" if refunded else "paid",
        test_mode=bool(attrs.get("test_mode", False)),
        last_event=event,
        updated_at=now_utc(),
    )
