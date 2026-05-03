"""Packaging Service: build Reader Package from active artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from vn_core.contracts.reader_manifest import ReaderPackageManifest


class PackagingService:
    def build_reader_package(
        self,
        output_dir: str | Path,
        manifest: ReaderPackageManifest,
        cleaned_html: str = "",
        segments_jsonl: str = "",
        reading_plan_jsonl: str = "",
        voices_json: str = "",
        audio_manifest_json: str = "",
        timing_json: str = "",
    ) -> Path:
        pkg_dir = Path(output_dir)
        pkg_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = pkg_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        if cleaned_html:
            html_path = pkg_dir / "cleaned.html"
            html_path.write_text(cleaned_html, encoding="utf-8")

        if segments_jsonl:
            seg_path = pkg_dir / "segments.jsonl"
            seg_path.write_text(segments_jsonl, encoding="utf-8")

        if reading_plan_jsonl:
            plan_path = pkg_dir / "reading_plan.jsonl"
            plan_path.write_text(reading_plan_jsonl, encoding="utf-8")

        if voices_json:
            voice_path = pkg_dir / "voices.json"
            voice_path.write_text(voices_json, encoding="utf-8")

        if audio_manifest_json:
            am_path = pkg_dir / "audio_manifest.json"
            am_path.write_text(audio_manifest_json, encoding="utf-8")

        if timing_json:
            timing_path = pkg_dir / "timing.json"
            timing_path.write_text(timing_json, encoding="utf-8")

        return pkg_dir
