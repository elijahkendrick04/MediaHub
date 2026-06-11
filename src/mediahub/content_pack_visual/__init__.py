"""content_pack_visual — attach generated visuals to content_pack items.

This is a thin overlay around ``content_pack.builder``. It:

1. takes the same ``run_data`` + ``profile_id`` used by ``build_grouped_pack``,
2. builds the pack as usual,
3. for each item that meets the recognition + media requirements, calls the
   creative_brief generator + graphic_renderer to attach a list of
   GeneratedVisual records to the item under the key ``visuals``.

It is *opt-in* — the existing pack builder remains unchanged. Web routes call
this module instead when they want visuals attached.
"""

from .integration import (
    attach_visuals_to_pack,
    create_visual_for_item,
    visuals_dir_for_run,
    persist_visual,
)

__all__ = [
    "attach_visuals_to_pack",
    "create_visual_for_item",
    "visuals_dir_for_run",
    "persist_visual",
]
