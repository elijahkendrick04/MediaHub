"""Mobile-parity audit tool for MediaHub.

An operator-only diagnostic surface (``/tools/mobile-parity``) that answers a
single product question: *"Is the phone experience as good as the desktop
one, on every page?"*

The whole audit runs **client-side, same-origin**. The page loads each of the
app's own GET pages into a phone-sized ``<iframe>`` (the iframe is same-origin,
so its ``contentDocument`` is fully readable from JS) and runs a battery of
mobile-readiness checks against the *rendered* DOM at that width:

  * **Horizontal overflow** — the #1 mobile sin. ``scrollWidth > innerWidth``
    means the user has to pan sideways. Offenders are named (tag + classes).
  * **Viewport meta** — ``width=device-width`` must be declared or real phones
    render the desktop layout zoomed out.
  * **Touch targets** — interactive controls smaller than the WCAG 2.5.8 (AA,
    24px) / 2.5.5 (AAA, 44px) minimums are flagged. AA is legally required
    under the European Accessibility Act (in force June 2025).
  * **Navigation reachability** — a phone needs the hamburger nav, the bottom
    tab bar, or the action dock to be present.
  * **Legible text** — body copy rendered below ~12px is flagged.
  * **Tap-zone crowding** — interactive controls whose hit areas overlap.

Each page earns a 0–100 parity score and a pass / review / fail verdict; the
tool rolls them into a site-wide score. A built-in device-preview pane lets the
operator eyeball any page at iPhone / Pixel / iPad / desktop widths side by
side with the desktop reference.

This is a *measurement* tool — it makes mobile regressions visible and
verifiable; it does not change the product CSS. The fixes it surfaces are made
in the page sources / the ``responsive_guardrails`` layer.
"""

from __future__ import annotations

import json

# Device presets the audit can run at. Widths are CSS pixels (the iframe
# element is sized to this, so the page's own media queries / container
# queries resolve exactly as they would on the real device). The first entry
# flagged ``default`` is the width the audit runs at; the others drive the
# preview pane and the optional multi-width sweep.
MOBILE_PARITY_DEVICES: list[dict] = [
    {
        "id": "iphone-se",
        "label": "iPhone SE",
        "w": 375,
        "h": 667,
        "kind": "phone",
        "default": False,
    },
    {"id": "iphone-14", "label": "iPhone 14", "w": 390, "h": 844, "kind": "phone", "default": True},
    {"id": "pixel-7", "label": "Pixel 7", "w": 412, "h": 915, "kind": "phone", "default": False},
    {
        "id": "ipad-mini",
        "label": "iPad mini",
        "w": 768,
        "h": 1024,
        "kind": "tablet",
        "default": False,
    },
    {"id": "desktop", "label": "Desktop", "w": 1280, "h": 800, "kind": "desktop", "default": False},
]


def build_mobile_parity_body(targets: list[dict]) -> str:
    """Return the HTML body for the mobile-parity audit tool.

    ``targets`` is a list of ``{"label": str, "url": str, "group": str}`` dicts
    — the in-app GET pages to audit. They are emitted as JSON for the
    client-side engine; nothing here trusts them beyond same-origin fetch.
    """
    targets_json = json.dumps(targets)
    devices_json = json.dumps(MOBILE_PARITY_DEVICES)
    return f"""
<section class="mh-hero" data-lane="" style="padding-top:var(--sp-7);padding-bottom:var(--sp-5)">
  <span class="mh-hero-eyebrow">Operator tools</span>
  <h1>Mobile <em class="editorial">parity</em> audit.</h1>
  <p class="lede">
    Every page below is loaded in a phone-sized frame and checked against the
    things that make a phone feel second-class &mdash; sideways scroll, missing
    viewport meta, tap targets too small for a thumb, unreachable navigation,
    and text rendered too small to read. Run the sweep, then open any page in
    the preview to see it at real device widths.
  </p>
</section>

<div class="mh-mp" data-mp
     data-targets='{targets_json}'
     data-devices='{devices_json}'>

  <div class="mh-mp-toolbar" role="group" aria-label="Audit controls">
    <div class="mh-mp-devicepick" role="radiogroup" aria-label="Audit width">
      <span class="mh-mp-tb-label">Audit at</span>
      <div class="mh-mp-chips" data-mp-devicechips></div>
    </div>
    <div class="mh-mp-tb-actions">
      <button type="button" class="mh-cta-primary mh-mp-run" data-mp-run>
        Run audit
      </button>
      <button type="button" class="mh-cta-secondary mh-mp-stop" data-mp-stop hidden>
        Stop
      </button>
    </div>
  </div>

  <div class="mh-mp-scorecard" data-mp-scorecard hidden>
    <div class="mh-mp-score-ring" data-mp-scorering>
      <span class="mh-mp-score-num" data-mp-scorenum>&mdash;</span>
      <span class="mh-mp-score-cap">parity</span>
    </div>
    <div class="mh-mp-score-breakdown">
      <div class="mh-mp-tally">
        <span class="mh-mp-tally-n" data-mp-tally-pass>0</span>
        <span class="mh-mp-tally-l">pass</span>
      </div>
      <div class="mh-mp-tally">
        <span class="mh-mp-tally-n mh-is-warn" data-mp-tally-warn>0</span>
        <span class="mh-mp-tally-l">review</span>
      </div>
      <div class="mh-mp-tally">
        <span class="mh-mp-tally-n mh-is-fail" data-mp-tally-fail>0</span>
        <span class="mh-mp-tally-l">fail</span>
      </div>
      <div class="mh-mp-progress" data-mp-progresswrap hidden>
        <div class="mh-mp-progress-bar"><span data-mp-progressbar></span></div>
        <span class="mh-mp-progress-txt" data-mp-progresstxt></span>
      </div>
    </div>
  </div>

  <div class="mh-mp-grid">
    <div class="mh-mp-results">
      <div class="mh-mp-results-head">
        <h2 class="mh-mp-h">Pages <span class="mh-mp-count" data-mp-count></span></h2>
        <div class="mh-mp-filter" role="group" aria-label="Filter results">
          <button type="button" data-mp-filter="all" class="is-active">All</button>
          <button type="button" data-mp-filter="fail">Fails</button>
          <button type="button" data-mp-filter="warn">Review</button>
        </div>
      </div>
      <ul class="mh-mp-list" data-mp-list aria-live="polite"></ul>
    </div>

    <aside class="mh-mp-preview" data-mp-preview>
      <div class="mh-mp-preview-head">
        <span class="mh-mp-preview-title" data-mp-preview-title>Device preview</span>
        <div class="mh-mp-chips mh-mp-chips-sm" data-mp-previewchips></div>
      </div>
      <div class="mh-mp-stage" data-mp-stage>
        <div class="mh-mp-device" data-mp-device>
          <iframe data-mp-previewframe title="Page preview" loading="lazy"
                  referrerpolicy="same-origin"></iframe>
        </div>
        <p class="mh-mp-preview-empty" data-mp-preview-empty>
          Run the audit or pick a page to preview it at real device widths.
        </p>
      </div>
    </aside>
  </div>

  <!-- Off-screen measurement frame. The audit loads each page here at the
       chosen device width and reads its rendered DOM. aria-hidden + off-canvas
       so it never reaches assistive tech or the visible layout. -->
  <iframe data-mp-auditframe title="Audit measurement frame" aria-hidden="true"
          tabindex="-1" referrerpolicy="same-origin"
          style="position:absolute;left:-99999px;top:0;border:0;visibility:hidden"></iframe>
</div>

{_MOBILE_PARITY_CSS}
{_MOBILE_PARITY_JS}
"""


_MOBILE_PARITY_CSS = """
<style>
.mh-mp { margin-top: var(--sp-5); }

.mh-mp-toolbar {
  display: flex; flex-wrap: wrap; align-items: center; gap: var(--sp-4);
  justify-content: space-between;
  padding: var(--sp-3) var(--sp-4);
  border: 1px solid var(--hairline); border-radius: 14px;
  background: var(--panel);
}
.mh-mp-devicepick { display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap; }
.mh-mp-tb-label { font: 600 12px/1 var(--font-mono, monospace); letter-spacing: .08em;
  text-transform: uppercase; color: var(--ink-muted); }
.mh-mp-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.mh-mp-chip {
  appearance: none; cursor: pointer;
  border: 1px solid var(--hairline); background: transparent; color: var(--ink-dim);
  border-radius: 999px; padding: 7px 13px; font-size: 13px; font-weight: 600;
  min-height: 36px; transition: border-color .15s, color .15s, background .15s;
}
.mh-mp-chip:hover { color: var(--ink); border-color: var(--rule); }
.mh-mp-chip.is-active { background: var(--accent); color: var(--accent-ink, #0b0b0b);
  border-color: var(--accent); }
.mh-mp-chip .mh-mp-chip-dim { opacity: .6; font-weight: 500; margin-left: 4px; }
.mh-mp-tb-actions { display: flex; gap: var(--sp-3); }

.mh-mp-scorecard {
  display: flex; align-items: center; gap: var(--sp-5);
  margin-top: var(--sp-4); padding: var(--sp-4) var(--sp-5);
  border: 1px solid var(--hairline); border-radius: 16px; background: var(--panel);
}
.mh-mp-score-ring {
  --v: 0; flex: 0 0 auto;
  width: 96px; height: 96px; border-radius: 50%;
  display: grid; place-content: center; text-align: center;
  background:
    radial-gradient(closest-side, var(--panel) 73%, transparent 74% 100%),
    conic-gradient(var(--mp-ring, var(--lane)) calc(var(--v) * 1%), var(--hairline) 0);
}
.mh-mp-score-num { font: 800 28px/1 var(--font-display, inherit); color: var(--ink); display: block; }
.mh-mp-score-cap { font: 600 10px/1 var(--font-mono, monospace); letter-spacing: .1em;
  text-transform: uppercase; color: var(--ink-muted); }
.mh-mp-score-breakdown { display: flex; align-items: center; gap: var(--sp-5); flex-wrap: wrap; }
.mh-mp-tally { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.mh-mp-tally-n { font: 800 22px/1 var(--font-display, inherit); color: var(--ink); }
.mh-mp-tally-n.mh-is-warn { color: var(--lane, #D4FF3A); }
.mh-mp-tally-n.mh-is-fail { color: #ff6b6b; }
.mh-mp-tally-l { font: 600 10px/1 var(--font-mono, monospace); letter-spacing: .08em;
  text-transform: uppercase; color: var(--ink-muted); }
.mh-mp-progress { display: flex; flex-direction: column; gap: 6px; min-width: 160px; }
.mh-mp-progress-bar { height: 6px; border-radius: 999px; background: var(--hairline); overflow: hidden; }
.mh-mp-progress-bar > span { display: block; height: 100%; width: 0; background: var(--lane); transition: width .2s; }
.mh-mp-progress-txt { font-size: 12px; color: var(--ink-muted); }

.mh-mp-grid {
  display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 0.9fr);
  gap: var(--sp-5); margin-top: var(--sp-5); align-items: start;
}
@media (max-width: 900px) { .mh-mp-grid { grid-template-columns: minmax(0, 1fr); } }

.mh-mp-results-head { display: flex; align-items: center; justify-content: space-between;
  gap: var(--sp-3); margin-bottom: var(--sp-3); flex-wrap: wrap; }
.mh-mp-h { font-size: 18px; margin: 0; }
.mh-mp-count { color: var(--ink-muted); font-weight: 500; font-size: 14px; }
.mh-mp-filter { display: flex; gap: 4px; }
.mh-mp-filter button { appearance: none; cursor: pointer; border: 1px solid var(--hairline);
  background: transparent; color: var(--ink-dim); border-radius: 8px; padding: 5px 11px;
  font-size: 12px; font-weight: 600; min-height: 32px; }
.mh-mp-filter button.is-active { background: var(--panel-2, var(--panel)); color: var(--ink);
  border-color: var(--rule); }

.mh-mp-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.mh-mp-row {
  display: grid; grid-template-columns: 10px 1fr auto; align-items: center; gap: var(--sp-3);
  padding: 12px 14px; border: 1px solid var(--hairline); border-radius: 12px;
  background: var(--panel); cursor: pointer; text-align: left; width: 100%;
  appearance: none; color: inherit; transition: border-color .15s, background .15s;
}
.mh-mp-row:hover { border-color: var(--rule); }
.mh-mp-row.is-selected { border-color: var(--accent); }
.mh-mp-row-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--hairline); }
.mh-mp-row[data-status="pass"] .mh-mp-row-dot { background: #4ade80; }
.mh-mp-row[data-status="warn"] .mh-mp-row-dot { background: var(--lane, #D4FF3A); }
.mh-mp-row[data-status="fail"] .mh-mp-row-dot { background: #ff6b6b; }
.mh-mp-row[data-status="error"] .mh-mp-row-dot { background: var(--ink-muted); }
.mh-mp-row[data-status="skip"] .mh-mp-row-dot { background: var(--ink-faint, var(--ink-muted)); opacity: .5; }
.mh-mp-row-main { min-width: 0; }
.mh-mp-row-label { font-weight: 650; font-size: 15px; color: var(--ink);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mh-mp-row-url { font: 500 12px/1.3 var(--font-mono, monospace); color: var(--ink-muted);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mh-mp-row-issues { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.mh-mp-issue { font: 600 11px/1 var(--font-mono, monospace); padding: 4px 7px; border-radius: 6px;
  background: rgba(255,107,107,0.12); color: #ff8f8f; border: 1px solid rgba(255,107,107,0.25); }
.mh-mp-issue.is-warn { background: rgba(212,255,58,0.10); color: var(--lane, #D4FF3A);
  border-color: rgba(212,255,58,0.22); }
.mh-mp-row-score { font: 800 17px/1 var(--font-display, inherit); color: var(--ink); justify-self: end; }
.mh-mp-row[data-status="error"] .mh-mp-row-score { font-size: 12px; color: var(--ink-muted); }
.mh-mp-row-detail { grid-column: 1 / -1; margin-top: 8px; padding-top: 10px;
  border-top: 1px dashed var(--hairline); font-size: 13px; color: var(--ink-dim); line-height: 1.5; }
.mh-mp-row-detail ul { margin: 6px 0 0; padding-left: 18px; }
.mh-mp-row-detail code { font-size: 12px; background: var(--panel-2, rgba(0,0,0,0.2));
  padding: 1px 5px; border-radius: 4px; }

.mh-mp-preview { position: sticky; top: 84px; }
.mh-mp-preview-head { display: flex; align-items: center; justify-content: space-between;
  gap: var(--sp-3); margin-bottom: var(--sp-3); flex-wrap: wrap; }
.mh-mp-preview-title { font-weight: 650; font-size: 14px; color: var(--ink);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mh-mp-stage { border: 1px solid var(--hairline); border-radius: 16px; background: var(--panel-2, rgba(0,0,0,0.18));
  padding: var(--sp-4); display: grid; place-items: center; min-height: 360px; overflow: auto; }
.mh-mp-device { background: #000; border-radius: 18px; padding: 8px;
  box-shadow: 0 18px 48px rgba(0,0,0,0.45); transform-origin: top center; }
.mh-mp-device iframe { display: block; border: 0; border-radius: 10px; background: var(--bg);
  width: 390px; height: 720px; }
.mh-mp-preview-empty { color: var(--ink-muted); font-size: 13px; text-align: center; max-width: 32ch; }

@media (max-width: 900px) {
  .mh-mp-preview { position: static; }
  .mh-mp-device iframe { width: 360px; }
}
</style>
"""


_MOBILE_PARITY_JS = r"""
<script>
(function(){
  var root = document.querySelector('[data-mp]');
  if (!root) return;

  var TARGETS = [];
  var DEVICES = [];
  try { TARGETS = JSON.parse(root.getAttribute('data-targets') || '[]'); } catch(e){}
  try { DEVICES = JSON.parse(root.getAttribute('data-devices') || '[]'); } catch(e){}

  var auditFrame   = root.querySelector('[data-mp-auditframe]');
  var previewFrame = root.querySelector('[data-mp-previewframe]');
  var listEl       = root.querySelector('[data-mp-list]');
  var runBtn       = root.querySelector('[data-mp-run]');
  var stopBtn      = root.querySelector('[data-mp-stop]');
  var scorecard    = root.querySelector('[data-mp-scorecard]');
  var scoreRing    = root.querySelector('[data-mp-scorering]');
  var scoreNum     = root.querySelector('[data-mp-scorenum]');
  var tallyPass    = root.querySelector('[data-mp-tally-pass]');
  var tallyWarn    = root.querySelector('[data-mp-tally-warn]');
  var tallyFail    = root.querySelector('[data-mp-tally-fail]');
  var progWrap     = root.querySelector('[data-mp-progresswrap]');
  var progBar      = root.querySelector('[data-mp-progressbar]');
  var progTxt      = root.querySelector('[data-mp-progresstxt]');
  var countEl      = root.querySelector('[data-mp-count]');
  var devChips     = root.querySelector('[data-mp-devicechips]');
  var prevChips    = root.querySelector('[data-mp-previewchips]');
  var previewTitle = root.querySelector('[data-mp-preview-title]');
  var previewEmpty = root.querySelector('[data-mp-preview-empty]');
  var deviceWrap   = root.querySelector('[data-mp-device]');

  var auditDeviceId = (DEVICES.filter(function(d){return d.default;})[0] || DEVICES[0] || {id:'iphone-14',w:390,h:844}).id;
  var previewDeviceId = auditDeviceId;
  var results = {};      // url -> result
  var selectedUrl = null;
  var filter = 'all';
  var aborted = false;
  var running = false;

  function dev(id){ for (var i=0;i<DEVICES.length;i++){ if (DEVICES[i].id===id) return DEVICES[i]; } return DEVICES[0]; }

  // ---- chips -------------------------------------------------------------
  function buildChips(container, current, onPick){
    container.innerHTML = '';
    DEVICES.forEach(function(d){
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'mh-mp-chip' + (d.id===current ? ' is-active' : '');
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-checked', d.id===current ? 'true' : 'false');
      b.innerHTML = d.label + '<span class="mh-mp-chip-dim">' + d.w + '</span>';
      b.addEventListener('click', function(){ onPick(d.id); });
      container.appendChild(b);
    });
  }
  function pickAudit(id){ auditDeviceId = id; buildChips(devChips, id, pickAudit); }
  buildChips(devChips, auditDeviceId, pickAudit);
  function pickPreview(id){ previewDeviceId = id; buildChips(prevChips, id, pickPreview); sizePreview(); if (selectedUrl) loadPreview(selectedUrl); }
  buildChips(prevChips, previewDeviceId, pickPreview);

  function sizePreview(){
    var d = dev(previewDeviceId);
    if (!previewFrame) return;
    previewFrame.style.width = d.w + 'px';
    previewFrame.style.height = Math.min(d.h, 760) + 'px';
    // Scale the device shell down if it would overflow the stage.
    var stage = root.querySelector('[data-mp-stage]');
    var avail = stage ? (stage.clientWidth - 32) : d.w;
    var scale = Math.min(1, avail / (d.w + 16));
    deviceWrap.style.transform = 'scale(' + scale.toFixed(3) + ')';
  }

  // ---- the audit engine --------------------------------------------------
  function loadIntoFrame(frame, url, w, h){
    return new Promise(function(resolve, reject){
      var done = false;
      var timer = setTimeout(function(){ if(!done){ done=true; reject(new Error('timeout')); } }, 15000);
      frame.style.width = w + 'px';
      frame.style.height = h + 'px';
      frame.onload = function(){
        if (done) return; done = true; clearTimeout(timer);
        // Let layout, fonts and any deferred scripts settle before measuring.
        setTimeout(function(){ resolve(); }, 450);
      };
      try { frame.src = url; } catch(e){ clearTimeout(timer); reject(e); }
    });
  }

  function isInteractive(el){
    if (el.matches('a[href], button, select, textarea, [role="button"], [role="link"], [role="tab"], [role="menuitem"], summary')) return true;
    if (el.tagName === 'INPUT' && el.type !== 'hidden') return true;
    return false;
  }

  function describe(el){
    var s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    else if (el.className && typeof el.className === 'string') {
      var c = el.className.trim().split(/\s+/).slice(0,2).join('.');
      if (c) s += '.' + c;
    }
    return s;
  }

  function audit(doc, win){
    // Some auto-discovered routes are JSON probes / non-HTML responses the
    // browser renders in a bare <pre> (e.g. the deep-health endpoint). They
    // have no viewport or nav by design, so scoring them as "fails" would be
    // noise — skip them and leave them out of the site score.
    if (doc.contentType && doc.contentType.toLowerCase().indexOf('html') === -1) {
      return {score:null, status:'skip', issues:[]};
    }
    var de = doc.documentElement;
    var vw = win.innerWidth;
    var issues = [];   // {sev:'fail'|'warn', code, label, detail}
    var deductions = 0;

    // 1) Horizontal overflow.
    var scrollW = Math.max(de.scrollWidth, doc.body ? doc.body.scrollWidth : 0);
    if (scrollW > vw + 2) {
      var offenders = [];
      var all = doc.body ? doc.body.querySelectorAll('*') : [];
      for (var i=0; i<all.length && offenders.length<6; i++){
        var r = all[i].getBoundingClientRect();
        if (r.width > 0 && r.right > vw + 2 && r.left >= -2) {
          // only report elements that themselves exceed the viewport width
          if (r.width > vw - 4) offenders.push(describe(all[i]) + ' (' + Math.round(r.width) + 'px)');
        }
      }
      deductions += 42;
      issues.push({sev:'fail', code:'overflow', label:'sideways scroll +' + Math.round(scrollW - vw) + 'px',
        detail: offenders.length ? ('Widest elements: ' + offenders.join(', ')) : 'Content is wider than the viewport.'});
    }

    // 2) Viewport meta.
    var vm = doc.querySelector('meta[name="viewport"]');
    if (!vm || !/width\s*=\s*device-width/i.test(vm.getAttribute('content') || '')) {
      deductions += 25;
      issues.push({sev:'fail', code:'no-viewport', label:'no viewport meta',
        detail:'Missing &lt;meta name="viewport" content="width=device-width"&gt; — real phones render the desktop layout zoomed out.'});
    }

    // 3) Touch targets.
    var inter = [];
    var cand = doc.querySelectorAll('a[href], button, select, textarea, input, [role="button"], [role="link"], [role="tab"], [role="menuitem"], summary');
    var tooSmall = 0, snug = 0, smallEx = [];
    for (var j=0;j<cand.length;j++){
      var el = cand[j];
      if (!isInteractive(el)) continue;
      var rc = el.getBoundingClientRect();
      var cs = win.getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || rc.width === 0 || rc.height === 0) continue;
      // WCAG 2.5.8 "inline" exception: a link flowing inside a sentence is
      // sized by the surrounding line-height, not by the author, so it's
      // exempt from the target-size minimum. Skip true inline text links so
      // legal / prose pages aren't penalised for something that isn't a bug.
      if (el.tagName === 'A' && cs.display.indexOf('inline') === 0 && cs.display !== 'inline-block' && cs.display !== 'inline-flex' && cs.display !== 'inline-grid') continue;
      inter.push({el:el, r:rc});
      var min = Math.min(rc.width, rc.height);
      if (min < 24) { tooSmall++; if (smallEx.length<5) smallEx.push(describe(el) + ' (' + Math.round(rc.width) + '×' + Math.round(rc.height) + ')'); }
      else if (min < 44) { snug++; }
    }
    if (tooSmall > 0) {
      deductions += Math.min(24, 6 + tooSmall * 3);
      issues.push({sev:'fail', code:'touch', label:tooSmall + ' tap target' + (tooSmall>1?'s':'') + ' < 24px',
        detail:'Below the WCAG 2.5.8 (AA) minimum. ' + smallEx.join(', ')});
    } else if (snug > 2) {
      deductions += 6;
      issues.push({sev:'warn', code:'touch-snug', label:snug + ' tap targets < 44px',
        detail:'Below the comfortable AAA 44px target; usable but tight for thumbs.'});
    }

    // 4) Navigation reachability.
    var hasNav = doc.querySelector('.mh-nav-toggle, .mh-bottomnav, .mh-action-dock');
    if (!hasNav) {
      deductions += 14;
      issues.push({sev:'warn', code:'nav', label:'no mobile nav',
        detail:'No hamburger toggle, bottom tab bar, or action dock found — navigation may be hard to reach on a phone.'});
    }

    // 5) Tiny text.
    var tiny = 0, tinyEx = [];
    var textEls = doc.querySelectorAll('p, li, td, th, span, a, label, dd, dt, small, figcaption');
    for (var k=0;k<textEls.length;k++){
      var t = textEls[k];
      if (!t.textContent || !t.textContent.trim()) continue;
      var fs = parseFloat(win.getComputedStyle(t).fontSize || '16');
      var rr = t.getBoundingClientRect();
      if (rr.width === 0 || rr.height === 0) continue;
      if (fs && fs < 12) { tiny++; if (tinyEx.length<4) tinyEx.push(describe(t) + ' (' + fs.toFixed(0) + 'px)'); }
    }
    if (tiny > 3) {
      deductions += 8;
      issues.push({sev:'warn', code:'tiny-text', label:tiny + ' text runs < 12px',
        detail:'Text this small is hard to read on a phone without zooming. ' + tinyEx.join(', ')});
    }

    // 6) Tap-zone crowding — interactive hit areas that overlap.
    var overlaps = 0;
    for (var a=0;a<inter.length;a++){
      for (var b=a+1;b<inter.length;b++){
        var A = inter[a].r, B = inter[b].r;
        if (inter[a].el.contains(inter[b].el) || inter[b].el.contains(inter[a].el)) continue;
        var ox = Math.max(0, Math.min(A.right,B.right) - Math.max(A.left,B.left));
        var oy = Math.max(0, Math.min(A.bottom,B.bottom) - Math.max(A.top,B.top));
        if (ox > 4 && oy > 4) overlaps++;
      }
      if (overlaps > 30) break;
    }
    if (overlaps > 4) {
      deductions += 6;
      issues.push({sev:'warn', code:'crowding', label:'crowded tap zones',
        detail: overlaps + ' overlapping interactive hit areas — taps may land on the wrong control.'});
    }

    var score = Math.max(0, 100 - deductions);
    var status = 'pass';
    var hasFail = issues.some(function(i){return i.sev==='fail';});
    if (hasFail || score < 60) status = 'fail';
    else if (issues.length > 0 || score < 88) status = 'warn';
    return {score:score, status:status, issues:issues};
  }

  // ---- rendering ---------------------------------------------------------
  function statusOrder(s){ return s==='fail'?0 : s==='warn'?1 : s==='pass'?2 : s==='error'?3 : 4; }

  function renderList(){
    listEl.innerHTML = '';
    var items = TARGETS.slice();
    var shown = 0;
    items.sort(function(x,y){
      var rx = results[x.url], ry = results[y.url];
      if (rx && ry) return statusOrder(rx.status) - statusOrder(ry.status);
      if (rx) return -1; if (ry) return 1; return 0;
    });
    items.forEach(function(t){
      var res = results[t.url];
      if (filter !== 'all') {
        if (!res || res.status !== filter) return;
      }
      shown++;
      var li = document.createElement('li');
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'mh-mp-row' + (selectedUrl===t.url ? ' is-selected' : '');
      btn.setAttribute('data-status', res ? res.status : 'pending');
      var issuesHtml = '';
      if (res && res.issues && res.issues.length) {
        issuesHtml = '<div class="mh-mp-row-issues">' + res.issues.map(function(is){
          return '<span class="mh-mp-issue' + (is.sev==='warn'?' is-warn':'') + '">' + is.label + '</span>';
        }).join('') + '</div>';
      }
      var detailHtml = '';
      if (selectedUrl===t.url && res && res.issues && res.issues.length) {
        detailHtml = '<div class="mh-mp-row-detail"><ul>' + res.issues.map(function(is){
          return '<li>' + is.detail + '</li>';
        }).join('') + '</ul></div>';
      } else if (selectedUrl===t.url && res && res.status==='pass') {
        detailHtml = '<div class="mh-mp-row-detail">No mobile-parity issues found at this width.</div>';
      } else if (selectedUrl===t.url && res && res.status==='error') {
        detailHtml = '<div class="mh-mp-row-detail">Could not load this page for audit (' + (res.error||'error') + ').</div>';
      } else if (selectedUrl===t.url && res && res.status==='skip') {
        detailHtml = '<div class="mh-mp-row-detail">Not an HTML page (JSON / probe response) &mdash; skipped, not scored.</div>';
      }
      var scoreTxt = res ? (res.status==='error' ? 'n/a' : res.status==='skip' ? 'skip' : res.score) : '&middot;';
      btn.innerHTML =
        '<span class="mh-mp-row-dot" aria-hidden="true"></span>' +
        '<span class="mh-mp-row-main">' +
          '<span class="mh-mp-row-label">' + t.label + '</span>' +
          '<span class="mh-mp-row-url">' + t.url + '</span>' +
          issuesHtml +
        '</span>' +
        '<span class="mh-mp-row-score">' + scoreTxt + '</span>' +
        detailHtml;
      btn.addEventListener('click', function(){
        selectedUrl = (selectedUrl===t.url) ? null : t.url;
        if (selectedUrl) loadPreview(t.url, t.label);
        renderList();
      });
      li.appendChild(btn);
      listEl.appendChild(li);
    });
    countEl.textContent = shown + ' / ' + TARGETS.length;
  }

  function loadPreview(url, label){
    if (previewEmpty) previewEmpty.style.display = 'none';
    if (previewFrame) {
      sizePreview();
      previewFrame.style.display = 'block';
      previewFrame.src = url;
    }
    if (previewTitle && label) previewTitle.textContent = label;
  }

  var RING_COLORS = {good:'#4ade80', mid:'var(--lane, #D4FF3A)', bad:'#ff6b6b'};
  function paintScore(){
    var done = TARGETS.map(function(t){return results[t.url];}).filter(Boolean);
    var pass=0, warn=0, fail=0, sum=0, n=0;
    done.forEach(function(r){
      if (r.status==='error' || r.status==='skip') return;
      n++; sum += r.score;
      if (r.status==='pass') pass++; else if (r.status==='warn') warn++; else fail++;
    });
    var avg = n ? Math.round(sum/n) : 0;
    tallyPass.textContent = pass; tallyWarn.textContent = warn; tallyFail.textContent = fail;
    scoreNum.innerHTML = n ? avg : '&mdash;';
    scoreRing.style.setProperty('--v', avg);
    scoreRing.style.setProperty('--mp-ring', avg>=88?RING_COLORS.good : avg>=60?RING_COLORS.mid : RING_COLORS.bad);
  }

  // ---- run loop ----------------------------------------------------------
  function runAudit(){
    if (running) return;
    running = true; aborted = false;
    results = {};
    scorecard.hidden = false;
    progWrap.hidden = false;
    runBtn.hidden = true; stopBtn.hidden = false;
    var d = dev(auditDeviceId);
    var i = 0;
    renderList();

    function step(){
      if (aborted || i >= TARGETS.length) { finish(); return; }
      var t = TARGETS[i];
      progBar.style.width = Math.round((i/TARGETS.length)*100) + '%';
      progTxt.textContent = 'Auditing ' + (i+1) + ' of ' + TARGETS.length + ' — ' + t.label;
      loadIntoFrame(auditFrame, t.url, d.w, d.h).then(function(){
        try {
          var doc = auditFrame.contentDocument;
          var win = auditFrame.contentWindow;
          if (!doc || !win) throw new Error('no document');
          results[t.url] = audit(doc, win);
        } catch (err) {
          results[t.url] = {score:0, status:'error', issues:[], error:(err && err.message) || 'blocked'};
        }
        i++; paintScore(); renderList(); step();
      }).catch(function(err){
        results[t.url] = {score:0, status:'error', issues:[], error:(err && err.message) || 'load failed'};
        i++; paintScore(); renderList(); step();
      });
    }
    step();
  }

  function finish(){
    running = false;
    progBar.style.width = '100%';
    progTxt.textContent = aborted ? 'Stopped.' : 'Done — ' + Object.keys(results).length + ' pages audited.';
    setTimeout(function(){ progWrap.hidden = true; }, 1600);
    runBtn.hidden = false; stopBtn.hidden = true;
    paintScore(); renderList();
  }

  runBtn.addEventListener('click', runAudit);
  stopBtn.addEventListener('click', function(){ aborted = true; });

  root.querySelectorAll('[data-mp-filter]').forEach(function(b){
    b.addEventListener('click', function(){
      filter = b.getAttribute('data-mp-filter');
      root.querySelectorAll('[data-mp-filter]').forEach(function(x){ x.classList.toggle('is-active', x===b); });
      renderList();
    });
  });

  window.addEventListener('resize', function(){ if (selectedUrl) sizePreview(); });

  // initial paint
  sizePreview();
  renderList();
})();
</script>
"""


__all__ = ["build_mobile_parity_body", "MOBILE_PARITY_DEVICES"]
