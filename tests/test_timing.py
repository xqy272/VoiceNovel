"""Tests for timing duration probing and chapter WAV assembly."""

from __future__ import annotations

import wave

from vn_core.timing import assemble_chapter_wav, build_timing, get_audio_duration_ms


def _write_wav(path, duration_ms: int, sample_rate: int = 24000):
    frames = int(sample_rate * duration_ms / 1000)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * frames)


def test_get_audio_duration_ms_for_wav(tmp_path):
    wav_path = tmp_path / "seg.wav"
    _write_wav(wav_path, 750)

    assert get_audio_duration_ms(wav_path) == 750


def test_assemble_chapter_wav(tmp_path):
    first = tmp_path / "s001.wav"
    second = tmp_path / "s002.wav"
    _write_wav(first, 500)
    _write_wav(second, 700)

    timing = build_timing(
        segment_ids=["s001", "s002"],
        segment_durations_ms=[500, 700],
        gap_after_ms=[120, 0],
        chapter_audio="audio/ch001.wav",
    )
    out = assemble_chapter_wav(
        segment_ids=["s001", "s002"],
        audio_paths={"s001": str(first), "s002": str(second)},
        timing_entries=timing,
        output_path=tmp_path / "ch001.wav",
    )

    expected_ms = timing[0].start_ms + 500 + 120 + 700
    assert get_audio_duration_ms(out) == expected_ms
