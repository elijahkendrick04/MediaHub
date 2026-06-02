"""
Typed schema for sport profiles.

A **sport profile** is the human-authored, version-controlled configuration that
tells the strategy brain what a given sport should post. It parameterises four
things *per post type* (the four axes the roadmap calls out):

  1. ``enabled``            — does this sport produce this post type at all?
  2. ``data_inputs``        — which ingestion inputs feed it (keys, not files).
  3. ``template_namespace`` — which graphic/reel template set renders it.
  4. ``default_autonomy``   — the starting ``AutonomyLevel`` for the post type.

A sport profile is the *strategy/config* object. It is complementary to — and
deliberately separate from — ``mediahub.recognition.registry.SportConfig``, which
is the *engine* object (the bundle of deterministic detectors, history provider,
and voice templates registered via ``register_sport``). ``SportProfile.engine_sport``
names the registered sport the profile draws its detections from, so the two stay
linked without merging two very different concerns (config vs. detector code).

Style matches the rest of the repo: plain ``@dataclass``, ``field(default_factory=…)``
for mutable defaults, and ``from_dict``/``to_dict`` round-trips that tolerate unknown
keys for forward/backward compatibility (cf. ``brand.kit.BrandKit``).

This module is inert scaffolding — nothing in the running product imports it yet.
See ``docs/SPORT_PROFILES.md`` for the authoring guide.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .autonomy import AutonomyLevel


@dataclass
class PostTypeConfig:
    """Per-post-type configuration inside a sport profile."""

    post_type: str
    enabled: bool = True
    data_inputs: list[str] = field(default_factory=list)
    template_namespace: str = ""
    default_autonomy: AutonomyLevel = AutonomyLevel.APPROVAL_REQUIRED

    @classmethod
    def from_dict(cls, post_type: str, data: dict) -> "PostTypeConfig":
        data = data or {}
        return cls(
            post_type=post_type,
            enabled=bool(data.get("enabled", True)),
            data_inputs=list(data.get("data_inputs", []) or []),
            template_namespace=str(data.get("template_namespace", "") or ""),
            default_autonomy=AutonomyLevel.from_str(data.get("default_autonomy")),
        )

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "data_inputs": list(self.data_inputs),
            "template_namespace": self.template_namespace,
            "default_autonomy": self.default_autonomy.value,
        }


@dataclass
class SportProfile:
    """A whole sport's posting configuration (one file per sport).

    ``engine_sport`` defaults to ``sport`` when omitted, so a profile whose slug
    already matches the ``register_sport`` name needs no extra wiring.
    """

    sport: str
    display_name: str
    engine_sport: str = ""
    governing_bodies: list[str] = field(default_factory=list)
    post_types: dict[str, PostTypeConfig] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.engine_sport:
            self.engine_sport = self.sport

    @classmethod
    def from_dict(cls, data: dict) -> "SportProfile":
        """Build a profile from a parsed YAML/JSON mapping, ignoring unknown keys."""
        data = data or {}
        sport = str(data.get("sport") or "").strip()
        if not sport:
            raise ValueError("sport profile is missing the required 'sport' field")
        raw_post_types = data.get("post_types") or {}
        post_types = {
            str(key): PostTypeConfig.from_dict(str(key), value)
            for key, value in raw_post_types.items()
        }
        return cls(
            sport=sport,
            display_name=str(data.get("display_name") or sport.title()),
            engine_sport=str(data.get("engine_sport") or ""),
            governing_bodies=list(data.get("governing_bodies", []) or []),
            post_types=post_types,
            notes=str(data.get("notes", "") or ""),
        )

    def to_dict(self) -> dict:
        return {
            "sport": self.sport,
            "display_name": self.display_name,
            "engine_sport": self.engine_sport,
            "governing_bodies": list(self.governing_bodies),
            "post_types": {k: v.to_dict() for k, v in self.post_types.items()},
            "notes": self.notes,
        }

    def enabled_post_types(self) -> list[str]:
        """Sorted keys of the post types this sport currently produces."""
        return sorted(k for k, v in self.post_types.items() if v.enabled)

    def autonomy_for(self, post_type: str) -> AutonomyLevel:
        """Default autonomy for a post type (gated default if not configured)."""
        cfg = self.post_types.get(post_type)
        return cfg.default_autonomy if cfg else AutonomyLevel.default()


__all__ = ["PostTypeConfig", "SportProfile"]
