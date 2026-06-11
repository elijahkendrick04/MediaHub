"""
Club profile system — replaces V3's per-club hardcoded filter.

A ClubProfile captures everything specific to one client club:
  - canonical club codes that mean "us"
  - exclusion codes (e.g. host club of a meet we attend)
  - human display name + brand colour
  - tone hint for caption style
  - known asa_ids (built up over time from PB store + prior meets)
  - "important" qualification standard ids to surface first
  - (V7) brand_kit dict, tone str, caption_templates dict, achievement_priorities dict

Profiles live as JSON files under /club_profiles/. There is no
auto-seeded demo club; the empty-state UI prompts the user to create
their own profile.
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class ClubProfile:
    profile_id: str  # short slug, e.g. 'your-club'
    display_name: str  # human name, e.g. 'Your Club Swimming'
    short_name: str = ""  # e.g. 'Your Club'
    club_codes: list[str] = field(default_factory=list)  # canonical codes meaning "us"
    exclude_codes: list[str] = field(default_factory=list)  # e.g. host clubs to skip
    known_asa_ids: list[str] = field(default_factory=list)
    brand_primary: str = "#A30D2D"
    brand_secondary: str = "#000000"
    caption_tone: str = "warm-club"  # warm-club | sharp-news | playful-fan
    important_standards: list[str] = field(default_factory=list)
    important_swimmers: list[str] = field(default_factory=list)  # asa_ids to spotlight
    governing_body: str = ""
    country: str = ""
    notes: str = ""

    # ---- V7 extensions (all optional with defaults so old JSON still loads) ----

    # BrandKit dict (matches brand.kit.BrandKit.to_dict() schema)
    brand_kit: dict = field(default_factory=dict)

    # Active tone: "warm-club" | "hype" | "data-led"
    tone: str = "warm-club"

    # Caption templates: {content_type: {tone_str: {slot: template_str}}}
    caption_templates: dict = field(default_factory=dict)

    # Per-achievement-type priority multipliers for the V5 ranker
    # Keys match Achievement.type strings; "_default" is the fallback.
    achievement_priorities: dict = field(default_factory=dict)

    # ---- Holo-style organisation DNA (all optional, backward-compatible) ----

    # swimming_club | athletics | football | university_society | corporate_team | other
    org_type: str = "other"

    # Active social platforms: instagram | tiktok | twitter | facebook | linkedin
    platforms: list[str] = field(default_factory=list)

    # Primary sponsor info
    sponsor_name: str = ""
    sponsor_guidelines: str = ""

    # Up to 5 past captions pasted by the user to calibrate voice
    exemplar_captions: list[str] = field(default_factory=list)

    # Freeform brand voice notes
    tone_notes: str = ""

    # ---- Voice imitation layer (Brand DNA §4.5 Lately, §4.6 Jasper) ----

    # 5-20 raw caption strings pasted by the user (Instagram/Facebook/X).
    # Names should be redacted before storage — see brand.voice_imitation.
    voice_examples: list[str] = field(default_factory=list)

    # Structured voice profile derived from voice_examples. Schema:
    #   sentence_length_avg: float
    #   sentence_length_p90: float
    #   emoji_rate_per_caption: float
    #   hashtag_count_avg: float
    #   characteristic_openers: list[str]
    #   characteristic_closers: list[str]
    #   forbidden_phrases: list[str]
    #   preferred_swimmer_address:
    #       first_name | last_name | surname_only | nickname
    voice_profile: dict = field(default_factory=dict)
    # ---- Brand DNA capture (Step 1 of roadmap; all optional) ----
    # Populated by mediahub.brand.dna_capture.capture_brand_dna() when
    # the user runs "Capture from website" on /organisation. Old club
    # profile JSONs without these keys still load because from_dict
    # filters unknown keys and dataclass defaults fill missing ones.

    brand_voice_summary: str = ""
    brand_keywords: list[str] = field(default_factory=list)
    brand_palette_extracted: dict = field(default_factory=dict)
    brand_logo_url: str = ""
    brand_typography_hint: str = ""
    brand_phrases_to_avoid: list[str] = field(default_factory=list)
    brand_phrases_to_use: list[str] = field(default_factory=list)
    brand_source_url: str = ""
    brand_captured_at: str = ""
    brand_capture_status: str = ""

    # ---- Unified palette resolution (palette selector fix) -----------------
    # ``brand_palette_extracted`` is now AI-decided across EVERY source the
    # org provided (website + socials + brand guidelines doc + uploaded
    # logos), not just the website. ``brand_palette_manual`` carries the
    # user's confirmation override from /organisation/setup — when present
    # it wins per-slot over the AI's pick. ``brand_palette_sources`` keeps
    # the raw per-source colour lists so the UI can show the user where
    # each candidate came from. ``brand_palette_use_fourth`` mirrors the
    # confirmation tickbox: it gates whether the optional 4th brand colour
    # is rendered downstream.
    brand_palette_manual: dict = field(default_factory=dict)
    brand_palette_use_fourth: bool = False
    brand_palette_sources: dict = field(default_factory=dict)
    brand_palette_reasoning: str = ""

    # ---- Social links (used by brand.social_dna for first-run setup) ----
    # Keys: instagram | facebook | twitter | tiktok | linkedin.
    # Values are full URLs. Empty/missing keys are simply not used.
    social_links: dict = field(default_factory=dict)

    # ---- AI-interpreted brand guidelines document (optional upload) ----
    # Populated by brand.guidelines.ingest_guidelines_file when the user
    # uploads a style-guide PDF/DOCX/ZIP/etc. on /organisation/setup or
    # /organisation. The structured dict is consumed by every content
    # tool via brand.context.brand_context_for_llm(profile).
    brand_guidelines: dict = field(default_factory=dict)
    brand_guidelines_raw_excerpt: str = ""
    brand_guidelines_filename: str = ""
    brand_guidelines_uploaded_at: str = ""
    brand_guidelines_status: str = ""
    brand_guidelines_extractor: str = ""
    brand_guidelines_byte_size: int = 0

    # Non-negotiable rules extracted from brand_guidelines_raw_excerpt as a
    # dedicated second LLM pass. Each entry is one literal MUST / NEVER /
    # ALWAYS / REQUIRED / SHALL statement from the user's uploaded
    # document. brand.context surfaces these at the TOP of every system
    # prompt with explicit override framing so the AI cannot quietly drown
    # them out under website-derived voice signals.
    brand_guidelines_mandatory_rules: list[str] = field(default_factory=list)

    # ---- Multi-logo upload (D1) -----------------------------------------
    # Each entry: {logo_id, original_filename, stored_path, mime,
    # byte_size, uploaded_at, label, ai_description, ai_dominant_colours}.
    # The AI description + dominant colours come from a vision LLM pass
    # when available so downstream image/motion generators can pick the
    # right logo variant (full-colour vs mono, wordmark vs icon, etc.)
    # without the user having to label each file manually.
    brand_logos: list[dict] = field(default_factory=list)

    # ---- Per-link capture state (B11) -----------------------------------
    # Mirrors social_links but carries the AI's interpretation outcome
    # per link: which playbook succeeded, when it last validated, the
    # last block/auth/rate-limit status, and a per-link voice digest.
    # Schema: {platform: {url, status, playbook_domain, last_attempt_at,
    # last_success_at, voice_digest}}.
    link_capture_state: dict = field(default_factory=dict)

    # ---- Derived operating profile (one-shot LLM derivation, cached) ----
    # Populated by brand.derived.derive_operating_profile at profile-save
    # time. Contains per-org tone prose, achievement priority weights,
    # achievement type phrases, and per-artefact creative intents.
    # Consumers go through brand.derived.<helper>_for(profile, key,
    # default) so when this cache is missing (older profiles, no LLM
    # configured), the hardcoded constants in the consumer modules are
    # used as fallbacks. This keeps the system AI-driven where context
    # exists, deterministic where it doesn't.
    brand_operating_profile: dict = field(default_factory=dict)

    # ---- Per-org Buffer access token (multi-tenant publishing) ----
    # Each ClubProfile carries its OWN Buffer personal access token.
    # This is the multi-tenant-safe model: when MediaHub serves many
    # clubs from one deployment, each club connects their own Buffer
    # account — content is NEVER channelled through a shared Buffer
    # account (which would violate Buffer's TOS and conflate every
    # club's posting queue).
    #
    # Single-tenant self-hosted deployments may set BUFFER_ACCESS_TOKEN
    # in the environment instead; the resolver in web.py falls back to
    # the env var when this field is empty. That model is safe because
    # operator IS the user.
    #
    # Connection happens inline inside the schedule modal, never in a
    # settings page (per the operator-config rewrite). Users who don't
    # use Buffer at all can fall through to the download-and-post-
    # manually path.
    buffer_access_token: str = ""

    # ---- P2.2/P2.3: autonomous publishing targets (optional) ----
    # The Buffer channel ids autonomous posts may go to, chosen by a human in
    # Settings → Autonomy. Empty (the default) means autonomy can auto-APPROVE
    # gate-passing cards but never place them anywhere — publishing stays a
    # human act until someone explicitly picks channels. Never auto-connected.
    autonomy_channel_ids: list[str] = field(default_factory=list)

    # ---- Step 2: Voice Imitation (all optional, backward-compatible) ----
    # Raw example captions pasted by the user (5-20 past social posts).
    voice_examples: list[str] = field(default_factory=list)

    # Structured voice profile computed by brand.voice_imitation.analyse_examples().
    # Keys: sentence_length_avg, sentence_length_p90, emoji_rate_per_caption,
    # hashtag_count_avg, characteristic_openers, characteristic_closers,
    # forbidden_phrases, preferred_swimmer_address.
    voice_profile: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ClubProfile":
        # Tolerant load: ignore unknown keys, default missing ones.
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})

    # ----- runtime: matches V3 ClubRoster API for drop-in replacement -----

    def is_ours(self, club_code: Optional[str], asa_id: Optional[str]) -> bool:
        if club_code and club_code in self.exclude_codes:
            return False
        if club_code:
            return club_code in self.club_codes
        if asa_id and asa_id in self.known_asa_ids:
            return True
        return False

    def filter_results(
        self, results, attr_club: str = "club_code", attr_asa: str = "asa_id"
    ) -> list:
        keep = []
        for r in results:
            cc = getattr(r, attr_club, None)
            # Result has swimmer_key, not asa_id directly — caller passes
            # already-resolved asa via attr_asa name when needed.
            asa = getattr(r, attr_asa, None) if hasattr(r, attr_asa) else None
            if self.is_ours(cc, asa):
                keep.append(r)
        return keep

    # ---- V7 helpers ----

    def get_achievement_priority(self, achievement_type: str) -> float:
        """Return the club-configured priority multiplier for an achievement type.

        Resolution order — AI-derived wins at every level so that any
        org with a derived operating profile gets the AI's judgment over
        the legacy hardcoded weights:

          1. ``brand_operating_profile.achievement_priorities[type]``
          2. ``brand_operating_profile.achievement_priorities['_default']``
          3. ``self.achievement_priorities[type]``         (legacy override)
          4. ``self.achievement_priorities['_default']``   (legacy default)
          5. ``1.0``
        """

        def _as_float(v) -> Optional[float]:
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        derived = (self.brand_operating_profile or {}).get("achievement_priorities") or {}
        if achievement_type in derived:
            f = _as_float(derived[achievement_type])
            if f is not None:
                return f
        if "_default" in derived:
            f = _as_float(derived["_default"])
            if f is not None:
                return f
        priorities = self.achievement_priorities or {}
        if achievement_type in priorities:
            f = _as_float(priorities[achievement_type])
            if f is not None:
                return f
        if "_default" in priorities:
            f = _as_float(priorities["_default"])
            if f is not None:
                return f
        return 1.0

    def get_brand_kit(self):
        """Return a BrandKit instance synthesised from this profile's data.

        Colour resolution order (manual override always wins so the user's
        confirmation on /organisation/setup can correct the AI):
          1. ``brand_palette_manual`` slot (primary/secondary/accent)
          2. ``brand_palette_extracted`` slot (AI's unified pick)
          3. legacy ``brand_primary`` / ``brand_secondary`` strings
          4. BrandKit defaults
        """
        from mediahub.brand.kit import BrandKit
        from mediahub.brand.palette import effective_palette

        bk_data = dict(self.brand_kit or {})
        palette = effective_palette(
            manual=self.brand_palette_manual,
            extracted=self.brand_palette_extracted,
        )
        primary = palette.get("primary") or bk_data.get("primary_colour") or self.brand_primary
        secondary = (
            palette.get("secondary") or bk_data.get("secondary_colour") or self.brand_secondary
        )
        accent = palette.get("accent") or bk_data.get("accent_colour")

        merged = {
            "profile_id": self.profile_id,
            "display_name": bk_data.get("display_name") or self.display_name,
            "primary_colour": primary,
            "secondary_colour": secondary,
            "accent_colour": accent,
            "logo_svg": bk_data.get("logo_svg"),
            "governing_body": bk_data.get("governing_body") or (self.governing_body or None),
            "short_name": bk_data.get("short_name") or (self.short_name or None),
            # Carry the cached Adaptive Theming Engine palette through so
            # ensure_derived_palette() returns it directly instead of
            # re-running the ~300ms HCT/MD3/repair pipeline on every
            # _layout() call. Without this, every HTML page paid the
            # full theming cost — see scripts/perf/baseline.md.
            "derived_palette": bk_data.get("derived_palette"),
        }
        return BrandKit.from_dict(merged)

    def get_tone(self):
        """Return the active Tone enum for this profile."""
        from mediahub.brand.tone import tone_from_str

        return tone_from_str(self.tone or self.caption_tone or "warm-club")

    def is_ready(self) -> bool:
        """True when there is enough context to generate on-brand content.

        Requires a real organisation name plus at least one of:
        - a captured brand voice summary (from website / socials),
        - an AI-extracted or manually confirmed palette (manual-mode
          setup picks colours by hand — that's as strong a brand signal
          as an AI extraction),
        - an analysed voice_profile,
        - pasted voice_examples (>=3),
        - a non-default tone_notes block.

        This is what the routing gate consults before unlocking content
        production. The point is to stop the user from generating
        anonymous, generic content before the system knows who they are.
        """
        name_ok = bool((self.display_name or "").strip())
        if not name_ok:
            return False
        brand_ok = bool(
            (self.brand_voice_summary or "").strip()
            or self.brand_palette_extracted
            or self.brand_palette_manual
            or self.brand_keywords
        )
        voice_ok = bool(self.voice_profile) or len(self.voice_examples or []) >= 3
        notes_ok = len((self.tone_notes or "").strip()) >= 30
        guidelines_ok = bool(self.brand_guidelines)
        return brand_ok or voice_ok or notes_ok or guidelines_ok


# ---------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------


def _profiles_dir() -> Path:
    # Priority: explicit override > DATA_DIR (persistent disk) > source-relative fallback.
    p = os.environ.get("SWIM_CONTENT_PROFILES_DIR")
    if p:
        d = Path(p)
    elif os.environ.get("DATA_DIR"):
        d = Path(os.environ["DATA_DIR"]) / "club_profiles"
    else:
        d = Path(__file__).resolve().parents[1] / "club_profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_profiles() -> list[ClubProfile]:
    out = []
    for f in sorted(_profiles_dir().glob("*.json")):
        try:
            out.append(ClubProfile.from_dict(json.loads(f.read_text())))
        except Exception:
            continue
    return out


def load_profile(profile_id: str) -> Optional[ClubProfile]:
    p = _profiles_dir() / f"{profile_id}.json"
    if not p.exists():
        return None
    try:
        return ClubProfile.from_dict(json.loads(p.read_text()))
    except Exception:
        return None


def save_profile(profile: ClubProfile) -> Path:
    p = _profiles_dir() / f"{profile.profile_id}.json"
    p.write_text(json.dumps(profile.to_dict(), indent=2))
    return p


# Default achievement-priority weights (used when a profile is
# created via seed_coma_profile_if_empty or any other helper).
# These are generic and not tied to any specific club.
_DEFAULT_PRIORITIES = {
    "pb_confirmed": 1.5,
    "first_sub_barrier": 1.3,
    "biggest_drop_of_meet": 1.3,
    "medal_gold": 1.0,
    "medal_silver": 0.8,
    "medal_bronze": 0.6,
    "qualifying_time": 0.7,
    "qual_hit_in_window": 0.7,
    "qual_hit_out_of_window": 0.5,
    "top_of_field_top_3": 0.7,
    "top_of_field_top_5": 0.6,
    "top_of_field_top_10": 0.5,
    "fastest_since_date": 1.0,
    "multi_pb_weekend": 1.2,
    "return_to_form": 1.1,
    "_default": 1.0,
}


def seed_default_profiles() -> None:
    """
    V8.1: never auto-seeds any specific club. Empty-state UI prompts
    the user to create their own profile (see web.py).
    """
    return


def seed_coma_profile_if_empty() -> ClubProfile:
    """
    Seed City of Manchester Aquatics profile when explicitly requested.
    Returns the profile (existing or freshly created).
    """
    existing = load_profile("coma")
    if existing:
        return existing
    profile = ClubProfile(
        profile_id="coma",
        display_name="City of Manchester Aquatics",
        short_name="COMA",
        club_codes=["CMA", "Co Manch Aq", "COMA"],
        brand_primary="#003DA5",
        brand_secondary="#FFD700",
        caption_tone="warm-club",
        tone="warm-club",
        governing_body="Swim England",
        country="United Kingdom",
        notes="City of Manchester Aquatics — quick-start profile.",
        achievement_priorities=_DEFAULT_PRIORITIES,
    )
    save_profile(profile)
    return profile


def detect_likely_profile(meet_clubs: dict, meet_host_code: Optional[str]) -> Optional[str]:
    """Given a parsed meet, suggest which existing profile is most likely
    the user's club. Returns profile_id or None."""
    profiles = list_profiles()
    best = None
    best_score = 0
    for prof in profiles:
        score = 0
        for cc in prof.club_codes:
            if cc in meet_clubs:
                score += 5
            if cc == meet_host_code:
                # If the user's own club is the host, that's still ok but
                # not a higher signal than just being in the meet.
                score += 1
        if score > best_score:
            best, best_score = prof, score
    return best.profile_id if best else None
