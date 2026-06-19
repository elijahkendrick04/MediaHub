"""media_library — MediaAsset CRUD + AI description parsing + selector + editor.

The non-destructive photo editor (roadmap 1.3) lives in :mod:`.photo_ops` (the
pure engine) and :mod:`.photo_edit` (asset integration); HEIC ingest is in
:mod:`.heic`. They're imported lazily by callers to keep this package's import
light, but the key names are re-exported here for convenience.
"""

from .models import MediaAsset, ASSET_TYPES, PERMISSION_STATUSES, APPROVAL_STATUSES
from .store import MediaLibraryStore, get_store
from .describe import parse_description
from .selector import select_assets, score_asset
from .photo_ops import EditRecipe, EditOp, enhance_auto, compose_grid
from .photo_edit import effective_image_path, recipe_for_asset, save_recipe

__all__ = [
    "MediaAsset",
    "ASSET_TYPES",
    "PERMISSION_STATUSES",
    "APPROVAL_STATUSES",
    "MediaLibraryStore",
    "get_store",
    "parse_description",
    "select_assets",
    "score_asset",
    "EditRecipe",
    "EditOp",
    "enhance_auto",
    "compose_grid",
    "effective_image_path",
    "recipe_for_asset",
    "save_recipe",
]
