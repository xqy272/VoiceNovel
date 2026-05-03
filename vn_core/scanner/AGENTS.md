# Scanner — AI Agent Guide

## Purpose
LLM-based book scanner that extracts characters, terms, aliases, and scene summaries from book text.

## Key Concepts
- **Book Scan**: One-time or incremental extraction via LLM
- **Characters**: names, aliases, traits, first_seen chapter
- **Glossary**: terms, categories, definitions
- **Scene Summaries**: per-chapter scene snapshots

## Module: `vn_core/scanner/`

### `scan_book(book_id, chapters_text, llm_gateway, store) -> dict`
1. For each chapter, send text to LLM with extraction prompt
2. Parse LLM JSON output for characters, terms, scenes
3. Write extracted data to Project Store via Harness Gate
4. Return extraction results

## Cold Start Phases
- Phase 1 (local): Segment and adapt without LLM — immediate
- Phase 2 (LLM quick scan): Run scanner on current chapter + context window
- Phase 3: Minimum playable buffer with fallback voices
- Phase 4: Background improvement with full book scan