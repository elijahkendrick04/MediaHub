"""
collab — the collaboration & review layer (roadmap 1.18).

MediaHub's own review layer on the shipped workflow spine: finer roles,
anchored comments / mentions / tasks, version history, element locks, and
expiring share links. Built so a committee can work the way it really does —
one volunteer drafts, a coach checks names, the chair approves.

Exposes (built incrementally across the 1.18 sub-builds):
  permissions  — role → capability matrix (the single source of truth for
                 what each workspace seat can do)
  threads      — anchored comments, tasks & reactions store
  mentions     — @mention parsing + resolution against workspace members
  revisions    — design-spec version history, diff & restore
  locks        — per-card element locks, enforced at edit time
"""

from . import locks, mentions, permissions, revisions, threads

__all__ = ["permissions", "threads", "mentions", "revisions", "locks"]
