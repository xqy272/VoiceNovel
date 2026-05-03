# VoiceNovel — AI Agent Documentation

> This document is the entry point for AI coding agents working on VoiceNovel.
> Read this first, then consult module-level `AGENTS.md` files for specifics.

## Architecture Overview

VoiceNovel is an AI-native multi-role audiobook system. Core architecture:

```
┌─────────────────────────────────────────────────────────────┐
│                    vn_server (FastAPI REST+WS)               │
├─────────────────────────────────────────────────────────────┤
│                     Pipeline Orchestrator                      │
│  (cold_start → book_scan → plan_chapter → render → package)  │
├──────────┬──────────┬──────────┬──────────┬────────────────┤
│  Import  │ Segment  │  Adapt    │  Planner │   Render       │
│  (TXT/   │          │          │ (speaker │  (TTS Gateway   │
│   EPUB)  │          │          │  attrib) │   + Composer)  │
├──────────┴──────────┴──────────┴──────────┴────────────────┤
│                  Context Fetch Engine                         │
│           (ContextSpec → BookModel → ContextCapsule)         │
├──────────────────────────────────────────────────────────────┤
│                        Harness Gate                          │
│            (validate → commit → provenance → exceptions)    │
├──────────────────────────────────────────────────────────────┤
│                     Project Store (SQLite)                   │
│  artifacts | jobs | characters | glossary | decisions | ... │
└──────────────────────────────────────────────────────────────┘
```

## Module Map

| Module | Path | Purpose | AGENTS.md |
|--------|------|---------|-----------|
| Contracts | `vn_core/contracts/` | Pydantic models — single source of truth for data shapes | Yes |
| Store | `vn_core/store/` | SQLite persistence layer | Yes |
| Importers | `vn_core/importers/` | TXT/EPUB → structured chapters | Yes |
| Segmenter | `vn_core/segmenter/` | Chinese clause/sentence splitting | Yes |
| Adaptation | `vn_core/adaptation/` | Text cleanup, punctuation fix, TTS normalization | Yes |
| Planner | `vn_core/planner/` | Speaker attribution, reading style | Yes |
| Voice | `vn_core/voice/` | Voice registry + casting | Yes |
| LLM Gateway | `vn_core/llm_gateway/` | Unified LLM interface with caching/fallback | Yes |
| Render | `vn_core/render/` | Speech Gateway + TTS adapters + input composer | Yes |
| Timing | `vn_core/timing/` | Build timing.json from audio durations | Yes |
| Packaging | `vn_core/packaging/` | Assemble Reader Package | Yes |
| Book Model | `vn_core/book_model/` | Runtime projection over Store | Yes |
| Context | `vn_core/context/` | Context Fetch Engine | Yes |
| Scanner | `vn_core/scanner/` | LLM Book Scanner (character/term extraction) | Yes |
| XHTML | `vn_core/xhtml/` | Cleaned HTML with data-seg-id spans | Yes |
| Cost Planner | `vn_core/cost_planner/` | Token/audio cost estimation with rate cards | Yes |
| Harness | `vn_core/harness/` | Write gate: validate → commit → provenance | Yes |
| Pipeline | `vn_core/pipeline/` | End-to-end pipeline + cold start (4-phase) | Yes |
| Preflight | `vn_core/preflight/` | System readiness checks before generation | Yes |
| Orchestration | `vn_core/orchestration/` | Job scheduling, execution loop, prefetch policy | Yes |
| Server | `vn_server/api/` | FastAPI REST + WebSocket + reader endpoints | Yes |
| Export | `vn_core/export/` | M4B, Audiobookshelf, DAW package generators | Yes |
| Schema Export | `vn_core/contracts/export_schema.py` | JSON Schema + TypeScript type generation | No |
| Koodo Adapter | `integrations/koodo_package_adapter/` | Reader Package → Koodo format | Yes |
| Koodo Voice | `integrations/koodo_voice_plugin/` | VoiceNovel TTS → Koodo voice config | Yes |
| Web Reader | `web_reader/` | Svelte 5 reference reader client | Yes |

## Key Principles

1. **Store is sole truth source** — Services never write directly; they go through Harness Gate
2. **Services are stateless** — Input + ContextCapsule → Output + proposed patches
3. **Segment IDs are stable** — Once `segmenter_version` is locked, IDs never change
4. **BackendSpeechRequest.text is final merged text** — TTS adapters don't see source text
5. **All LLM calls go through LLM Gateway** — Never direct SDK connections
6. **Cold start has 4 phases** — Local (fast) → LLM quick scan → minimum buffer → background improvement
7. **Concurrent TTS synthesis** — `bake_chapter()` uses `asyncio.gather` with semaphore for parallel TTS
8. **Provenance per stage** — Each pipeline stage writes provenance via Harness Gate

## Data Flow (End-to-End)

```
Book Import → Paragraphs → Text Adaptation (pre_segment)
  → Chinese Segmenter → Segments → Text Adaptation (pre_tts)
  → Context Fetch Engine → ContextCapsule
  → Reading Planner → ReadingPlanEntry per segment
  → Voice Casting → VoiceAssignment per character
  → TTS Input Composer → BackendSpeechRequest per segment
  → Speech Gateway (concurrent) → AudioTake per segment
  → Timing Builder → TimingEntry per segment
  → Cleaned XHTML Generator → HTML with data-seg-id
  → Packaging Service → Reader Package (manifest + all files)
  → Harness Gate → Write all artifacts + decisions + provenance to Store
```

## Cold Start (4-Phase)

```
Phase 1 (local):   import_book() + segment + adapt → fallback voice (no LLM, no network)
Phase 2 (scan):     BookScanner.scan_chapter() → populate characters + glossary
Phase 3 (buffer):   Render first N segments (MIN_BUFFER_SEGMENTS=30) for immediate playback
Phase 4 (full):     Pipeline.bake_chapter() → full chapter processing with concurrent TTS
```

## Running Tests

```bash
py -3.12 -m pytest tests/ -v
```

## Running the Server

```bash
py -3.12 -m vn_server
# or with auto-reload:
py -3.12 -m vn_server --reload
```

## Lint

```bash
py -3.12 -m ruff check vn_core/ vn_server/ integrations/ tests/
```

## Running the Web Reader

```bash
cd web_reader
npm install
npm run dev    # Dev server on :3000, proxies /api to :5000
npm run build  # Production build to dist/
```

## JSON Schema / TypeScript Export

```bash
py -3.12 -m vn_core.contracts.export_schema data/schemas  # Generate JSON schemas
```

## Relevant Files

- `vn_core/contracts/export_schema.py` — JSON Schema + TS type generator
- `vn_core/pipeline/pipeline.py` — Pipeline with cold_start() and concurrent bake_chapter()
- `vn_core/export/m4b.py` — M4B audiobook export
- `vn_core/export/audiobookshelf.py` — Audiobookshelf export
- `vn_core/export/daw.py` — DAW package export
- `integrations/koodo_package_adapter/__init__.py` — Koodo format converter
- `integrations/koodo_voice_plugin/__init__.py` — Koodo voice config generator
- `web_reader/src/App.svelte` — Main reader layout with localStorage resume