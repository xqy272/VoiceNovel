"""M4B Export: generate audiobook M4B metadata and chapter markers."""

from __future__ import annotations

import json
from pathlib import Path

from vn_core.contracts.timing_entry import TimingEntry


def export_m4b(
    output_dir: str | Path,
    book_id: str,
    title: str = "",
    author: str = "",
    chapters: list[dict] | None = None,
    timing: list[TimingEntry] | None = None,
    audio_files: list[Path] | None = None,
) -> Path:
    """Export M4B audiobook metadata with chapter markers.

    Generates:
    - metadata.json: FFmpeg-compatible metadata for M4B creation
    - chapters.txt: FFmetadata chapter markers file

    The actual M4B muxing requires FFmpeg and is done externally.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    chapter_list = chapters or []
    timing_list = timing or []

    metadata = {
        "book_id": book_id,
        "title": title or book_id,
        "author": author or "Unknown",
        "format": "m4b",
        "chapters": [],
    }

    for i, ch in enumerate(chapter_list):
        ch_id = ch.get("chapter_id", f"ch{i:03d}")
        ch_title = ch.get("title", f"Chapter {i + 1}")
        ch_timing = [t for t in timing_list if t.chapter_audio]
        start_ms = ch_timing[0].start_ms if ch_timing else i * 60000
        end_ms = ch_timing[-1].end_ms if ch_timing else (i + 1) * 60000
        metadata["chapters"].append({
            "chapter_id": ch_id,
            "title": ch_title,
            "start_ms": start_ms,
            "end_ms": end_ms,
        })

    metadata_path = out / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    ffmetadata = _build_ffmetadata(metadata["chapters"])
    ffmeta_path = out / "chapters.txt"
    ffmeta_path.write_text(ffmetadata, encoding="utf-8")

    if audio_files:
        playlist = [str(f) for f in audio_files]
        playlist_path = out / "audio_sources.json"
        playlist_path.write_text(
            json.dumps(playlist, indent=2),
            encoding="utf-8",
        )

    return out


def _build_ffmetadata(chapters: list[dict]) -> str:
    """Build FFmetadata format for FFmpeg chapter markers."""
    lines = [
        ";FFMETADATA1",
        f"title={chapters[0].get('title', 'Audiobook') if chapters else 'Audiobook'}",
    ]
    for ch in chapters:
        start_ms = ch.get("start_ms", 0)
        end_ms = ch.get("end_ms", start_ms + 60000)
        lines.append("")
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={start_ms}")
        lines.append(f"END={end_ms}")
        lines.append(f"title={ch.get('title', 'Chapter')}")
    return "\n".join(lines)
