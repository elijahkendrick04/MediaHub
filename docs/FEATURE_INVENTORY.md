# Feature Inventory

User-visible features, mapped to the routes / modules that implement them.

| Feature | Route / Entry | Module |
|---|---|---|
| Upload meet results | POST `/upload` | `mediahub.web.web::upload_post` |
| Watch upload progress | GET `/runs/<id>` + `/api/runs/<id>/status` | `mediahub.web.web::run_status` |
| Review generated cards | GET `/review/<id>` | `mediahub.web.web::review` |
| Edit a card caption | POST `/api/runs/<id>/cards/<card_id>` | `mediahub.web.web` |
| Download pack ZIP | GET `/api/runs/<id>/export` | `mediahub.web.web::export_run` |
| Inspect detector trace | GET `/api/runs/<id>/trust` | `mediahub.web.web` |
| Privacy: list runs | GET `/privacy` | `mediahub.web.web` |
| Privacy: delete run | POST `/privacy/run/<id>/delete` | `mediahub.web.web` |
| Privacy: clear PB cache | POST `/privacy/cache/clear` | `mediahub.web.web` |
| Ground-truth eval | GET/POST `/ground-truth/<id>` | `mediahub.web.ground_truth` |
| Brand kit upload | POST `/api/brand-kit/upload` | `mediahub.web.brand_kit_upload` |
| Live AI caption | POST `/api/ai-caption` | `mediahub.web.ai_caption` |
| Health check | GET `/healthz` | `mediahub.web.web` |
| Research roadmap | GET `/research` | `mediahub.web.web` |
| Voice list | GET `/api/voices` | `mediahub.voice.learned.store` |
| Media library | GET/POST `/api/media-library` | `mediahub.media_library.store` |
| Cutout providers | config: `MEDIAHUB_CUTOUT_PROVIDER` | `mediahub.media_ai.providers.*` |
| Creative brief vision | internal | `mediahub.creative_brief.generator` |
| PB verification | internal | `mediahub.pb_discovery.discover` |
| Content pack ZIP | internal | `mediahub.content_pack.builder` |

> **Configuration:** Secrets and operator config are env-var only (see
> `.env.example` and `docs/ENV_INVENTORY.md`). The previous in-app
> `/settings/secrets` page was removed in the operator-config rewrite.

