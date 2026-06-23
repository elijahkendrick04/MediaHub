/* mobile-capture.js — phone-first camera capture + on-device downscale for the
 * media library (roadmap 1.22, Mobile PWA).
 *
 * Progressive enhancement over the plain upload <form>: with no JS the form
 * posts a multipart upload exactly as before. With JS we (a) expose a "Take
 * photo" button that opens the device camera via a hidden <input capture>, and
 * (b) downscale large photos in a <canvas> before upload so a poolside
 * volunteer on a slow connection isn't sending a 12-megapixel original. Any
 * failure falls back to a native form submit so the upload always goes through.
 *
 * No framework — plain fetch + DOM, matching the rest of the app.
 */
(function () {
  "use strict";

  var form = document.querySelector("[data-mh-capture-form]");
  if (!form) return;

  var MAX_DIM = 2048; // longest edge after downscale (plenty for any card render)
  var JPEG_Q = 0.85;
  var DOWNSCALE_MIN_BYTES = 1.5 * 1024 * 1024; // only bother downscaling big files

  var fileInput = form.querySelector('input[type=file][name=file]');
  var captureInput = document.getElementById("ml-capture");
  var captureBtn = document.getElementById("ml-capture-btn");
  var statusEl = document.getElementById("ml-capture-status");
  var endpoint = form.getAttribute("action");

  function token() {
    var el = form.querySelector('input[name=csrf_token]');
    return el ? el.value : "";
  }

  function field(name, fallback) {
    var el = form.querySelector("[name=" + name + "]");
    return el && el.value ? el.value : fallback || "";
  }

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg || "";
  }

  function canDownscale() {
    try {
      return !!(
        window.createImageBitmap &&
        document.createElement("canvas").getContext &&
        document.createElement("canvas").toBlob
      );
    } catch (e) {
      return false;
    }
  }

  // Returns Promise<Blob|File>. If the image is already small enough (or
  // anything goes wrong) it resolves with the original file untouched.
  function downscale(file) {
    return createImageBitmap(file).then(function (bmp) {
      var w = bmp.width,
        h = bmp.height;
      var scale = Math.min(1, MAX_DIM / Math.max(w, h));
      if (scale >= 1) {
        if (bmp.close) bmp.close();
        return file;
      }
      var cw = Math.round(w * scale),
        ch = Math.round(h * scale);
      var canvas = document.createElement("canvas");
      canvas.width = cw;
      canvas.height = ch;
      var ctx = canvas.getContext("2d");
      ctx.drawImage(bmp, 0, 0, cw, ch);
      if (bmp.close) bmp.close();
      return new Promise(function (resolve) {
        canvas.toBlob(
          function (blob) {
            resolve(blob || file);
          },
          "image/jpeg",
          JPEG_Q
        );
      });
    });
  }

  function uploadBlob(blob, filename) {
    var fd = new FormData();
    fd.append("file", blob, filename || "photo.jpg");
    fd.append("profile_id", field("profile_id"));
    var descr = field("description");
    if (descr) fd.append("description", descr);
    fd.append("asset_type", field("asset_type", "athlete_photo"));
    var t = token();
    if (t) fd.append("csrf_token", t);
    return fetch(endpoint, {
      method: "POST",
      body: fd,
      headers: { "X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": t },
      credentials: "same-origin",
    }).then(function (r) {
      return r.ok ? r.json() : Promise.reject(r);
    });
  }

  function nativeFallback() {
    setStatus("");
    try {
      form.submit();
    } catch (e) {
      /* nothing more we can do */
    }
  }

  function processAndUpload(file) {
    if (!file) return;
    setStatus("Preparing photo…");
    var prep =
      canDownscale() && file.size > DOWNSCALE_MIN_BYTES
        ? downscale(file).catch(function () {
            return file;
          })
        : Promise.resolve(file);
    prep
      .then(function (blob) {
        setStatus("Uploading…");
        var fname = (file.name || "photo.jpg").replace(/\.(heic|heif)$/i, ".jpg");
        return uploadBlob(blob, fname);
      })
      .then(function () {
        setStatus("Added to your library.");
        var base = window.location.pathname;
        window.location.assign(base + "?shared=1");
      })
      .catch(function () {
        // The AJAX/downscale path failed — fall back to a plain form submit so
        // the photo still reaches the library.
        nativeFallback();
      });
  }

  // (1) Intercept the main upload form to downscale before sending. Only when
  //     a file is actually chosen and the browser can downscale; otherwise let
  //     the native multipart submit run untouched.
  form.addEventListener("submit", function (ev) {
    if (!fileInput || !fileInput.files || !fileInput.files.length) return;
    if (!canDownscale()) return;
    ev.preventDefault();
    processAndUpload(fileInput.files[0]);
  });

  // (2) Camera capture affordance. The button is only revealed when this script
  //     ran, so a no-JS page never shows a dead control. On a phone the hidden
  //     <input capture> opens the camera; on desktop it's a normal file picker.
  if (captureInput && captureBtn) {
    captureBtn.hidden = false;
    captureBtn.addEventListener("click", function () {
      captureInput.click();
    });
    captureInput.addEventListener("change", function () {
      if (captureInput.files && captureInput.files.length) {
        processAndUpload(captureInput.files[0]);
      }
    });
  }
})();
