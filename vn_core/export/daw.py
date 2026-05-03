"""DAW Package Export: generate DAW-compatible project structure."""

from __future__ import annotations

import json
from pathlib import Path

from vn_core.contracts.timing_entry import TimingEntry


def export_daw_package(
    output_dir: str | Path,
    book_id: str,
    title: str = "",
    chapters: list[dict] | None = None,
    timing: list[TimingEntry] | None = None,
    audio_files: list[Path] | None = None,
    sample_rate: int = 48000,
) -> Path:
    """Export DAW-compatible project package.

    Generates:
    - project.json: DAW project metadata with track layout
    - markers.json: Timeline markers for each segment
    - regions.json: Audio regions with start/end positions
    - cue_sheet.txt: Cue sheet for chapter navigation
    """
    out = Path(output_dir) / f"{book_id}_daw"
    out.mkdir(parents=True, exist_ok=True)

    chapter_list = chapters or []
    timing_list = timing or []
    audio_files_list = audio_files or []

    total_duration_ms = 0
    if timing_list:
        total_duration_ms = max(t.end_ms for t in timing_list)

    tracks = _build_tracks(chapter_list, timing_list, audio_files_list, sample_rate)

    project = {
        "book_id": book_id,
        "title": title or book_id,
        "sample_rate": sample_rate,
        "total_duration_ms": total_duration_ms,
        "total_duration_samples": int(total_duration_ms * sample_rate / 1000),
        "tracks": tracks,
    }

    project_path = out / "project.json"
    project_path.write_text(
        json.dumps(project, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    markers = _build_markers(timing_list, sample_rate)
    markers_path = out / "markers.json"
    markers_path.write_text(
        json.dumps(markers, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    regions = _build_regions(timing_list, sample_rate)
    regions_path = out / "regions.json"
    regions_path.write_text(
        json.dumps(regions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    cue_sheet = _build_cue_sheet(book_id, title or book_id, chapter_list, timing_list)
    cue_path = out / "cue_sheet.txt"
    cue_path.write_text(cue_sheet, encoding="utf-8")

    return out


def _build_tracks(
    chapters: list[dict],
    timing: list[TimingEntry],
    audio_files: list[Path],
    sample_rate: int,
) -> list[dict]:
    """Build track list from timing data."""
    tracks = []
    unique_audio = set()
    for t in timing:
        unique_audio.add(t.chapter_audio)

    for idx, audio_name in enumerate(sorted(unique_audio)):
        audio_timing = [t for t in timing if t.chapter_audio == audio_name]
        start_ms = audio_timing[0].start_ms if audio_timing else 0
        end_ms = audio_timing[-1].end_ms if audio_timing else 0
        matching_file = None
        for f in audio_files:
            if audio_name in str(f):
                matching_file = str(f)
                break
        tracks.append({
            "track_number": idx + 1,
            "audio_file": matching_file or audio_name,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "start_sample": int(start_ms * sample_rate / 1000),
            "end_sample": int(end_ms * sample_rate / 1000),
            "segments": len(audio_timing),
        })

    if not tracks and audio_files:
        for idx, f in enumerate(audio_files):
            tracks.append({
                "track_number": idx + 1,
                "audio_file": str(f),
                "start_ms": 0,
                "end_ms": 0,
                "start_sample": 0,
                "end_sample": 0,
                "segments": 0,
            })

    return tracks


def _build_markers(timing: list[TimingEntry], sample_rate: int) -> list[dict]:
    """Build timeline markers from timing entries."""
    markers = []
    for t in timing:
        markers.append({
            "segment_id": t.segment_id,
            "start_ms": t.start_ms,
            "end_ms": t.end_ms,
            "start_sample": t.start_sample or int(t.start_ms * sample_rate / 1000),
            "end_sample": t.end_sample or int(t.end_ms * sample_rate / 1000),
            "gap_after_ms": t.gap_after_ms,
        })
    return markers


def _build_regions(timing: list[TimingEntry], sample_rate: int) -> list[dict]:
    """Build region definitions for each chapter audio file."""
    regions = []
    current_audio = None
    region_segments = []

    for t in timing:
        if t.chapter_audio != current_audio:
            if current_audio and region_segments:
                regions.append({
                    "audio_file": current_audio,
                    "segments": region_segments,
                })
            current_audio = t.chapter_audio
            region_segments = []

        region_segments.append({
            "segment_id": t.segment_id,
            "start_ms": t.start_ms,
            "end_ms": t.end_ms,
            "start_sample": t.start_sample or int(t.start_ms * sample_rate / 1000),
            "end_sample": t.end_sample or int(t.end_ms * sample_rate / 1000),
        })

    if current_audio and region_segments:
        regions.append({
            "audio_file": current_audio,
            "segments": region_segments,
        })

    return regions


def _build_cue_sheet(
    book_id: str,
    title: str,
    chapters: list[dict],
    timing: list[TimingEntry],
) -> str:
    """Build a CUE sheet for chapter navigation."""
    lines = [
        f'TITLE "{title}"',
        'PERFORMER "VoiceNovel"',
        f'REM BOOK_ID {book_id}',
    ]

    unique_audio = sorted(set(t.chapter_audio for t in timing)) if timing else []
    if len(unique_audio) == 1:
        lines.append(f'FILE "{unique_audio[0]}" MP3')
    elif unique_audio:
        for idx, audio in enumerate(unique_audio):
            lines.append(f'REM AUDIO_{idx + 1} "{audio}"')
        lines.append(f'FILE "{unique_audio[0]}" MP3')

    for i, ch in enumerate(chapters):
        ch_title = ch.get("title", f"Chapter {i + 1}")
        ch_timing = [t for t in timing if t.chapter_audio]
        start_ms = ch_timing[0].start_ms if ch_timing else 0
        minutes = int(start_ms // 60000)
        seconds = int((start_ms % 60000) // 1000)
        frames = int(((start_ms % 1000) * 75) // 1000)
        lines.append(f"  TRACK {i + 1:02d} AUDIO")
        lines.append(f'    TITLE "{ch_title}"')
        lines.append(f"    INDEX 01 {minutes:02d}:{seconds:02d}:{frames:02d}")

    if not chapters and unique_audio:
        lines.append("  TRACK 01 AUDIO")
        lines.append(f'    TITLE "{title}"')
        lines.append("    INDEX 01 00:00:00")

    return "\n".join(lines)
