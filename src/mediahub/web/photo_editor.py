"""Flask-free body for the non-destructive photo editor (roadmap **1.3**).

Mirrors :mod:`mediahub.web.image_studio`: a pure function that builds the editor
page's HTML + scoped CSS + JS, with every URL passed in already-resolved
(``url_for`` lives in the route, not here) so the body unit-tests without a
request context. The editor is **run-independent** — it operates on a library
asset, which is exactly the "standalone Photo Editor" surface the roadmap asks
for; it's reachable from the media library without starting a content run.

The page is *server-authoritative*: the JS assembles an
:class:`~mediahub.media_library.photo_ops.EditRecipe` from the controls and
debounce-POSTs it to the preview endpoint, swapping in the real server render —
so what you see is byte-for-byte what "Apply & save" persists. Tone/colour
maths never runs an LLM (deterministic-engine boundary); one-click Enhance asks
the server for a deterministic recipe.
"""

from __future__ import annotations

import json

from markupsafe import escape

__all__ = ["render_editor_body", "ADJUST_CONTROLS", "EFFECT_CONTROLS"]


def _script_json(obj: object) -> str:
    """JSON safe to embed inside a ``<script>`` (no ``</script>`` break-out)."""
    return json.dumps(obj).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# Each tuple: (op, param, label, min, max, step, default, map). ``map`` tells the
# JS how to turn the 0-centred/0-based slider value into the op's real param:
#   factorpct → factor = 1 + v/100   unit → amount = v        pct01 → v/100
#   amount    → amount = v           div25 → v/25 (0..4)       raw → v
ADJUST_CONTROLS = (
    ("brightness", "factor", "Brightness", -90, 90, 1, 0, "factorpct"),
    ("contrast", "factor", "Contrast", -80, 120, 1, 0, "factorpct"),
    ("saturation", "factor", "Saturation", -100, 120, 1, 0, "factorpct"),
    ("warmth", "amount", "Warmth", -100, 100, 1, 0, "unit"),
    ("tint", "amount", "Tint", -100, 100, 1, 0, "unit"),
    ("highlights", "amount", "Highlights", -100, 100, 1, 0, "unit"),
    ("shadows", "amount", "Shadows", -100, 100, 1, 0, "unit"),
    ("white_balance", "amount", "White balance", 0, 100, 1, 0, "pct01"),
    ("clarity", "amount", "Clarity", 0, 100, 1, 0, "amount"),
    ("sharpen", "amount", "Sharpen", 0, 100, 1, 0, "div25"),
)

EFFECT_CONTROLS = (
    ("vignette", "amount", "Vignette", 0, 100, 1, 0, "amount"),
    ("blur", "radius", "Blur", 0, 60, 1, 0, "raw"),
    ("grayscale", "amount", "Black & white", 0, 100, 1, 0, "pct01"),
    ("sepia", "amount", "Sepia", 0, 100, 1, 0, "pct01"),
    ("golden_hour", "amount", "Golden hour", 0, 100, 1, 0, "pct01"),
    ("colour_punch", "amount", "Colour punch", 0, 100, 1, 0, "amount"),
    ("pixelate", "size", "Pixelate", 1, 64, 1, 1, "raw"),
    ("glitch", "amount", "Glitch", 0, 100, 1, 0, "amount"),
    ("opacity", "alpha", "Opacity", 0, 100, 1, 100, "pct01"),
)

FILTERS = (
    "natural",
    "crisp",
    "punchy",
    "vivid",
    "editorial",
    "soft",
    "mono",
    "noir",
    "sepia",
    "golden",
    "poolside",
)
SHAPES = ("circle", "oval", "square", "rounded", "triangle", "star", "heart")
PROFILE_PRESETS = (
    ("avatar_circle", "Circle"),
    ("avatar_square", "Rounded"),
    ("avatar_ring", "Brand ring"),
)


def _slider(op: str, param: str, label: str, lo, hi, step, default, mp) -> str:
    sid = f"pe-{op}"
    return (
        '<div class="pe-ctl">'
        f'<label for="{sid}">{escape(label)}<span class="pe-val" id="{sid}-v">{default}</span></label>'
        f'<input type="range" id="{sid}" data-op="{op}" data-param="{param}" data-map="{mp}" '
        f'data-default="{default}" min="{lo}" max="{hi}" step="{step}" value="{default}">'
        "</div>"
    )


def render_editor_body(
    *,
    asset_id: str,
    asset_label: str,
    asset_type: str,
    asset_url: str,
    edited_url: str,
    apply_url: str,
    preview_url: str,
    enhance_url: str,
    reset_url: str,
    profile_pic_url: str,
    back_url: str,
    studio_url: str = "",
    cutout_url: str = "",
    width: int = 0,
    height: int = 0,
    brand_shadow: str = "#0b1020",
    brand_highlight: str = "#f5f7ff",
    has_edit: bool = False,
    recipe: object = None,
) -> str:
    """Build the photo-editor page body. Every URL is pre-resolved by the route."""
    cfg = {
        "assetId": asset_id,
        "applyUrl": apply_url,
        "previewUrl": preview_url,
        "enhanceUrl": enhance_url,
        "resetUrl": reset_url,
        "profilePicUrl": profile_pic_url,
        "assetUrl": asset_url,
        "editedUrl": edited_url,
        "width": int(width or 0),
        "height": int(height or 0),
        "brandShadow": brand_shadow,
        "brandHighlight": brand_highlight,
        "recipe": recipe if isinstance(recipe, dict) else {"steps": []},
    }
    config = _script_json(cfg)
    safe_label = escape(asset_label or "this photo")
    safe_type = escape((asset_type or "photo").replace("_", " "))
    dims = f"{int(width)}&times;{int(height)}" if width and height else ""

    extra_links = ""
    if studio_url:
        extra_links += f'<span class="sep">·</span><a href="{escape(studio_url)}">AI studio</a>'
    if cutout_url:
        extra_links += f'<span class="sep">·</span><a href="{escape(cutout_url)}">Cut-out</a>'

    hero = (
        '<section class="mh-hero" data-lane="" '
        'style="padding-top:var(--sp-7);padding-bottom:var(--sp-5);margin-bottom:var(--sp-5)">'
        '<span class="mh-hero-eyebrow">Photo editor</span>'
        f"<h1>{safe_label}</h1>"
        '<div class="strap" style="margin-top:var(--sp-3)">'
        f"<span>{safe_type}</span>"
        + (f'<span class="sep">·</span><span>{dims}</span>' if dims else "")
        + f'<span class="sep">·</span><a href="{escape(back_url)}">&larr; Library</a>'
        + extra_links
        + "</div>"
        '<p class="lede" style="margin-top:var(--sp-3)">Filters, adjustments, crop &amp; '
        "perspective, shapes, frames, a blur brush and one-click enhance &mdash; all "
        "non-destructive. Your original is never changed; the recipe is applied to a copy at "
        "render time, so a card always shows the edited photo.</p>"
        "</section>"
    )

    stage = (
        '<div class="pe-stage-col">'
        '<div class="pe-stage" id="pe-stage">'
        f'<img class="pe-img" id="pe-img" src="{escape(edited_url if has_edit else asset_url)}" '
        f'alt="{safe_label}" crossorigin="anonymous">'
        '<canvas class="pe-overlay" id="pe-overlay"></canvas>'
        '<div class="pe-busy" id="pe-busy" hidden>rendering&hellip;</div>'
        "</div>"
        '<div class="pe-stagebar">'
        '<button type="button" class="btn" id="pe-apply">Apply &amp; save</button>'
        '<button type="button" class="btn secondary" id="pe-enhance">&#10022; Enhance</button>'
        '<button type="button" class="btn ghost" id="pe-undo">Undo</button>'
        '<button type="button" class="btn ghost" id="pe-reset">Reset</button>'
        '<span class="pe-saved dim" id="pe-saved" role="status" aria-live="polite"></span>'
        "</div>"
        "</div>"
    )

    # --- tool sections -----------------------------------------------------
    filter_chips = "".join(
        f'<button type="button" class="pe-filter" data-filter="{f}">{escape(f.title())}</button>'
        for f in FILTERS
    )
    filters = (
        '<details class="pe-sec" open><summary>Filters</summary>'
        f'<div class="pe-filters" id="pe-filters">{filter_chips}</div>'
        '<div class="pe-ctl"><label for="pe-filter-int">Intensity'
        '<span class="pe-val" id="pe-filter-int-v">100</span></label>'
        '<input type="range" id="pe-filter-int" min="0" max="100" step="1" value="100"></div>'
        "</details>"
    )

    adjust = (
        '<details class="pe-sec" open><summary>Adjust</summary>'
        + "".join(_slider(*c) for c in ADJUST_CONTROLS)
        + "</details>"
    )
    effects = (
        '<details class="pe-sec"><summary>Effects</summary>'
        + "".join(_slider(*c) for c in EFFECT_CONTROLS)
        + '<div class="pe-ctl pe-duo"><label>Duotone'
        '<input type="checkbox" id="pe-duo-on"></label>'
        f'<input type="color" id="pe-duo-lo" value="{escape(brand_shadow)}" aria-label="Duotone shadow">'
        f'<input type="color" id="pe-duo-hi" value="{escape(brand_highlight)}" aria-label="Duotone highlight">'
        '<input type="range" id="pe-duo-int" min="0" max="100" step="1" value="100" aria-label="Duotone intensity">'
        "</div>"
        "</details>"
    )

    crop = (
        '<details class="pe-sec"><summary>Crop &amp; rotate</summary>'
        '<div class="pe-row" id="pe-aspect">'
        '<button type="button" class="btn ghost" data-aspect="free">Free</button>'
        '<button type="button" class="btn ghost" data-aspect="1:1">1:1</button>'
        '<button type="button" class="btn ghost" data-aspect="4:5">4:5</button>'
        '<button type="button" class="btn ghost" data-aspect="9:16">9:16</button>'
        '<button type="button" class="btn ghost" data-aspect="16:9">16:9</button>'
        "</div>"
        '<p class="dim pe-hint">Drag on the photo to set a crop box.</p>'
        '<div class="pe-row">'
        '<button type="button" class="btn ghost" id="pe-rotl">&#8634; 90&deg;</button>'
        '<button type="button" class="btn ghost" id="pe-rotr">90&deg; &#8635;</button>'
        '<button type="button" class="btn ghost" id="pe-fliph">Flip H</button>'
        '<button type="button" class="btn ghost" id="pe-flipv">Flip V</button>'
        '<button type="button" class="btn ghost" id="pe-crop-clear">Clear crop</button>'
        "</div>"
        '<div class="pe-ctl"><label for="pe-persp-h">Perspective H'
        '<span class="pe-val" id="pe-persp-h-v">0</span></label>'
        '<input type="range" id="pe-persp-h" min="-100" max="100" step="1" value="0"></div>'
        '<div class="pe-ctl"><label for="pe-persp-v">Perspective V'
        '<span class="pe-val" id="pe-persp-v-v">0</span></label>'
        '<input type="range" id="pe-persp-v" min="-100" max="100" step="1" value="0"></div>'
        "</details>"
    )

    shape_opts = "".join(f'<option value="{s}">{escape(s.title())}</option>' for s in SHAPES)
    shape = (
        '<details class="pe-sec"><summary>Shape &amp; frame</summary>'
        '<div class="pe-ctl"><label for="pe-shape">Crop to shape</label>'
        f'<select id="pe-shape"><option value="">None</option>{shape_opts}</select></div>'
        '<div class="pe-ctl"><label for="pe-shape-feather">Feather'
        '<span class="pe-val" id="pe-shape-feather-v">0</span></label>'
        '<input type="range" id="pe-shape-feather" min="0" max="100" step="1" value="0"></div>'
        '<div class="pe-ctl"><label>Frame<input type="checkbox" id="pe-frame-on"></label>'
        '<input type="color" id="pe-frame-col" value="#ffffff" aria-label="Frame colour">'
        '<input type="range" id="pe-frame-w" min="1" max="20" step="1" value="4" aria-label="Frame width"></div>'
        "</details>"
    )

    brush = (
        '<details class="pe-sec"><summary>Blur brush &amp; eraser</summary>'
        '<p class="dim pe-hint">Paint to blur faces / bystanders (safeguarding) or erase pixels.</p>'
        '<div class="pe-row pe-brushmode" role="group" aria-label="Brush mode">'
        '<button type="button" class="btn secondary is-on" id="pe-brush-blur" data-brush="blur_brush">Blur brush</button>'
        '<button type="button" class="btn secondary" id="pe-brush-erase" data-brush="eraser">Eraser</button>'
        '<button type="button" class="btn ghost" id="pe-brush-off" data-brush="">Off</button>'
        "</div>"
        '<div class="pe-ctl"><label for="pe-brush-size">Brush size'
        '<span class="pe-val" id="pe-brush-size-v">8</span></label>'
        '<input type="range" id="pe-brush-size" min="2" max="40" step="1" value="8"></div>'
        '<button type="button" class="btn ghost" id="pe-brush-clear">Clear brush strokes</button>'
        "</details>"
    )

    prof_btns = "".join(
        f'<button type="button" class="btn ghost pe-profile" data-preset="{p}">{escape(lbl)}</button>'
        for p, lbl in PROFILE_PRESETS
    )
    export = (
        '<details class="pe-sec"><summary>Export</summary>'
        '<p class="dim pe-hint">Save a profile picture as a new draft asset.</p>'
        f'<div class="pe-row" id="pe-profile">{prof_btns}</div>'
        "</details>"
    )

    tools = (
        '<aside class="pe-tools" id="pe-tools">'
        f"{filters}{adjust}{effects}{crop}{shape}{brush}{export}"
        "</aside>"
    )

    body = (
        f"{hero}"
        f'<div class="pe" data-asset="{escape(asset_id)}">'
        f"{stage}{tools}"
        "</div>"
        f'<script type="application/json" id="pe-config">{config}</script>'
        f"<style>{_CSS}</style>"
        f"<script>{_JS}</script>"
    )
    return body


_CSS = """
.pe{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:var(--sp-5);align-items:start}
@media (max-width:860px){.pe{grid-template-columns:1fr}}
.pe-stage-col{min-width:0;position:sticky;top:var(--sp-4)}
.pe-stage{position:relative;display:inline-block;max-width:100%;border:1px solid var(--border,#2a2f3a);
  border-radius:10px;overflow:hidden;background:repeating-conic-gradient(#1b1f27 0% 25%,#232833 0% 50%) 50%/22px 22px;line-height:0}
.pe-img{display:block;max-width:100%;height:auto;user-select:none;-webkit-user-drag:none}
.pe-overlay{position:absolute;inset:0;width:100%;height:100%;cursor:crosshair;touch-action:none}
.pe-busy{position:absolute;top:8px;right:8px;background:rgba(0,0,0,.6);color:#fff;font-size:12px;
  padding:3px 8px;border-radius:6px}
.pe-stagebar{display:flex;gap:var(--sp-2);flex-wrap:wrap;align-items:center;margin-top:var(--sp-4)}
.pe-saved{margin-left:auto}
.pe-tools{display:flex;flex-direction:column;gap:var(--sp-3)}
.pe-sec{border:1px solid var(--border,#2a2f3a);border-radius:10px;background:var(--panel,#141821);
  padding:var(--sp-3) var(--sp-4)}
.pe-sec>summary{cursor:pointer;font-weight:600;list-style:none}
.pe-sec>summary::-webkit-details-marker{display:none}
.pe-ctl{margin-top:var(--sp-3)}
.pe-ctl label{display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px;align-items:center;gap:8px}
.pe-ctl input[type=range]{width:100%}
.pe-val{color:var(--ink-dim,#9aa3b2);font-variant-numeric:tabular-nums}
.pe-filters{display:flex;flex-wrap:wrap;gap:6px;margin-top:var(--sp-2)}
.pe-filter{font-size:12px;padding:4px 10px;border:1px solid var(--border,#2a2f3a);border-radius:999px;
  background:transparent;color:var(--ink,#e8ecf3);cursor:pointer}
.pe-filter.is-on{background:var(--accent,#5b8cff);color:var(--accent-ink,#0b0d12);border-color:var(--accent,#5b8cff)}
.pe-row{display:flex;flex-wrap:wrap;gap:6px;margin-top:var(--sp-2)}
.pe-row .btn{font-size:12px;padding:5px 10px}
.pe-row .btn.is-on{background:var(--accent,#5b8cff);color:var(--accent-ink,#0b0d12);border-color:var(--accent,#5b8cff)}
.pe-hint{font-size:12px;margin:var(--sp-2) 0 0}
.pe-duo,.pe-ctl.pe-duo{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.pe-duo label{flex:0 0 auto}
"""


# The editor controller. Server-authoritative: it assembles a recipe and asks
# the server to render it (debounced), so the preview equals what is saved.
_JS = r"""
(function(){
  var cfgEl=document.getElementById('pe-config'); if(!cfgEl) return;
  var cfg; try{cfg=JSON.parse(cfgEl.textContent);}catch(e){return;}
  var img=document.getElementById('pe-img');
  var overlay=document.getElementById('pe-overlay');
  var busy=document.getElementById('pe-busy');
  var saved=document.getElementById('pe-saved');
  var RANK={crop:10,perspective:20,rotate:30,flip:40,resize:50,white_balance:90,auto_contrast:95,
    levels:100,brightness:110,contrast:120,highlights:130,shadows:140,warmth:150,tint:160,
    saturation:170,clarity:180,sharpen:190,filter:300,grayscale:400,sepia:410,duotone:420,
    golden_hour:430,colour_punch:440,vignette:500,blur:510,pixelate:520,glitch:530,
    blur_brush:600,eraser:610,shape_crop:700,frame:710,opacity:800};

  // Recipe state: a map of op -> params. Brush/crop kept in dedicated state.
  var ops={};                 // single-instance ops keyed by name
  var blurStamps=[], eraseStamps=[];
  var history=[];             // recipe snapshots for Undo
  var brushMode='blur_brush', brushSize=8, cropDrag=null;

  function snapshot(){ history.push(JSON.stringify(serialise())); if(history.length>40) history.shift(); }

  function serialise(){
    var o=Object.assign({}, ops);
    if(blurStamps.length) o.blur_brush={stamps:blurStamps, radius:14, feather:0.4};
    if(eraseStamps.length) o.eraser={stamps:eraseStamps, feather:0.3};
    var steps=Object.keys(o).map(function(k){return {op:k,params:o[k]};});
    steps.sort(function(a,b){return (RANK[a.op]||999)-(RANK[b.op]||999);});
    return {steps:steps};
  }

  // ---- server preview (debounced) ----
  var timer=null, inflight=false, pending=false;
  function schedulePreview(){ if(timer) clearTimeout(timer); timer=setTimeout(preview,160); }
  function preview(){
    if(inflight){pending=true;return;}
    inflight=true; busy.hidden=false;
    fetch(cfg.previewUrl,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(serialise())})
      .then(function(r){return r.ok?r.blob():null;})
      .then(function(b){ if(b){ var u=URL.createObjectURL(b);
        img.onload=function(){URL.revokeObjectURL(u);}; img.src=u; } })
      .catch(function(){})
      .then(function(){ inflight=false; busy.hidden=true;
        if(pending){pending=false; schedulePreview();} });
  }

  // ---- slider binding ----
  function applyMap(map,v){
    if(map==='factorpct') return 1+v/100;
    if(map==='unit') return v;
    if(map==='pct01') return v/100;
    if(map==='div25') return v/25;
    return v; // raw / amount
  }
  function isOff(op,param,v){
    if(op==='opacity') return v>=100;
    if(op==='pixelate') return v<=1;
    return v===0;
  }
  function bindSlider(el){
    var op=el.getAttribute('data-op'), param=el.getAttribute('data-param'), map=el.getAttribute('data-map');
    var lab=document.getElementById(el.id+'-v');
    el.addEventListener('input',function(){
      var v=parseFloat(el.value); if(lab) lab.textContent=el.value;
      if(isOff(op,param,v)){ delete ops[op]; }
      else { var p={}; p[param]=applyMap(map,v); ops[op]=p; }
      schedulePreview();
    });
    el.addEventListener('change',snapshot);
  }
  Array.prototype.forEach.call(document.querySelectorAll('input[type=range][data-op]'),bindSlider);

  // ---- filters ----
  var filterInt=document.getElementById('pe-filter-int');
  var filterIntV=document.getElementById('pe-filter-int-v');
  function setFilter(name){
    Array.prototype.forEach.call(document.querySelectorAll('.pe-filter'),function(b){
      b.classList.toggle('is-on', b.getAttribute('data-filter')===name && !!name);});
    if(name){ ops.filter={name:name, intensity:parseFloat(filterInt.value)/100}; }
    else { delete ops.filter; }
    schedulePreview();
  }
  Array.prototype.forEach.call(document.querySelectorAll('.pe-filter'),function(b){
    b.addEventListener('click',function(){ snapshot();
      var name=b.getAttribute('data-filter');
      setFilter(ops.filter&&ops.filter.name===name?'':name);});});
  if(filterInt) filterInt.addEventListener('input',function(){ filterIntV.textContent=filterInt.value;
    if(ops.filter){ops.filter.intensity=parseFloat(filterInt.value)/100; schedulePreview();}});

  // ---- duotone ----
  var duoOn=document.getElementById('pe-duo-on'),duoLo=document.getElementById('pe-duo-lo'),
      duoHi=document.getElementById('pe-duo-hi'),duoInt=document.getElementById('pe-duo-int');
  function syncDuo(){ if(duoOn.checked){ ops.duotone={shadow:duoLo.value,highlight:duoHi.value,
      amount:parseFloat(duoInt.value)/100}; } else { delete ops.duotone; } schedulePreview(); }
  [duoOn,duoLo,duoHi,duoInt].forEach(function(el){ if(el) el.addEventListener('input',function(){snapshot();syncDuo();}); });

  // ---- frame ----
  var frOn=document.getElementById('pe-frame-on'),frCol=document.getElementById('pe-frame-col'),
      frW=document.getElementById('pe-frame-w');
  function syncFrame(){ if(frOn.checked){ ops.frame={style:'solid',colour:frCol.value,
      width:parseFloat(frW.value)/100}; } else { delete ops.frame; } schedulePreview(); }
  [frOn,frCol,frW].forEach(function(el){ if(el) el.addEventListener('input',function(){snapshot();syncFrame();}); });

  // ---- shape ----
  var shapeSel=document.getElementById('pe-shape'),shapeF=document.getElementById('pe-shape-feather'),
      shapeFV=document.getElementById('pe-shape-feather-v');
  function syncShape(){ if(shapeSel.value){ ops.shape_crop={shape:shapeSel.value,
      feather:parseFloat(shapeF.value)/100}; } else { delete ops.shape_crop; } schedulePreview(); }
  if(shapeSel) shapeSel.addEventListener('change',function(){snapshot();syncShape();});
  if(shapeF) shapeF.addEventListener('input',function(){shapeFV.textContent=shapeF.value; if(shapeSel.value) syncShape();});

  // ---- rotate / flip ----
  document.getElementById('pe-rotl').addEventListener('click',function(){snapshot();rotate(-90);});
  document.getElementById('pe-rotr').addEventListener('click',function(){snapshot();rotate(90);});
  function rotate(delta){ var cur=(ops.rotate&&ops.rotate.degrees)||0; var d=((cur+delta)%360+360)%360;
    if(d===0) delete ops.rotate; else ops.rotate={degrees:d,expand:true}; schedulePreview(); }
  document.getElementById('pe-fliph').addEventListener('click',function(){snapshot();flip('h');});
  document.getElementById('pe-flipv').addEventListener('click',function(){snapshot();flip('v');});
  function flip(axis){ if(ops.flip&&ops.flip.axis===axis) delete ops.flip; else ops.flip={axis:axis};
    document.getElementById('pe-fliph').classList.toggle('is-on',!!ops.flip&&ops.flip.axis==='h');
    document.getElementById('pe-flipv').classList.toggle('is-on',!!ops.flip&&ops.flip.axis==='v');
    schedulePreview(); }

  // ---- perspective ----
  var pH=document.getElementById('pe-persp-h'),pV=document.getElementById('pe-persp-v');
  function syncPersp(){ var h=parseFloat(pH.value)/100,v=parseFloat(pV.value)/100;
    document.getElementById('pe-persp-h-v').textContent=pH.value;
    document.getElementById('pe-persp-v-v').textContent=pV.value;
    if(h===0&&v===0) delete ops.perspective; else ops.perspective={h:h,v:v}; schedulePreview(); }
  [pH,pV].forEach(function(el){ if(el){el.addEventListener('input',syncPersp);el.addEventListener('change',snapshot);} });

  // ---- aspect crop presets + drag crop ----
  function aspectCrop(ratio){ if(ratio==='free'){ return; }
    var parts=ratio.split(':'),rw=parseFloat(parts[0]),rh=parseFloat(parts[1]);
    var iw=cfg.width||img.naturalWidth||1, ih=cfg.height||img.naturalHeight||1;
    var target=rw/rh, cur=iw/ih, w=1,h=1;
    if(cur>target){ w=target/cur; } else { h=cur/target; }
    ops.crop={x:(1-w)/2,y:(1-h)/2,w:w,h:h}; schedulePreview(); }
  Array.prototype.forEach.call(document.querySelectorAll('#pe-aspect [data-aspect]'),function(b){
    b.addEventListener('click',function(){snapshot();aspectCrop(b.getAttribute('data-aspect'));});});
  document.getElementById('pe-crop-clear').addEventListener('click',function(){snapshot();delete ops.crop;schedulePreview();});

  // ---- overlay: crop drag + brush paint ----
  function rel(ev){ var r=overlay.getBoundingClientRect();
    return {x:Math.min(1,Math.max(0,(ev.clientX-r.left)/r.width)),
            y:Math.min(1,Math.max(0,(ev.clientY-r.top)/r.height))}; }
  function octx(){ overlay.width=overlay.clientWidth; overlay.height=overlay.clientHeight; return overlay.getContext('2d'); }
  function paintStamps(){ var c=octx(); c.clearRect(0,0,overlay.width,overlay.height);
    function draw(list,col){ c.fillStyle=col; list.forEach(function(s){ c.beginPath();
      c.arc(s.cx*overlay.width,s.cy*overlay.height,s.r*Math.min(overlay.width,overlay.height),0,7); c.fill(); }); }
    draw(blurStamps,'rgba(91,140,255,.35)'); draw(eraseStamps,'rgba(255,80,80,.35)'); }

  var painting=false;
  overlay.addEventListener('pointerdown',function(ev){ overlay.setPointerCapture(ev.pointerId);
    var p=rel(ev);
    if(brushMode){ snapshot(); painting=true; addStamp(p); }
    else { snapshot(); cropDrag={x0:p.x,y0:p.y,x1:p.x,y1:p.y}; }
  });
  overlay.addEventListener('pointermove',function(ev){ var p=rel(ev);
    if(painting){ addStamp(p); }
    else if(cropDrag){ cropDrag.x1=p.x;cropDrag.y1=p.y; drawCropBox(); }
  });
  function endPointer(){ if(painting){painting=false; schedulePreview();}
    if(cropDrag){ commitCrop(); cropDrag=null; } }
  overlay.addEventListener('pointerup',endPointer);
  overlay.addEventListener('pointercancel',endPointer);
  function addStamp(p){ var r=brushSize/100;
    (brushMode==='eraser'?eraseStamps:blurStamps).push({cx:p.x,cy:p.y,r:r,strength:1}); paintStamps(); }
  function drawCropBox(){ var c=octx(); c.clearRect(0,0,overlay.width,overlay.height);
    var x=Math.min(cropDrag.x0,cropDrag.x1)*overlay.width, y=Math.min(cropDrag.y0,cropDrag.y1)*overlay.height,
        w=Math.abs(cropDrag.x1-cropDrag.x0)*overlay.width, h=Math.abs(cropDrag.y1-cropDrag.y0)*overlay.height;
    c.strokeStyle='#fff'; c.lineWidth=2; c.setLineDash([6,4]); c.strokeRect(x,y,w,h);
    c.fillStyle='rgba(0,0,0,.25)'; c.fillRect(0,0,overlay.width,y); c.fillRect(0,y+h,overlay.width,overlay.height-y-h);
    c.fillRect(0,y,x,h); c.fillRect(x+w,y,overlay.width-x-w,h); }
  function commitCrop(){ var w=Math.abs(cropDrag.x1-cropDrag.x0),h=Math.abs(cropDrag.y1-cropDrag.y0);
    if(w<0.03||h<0.03){ var c=octx(); c.clearRect(0,0,overlay.width,overlay.height); paintStamps(); return; }
    ops.crop={x:Math.min(cropDrag.x0,cropDrag.x1),y:Math.min(cropDrag.y0,cropDrag.y1),w:w,h:h};
    var c2=octx(); c2.clearRect(0,0,overlay.width,overlay.height); paintStamps(); schedulePreview(); }

  // ---- brush controls ----
  Array.prototype.forEach.call(document.querySelectorAll('[data-brush]'),function(b){
    b.addEventListener('click',function(){ brushMode=b.getAttribute('data-brush');
      Array.prototype.forEach.call(document.querySelectorAll('[data-brush]'),function(x){
        x.classList.toggle('is-on',x===b);});
      overlay.style.cursor=brushMode?'crosshair':'default'; });});
  var bsize=document.getElementById('pe-brush-size');
  bsize.addEventListener('input',function(){ brushSize=parseFloat(bsize.value);
    document.getElementById('pe-brush-size-v').textContent=bsize.value; });
  document.getElementById('pe-brush-clear').addEventListener('click',function(){snapshot();
    blurStamps=[];eraseStamps=[]; paintStamps(); schedulePreview();});

  // ---- enhance / reset / undo / apply ----
  document.getElementById('pe-enhance').addEventListener('click',function(){
    fetch(cfg.enhanceUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
      .then(function(r){return r.json();}).then(function(j){ if(j&&j.recipe&&j.recipe.steps){ snapshot();
        j.recipe.steps.forEach(function(s){ ops[s.op]=s.params; }); schedulePreview();
        flash('Enhanced — review & save'); }}).catch(function(){});
  });
  document.getElementById('pe-reset').addEventListener('click',function(){ snapshot();
    ops={}; blurStamps=[];eraseStamps=[];
    Array.prototype.forEach.call(document.querySelectorAll('input[type=range][data-op]'),function(el){
      el.value=el.getAttribute('data-default'); var l=document.getElementById(el.id+'-v'); if(l)l.textContent=el.value;});
    setFilter(''); paintStamps(); img.src=cfg.assetUrl; flash('Reset'); });
  document.getElementById('pe-undo').addEventListener('click',function(){ if(!history.length) return;
    var prev=JSON.parse(history.pop()); ops={}; blurStamps=[];eraseStamps=[];
    (prev.steps||[]).forEach(function(s){ if(s.op==='blur_brush'){blurStamps=s.params.stamps||[];}
      else if(s.op==='eraser'){eraseStamps=s.params.stamps||[];} else {ops[s.op]=s.params;} });
    paintStamps(); preview(); });
  document.getElementById('pe-apply').addEventListener('click',function(){
    fetch(cfg.applyUrl,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(serialise())}).then(function(r){return r.json();})
      .then(function(j){ if(j&&j.ok){ flash('Saved'); if(j.edited_url){ img.src=j.edited_url+'?t='+Date.now(); } }
        else { flash((j&&j.error)||'Save failed'); } }).catch(function(){flash('Save failed');});
  });
  Array.prototype.forEach.call(document.querySelectorAll('.pe-profile'),function(b){
    b.addEventListener('click',function(){ flash('Exporting…');
      fetch(cfg.profilePicUrl,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({preset:b.getAttribute('data-preset')})}).then(function(r){return r.json();})
        .then(function(j){ flash(j&&j.ok?'Profile picture saved to library':'Export failed'); }).catch(function(){flash('Export failed');}); });});

  function flash(msg){ saved.textContent=msg; }

  // Reflect a persisted recipe back onto the controls so reopening an edited
  // photo shows the right slider positions (best-effort; never throws).
  function restoreControls(){
    try{
      Array.prototype.forEach.call(document.querySelectorAll('input[type=range][data-op]'),function(el){
        var op=el.getAttribute('data-op'),param=el.getAttribute('data-param'),map=el.getAttribute('data-map');
        var p=ops[op]; if(!p||p[param]===undefined) return; var raw=p[param],v;
        if(map==='factorpct') v=(raw-1)*100; else if(map==='pct01') v=raw*100;
        else if(map==='div25') v=raw*25; else v=raw;
        el.value=v; var lab=document.getElementById(el.id+'-v'); if(lab) lab.textContent=Math.round(v);
      });
      if(ops.filter&&ops.filter.name){ filterInt.value=Math.round((ops.filter.intensity||1)*100);
        filterIntV.textContent=filterInt.value;
        Array.prototype.forEach.call(document.querySelectorAll('.pe-filter'),function(b){
          b.classList.toggle('is-on', b.getAttribute('data-filter')===ops.filter.name);}); }
      if(ops.duotone){ duoOn.checked=true; if(ops.duotone.shadow)duoLo.value=ops.duotone.shadow;
        if(ops.duotone.highlight)duoHi.value=ops.duotone.highlight; duoInt.value=Math.round((ops.duotone.amount||1)*100); }
      if(ops.shape_crop){ shapeSel.value=ops.shape_crop.shape||''; shapeF.value=Math.round((ops.shape_crop.feather||0)*100);
        shapeFV.textContent=shapeF.value; }
      if(ops.frame){ frOn.checked=true; if(ops.frame.colour)frCol.value=ops.frame.colour; frW.value=Math.round((ops.frame.width||0.04)*100); }
      if(ops.perspective){ pH.value=Math.round((ops.perspective.h||0)*100); pV.value=Math.round((ops.perspective.v||0)*100);
        document.getElementById('pe-persp-h-v').textContent=pH.value; document.getElementById('pe-persp-v-v').textContent=pV.value; }
      if(ops.flip){ document.getElementById(ops.flip.axis==='v'?'pe-flipv':'pe-fliph').classList.add('is-on'); }
    }catch(e){}
  }

  // Load any persisted recipe into the controls on open.
  if(cfg.recipe&&cfg.recipe.steps&&cfg.recipe.steps.length){
    cfg.recipe.steps.forEach(function(s){ if(s.op==='blur_brush'){blurStamps=s.params.stamps||[];}
      else if(s.op==='eraser'){eraseStamps=s.params.stamps||[];} else {ops[s.op]=s.params;} });
    paintStamps(); restoreControls();
  }
})();
"""
