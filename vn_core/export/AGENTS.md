# Export — AI Agent Guide

## Purpose
Generate output packages in multiple formats from VoiceNovel Reader Packages.

## Module: `vn_core/export/`

### `m4b.py` — M4B Audiobook Export
- Produces FFmpeg-compatible metadata and chapter markers
- `metadata.json`: Book metadata with chapter timestamps
- `chapters.txt`: FFmetadata chapter markers for M4B muxing
- `audio_sources.json`: Playlist of source audio files

### `audiobookshelf.py` — Audiobookshelf Export
- Produces Audiobookshelf-compatible directory structure
- `audiobook.json`: Book metadata with chapter markers and durations
- `chapters.json`: Chapter markers in seconds (Audiobookshelf format)
- `metadata.opf`: OPF metadata for audiobook identification

### `daw.py` — DAW Package Export
- Produces DAW-compatible project structure
- `project.json`: DAW project with track layout, sample-accurate positions
- `markers.json`: Timeline markers per segment with sample offsets
- `regions.json`: Audio regions grouped by chapter audio file
- `cue_sheet.txt`: CUE sheet for chapter navigation

## Key Concepts
- All exports consume `TimingEntry` list + chapter metadata
- Sample positions calculated from `start_ms` × `sample_rate / 1000`
- M4B requires external FFmpeg for actual muxing
- Audiobookshelf expects seconds (float) not milliseconds
- DAW export provides both ms-based and sample-based timestamps