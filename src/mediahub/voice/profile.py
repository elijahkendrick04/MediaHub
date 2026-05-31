"""
voice/profile.py — VoiceProfile and VoiceExemplar dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VoiceExemplar:
    """A pasted example post used for future few-shot LLM context."""

    title: str  # "Loughborough big PB post"
    source_url: str = ""
    text: str = ""  # the actual post text — used for future few-shot
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "source_url": self.source_url,
            "text": self.text,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VoiceExemplar":
        return cls(
            title=d.get("title", ""),
            source_url=d.get("source_url", ""),
            text=d.get("text", ""),
            notes=d.get("notes", ""),
        )


@dataclass
class VoiceProfile:
    """
    Club voice profile for caption generation.

    Used by brand/apply.py to:
    - Apply name_style (first_name | full_name | surname)
    - Apply emoji_level (none | sparing | moderate | heavy)
    - Append sign_off if set
    - Store preferred/banned phrases for future LLM use
    - Store exemplars for future few-shot context
    """

    profile_id: str
    tone: str = "warm-club"  # professional | hype | friendly | formal | warm-club | data-led
    emoji_level: str = "moderate"  # none | sparing | moderate | heavy
    preferred_phrases: list = field(default_factory=list)  # list[str]
    banned_phrases: list = field(default_factory=list)  # list[str]
    hashtag_style: str = "club_only"  # club_only | meet_specific | none | full
    name_style: str = "first_name"  # first_name | full_name | surname
    sign_off: str = ""  # e.g. "—YourClub" or empty
    exemplars: list = field(default_factory=list)  # list[VoiceExemplar]

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "tone": self.tone,
            "emoji_level": self.emoji_level,
            "preferred_phrases": self.preferred_phrases,
            "banned_phrases": self.banned_phrases,
            "hashtag_style": self.hashtag_style,
            "name_style": self.name_style,
            "sign_off": self.sign_off,
            "exemplars": [e.to_dict() if hasattr(e, "to_dict") else e for e in self.exemplars],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VoiceProfile":
        exemplars = []
        for e in d.get("exemplars", []):
            if isinstance(e, dict):
                exemplars.append(VoiceExemplar.from_dict(e))
            elif hasattr(e, "to_dict"):
                exemplars.append(e)
        return cls(
            profile_id=d.get("profile_id", ""),
            tone=d.get("tone", "warm-club"),
            emoji_level=d.get("emoji_level", "moderate"),
            preferred_phrases=d.get("preferred_phrases", []),
            banned_phrases=d.get("banned_phrases", []),
            hashtag_style=d.get("hashtag_style", "club_only"),
            name_style=d.get("name_style", "first_name"),
            sign_off=d.get("sign_off", ""),
            exemplars=exemplars,
        )

    def get_name(self, first_name: str, last_name: str) -> str:
        """Return the name formatted according to name_style."""
        if self.name_style == "full_name":
            return f"{first_name} {last_name}".strip()
        if self.name_style == "surname":
            return last_name.strip()
        return first_name.strip()  # default: first_name

    def apply_emoji(self, text: str) -> str:
        """Strip emojis from text if emoji_level is 'none'."""
        if self.emoji_level != "none":
            return text
        import re

        # Remove emoji unicode ranges
        # Use a broad emoji removal approach - encode/decode trick
        try:
            emoji_pattern = re.compile(
                "["
                "\U0001f300-\U0001faff"  # broad emoji block
                "\U00002702-\U000027b0"
                "\U000024c2-\U0001f251"
                "\U0001f600-\U0001f64f"  # emoticons
                "\U0001f680-\U0001f6ff"  # transport & map
                "\U0001f1e0-\U0001f1ff"  # flags
                "\U00002500-\U00002bef"  # various symbols
                "\U0001f900-\U0001f9ff"  # supplemental symbols
                "\U0001fa00-\U0001faff"  # chess symbols etc.
                "]+",
                flags=re.UNICODE,
            )
        except re.error:
            emoji_pattern = re.compile(
                "[\U0001f600-\U0001f64f\U0001f300-\U0001f5ff]+",
                flags=re.UNICODE,
            )
        return emoji_pattern.sub("", text).strip()

    def apply_sign_off(self, text: str) -> str:
        """Append sign_off to text if set."""
        if self.sign_off:
            return f"{text}\n{self.sign_off}"
        return text


__all__ = ["VoiceProfile", "VoiceExemplar"]
