# MediaHub Webhooks

MediaHub can POST a **signed JSON payload** to a URL you control whenever
something happens in your organisation — a run finishes, a card is approved, a
pack is exported, a form is submitted. This is how you wire MediaHub into your
own tools, or into Zapier/Make/n8n via *your* account (we publish recipes; we
don't embed their runtimes). Part of roadmap **1.21**; see also
[`PUBLIC_API.md`](PUBLIC_API.md).

> Webhooks are an outbound *notification* surface. They never carry an action
> that posts content to a social account — approval stays a human signal in the
> app or via the API, and MediaHub only ever exports/downloads for manual posting.

## Registering an endpoint

In the app under **Organisation → API & webhooks**, or via the API:

```bash
curl -X POST "$BASE/api/v1/webhooks" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/hooks/mediahub","events":["run.finished","card.approved"]}'
```

The response includes the **signing secret** (`whsec_…`) **once** — store it to
verify deliveries. (The owner can also see/roll it in the app.) Managing
webhooks needs the `webhooks:manage` scope; listing needs `webhooks:read`.

## Events

| Event | Fires when | `data` fields |
|---|---|---|
| `run.finished` | A pipeline run completes and cards are ready | `run_id`, `card_count`, `meet_name` |
| `card.approved` | A card is approved (UI **or** API) | `run_id`, `card_id`, `via` |
| `pack.exported` | A content pack ZIP is built | `run_id`, `format` |

## Payload

```json
{
  "id": "whd_4f2a…",         // delivery id
  "type": "card.approved",
  "created": "2026-06-23T10:30:00Z",
  "org": "your-club",
  "data": { "run_id": "a1b2c3", "card_id": "swim-1", "via": "web" }
}
```

Payloads are deliberately small and whitelisted — ids, counts, names — never an
internal path or secret.

## Verifying the signature

Every request carries:

```
X-MediaHub-Signature: t=<unix-ts>,v1=<hex hmac-sha256>
X-MediaHub-Event: card.approved
X-MediaHub-Delivery: whd_4f2a…
```

The signature is `HMAC-SHA256(secret, "{t}.{raw_body}")`. Verify it the way you'd
verify Stripe's:

```python
import hashlib, hmac, time

def verify(secret: str, header: str, raw_body: bytes, tolerance=300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    ts, sig = int(parts["t"]), parts["v1"]
    if abs(time.time() - ts) > tolerance:        # replay guard
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + raw_body,
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
```

Verify against the **raw** request body, before any JSON parsing.

## Delivery, retries & failures

- MediaHub attempts delivery immediately, off the request path.
- A non-2xx response or a network error is retried with **exponential backoff**
  (≈30s, 2m, 10m, 1h, 6h — six attempts total), then the delivery is marked
  `failed`. The scheduler runs the retry sweep, so retries survive restarts.
- Every attempt is logged. See an endpoint's history (and re-drive a failed one)
  in the app, or via `GET /api/v1/webhooks/{id}/deliveries`.
- Respond `2xx` quickly (under ~10s, tunable with `MEDIAHUB_WEBHOOK_TIMEOUT`) and
  do slow work asynchronously. Treat deliveries as **at-least-once** and
  **de-duplicate on `id`**.

## Security notes

- Always verify the signature and reject stale timestamps.
- The signing secret is a shared HMAC key — keep it server-side; roll it in the
  app if it leaks (deliveries re-sign with the new secret immediately).
- Endpoints are tenant-isolated: a token only ever sees/*manages its own org's*
  webhooks.
