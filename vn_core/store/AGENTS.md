# Project Store — AI Agent Guide

## Purpose
SQLite-backed single source of truth for all project data. Every artifact, job, character, decision, and provenance record lives here. Services never write directly — they go through the Harness Gate.

## Key Concepts
- **Artifact superseding**: Writing a new `active` artifact auto-supersedes the previous one for same (book_id, artifact_type, unit_id)
- **WAL mode**: Write-Ahead Logging for concurrent read/write safety
- **Three table groups**: Artifact tables (artifacts, dependencies, jobs, configs, provenance, exceptions), Book structure tables (books, chapters, paragraphs), Book Model tables (characters, glossary, pronunciation, decisions, scenes, voice_assignments)

## Module: `vn_core/store/`

### Artifact Operations
- `write_artifact(book_id, artifact_version_id, artifact_type, unit_id, ...)` — Write + auto-supersede
- `add_dependency(artifact_version_id, depends_on_artifact_version_id, ...)` — Record artifact dependency
- `get_active_artifact(book_id, artifact_type, unit_id)` — Get current active artifact

### Job Operations
- `upsert_job(job: JobState)` — Create or update a pipeline job
- `get_job(job_id)` — Get job by ID

### Generation Config
- `upsert_generation_config(config: GenerationConfig)` — Save generation settings
- `get_generation_config(book_id, generation_config_id)` — Load generation settings

### Book Structure
- `upsert_book / upsert_chapter / upsert_paragraph` — Write book structure
- `get_book / get_chapters / get_paragraphs` — Read book structure

### Book Model
- `upsert_character / get_characters` — Character registry
- `upsert_decision` — Store pipeline decisions
- `upsert_scene_snapshot / get_scene_snapshot` — Chapter scene state
- `upsert_voice_assignment` — Character voice bindings
- Glossary and pronunciation tables managed directly via conn

## Schema Notes
- `characters.names` and `characters.traits` are stored as JSON arrays (string columns)
- `decisions.value` is a JSON object column
- All timestamps default to `datetime('now')`
- Foreign keys are enabled via `PRAGMA foreign_keys=ON`

## Dependencies
- `vn_core.contracts.generation_config` — GenerationConfig model
- `vn_core.contracts.job_state` — JobState model
