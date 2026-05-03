"""Shared result types for TTS adapters — no circular import risk."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TTSResult:
    request_id: str
    segment_id: str
    audio_path: str
    duration_ms: float = 0.0
    engine: str = ""
    voice_id: str = ""
    status: str = "success"
    error: str = ""
