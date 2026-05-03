"""Timing Builder: generate timing.json from audio segments and spacing config."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from vn_core.contracts.timing_entry import AudioSpacing, TimingEntry

DEFAULT_SPACING = AudioSpacing()


def build_timing(
    segment_ids: list[str],
    segment_durations_ms: list[int],
    gap_after_ms: list[int] | None = None,
    chapter_audio: str = "Chapter_001.mp3",
    segmenter_version: str = "zh_clause_v1",
    sample_rate: int = 48000,
    spacing: AudioSpacing | None = None,
    paragraph_breaks: list[int] | None = None,
) -> list[TimingEntry]:
    if len(segment_ids) != len(segment_durations_ms):
        raise ValueError("segment_ids and segment_durations_ms must have same length")

    sp = spacing or DEFAULT_SPACING
    if gap_after_ms is None:
        gap_after_ms = [0] * len(segment_ids)

    if paragraph_breaks is None:
        paragraph_breaks = []

    entries: list[TimingEntry] = []
    current_ms: int = sp.chapter_intro_silence_ms

    for i, (seg_id, duration) in enumerate(zip(segment_ids, segment_durations_ms)):
        start_ms = current_ms
        end_ms = current_ms + duration

        gap = gap_after_ms[i]
        if i < len(segment_ids) - 1:
            end_of_para = i in paragraph_breaks
            if end_of_para:
                gap = max(gap, sp.paragraph_gap_ms)
            elif gap <= 0:
                gap = sp.sentence_gap_ms

        entries.append(
            TimingEntry(
                segment_id=seg_id,
                segmenter_version=segmenter_version,
                chapter_audio=chapter_audio,
                start_ms=start_ms,
                end_ms=end_ms,
                gap_after_ms=gap,
                start_sample=start_ms * sample_rate // 1000,
                end_sample=end_ms * sample_rate // 1000,
                sample_rate=sample_rate,
            )
        )

        current_ms = end_ms + gap

    return entries


def compute_chapter_duration_ms(timing_entries: list[TimingEntry]) -> int:
    if not timing_entries:
        return 0
    last = timing_entries[-1]
    return last.end_ms + last.gap_after_ms


def get_audio_duration_ms(audio_path: str | Path) -> int | None:
    path = Path(audio_path)
    if not path.exists():
        return None

    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as wav:
                frames = wav.getnframes()
                rate = wav.getframerate()
                if rate <= 0:
                    return None
                return round(frames * 1000 / rate)
        except (wave.Error, OSError):
            return None

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None

    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        seconds = float(completed.stdout.strip())
        return round(seconds * 1000)
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def assemble_chapter_wav(
    segment_ids: list[str],
    audio_paths: dict[str, str],
    timing_entries: list[TimingEntry],
    output_path: str | Path,
    sample_rate: int = 24000,
    temp_dir: str | Path | None = None,
) -> Path:
    """Assemble segment audio into one chapter WAV using timing gaps.

    WAV inputs are copied directly after sample-rate normalization. Non-WAV
    inputs are decoded through ffmpeg when available.

    If *temp_dir* is provided, a subdirectory under it is used instead of
    the system default temp directory.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    timing_by_segment = {entry.segment_id: entry for entry in timing_entries}
    first_start_ms = timing_entries[0].start_ms if timing_entries else 0

    _cleanup_tmp = None
    if temp_dir:
        tdir = Path(temp_dir) / ".tmp_audio"
        tdir.mkdir(parents=True, exist_ok=True)
        tmp_dir = tdir
    else:
        _cleanup_tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(_cleanup_tmp.name)

    try:
        normalized_paths: dict[str, Path] = {}
        for seg_id in segment_ids:
            source = audio_paths.get(seg_id)
            if not source:
                continue
            src = Path(source)
            if not src.exists():
                continue
            normalized_paths[seg_id] = _ensure_wav(src, tmp_dir, sample_rate)

        with wave.open(str(out), "wb") as chapter:
            chapter.setnchannels(1)
            chapter.setsampwidth(2)
            chapter.setframerate(sample_rate)
            _write_silence(chapter, first_start_ms, sample_rate)

            for seg_id in segment_ids:
                path = normalized_paths.get(seg_id)
                if path:
                    _append_wav(chapter, path, sample_rate)
                entry = timing_by_segment.get(seg_id)
                if entry:
                    _write_silence(chapter, entry.gap_after_ms, sample_rate)
    finally:
        if _cleanup_tmp:
            _cleanup_tmp.cleanup()
        elif temp_dir:
            import shutil as _shutil
            try:
                _shutil.rmtree(str(tmp_dir), ignore_errors=True)
            except Exception:
                pass

    return out


def _ensure_wav(source: Path, tmp_dir: Path, sample_rate: int) -> Path:
    if source.suffix.lower() == ".wav":
        return source

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(f"ffmpeg is required to decode non-WAV audio: {source}")

    target = tmp_dir / f"{source.stem}.wav"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i", str(source),
            "-ac", "1",
            "-ar", str(sample_rate),
            str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return target


def _append_wav(chapter: wave.Wave_write, source: Path, target_rate: int):
    with wave.open(str(source), "rb") as segment:
        if segment.getnchannels() != 1 or segment.getsampwidth() != 2:
            raise RuntimeError(f"Unsupported WAV format for chapter assembly: {source}")
        if segment.getframerate() != target_rate:
            raise RuntimeError(
                f"Sample rate mismatch for {source}: {segment.getframerate()} != {target_rate}"
            )
        chapter.writeframes(segment.readframes(segment.getnframes()))


def _write_silence(chapter: wave.Wave_write, duration_ms: int, sample_rate: int):
    if duration_ms <= 0:
        return
    frame_count = int(sample_rate * duration_ms / 1000)
    chapter.writeframes(b"\x00\x00" * frame_count)


def convert_wav_to_mp3(wav_path: str | Path, mp3_path: str | Path,
                       bitrate: str = "192k") -> Path:
    """Convert a WAV file to MP3 using ffmpeg.

    Returns the MP3 path on success. Raises RuntimeError if ffmpeg is unavailable
    or conversion fails.
    """
    wav = Path(wav_path)
    mp3 = Path(mp3_path)
    mp3.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for MP3 conversion")

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i", str(wav),
            "-acodec", "libmp3lame",
            "-ab", bitrate,
            "-ac", "1",
            str(mp3),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return mp3


def assemble_chapter_mp3(
    segment_ids: list[str],
    audio_paths: dict[str, str],
    timing_entries: list[TimingEntry],
    output_path: str | Path,
    sample_rate: int = 24000,
    mp3_bitrate: str = "192k",
    keep_wav: bool = False,
    temp_dir: str | Path | None = None,
) -> Path:
    """Assemble chapter audio as MP3 via WAV intermediate.

    1. Assembles segments into a chapter WAV (same as assemble_chapter_wav)
    2. Converts WAV → MP3 via ffmpeg
    3. Optionally keeps the intermediate WAV for deterministic testing

    Returns the MP3 path.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    wav_path = out.with_suffix(".wav")
    assemble_chapter_wav(
        segment_ids=segment_ids,
        audio_paths=audio_paths,
        timing_entries=timing_entries,
        output_path=wav_path,
        sample_rate=sample_rate,
        temp_dir=temp_dir,
    )

    mp3_path = out if out.suffix.lower() == ".mp3" else out.with_suffix(".mp3")
    convert_wav_to_mp3(wav_path, mp3_path, bitrate=mp3_bitrate)

    if not keep_wav:
        try:
            wav_path.unlink()
        except OSError:
            pass

    return mp3_path


def ffmpeg_available() -> bool:
    """Check if ffmpeg is in PATH."""
    return shutil.which("ffmpeg") is not None
