# `webhooks/` — outbound signed webhooks (roadmap 1.21)

When something happens in an organisation — a run finishes, a card is approved, a
pack is exported, a form is submitted — MediaHub POSTs a **signed JSON payload**
to the URLs that org has registered. This is how a club wires MediaHub into its
own tools (or into Zapier/Make via *their* account).

These are *outbound notifications*, not a publishing path: nothing here posts to
a social account. Approval stays a human signal; webhooks just tell you it
happened.

## Files

| File | Role |
|---|---|
| `events.py` | The event catalogue (`run.finished`, `card.approved`, `pack.exported`) + whitelisted payload builders — one source of truth |
| `registry.py` | Per-org endpoint registry (URL, subscribed events, signing secret) — tenant-scoped CRUD |
| `signing.py` | HMAC-SHA256 signing (`X-MediaHub-Signature: t=…,v1=…`, Stripe-style) + a `verify()` for receivers/tests |
| `delivery.py` | `emit()` fan-out, immediate attempt, durable retry with backoff, the delivery log, and the scheduler retry handler |
| `_db.py` | The `webhook_endpoints` + `webhook_deliveries` tables in `DATA_DIR/data.db` |

## Flow

```
engine event ──▶ webhooks.emit(event, profile_id, payload)
                   │  (called from web.py chokepoints; best-effort, never raises)
                   ▼
            for each active endpoint subscribed to the event:
                   enqueue a durable delivery row  ──▶  attempt now (daemon thread)
                                                          │ success → delivered
                                                          │ failure → pending + backoff
                   scheduler "webhook_delivery" task ──▶ deliver_pending() retries due rows
```

## Where it's wired

`web.py` calls `webhooks.emit(...)` at three chokepoints:
- run finished — beside `notify_pack_ready`
- card approved — inside `_phase_w_after_status_change` (the single point both the
  web route and the public API pass through)
- pack exported — inside `_build_run_pack_zip` (shared by the route and the API)

The retry sweep is registered as the scheduler task type `webhook_delivery`.

Human docs: [`docs/WEBHOOKS.md`](../../../docs/WEBHOOKS.md). The management UI and
the REST CRUD live with the rest of the platform API
([`api_public/`](../api_public/README.md)).
