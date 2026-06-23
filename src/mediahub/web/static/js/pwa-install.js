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
    chip = document.createElement("button");
    chip.type = "button";
    chip.id = "mh-install-chip";

    var text = document.createElement("span");
    text.className = "mh-install-label";
    text.textContent = label;
    chip.appendChild(text);

    var close = document.createElement("span");
    close.className = "mh-install-x";
    close.setAttribute("aria-hidden", "true");
    close.textContent = "×"; // ×
    chip.appendChild(close);

    chip.hidden = true;
    chip.addEventListener("click", function (e) {
      if (e.target === close) {
        hide();
        remember();
        return;
      }
      onActivate();
    });
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
