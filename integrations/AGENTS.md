# Koodo Integrations — AI Agent Guide

## Package Adapter: `integrations/koodo_package_adapter/`

### Purpose
Convert VoiceNovel Reader Packages to Koodo Reader-compatible format.

### `koodo_from_reader_package(package_dir, output_dir, book_title)`
Reads manifest.json + timing.json + segments.jsonl + voices.json + cleaned HTML from a Reader Package, then produces:
- `koodo_metadata.json`: Koodo-format book metadata (format_version, source, highlight settings)
- `koodo_chapters.json`: Chapter markers with audio file grouping + durations
- `koodo_toc.json`: Table of contents with segment-level timing entries
- `content.xhtml`: Copy of cleaned HTML from the Reader Package
- `index.json`: File index pointing to content, chapters, TOC

## Voice Plugin: `integrations/koodo_voice_plugin/`

### Purpose
Configure Koodo Reader to use VoiceNovel TTS backends for playback.

### `generate_koodo_voice_config(output_path, voice_assignments, voice_registry_entries, book_id)`
Produces:
- `voice_config.json`: Maps VoiceNovel voice assignments to Koodo format
  - Character → voice_id mapping with confidence and source
  - Voice registry entries with tags, backend, language
  - Engine config: API endpoints for synthesis and audio retrieval
- `playback_config.json`: Playback synchronization settings
  - Highlight sync enabled, granularity, segment data attribute, timing path