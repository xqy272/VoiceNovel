# Timing Builder — AI Agent Guide

## Purpose
Build `timing.json` from measured audio durations, insert configurable silence gaps between segments, assemble chapter WAV from segment audio, and measure actual audio duration.

## Key Concepts
- **Real duration measurement**: Uses `wave` module for WAV, `ffprobe` for non-WAV formats
- **Configurable spacing**: Clause, sentence, paragraph, chapter intro/outro gaps are all tunable via `AudioSpacing`
- **Dual timing fields**: `start_ms/end_ms` for playback, `start_sample/end_sample` for debug/rebuild
- **Chapter assembly**: Concatenates segment WAVs with silence gaps into a single chapter WAV

## Module: `vn_core/timing/`

### `build_timing(segment_ids, segment_durations_ms, gap_after_ms, chapter_audio, segmenter_version, sample_rate, spacing, paragraph_breaks) -> list[TimingEntry]`
1. Validate segment_ids and durations match in length
2. Start at `chapter_intro_silence_ms`
3. For each segment: compute start/end from accumulated time + current duration
4. Apply spacing: use explicit `gap_after_ms`, or paragraph gap at paragraph boundaries, or default sentence gap
5. Convert ms to samples using sample_rate
6. Return ordered list of TimingEntry

### `compute_chapter_duration_ms(timing_entries) -> int`
Total duration = last entry's end_ms + gap_after_ms.

### `get_audio_duration_ms(audio_path) -> int | None`
- WAV: reads frames/rate via `wave` module
- Other: uses `ffprobe` to extract format duration
- Returns None if file missing or tools unavailable

### `assemble_chapter_wav(segment_ids, audio_paths, timing_entries, output_path, sample_rate) -> Path`
1. Normalize all segment audio to target sample rate (mono, 16-bit WAV)
2. Write intro silence based on first entry's start_ms
3. For each segment: append normalized WAV frames, then write gap silence
4. Non-WAV inputs decoded via ffmpeg if available

### Default Spacing
```python
AudioSpacing(
    clause_gap_ms=120,
    sentence_gap_ms=180,
    paragraph_gap_ms=350,
    chapter_intro_silence_ms=500,
    chapter_outro_silence_ms=800,
)
```

## Dependencies
- `vn_core.contracts.timing_entry` — TimingEntry, AudioSpacing
- `wave` — stdlib, WAV reading/writing
- `ffmpeg` / `ffprobe` — optional system tools for non-WAV formats
