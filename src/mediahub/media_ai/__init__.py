"""media_ai — Claude Sonnet wrapper + background-removal providers.

Public API:
    llm.generate(messages, system=None, max_tokens=1024) -> str
    llm.generate_json(prompt, schema_hint, system=None) -> dict
    providers.get_bg_remover() -> BackgroundRemover
"""
from .llm import generate, generate_json, generate_vision, is_available

__all__ = ["generate", "generate_json", "generate_vision", "is_available"]
