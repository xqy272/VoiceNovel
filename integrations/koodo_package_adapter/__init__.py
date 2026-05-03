"""Koodo Package Adapter: Convert VoiceNovel Reader Packages to Koodo Reader format."""

from __future__ import annotations

import json
from pathlib import Path


def koodo_from_reader_package(
    package_dir: str | Path,
    output_dir: str | Path | None = None,
    book_title: str = "",
) -> Path:
    """Convert a VoiceNovel Reader Package to Koodo-compatible format.

    Reads manifest.json, timing.json, segments.jsonl, voices.json,
    and cleaned HTML from the package dir, then produces:
    - koodo_metadata.json: Koodo-format book metadata
    - koodo_chapters.json: Chapter markers with timestamps
    - content.xhtml: Copy of cleaned HTML
    - koodo_toc.json: Table of contents with audio offsets
    """
    pkg = Path(package_dir)
    out = Path(output_dir) if output_dir else pkg / "koodo"
    out.mkdir(parents=True, exist_ok=True)

    manifest_data = _load_json(pkg / "manifest.json")
    timing_data = _load_json(pkg / "timing.json")
    segments = _load_segments(pkg / "segments.jsonl")
    voices = _load_json(pkg / "voices.json")

    html_content = ""
    for ext in (".cleaned.xhtml", ".html"):
        candidates = list(pkg.glob(f"*{ext}"))
        if candidates:
            html_content = candidates[0].read_text(encoding="utf-8")
            break

    book_id = manifest_data.get("book_id", "unknown")
    title = book_title or manifest_data.get("title", book_id)
    audio_codec = manifest_data.get("audio_codec", "mp3")

    koodo_meta = {
        "format_version": "1.0",
        "source": "VoiceNovel",
        "book_id": book_id,
        "title": title,
        "segmenter_version": manifest_data.get("segmenter_version", ""),
        "highlight_granularity": manifest_data.get("highlight_granularity", "sentence_clause"),
        "audio_codec": audio_codec,
        "timing_unit": manifest_data.get("timing_unit", "ms"),
        "total_segments": len(segments),
        "total_timing_entries": len(timing_data),
        "voice_count": len(voices) if isinstance(voices, list) else 0,
    }

    meta_path = out / "koodo_metadata.json"
    meta_path.write_text(
        json.dumps(koodo_meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    chapters = _build_chapters(timing_data, segments)
    chapters_path = out / "koodo_chapters.json"
    chapters_path.write_text(
        json.dumps(chapters, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    toc = _build_toc(timing_data, segments, title)
    toc_path = out / "koodo_toc.json"
    toc_path.write_text(
        json.dumps(toc, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if html_content:
        content_path = out / "content.xhtml"
        content_path.write_text(html_content, encoding="utf-8")

        idx_path = out / "index.json"
        idx = {
            "book_id": book_id,
            "content_file": "content.xhtml",
            "chapters_file": "koodo_chapters.json",
            "toc_file": "koodo_toc.json",
            "audio_dir": "audio",
        }
        idx_path.write_text(
            json.dumps(idx, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return out


def _load_json(path: Path) -> dict | list:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _load_segments(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if line.strip():
            result.append(json.loads(line))
    return result


def _build_chapters(
    timing_data: list | dict,
    segments: list[dict],
) -> list[dict]:
    timing_list = timing_data if isinstance(timing_data, list) else []
    if not timing_list:
        return []

    grouped: dict[str, list] = {}
    for t in timing_list:
        audio = t.get("chapter_audio", "unknown")
        grouped.setdefault(audio, []).append(t)

    chapters = []
    for audio_name, entries in grouped.items():
        start_ms = min(e.get("start_ms", 0) for e in entries)
        end_ms = max(e.get("end_ms", 0) for e in entries)
        chapters.append({
            "audio_file": audio_name,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "duration_ms": end_ms - start_ms,
            "segment_count": len(entries),
        })

    return chapters


def _build_toc(
    timing_data: list | dict,
    segments: list[dict],
    title: str,
) -> dict:
    timing_list = timing_data if isinstance(timing_data, list) else []

    entries = []
    for t in timing_list:
        seg_id = t.get("segment_id", "")
        matching = [s for s in segments if s.get("segment_id") == seg_id]
        text = matching[0].get("text", "") if matching else ""
        entries.append({
            "segment_id": seg_id,
            "start_ms": t.get("start_ms", 0),
            "end_ms": t.get("end_ms", 0),
            "text_preview": text[:50] if text else "",
        })

    return {
        "title": title,
        "entry_count": len(entries),
        "entries": entries,
    }
