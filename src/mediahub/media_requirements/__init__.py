"""media_requirements — declares what media each content item needs and evaluates readiness."""

from .rules import (
    MediaRequirement,
    MediaRequirementSet,
    REQUIREMENT_RULES,
    requirements_for,
)
from .evaluator import evaluate, EvaluationResult

__all__ = [
    "MediaRequirement",
    "MediaRequirementSet",
    "REQUIREMENT_RULES",
    "requirements_for",
    "evaluate",
    "EvaluationResult",
]
