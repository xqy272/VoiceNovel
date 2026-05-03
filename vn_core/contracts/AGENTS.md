# Contracts — AI Agent Guide

## Purpose
Single source of truth for all data shapes in VoiceNovel. Pydantic models define every artifact, request, response, and event that flows through the pipeline and server API.

## Key Concepts
- **Contracts-first**: No service creates ad-hoc dicts; all structured data uses these models
- **JSON Schema export**: `export_schema.py` generates JSON Schema + TypeScript types for all contracts
- **Immutable provenance**: Each contract carries version identifiers and hash fields for traceability

## Module: `vn_core/contracts/`

| File | Model(s) | Purpose |
|------|----------|---------|
| `segment.py` | `Segment` | Single text segment with stable segment_id |
| `text_adaptation.py` | `TextAdaptationOperation`, `AdaptationCategory`, `AdaptationScope` | Trackable text transformation |
| `reading_plan.py` | `ReadingPlanEntry`, `ReadingStyle`, `Enhancements`, `VoiceConstraints` | Per-segment speaker attribution and style |
| `voice_assignment.py` | `VoiceAssignment` | Character → voice binding with confidence |
| `speech_request.py` | `BackendSpeechRequest` | Final merged text + voice config for TTS |
| `audio_take.py` | `AudioTake` | Rendered audio file with metadata |
| `timing_entry.py` | `TimingEntry`, `AudioSpacing` | Per-segment timing with ms + sample offsets |
| `reader_manifest.py` | `ReaderManifest`, `ReaderPackageManifest`, `TimingProfile` | Reader package structure |
| `reader_adapter.py` | `ReaderAdapterRequest`, `ReaderAdapterResponse` | External reader ↔ Core Server protocol |
| `job_state.py` | `JobState`, `JobStage`, `JobStatus` | Pipeline job lifecycle |
| `generation_config.py` | `GenerationConfig` | Per-project generation settings |
| `provenance.py` | `ProvenanceEntry` | Pipeline stage provenance record |
| `exception_entry.py` | `ExceptionEntry` | Harness exception record |
| `memory_patch.py` | `MemoryPatch` | Book Model update patch |
| `context_spec.py` | `ContextSpec` | Service-declared context requirements |
| `context_capsule.py` | `ContextCapsule` | Assembled context data for a service |
| `export_schema.py` | — | JSON Schema + TypeScript type generator |

## Adding a New Contract
1. Create the Pydantic model in a new or existing file
2. Re-export from `__init__.py`
3. Add to `export_schema.py` schema list
4. Run `py -3.12 -m vn_core.contracts.export_schema data/schemas` to regenerate schemas

## Dependencies
- None (zero internal dependencies — contracts are the leaf layer)
