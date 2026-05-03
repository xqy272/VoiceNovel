# Pipeline — AI Agent Guide

## Purpose
End-to-end pipeline orchestration: takes a book from import through to packaged Reader output.

## Key Concepts
- **Cold Start Phases**: 4-phase startup (local → LLM scan → min buffer → background)
- **Chapter Bake**: Process a single chapter from segments to packaged output
- **Harness Gate**: All writes go through validation before committing to store

## Module: `vn_core/pipeline/`

### `cold_start(book_id, source_path, store, llm_gateway) -> dict`
Phase 1: Import + segment + adapt + fallback voice (no LLM needed)
Phase 2: LLM quick scan of current chapter (character extraction)
Phase 3: Process minimum playable buffer (first 20-40 segments)
Phase 4: Background full-chapter processing

### `bake_chapter(book_id, chapter_id, store, llm_gateway) -> dict`
Full processing of a single chapter:
1. Load paragraphs from store
2. Adapt (pre_segment) + segment
3. Adapt (pre_tts) each segment
4. Fetch context capsules
5. Run reading planner
6. Cast voices for all characters
7. Compose TTS requests
8. Synthesize via Speech Gateway
9. Build timing
10. Generate cleaned XHTML
11. Package as Reader Package
12. Commit all artifacts via Harness Gate

### Pipeline Flow
```
import_book → store chapters/paragraphs
  → segment_chapter → adapt_pre_tts
  → scanner.scan_chapter (populate characters/glossary)
  → planner.plan_chapter
  → voice_casting.cast_all_characters
  → tts_composer.compose + gateway.synthesize
  → timing.build_timing
  → xhtml.generate_cleaned_html
  → packaging.build_reader_package
  → harness.commit all artifacts
```