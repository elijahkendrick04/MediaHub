"""
voice — Voice profile configuration for caption generation.
"""
from .profile import VoiceProfile, VoiceExemplar
from .store import load_voice_profile, save_voice_profile

__all__ = ["VoiceProfile", "VoiceExemplar", "load_voice_profile", "save_voice_profile"]
