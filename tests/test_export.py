"""Tests for export targets: M4B, Audiobookshelf, DAW."""

import json
from pathlib import Path

import pytest

from vn_core.contracts.timing_entry import TimingEntry
from vn_core.export.audiobookshelf import export_audiobookshelf
from vn_core.export.daw import export_daw_package
from vn_core.export.m4b import export_m4b


@pytest.fixture
def sample_timing():
    return [
        TimingEntry(
            segment_id="ch001_p001_s000",
            segmenter_version="v1",
            chapter_audio="ch001.mp3",
            start_ms=0,
            end_ms=3000,
            gap_after_ms=200,
        ),
        TimingEntry(
            segment_id="ch001_p001_s001",
            segmenter_version="v1",
            chapter_audio="ch001.mp3",
            start_ms=3200,
            end_ms=6500,
            gap_after_ms=180,
        ),
        TimingEntry(
            segment_id="ch002_p001_s000",
            segmenter_version="v1",
            chapter_audio="ch002.mp3",
            start_ms=0,
            end_ms=4000,
            gap_after_ms=350,
        ),
    ]


@pytest.fixture
def sample_chapters():
    return [
        {"chapter_id": "ch001", "title": "First Chapter"},
        {"chapter_id": "ch002", "title": "Second Chapter"},
    ]


class TestM4BExport:
    def test_export_creates_metadata(self, tmp_path, sample_chapters, sample_timing):
        out = export_m4b(
            output_dir=str(tmp_path / "m4b"),
            book_id="test_book",
            title="Test Book",
            chapters=sample_chapters,
            timing=sample_timing,
        )
        metadata = json.loads((out / "metadata.json").read_text())
        assert metadata["book_id"] == "test_book"
        assert metadata["title"] == "Test Book"
        assert len(metadata["chapters"]) == 2

    def test_export_creates_chapters_txt(self, tmp_path, sample_chapters, sample_timing):
        out = export_m4b(
            output_dir=str(tmp_path / "m4b"),
            book_id="test_book",
            title="Test Book",
            chapters=sample_chapters,
            timing=sample_timing,
        )
        chapters_txt = (out / "chapters.txt").read_text()
        assert ";FFMETADATA1" in chapters_txt
        assert "CHAPTER" in chapters_txt

    def test_export_with_audio_files(self, tmp_path, sample_timing):
        audio_files = [Path("/data/audio/ch001.mp3")]
        out = export_m4b(
            output_dir=str(tmp_path / "m4b"),
            book_id="test_book",
            timing=sample_timing,
            audio_files=audio_files,
        )
        sources = json.loads((out / "audio_sources.json").read_text())
        assert len(sources) == 1


class TestAudiobookshelfExport:
    def test_export_creates_directory(self, tmp_path, sample_chapters, sample_timing):
        out = export_audiobookshelf(
            output_dir=str(tmp_path / "abs"),
            book_id="test_book",
            title="Test Book",
            chapters=sample_chapters,
            timing=sample_timing,
        )
        assert (out / "audiobook.json").exists()
        assert (out / "chapters.json").exists()
        assert (out / "metadata.opf").exists()

    def test_audiobook_metadata(self, tmp_path, sample_chapters, sample_timing):
        out = export_audiobookshelf(
            output_dir=str(tmp_path / "abs"),
            book_id="test_book",
            title="Test Book",
            author="Test Author",
            chapters=sample_chapters,
            timing=sample_timing,
        )
        meta = json.loads((out / "audiobook.json").read_text())
        assert meta["title"] == "Test Book"
        assert meta["author"] == "Test Author"
        assert meta["duration_ms"] == 6500
        assert len(meta["chapters"]) == 2

    def test_chapters_json_format(self, tmp_path, sample_chapters, sample_timing):
        out = export_audiobookshelf(
            output_dir=str(tmp_path / "abs"),
            book_id="test_book",
            chapters=sample_chapters,
            timing=sample_timing,
        )
        chapters = json.loads((out / "chapters.json").read_text())
        assert len(chapters) == 2
        assert "start" in chapters[0]
        assert chapters[0]["start"] == 0.0

    def test_opf_metadata(self, tmp_path, sample_chapters, sample_timing):
        out = export_audiobookshelf(
            output_dir=str(tmp_path / "abs"),
            book_id="test_book",
            title="Test Book",
            chapters=sample_chapters,
            timing=sample_timing,
        )
        opf = (out / "metadata.opf").read_text()
        assert "test_book" in opf
        assert "Test Book" in opf


class TestDAWExport:
    def test_export_creates_directory(self, tmp_path, sample_chapters, sample_timing):
        out = export_daw_package(
            output_dir=str(tmp_path / "daw"),
            book_id="test_book",
            title="Test Book",
            chapters=sample_chapters,
            timing=sample_timing,
        )
        assert (out / "project.json").exists()
        assert (out / "markers.json").exists()
        assert (out / "regions.json").exists()
        assert (out / "cue_sheet.txt").exists()

    def test_project_json(self, tmp_path, sample_chapters, sample_timing):
        out = export_daw_package(
            output_dir=str(tmp_path / "daw"),
            book_id="test_book",
            title="Test Book",
            chapters=sample_chapters,
            timing=sample_timing,
        )
        project = json.loads((out / "project.json").read_text())
        assert project["book_id"] == "test_book"
        assert project["sample_rate"] == 48000
        assert project["total_duration_ms"] == 6500
        assert len(project["tracks"]) == 2

    def test_markers_json(self, tmp_path, sample_timing):
        out = export_daw_package(
            output_dir=str(tmp_path / "daw"),
            book_id="test_book",
            timing=sample_timing,
        )
        markers = json.loads((out / "markers.json").read_text())
        assert len(markers) == 3
        assert markers[0]["segment_id"] == "ch001_p001_s000"
        assert markers[0]["start_ms"] == 0

    def test_regions_json(self, tmp_path, sample_timing):
        out = export_daw_package(
            output_dir=str(tmp_path / "daw"),
            book_id="test_book",
            timing=sample_timing,
        )
        regions = json.loads((out / "regions.json").read_text())
        assert len(regions) == 2
        assert regions[0]["audio_file"] == "ch001.mp3"
        assert len(regions[0]["segments"]) == 2

    def test_cue_sheet(self, tmp_path, sample_chapters, sample_timing):
        out = export_daw_package(
            output_dir=str(tmp_path / "daw"),
            book_id="test_book",
            title="Test Book",
            chapters=sample_chapters,
            timing=sample_timing,
        )
        cue = (out / "cue_sheet.txt").read_text()
        assert "Test Book" in cue
        assert "TRACK" in cue
