"""Regression tests for deep-review batch 6 (injection hardening).

  #113 safeguarding.consent.export_csv neutralises CSV formula injection
  #117 data_hub.portability CSV/XLSX export neutralises formula injection
  #118 interop.svg_import strips url(http…) from a <style> ELEMENT, not just attrs
"""

from __future__ import annotations

import csv
import io

from mediahub.data_hub.models import DataCell, DataColumn, DataTable
from mediahub.data_hub.portability import _csv_safe as portability_csv_safe
from mediahub.data_hub.portability import export_csv as portability_export_csv
from mediahub.interop.svg_import import sanitize_svg
from mediahub.safeguarding.consent import _csv_safe as consent_csv_safe


def test_csv_safe_prefixes_formula_leaders():
    for fn in (consent_csv_safe, portability_csv_safe):
        assert fn("=SUM(A1)") == "'=SUM(A1)"
        assert fn("+1") == "'+1"
        assert fn("-1") == "'-1"
        assert fn("@cmd") == "'@cmd"
        assert fn("\ttab") == "'\ttab"
        # Ordinary content is untouched.
        assert fn("Jamie Rivers") == "Jamie Rivers"
        assert fn("30.91") == "30.91"
        assert fn("") == ""
        assert fn(None) == ""


def test_portability_export_csv_neutralises_injection():
    table = DataTable(
        table_id="t1",
        title="T",
        columns=[DataColumn(key="name", title="Name")],
        rows=[{"name": DataCell(value="=HYPERLINK(0)", display="=HYPERLINK(0)")}],
    )
    out = portability_export_csv(table)
    data_cell = list(csv.reader(io.StringIO(out)))[1][0]
    assert data_cell.startswith("'"), f"formula cell not neutralised: {data_cell!r}"
    assert data_cell == "'=HYPERLINK(0)"


def test_svg_style_element_strips_http_url():
    # url(http…) inside a <style> BLOCK (not just a style attribute) is a
    # tracking/exfil vector when the SVG renders inline — it must be scrubbed.
    evil = (
        b"<svg xmlns='http://www.w3.org/2000/svg'>"
        b"<style>rect{fill:url(https://evil.example/track.png)}</style>"
        b"<rect width='10' height='10'/></svg>"
    )
    out = sanitize_svg(evil)
    assert b"evil.example" not in out
    assert b"https://" not in out
