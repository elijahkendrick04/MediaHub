"""web.data_hub_ui — HTML for the data hub grid + index (roadmap 1.13).

Pure rendering helpers kept out of the monolith for testability. Everything is
server-rendered and escaped (``markupsafe.escape``); sort/filter/freeze are plain
links + CSS (no inline JS), so the grid is robust under the app's CSP. The route
layer wraps these with ``_layout``.
"""

from __future__ import annotations

from flask import url_for
from markupsafe import escape as _h

from mediahub.data_hub.models import DataCell, DataTable, Provenance
from mediahub.data_hub.view import arrange

_GRID_CSS = """
<style>
.dh-wrap{overflow:auto;border:1px solid var(--line,#26314d);border-radius:10px;max-height:70vh}
.dh-grid{border-collapse:separate;border-spacing:0;width:100%;font-size:13px}
.dh-grid th,.dh-grid td{padding:8px 10px;border-bottom:1px solid var(--line,#26314d);
  white-space:nowrap;text-align:left;vertical-align:top}
.dh-grid thead th{position:sticky;top:0;background:var(--panel,#141c2f);z-index:2;
  font-weight:600}
.dh-grid th.dh-frozen,.dh-grid td.dh-frozen{position:sticky;left:0;
  background:var(--panel,#141c2f);z-index:1}
.dh-grid thead th.dh-frozen{z-index:3}
.dh-grid a.dh-sort{color:inherit;text-decoration:none}
.dh-grid a.dh-sort:hover{text-decoration:underline}
.dh-flag{background:rgba(220,140,40,.16)}
.dh-flag .dh-mark{color:#e0962a;font-weight:700;margin-right:4px}
.dh-prov{display:inline-block;font-size:10px;line-height:1;padding:2px 5px;border-radius:6px;
  margin-left:6px;opacity:.8;border:1px solid var(--line,#26314d)}
.dh-prov.parsed{color:#7fc9ff}.dh-prov.imported{color:#9be29b}.dh-prov.hand{color:#d9c27a}
.dh-prov.derived{color:#c9a6ff}.dh-prov.connector{color:#76d4d0}.dh-prov.registry{color:#aab4cc}
.dh-toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:10px 0}
.dh-meta{color:var(--dim,#8a94ad);font-size:12px}
.dh-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0}
</style>
"""


def _prov_badge(cell: DataCell, *, first: bool) -> str:
    """A tiny provenance badge — shown once per row on the first column."""
    if not first:
        return ""
    cls = Provenance.normalise(cell.provenance)
    label = Provenance.label(cls)
    return (
        f'<span class="dh-prov {_h(cls)}" role="img" '
        f'aria-label="Where this came from: {_h(label)}" title="{_h(label)}">{_h(label)}</span>'
    )


def _sort_link(
    table_id: str, key: str, title: str, *, sort: str, direction: str, query: str
) -> str:
    next_dir = "desc" if (sort == key and direction == "asc") else "asc"
    arrow = ""
    if sort == key:
        arrow = " ▲" if direction == "asc" else " ▼"
    href = url_for("data_hub_table", table_id=table_id, sort=key, dir=next_dir, q=query or None)
    return f'<a class="dh-sort" href="{href}">{_h(title)}{arrow}</a>'


def render_grid(
    table: DataTable,
    *,
    sort: str = "",
    direction: str = "asc",
    query: str = "",
    max_rows: int = 500,
) -> str:
    """Render a :class:`DataTable` as a server-sorted/filtered HTML grid."""
    rows = arrange(table, sort=sort, direction=direction, query=query)
    shown = rows[:max_rows]

    head_cells = []
    for col in table.columns:
        frozen = " dh-frozen" if col.frozen else ""
        link = _sort_link(
            table.table_id, col.key, col.title, sort=sort, direction=direction, query=query
        )
        head_cells.append(f'<th scope="col" class="dh-col{frozen}">{link}</th>')
    thead = "<thead><tr>" + "".join(head_cells) + "</tr></thead>"

    body_rows = []
    for row in shown:
        tds = []
        for i, col in enumerate(table.columns):
            cell = row.get(col.key)
            cell = cell if isinstance(cell, DataCell) else DataCell.from_dict(cell)
            frozen = " dh-frozen" if col.frozen else ""
            flag = " dh-flag" if cell.flagged else ""
            mark = (
                '<span class="dh-mark" role="img" aria-label="Needs review" '
                'title="Needs review">&#9888;</span>'
                if cell.flagged
                else ""
            )
            title_attr = f' title="{_h(cell.note)}"' if cell.note else ""
            # Flagged cells are announced to screen readers with the reason.
            cell_aria = (
                f' aria-label="Needs review: {_h(cell.note)}"' if cell.flagged and cell.note else ""
            )
            badge = _prov_badge(cell, first=(i == 0))
            tds.append(
                f'<td class="dh-cell{frozen}{flag}"{title_attr}{cell_aria}>{mark}{_h(cell.display)}{badge}</td>'
            )
        body_rows.append("<tr>" + "".join(tds) + "</tr>")
    tbody = "<tbody>" + "".join(body_rows) + "</tbody>"

    note = ""
    if len(rows) > max_rows:
        note = f'<p class="dh-meta">Showing first {max_rows} of {len(rows)} rows.</p>'
    flag_note = f" {table.flagged_count} cell(s) flagged for review." if table.flagged_count else ""
    caption = (
        f'<caption class="dh-sr">{_h(table.title)} — {table.row_count} rows, '
        f"{len(table.columns)} columns.{flag_note}</caption>"
    )
    grid = f'<div class="dh-wrap"><table class="dh-grid">{caption}{thead}{tbody}</table></div>'
    return _GRID_CSS + grid + note


def render_toolbar(table: DataTable, *, query: str = "") -> str:
    """Filter box + export buttons for a table page."""
    filter_form = (
        f'<form method="get" action="{url_for("data_hub_table", table_id=table.table_id)}" '
        'style="display:flex;gap:6px">'
        f'<input type="text" name="q" value="{_h(query)}" placeholder="Filter rows…" '
        'aria-label="Filter rows in this table" style="padding:6px 8px;min-width:180px">'
        '<button class="btn secondary" type="submit">Filter</button>'
        "</form>"
    )
    csv_url = url_for("data_hub_export", table_id=table.table_id, fmt="csv")
    xlsx_url = url_for("data_hub_export", table_id=table.table_id, fmt="xlsx")
    exports = (
        f'<a class="btn secondary" href="{csv_url}">Export CSV</a>'
        f'<a class="btn secondary" href="{xlsx_url}">Export Excel</a>'
    )
    meta = (
        f'<span class="dh-meta">{table.row_count} rows · {len(table.columns)} columns'
        f"{' · ' + str(table.flagged_count) + ' flagged' if table.flagged_count else ''}</span>"
    )
    return f'<div class="dh-toolbar">{filter_form}{exports}{meta}</div>'


def render_index(
    *,
    canonical: list[dict],
    org_tables: list[dict],
    runs: list[dict],
    jobs: list[dict],
    connectors: list[dict],
) -> str:
    """The data-hub landing page body."""

    def _table_card(t: dict) -> str:
        href = url_for("data_hub_table", table_id=t["table_id"])
        flagged = (
            f' · <span style="color:#e0962a">{t["n_flagged"]} flagged</span>'
            if t.get("n_flagged")
            else ""
        )
        return (
            f'<a class="card" href="{href}" style="display:block;text-decoration:none">'
            f'<h3 style="margin:0 0 4px">{_h(t["title"])}</h3>'
            f'<p class="dim" style="margin:0;font-size:12px">{t["n_rows"]} rows · '
            f"{t['n_columns']} columns{flagged}</p></a>"
        )

    canon_html = "".join(_table_card(t) for t in canonical) or '<p class="dim">No data yet.</p>'
    org_html = (
        "".join(_table_card(t) for t in org_tables) or '<p class="dim">No club tables yet.</p>'
    )

    # Bulk launcher: pick a recent run, make a certificate for every PB swimmer.
    run_opts = "".join(
        f'<option value="{_h(r["run_id"])}">{_h(r.get("meet") or r["run_id"])}</option>'
        for r in runs
    )
    bulk_card = (
        '<div class="card"><h3 style="margin-top:0">Bulk generate</h3>'
        '<p class="dim" style="font-size:13px">Make one piece of content for every '
        "matching swimmer in a meet &mdash; each one queued for your review.</p>"
    )
    if run_opts:
        bulk_card += (
            f'<form method="post" action="{url_for("api_data_hub_bulk")}" '
            'style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
            f'<select name="run_id" style="padding:6px">{run_opts}</select>'
            '<select name="format_slug" style="padding:6px">'
            '<option value="certificate">Certificate</option></select>'
            '<label class="dim" style="font-size:12px"><input type="checkbox" name="pb_only" '
            'value="1" checked> PB swimmers only</label>'
            '<button class="btn" type="submit">Generate &amp; queue</button>'
            "</form>"
        )
    else:
        bulk_card += '<p class="dim">Process a meet first, then bulk-generate from it.</p>'
    bulk_card += "</div>"

    jobs_html = ""
    if jobs:
        rows = "".join(
            f"<tr><td>{_h(j['title'])}</td><td>{_h(j['status'])}</td>"
            f"<td>{j['n_queued']}/{j['n_total']}</td><td>{j['pct']}%</td></tr>"
            for j in jobs[:10]
        )
        jobs_html = (
            '<div class="card"><h3 style="margin-top:0">Recent bulk jobs</h3>'
            '<table style="width:100%;font-size:13px"><thead><tr><th align="left">Job</th>'
            "<th>Status</th><th>Queued</th><th>Done</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
        )

    new_table_card = (
        '<div class="card"><h3 style="margin-top:0">Add a table</h3>'
        '<p class="dim" style="font-size:13px">Import a spreadsheet (CSV or Excel). '
        "Anything that doesn&rsquo;t fit is flagged for review, never guessed.</p>"
        f'<form method="post" action="{url_for("api_data_hub_import")}" '
        'enctype="multipart/form-data" style="display:flex;gap:8px;align-items:center">'
        '<input type="file" name="file" accept=".csv,.xlsx,.tsv" required>'
        '<button class="btn" type="submit">Import</button></form>'
        "</div>"
    )

    return (
        '<section class="mh-hero"><span class="mh-hero-eyebrow">Data hub</span>'
        '<h1 style="margin:.2em 0">Your club&rsquo;s data, as tables</h1>'
        '<p class="lede">Browse what MediaHub knows, keep your own tables, and make '
        "content in bulk &mdash; every value shows where it came from.</p></section>"
        "<h2>From your meets</h2>"
        '<div class="mh-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px">'
        f"{canon_html}</div>"
        '<h2 style="margin-top:24px">Your tables</h2>'
        '<div class="mh-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px">'
        f"{org_html}</div>"
        f'<h2 style="margin-top:24px">Tools</h2>{new_table_card}{bulk_card}{jobs_html}'
    )


__all__ = ["render_grid", "render_toolbar", "render_index"]
