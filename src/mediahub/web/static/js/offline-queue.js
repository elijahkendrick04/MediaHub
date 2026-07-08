/* offline-queue.js — surfaces the PWA offline approval queue (roadmap 1.22).
 *
 * The heavy lifting (intercept, persist, replay) lives in the service worker.
 * This script is the thin client side: it keeps a small status pill in sync
 * with the queue length the SW reports, drains on load when we're online
 * (D-5 — iOS Safari has no Background Sync), offers a manual "Sync now", and
 * surfaces approvals the server refused or held on replay instead of a false
 * "All changes synced" (D-4). No framework; a no-op where service workers are
 * absent.
 */
(function () {
  "use strict";

  if (!("serviceWorker" in navigator)) return;

  var indicator = null;

  function ensureIndicator() {
    if (indicator) return indicator;
    indicator = document.createElement("div");
    indicator.id = "mh-offline-queue";
    indicator.setAttribute("role", "status");
    indicator.setAttribute("aria-live", "polite");
    indicator.hidden = true;
    if (document.body) document.body.appendChild(indicator);
    return indicator;
  }

  function ping(type) {
    if (navigator.serviceWorker.controller) {
      navigator.serviceWorker.controller.postMessage({ type: type });
    }
  }

  // A tappable manual drain for when the volunteer is back online but the queue
  // hasn't flushed — the only path on iOS Safari, which has no Background Sync.
  function syncNowButton() {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "mh-oq-sync";
    b.textContent = "Sync now";
    b.addEventListener("click", function () {
      ping("mediahub-queue-replay");
      setTimeout(function () {
        ping("mediahub-queue-status");
      }, 800);
    });
    return b;
  }

  // A Dismiss for the persistent "review needed" state — the only way to clear
  // it, so a follow-up status ping can't erase a lost-approval notice.
  function dismissButton() {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "mh-oq-sync";
    b.textContent = "Dismiss";
    b.addEventListener("click", function () {
      problems = [];
      render(lastCount);
    });
    return b;
  }

  // Text is server-echoed on the problem path; build via textContent, never
  // innerHTML.
  function setPill(el, text, state) {
    el.textContent = "";
    var span = document.createElement("span");
    span.textContent = text;
    el.appendChild(span);
    el.dataset.state = state;
    el.hidden = false;
  }

  // Problems (approvals the server refused or held) only arrive on a drain and
  // are the highest-priority thing to surface. They are PERSISTED here — not
  // passed per-render — so a follow-up mediahub-queue-status ping (count only)
  // can't erase the notice (D-4), and shown ahead of the sync-pending count so
  // a still-queued transient item can't hide them.
  var problems = [];
  var lastCount = 0;

  function render(count) {
    var el = ensureIndicator();
    if (!el) return;
    lastCount = count || 0;
    if (problems.length) {
      var n = problems.length;
      setPill(
        el,
        n +
          (n === 1 ? " approval couldn't be saved" : " approvals couldn't be saved") +
          " (consent, brand, or another approver) — review needed",
        "problem"
      );
      // Persistent until dismissed; still offer a drain if items remain queued.
      if (lastCount > 0 && navigator.onLine) el.appendChild(syncNowButton());
      el.appendChild(dismissButton());
    } else if (lastCount > 0) {
      setPill(
        el,
        lastCount +
          (lastCount === 1 ? " change waiting to sync" : " changes waiting to sync"),
        "pending"
      );
      // Offer a manual drain when we're online — essential on iOS.
      if (navigator.onLine) el.appendChild(syncNowButton());
    } else if (el.dataset.state === "pending") {
      // A genuine, clean drain.
      setPill(el, "All changes synced", "synced");
      setTimeout(function () {
        if (el.dataset.state === "synced") el.hidden = true;
      }, 2500);
    } else {
      el.hidden = true;
    }
  }

  navigator.serviceWorker.addEventListener("message", function (e) {
    var d = e.data || {};
    if (d.type !== "mediahub-queue") return;
    // Accumulate problems across drains; a plain status ping carries none and
    // must not clear a standing notice.
    if (d.problems && d.problems.length) problems = problems.concat(d.problems);
    render(d.count || 0);
  });

  // On load, drain immediately when we're online (D-5): iOS Safari never fires
  // Background Sync, so an app reopened while already online would otherwise
  // strand queued approvals until the connection happens to drop and return.
  // Then ask for the current count.
  navigator.serviceWorker.ready
    .then(function () {
      if (navigator.onLine) ping("mediahub-queue-replay");
      ping("mediahub-queue-status");
    })
    .catch(function () {});

  // Back online: nudge a replay (Background Sync covers Chrome/Android; this is
  // the fallback for iOS Safari and friends) and refresh the count after.
  window.addEventListener("online", function () {
    ping("mediahub-queue-replay");
    setTimeout(function () {
      ping("mediahub-queue-status");
    }, 1500);
  });
})();
