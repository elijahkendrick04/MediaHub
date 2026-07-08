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

  function render(count, problems) {
    var el = ensureIndicator();
    if (!el) return;
    problems = problems || [];
    if (count > 0) {
      setPill(
        el,
        count + (count === 1 ? " change waiting to sync" : " changes waiting to sync"),
        "pending"
      );
      // Offer a manual drain when we're online — essential on iOS.
      if (navigator.onLine) el.appendChild(syncNowButton());
    } else if (problems.length) {
      // The queue drained but the server refused or held some approvals — say so
      // honestly rather than flashing a clean "synced" over a lost approval (D-4).
      var n = problems.length;
      setPill(
        el,
        n +
          (n === 1 ? " approval couldn't be saved" : " approvals couldn't be saved") +
          " (consent, brand, or another approver) — review needed",
        "problem"
      );
      // No auto-hide — the volunteer must see and act on this.
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
    if (d.type === "mediahub-queue") render(d.count || 0, d.problems || []);
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
