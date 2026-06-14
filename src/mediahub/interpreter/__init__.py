"""
interpreter/__init__.py — public API for the V7.5 format-agnostic interpreter.

Usage:
    from mediahub.interpreter import interpret_document

    result: InterpretedMeet = interpret_document(raw_bytes, hint="pdf")

No swim-vocabulary literals in this file.
"""

from __future__ import annotations

import logging
import re
import pathlib
from typing import Optional

from .schema_dataclasses import InterpretedEvent, InterpretedMeet, InterpretedSwim, ColumnSchema
from .ingest import ingest
from .ontology_loader import OntologyLoader
from .patterns import PatternStore
from .schema_induce import induce_schema
from .events_induce import induce_events
from .rows import assign_rows_to_events
from .hypothesis import propose_patterns, save_corpus_section
from .hytek_parser import detect_hy3, parse_hy3
from .sdif_parser import detect_sdif, parse_sdif
from .lenex_parser import detect_lenex, parse_lenex

log = logging.getLogger(__name__)

__all__ = ["interpret_document", "InterpretedMeet", "InterpretedEvent", "InterpretedSwim"]

# Shared singletons (re-used across calls in the same process)
_ontology: OntologyLoader | None = None
_store: PatternStore | None = None

_LOW_CONF_THRESHOLD = 0.6
_MIN_OVERALL_CONF = 0.5

# W.10 OCR fallback: OCR'd text is never high-confidence — cap the overall
# score and flag every uncertain recognised line for human review.
_OCR_CONFIDENCE_CAP = 0.55
_OCR_LINE_LOW_CONF = 0.6
_OCR_MAX_LOW_CONF_FLAGS = 20

# Regex for meet-level metadata — structural only, no domain vocab
_DATE_RE = re.compile(r"\b(\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4}|\d{4}[\-/]\d{2}[\-/]\d{2})\b")


def _get_singletons(
    ontology_root: Optional[pathlib.Path] = None,
    patterns_path: Optional[pathlib.Path] = None,
) -> tuple[OntologyLoader, PatternStore]:
    global _ontology, _store
    if _ontology is None or ontology_root is not None:
        _ontology = OntologyLoader(root=ontology_root)
    if _store is None or patterns_path is not None:
        _store = PatternStore(path=patterns_path)
    return _ontology, _store


# ---------------------------------------------------------------------------
# Meet-level metadata extraction
# ---------------------------------------------------------------------------


def _extract_meet_metadata(
    text: str,
    ontology: OntologyLoader,
) -> dict:
    """Extract top-level meet fields from the first ~2000 characters."""
    header = text[:2000]
    lines = [ln.strip() for ln in header.splitlines() if ln.strip()]

    meet_name: Optional[str] = None
    venue: Optional[str] = None
    dates: Optional[tuple[str, str]] = None
    course_default: Optional[str] = None
    governing_body_hint: Optional[str] = None

    # First non-trivial line is often the meet name
    for ln in lines[:5]:
        if len(ln) >= 6 and re.search(r"[A-Za-z]", ln):
            meet_name = ln
            break

    # Venue: second meaningful line
    for ln in lines[1:8]:
        if len(ln) >= 4 and ln != meet_name and re.search(r"[A-Za-z]", ln):
            venue = ln
            break

    # Dates
    date_matches = _DATE_RE.findall(header)
    if len(date_matches) >= 2:
        dates = (date_matches[0], date_matches[-1])
    elif len(date_matches) == 1:
        dates = (date_matches[0], date_matches[0])

    # Course from ontology
    course_map = ontology.canonical_map("courses")
    course_re = ontology.build_regex("courses")
    if course_re:
        cm = course_re.search(header)
        if cm:
            course_default = course_map.get(cm.group(0).lower())

    # Governing body from ontology (may be empty dict)
    gb_map = ontology.canonical_map("governing_bodies")
    if gb_map:
        gb_re = ontology.build_regex("governing_bodies")
        if gb_re:
            gm = gb_re.search(header)
            if gm:
                governing_body_hint = gb_map.get(gm.group(0).lower())

    return {
        "meet_name": meet_name,
        "venue": venue,
        "dates": dates,
        "course_default": course_default,
        "governing_body_hint": governing_body_hint,
    }


# ---------------------------------------------------------------------------
# Confidence calculation
# ---------------------------------------------------------------------------


def _overall_confidence(events: list[InterpretedEvent]) -> float:
    if not events:
        return 0.0
    event_confs: list[float] = []
    for ev in events:
        if ev.swims:
            swim_mean = sum(s.confidence for s in ev.swims) / len(ev.swims)
            ev_conf = 0.4 * ev.confidence + 0.6 * swim_mean
        else:
            ev_conf = ev.confidence * 0.5
        event_confs.append(ev_conf)
    return round(sum(event_confs) / len(event_confs), 4)


# Generous upper bound on human swim speed (m/s). World-record pace is ~2.4 m/s
# over 50m and slower over every longer distance, so a time that implies a
# FASTER pace than this can only be a wrong time↔event pairing (a 50m time
# filed under a 100m event, a 400m time under 1500m, etc.).
_MAX_SWIM_SPEED_MPS = 2.5


def _time_to_seconds(t: str) -> Optional[float]:
    """Canonical 'mm:ss.cc' / 'ss.cc' → seconds, or None for non-times (DQ/DNS)."""
    try:
        if ":" in t:
            mm, rest = t.split(":", 1)
            return int(mm) * 60 + float(rest)
        return float(t)
    except (ValueError, TypeError, AttributeError):
        return None


def _flag_implausible_swims(events: list[InterpretedEvent]) -> list[dict]:
    """Flag swims whose time is physically impossible for the event's distance.

    Such a pairing means the row was matched to the wrong event (e.g. a 50m-shaped
    time shown under a 100m event, or a 400m-shaped time under a 1500m event). We
    never silently drop it — we drop its confidence and return a needs_review
    entry so the uncertainty is explicit and it can't surface as a confident
    card/PB.
    """
    flags: list[dict] = []
    for ev in events:
        if not ev.distance_m:
            continue
        floor_s = ev.distance_m / _MAX_SWIM_SPEED_MPS
        for s in ev.swims:
            if not s.time:
                continue
            secs = _time_to_seconds(s.time)
            if secs is None or secs <= 0 or secs >= floor_s:
                continue
            s.confidence = min(s.confidence, 0.2)
            s.field_confidence["time_event_mismatch"] = 0.0
            flags.append(
                {
                    "reason": "implausible-time-for-event",
                    "detail": (
                        f"{s.swimmer_name or 'A swimmer'}: {s.time} is impossible for "
                        f"{ev.distance_m}m (minimum ~{floor_s:.0f}s) — the result was "
                        "likely paired with the wrong event; flagged for review."
                    ),
                }
            )
    return flags


# ---------------------------------------------------------------------------
# Native (Hy-Tek / SDIF) fast path
# ---------------------------------------------------------------------------

_ZIP_MAGIC = b"PK\x03\x04"


def _merge_meets(meets: list[InterpretedMeet]) -> InterpretedMeet:
    """Merge several InterpretedMeets (e.g. .hy3 + .cl2 from same ZIP).

    The .hy3 and .cl2 redundantly encode the same swims; we prefer the
    .hy3 (richer event metadata) when present and fall back to .cl2.
    """
    if not meets:
        return InterpretedMeet(
            meet_name=None,
            venue=None,
            dates=None,
            course_default=None,
            governing_body_hint=None,
            events=[],
            overall_confidence=0.0,
            needs_review=[],
            sources_used=[],
            patterns_used=[],
            new_patterns_proposed=[],
        )

    # Sort by overall_confidence desc, then by # of swims desc, then prefer hy3
    def _rank(m: InterpretedMeet) -> tuple:
        n_swims = sum(len(e.swims) for e in m.events)
        is_hy3 = any("hy3" in s for s in m.sources_used)
        return (m.overall_confidence, n_swims, 1 if is_hy3 else 0)

    meets.sort(key=_rank, reverse=True)
    primary = meets[0]
    sources = []
    for m in meets:
        sources.extend(m.sources_used)
    primary.sources_used = list(dict.fromkeys(sources))
    return primary


def _try_native_parse(
    data: bytes,
    *,
    hint: Optional[str] = None,
    source_path: Optional[pathlib.Path] = None,
) -> Optional[InterpretedMeet]:
    """Attempt direct parsing for native interchange formats.

    Returns an InterpretedMeet if the input is .hy3, .cl2/SDIF, LENEX
    (.lef/.lxf), or a ZIP containing such files. Returns None to defer
    to the schema-induce pipeline.
    """
    if not data:
        return None

    # Direct HY3 / SDIF detection
    if detect_hy3(data) or (hint and "hy3" in hint.lower()):
        try:
            return parse_hy3(data)
        except Exception as exc:  # noqa: BLE001
            log.warning("hytek parser failed: %s", exc)

    if detect_sdif(data) or (hint and any(x in hint.lower() for x in ("cl2", "sd3", "sdif"))):
        try:
            return parse_sdif(data)
        except Exception as exc:  # noqa: BLE001
            log.warning("sdif parser failed: %s", exc)

    if detect_lenex(data) or (hint and any(x in hint.lower() for x in (".lef", ".lxf", "lenex"))):
        try:
            return parse_lenex(data)
        except Exception as exc:  # noqa: BLE001
            log.warning("lenex parser failed: %s", exc)

    # ZIP: look for HY3 / CL2 / LENEX members and parse them directly. We cap
    # member count and uncompressed size via _zip_safety so a malicious
    # compression bomb can't OOM the worker.
    if data[:4] == _ZIP_MAGIC:
        import zipfile  # noqa: PLC0415
        import io  # noqa: PLC0415
        from ._zip_safety import safe_member_names, safe_read_member, UnsafeZipError  # noqa: PLC0415

        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except Exception:  # noqa: BLE001
            return None
        try:
            try:
                safe_names = safe_member_names(zf)
            except UnsafeZipError as exc:
                log.warning("rejected unsafe ZIP: %s", exc)
                return None
            hytek_members = [n for n in safe_names if n.lower().endswith(".hy3")]
            sdif_members = [n for n in safe_names if n.lower().endswith((".cl2", ".sd3"))]
            lenex_members = [n for n in safe_names if n.lower().endswith((".lef", ".lxf"))]
            if not hytek_members and not sdif_members and not lenex_members:
                return None
            results: list[InterpretedMeet] = []
            info_by_name = {info.filename: info for info in zf.infolist()}
            for n in hytek_members:
                try:
                    results.append(parse_hy3(safe_read_member(zf, info_by_name[n])))
                except UnsafeZipError as exc:
                    log.warning("hytek member %s rejected: %s", n, exc)
                except Exception as exc:  # noqa: BLE001
                    log.warning("hytek member %s failed: %s", n, exc)
            for n in sdif_members:
                try:
                    results.append(parse_sdif(safe_read_member(zf, info_by_name[n])))
                except UnsafeZipError as exc:
                    log.warning("sdif member %s rejected: %s", n, exc)
                except Exception as exc:  # noqa: BLE001
                    log.warning("sdif member %s failed: %s", n, exc)
            for n in lenex_members:
                try:
                    results.append(parse_lenex(safe_read_member(zf, info_by_name[n])))
                except UnsafeZipError as exc:
                    log.warning("lenex member %s rejected: %s", n, exc)
                except Exception as exc:  # noqa: BLE001
                    log.warning("lenex member %s failed: %s", n, exc)
            if results:
                merged = _merge_meets(results)
                # Tag that the source was a ZIP wrapper
                merged.sources_used = ["format:zip"] + [
                    s for s in merged.sources_used if s != "format:zip"
                ]
                return merged
        finally:
            zf.close()
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def interpret_document(
    data: bytes,
    hint: Optional[str] = None,
    *,
    source_path: Optional[pathlib.Path] = None,
    ontology_root: Optional[pathlib.Path] = None,
    patterns_path: Optional[pathlib.Path] = None,
) -> InterpretedMeet:
    """
    Parse *data* bytes and return an InterpretedMeet.

    Parameters
    ----------
    data:
        Raw document bytes (PDF, HTML, plain text, ZIP, hy3, or image).
    hint:
        Format hint string (e.g. "pdf", "html", "text").  Optional.
    source_path:
        Optional on-disk path of the input.  When provided and the document
        is a frameset HTML or a results landing page with sibling event
        pages, the interpreter will aggregate those siblings transparently.
        Bytes-only callers may pass ``None``.
    ontology_root:
        Override for the ontology directory path.
    patterns_path:
        Override for the patterns.jsonl path.

    Returns
    -------
    InterpretedMeet with overall_confidence 0..1.
    Image inputs that require OCR are returned with overall_confidence=0.0
    and a needs_review entry.
    """
    ontology, store = _get_singletons(ontology_root, patterns_path)

    # ---- Fast path: native Hy-Tek formats -----------------------------
    # Hy-Tek `.hy3` and `.cl2` (SDIF) are fixed-width record streams that
    # the schema-induce path would mangle. Detect them up-front and route
    # to dedicated parsers.
    fast = _try_native_parse(data, hint=hint, source_path=source_path)
    if fast is not None:
        return fast

    # ---- Stage 1: Ingest ------------------------------------------------
    stream = ingest(
        data,
        content_type_hint=hint,
        source_path=pathlib.Path(source_path) if source_path else None,
    )
    sources_used = [f"format:{stream.format_detected}"]

    # Handle OCR-needed images
    if stream.format_detected == "image-needs-ocr":
        return InterpretedMeet(
            meet_name=None,
            venue=None,
            dates=None,
            course_default=None,
            governing_body_hint=None,
            events=[],
            overall_confidence=0.0,
            needs_review=[{"reason": "image-needs-ocr", "detail": "OCR not available"}],
            sources_used=sources_used,
            patterns_used=[],
            new_patterns_proposed=[],
        )

    # ---- Stage 2: Schema induction --------------------------------------
    schemas = induce_schema(stream, ontology=ontology)
    patterns_used: list[str] = []
    needs_review: list[dict] = []
    new_patterns_proposed: list[dict] = []

    # Flag low-confidence columns
    for schema in schemas:
        if schema.confidence < _LOW_CONF_THRESHOLD:
            needs_review.append(
                {
                    "reason": "low-confidence-column",
                    "col_type": schema.col_type,
                    "confidence": schema.confidence,
                    "header": schema.header_text,
                }
            )
            # Hypothesis: propose patterns for failing sections
            if stream.text:
                proposed = propose_patterns(
                    stream_section=stream.text[:500],
                    current_store=store,
                    pattern_type=f"schema_{schema.col_type}",
                )
                new_patterns_proposed.extend(proposed)

    # Record which patterns fired
    for rec in store.all_records():
        if rec.get("fires", 0) > 0:
            patterns_used.append(rec["id"])

    # ---- Stage 3: Events induction --------------------------------------
    events = induce_events(stream, ontology=ontology)

    if not events:
        needs_review.append(
            {
                "reason": "no-events-detected",
                "detail": "Event-header detection found no events; synthetic fallback used.",
            }
        )
        # Hypothesis: propose patterns for event headers
        for line in stream.lines[:20]:
            text = getattr(line, "text", "").strip()
            if text:
                proposed = propose_patterns(
                    stream_section=text,
                    current_store=store,
                    pattern_type="event_header",
                )
                new_patterns_proposed.extend(proposed)

    # ---- Stage 4: Row extraction ----------------------------------------
    assign_rows_to_events(stream, events, schemas)

    # ---- Stage 4b: physical-plausibility guard --------------------------
    # Catch results paired with the wrong event (a time impossible for the
    # distance) and flag them for review instead of presenting them as fact.
    needs_review.extend(_flag_implausible_swims(events))

    # ---- Stage 5: Meet metadata -----------------------------------------
    meta = _extract_meet_metadata(stream.text, ontology)

    # ---- Stage 6: Overall confidence + hypothesis -----------------------
    overall_conf = _overall_confidence(events)

    # ---- W.10: OCR provenance + per-row uncertainty ----------------------
    # When ingestion recovered the text via OCR (phone photo / scanned PDF),
    # record which engine ran, flag every low-confidence recognised line, and
    # cap the overall confidence — uncertain rows are flagged for human
    # review, never silently guessed.
    if stream.format_detected == "image-ocr":
        ocr_engine = getattr(stream, "ocr_engine", "unknown")
        ocr_lines = list(getattr(stream, "ocr_lines", []))
        low_conf_lines = [(t, c) for t, c in ocr_lines if c < _OCR_LINE_LOW_CONF]
        sources_used.append(f"ocr:{ocr_engine}")
        needs_review.append(
            {
                "reason": "ocr-used",
                "detail": f"{ocr_engine}; {len(low_conf_lines)} low-confidence lines",
            }
        )
        for line_text, line_conf in low_conf_lines[:_OCR_MAX_LOW_CONF_FLAGS]:
            needs_review.append(
                {
                    "reason": "ocr-low-confidence-row",
                    "detail": line_text,
                    "confidence": line_conf,
                }
            )
        overall_conf = min(overall_conf, _OCR_CONFIDENCE_CAP)
    elif getattr(stream, "ocr_unavailable_detail", None):
        # Scanned PDF with no OCR engine installed: honest review flag,
        # everything else about the (empty) pipeline result stays as-is.
        needs_review.append({"reason": "image-needs-ocr", "detail": stream.ocr_unavailable_detail})

    if overall_conf < _LOW_CONF_THRESHOLD and stream.text:
        # Low confidence overall — run hypothesis on whole-doc sample
        proposed = propose_patterns(
            stream_section=stream.text[:800],
            current_store=store,
            pattern_type="document_layout",
        )
        new_patterns_proposed.extend(proposed)
        needs_review.append(
            {
                "reason": "low-overall-confidence",
                "confidence": overall_conf,
                "note": f"Proposed {len(proposed)} new patterns (provisional=True)",
            }
        )

    # Save successful sections to corpus for future validation
    if overall_conf >= _LOW_CONF_THRESHOLD and stream.text:
        try:
            save_corpus_section(stream.text[:2000], label="success")
        except Exception as exc:  # noqa: BLE001
            log.debug("Could not save corpus section: %s", exc)

    return InterpretedMeet(
        meet_name=meta["meet_name"],
        venue=meta["venue"],
        dates=meta["dates"],
        course_default=meta["course_default"],
        governing_body_hint=meta["governing_body_hint"],
        events=events,
        overall_confidence=overall_conf,
        needs_review=needs_review,
        sources_used=sources_used,
        patterns_used=list(set(patterns_used)),
        new_patterns_proposed=new_patterns_proposed,
    )
