"""
voice/learned/models.py — VoiceProfile and VoiceFeatures dataclasses.

These are the V7.5 learned-voice schema types.  Nothing here references
any specific named voice; all slug/label data lives in the seed JSON files.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class VoiceFeatures:
    """Statistically-induced style features from exemplar posts."""

    avg_sentence_len: float = 0.0
    capitalisation_style: str = "sentence"     # "sentence" | "title" | "all_caps_emphasis"
    emoji_density: float = 0.0                 # emojis per 100 chars
    emoji_palette: List[str] = field(default_factory=list)
    hashtag_density: float = 0.0              # hashtags per 100 chars
    common_hashtags: List[str] = field(default_factory=list)
    starting_phrases: List[str] = field(default_factory=list)
    sign_offs: List[str] = field(default_factory=list)
    name_format: str = "first_only"            # "first_only" | "full" | "first_initial"
    time_format: str = "m:ss.cc"               # how times are written in posts
    achievement_words: List[str] = field(default_factory=list)
    exclamation_density: float = 0.0           # exclamation marks per sentence
    second_person_density: float = 0.0         # "you/your" per 100 words

    # ------------------------------------------------------------------ #
    # Serialisation                                                        #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        return {
            "avg_sentence_len": self.avg_sentence_len,
            "capitalisation_style": self.capitalisation_style,
            "emoji_density": self.emoji_density,
            "emoji_palette": self.emoji_palette,
            "hashtag_density": self.hashtag_density,
            "common_hashtags": self.common_hashtags,
            "starting_phrases": self.starting_phrases,
            "sign_offs": self.sign_offs,
            "name_format": self.name_format,
            "time_format": self.time_format,
            "achievement_words": self.achievement_words,
            "exclamation_density": self.exclamation_density,
            "second_person_density": self.second_person_density,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VoiceFeatures":
        return cls(
            avg_sentence_len=float(d.get("avg_sentence_len", 0.0)),
            capitalisation_style=str(d.get("capitalisation_style", "sentence")),
            emoji_density=float(d.get("emoji_density", 0.0)),
            emoji_palette=list(d.get("emoji_palette", [])),
            hashtag_density=float(d.get("hashtag_density", 0.0)),
            common_hashtags=list(d.get("common_hashtags", [])),
            starting_phrases=list(d.get("starting_phrases", [])),
            sign_offs=list(d.get("sign_offs", [])),
            name_format=str(d.get("name_format", "first_only")),
            time_format=str(d.get("time_format", "m:ss.cc")),
            achievement_words=list(d.get("achievement_words", [])),
            exclamation_density=float(d.get("exclamation_density", 0.0)),
            second_person_density=float(d.get("second_person_density", 0.0)),
        )


@dataclass
class VoiceProfile:
    """A named, learned voice profile derived from exemplar posts."""

    voice_id: str                              # slug, e.g. "yourclub_warm"
    display_name: str = ""                     # human label, e.g. "Warm club voice"
    description: str = ""
    exemplars: List[str] = field(default_factory=list)   # raw post texts
    features: VoiceFeatures = field(default_factory=VoiceFeatures)
    created_at: str = ""
    updated_at: str = ""

    # ------------------------------------------------------------------ #
    # Serialisation                                                        #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        return {
            "voice_id": self.voice_id,
            "display_name": self.display_name,
            "description": self.description,
            "exemplars": self.exemplars,
            "features": self.features.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VoiceProfile":
        features_raw = d.get("features", {})
        features = (
            VoiceFeatures.from_dict(features_raw)
            if isinstance(features_raw, dict)
            else VoiceFeatures()
        )
        return cls(
            voice_id=str(d.get("voice_id", "")),
            display_name=str(d.get("display_name", "")),
            description=str(d.get("description", "")),
            exemplars=list(d.get("exemplars", [])),
            features=features,
            created_at=str(d.get("created_at", "")),
            updated_at=str(d.get("updated_at", "")),
        )


__all__ = ["VoiceFeatures", "VoiceProfile"]
