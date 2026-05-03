"""Audiobookshelf Export: generate Audiobookshelf-compatible audiobook structure."""

from __future__ import annotations

import json
from pathlib import Path

from vn_core.contracts.timing_entry import TimingEntry


def export_audiobookshelf(
    output_dir: str | Path,
    book_id: str,
    title: str = "",
    author: str = "",
    description: str = "",
    chapters: list[dict] | None = None,
    timing: list[TimingEntry] | None = None,
    audio_files: list[Path] | None = None,
) -> Path:
    """Export Audiobookshelf-compatible directory structure.

    Generates:
    - audiobook.json: Metadata compatible with Audiobookshelf
    - chapters.json: Chapter markers with timestamps
    - metadata.opf: OPF metadata for the audiobook
    """
    out = Path(output_dir) / book_id
    out.mkdir(parents=True, exist_ok=True)

    chapter_list = chapters or []
    timing_list = timing or []

    total_duration_ms = 0
    if timing_list:
        total_duration_ms = max(t.end_ms for t in timing_list)

    audio_files_list = [str(f) for f in (audio_files or [])]

    audiobook_meta = {
        "id": book_id,
        "title": title or book_id,
        "author": author or "Unknown",
        "description": description,
        "narrator": "VoiceNovel",
        "duration_ms": total_duration_ms,
        "chapters": [],
        "audio_files": audio_files_list,
    }

    for i, ch in enumerate(chapter_list):
        ch_id = ch.get("chapter_id", f"ch{i:03d}")
        ch_title = ch.get("title", f"Chapter {i + 1}")
        ch_timing = [t for t in timing_list if t.chapter_audio]
        start_ms = ch_timing[0].start_ms if ch_timing else 0
        end_ms = ch_timing[-1].end_ms if ch_timing else 0
        length_ms = end_ms - start_ms if end_ms > start_ms else 0
        audiobook_meta["chapters"].append({
            "id": ch_id,
            "title": ch_title,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "length_ms": length_ms,
        })

    audiobook_path = out / "audiobook.json"
    audiobook_path.write_text(
        json.dumps(audiobook_meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    chapters_json = [
        {
            "id": ch["id"],
            "title": ch["title"],
            "start": ch["start_ms"] / 1000.0,
            "end": ch["end_ms"] / 1000.0,
            "length": ch["length_ms"] / 1000.0,
        }
        for ch in audiobook_meta["chapters"]
    ]
    chapters_path = out / "chapters.json"
    chapters_path.write_text(
        json.dumps(chapters_json, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    opf_content = _build_opf(book_id, title or book_id, author or "Unknown", description)
    opf_path = out / "metadata.opf"
    opf_path.write_text(opf_content, encoding="utf-8")

    return out


def _build_opf(
    book_id: str,
    title: str,
    author: str,
    description: str,
) -> str:
    """Build minimal OPF metadata for Audiobookshelf."""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">{book_id}</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:description>{description}</dc:description>
    <dc:format>audio/mpeg</dc:format>
    <meta property="dcterms:modified">2024-01-01T00:00:00Z</meta>
  </metadata>
</package>"""
