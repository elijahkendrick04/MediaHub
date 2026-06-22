"""
collab — the collaboration & review layer (roadmap 1.18).

MediaHub's own review layer on the shipped workflow spine: finer roles,
anchored comments / mentions / tasks, version history, element locks, and
expiring share links. Built so a committee can work the way it really does —
one volunteer drafts, a coach checks names, the chair approves.

Exposes (built incrementally across the 1.18 sub-builds):
  permissions  — role → capability matrix (the single source of truth for
                 what each workspace seat can do)
"""

from . import permissions

__all__ = ["permissions"]
