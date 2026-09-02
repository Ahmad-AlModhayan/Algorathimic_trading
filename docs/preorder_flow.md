# Preorder flow (build order step 2)

Gate: 20 paid preorders, or revise the product before continuing. The counter is real:
paid, non-test orders from the merchant of record, plus a manual adjustment for orders taken
outside the checkout.

## Pieces
- Landing page `lab/dashboard/app/page.tsx` (copy in `content/landing.ar.json`, linted).
  CTA links to `NEXT_PUBLIC_CHECKOUT_URL`, a hosted Lemon Squeezy checkout for a one-time
  product. No payment data touches our code.
- Webhook `POST /api/webhooks/lemonsqueezy` (`lab/api.py`, `lab/payments.py`): verifies the
  HMAC signature, upserts a `Preorder` keyed by the provider order id (idempotent), handles
  `order_created` and `order_refunded`. A replayed create never resurrects a refund.
- Funnel: landing views (`POST /api/public/landing`, tagged by `?ref=` from each X post),
  paid preorders, target. Dashboard `/admin` shows it.
- Admin API requires `LAB_ADMIN_TOKEN` (bearer). It fails closed when unset.

## Setup on your side
1. Lemon Squeezy: create the store, a one-time product, note the checkout URL.
2. Webhook: URL `https://<api-host>/api/webhooks/lemonsqueezy`, events `order_created`,
   `order_refunded`, copy the signing secret into `LEMONSQUEEZY_SIGNING_SECRET`.
3. Send a test-mode order. It must appear under `GET /api/preorders` with `test_mode: true`
   and must NOT move the funnel counter.
4. Set `LAB_ADMIN_TOKEN` to a long random string on the API host.

## Unverified assumptions (network to the provider docs was blocked when this was written)
- Signature header name `X-Signature`, hex HMAC-SHA256 over the raw body.
- Attribute names `user_email`, `user_name`, `total` (cents), `currency`, `status`, `refunded`,
  `test_mode`; event names `order_created`, `order_refunded`.
If any differs, the change is confined to `lab/payments.py` and its tests.

## Licenses
Lemon Squeezy issues license keys per order when the product has "license keys" enabled.
`license_key_created` / `license_key_updated` events land in the same webhook and are stored;
`POST /api/lab/activate {key}` answers valid/invalid from that local copy. Enable license keys
on the product and add the two events to the webhook.

## Deliberately not built yet
- Supabase Auth: `/admin` and `/lab` use the admin token today. The buyer-facing lab needs
  Supabase Auth with the license key bound to the account at first sign-in; `/api/lab/activate`
  is the check that binding will call.
- License key delivery: preorders store the buyer email; delivery happens at launch.
- Hosting: API needs a host with a public URL for the webhook; the Next app fits Vercel.
