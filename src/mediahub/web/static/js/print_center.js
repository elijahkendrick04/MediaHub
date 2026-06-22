/* Print Center — roadmap 1.20.
 *
 * Drives the per-meet print tool: pick a card + product, run the deterministic
 * pre-flight check, then download a print-ready PDF or preview a merch mockup.
 * State-changing calls are JSON POSTs (CSRF-exempt by content-type); the
 * product/placement/colour ride the query string. No framework, no deps.
 */
(function () {
  "use strict";
  var panel = document.querySelector("[data-print-tool]");
  if (!panel) return;

  var pfTmpl = panel.dataset.preflightUrl;
  var printTmpl = panel.dataset.printUrl;
  var mockTmpl = panel.dataset.mockupUrl;

  var $ = function (id) { return document.getElementById(id); };
  var report = $("pr-report");
  var preview = $("pr-preview");

  function selectedCard() { return ($("pr-card").value || "").trim(); }
  function selectedProduct() {
    var raw = ($("pr-product").value || "").split("::");
    return { product: raw[0] || "", placement: raw[1] || "" };
  }

  function buildUrl(tmpl, extra) {
    var card = encodeURIComponent(selectedCard());
    var url = tmpl.replace("__CARD__", card);
    var p = selectedProduct();
    var q = ["product=" + encodeURIComponent(p.product),
             "placement=" + encodeURIComponent(p.placement)];
    (extra || []).forEach(function (kv) { q.push(kv); });
    return url + "?" + q.join("&");
  }

  function setBusy(msg) {
    report.innerHTML = "";
    var p = document.createElement("p");
    p.className = "muted";
    p.textContent = msg;
    report.appendChild(p);
  }

  function note(text, cls) {
    var p = document.createElement("p");
    p.className = cls || "muted";
    p.textContent = text;
    return p;
  }

  var SEV = { error: "#e5484d", warning: "#f5a524", info: "#8b8d98" };

  function renderReport(data) {
    report.innerHTML = "";
    var head = document.createElement("p");
    head.style.fontWeight = "600";
    head.textContent = data.summary || (data.passed ? "Ready for the printer." : "Checked.");
    head.style.color = data.ok ? (data.passed ? "#46a758" : "#f5a524") : "#e5484d";
    report.appendChild(head);
    (data.violations || []).forEach(function (v) {
      var box = document.createElement("div");
      box.className = "card";
      box.style.margin = "8px 0";
      box.style.borderLeft = "4px solid " + (SEV[v.severity] || "#8b8d98");
      box.style.padding = "8px 12px";
      var t = document.createElement("strong");
      t.textContent = "[" + (v.severity || "") + "] " + (v.title || "");
      box.appendChild(t);
      box.appendChild(note(v.detail || "", "muted"));
      if (v.fix) {
        var fix = note("Fix: " + v.fix, "muted");
        fix.style.fontStyle = "italic";
        box.appendChild(fix);
      }
      report.appendChild(box);
    });
    if (!(data.violations || []).length) {
      report.appendChild(note("No issues found — this design is ready to print.", "muted"));
    }
  }

  function jsonPost(url) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: "{}",
    });
  }

  function guard() {
    if (!selectedCard()) { setBusy("Pick a card first."); return false; }
    if (!selectedProduct().product) { setBusy("Pick a product first."); return false; }
    return true;
  }

  $("pr-preflight").addEventListener("click", function () {
    if (!guard()) return;
    setBusy("Running pre-flight…");
    jsonPost(buildUrl(pfTmpl))
      .then(function (r) { return r.json(); })
      .then(renderReport)
      .catch(function () { setBusy("Pre-flight failed — try again."); });
  });

  $("pr-download").addEventListener("click", function () {
    if (!guard()) return;
    setBusy("Building the print-ready PDF… (a cold render can take a minute)");
    var colour = $("pr-colour").value || "rgb";
    var extra = ["colour=" + encodeURIComponent(colour)];
    if ($("pr-force").checked) extra.push("force=1");
    jsonPost(buildUrl(printTmpl, extra)).then(function (r) {
      var ctype = r.headers.get("Content-Type") || "";
      if (ctype.indexOf("application/pdf") !== -1) {
        return r.blob().then(function (b) {
          var a = document.createElement("a");
          a.href = URL.createObjectURL(b);
          a.download = selectedProduct().product + "-" + selectedCard() + "-" + colour + ".pdf";
          document.body.appendChild(a);
          a.click();
          a.remove();
          report.innerHTML = "";
          report.appendChild(note("Downloaded the print-ready PDF.", "muted"));
        });
      }
      return r.json().then(function (data) {
        if (data && data.preflight) {
          renderReport(data.preflight);
          report.insertBefore(
            note(data.user_message || "Held back by a blocking issue.", "muted"),
            report.firstChild
          );
        } else {
          setBusy((data && data.user_message) || "Couldn't make the print file.");
        }
      });
    }).catch(function () { setBusy("Export failed — try again."); });
  });

  $("pr-mockup").addEventListener("click", function () {
    if (!guard()) return;
    preview.innerHTML = "";
    setBusy("Composing the mockup…");
    jsonPost(buildUrl(mockTmpl)).then(function (r) {
      var ctype = r.headers.get("Content-Type") || "";
      if (ctype.indexOf("image/") !== -1) {
        return r.blob().then(function (b) {
          report.innerHTML = "";
          var img = document.createElement("img");
          img.src = URL.createObjectURL(b);
          img.alt = "Product mockup preview";
          img.style.maxWidth = "420px";
          img.style.width = "100%";
          img.style.borderRadius = "12px";
          preview.innerHTML = "";
          preview.appendChild(img);
        });
      }
      return r.json().then(function (data) {
        setBusy((data && data.user_message) || "Couldn't make the mockup.");
      });
    }).catch(function () { setBusy("Mockup failed — try again."); });
  });
})();
