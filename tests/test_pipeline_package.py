"""Pipeline package smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vn_core.importers import import_book
from vn_core.pipeline import Pipeline
from vn_core.store import ProjectStore
from vn_core.timing import get_audio_duration_ms

GOLDEN_BOOK = Path(__file__).parent / "golden_books" / "mountain_inn.txt"


@pytest.mark.asyncio
async def test_bake_chapter_builds_playable_reader_package(tmp_path):
    store = ProjectStore(tmp_path / "project.sqlite")
    store.initialize()
    try:
        import_book(str(GOLDEN_BOOK), book_id="golden_mountain_inn", store=store)
        pipeline = Pipeline(store=store, output_dir=str(tmp_path / "out"), tts_engine="mock")

        result = await pipeline.bake_chapter("golden_mountain_inn", "ch001")

        assert result.success, result.errors
        package_dir = Path(result.package_dir)
        assert (package_dir / "cleaned.html").exists()
        assert (package_dir / "timing.json").exists()
        assert (package_dir / "reading_plan.jsonl").exists()
        assert (package_dir / "audio_manifest.json").exists()
        chapter_audio = package_dir / "audio" / "ch001.wav"
        assert chapter_audio.exists()
        assert get_audio_duration_ms(chapter_audio) is not None

        timing = json.loads((package_dir / "timing.json").read_text(encoding="utf-8"))
        assert timing
        assert all(entry["chapter_audio"] == "audio/ch001.wav" for entry in timing)

        active_package = store.get_active_artifact(
            "golden_mountain_inn", "reader_package", "ch001"
        )
        assert active_package is not None
        deps = store.get_artifact_dependencies(
            "golden_mountain_inn", active_package["artifact_version_id"]
        )
        assert {d["dependency_role"] for d in deps} >= {
            "segments",
            "reading_plan",
            "timing",
            "cleaned_html",
            "chapter_audio",
        }

        cached = await pipeline.bake_chapter("golden_mountain_inn", "ch001")
        assert cached.success, cached.errors
        assert cached.segments
        assert cached.timing
        assert cached.cleaned_html
    finally:
        store.close()


@pytest.mark.asyncio
async def test_bake_chapter_ignores_dependencyless_empty_cache(tmp_path):
    store = ProjectStore(tmp_path / "project.sqlite")
    store.initialize()
    try:
        import_book(str(GOLDEN_BOOK), book_id="cache_mountain_inn", store=store)

        empty_pkg = tmp_path / "out" / "packages" / "cache_mountain_inn" / "ch001"
        empty_pkg.mkdir(parents=True)
        store.write_artifact(
            "cache_mountain_inn",
            "cache_mountain_inn_reader_package_ch001_v999",
            "reader_package",
            "ch001",
            file_path=str(empty_pkg),
        )

        pipeline = Pipeline(store=store, output_dir=str(tmp_path / "out"), tts_engine="mock")
        result = await pipeline.bake_chapter("cache_mountain_inn", "ch001")

        assert result.success, result.errors
        assert result.segments
        assert result.timing
        assert (Path(result.package_dir) / "manifest.json").exists()
    finally:
        store.close()
