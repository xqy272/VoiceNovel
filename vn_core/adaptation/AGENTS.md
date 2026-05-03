# Text Adaptation — AI Agent Guide

## Purpose
Two-pass text normalization pipeline: pre-segment cleanup and pre-TTS normalization. All operations are tracked as `TextAdaptationOperation` records for provenance and rollback.

## Key Concepts
- **Two-pass design**: `adapt_pre_segment` runs before segmentation (cleans paragraphs); `adapt_pre_tts` runs after (normalizes for speech)
- **Tracked operations**: Every change produces a `TextAdaptationOperation` with original/normalized text, category, scope, confidence, and risk
- **Scoped application**: Operations can target `display_and_tts`, `tts_only`, or `suggest_only`

## Module: `vn_core/adaptation/`

### `basic_cleanup(text) -> str`
- Normalize line endings (`\r\n` → `\n`)
- Collapse multiple spaces/tabs
- Collapse 3+ newlines to 2
- Unicode NFKC normalization
- Strip whitespace

### `fix_punctuation(text, segment_id_prefix) -> (str, list[TextAdaptationOperation])`
- Collapse repeated ellipsis (`………` → `…`)
- Collapse repeated em-dashes (`————` → `——`)

### `normalize_numbers_display(text, segment_id_prefix) -> (str, list[TextAdaptationOperation])`
- Insert spaces between digits in 4-digit years (1900-2099) for better TTS reading

### `TextAdapter(policy="balanced")`

#### `adapt_pre_segment(segment_id, text) -> AdaptationResult`
1. `basic_cleanup` — whitespace + encoding normalization
2. `fix_punctuation` — repeated punctuation collapse
Returns `AdaptationResult(operations, adapted_text)`

#### `adapt_pre_tts(segment_id, text) -> AdaptationResult`
1. `normalize_numbers_display` — TTS number readability
Returns `AdaptationResult(operations, adapted_text)`

#### `apply_operations(text, operations, scope) -> str`
Replay adaptation operations on text, optionally filtering by scope.

## Dependencies
- `vn_core.contracts.text_adaptation` — AdaptationCategory, AdaptationScope, TextAdaptationOperation
