# Packaging Service — AI Agent Guide

## Purpose
Assemble a Reader Package from active artifacts — the canonical output consumed by the Web Reader. Packaging reads artifacts from the pipeline, validates dependencies, and writes a complete directory structure ready for serving.

## Key Concepts
- **Read-only assembly**: Packaging does not call LLM, TTS, or modify text — it only assembles existing active artifacts
- **Package vs Export boundary**: Packaging produces the internal Reader Package (main path); Export produces user-triggered external formats (M4B, DAW, Audiobookshelf)
- **Manifest-driven**: `manifest.json` is the entry point the reader uses to discover all package files

## Module: `vn_core/packaging/`

### `PackagingService`

#### `build_reader_package(output_dir, manifest, cleaned_html, segments_jsonl, voices_json, audio_manifest_json, timing_json) -> Path`
1. Create output directory
2. Write `manifest.json` from `ReaderPackageManifest`
3. Write optional files if content provided:
   - `cleaned.html` — XHTML with data-seg-id spans
   - `segments.jsonl` — one Segment JSON per line
   - `voices.json` — VoiceAssignment array
   - `audio_manifest.json` — chapter + segment audio metadata
   - `timing.json` — TimingEntry array
4. Return output directory path

### Reader Package Structure
```
{package_dir}/
  manifest.json          # ReaderPackageManifest
  cleaned.html           # XHTML with data-seg-id spans
  segments.jsonl         # Segment records (JSONL)
  voices.json            # Voice assignments
  audio_manifest.json    # Audio file metadata
  timing.json            # Per-segment timing
  audio/
    {chapter_id}.wav     # Chapter audio (or .mp3)
```

## Dependencies
- `vn_core.contracts.reader_manifest` — ReaderPackageManifest
