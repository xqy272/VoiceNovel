"""Koodo Voice Plugin: Integrate VoiceNovel TTS with Koodo Reader's voice system."""

from __future__ import annotations

import json
from pathlib import Path


def generate_koodo_voice_config(
    output_path: str | Path,
    voice_assignments: list[dict] | None = None,
    voice_registry_entries: list[dict] | None = None,
    book_id: str = "",
) -> Path:
    """Generate a Koodo-compatible voice configuration file.

    Maps VoiceNovel voice assignments and registry to Koodo's
    voice engine format, enabling Koodo to use VoiceNovel's
    TTS backends for audio playback.
    """
    out = Path(output_path)
    out.mkdir(parents=True, exist_ok=True)

    voice_map = _build_voice_map(voice_assignments or [], voice_registry_entries or [])

    config = {
        "format_version": "1.0",
        "source": "VoiceNovel",
        "book_id": book_id,
        "voices": voice_map,
        "engine_config": {
            "backend": "voicenovel",
            "api_endpoint": "http://localhost:5000",
            "synthesis_path": "/api/projects/{book_id}/chapters/{chapter_id}/tts",
            "audio_path": "/api/projects/{book_id}/chapters/{chapter_id}/audio",
            "supported_codecs": ["mp3", "opus"],
            "default_codec": "mp3",
        },
    }

    config_path = out / "voice_config.json"
    config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    playback_config = {
        "format_version": "1.0",
        "highlight_sync": True,
        "highlight_granularity": "sentence_clause",
        "segment_data_attribute": "data-seg-id",
        "highlight_class": "highlight",
        "audio_sync_mode": "timing_json",
        "timing_path": "/api/projects/{book_id}/chapters/{chapter_id}/timing",
        "content_path": "/api/projects/{book_id}/chapters/{chapter_id}/content",
    }

    playback_path = out / "playback_config.json"
    playback_path.write_text(
        json.dumps(playback_config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return out


def _build_voice_map(
    voice_assignments: list[dict],
    voice_registry_entries: list[dict],
) -> list[dict]:
    """Build Koodo-compatible voice map from VoiceNovel data."""
    voices = []
    seen_ids = set()

    for va in voice_assignments:
        voice_id = va.get("voice_id", "")
        if voice_id in seen_ids:
            continue
        seen_ids.add(voice_id)
        voices.append({
            "character_id": va.get("character_id", ""),
            "voice_id": voice_id,
            "confidence": va.get("confidence", 1.0),
            "source": va.get("source", "auto"),
            "user_locked": va.get("user_locked", False),
        })

    for vr in voice_registry_entries:
        vid = vr.get("voice_id", "")
        if vid in seen_ids:
            continue
        seen_ids.add(vid)
        voices.append({
            "character_id": "",
            "voice_id": vid,
            "name": vr.get("name", vid),
            "tags": vr.get("tags", []),
            "backend": vr.get("backend", "mock"),
            "language": vr.get("language", []),
            "status": vr.get("status", "approved"),
        })

    return voices
