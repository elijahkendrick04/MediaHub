"""Roadmap 1.2 — the generative-imagery **studio** (mask-brush + edit family).

The hands-on surface in front of the ``media_ai.imagine`` seam. The seam, its
providers (the in-house local diffusion default + optional Gemini/Imagen), the
whole edit family (``edit`` / ``fill`` / ``remove`` / ``expand`` / ``upscale`` /
``style_match`` / ``similar``), per-org quota and provenance stamping are all
shipped and unit-tested; the JSON routes that drive them live in ``web.py``
(``/api/media-library/<asset_id>/imagine/<op>`` — they already accept a brushed
``mask_b64``). What was *still open as 1.2* (see
``docs/CREATIVE_SUITE_PARITY.md``) is this **studio UI**: a place a volunteer can
paint a mask over a photo and run Fill / Remove, expand a too-tight crop to a
story canvas, upscale a low-res phone shot, restyle to the club look, lift a
subject, or grab text — without touching an API.

Like ``design_editor`` this module is **pure / Flask-free** so it unit-tests
without a request: the route in ``web.py`` resolves every ``url_for(...)`` link,
measures the asset, and passes them in; all capability/quota state is fetched at
runtime from ``/api/media-library/imagine/info`` so the studio can only ever
offer operations the *active* provider actually supports (honest errors, never a
fake button). The brush, the canvas maths and the op wiring are plain vanilla JS
in :data:`_STUDIO_JS`; the config blob is JSON-embedded the same safe way the
design studio does it.

Standing rules honoured here: every produced image is a new provenance-stamped
``MediaAsset`` (the route stamps it), people are off by default, results are
review-gated (they land as ``draft`` in the library, never auto-published), and
nothing here fabricates *results data* — generative pixels are scenery, not
facts.
"""

from __future__ import annotations

import json

from markupsafe import escape

# The curated, provider-agnostic style vocabulary the seam shares across
# backends — imported so the studio's "Restyle" picker can never drift from
# what the providers actually understand.
from mediahub.media_ai.imagine_providers.styles import DEFAULT_STYLE, STYLE_PRESETS

# Sentinels the route fills with a concrete ``url_for`` and the JS rewrites per
# operation / per result asset. Kept deliberately unmistakable so a hex asset id
# can never collide with them.
OP_SENTINEL = "__IMAGINE_OP__"
ASSET_SENTINEL = "__IMAGINE_ASSET__"

# Target canvases the "Expand" outpaint offers. Mirrors the generate-panel
# aspect list plus the editorial 4:5 portrait the cards use.
ASPECT_CHOICES: tuple[tuple[str, str], ...] = (
    ("1:1", "Square · 1:1"),
    ("4:5", "Portrait · 4:5"),
    ("3:4", "Portrait · 3:4"),
    ("9:16", "Story · 9:16"),
    ("16:9", "Landscape · 16:9"),
)

# Upscale factors the print pipeline (1.20) leans on.
UPSCALE_FACTORS: tuple[tuple[int, str], ...] = (
    (2, "2× — sharper for screen"),
    (4, "4× — print resolution"),
)

# The studio tool panels, in display order. Each tuple is
# ``(op, title, blurb, needs_mask)``. ``op`` matches the seam's operation name
# (the value the route's ``available_operations()`` advertises), so a panel is
# shown enabled only when that op is live on the active provider. ``needs_mask``
# panels activate the brush. ``subject_lift`` and ``grab_text`` are the
# deterministic / vision ops (key-free / vision-gated, not image-provider ops).
TOOL_PANELS: tuple[tuple[str, str, str, bool], ...] = (
    ("edit", "Fill / replace", "Paint over a region, then say what should go there.", True),
    ("remove", "Erase object", "Paint over what to remove — the hole is filled in.", True),
    ("expand", "Expand canvas", "Extend the photo to a new shape with generated fill.", False),
    ("upscale", "Upscale", "Raise resolution on a low-res phone shot before print.", False),
    ("style_match", "Restyle", "Re-style the photo toward a club editorial look.", False),
    ("similar", "Variations", "Make on-style variations of this image.", False),
    (
        "subject_lift",
        "Lift subject",
        "Cut the subject out (background removed) — no AI key needed.",
        False,
    ),
    ("grab_text", "Grab text", "Read the words out of the image into editable text.", False),
)

# The full op vocabulary the studio knows how to drive — used by the test-suite
# structural check and to keep the JS / panels in lock-step with the seam.
STUDIO_OPS: tuple[str, ...] = tuple(op for op, _, _, _ in TOOL_PANELS)


def _script_json(obj: object) -> str:
    """JSON for a ``<script>`` block — escape ``<`` so a value can never close
    the tag or smuggle markup into the page (same guard as the design studio)."""
    return json.dumps(obj, ensure_ascii=True).replace("<", "\\u003c")


def _style_options() -> str:
    opts = []
    for key in sorted(STYLE_PRESETS):
        sel = " selected" if key == DEFAULT_STYLE else ""
        label = escape(key.replace("_", " ").title())
        opts.append(f'<option value="{escape(key)}"{sel}>{label}</option>')
    return "".join(opts)


def _aspect_options() -> str:
    return "".join(
        f'<option value="{escape(val)}">{escape(label)}</option>' for val, label in ASPECT_CHOICES
    )


def _upscale_options() -> str:
    return "".join(
        f'<option value="{factor}">{escape(label)}</option>' for factor, label in UPSCALE_FACTORS
    )


def _panel_html(op: str, title: str, blurb: str, needs_mask: bool) -> str:
    """One tool panel. The op-specific control lives inside; the Apply button
    carries ``data-op`` so the JS knows which seam call to make. Panels start
    hidden via ``hidden`` and are revealed when the runtime capability probe
    confirms the op is live (honest: no button for an op the provider can't do).
    """
    brush_attr = ' data-needs-mask="1"' if needs_mask else ""
    controls = ""
    if op == "edit":
        controls = (
            '<label for="mh-st-edit-text">What should go there?</label>'
            '<input id="mh-st-edit-text" type="text" maxlength="240" '
            'placeholder="e.g. a clean navy wall behind the swimmer">'
            '<label class="mh-st-check"><input type="checkbox" id="mh-st-edit-people"> '
            "Allow people in the result (off by default)</label>"
        )
    elif op == "expand":
        controls = (
            '<label for="mh-st-expand-aspect">New shape</label>'
            f'<select id="mh-st-expand-aspect">{_aspect_options()}</select>'
            '<label for="mh-st-expand-prompt">Hint (optional)</label>'
            '<input id="mh-st-expand-prompt" type="text" maxlength="240" '
            'placeholder="e.g. more pool deck and lane ropes">'
        )
    elif op == "upscale":
        controls = (
            '<label for="mh-st-upscale-factor">Amount</label>'
            f'<select id="mh-st-upscale-factor">{_upscale_options()}</select>'
        )
    elif op == "style_match":
        controls = (
            '<label for="mh-st-style">Look</label>'
            f'<select id="mh-st-style">{_style_options()}</select>'
        )
    elif op == "similar":
        controls = (
            '<label for="mh-st-similar-prompt">Steer (optional)</label>'
            '<input id="mh-st-similar-prompt" type="text" maxlength="240" '
            'placeholder="e.g. warmer, more dynamic">'
        )
    elif op == "grab_text":
        controls = (
            '<textarea id="mh-st-grab-out" class="mh-st-grab" rows="4" readonly '
            'placeholder="The transcribed text appears here." hidden></textarea>'
        )
    # subject_lift / remove need no extra control beyond the brush / button.

    apply_label = {
        "subject_lift": "Lift subject",
        "grab_text": "Read text",
        "similar": "Make variations",
    }.get(op, title)

    return (
        f'<section class="mh-st-panel" data-panel="{escape(op)}"{brush_attr} hidden>'
        f"<h3>{escape(title)}</h3>"
        f'<p class="dim">{escape(blurb)}</p>'
        f"{controls}"
        f'<button type="button" class="btn mh-st-apply" data-op="{escape(op)}">'
        f"{escape(apply_label)} &rarr;</button>"
        '<span class="mh-st-panel-note dim" hidden></span>'
        "</section>"
    )


def render_studio_body(
    *,
    asset_id: str,
    asset_label: str,
    asset_type: str,
    asset_url: str,
    info_url: str,
    op_url_base: str,
    grab_text_url: str,
    subject_lift_url: str,
    cutout_url: str,
    studio_url_base: str,
    file_url_base: str,
    back_url: str,
    gen_history_url: str,
    width: int = 0,
    height: int = 0,
    dev_operator: bool = False,
) -> str:
    """Build the Image-studio page body.

    Every URL is passed in already-resolved (``url_for`` lives in the route, not
    here). ``op_url_base`` carries :data:`OP_SENTINEL` where the operation name
    goes; ``studio_url_base`` / ``file_url_base`` carry :data:`ASSET_SENTINEL`
    where a *result* asset id goes, so the JS can offer "open the result in the
    studio" without another round-trip. The asset label/type are HTML-escaped
    (parsed metadata is never trusted into markup — same ``_h()`` rule as the
    rest of the app).
    """
    cfg = {
        "infoUrl": info_url,
        "opUrlBase": op_url_base,
        "opSentinel": OP_SENTINEL,
        "grabTextUrl": grab_text_url,
        "subjectLiftUrl": subject_lift_url,
        "cutoutUrl": cutout_url,
        "studioUrlBase": studio_url_base,
        "fileUrlBase": file_url_base,
        "assetSentinel": ASSET_SENTINEL,
        "width": int(width or 0),
        "height": int(height or 0),
    }
    config = _script_json(cfg)

    safe_label = escape(asset_label or "this photo")
    safe_type = escape((asset_type or "photo").replace("_", " "))
    dims = f"{int(width)}&times;{int(height)}" if width and height else ""

    panels = "".join(
        _panel_html(op, title, blurb, needs_mask) for op, title, blurb, needs_mask in TOOL_PANELS
    )

    hero = (
        '<section class="mh-hero" data-lane="" '
        'style="padding-top:var(--sp-7);padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Image studio</span>'
        f"<h1>{safe_label}</h1>"
        '<div class="strap" style="margin-top:var(--sp-3)">'
        f"<span>{safe_type}</span>"
        + (f'<span class="sep">·</span><span>{dims}</span>' if dims else "")
        + '<span class="sep">·</span>'
        f'<a href="{escape(back_url)}">&larr; Library</a>'
        '<span class="sep">·</span>'
        f'<a href="{escape(gen_history_url)}">Generated images</a>'
        "</div>"
        '<p class="lede" style="margin-top:var(--sp-3)">Paint a mask and fill or erase, '
        "expand the canvas, upscale, restyle, lift the subject, or grab the text. Every result "
        "is provenance-stamped and saved to your library as a draft for review &mdash; nothing "
        "is published.</p>"
        "</section>"
    )

    stage = (
        '<div class="mh-st-stage-col">'
        '<div class="mh-st-stage" id="mh-st-stage">'
        f'<img class="mh-st-img" id="mh-st-img" src="{escape(asset_url)}" '
        f'alt="{safe_label}" crossorigin="anonymous">'
        '<canvas class="mh-st-overlay" id="mh-st-overlay"></canvas>'
        "</div>"
        # Brush bar — only meaningful for the mask ops; the JS shows it when a
        # mask panel is active.
        '<div class="mh-st-brushbar" id="mh-st-brushbar" hidden>'
        '<div class="mh-st-tooltoggle" role="group" aria-label="Brush mode">'
        '<button type="button" class="btn secondary is-on" id="mh-st-brush" data-mode="brush">Brush</button>'
        '<button type="button" class="btn secondary" id="mh-st-erase" data-mode="erase">Eraser</button>'
        "</div>"
        '<label for="mh-st-size" class="mh-st-sizelabel">Size</label>'
        '<input type="range" id="mh-st-size" min="6" max="160" value="40">'
        '<button type="button" class="btn ghost" id="mh-st-clear">Clear mask</button>'
        '<span class="dim mh-st-brushhint">Paint where the change should happen.</span>'
        "</div>"
        "</div>"
    )

    tools = (
        '<aside class="mh-st-tools" id="mh-st-tools">'
        '<div class="mh-st-statusbar">'
        '<span class="mh-st-provider" id="mh-st-provider">Checking image engine&hellip;</span>'
        '<span class="mh-st-quota dim" id="mh-st-quota"></span>'
        "</div>"
        # Honest note shown when no image provider is configured. The
        # deterministic / vision ops can still light up independently.
        # Env-var instructions are operator-only: hosted-SaaS customers cannot
        # set env vars, so they get plain "not enabled here" copy instead.
        '<p class="mh-st-providernote dim" id="mh-st-providernote" hidden>'
        + (
            "No image generator is configured, so the AI edit tools are off. The default is the "
            "in-house on-server model (set <code>MEDIAHUB_IMAGINE_LOCAL_ENDPOINT</code>); a "
            "Gemini key also enables them."
            if dev_operator
            else "AI edit tools aren&rsquo;t enabled on this deployment &mdash; ask your "
            "operator about turning them on."
        )
        + "</p>"
        f"{panels}"
        '<p class="dim mh-st-noops" id="mh-st-noops" hidden>No studio tools are available on '
        "this deployment yet.</p>"
        "</aside>"
    )

    results = (
        '<section class="mh-st-results" id="mh-st-results" hidden>'
        "<h2>Results</h2>"
        '<p class="dim">Each edit is a new draft in your library. Open one in the studio to keep '
        "editing, or download it.</p>"
        '<div class="mh-st-resultstrip" id="mh-st-resultstrip"></div>'
        "</section>"
    )

    # The live status line for the running op.
    statusline = '<div class="mh-st-runstatus dim" id="mh-st-runstatus" role="status" aria-live="polite"></div>'

    body = (
        f"{hero}"
        f'<div class="mh-st" data-asset="{escape(asset_id)}">'
        f"{stage}"
        f"{tools}"
        "</div>"
        f"{statusline}"
        f"{results}"
        f'<script type="application/json" id="mh-st-config">{config}</script>'
        f"<style>{_STUDIO_CSS}</style>"
        f"<script>{_STUDIO_JS}</script>"
    )
    return body


# ---------------------------------------------------------------------------
# Styling — dark-first, leans on the existing CSS variables (--bg/--panel/
# --accent/--ink/--border), scoped under .mh-st so it can't bleed.
# ---------------------------------------------------------------------------

_STUDIO_CSS = """
.mh-st{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:var(--sp-5);align-items:start}
@media (max-width:860px){.mh-st{grid-template-columns:1fr}}
.mh-st-stage-col{min-width:0}
.mh-st-stage{position:relative;display:inline-block;max-width:100%;border:1px solid var(--border);
  border-radius:10px;overflow:hidden;background:
  repeating-conic-gradient(#1b1f27 0% 25%, #232833 0% 50%) 50%/22px 22px;line-height:0}
.mh-st-img{display:block;max-width:100%;height:auto;user-select:none;-webkit-user-drag:none}
.mh-st-overlay{position:absolute;inset:0;width:100%;height:100%;cursor:crosshair;touch-action:none}
.mh-st-brushbar{display:flex;align-items:center;gap:var(--sp-3);flex-wrap:wrap;margin-top:var(--sp-4);
  padding:var(--sp-3) var(--sp-4);border:1px solid var(--border);border-radius:10px;background:var(--panel)}
.mh-st-tooltoggle{display:inline-flex;gap:2px}
.mh-st-tooltoggle .btn{font-size:12px;padding:4px 12px}
.mh-st-tooltoggle .btn.is-on{background:var(--accent);color:var(--accent-ink,#0b0d12);border-color:var(--accent)}
.mh-st-sizelabel{margin:0 0 0 var(--sp-2);font-size:12px}
#mh-st-size{max-width:130px}
.mh-st-brushhint{font-size:12px;flex:1 1 140px}
.mh-st-tools{display:flex;flex-direction:column;gap:var(--sp-3);position:sticky;top:var(--sp-4)}
.mh-st-statusbar{display:flex;justify-content:space-between;align-items:baseline;gap:var(--sp-3);
  padding-bottom:var(--sp-2);border-bottom:1px solid var(--border)}
.mh-st-provider{font-weight:600;font-size:13px}
.mh-st-quota{font-size:12px}
.mh-st-providernote{font-size:12px;line-height:1.45;margin:0}
.mh-st-providernote code{font-size:11px}
.mh-st-panel{border:1px solid var(--border);border-radius:10px;padding:var(--sp-4);background:var(--panel)}
.mh-st-panel.is-active{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
.mh-st-panel h3{margin:0 0 4px;font-size:14px}
.mh-st-panel p.dim{margin:0 0 var(--sp-3);font-size:12px;line-height:1.4}
.mh-st-panel label{display:block;font-size:12px;margin:var(--sp-3) 0 4px}
.mh-st-panel input[type=text],.mh-st-panel select,.mh-st-grab{width:100%;box-sizing:border-box}
.mh-st-check{display:flex !important;align-items:center;gap:6px;font-size:12px}
.mh-st-check input{width:auto}
.mh-st-apply{margin-top:var(--sp-4);font-size:13px}
.mh-st-panel .btn[disabled]{opacity:0.5;cursor:not-allowed}
.mh-st-panel-note{display:block;margin-top:var(--sp-3);font-size:11px}
.mh-st-grab{margin-top:var(--sp-3);font-family:var(--mono,monospace);font-size:12px}
.mh-st-runstatus{min-height:20px;margin-top:var(--sp-4);font-size:13px}
.mh-st-runstatus.is-err{color:var(--danger,#ff6b6b)}
.mh-st-results{margin-top:var(--sp-5)}
.mh-st-results h2{margin-bottom:var(--sp-2)}
.mh-st-resultstrip{display:flex;gap:var(--sp-4);flex-wrap:wrap;margin-top:var(--sp-4)}
.mh-st-result{width:180px;border:1px solid var(--border);border-radius:10px;overflow:hidden;background:var(--panel)}
.mh-st-result img{width:100%;display:block;aspect-ratio:1;object-fit:cover;background:var(--bg)}
.mh-st-result figcaption{padding:var(--sp-3)}
.mh-st-result .mh-st-op{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--ink-muted)}
.mh-st-result .mh-st-acts{display:flex;gap:6px;margin-top:var(--sp-3)}
.mh-st-result .btn{font-size:11px;padding:3px 9px}
.mh-st-busy{opacity:.6;pointer-events:none}
"""


# ---------------------------------------------------------------------------
# Behaviour — vanilla JS. Canvas maths map display pixels → the photo's natural
# pixels so the exported mask aligns with the source the provider receives.
# ---------------------------------------------------------------------------

_STUDIO_JS = r"""
(function(){
  var cfgEl = document.getElementById('mh-st-config');
  if(!cfgEl) return;
  var CFG; try{ CFG = JSON.parse(cfgEl.textContent||'{}'); }catch(e){ return; }

  var img = document.getElementById('mh-st-img');
  var overlay = document.getElementById('mh-st-overlay');
  var brushbar = document.getElementById('mh-st-brushbar');
  var sizeInput = document.getElementById('mh-st-size');
  var status = document.getElementById('mh-st-runstatus');
  var providerEl = document.getElementById('mh-st-provider');
  var quotaEl = document.getElementById('mh-st-quota');
  var providerNote = document.getElementById('mh-st-providernote');
  var noOps = document.getElementById('mh-st-noops');
  var resultsWrap = document.getElementById('mh-st-results');
  var strip = document.getElementById('mh-st-resultstrip');
  if(!img || !overlay) return;

  // Offscreen mask canvas at NATURAL resolution: white = act here, black = leave.
  var mask = document.createElement('canvas');
  var octx = overlay.getContext('2d');           // visible tinted strokes
  var mctx = mask.getContext('2d');              // exported white-on-black mask
  var painted = false, mode = 'brush', drawing = false, last = null;

  function sizeCanvases(){
    var nw = img.naturalWidth||CFG.width||img.width||512;
    var nh = img.naturalHeight||CFG.height||img.height||512;
    overlay.width = nw; overlay.height = nh;
    mask.width = nw; mask.height = nh;
    resetMask();
  }
  function resetMask(){
    mctx.globalCompositeOperation='source-over';
    mctx.fillStyle='#000'; mctx.fillRect(0,0,mask.width,mask.height);
    octx.clearRect(0,0,overlay.width,overlay.height);
    painted=false;
  }
  function toCanvas(e){
    var r = overlay.getBoundingClientRect();
    var sx = overlay.width/(r.width||1), sy = overlay.height/(r.height||1);
    return { x:(e.clientX-r.left)*sx, y:(e.clientY-r.top)*sy };
  }
  function stroke(a,b){
    var lw = parseInt(sizeInput && sizeInput.value || '40',10);
    // Visible overlay stroke (accent-tinted) or erase via destination-out.
    octx.lineCap='round'; octx.lineJoin='round'; octx.lineWidth=lw;
    octx.globalCompositeOperation = (mode==='erase') ? 'destination-out' : 'source-over';
    octx.strokeStyle = 'rgba(110,168,254,0.55)';
    octx.beginPath(); octx.moveTo(a.x,a.y); octx.lineTo(b.x,b.y); octx.stroke();
    // Export mask: white to act, black to leave.
    mctx.lineCap='round'; mctx.lineJoin='round'; mctx.lineWidth=lw;
    mctx.globalCompositeOperation='source-over';
    mctx.strokeStyle = (mode==='erase') ? '#000' : '#fff';
    mctx.beginPath(); mctx.moveTo(a.x,a.y); mctx.lineTo(b.x,b.y); mctx.stroke();
    if(mode!=='erase') painted=true;
  }
  overlay.addEventListener('pointerdown',function(e){ drawing=true; last=toCanvas(e); stroke(last,last); overlay.setPointerCapture(e.pointerId); });
  overlay.addEventListener('pointermove',function(e){ if(!drawing) return; var p=toCanvas(e); stroke(last,p); last=p; });
  overlay.addEventListener('pointerup',function(){ drawing=false; });
  overlay.addEventListener('pointercancel',function(){ drawing=false; });

  if(img.complete && img.naturalWidth) sizeCanvases();
  img.addEventListener('load', sizeCanvases);

  // Brush-mode toggle + clear.
  var brushBtn=document.getElementById('mh-st-brush'), eraseBtn=document.getElementById('mh-st-erase');
  function setMode(m){ mode=m;
    if(brushBtn) brushBtn.classList.toggle('is-on', m==='brush');
    if(eraseBtn) eraseBtn.classList.toggle('is-on', m==='erase'); }
  if(brushBtn) brushBtn.addEventListener('click',function(){setMode('brush');});
  if(eraseBtn) eraseBtn.addEventListener('click',function(){setMode('erase');});
  var clearBtn=document.getElementById('mh-st-clear');
  if(clearBtn) clearBtn.addEventListener('click',resetMask);

  function maskB64(){
    if(!painted) return null;
    var url = mask.toDataURL('image/png');
    var comma = url.indexOf(','); return comma<0 ? null : url.slice(comma+1);
  }

  function opUrl(op){ return CFG.opUrlBase.replace(CFG.opSentinel, op); }
  function studioUrl(id){ return CFG.studioUrlBase.replace(CFG.assetSentinel, encodeURIComponent(id)); }
  function fileUrl(id){ return CFG.fileUrlBase.replace(CFG.assetSentinel, encodeURIComponent(id)); }

  function say(msg, err){ status.textContent=msg||''; status.classList.toggle('is-err', !!err); }
  function renderQuota(q){
    if(!q || quotaEl==null) return;
    if(q.unlimited){ quotaEl.textContent='Unlimited'; return; }
    quotaEl.textContent = (q.remaining)+' of '+(q.limit)+' image edits left this month';
  }

  // Panels show only for ops the active provider advertises.
  function showPanels(ops){
    var set={}; (ops||[]).forEach(function(o){set[o]=true;});
    var anyMask=false, anyShown=false;
    document.querySelectorAll('.mh-st-panel').forEach(function(p){
      var op=p.getAttribute('data-panel');
      var ok=!!set[op];
      p.hidden=!ok;
      if(ok){ anyShown=true; if(p.getAttribute('data-needs-mask')) anyMask=true; }
    });
    if(noOps) noOps.hidden = anyShown;
    return anyMask;
  }

  function addResult(op, asset){
    if(!asset || !asset.id) return;
    resultsWrap.hidden=false;
    var fig=document.createElement('figure'); fig.className='mh-st-result';
    var url = fileUrl(asset.id);
    fig.innerHTML =
      '<a href="'+url+'" target="_blank" rel="noopener"><img loading="lazy" src="'+url+'" alt=""></a>'+
      '<figcaption><span class="mh-st-op"></span>'+
      '<div class="mh-st-acts">'+
        '<a class="btn secondary" data-studio>Open</a>'+
        '<a class="btn ghost" href="'+url+'" download>Save</a>'+
      '</div></figcaption>';
    fig.querySelector('.mh-st-op').textContent = op;
    fig.querySelector('[data-studio]').href = studioUrl(asset.id);
    strip.insertBefore(fig, strip.firstChild);
  }

  function run(op, payload, btn){
    say('Working…'); if(btn) btn.disabled=true;
    document.querySelector('.mh-st').classList.add('mh-st-busy');
    var url, opts={method:'POST',headers:{'Content-Type':'application/json'}};
    if(op==='grab_text'){ url=CFG.grabTextUrl; opts.body='{}'; }
    else if(op==='subject_lift'){ url=CFG.subjectLiftUrl; opts.body=JSON.stringify(payload||{}); }
    else { url=opUrl(op); opts.body=JSON.stringify(payload||{}); }
    fetch(url,opts).then(function(r){ return r.json().then(function(j){return {ok:r.ok,j:j};}); })
    .then(function(res){
      document.querySelector('.mh-st').classList.remove('mh-st-busy');
      if(btn) btn.disabled=false;
      var j=res.j||{};
      if(!res.ok || !j.ok){ say((j.user_message||j.error||'That didn’t work.'), true); return; }
      if(j.quota) renderQuota(j.quota);
      if(op==='grab_text'){
        var out=document.getElementById('mh-st-grab-out');
        if(out){ out.hidden=false; out.value = j.found ? (j.text||'') : 'No legible text found.'; }
        say('Done.'); return;
      }
      if(op==='subject_lift'){ status.classList.remove('is-err'); status.innerHTML='Subject lifted &mdash; <a href="'+CFG.cutoutUrl+'">see the cut-out</a>.'; return; }
      addResult(op, j.asset); say('Done — saved as a draft in your library.');
    })
    .catch(function(){ document.querySelector('.mh-st').classList.remove('mh-st-busy'); if(btn) btn.disabled=false; say('Network error.', true); });
  }

  // Wire each panel's Apply button to its seam call.
  document.querySelectorAll('.mh-st-apply').forEach(function(btn){
    btn.addEventListener('click',function(){
      var op=btn.getAttribute('data-op');
      if(op==='edit'){
        var instr=(document.getElementById('mh-st-edit-text').value||'').trim();
        if(!instr){ say('Say what should go in the painted area first.', true); return; }
        run('edit', {instruction:instr, mask_b64:maskB64(), allow_people:document.getElementById('mh-st-edit-people').checked}, btn);
      } else if(op==='remove'){
        if(!painted){ say('Paint over what you want removed first.', true); return; }
        run('remove', {mask_b64:maskB64()}, btn);
      } else if(op==='expand'){
        run('expand', {aspect:document.getElementById('mh-st-expand-aspect').value, prompt:(document.getElementById('mh-st-expand-prompt').value||'').trim()}, btn);
      } else if(op==='upscale'){
        run('upscale', {factor:parseInt(document.getElementById('mh-st-upscale-factor').value,10)||2}, btn);
      } else if(op==='style_match'){
        run('style_match', {style:document.getElementById('mh-st-style').value}, btn);
      } else if(op==='similar'){
        run('similar', {prompt:(document.getElementById('mh-st-similar-prompt').value||'').trim()}, btn);
      } else if(op==='subject_lift'){
        run('subject_lift', {ratio:'4:5'}, btn);
      } else if(op==='grab_text'){
        run('grab_text', {}, btn);
      }
    });
  });

  // Activate the brush when a mask panel is in focus; the bar is otherwise idle.
  function maybeShowBrush(){
    var anyMask = document.querySelector('.mh-st-panel[data-needs-mask]:not([hidden])');
    if(brushbar) brushbar.hidden = !anyMask;
  }

  // Probe live capabilities, quota and the active provider.
  fetch(CFG.infoUrl, {headers:{'Accept':'application/json'}})
    .then(function(r){ return r.ok ? r.json() : null; })
    .then(function(info){
      if(!info){ providerEl.textContent='Image engine unavailable.'; showPanels([]); return; }
      providerEl.textContent = info.available ? ('Engine: '+(info.provider||'ready')) : 'No image generator configured';
      if(providerNote) providerNote.hidden = !!info.available;
      renderQuota(info.quota);
      showPanels(info.operations||[]);
      maybeShowBrush();
    })
    .catch(function(){ providerEl.textContent='Image engine unavailable.'; showPanels([]); });
})();
"""


__all__ = [
    "render_studio_body",
    "OP_SENTINEL",
    "ASSET_SENTINEL",
    "ASPECT_CHOICES",
    "UPSCALE_FACTORS",
    "TOOL_PANELS",
    "STUDIO_OPS",
]
