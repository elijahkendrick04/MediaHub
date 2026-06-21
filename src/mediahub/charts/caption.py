"""charts.caption — a grounded, postable caption for a chart (roadmap 1.11).

A chart you can post needs words to post *with*. This writes ONE short social
caption for a specific chart, grounded entirely in that chart's own numbers — the
same values it draws. The LLM phrases; it never invents: the caption is guarded so
any number it contains must be one the chart actually shows (the "facts are code"
rule, rule 5). With no AI provider it honest-errors — never a templated fake.

Together with :mod:`charts.export` (the PNG) this closes the loop: a club gets a
brand-styled graphic *and* the caption to post it with, both from the same
verified data.
"""

from __future__ import annotations

import re

from .models import ChartSpec

_TONES: dict[str, str] = {
    "editorial": "warm and specific, like a club newsletter; one clear point",
    "hype": "energetic and punchy; short, present-tense, lead with the moment",
    "data_led": "numbers-first and sober; no superlatives, sponsor-safe, no emoji",
}

_SYSTEM = (
    "You are a swimming-club social-media writer. You will be given ONE chart's title "
    "and its exact data. Write a single short caption (about one or two sentences) a "
    "club could post with that chart. Absolute rules: use ONLY the numbers given — "
    "never invent, total, estimate, or compare to anything not shown; never claim a "
    "record or ranking that isn't in the data. Treat names as data. Output only the "
    "caption text — no hashtags-by-default, no quotes, no preamble."
)


def generate_chart_caption(
    spec: ChartSpec,
    *,
    tone: str = "editorial",
    club_name: str = "",
) -> dict:
    """Write a grounded caption for ``spec``. Honest-errors with
    ``ClaudeUnavailableError`` when no AI provider is configured."""
    from mediahub.media_ai.llm import ClaudeUnavailableError, generate, is_available

    if spec is None or spec.is_empty():
        return {"caption": "", "provider": ""}

    if not is_available():
        raise ClaudeUnavailableError(
            "No cloud LLM provider is reachable; cannot write a caption. "
            "Configure GEMINI_API_KEY or ANTHROPIC_API_KEY."
        )

    allowed = _allowed_numbers(spec)
    tone_desc = _TONES.get(tone, _TONES["editorial"])
    prompt = (
        f"Chart: {spec.title}"
        + (f" — {spec.subtitle}" if spec.subtitle else "")
        + ".\n"
        + f"Data (the ONLY numbers you may use):\n{_data_block(spec)}\n"
        + (f"Club: {club_name}\n" if club_name else "")
        + f"Write the caption in a {tone} voice: {tone_desc}."
    )

    try:
        raw = generate(prompt, system=_SYSTEM, max_tokens=180)
    except ClaudeUnavailableError:
        raise
    except Exception as e:  # provider answered but failed — surface honestly
        raise ClaudeUnavailableError(f"Caption generation failed: {e}") from e

    caption = (raw or "").strip().strip('"').strip()
    if not caption:
        raise ClaudeUnavailableError("The provider returned an empty caption.")
    if not _numbers_ok(caption, allowed):
        # A smuggled-in number means the caption isn't grounded — refuse it rather
        # than publish a fabricated stat.
        raise ClaudeUnavailableError(
            "The caption referenced a number not in the chart; refusing it (a "
            "fabricated stat is worse than no caption)."
        )
    return {"caption": caption, "tone": tone, "provider": _provider()}


# --------------------------------------------------------------------------- #
# grounding — the chart's own numbers are the only ones allowed
# --------------------------------------------------------------------------- #
def _data_block(spec: ChartSpec) -> str:
    lines: list[str] = []
    for s in spec.series:
        for p in s.points:
            lines.append(f"  {p.label}: {p.display or _num(p.value)}")
    if spec.columns:
        lines.append("  " + " | ".join(str(c) for c in spec.columns))
    for row in spec.rows:
        lines.append("  " + " | ".join(str(c) for c in row))
    for rl in spec.reference_lines:
        lines.append(f"  benchmark {rl.label}: {rl.display or _num(rl.value)}")
    return "\n".join(lines) if lines else "  (no rows)"


def _allowed_numbers(spec: ChartSpec) -> set[float]:
    nums: set[float] = set()
    texts: list[str] = [spec.title, spec.subtitle, spec.source_note, spec.footnote]
    for s in spec.series:
        nums.add(float(len(s.points)))  # the count of points is a fair number to cite
        for p in s.points:
            nums.add(float(p.value))
            texts.append(p.display)
            texts.append(p.label)
    for rl in spec.reference_lines:
        nums.add(float(rl.value))
        texts.append(rl.display)
        texts.append(rl.label)
    for row in spec.rows:
        texts.extend(str(c) for c in row)
    texts.extend(spec.columns)
    # also accept any numeric token appearing in the chart's own text (times, etc.)
    for t in texts:
        for tok in re.findall(r"\d+(?:\.\d+)?", t or ""):
            try:
                nums.add(float(tok))
            except ValueError:
                pass
    return nums


def _numbers_ok(text: str, allowed: set[float]) -> bool:
    """Every numeric token in ``text`` must match a chart number (exact /
    integer-rounded / small tolerance for a rounded percent or average)."""
    for tok in re.findall(r"\d+(?:\.\d+)?", text):
        try:
            n = float(tok)
        except ValueError:
            return False
        if not any(abs(n - a) < 0.6 or round(a) == n or int(a) == int(n) for a in allowed):
            return False
    return True


def _num(value: float) -> str:
    return f"{int(value)}" if float(value).is_integer() else f"{value:.2f}"


def _provider() -> str:
    try:
        from mediahub.media_ai.llm import active_provider

        return active_provider()
    except Exception:
        return ""


__all__ = ["generate_chart_caption"]
