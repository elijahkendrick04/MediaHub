"""
voice/learned — V7.5 learned voice engine.

Public API
----------
from mediahub.voice.learned.induce   import induce_voice
from mediahub.voice.learned.store    import save_voice, load_voice, list_voices
from mediahub.voice.learned.render   import render_caption
from mediahub.voice.learned.feature_extract import extract_features
from mediahub.voice.learned.models   import VoiceProfile, VoiceFeatures
"""
from .models import VoiceProfile, VoiceFeatures

__all__ = ["VoiceProfile", "VoiceFeatures"]
