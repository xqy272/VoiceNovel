# Server API — AI Agent Guide

## Purpose
FastAPI REST + WebSocket server exposing the VoiceNovel pipeline as HTTP endpoints. Serves reader content, timing, audio, and project management APIs.

## Key Concepts
- **REST endpoints**: CRUD for projects, chapters, generation configs, jobs, and reader assets
- **WebSocket**: `/ws/pipeline` for real-time pipeline progress and preflight checks
- **Reader adapter**: `/api/reader-adapter` provides a Koodo-compatible status/chapter endpoint
- **CORS**: Open CORS for development (all origins, all methods)

## Module: `vn_server/api/`

### `create_app(data_dir, store_path) -> FastAPI`
Factory function that creates the FastAPI app with all routes.

### REST Endpoints

#### Project Management
- `GET /` — Server status
- `GET /health` — Preflight health check
- `GET /api/projects` — List all projects with chapters
- `POST /api/projects` — Import a book (CreateProjectRequest)
- `GET /api/projects/{book_id}` — Project detail with characters and artifacts

#### Generation Config
- `GET /api/projects/{book_id}/generation-config` — Get config
- `POST /api/projects/{book_id}/generation-config` — Update config

#### Chapters & Pipeline
- `GET /api/projects/{book_id}/chapters` — List chapters
- `POST /api/projects/{book_id}/chapters/{chapter_id}/segment` — Segment a chapter
- `POST /api/projects/{book_id}/chapters/{chapter_id}/plan` — Plan a chapter
- `POST /api/projects/{book_id}/chapters/{chapter_id}/tts` — TTS a chapter
- `POST /api/projects/{book_id}/chapters/{chapter_id}/package` — Package a chapter

#### Reader Assets
- `GET /api/projects/{book_id}/chapters/{chapter_id}/content` — Cleaned HTML
- `GET /api/projects/{book_id}/chapters/{chapter_id}/timing` — Timing JSON
- `GET /api/projects/{book_id}/chapters/{chapter_id}/audio` — Chapter audio file

#### Jobs
- `POST /api/jobs` — Submit a pipeline job (async background task)
- `GET /api/jobs/{job_id}` — Get job status

#### Voice
- `GET /api/voices?backend=` — List available voices

#### Reader Adapter
- `POST /api/reader-adapter` — Koodo-compatible reader protocol

#### Bake (Full Pipeline)
- `POST /api/bake` — Run full chapter bake synchronously

### WebSocket: `/ws/pipeline`
Commands:
- `{"command": "status"}` — Returns session state
- `{"command": "preflight"}` — Runs preflight checks

### Request Models
- `CreateProjectRequest`: source_path, title, book_id
- `JobSubmitRequest`: book_id, chapter_id, stage, priority, generation_config_id, reading_profile
- `BakeChapterRequest`: book_id, chapter_id, generation_config_id, reading_profile
- `GenerationConfigRequest`: generation_config_id, reading_profile, execution_mode, tts_engine, cache_buster, metadata
- `ReaderAdapterRequestModel`: book_id, chapter_id, position_segment_id, position_time_ms, action, capabilities

## Dependencies
- `fastapi` — Web framework
- `vn_core.pipeline` — Pipeline (bake_chapter)
- `vn_core.store` — ProjectStore
- `vn_core.importers` — import_book
- `vn_core.segmenter` — ChineseSegmenter
- `vn_core.planner` — ReadingPlanner
- `vn_core.render` — SpeechGateway, TTSInputComposer
- `vn_core.voice` — VoiceRegistry
- `vn_core.packaging` — PackagingService
- `vn_core.orchestration` — Orchestrator
- `vn_core.preflight` — PreflightCheck
- `vn_core.llm_gateway` — LLMGateway
