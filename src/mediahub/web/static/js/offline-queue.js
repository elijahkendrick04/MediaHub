/* offline-queue.js — surfaces the PWA offline approval queue (roadmap 1.22).
 *
 * The heavy lifting (intercept, persist, replay) lives in the service worker.
 * This script is the thin client side: it keeps a small status pill in sync
 * with the queue length the SW reports, and — for browsers without Background
 * Sync (notably iOS Safari) — nudges the SW to replay the moment the device
 * comes back online. No framework; a no-op where service workers are absent.
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

  function render(count) {
    var el = ensureIndicator();
    if (!el) return;
    if (count > 0) {
      el.textContent =
        count + (count === 1 ? " change waiting to sync" : " changes waiting to sync");
      el.dataset.state = "pending";
      el.hidden = false;
    } else if (el.dataset.state === "pending") {
      // The queue just drained — flash a brief confirmation, then hide.
      el.textContent = "All changes synced";
      el.dataset.state = "synced";
      el.hidden = false;
      setTimeout(function () {
        if (el.dataset.state === "synced") el.hidden = true;
      }, 2500);
    } else {
      el.hidden = true;
    }
  }

  navigator.serviceWorker.addEventListener("message", function (e) {
    var d = e.data || {};
    if (d.type === "mediahub-queue") render(d.count || 0);
  });

  function ping(type) {
    if (navigator.serviceWorker.controller) {
      navigator.serviceWorker.controller.postMessage({ type: type });
    }
  }

  // Ask for the current queue on load (covers a reload that still has pending
  // items the SW hasn't been able to flush yet).
  navigator.serviceWorker.ready
    .then(function () {
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
