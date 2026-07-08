/* pwa-install.js — first-party "install / Add to Home Screen" affordance
 * (roadmap 1.22).
 *
 * On Chromium/Android we capture the `beforeinstallprompt` event and offer the
 * install on our own terms via a calm bottom-left chip. On iOS Safari (which
 * has no such event) we show a one-time "Add to Home Screen" hint instead.
 * Either way it's dismissible and the dismissal is remembered, and it never
 * shows once the app is already installed. No framework; a no-op on
 * unsupported browsers.
 */
(function () {
  "use strict";

  var DISMISS_KEY = "mh_pwa_install_dismissed";

  function dismissed() {
    try {
      return localStorage.getItem(DISMISS_KEY) === "1";
    } catch (e) {
      return false;
    }
  }
  function remember() {
    try {
      localStorage.setItem(DISMISS_KEY, "1");
    } catch (e) {}
  }
  function isStandalone() {
    return (
      (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
      window.navigator.standalone === true
    );
  }

  if (isStandalone()) return; // already installed — nothing to offer

  var chip = null;
  var deferred = null;

  function makeChip(label, onActivate) {
    if (chip) return chip;
    // I-7: two real, keyboard-focusable buttons — an install action and a
    // separate Dismiss — rather than one <button> with a mouse-only × span.
    // (A <button> can't nest a <button>, so the chip is a container.)
    chip = document.createElement("div");
    chip.id = "mh-install-chip";

    var action = document.createElement("button");
    action.type = "button";
    action.className = "mh-install-action";
    action.textContent = label;
    action.addEventListener("click", onActivate);
    chip.appendChild(action);

    var close = document.createElement("button");
    close.type = "button";
    close.className = "mh-install-x";
    close.setAttribute("aria-label", "Dismiss");
    close.textContent = "×"; // ×
    close.addEventListener("click", function (e) {
      e.stopPropagation();
      hide();
      remember();
    });
    chip.appendChild(close);

    chip.hidden = true;
    if (document.body) document.body.appendChild(chip);
    return chip;
  }

  function show() {
    if (chip) chip.hidden = false;
  }
  function hide() {
    if (chip) chip.hidden = true;
  }

  // Chromium / Android: stash the prompt, then surface it on a tap.
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferred = e;
    if (dismissed()) return;
    makeChip("Install MediaHub", function () {
      if (!deferred) return;
      deferred.prompt();
      if (deferred.userChoice) {
        deferred.userChoice.then(function () {
          hide();
          deferred = null;
        });
      } else {
        hide();
      }
    });
    show();
  });

  window.addEventListener("appinstalled", function () {
    hide();
    remember();
  });

  // iOS Safari: no install event — offer a one-time A2HS hint that just
  // dismisses on tap (the OS install gesture lives in the Share sheet).
  (function () {
    var ua = window.navigator.userAgent || "";
    var isIOS = /iphone|ipad|ipod/i.test(ua) && !window.MSStream;
    var isSafari = /safari/i.test(ua) && !/crios|fxios|edgios/i.test(ua);
    if (isIOS && isSafari && !dismissed()) {
      makeChip("Add to Home Screen — tap Share, then ‘Add to Home Screen’", function () {
        hide();
        remember();
      });
      show();
    }
  })();
})();
