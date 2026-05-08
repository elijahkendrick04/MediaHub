# Route Inventory

All Flask routes registered by `mediahub.web.create_app()`.

_Auto-generated from `app.url_map` by `scripts/build_inventories.py`._

| Endpoint | Methods | Rule |
|---|---|---|
| `home` | `GET` | `/` |
| `api_media_library_upload` | `POST` | `/api/media-library` |
| `api_media_library_file` | `GET` | `/api/media-library/file/<asset_id>` |
| `api_cards` | `GET` | `/api/runs/<run_id>/cards` |
| `api_create_graphic` | `POST` | `/api/runs/<run_id>/cards/<card_id>/create-graphic` |
| `api_regenerate_graphic` | `POST` | `/api/runs/<run_id>/cards/<card_id>/regenerate` |
| `api_regenerate_variants` | `POST` | `/api/runs/<run_id>/cards/<card_id>/regenerate-variants` |
| `api_export` | `GET` | `/api/runs/<run_id>/export` |
| `api_recognition` | `GET` | `/api/runs/<run_id>/recognition` |
| `api_status` | `GET` | `/api/runs/<run_id>/status` |
| `api_live_caption` | `POST` | `/api/runs/<run_id>/swim/<swim_id>/caption` |
| `api_swim_trace` | `GET` | `/api/runs/<run_id>/swim/<swim_id>/trace` |
| `api_trust` | `GET` | `/api/runs/<run_id>/trust` |
| `api_venue_search` | `GET` | `/api/runs/<run_id>/venue-search` |
| `api_llm_status` | `GET` | `/api/settings/llm-status` |
| `api_visual_get` | `GET` | `/api/visual/<vid>` |
| `api_visual_png` | `GET` | `/api/visual/<vid>/png/<format_name>` |
| `api_workflow_set` | `POST` | `/api/workflow/<run_id>/<card_id>` |
| `api_workflow_mark_all_posted` | `POST` | `/api/workflow/<run_id>/mark-all-posted` |
| `pb_audit_page` | `GET` | `/audit/<run_id>` |
| `pb_ground_truth` | `GET,POST` | `/audit/<run_id>/ground-truth` |
| `pb_ignore` | `POST` | `/audit/<run_id>/ignore/<path:swimmer_key>` |
| `pb_verify_form` | `GET,POST` | `/audit/<run_id>/verify/<path:swimmer_key>` |
| `ground_truth` | `GET,POST` | `/ground-truth/<run_id>` |
| `health` | `GET` | `/health` |
| `healthz` | `GET` | `/healthz` |
| `make_page` | `GET` | `/make` |
| `media_library_page` | `GET` | `/media-library` |
| `content_pack` | `GET` | `/pack/<run_id>` |
| `content_pack_grouped` | `GET` | `/pack/<run_id>/grouped` |
| `content_pack_zip` | `GET` | `/pack/<run_id>/zip` |
| `privacy_page` | `GET` | `/privacy` |
| `privacy_cache_clear` | `POST` | `/privacy/cache/clear` |
| `privacy_delete_run` | `POST` | `/privacy/run/<run_id>/delete` |
| `recognition_page` | `GET` | `/recognition/<run_id>` |
| `research_page` | `GET` | `/research` |
| `review` | `GET` | `/review/<run_id>` |
| `run_status` | `GET` | `/runs/<run_id>` |
| `stub_session_update` | `GET` | `/session-update` |
| `settings_page` | `GET,POST` | `/settings` |
| `stub_sponsor_post` | `GET` | `/sponsor-post` |
| `spotlight_landing` | `GET` | `/spotlight` |
| `spotlight_view` | `GET` | `/spotlight/<run_id>/<path:swimmer_key>` |
| `static` | `GET` | `/static/<path:filename>` |
| `upload` | `GET,POST` | `/upload` |
| `upload_configure` | `GET,POST` | `/upload/configure` |
| `stub_weekend_preview` | `GET` | `/weekend-preview` |
