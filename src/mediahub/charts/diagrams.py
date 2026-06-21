"""charts.diagrams — data-driven, brand-styled diagram formats (roadmap 1.11).

The "diagram types" half of 1.11: committee **org charts**, season **timelines**,
athlete **journeys**, and training **flows** — rendered the same way as the stat
charts (deterministic, brand-token styled SVG, self-hosted fonts) but from *roster
and fixture* data rather than results. A diagram is structure, not statistics: nodes
and connectors, laid out by tidy deterministic maths — never an LLM drawing boxes.

Like the chart builders, each ``*_from_*`` helper turns structured input (a roster,
a fixture list, a career history) into a :class:`DiagramSpec`; the renderer paints
it on brand. Same spec + same role vars → byte-identical SVG.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import fonts as _fonts
from .palette import ChartColours, _mix, role_vars_from_palette
from .render import _Box, _clip, _esc, _fit_size, _footer, _header, _rect, _svg_open, _text

DIAGRAM_KINDS: tuple[str, ...] = ("org_chart", "timeline", "journey", "flow")

# Chrome proportions — kept in step with charts.render so a diagram sits beside a
# chart without a visual seam.
_PAD = 0.055
_TITLE_H = 0.085
_SUB_H = 0.045
_FOOT_H = 0.045


@dataclass(frozen=True)
class DiagramNode:
    """One node: a committee role, a fixture, a career milestone, a process step."""

    id: str
    label: str  # the headline (a person, a meet, a stage)
    sublabel: str = ""  # the supporting line (a role, a date, a detail)
    parent: str = ""  # parent node id (org_chart hierarchy)

    def to_dict(self) -> dict:
        d = {"id": self.id, "label": self.label}
        if self.sublabel:
            d["sublabel"] = self.sublabel
        if self.parent:
            d["parent"] = self.parent
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Optional["DiagramNode"]:
        if not isinstance(data, dict) or not str(data.get("id", "")).strip():
            return None
        return cls(
            id=str(data["id"]).strip(),
            label=str(data.get("label", "")).strip(),
            sublabel=str(data.get("sublabel", "")).strip(),
            parent=str(data.get("parent", "")).strip(),
        )


@dataclass(frozen=True)
class DiagramSpec:
    """A render-ready diagram. Plain data; round-trips through JSON."""

    kind: str  # one of DIAGRAM_KINDS
    title: str = ""
    subtitle: str = ""
    nodes: tuple[DiagramNode, ...] = ()
    edges: tuple[tuple[str, str], ...] = ()  # (from_id, to_id) for flow
    width: int = 1080
    height: int = 1080
    source_note: str = ""
    footnote: str = ""
    chart_id: str = ""
    meta: dict = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.nodes

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "subtitle": self.subtitle,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [list(e) for e in self.edges],
            "width": self.width,
            "height": self.height,
            "source_note": self.source_note,
            "footnote": self.footnote,
            "chart_id": self.chart_id,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Optional["DiagramSpec"]:
        if not isinstance(data, dict):
            return None
        kind = str(data.get("kind", "")).strip().lower()
        if kind not in DIAGRAM_KINDS:
            return None
        nodes = tuple(
            n for n in (DiagramNode.from_dict(x) for x in data.get("nodes", [])) if n is not None
        )
        edges = tuple(
            (str(e[0]), str(e[1]))
            for e in data.get("edges", [])
            if isinstance(e, (list, tuple)) and len(e) == 2
        )
        return cls(
            kind=kind,
            title=str(data.get("title", "")).strip(),
            subtitle=str(data.get("subtitle", "")).strip(),
            nodes=nodes,
            edges=edges,
            width=int(data.get("width", 1080) or 1080),
            height=int(data.get("height", 1080) or 1080),
            source_note=str(data.get("source_note", "")).strip(),
            footnote=str(data.get("footnote", "")).strip(),
            chart_id=str(data.get("chart_id", "")).strip(),
            meta=dict(data.get("meta", {})) if isinstance(data.get("meta"), dict) else {},
        )


# --------------------------------------------------------------------------- #
# builders — structured data → DiagramSpec
# --------------------------------------------------------------------------- #
def org_chart_from_roster(members, *, title: str = "Committee", subtitle: str = "") -> Optional[DiagramSpec]:
    """Committee/coaching org chart from a roster of ``{name, role, reports_to}``."""
    nodes: list[DiagramNode] = []
    name_to_id: dict[str, str] = {}
    for i, m in enumerate(members or []):
        name = str(_get(m, "name") or "").strip()
        if not name:
            continue
        nid = str(_get(m, "id") or f"n{i}").strip()
        name_to_id[name.lower()] = nid
        nodes.append(DiagramNode(id=nid, label=name, sublabel=str(_get(m, "role") or "").strip()))
    if not nodes:
        return None
    # Resolve reports_to (a name or id) into parent ids.
    resolved: list[DiagramNode] = []
    id_set = {n.id for n in nodes}
    for n, m in zip(nodes, [m for m in members if str(_get(m, "name") or "").strip()]):
        rep = str(_get(m, "reports_to") or _get(m, "parent") or "").strip()
        parent = rep if rep in id_set else name_to_id.get(rep.lower(), "")
        resolved.append(DiagramNode(id=n.id, label=n.label, sublabel=n.sublabel, parent=parent))
    return DiagramSpec(
        kind="org_chart", title=title, subtitle=subtitle, nodes=tuple(resolved),
        source_note="Source: club roster", chart_id="org_chart",
    )


def season_timeline_from_meets(meets, *, title: str = "Season timeline", subtitle: str = "") -> Optional[DiagramSpec]:
    """Horizontal season timeline from a list of ``{date, name}`` fixtures/meets."""
    items = []
    for i, mt in enumerate(meets or []):
        label = str(_get(mt, "name") or _get(mt, "label") or "").strip()
        if not label:
            continue
        date = str(_get(mt, "date") or _get(mt, "start_date") or "").strip()
        items.append((date, label, i))
    if not items:
        return None
    items.sort(key=lambda t: (t[0] or "~", t[2]))  # by date, stable on ties
    nodes = tuple(
        DiagramNode(id=f"e{i}", label=label, sublabel=_pretty_date(date))
        for i, (date, label, _) in enumerate(items)
    )
    return DiagramSpec(
        kind="timeline", title=title, subtitle=subtitle, nodes=nodes,
        source_note="Source: club fixtures", chart_id="season_timeline",
    )


def athlete_journey(swimmer_name: str, milestones, *, subtitle: str = "") -> Optional[DiagramSpec]:
    """A swimmer's career journey from ordered ``{label, detail}`` milestones."""
    nodes = []
    for i, ms in enumerate(milestones or []):
        label = str(_get(ms, "label") or "").strip()
        if not label:
            continue
        nodes.append(DiagramNode(id=f"m{i}", label=label, sublabel=str(_get(ms, "detail") or "").strip()))
    if not nodes:
        return None
    return DiagramSpec(
        kind="journey", title=swimmer_name.strip() or "Journey", subtitle=subtitle or "Career milestones",
        nodes=tuple(nodes), source_note="Source: club history", chart_id="athlete_journey",
    )


def training_flow(steps, *, title: str = "Training week", subtitle: str = "") -> Optional[DiagramSpec]:
    """A linear process flow from ordered ``{label, detail}`` steps."""
    nodes = []
    for i, st in enumerate(steps or []):
        label = str(_get(st, "label") or "").strip()
        if not label:
            continue
        nodes.append(DiagramNode(id=f"s{i}", label=label, sublabel=str(_get(st, "detail") or "").strip()))
    if not nodes:
        return None
    edges = tuple((f"s{i}", f"s{i + 1}") for i in range(len(nodes) - 1))
    return DiagramSpec(
        kind="flow", title=title, subtitle=subtitle, nodes=nodes, edges=edges, chart_id="training_flow",
    )


# --------------------------------------------------------------------------- #
# renderer
# --------------------------------------------------------------------------- #
def render_diagram_svg(
    spec: DiagramSpec,
    role_vars: Optional[dict[str, str]] = None,
    *,
    palette: Optional[dict] = None,
    brand_kit=None,
    embed_fonts: bool = True,
) -> str:
    """Render ``spec`` to a complete, brand-styled SVG string."""
    if role_vars is None:
        role_vars = role_vars_from_palette(palette, brand_kit)
    c = ChartColours(role_vars)
    w, h = int(spec.width), int(spec.height)
    short = max(1, min(w, h))
    pad = round(_PAD * short)

    y = pad
    if spec.title:
        y += round(_TITLE_H * short)
    if spec.subtitle:
        y += round(_SUB_H * short)
    plot_top = y + (round(0.02 * short) if (spec.title or spec.subtitle) else 0)
    foot_h = round(_FOOT_H * short) if (spec.source_note or spec.footnote) else 0
    box = _Box(pad, plot_top, w - pad, h - pad - foot_h)

    frag = [_svg_open(w, h, embed_fonts), _rect(0, 0, w, h, c.ground)]
    frag.append(_header(spec, c, x=pad, top=pad, width=w - 2 * pad, short=short))
    if foot_h:
        frag.append(_footer(spec, c, x=pad, bottom=h - pad, width=w - 2 * pad, short=short))
    if spec.is_empty():
        frag.append(_text((box.left + box.right) / 2, (box.top + box.bottom) / 2,
                          "Nothing to diagram yet", round(0.03 * short), c.muted,
                          family=_fonts.body_stack(), anchor="middle"))
    elif spec.kind == "org_chart":
        frag.append(_render_org_chart(spec, c, box, short))
    elif spec.kind == "timeline":
        frag.append(_render_timeline(spec, c, box, short))
    elif spec.kind == "journey":
        frag.append(_render_journey(spec, c, box, short))
    elif spec.kind == "flow":
        frag.append(_render_flow(spec, c, box, short))
    frag.append("</svg>")
    return "".join(frag)


def _render_org_chart(spec: DiagramSpec, c: ChartColours, box: _Box, short: int) -> str:
    depth, xpos, children, roots, n_leaves = _layout_tree(spec.nodes)
    if not depth:
        return ""
    by_id = {n.id: n for n in spec.nodes}
    max_d = max(depth.values())
    leaf_span = max(1, n_leaves - 1)
    node_w = min(box.w / max(1, n_leaves), box.w * 0.26)
    node_h = round(0.07 * short)
    row_gap = (box.h - node_h) / max(1, max_d) if max_d else 0

    def cx(nid: str) -> float:
        return box.left + node_w / 2 + (xpos[nid] / leaf_span) * (box.w - node_w)

    def cy(nid: str) -> float:
        return box.top + depth[nid] * row_gap + node_h / 2

    out: list[str] = []
    # connectors first (under the boxes), elbow style
    for nid in depth:
        for kid in children.get(nid, []):
            x1, y1 = cx(nid), cy(nid) + node_h / 2
            x2, y2 = cx(kid), cy(kid) - node_h / 2
            mid = (y1 + y2) / 2
            out.append(
                f'<path d="M{x1:.1f},{y1:.1f} L{x1:.1f},{mid:.1f} L{x2:.1f},{mid:.1f} '
                f'L{x2:.1f},{y2:.1f}" fill="none" stroke="{c.grid}" stroke-width="2"/>'
            )
    for nid in depth:
        n = by_id[nid]
        is_root = not n.parent
        _node_box(out, cx(nid), cy(nid), node_w, node_h, c, short, n.label, n.sublabel, accent=is_root)
    return "".join(out)


def _render_timeline(spec: DiagramSpec, c: ChartColours, box: _Box, short: int) -> str:
    nodes = list(spec.nodes)
    n = len(nodes)
    midy = (box.top + box.bottom) / 2
    # Inset the end stations by half a card so the first/last labels never clip.
    card_w = box.w * 0.22
    inset = card_w / 2 + round(0.01 * short)
    usable_l, usable_r = box.left + inset, box.right - inset
    step = (usable_r - usable_l) / max(1, n - 1) if n > 1 else 0
    if n > 1:
        card_w = min(card_w, step * 0.92)
    dot = max(5, round(0.012 * short))

    def _x(i: int) -> float:
        return usable_l + (i * step if n > 1 else (usable_r - usable_l) / 2)

    out = [f'<line x1="{_x(0):.1f}" y1="{midy:.1f}" x2="{_x(n - 1):.1f}" y2="{midy:.1f}" stroke="{c.grid}" stroke-width="3"/>']
    for i, node in enumerate(nodes):
        x = _x(i)
        up = (i % 2 == 0)
        out.append(f'<circle cx="{x:.1f}" cy="{midy:.1f}" r="{dot}" fill="{c.accent}"/>')
        stalk = round(0.10 * short)
        ey = midy - stalk if up else midy + stalk
        out.append(f'<line x1="{x:.1f}" y1="{midy:.1f}" x2="{x:.1f}" y2="{ey:.1f}" stroke="{c.grid}" stroke-width="2"/>')
        ch = round(0.075 * short)
        cyb = ey - ch if up else ey
        _node_box(out, x, cyb + ch / 2, card_w, ch, c, short, node.label, node.sublabel, accent=False)
    return "".join(out)


def _render_journey(spec: DiagramSpec, c: ChartColours, box: _Box, short: int) -> str:
    nodes = list(spec.nodes)
    n = len(nodes)
    row_h = box.h / max(1, n)
    railx = box.left + box.w * 0.10
    dot = max(6, round(0.013 * short))
    out: list[str] = []
    out.append(f'<line x1="{railx:.1f}" y1="{box.top:.1f}" x2="{railx:.1f}" y2="{box.bottom:.1f}" stroke="{c.grid}" stroke-width="3"/>')
    for i, node in enumerate(nodes):
        cy = box.top + i * row_h + row_h / 2
        out.append(f'<circle cx="{railx:.1f}" cy="{cy:.1f}" r="{dot}" fill="{c.accent}"/>')
        tx = railx + round(0.04 * short)
        title_size = _fit_size(node.label, round(0.034 * short), box.right - tx, char_factor=0.5)
        out.append(_text(tx, cy - round(0.004 * short), _esc(node.label), title_size, c.ink,
                         family=_fonts.display_stack(), weight="400"))
        if node.sublabel:
            out.append(_text(tx, cy + round(0.030 * short), _esc(_clip(node.sublabel, 60)),
                             round(0.022 * short), c.muted, family=_fonts.body_stack()))
    return "".join(out)


def _render_flow(spec: DiagramSpec, c: ChartColours, box: _Box, short: int) -> str:
    nodes = list(spec.nodes)
    n = len(nodes)
    per_row = max(1, min(n, int(box.w // (box.w * 0.24)) or 1, 4))
    cols = per_row
    rows = (n + cols - 1) // cols
    gap = round(0.03 * short)
    bw = (box.w - (cols - 1) * gap) / cols
    bh = round(0.10 * short)
    v_gap = round(0.05 * short)
    block_h = rows * bh + (rows - 1) * v_gap
    y0 = box.top + max(0.0, (box.h - block_h) / 2)  # centre the block vertically
    centres: dict[str, tuple[float, float]] = {}
    positions: list[tuple[float, float]] = []
    for i, node in enumerate(nodes):
        r, col = divmod(i, cols)
        if r % 2 == 1:  # serpentine so the flow reads left→right then right→left
            col = cols - 1 - col
        x = box.left + col * (bw + gap)
        yb = y0 + r * (bh + v_gap)
        cxn, cyn = x + bw / 2, yb + bh / 2
        centres[node.id] = (cxn, cyn)
        positions.append((cxn, cyn))
    out: list[str] = []
    # Connectors first so they tuck *under* the boxes (clean joins, no through-lines).
    for a, b in spec.edges:
        if a in centres and b in centres:
            (x1, y1), (x2, y2) = centres[a], centres[b]
            out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{c.grid}" stroke-width="2"/>')
    for i, node in enumerate(nodes):
        cxn, cyn = positions[i]
        _node_box(out, cxn, cyn, bw, bh, c, short, node.label, node.sublabel, accent=(i == 0))
    return "".join(out)


def _node_box(out: list[str], cx: float, cy: float, w: float, h: float, c: ChartColours,
              short: int, label: str, sublabel: str, *, accent: bool) -> None:
    x, y = cx - w / 2, cy - h / 2
    fill = c.accent if accent else _mix(c.ground, c.ink, 0.08)
    ink = c.on_accent if accent else c.ink
    sub_ink = _mix(ink, fill, 0.35)
    out.append(_rect(x, y, w, h, fill, rx=round(0.012 * short)))
    out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{round(0.012*short)}" fill="none" stroke="{c.grid if not accent else fill}" stroke-width="1.5"/>')
    title_size = _fit_size(label, round(0.026 * short), w * 0.9, char_factor=0.55)
    out.append(_text(cx, cy + (0 if not sublabel else -round(0.006 * short)) + title_size * 0.18,
                     _esc(_clip(label, 26)), title_size, ink, family=_fonts.body_stack(),
                     weight="700", anchor="middle"))
    if sublabel:
        out.append(_text(cx, cy + round(0.026 * short), _esc(_clip(sublabel, 30)),
                         round(0.018 * short), sub_ink, family=_fonts.body_stack(), anchor="middle"))


def _layout_tree(nodes):
    """Tidy first-pass layout: leaves get sequential x slots; a parent sits over the
    mean of its children. Deterministic. Returns (depth, x, children, roots, n_leaves)."""
    by_id = {n.id: n for n in nodes}
    children: dict[str, list[str]] = {n.id: [] for n in nodes}
    roots: list[str] = []
    for n in nodes:
        if n.parent and n.parent in by_id and n.parent != n.id:
            children[n.parent].append(n.id)
        else:
            roots.append(n.id)
    depth: dict[str, int] = {}
    x: dict[str, float] = {}
    counter = [0]
    visiting: set[str] = set()

    def visit(nid: str, d: int) -> None:
        if nid in visiting:
            return  # guard against a malformed cycle
        visiting.add(nid)
        depth[nid] = d
        kids = children.get(nid, [])
        if not kids:
            x[nid] = float(counter[0])
            counter[0] += 1
        else:
            for k in kids:
                visit(k, d + 1)
            xs = [x[k] for k in kids if k in x]
            x[nid] = sum(xs) / len(xs) if xs else float(counter[0])

    for r in roots:
        visit(r, 0)
    return depth, x, children, roots, counter[0]


def _get(obj, name: str):
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _pretty_date(iso: str) -> str:
    s = (iso or "").strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        try:
            return f"{int(s[8:10])} {months[int(s[5:7]) - 1]} {s[0:4]}"
        except (ValueError, IndexError):
            return s
    return s


__all__ = [
    "DIAGRAM_KINDS",
    "DiagramNode",
    "DiagramSpec",
    "render_diagram_svg",
    "org_chart_from_roster",
    "season_timeline_from_meets",
    "athlete_journey",
    "training_flow",
]
