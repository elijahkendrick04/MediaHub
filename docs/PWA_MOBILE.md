# Mobile PWA (roadmap 1.22)

> **Status:** Active. MediaHub is hosted-only (ADR-0011) — there is no desktop
> install and no native-store app. The mobile story is **one responsive web
> app, made properly mobile, then a PWA**: installable, share-target capture,
> camera capture, and an offline-tolerant approval queue. Offline tolerance is
> a browser cache, **not** a self-host/install product path.

This document describes the Progressive Web App surface: what it adds, where it
lives in the code, and the rules it respects.

## Why this exists

The highest-value mobile behaviours for a poolside volunteer are: **share a
photo from the camera roll straight into the club's media library**, **take a
photo into the library**, and **approve / caption content on the bus** — even
when the signal drops. The PWA delivers exactly those, reusing the existing
hosted state (cross-device sync is therefore inherent — there is nothing new to
sync).

## What's in the layer

### 1. Installable app shell

- **Manifest** — `GET /manifest.webmanifest` (`web_manifest`): name, standalone
  display, theme/background colours, **maskable PNG icons** (192 + 512, rendered
  from the podium mark by `_app_icon_png` and served at `/icon-<size>.png`), plus
  an SVG icon. `start_url` / `scope` resolve through any deployed prefix.
- **Service worker** — `GET /sw.js` (`service_worker`), root-scoped via the
  `Service-Worker-Allowed` header. Network-first for the shell (an online user
  can never be served a stale page), cache + a tiny offline page as the fallback.
- **Registration** — every page registers the worker and links the manifest
  (see the shared `<head>` in `_layout`).
- **Install affordance** — `static/js/pwa-install.js` captures
  `beforeinstallprompt` (Chromium/Android) and offers a calm install chip; iOS
  Safari (no such event) gets a one-time "Add to Home Screen" hint. Dismissible,
  remembered, and never shown once the app already runs standalone.

### 2. Share-target capture → media library

The manifest declares a **Web Share Target**, so the installed app appears in the
phone's OS share sheet. Sharing one or more photos POSTs them to
`POST /share-target` (`share_target_receiver`), which:

- saves each image into the **active organisation's** media library (the same
  `_save_library_photo` path the upload form uses — storage + HEIC normalisation
  handled identically),
- skips non-image attachments and HEIC photos that can't be decoded (counted),
- redirects to `/media-library?shared=N&skipped=M` with a success banner.

The OS share sheet can't carry a CSRF token, so `/share-target` is on the CSRF
exempt list. This is safe: it only ever writes a **non-destructive, immediately
visible** asset into the **signed-in** session's own library, and it still
requires an active profile (it bounces to sign-in otherwise).

### 3. Camera capture + on-device downscale

The media-library upload form gains a **"Take photo"** affordance
(`<input capture="environment">`, driven by `static/js/mobile-capture.js`) that
opens the device camera. Large photos are **downscaled in a `<canvas>`** before
upload so a volunteer on a slow connection isn't sending a 12-megapixel original.
It's progressive enhancement: with no JS the form posts exactly as before, and
any downscale/AJAX failure falls back to a native submit.

> The camera is reached via `<input capture>`, **not** `getUserMedia`, so the
> `Permissions-Policy: camera=()` header stays locked.

### 4. Offline-tolerant approval queue

Approve / reject / caption-edit all POST to `/api/workflow/<run>/<card>`. The
service worker intercepts these:

- **Online** → the request passes straight through.
- **Offline** → it's persisted to an **IndexedDB** queue (`mediahub-pwa` →
  `approval-queue`), a **Background Sync** (`mediahub-approval-queue`) is
  registered, and a synthetic `202 {queued:true}` is returned so the optimistic
  UI stands and the volunteer keeps triaging.
- **Reconnect** → the `sync` handler drains the queue **in submission order**,
  replaying each request. A final server decision (`status < 500`) drops the
  entry; a `5xx`/network error keeps it for the next sync.

Replay is always safe because **the workflow API is idempotent** — re-approving
a card is a no-op (pinned by `test_pwa_offline_queue.py`).

A client script (`static/js/offline-queue.js`) keeps a small **"N changes
waiting to sync → All changes synced"** status pill in step with the worker, and
nudges a replay on the `online` event (the fallback for browsers without
Background Sync, notably iOS Safari). The `[data-mh-wf]` approval handler is
queue-aware: offline it shows an honest *"Saved offline — will sync when you
reconnect"* toast.

### 5. Mobile-first review / caption / crop

The desktop-primary review surface is already responsive (the
[responsive guardrails](RESPONSIVE_DESIGN.md) + the U.4 / U.13 mobile passes —
46px triage targets, the floating action dock). On top of that, the **card
inspector** (caption box, accent swatches, focus-crop grid) becomes a
**thumb-reachable bottom sheet** on phones (`@media (max-width: 560px)`): it
rises from the bottom edge with rounded top corners and a grab handle, and the
crop cells grow to 44px tap targets. Full canvas editing stays desktop-primary —
the phone scope is the volunteer jobs: approve, caption tweak, photo pick, quick
crop.

### 6. Guest access & cross-device sync

Guest / logged-out viewing is the existing **1.18 share tokens**; cross-device
sync is **inherent** (server-side hosted state). Neither needed new work for
1.22 — they're noted here for completeness.

## Where the code lives

| Concern | File / symbol |
|---|---|
| Manifest + share_target | `web/web.py` → `web_manifest` |
| Service worker (shell + offline queue) | `web/web.py` → `_SERVICE_WORKER_JS`, `service_worker` |
| Share-target receiver | `web/web.py` → `share_target_receiver` |
| Shared photo-save path | `web/web.py` → `_save_library_photo` |
| Maskable PNG icons | `web/web.py` → `_app_icon_png`, `app_icon` |
| Camera capture + downscale | `web/static/js/mobile-capture.js` |
| Offline-queue indicator | `web/static/js/offline-queue.js` |
| Install / A2HS affordance | `web/static/js/pwa-install.js` |
| Inspector bottom sheet + chips/pill CSS | `web/static/theme/theme-components.css` |

## What the tests pin

- `tests/test_pwa.py` — manifest validity, root-scoped network-first worker,
  page wiring.
- `tests/test_pwa_share_target.py` — manifest share_target, the receiver
  (multi-file, non-image skip, tenant scope, signed-out, CSRF-exempt), camera
  affordance + banner.
- `tests/test_pwa_offline_queue.py` — the worker's queue machinery (intercept,
  IndexedDB, Background Sync, idempotent drain, 202, message protocol), the
  client indicator + queue-aware handler + CSS, and a functional check that the
  workflow API is idempotent (so replay is safe).
- `tests/test_pwa_mobile_install.py` — maskable PNG icons, the install script +
  chip, and the inspector bottom sheet.

## Rules respected

- **Hosted-only (ADR-0011).** Offline tolerance is a browser cache, never a
  self-host/install product path.
- **Approval-first.** Nothing here publishes to an external channel; approved
  cards are still exported/downloaded for manual posting.
- **Deterministic where it matters.** The share-target save runs no LLM
  description parse; icon geometry is deterministic.
- **Self-hosted fonts, locked camera policy, no new CDN.**
