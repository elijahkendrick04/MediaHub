"""Deterministic rich-text formatting model (roadmap 1.9).

Character/paragraph CSS, list/link/run emission, and the editor utilities
(uppercase, find & replace, copy-style, auto-link, the honest spellcheck seam).
The throughline is XSS safety: user text is always escaped and every styled
value is validated, so a caption can never inject CSS or markup.
"""
from __future__ import annotations

from mediahub.typography import formatting as fmt


# --------------------------------------------------------------------------- #
# TextFormat -> CSS
# --------------------------------------------------------------------------- #
class TestFormatCss:
    def test_role_colour_resolves_to_var(self):
        assert "color:var(--mh-accent)" in fmt.TextFormat(colour="accent").css()

    def test_hex_colour_passes(self):
        assert "color:#1a2b3c" in fmt.TextFormat(colour="#1a2b3c").css()

    def test_invalid_colour_dropped(self):
        # No injection: a bogus colour value never reaches the style string.
        assert "color" not in fmt.TextFormat(colour="red;}/*x*/").css()

    def test_weight_clamped(self):
        assert "font-weight:900" in fmt.TextFormat(weight=5000).css()
        assert "font-weight:100" in fmt.TextFormat(weight=-3).css()

    def test_alignment_validated(self):
        assert "text-align:center" in fmt.TextFormat(align="center").css()
        assert "text-align" not in fmt.TextFormat(align="diagonal").css()

    def test_decorations_combine(self):
        css = fmt.TextFormat(underline=True, strikethrough=True).css()
        assert "text-decoration:underline line-through" in css

    def test_decimal_size_and_clamp(self):
        assert "font-size:17.5px" in fmt.TextFormat(size_px=17.5).css()
        assert "font-size:800px" in fmt.TextFormat(size_px=99999).css()

    def test_line_height_and_letter_spacing(self):
        css = fmt.TextFormat(line_height=1.25, letter_spacing_em=0.04).css()
        assert "line-height:1.25" in css and "letter-spacing:0.04em" in css

    def test_uppercase_and_italic(self):
        css = fmt.TextFormat(uppercase=True, style="italic").css()
        assert "text-transform:uppercase" in css and "font-style:italic" in css

    def test_gradient_clips_to_text(self):
        css = fmt.TextFormat(gradient=("accent", "#ffffff")).css()
        assert "background-clip:text" in css and "color:transparent" in css

    def test_gradient_with_bad_stop_is_dropped(self):
        assert fmt.TextFormat(gradient=("accent", "javascript:alert(1)")).css() == ""

    def test_copy_style_clones(self):
        src = fmt.TextFormat(colour="accent", weight=700, uppercase=True)
        assert fmt.copy_style(src) == src


# --------------------------------------------------------------------------- #
# Runs / lists / links (XSS-safe)
# --------------------------------------------------------------------------- #
class TestEmission:
    def test_plain_run_no_span(self):
        assert fmt.Run("Hello").html() == "Hello"

    def test_formatted_run_wraps_span(self):
        out = fmt.Run("Hi", fmt.TextFormat(colour="accent")).html()
        assert out.startswith("<span style=") and "Hi" in out

    def test_run_escapes_text(self):
        assert "&lt;script&gt;" in fmt.Run("<script>").html()

    def test_link_run_is_safe(self):
        out = fmt.Run("site", href="https://example.com/x").html()
        assert 'href="https://example.com/x"' in out and 'rel="noopener noreferrer nofollow"' in out

    def test_non_http_href_ignored(self):
        out = fmt.Run("x", href="javascript:alert(1)").html()
        assert "<a" not in out

    def test_render_list_markers(self):
        ol = fmt.render_list(["a", "b"], ordered=True, marker="lower-roman")
        assert ol.startswith("<ol") and "list-style-type:lower-roman" in ol
        ul = fmt.render_list(["a"], ordered=False, marker="square")
        assert "list-style-type:square" in ul

    def test_render_list_dash_marker(self):
        out = fmt.render_list(["x"], marker="dash")
        assert "&#8211;" in out and "<li>" in out

    def test_render_list_invalid_marker_defaults(self):
        out = fmt.render_list(["x"], ordered=True, marker="emoji")
        assert "list-style-type:decimal" in out

    def test_render_list_escapes_items(self):
        assert "&lt;b&gt;" in fmt.render_list(["<b>"], ordered=True)

    def test_auto_link_escapes_then_links(self):
        out = fmt.auto_link("see https://x.io and <script>")
        assert '<a href="https://x.io"' in out and "&lt;script&gt;" in out


# --------------------------------------------------------------------------- #
# Editor utilities
# --------------------------------------------------------------------------- #
class TestUtilities:
    def test_uppercase(self):
        assert fmt.to_uppercase("gold medal") == "GOLD MEDAL"

    def test_find_replace_literal_and_count(self):
        new, n = fmt.find_replace("a.b.c", ".", "-")
        assert new == "a-b-c" and n == 2  # '.' treated literally, not regex

    def test_find_replace_case_insensitive(self):
        new, n = fmt.find_replace("PB pb Pb", "pb", "best", case_sensitive=False)
        assert n == 3 and new == "best best best"

    def test_find_replace_whole_word(self):
        new, n = fmt.find_replace("cat category", "cat", "dog", whole_word=True)
        assert new == "dog category" and n == 1

    def test_find_replace_empty_find(self):
        assert fmt.find_replace("x", "", "y") == ("x", 0)

    def test_spellcheck_honest_without_dictionary(self):
        available, miss = fmt.spellcheck("teh quik")
        assert available is False and miss == []

    def test_spellcheck_with_dictionary_flags_unknown(self):
        available, miss = fmt.spellcheck("the quik fox", dictionary={"the", "fox"})
        assert available is True
        assert [m.word for m in miss] == ["quik"]
