/* bulk_export.js — drives the Export Center bulk-export tool (roadmap 1.19).
 *
 * Reads its endpoints from the panel's data-* attributes, kicks the background
 * job, polls progress, then surfaces a download button and a "create share
 * link" action. No framework — plain fetch + DOM, matching the rest of the app.
 */
(function () {
  "use strict";
  var panel = document.querySelector("[data-bulk-export]");
  if (!panel) return;

  var startBtn = document.getElementById("bx-start");
  var statusEl = document.getElementById("bx-status");
  var resultEl = document.getElementById("bx-result");
  var qualityEl = document.getElementById("bx-quality");
  var qualityOut = document.getElementById("bx-quality-out");
  var kickUrl = panel.getAttribute("data-kick-url");
  var shareUrl = panel.getAttribute("data-share-url");
  var lastJobId = "";

  // F-11 — a live readout beside the quality slider so the user can see the
  // value they picked (was a bare range input with no output).
  if (qualityEl && qualityOut) {
    var syncQuality = function () { qualityOut.textContent = qualityEl.value; };
    qualityEl.addEventListener("input", syncQuality);
    syncQuality();
  }

  function chosenFormats() {
    return Array.prototype.slice
      .call(panel.querySelectorAll('input[name="fmt"]:checked'))
      .map(function (el) { return el.value; });
  }

  function setStatus(text) { statusEl.textContent = text || ""; }

  // A transient network blip must not abandon a still-running server job (the
  // user's retry would kick a brand-new job): retry the status poll a few
  // times with backoff before declaring the job lost.
  var POLL_MAX_RETRIES = 3;
  var pollRetries = 0;

  function poll(pollUrl) {
    fetch(pollUrl, { headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        pollRetries = 0; // any successful poll resets the retry budget
        if (j.status === "running") {
          setStatus("Exporting… " + (j.done || 0) + " / " + (j.total || "?"));
          setTimeout(function () { poll(pollUrl); }, 1200);
          return;
        }
        startBtn.disabled = false;
        if (j.status === "done") {
          var note = j.error_count
            ? " (" + j.error_count + " item/format combos were skipped — see the manifest)"
            : "";
          setStatus("Done — " + j.file_count + " files" + note);
          renderResult(j.file_url);
        } else {
          setStatus("Export failed: " + (j.error || "unknown error"));
        }
      })
      .catch(function () {
        if (pollRetries < POLL_MAX_RETRIES) {
          pollRetries += 1;
          var delay = 1000 * Math.pow(2, pollRetries); // 2s / 4s / 8s
          setStatus("Connection hiccup — retrying… (" + pollRetries + "/" + POLL_MAX_RETRIES + ")");
          setTimeout(function () { poll(pollUrl); }, delay);
          return;
        }
        startBtn.disabled = false;
        setStatus("Lost contact with the export job — try again.");
      });
  }

  function renderResult(fileUrl) {
    resultEl.innerHTML = "";
    var dl = document.createElement("a");
    dl.href = fileUrl;
    dl.className = "btn";
    dl.textContent = "Download ZIP";
    dl.setAttribute("download", "");
    resultEl.appendChild(dl);

    var shareBtn = document.createElement("button");
    shareBtn.className = "btn ghost";
    shareBtn.style.marginLeft = "8px";
    shareBtn.textContent = "Create share link";
    shareBtn.onclick = function () {
      shareBtn.disabled = true;
      fetch(shareUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job: lastJobId }),
      })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          shareBtn.disabled = false;
          if (!j.ok) { setStatus("Could not create a share link."); return; }
          // E-5: the link used to render as a bare readonly input — no copy
          // affordance and no sign that it expires (the API always said when).
          var wrap = document.createElement("div");
          wrap.style.cssText =
            "display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px;max-width:640px";
          var inp = document.createElement("input");
          inp.type = "text";
          inp.readOnly = true;
          inp.value = window.location.origin + j.url;
          inp.style.cssText = "flex:1;min-width:220px";
          inp.onclick = function () { inp.select(); };
          var cp = document.createElement("button");
          cp.className = "btn secondary";
          cp.textContent = "Copy";
          cp.onclick = function () {
            var done = function (ok) {
              cp.textContent = ok ? "Copied!" : "Copy failed";
              setTimeout(function () { cp.textContent = "Copy"; }, 1600);
            };
            var legacy = function () {
              inp.focus(); inp.select();
              try { done(document.execCommand("copy")); } catch (e) { done(false); }
            };
            if (navigator.clipboard && window.isSecureContext) {
              navigator.clipboard.writeText(inp.value).then(function () { done(true); }).catch(legacy);
            } else { legacy(); }
          };
          var exp = document.createElement("span");
          exp.className = "muted";
          exp.style.fontSize = "12px";
          if (j.expires_at) {
            exp.textContent = "expires " + new Date(j.expires_at * 1000).toLocaleDateString();
          }
          exp.title = "Revoke it any time from a card's Share panel on the Content builder.";
          wrap.appendChild(inp);
          wrap.appendChild(cp);
          wrap.appendChild(exp);
          resultEl.appendChild(wrap);
        })
        .catch(function () { shareBtn.disabled = false; setStatus("Share link failed."); });
    };
    resultEl.appendChild(shareBtn);
  }

  startBtn.addEventListener("click", function () {
    var formats = chosenFormats();
    if (!formats.length) { setStatus("Pick at least one format."); return; }
    startBtn.disabled = true;
    resultEl.innerHTML = "";
    pollRetries = 0;
    setStatus("Starting…");
    fetch(kickUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        formats: formats,
        options: { quality: parseInt(qualityEl.value, 10) || 90 },
      }),
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok || !res.j.ok) {
          startBtn.disabled = false;
          setStatus(res.j.message || res.j.error || "Could not start the export.");
          return;
        }
        lastJobId = res.j.job_id;
        poll(res.j.poll_url);
      })
      .catch(function () {
        startBtn.disabled = false;
        setStatus("Could not start the export.");
      });
  });
})();
