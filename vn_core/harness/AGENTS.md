# Harness Gate — AI Agent Guide

## Purpose
Quality control plane for all writes to the Project Store. Every artifact, decision, and provenance record passes through the Harness Gate for validation before commit. No service writes directly to Store.

## Key Concepts
- **Gate decisions**: `pass` (proceed), `retry` (recoverable), `fail` (block), `stale` (cache expired)
- **Validators per artifact type**: segments, reading_plan, audio_take, timing, reader_package each have dedicated validators
- **Provenance tracking**: Every pipeline stage writes a provenance record with model, hash, config, and run metadata
- **Exception queue**: Unresolvable issues are written to the exceptions table for later manual review

## Module: `vn_core/harness/`

### Enums
- `GateDecision`: `pass_decision`, `retry_decision`, `fail_decision`, `stale_decision`

### `GateResult(decision, reason, exceptions)`
Returned by every validate call.

### `HarnessGate`

#### `validate(artifact_type, proposed_data, context) -> GateResult`
Dispatches to type-specific validator:
- **segments**: Checks non-empty text, no duplicate segment_ids
- **reading_plan**: Checks non-empty segment_id and text per entry
- **audio_take**: Checks audio_path present on success status
- **timing**: Checks no time overlaps (start_ms >= prev end_ms)
- **reader_package**: Checks manifest.json, cleaned.html, segments.jsonl, voices.json, timing.json, audio_manifest.json, and audio directory exist

#### `commit(store, book_id, artifact_type, unit_id, artifact_version_id, ...) -> GateResult`
Write artifact to store with auto-superseding of previous active.

#### `write_provenance(store, unit_id, stage, artifact_version_id, ...)`
Insert provenance record with LLM model, hashes, run_id, reading_profile.

#### `write_exception(store, book_id, unit_id, stage, exception_type, ...)`
Insert exception into the exceptions table for manual review.

#### `write_decision(store, book_id, segment_id, decision_type, value, ...)`
Write a pipeline decision (speaker attribution, etc.) to the decisions table.

## Adding a New Validator
1. Add a `_validate_{type}` method to HarnessGate
2. Register it in the `validators` dict in `validate()`
3. Return `GateResult` with appropriate decision and reason

## Dependencies
- `vn_core.contracts.segment` — Segment validation
- `vn_core.contracts.reading_plan` — ReadingPlanEntry validation
- `vn_core.contracts.timing_entry` — TimingEntry validation
- `vn_core.contracts.exception_entry` — ExceptionEntry types
- `vn_core.store.ProjectStore` — write operations
