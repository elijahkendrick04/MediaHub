"""brand/guidelines.py — AI-driven brand-guidelines document ingestion.

The user uploads a single file containing their brand guidelines (PDF
style guide, Word doc, plain-text rules, a ZIP of any of those, etc.).
This module:

  1. Extracts text from common document types, fail-soft per backend.
  2. Hands the extracted text to ONE LLM call which returns a
     structured profile (voice do's/don'ts, prohibited words, sponsor
     mention rules, key messages, etc.).
  3. Returns a dict that any content tool can read via
     ``brand_context_for_llm()`` (see ``brand.context``).

No hardcoded interpretation. The text extraction is mechanical; every
semantic decision ("is this a do or a don't?", "is this a tone
descriptor or a content rule?") is the LLM's job. When no LLM provider
is configured the module records the raw text excerpt and reports a
``no_provider`` status so the UI can surface "configure an AI provider"
rather than silently inventing regex-extracted stand-ins.

Public surface:
    extract_text(filename: str, file_bytes: bytes) -> dict
    interpret_guidelines(text: str) -> dict
    ingest_guidelines_file(filename, file_bytes) -> dict
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# Limits — sized for typical PDF/DOCX brand guides while preventing
# zip-bomb / multi-megabyte plaintext blow-ups.
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB upload cap
_MAX_EXTRACTED_CHARS = 200_000  # ~50 pages of text
_MAX_ZIP_FILES = 50  # within a single zip
_MAX_ZIP_DECOMPRESSED = 50 * 1024 * 1024  # 50 MB total inside zip
_RAW_EXCERPT_CHARS = 6_000  # what we persist on the profile


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ext(filename: str) -> str:
    name = (filename or "").lower()
    # Take the last extension; handle ".tar.gz" naively as ".gz".
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].strip()


# ---------------------------------------------------------------------------
# Text extraction — one entry point, per-format fail-soft backends
# ---------------------------------------------------------------------------


def _extract_pdf(data: bytes) -> str:
    """Try pdfplumber first, then pypdf. Return whatever we get."""
    text = ""
    try:
        import pdfplumber  # already a project dep

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t:
                    pages.append(t)
            text = "\n\n".join(pages)
    except Exception as e:
        log.debug("pdfplumber extraction failed: %s", e)
    if text.strip():
        return text
    # pypdf fallback for files pdfplumber can't read.
    try:
        from pypdf import PdfReader  # already a project dep

        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n\n".join(p for p in pages if p)
    except Exception as e:
        log.debug("pypdf extraction failed: %s", e)
        return ""


_DOCX_PARA_RE = re.compile(r"<w:p\b[^>]*>(.*?)</w:p>", re.DOTALL)
_DOCX_TEXT_RE = re.compile(r"<w:t\b[^>]*>(.*?)</w:t>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _extract_docx(data: bytes) -> str:
    """Read a .docx (Office Open XML) without python-docx — DOCX is
    a ZIP of XML, so we crack open word/document.xml and strip tags.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if "word/document.xml" not in zf.namelist():
                return ""
            xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
    except Exception as e:
        log.debug("docx unzip failed: %s", e)
        return ""
    paragraphs = []
    for para_match in _DOCX_PARA_RE.finditer(xml):
        para_xml = para_match.group(1)
        # Concatenate every <w:t> run inside the paragraph.
        runs = [m.group(1) for m in _DOCX_TEXT_RE.finditer(para_xml)]
        para_text = "".join(runs)
        # Decode the XML entities the runs may carry.
        para_text = (
            para_text.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&apos;", "'")
        )
        para_text = para_text.strip()
        if para_text:
            paragraphs.append(para_text)
    return "\n\n".join(paragraphs)


def _extract_html(data: bytes) -> str:
    try:
        from bs4 import BeautifulSoup  # already a project dep

        soup = BeautifulSoup(data, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
    except Exception:
        # Last resort: regex strip.
        try:
            decoded = data.decode("utf-8", errors="replace")
        except Exception:
            return ""
        text = _TAG_RE.sub(" ", decoded)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract_rtf(data: bytes) -> str:
    """Best-effort RTF: strip control words and braces. Good enough for
    a brand guide's text content; we don't need formatting.
    """
    try:
        s = data.decode("utf-8", errors="replace")
    except Exception:
        return ""
    # Remove RTF control words.
    s = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", s)
    s = re.sub(r"\\'[0-9a-fA-F]{2}", "", s)  # hex-escaped chars
    s = s.replace("{", " ").replace("}", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _extract_plain(data: bytes) -> str:
    """Decode as UTF-8 with replacement; fall back to latin-1."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("latin-1")
        except Exception:
            return ""


def _extract_zip(data: bytes) -> str:
    """Walk a ZIP and concatenate extracted text from each readable
    member. Bounded by file-count and total decompressed size."""
    out: list[str] = []
    decompressed = 0
    count = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if count >= _MAX_ZIP_FILES:
                    break
                if decompressed >= _MAX_ZIP_DECOMPRESSED:
                    break
                # Skip macOS noise.
                if info.filename.startswith("__MACOSX/") or info.filename.endswith("/.DS_Store"):
                    continue
                try:
                    body = zf.read(info)
                except Exception:
                    continue
                decompressed += len(body)
                count += 1
                inner_ext = _ext(info.filename)
                inner = _dispatch_extract(inner_ext, body)
                if inner.strip():
                    out.append(f"--- {info.filename} ---\n{inner}")
    except Exception as e:
        log.debug("zip walk failed: %s", e)
        return ""
    return "\n\n".join(out)


def _dispatch_extract(ext: str, data: bytes) -> str:
    if ext == "pdf":
        return _extract_pdf(data)
    if ext == "docx":
        return _extract_docx(data)
    if ext in ("html", "htm"):
        return _extract_html(data)
    if ext == "rtf":
        return _extract_rtf(data)
    if ext == "zip":
        return _extract_zip(data)
    if ext in ("txt", "md", "markdown", "rst", "csv", "tsv", "json", "yaml", "yml"):
        return _extract_plain(data)

    # Known-binary extensions that must NEVER be plaintext-decoded —
    # decoded garbage from a screenshot upload was leaking into the
    # profile's brand_voice_summary and then into every caption prompt
    # (Phase 1.5 bug: user reported "AI captions return uploaded
    # screenshots"). The right response for these is "unsupported",
    # not a best-effort UTF-8 decode of the binary bytes.
    _BINARY_EXTS = {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "tiff",
        "tif",
        "bmp",
        "ico",
        "svg",  # SVG technically XML but treated as image by
        # the brand-DNA pipeline upstream
        "heic",
        "heif",
        "avif",
        "mp4",
        "mov",
        "avi",
        "mkv",
        "webm",
        "m4v",
        "mp3",
        "wav",
        "ogg",
        "flac",
        "m4a",
        "exe",
        "dll",
        "so",
        "dylib",
        "psd",
        "ai",
        "indd",
    }
    if ext in _BINARY_EXTS:
        return ""

    # Magic-byte check: even if the extension is unknown, refuse to
    # decode files that start with common binary signatures.
    _BINARY_MAGIC = (
        b"\x89PNG\r\n\x1a\n",  # PNG
        b"\xff\xd8\xff",  # JPEG
        b"GIF87a",
        b"GIF89a",  # GIF
        b"RIFF",  # WebP / WAV (with WEBP/WAVE at byte 8)
        b"BM",  # BMP
        b"\x00\x00\x01\x00",  # ICO
        b"II*\x00",
        b"MM\x00*",  # TIFF
        b"\x1f\x8b",  # gzip
        b"PK\x03\x04",  # zip (already handled above)
        b"%PDF",  # PDF (already handled above)
        b"\x7fELF",  # Linux executable
        b"MZ",  # Windows executable
    )
    if data and any(data.startswith(sig) for sig in _BINARY_MAGIC):
        return ""

    # Unknown extension AND no binary magic-bytes: try plaintext decode
    # as a last resort. Tightened to 1% replacement-char threshold (was
    # 5%) because real text documents have well under that even with
    # unusual encodings.
    decoded = _extract_plain(data)
    if decoded and decoded.count("�") < max(5, int(len(decoded) * 0.01)):
        return decoded
    return ""


def extract_text(filename: str, file_bytes: bytes) -> dict:
    """Extract plain text from an uploaded brand-guidelines file.

    Returns:
        {
            "text": str,           # extracted body, truncated to limit
            "filename": str,
            "extension": str,
            "byte_size": int,
            "status": str,         # "ok" | "empty" | "too_large" | "unsupported"
            "extractor": str,      # which backend produced the text
        }
    Never raises.
    """
    out = {
        "text": "",
        "filename": filename or "",
        "extension": _ext(filename),
        "byte_size": len(file_bytes or b""),
        "status": "empty",
        "extractor": "",
    }
    if not file_bytes:
        out["status"] = "empty"
        return out
    if len(file_bytes) > _MAX_UPLOAD_BYTES:
        out["status"] = "too_large"
        return out
    ext = out["extension"]
    text = _dispatch_extract(ext, file_bytes)
    if not text.strip():
        out["status"] = "unsupported" if ext else "empty"
        return out
    if len(text) > _MAX_EXTRACTED_CHARS:
        text = text[:_MAX_EXTRACTED_CHARS]
    out["text"] = text
    out["status"] = "ok"
    out["extractor"] = {
        "pdf": "pdfplumber/pypdf",
        "docx": "docx-xml",
        "html": "beautifulsoup",
        "htm": "beautifulsoup",
        "rtf": "rtf-strip",
        "zip": "zip-walk",
    }.get(ext, "plaintext")
    return out


# ---------------------------------------------------------------------------
# LLM interpretation — one call, all the work
# ---------------------------------------------------------------------------

_LLM_SYSTEM = (
    "You are reading a club, society, sports team or organisation's "
    "brand guidelines document. Your job is to convert the text into a "
    "structured profile that another AI system will consult on every "
    "piece of content it generates for this organisation. Be faithful, "
    "terse and concrete. Never invent rules that aren't in the text. "
    "If a section is missing leave the corresponding key empty."
)

# Second LLM pass dedicated to surfacing non-negotiable rules verbatim.
# Bug reported by the user: rules like "the strapline MUST always
# appear in the caption" were being soft-interpreted by the primary pass
# as a generic `tone_dos` item and then drowned out by website-derived
# voice signals at generation time. This pass isolates anything that
# reads as a hard constraint and stores it verbatim so brand.context can
# surface it at the top of every system prompt with explicit override
# framing.
_MANDATORY_RULES_LLM_SYSTEM = (
    "You read brand guideline documents and surface ONLY the "
    "non-negotiable rules — the things the document literally states "
    "must always happen or must never happen. You preserve the user's "
    "wording. You do not interpret, soften, generalise, or expand. If a "
    "sentence reads as a preference or a suggestion, ignore it. If it "
    "reads as a hard rule (MUST, NEVER, ALWAYS, REQUIRED, SHALL, "
    "MANDATORY, FORBIDDEN, do not, never, only) — preserve it."
)


def _build_mandatory_rules_prompt(text: str) -> str:
    excerpt = text if len(text) <= 30_000 else text[:30_000] + "\n[... truncated ...]"
    return (
        "Here is the brand-guidelines document text:\n\n"
        "===== BEGIN DOCUMENT =====\n"
        f"{excerpt}\n"
        "===== END DOCUMENT =====\n\n"
        "Scan the document and extract every rule the organisation "
        "literally states is non-negotiable. Look for words like MUST, "
        "NEVER, ALWAYS, REQUIRED, SHALL, MANDATORY, FORBIDDEN, "
        'PROHIBITED, "do not", "never", "only", and any rule '
        'stated in equivalent force (e.g. "the strapline appears on '
        'every caption" is mandatory even without MUST).\n\n'
        "Return a SINGLE JSON object with EXACTLY one key:\n"
        "  mandatory_rules: array of strings — each entry is one rule, "
        "quoted as close to the document's own wording as possible "
        "(rephrase only if the source sentence is impractically long; "
        "preserve the imperative force). Up to 25 rules. If the "
        "document contains no non-negotiable rules, return an empty "
        "array.\n\n"
        "Do NOT include preferences, suggestions, examples, or things "
        "the document says are recommendations. Only hard rules."
    )


def _normalise_mandatory_rules(raw: object) -> list[str]:
    """Coerce the LLM's response into a clean list[str]. Accept either
    a list directly or a dict with `mandatory_rules`."""
    if isinstance(raw, dict):
        items = raw.get("mandatory_rules")
    else:
        items = raw
    if not isinstance(items, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s:
            continue
        # Strip surrounding quotes the LLM sometimes adds.
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()
        if not s:
            continue
        s = s[:600]
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= 25:
            break
    return out


def extract_mandatory_rules(text: str) -> list[str]:
    """Pull verbatim non-negotiable rules out of a brand-guidelines
    text using the configured cloud LLM. Returns ``[]`` when no
    provider is configured (the UI will surface "AI unavailable" via
    the parent payload's status field), when the LLM call fails, or
    when the document contained no mandatory rules.

    Never raises — this is a best-effort enrichment surface.
    """
    if not text or not text.strip():
        return []
    try:
        from mediahub.media_ai.llm import generate_json, is_available
    except Exception:
        return []
    if not is_available():
        return []
    prompt = _build_mandatory_rules_prompt(text)
    try:
        raw = generate_json(
            prompt, system=_MANDATORY_RULES_LLM_SYSTEM, max_tokens=1_800, fallback={}
        )
    except Exception as e:
        log.debug("mandatory-rules LLM call failed: %s", e)
        return []
    return _normalise_mandatory_rules(raw)


def _build_prompt(text: str) -> str:
    excerpt = text if len(text) <= 30_000 else text[:30_000] + "\n[... truncated ...]"
    return (
        "Here is the brand-guidelines document text:\n\n"
        "===== BEGIN DOCUMENT =====\n"
        f"{excerpt}\n"
        "===== END DOCUMENT =====\n\n"
        "Return a SINGLE JSON object with EXACTLY these keys "
        "(no prose, no fences, no commentary):\n"
        "  summary: string, 40-80 words summarising the brand & its "
        "voice the way another AI would need to know it before writing "
        "content for this org\n"
        "  voice_attributes: array of up to 8 single-word or short "
        'adjectives describing the desired voice (e.g. "warm", '
        '"data-led", "irreverent")\n'
        "  tone_dos: array of up to 8 short imperatives — things the "
        "voice should DO\n"
        "  tone_donts: array of up to 8 short imperatives — things the "
        "voice should NEVER do\n"
        "  prohibited_words: array of explicitly banned words or "
        "phrases\n"
        "  preferred_terminology: object mapping the wrong term to the "
        'preferred term (e.g. {"members": "athletes"})\n'
        "  hashtag_rules: short string describing how hashtags should "
        "be used (counts, required tags, anything banned)\n"
        "  sponsor_mention_rules: short string on how/when sponsors "
        "must be acknowledged\n"
        "  audience: short string describing who the content is for\n"
        "  key_messages: array of up to 6 short strings — recurring "
        "themes or pillar messages the brand always tries to land\n"
        "  palette_mentions: array of hex colours (#rrggbb) mentioned "
        "in the guidelines, lower-case\n"
    )


def _is_hex(c: str) -> bool:
    return isinstance(c, str) and bool(re.match(r"^#[0-9a-fA-F]{6}$", c))


def _empty_interpretation(status: str) -> dict:
    """Return the canonical empty-result shape for interpret_guidelines
    when no AI output was produced. ``status`` distinguishes the
    failure mode (``no_provider`` / ``provider_error`` / ``empty``) so
    the UI can show an honest message instead of inventing fake fields.
    """
    return {
        "summary": "",
        "voice_attributes": [],
        "tone_dos": [],
        "tone_donts": [],
        "prohibited_words": [],
        "preferred_terminology": {},
        "hashtag_rules": "",
        "sponsor_mention_rules": "",
        "audience": "",
        "key_messages": [],
        "palette_mentions": [],
        "status": status,
    }


def _normalise_interpretation(raw: dict) -> dict:
    """Clean the LLM's JSON: enforce types, strip stray fields, cap
    list sizes."""
    out = {
        "summary": "",
        "voice_attributes": [],
        "tone_dos": [],
        "tone_donts": [],
        "prohibited_words": [],
        "preferred_terminology": {},
        "hashtag_rules": "",
        "sponsor_mention_rules": "",
        "audience": "",
        "key_messages": [],
        "palette_mentions": [],
        "status": "ok",
    }
    if not isinstance(raw, dict):
        return out

    def _str(v, cap: int) -> str:
        return str(v).strip()[:cap] if isinstance(v, str) and v.strip() else ""

    def _list_str(v, item_cap: int, n_cap: int) -> list[str]:
        if not isinstance(v, list):
            return []
        cleaned = [str(x).strip()[:item_cap] for x in v if str(x).strip()]
        # de-dupe preserving order
        seen: set[str] = set()
        uniq: list[str] = []
        for x in cleaned:
            xl = x.lower()
            if xl in seen:
                continue
            seen.add(xl)
            uniq.append(x)
        return uniq[:n_cap]

    out["summary"] = _str(raw.get("summary"), 1_500)
    out["voice_attributes"] = _list_str(raw.get("voice_attributes"), 40, 8)
    out["tone_dos"] = _list_str(raw.get("tone_dos"), 200, 8)
    out["tone_donts"] = _list_str(raw.get("tone_donts"), 200, 8)
    out["prohibited_words"] = _list_str(raw.get("prohibited_words"), 80, 20)
    pref = raw.get("preferred_terminology")
    if isinstance(pref, dict):
        clean_pref: dict[str, str] = {}
        for k, v in pref.items():
            if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
                clean_pref[k.strip()[:60]] = v.strip()[:60]
            if len(clean_pref) >= 20:
                break
        out["preferred_terminology"] = clean_pref
    out["hashtag_rules"] = _str(raw.get("hashtag_rules"), 600)
    out["sponsor_mention_rules"] = _str(raw.get("sponsor_mention_rules"), 600)
    out["audience"] = _str(raw.get("audience"), 400)
    out["key_messages"] = _list_str(raw.get("key_messages"), 200, 6)
    palette = raw.get("palette_mentions")
    if isinstance(palette, list):
        valid: list[str] = []
        for h in palette:
            if not isinstance(h, str):
                continue
            c = h.strip().lower()
            if not c.startswith("#"):
                c = "#" + c
            if len(c) == 4:
                c = "#" + "".join(ch * 2 for ch in c[1:])
            if _is_hex(c):
                valid.append(c)
        out["palette_mentions"] = valid[:8]
    return out


def interpret_guidelines(text: str) -> dict:
    """Send the extracted text to the configured cloud LLM. Always
    returns a dict; on LLM unavailability or failure returns the
    canonical empty shape with a ``status`` field that tells callers
    why (``no_provider`` / ``provider_error`` / ``empty``). Never
    fabricates structured fields — the only honest output without an
    LLM is "AI couldn't be reached".
    """
    if not text or not text.strip():
        return {"summary": "", "status": "empty"}
    try:
        from mediahub.media_ai.llm import generate_json, is_available
    except Exception:
        return _empty_interpretation("no_provider")
    if not is_available():
        return _empty_interpretation("no_provider")
    prompt = _build_prompt(text)
    try:
        raw = generate_json(prompt, system=_LLM_SYSTEM, max_tokens=2_400, fallback={})
    except Exception as e:
        log.debug("guidelines LLM call failed: %s", e)
        return _empty_interpretation("provider_error")
    if not isinstance(raw, dict) or not raw:
        return _empty_interpretation("provider_error")
    out = _normalise_interpretation(raw)
    has_signal = bool(
        out["summary"]
        or out["voice_attributes"]
        or out["tone_dos"]
        or out["tone_donts"]
        or out["key_messages"]
    )
    if not has_signal:
        return _empty_interpretation("provider_error")
    return out


# ---------------------------------------------------------------------------
# Combined entry point — call this from the web layer
# ---------------------------------------------------------------------------


def ingest_guidelines_file(filename: str, file_bytes: bytes) -> dict:
    """End-to-end: extract → interpret → return saveable payload.

    Returns:
        {
          "brand_guidelines": dict,                       # structured AI output
          "brand_guidelines_raw_excerpt": str,            # first ~6 KB of text
          "brand_guidelines_filename": str,
          "brand_guidelines_uploaded_at": str,            # ISO timestamp
          "brand_guidelines_status": str,                 # "ok"|"no_provider"|"provider_error"|"empty"|"too_large"|"unsupported"
          "brand_guidelines_extractor": str,
          "brand_guidelines_byte_size": int,
          "brand_guidelines_mandatory_rules": list[str],  # MUST/NEVER/ALWAYS rules, verbatim
        }
    Never raises.
    """
    ex = extract_text(filename, file_bytes)
    payload = {
        "brand_guidelines": {},
        "brand_guidelines_raw_excerpt": "",
        "brand_guidelines_filename": ex["filename"],
        "brand_guidelines_uploaded_at": _now_iso(),
        "brand_guidelines_status": ex["status"],
        "brand_guidelines_extractor": ex["extractor"],
        "brand_guidelines_byte_size": ex["byte_size"],
        "brand_guidelines_mandatory_rules": [],
    }
    if ex["status"] != "ok":
        return payload
    interp = interpret_guidelines(ex["text"])
    payload["brand_guidelines"] = interp
    payload["brand_guidelines_status"] = interp.get("status", "ok")
    payload["brand_guidelines_raw_excerpt"] = ex["text"][:_RAW_EXCERPT_CHARS]
    # Second dedicated pass: surface non-negotiable rules verbatim so
    # downstream content generators can put them above everything else.
    payload["brand_guidelines_mandatory_rules"] = extract_mandatory_rules(ex["text"])
    return payload


__all__ = [
    "extract_text",
    "interpret_guidelines",
    "extract_mandatory_rules",
    "ingest_guidelines_file",
]
