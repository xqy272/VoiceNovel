"""Tests for Packaging Service module."""

import json

from vn_core.contracts.reader_manifest import ReaderPackageManifest
from vn_core.packaging import PackagingService


class TestPackagingService:
    def test_build_reader_package(self, tmp_path):
        service = PackagingService()
        manifest = ReaderPackageManifest(
            book_id="test_book_001",
            title="Test Book",
            segmenter_version="zh_clause_v1",
        )
        pkg_dir = service.build_reader_package(
            output_dir=str(tmp_path / "pkg"),
            manifest=manifest,
        )
        assert pkg_dir.exists()
        manifest_path = pkg_dir / "manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["book_id"] == "test_book_001"

    def test_build_package_with_content(self, tmp_path):
        service = PackagingService()
        manifest = ReaderPackageManifest(
            book_id="test_book_002",
            title="Test Book 2",
        )
        pkg_dir = service.build_reader_package(
            output_dir=str(tmp_path / "pkg2"),
            manifest=manifest,
            cleaned_html="<html><body>test</body></html>",
            segments_jsonl='{"id":"s001","text":"测试"}\n',
            voices_json='{"voices":[]}',
        )
        assert (pkg_dir / "cleaned.html").exists()
        assert (pkg_dir / "segments.jsonl").exists()
        assert (pkg_dir / "voices.json").exists()
