"""Tests for export API with StageResult atomic commit."""

from pathlib import Path
from unittest import mock

import pytest

from vn_core.harness import GateDecision, GateResult
from vn_core.store import ProjectStore

GOLDEN_BOOK = Path(__file__).parent / "golden_books" / "mountain_inn.txt"


def _assert_export_exception(store, book_id, chapter_id, fmt, fragment=""):
    """Assert an open export_failure exception exists with expected fields."""
    excs = store.list_exceptions(book_id=book_id, status="open")
    matching = [
        e for e in excs
        if (e.get("exception_type") == "export_failure"
            and e.get("stage") == f"export_{fmt}"
            and e.get("unit_id") == chapter_id)
    ]
    keys = ("exception_type", "stage", "unit_id", "message")
    assert len(matching) >= 1, (
        f"No export_failure exception for stage=export_{fmt} unit={chapter_id}. "
        f"Open: {[{k: e.get(k) for k in keys} for e in excs]}"
    )
    if fragment:
        msg = matching[0].get("message", "")
        assert fragment in msg, (
            f"Exception message does not contain '{fragment}': {msg}"
        )


class TestExportAPI:
    @pytest.fixture
    def client(self, tmp_path):
        from fastapi.testclient import TestClient

        from vn_server.api import create_app
        data_dir = tmp_path / "data"
        store_path = str(tmp_path / "exp.sqlite")
        app = create_app(data_dir=str(data_dir), store_path=store_path)
        return TestClient(app)

    def _bake(self, client, book_id):
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": book_id,
        })
        client.post("/api/bake", json={
            "book_id": book_id, "chapter_id": "ch001",
        })

    # --- success paths ---

    def test_export_daw_success(self, client):
        self._bake(client, "ex_ok")
        r = client.post("/api/projects/ex_ok/chapters/ch001/exports?format=daw")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["format"] == "daw"
        assert data["artifact_version_id"].startswith("ex_ok_export_daw")
        assert Path(data["output_dir"]).exists()

    def test_export_artifact_and_dependency(self, client, tmp_path):
        store_path = str(tmp_path / "exp.sqlite")
        self._bake(client, "ex_dep")
        client.post("/api/projects/ex_dep/chapters/ch001/exports?format=daw")

        store = ProjectStore(store_path)
        art = store.get_active_artifact("ex_dep", "export_daw", "ch001")
        assert art is not None, "Export artifact must be active"
        deps_ok = store.check_dependencies_active("ex_dep", art["artifact_version_id"])
        assert deps_ok["all_active"], f"Deps not active: {deps_ok}"
        deps = store.get_artifact_dependencies("ex_dep", art["artifact_version_id"])
        assert len(deps) >= 1
        assert deps[0]["dependency_role"] == "reader_package"
        store.close()

    def test_export_audiobookshelf(self, client):
        self._bake(client, "ex_abs")
        r = client.post(
            "/api/projects/ex_abs/chapters/ch001/exports?format=audiobookshelf",
        )
        assert r.status_code == 200, r.text
        assert r.json()["format"] == "audiobookshelf"

    def test_export_m4b(self, client):
        self._bake(client, "ex_m4b")
        r = client.post("/api/projects/ex_m4b/chapters/ch001/exports?format=m4b")
        assert r.status_code == 200, r.text
        assert r.json()["format"] == "m4b"

    def test_export_no_package_returns_409(self, client):
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "ex_nopkg",
        })
        r = client.post("/api/projects/ex_nopkg/chapters/ch001/exports?format=daw")
        assert r.status_code == 409, r.text

    # --- timing.json error paths ---

    def test_export_missing_timing_returns_409(self, client, tmp_path):
        """Missing timing.json must return exactly 409, write exception, no artifact."""
        store_path = str(tmp_path / "exp.sqlite")
        data_dir = str(tmp_path / "data_mt")
        from fastapi.testclient import TestClient

        from vn_server.api import create_app
        app = create_app(data_dir=data_dir, store_path=store_path)
        c2 = TestClient(app)
        c2.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "ex_mt",
        })
        c2.post("/api/bake", json={
            "book_id": "ex_mt", "chapter_id": "ch001",
        })
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("ex_mt", "reader_package", "ch001")
        if pkg and pkg["file_path"]:
            (Path(pkg["file_path"]) / "timing.json").unlink()
        store.close()
        r = c2.post("/api/projects/ex_mt/chapters/ch001/exports?format=daw")
        assert r.status_code == 409, (
            f"Expected 409 for missing timing, got {r.status_code}: {r.text}"
        )
        store3 = ProjectStore(store_path)
        _assert_export_exception(store3, "ex_mt", "ch001", "daw",
                                 "timing.json not found")
        art = store3.get_active_artifact("ex_mt", "export_daw", "ch001")
        assert art is None, "No export artifact should exist after missing timing"
        store3.close()

    def test_export_malformed_timing_returns_422(self, client, tmp_path):
        """Corrupt timing.json must return exactly 422, write exception, no artifact."""
        store_path = str(tmp_path / "exp.sqlite")
        data_dir = str(tmp_path / "data_mal")
        from fastapi.testclient import TestClient

        from vn_server.api import create_app
        app = create_app(data_dir=data_dir, store_path=store_path)
        c2 = TestClient(app)
        c2.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "ex_mal",
        })
        c2.post("/api/bake", json={
            "book_id": "ex_mal", "chapter_id": "ch001",
        })
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("ex_mal", "reader_package", "ch001")
        assert pkg and pkg["file_path"], "reader_package must exist"
        (Path(pkg["file_path"]) / "timing.json").write_text(
            "{not valid json!!!", encoding="utf-8",
        )
        store.close()

        r = c2.post("/api/projects/ex_mal/chapters/ch001/exports?format=daw")
        assert r.status_code == 422, (
            f"Expected 422 for malformed timing, got {r.status_code}: {r.text}"
        )
        store2 = ProjectStore(store_path)
        _assert_export_exception(store2, "ex_mal", "ch001", "daw", "not valid JSON")
        art = store2.get_active_artifact("ex_mal", "export_daw", "ch001")
        assert art is None, "No export artifact should exist after malformed timing"
        store2.close()

    def test_export_malformed_timing_bad_schema_returns_422(self, client, tmp_path):
        """Invalid TimingEntry schema must return exactly 422, write exception, no artifact."""
        store_path = str(tmp_path / "exp.sqlite")
        data_dir = str(tmp_path / "data_badschema")
        from fastapi.testclient import TestClient

        from vn_server.api import create_app
        app = create_app(data_dir=data_dir, store_path=store_path)
        c2 = TestClient(app)
        c2.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "ex_bads",
        })
        c2.post("/api/bake", json={
            "book_id": "ex_bads", "chapter_id": "ch001",
        })
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("ex_bads", "reader_package", "ch001")
        assert pkg and pkg["file_path"]
        import json
        (Path(pkg["file_path"]) / "timing.json").write_text(
            json.dumps([{"not_a_valid_field": 1}]),
            encoding="utf-8",
        )
        store.close()

        r = c2.post("/api/projects/ex_bads/chapters/ch001/exports?format=daw")
        assert r.status_code == 422, (
            f"Expected 422 for bad schema, got {r.status_code}: {r.text}"
        )
        store2 = ProjectStore(store_path)
        _assert_export_exception(store2, "ex_bads", "ch001", "daw", "validation failed")
        art = store2.get_active_artifact("ex_bads", "export_daw", "ch001")
        assert art is None, "No export artifact should exist after schema validation failure"
        store2.close()

    # --- generation failure cleanup ---

    def test_export_generation_failure_cleans_temp_dir(self, client, tmp_path):
        """If export generation writes partial files then raises, temp dir is cleaned."""
        store_path = str(tmp_path / "exp.sqlite")
        data_dir = str(tmp_path / "data_gf")
        from fastapi.testclient import TestClient

        from vn_server.api import create_app
        app = create_app(data_dir=data_dir, store_path=store_path)
        c2 = TestClient(app)
        self._bake(c2, "ex_gf")

        def _fake_export_that_fails(*args, **kwargs):
            out_dir = kwargs.get("output_dir", args[0] if args else ".")
            # Write partial files to simulate mid-generation failure
            partial = Path(out_dir) / "partial_output.txt"
            partial.write_text("partial content", encoding="utf-8")
            (Path(out_dir) / "subdir").mkdir(exist_ok=True)
            raise RuntimeError("simulated export crash")

        with mock.patch(
            "vn_core.export.daw.export_daw_package", _fake_export_that_fails,
        ):
            r = c2.post("/api/projects/ex_gf/chapters/ch001/exports?format=daw")

        assert r.status_code == 422, (
            f"Expected 422 on generation failure, got {r.status_code}: {r.text}"
        )
        # Exception written
        store2 = ProjectStore(store_path)
        _assert_export_exception(store2, "ex_gf", "ch001", "daw",
                                 "simulated export crash")
        # No export artifact
        art = store2.get_active_artifact("ex_gf", "export_daw", "ch001")
        assert art is None, "No export artifact should exist after generation failure"

        # Temp dir must not exist
        export_root = Path(data_dir) / "exports" / "ex_gf" / "ch001"
        if export_root.exists():
            for p in export_root.iterdir():
                if p.name.startswith(".tmp_"):
                    assert False, f"Temp dir should be cleaned: {p}"
        store2.close()

    # --- commit_stage_result failure ---

    def test_no_orphan_artifact_on_commit_failure(self, client, tmp_path):
        """If commit_stage_result fails, no artifact remains and output is cleaned."""
        store_path = str(tmp_path / "exp.sqlite")
        data_dir = str(tmp_path / "data_or")
        from fastapi.testclient import TestClient

        from vn_server.api import create_app
        app = create_app(data_dir=data_dir, store_path=store_path)
        c2 = TestClient(app)
        self._bake(c2, "ex_or")

        def _fake_commit_fail(self, store_arg, result):
            return GateResult(
                decision=GateDecision.fail_decision,
                reason="test injected commit failure",
            )

        with mock.patch(
            "vn_core.harness.HarnessGate.commit_stage_result", _fake_commit_fail,
        ):
            r = c2.post("/api/projects/ex_or/chapters/ch001/exports?format=daw")

        assert r.status_code == 409, (
            f"Expected 409 on commit failure, got {r.status_code}: {r.text}"
        )
        store2 = ProjectStore(store_path)
        art = store2.get_active_artifact("ex_or", "export_daw", "ch001")
        assert art is None, "No export artifact should exist after commit failure"

        # Output dir must not contain actual export artifacts
        export_root = Path(data_dir) / "exports" / "ex_or" / "ch001"
        if export_root.exists():
            for p in export_root.iterdir():
                if p.name.startswith(".tmp_"):
                    assert False, f"Temp dir should be cleaned: {p}"
                # Only empty dirs or dirs named after versions are allowed...
                # but commit failed so no version dir should have content
                assert p.is_dir() and not any(p.iterdir()), (
                    f"Export output directory {p} should be empty after cleanup"
                )
        store2.close()

    def test_unknown_format_400(self, client):
        self._bake(client, "ex_bad")
        r = client.post("/api/projects/ex_bad/chapters/ch001/exports?format=unknown")
        assert r.status_code == 400, r.text

    # --- list_exports filtering ---

    def test_list_exports_default_active_invalidated(self, client, tmp_path):
        """Default list_exports returns only active + invalidated, not superseded."""
        self._bake(client, "ex_list")
        # Export twice → first gets superseded, second is active
        client.post("/api/projects/ex_list/chapters/ch001/exports?format=daw")
        client.post("/api/projects/ex_list/chapters/ch001/exports?format=daw")

        r = client.get("/api/projects/ex_list/exports")
        assert r.status_code == 200, r.text
        exports = r.json()["exports"]
        statuses = [e["status"] for e in exports]
        assert "superseded" not in statuses, (
            f"Superseded exports should not appear by default. Got: {statuses}"
        )
        assert any(s == "active" for s in statuses), "Active export should appear"

    def test_list_exports_filter_by_format(self, client, tmp_path):
        """format filter returns only that export type."""
        self._bake(client, "ex_fmt")
        client.post("/api/projects/ex_fmt/chapters/ch001/exports?format=daw")
        client.post("/api/projects/ex_fmt/chapters/ch001/exports?format=audiobookshelf")

        r = client.get("/api/projects/ex_fmt/exports?format=daw")
        assert r.status_code == 200
        exports = r.json()["exports"]
        for e in exports:
            assert e["artifact_type"] == "export_daw", (
                f"Expected only daw exports, got {e['artifact_type']}"
            )

    def test_list_exports_filter_by_chapter(self, client, tmp_path):
        """chapter_id filter returns only exports for that chapter."""
        self._bake(client, "ex_ch")

        # Also create another chapter (ch002) via cold-start+bake if possible
        # For simplicity, just export ch001 and check filter
        client.post("/api/projects/ex_ch/chapters/ch001/exports?format=daw")

        r = client.get("/api/projects/ex_ch/exports?chapter_id=ch999")
        assert r.status_code == 200
        assert len(r.json()["exports"]) == 0

        r2 = client.get("/api/projects/ex_ch/exports?chapter_id=ch001")
        assert r2.status_code == 200
        assert len(r2.json()["exports"]) >= 1

    # --- download / browse ---

    def test_get_export_artifact_metadata(self, client, tmp_path):
        """GET .../exports/{vid} returns artifact metadata with deps."""
        self._bake(client, "ex_meta")
        r = client.post("/api/projects/ex_meta/chapters/ch001/exports?format=daw")
        vid = r.json()["artifact_version_id"]

        r2 = client.get(f"/api/projects/ex_meta/exports/{vid}")
        assert r2.status_code == 200, r2.text
        data = r2.json()
        assert data["artifact"]["artifact_version_id"] == vid
        assert len(data["dependencies"]) >= 1
        assert data["downloadable"] is True

    def test_get_export_artifact_404(self, client):
        r = client.get("/api/projects/nonexistent/exports/fake_vid_123")
        assert r.status_code == 404, r.text

    def test_download_export_zip(self, client, tmp_path):
        """Download active export returns ZIP for directory exports."""
        self._bake(client, "ex_dl")
        r = client.post("/api/projects/ex_dl/chapters/ch001/exports?format=daw")
        vid = r.json()["artifact_version_id"]

        r2 = client.get(f"/api/projects/ex_dl/exports/{vid}/download")
        assert r2.status_code == 200, r2.text
        assert r2.headers.get("content-type", "").startswith("application/zip")

    def test_download_inactive_blocked(self, client, tmp_path):
        """Download of invalidated export returns 409 without include_inactive."""
        store_path = str(tmp_path / "exp.sqlite")
        self._bake(client, "ex_blk")
        r = client.post("/api/projects/ex_blk/chapters/ch001/exports?format=daw")
        vid = r.json()["artifact_version_id"]

        store = ProjectStore(store_path)
        store.invalidate_artifact("ex_blk", vid, "test invalidation")
        store.close()

        r2 = client.get(f"/api/projects/ex_blk/exports/{vid}/download")
        assert r2.status_code == 409, r2.text

    def test_download_inactive_allowed_with_flag(self, client, tmp_path):
        """include_inactive=true allows download of invalidated export."""
        store_path = str(tmp_path / "exp.sqlite")
        self._bake(client, "ex_allow")
        r = client.post("/api/projects/ex_allow/chapters/ch001/exports?format=daw")
        vid = r.json()["artifact_version_id"]

        store = ProjectStore(store_path)
        store.invalidate_artifact("ex_allow", vid, "test invalidation")
        store.close()

        r2 = client.get(
            f"/api/projects/ex_allow/exports/{vid}/download?include_inactive=true",
        )
        assert r2.status_code == 200, r2.text

    # --- invalidation cascade ---

    def test_export_invalidated_when_reader_package_invalidated(self, client, tmp_path):
        """When reader_package is invalidated, export artifacts follow."""
        store_path = str(tmp_path / "exp.sqlite")
        self._bake(client, "ex_inv")
        r = client.post("/api/projects/ex_inv/chapters/ch001/exports?format=daw")
        assert r.status_code == 200, r.text
        vid = r.json()["artifact_version_id"]

        store = ProjectStore(store_path)
        # Verify export is active
        art = store.get_active_artifact("ex_inv", "export_daw", "ch001")
        assert art is not None
        assert art["status"] == "active"

        # Invalidate reader_package dependents
        pkg = store.get_active_artifact("ex_inv", "reader_package", "ch001")
        assert pkg is not None
        invalidated = store.invalidate_dependents(
            "ex_inv", pkg["artifact_version_id"],
            reason="test reader_package invalidation",
        )
        assert len(invalidated) >= 1, "Export artifact should be invalidated"
        assert vid in invalidated, (
            f"Export {vid} should be in invalidated list: {invalidated}"
        )

        # Verify export is now invalidated
        art2 = store.get_active_artifact("ex_inv", "export_daw", "ch001")
        assert art2 is None or art2.get("status") != "active", (
            "Export artifact should no longer be active"
        )

        # list_exports should show invalidated status with reason
        r2 = client.get("/api/projects/ex_inv/exports")
        assert r2.status_code == 200
        exports = r2.json()["exports"]
        export = next((e for e in exports if e["artifact_version_id"] == vid), None)
        assert export is not None, "Export should appear in list"
        assert export["status"] == "invalidated", (
            f"Export should be invalidated, got {export.get('status')}"
        )
        reason = export.get("invalidated_reason", "")
        assert "test reader_package invalidation" in reason, (
            f"invalidated_reason should contain the invalidation reason. Got: {reason}"
        )
        store.close()

    # --- security: type-based rejection ---

    def test_browse_non_export_artifact_returns_404(self, client, tmp_path):
        """Browse endpoint must not leak existence of non-export artifacts."""
        store_path = str(tmp_path / "exp.sqlite")
        self._bake(client, "ex_sec1")
        # Get a reader_package version_id
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("ex_sec1", "reader_package", "ch001")
        assert pkg is not None
        pkg_vid = pkg["artifact_version_id"]
        store.close()

        r = client.get(f"/api/projects/ex_sec1/exports/{pkg_vid}")
        assert r.status_code == 404, (
            f"Non-export artifact must return 404, got {r.status_code}: {r.text}"
        )

    def test_download_non_export_artifact_returns_404(self, client, tmp_path):
        """Download endpoint must reject non-export artifact types with 404."""
        store_path = str(tmp_path / "exp.sqlite")
        self._bake(client, "ex_sec2")
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("ex_sec2", "reader_package", "ch001")
        assert pkg is not None
        pkg_vid = pkg["artifact_version_id"]
        store.close()

        r = client.get(f"/api/projects/ex_sec2/exports/{pkg_vid}/download")
        assert r.status_code == 404, (
            f"Download of non-export artifact must return 404, got {r.status_code}: {r.text}"
        )

    # --- security: path scope ---

    def test_download_path_outside_export_dir_returns_409(self, client, tmp_path):
        """Artifact with file_path outside exports/book_id must be rejected."""
        store_path = str(tmp_path / "exp.sqlite")
        data_dir = str(tmp_path / "data_ps")
        from fastapi.testclient import TestClient

        from vn_server.api import create_app
        app = create_app(data_dir=data_dir, store_path=store_path)
        c2 = TestClient(app)
        self._bake(c2, "ex_path")

        # Insert a malicious export artifact with file_path outside exports/
        store = ProjectStore(store_path)
        evil_path = str(tmp_path / "secret.txt")
        Path(evil_path).write_text("secret", encoding="utf-8")
        conn = store._get_conn()
        conn.execute(
            """INSERT INTO artifacts
            (book_id, artifact_version_id, artifact_type, unit_id,
             schema_version, input_hash, status, file_path, metadata)
            VALUES (?, ?, ?, ?, '0.1', '', 'active', ?, '{}')""",
            ("ex_path", "ex_path_export_daw_ch001_v999", "export_daw",
             "ch001", evil_path),
        )
        conn.commit()

        r = c2.get("/api/projects/ex_path/exports/ex_path_export_daw_ch001_v999/download")
        assert r.status_code in (404, 409), (
            f"Path outside export dir must be rejected, got {r.status_code}: {r.text}"
        )
        store.close()

    # --- ZIP content validation ---

    def test_download_daw_zip_contains_expected_files(self, client):
        """Downloaded DAW ZIP must contain project.json, markers, regions, cue sheet."""
        import io
        import zipfile

        self._bake(client, "ex_zipct")
        r = client.post("/api/projects/ex_zipct/chapters/ch001/exports?format=daw")
        assert r.status_code == 200, r.text
        vid = r.json()["artifact_version_id"]

        dl = client.get(f"/api/projects/ex_zipct/exports/{vid}/download")
        assert dl.status_code == 200, dl.text
        assert dl.headers.get("content-type", "").startswith("application/zip")

        # Open ZIP from response content
        bio = io.BytesIO(dl.content)
        with zipfile.ZipFile(bio, "r") as zf:
            names = set(zf.namelist())
            expected = {"project.json", "markers.json", "regions.json", "cue_sheet.txt"}
            missing = expected - names
            assert not missing, (
                f"DAW ZIP missing expected files: {missing}. Contains: {names}"
            )
            # Verify they're not empty
            for name in expected:
                info = zf.getinfo(name)
                assert info.file_size > 0, f"{name} is empty in ZIP"

    # --- list_exports fields and ordering ---

    def test_list_exports_fields_and_order(self, client, tmp_path):
        """list_exports returns consistent fields sorted by created_at DESC."""
        self._bake(client, "ex_flds")
        # Export twice
        r1 = client.post("/api/projects/ex_flds/chapters/ch001/exports?format=daw")
        assert r1.status_code == 200
        import time
        time.sleep(1.5)  # ensure created_at differs (SQLite second granularity)
        r2 = client.post("/api/projects/ex_flds/chapters/ch001/exports?format=audiobookshelf")
        assert r2.status_code == 200
        vid1 = r1.json()["artifact_version_id"]
        vid2 = r2.json()["artifact_version_id"]

        r = client.get("/api/projects/ex_flds/exports")
        assert r.status_code == 200
        exports = r.json()["exports"]
        assert len(exports) >= 2

        required_fields = {
            "artifact_version_id", "artifact_type", "unit_id",
            "status", "file_path", "created_at", "invalidated_reason",
        }
        for exp in exports:
            for fld in required_fields:
                assert fld in exp, f"Missing field {fld} in export entry: {list(exp.keys())}"

        # Sorted: newer first
        vids = [e["artifact_version_id"] for e in exports]
        idx1 = vids.index(vid1) if vid1 in vids else -1
        idx2 = vids.index(vid2) if vid2 in vids else -1
        assert idx2 < idx1, (
            f"Second export (audiobookshelf) should appear before first (daw)."
            f" Got order: {vids}"
        )

    # --- downloadable reflects path scope ---

    def test_export_outside_path_not_downloadable(self, client, tmp_path):
        """Artifact with file_path outside exports/ returns downloadable=false, dl→409."""
        store_path = str(tmp_path / "exp.sqlite")
        data_dir = str(tmp_path / "data_ops")
        from fastapi.testclient import TestClient

        from vn_server.api import create_app
        app = create_app(data_dir=data_dir, store_path=store_path)
        c2 = TestClient(app)
        self._bake(c2, "ex_ops")

        # Create file outside exports/ but exists on disk
        outside_path = tmp_path / "outside_export_dir"
        outside_path.mkdir()
        (outside_path / "dummy.txt").write_text("ok", encoding="utf-8")

        store = ProjectStore(store_path)
        conn = store._get_conn()
        conn.execute(
            """INSERT INTO artifacts
            (book_id, artifact_version_id, artifact_type, unit_id,
             schema_version, input_hash, status, file_path, metadata)
            VALUES (?, ?, ?, ?, '0.1', '', 'active', ?, '{}')""",
            ("ex_ops", "ex_ops_export_daw_ch001_v999", "export_daw",
             "ch001", str(outside_path)),
        )
        conn.commit()

        # GET metadata: downloadable must be false
        r_meta = c2.get("/api/projects/ex_ops/exports/ex_ops_export_daw_ch001_v999")
        assert r_meta.status_code == 200, r_meta.text
        assert r_meta.json()["downloadable"] is False, (
            f"downloadable must be false when path is outside exports/. "
            f"Got: {r_meta.json()}"
        )

        # GET download: must return 409
        r_dl = c2.get(
            "/api/projects/ex_ops/exports/ex_ops_export_daw_ch001_v999/download",
        )
        assert r_dl.status_code == 409, (
            f"Download of artifact outside exports/ must return 409, "
            f"got {r_dl.status_code}: {r_dl.text}"
        )
        store.close()
