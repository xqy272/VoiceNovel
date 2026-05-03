"""Tests for station aggregation API and job/exception control."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vn_core.store import ProjectStore
from vn_server.api import create_app

GOLDEN_BOOK = Path(__file__).parent / "golden_books" / "mountain_inn.txt"


@pytest.fixture
def client(tmp_path):
    data_dir = tmp_path / "data"
    store_path = str(tmp_path / "station.sqlite")
    app = create_app(data_dir=str(data_dir), store_path=store_path)
    return TestClient(app)


class TestStationAPI:
    def test_station_after_cold_start(self, client):
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_test",
        })
        client.post("/api/projects/st_test/chapters/ch001/cold-start")

        resp = client.get("/api/projects/st_test/station")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["book_id"] == "st_test"
        assert len(data["chapters"]) >= 1
        ch1 = data["chapters"][0]
        assert ch1["buffer"]["status"] == "ready"
        assert ch1["progress"]["playable"] is True
        assert ch1["progress"]["full_ready"] is False
        assert "queue" in data

    def test_station_after_full_bake(self, client):
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_full",
        })
        client.post("/api/bake", json={
            "book_id": "st_full", "chapter_id": "ch001",
        })

        resp = client.get("/api/projects/st_full/station")
        assert resp.status_code == 200
        ch1 = resp.json()["chapters"][0]
        assert ch1["full_package"]["status"] in ("ready", "invalid")
        assert ch1["full_package"]["dependency_ok"] in (True, False)

    def test_full_invalid_when_files_missing(self, tmp_path):
        """If reader_package has no files, station marks it invalid."""
        store_path = str(tmp_path / "st_invalid.sqlite")
        data_dir = str(tmp_path / "data_inv")
        app = create_app(data_dir=data_dir, store_path=store_path)
        client2 = TestClient(app)
        client2.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_inv",
        })
        client2.post("/api/bake", json={
            "book_id": "st_inv", "chapter_id": "ch001",
        })

        # Manually corrupt the package: delete all files
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("st_inv", "reader_package", "ch001")
        if pkg and pkg.get("file_path"):
            import shutil
            pdir = Path(pkg["file_path"])
            if pdir.exists():
                shutil.rmtree(str(pdir))
        store.close()

        resp = client2.get("/api/projects/st_inv/station")
        assert resp.status_code == 200
        ch1 = resp.json()["chapters"][0]
        assert ch1["full_package"]["status"] == "invalid", (
            f"Expected invalid, got {ch1['full_package']['status']}"
        )

    def test_buffer_fallback_when_full_invalid(self, tmp_path):
        """If full is invalid but buffer is valid, /buffer returns buffer."""
        store_path = str(tmp_path / "st_fb.sqlite")
        data_dir = str(tmp_path / "data_fb")
        app = create_app(data_dir=data_dir, store_path=store_path)
        client2 = TestClient(app)
        client2.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_fb",
        })
        client2.post("/api/projects/st_fb/chapters/ch001/cold-start")
        client2.post("/api/bake", json={
            "book_id": "st_fb", "chapter_id": "ch001",
        })

        # Corrupt full package files
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("st_fb", "reader_package", "ch001")
        if pkg and pkg.get("file_path"):
            import shutil
            pdir = Path(pkg["file_path"])
            if pdir.exists():
                shutil.rmtree(str(pdir))
        store.close()

        resp = client2.get("/api/projects/st_fb/chapters/ch001/buffer")
        assert resp.status_code == 200, resp.text
        assert resp.json()["package_kind"] == "buffer"


class TestJobControl:
    def test_retry_pending_job_returns_409(self, client):
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_retry",
        })
        resp = client.post("/api/jobs", json={
            "book_id": "st_retry", "chapter_id": "ch001",
            "stage": "tts_render", "priority": "P2",
        })
        job_id = resp.json()["job_id"]

        r = client.post(f"/api/jobs/{job_id}/retry")
        assert r.status_code == 409, r.text

    def test_cancel_pending_job(self, client):
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_cancel",
        })
        resp = client.post("/api/jobs", json={
            "book_id": "st_cancel", "chapter_id": "ch001",
            "stage": "tts_render", "priority": "P2",
        })
        job_id = resp.json()["job_id"]

        r = client.post(f"/api/jobs/{job_id}/cancel")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("cancelled") is True
        assert data.get("ok") is True

    def test_cancel_unknown_returns_404(self, client):
        r = client.post("/api/jobs/nonexistent_job_id/cancel")
        assert r.status_code == 404

    def test_jobs_per_chapter_not_leaking(self, tmp_path):
        """Station chapter.jobs should only contain that chapter's jobs."""
        store_path = str(tmp_path / "st_leak.sqlite")
        data_dir = str(tmp_path / "data_leak")
        app = create_app(data_dir=data_dir, store_path=store_path)
        client2 = TestClient(app)
        client2.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_leak",
        })
        # Submit job for ch001
        client2.post("/api/jobs", json={
            "book_id": "st_leak", "chapter_id": "ch001",
        })
        # Submit job for ch002
        client2.post("/api/jobs", json={
            "book_id": "st_leak", "chapter_id": "ch002",
        })

        resp = client2.get("/api/projects/st_leak/station")
        data = resp.json()
        for ch in data["chapters"]:
            for job in ch["jobs"]:
                # Job must belong to this chapter
                assert job.get("unit_id") == ch["chapter_id"], (
                    f"Job {job.get('job_id')} unit_id={job.get('unit_id')}"
                    f" not matching chapter {ch['chapter_id']}"
                )


class TestExceptionsAPI:
    @pytest.fixture
    def exc_client(self, tmp_path):
        store_path = str(tmp_path / "exc_ctl.sqlite")
        data_dir = str(tmp_path / "data_exc")
        app = create_app(data_dir=data_dir, store_path=store_path)
        return TestClient(app)

    def test_list_and_resolve(self, exc_client, tmp_path):
        store_path = str(tmp_path / "exc_ctl.sqlite")
        store = ProjectStore(store_path)
        store.initialize()
        exc_client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_exc",
        })

        conn = store._get_conn()
        sql = (
            "INSERT INTO exceptions"
            " (exception_id, book_id, exception_type, severity, status,"
            " unit_id, stage, message)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        conn.execute(sql, (
            "exc_test_001", "st_exc", "tts_timeout", "high", "open",
            "ch001", "tts_render", "test error",
        ))
        conn.commit()

        # List open exceptions
        resp = exc_client.get("/api/exceptions?book_id=st_exc&status=open")
        assert resp.status_code == 200
        excs = resp.json()["exceptions"]
        assert len(excs) >= 1

        # Resolve
        r2 = exc_client.post("/api/exceptions/exc_test_001/resolve")
        assert r2.status_code == 200

        # Open list should be empty now
        r3 = exc_client.get("/api/exceptions?book_id=st_exc&status=open")
        assert len(r3.json()["exceptions"]) == 0
        store.close()

    def test_resolve_unknown_returns_404(self, exc_client):
        r = exc_client.post("/api/exceptions/nonexistent_999/resolve")
        assert r.status_code == 404, r.text

    def test_unit_id_filter(self, exc_client, tmp_path):
        store_path = str(tmp_path / "exc_ctl.sqlite")
        store = ProjectStore(store_path)
        store.initialize()
        exc_client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_uf",
        })

        conn = store._get_conn()
        sql = (
            "INSERT INTO exceptions"
            " (exception_id, book_id, exception_type, severity, status,"
            " unit_id, stage, message)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        conn.execute(sql, (
            "exc_uf_001", "st_uf", "tts_timeout", "high", "open",
            "ch001", "tts_render", "ch001 error",
        ))
        conn.execute(sql, (
            "exc_uf_002", "st_uf", "tts_timeout", "high", "open",
            "ch002", "tts_render", "ch002 error",
        ))
        conn.commit()

        # Filter by ch001
        r1 = exc_client.get(
            "/api/exceptions?book_id=st_uf&status=open&unit_id=ch001",
        )
        excs = r1.json()["exceptions"]
        assert len(excs) == 1
        assert excs[0]["unit_id"] == "ch001"

        # Filter by ch002
        r2 = exc_client.get(
            "/api/exceptions?book_id=st_uf&status=open&unit_id=ch002",
        )
        assert len(r2.json()["exceptions"]) == 1
        assert r2.json()["exceptions"][0]["unit_id"] == "ch002"
        store.close()

    def test_station_shows_open_exception(self, exc_client, tmp_path):
        store_path = str(tmp_path / "exc_ctl.sqlite")
        store = ProjectStore(store_path)
        store.initialize()
        exc_client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_exc2",
        })
        exc_client.post("/api/projects/st_exc2/chapters/ch001/cold-start")

        conn = store._get_conn()
        sql = (
            "INSERT INTO exceptions"
            " (exception_id, book_id, exception_type, severity, status,"
            " unit_id, stage, message)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        conn.execute(sql, (
            "exc_station_001", "st_exc2", "tts_timeout", "high", "open",
            "ch001", "tts_render", "station test error",
        ))
        conn.commit()

        resp = exc_client.get("/api/projects/st_exc2/station")
        assert resp.status_code == 200
        ch1 = resp.json()["chapters"][0]
        assert ch1["progress"]["has_open_exceptions"] is True
        assert len(ch1["exceptions"]) >= 1
        store.close()

    def test_resolve_second_exception_succeeds(self, exc_client, tmp_path):
        """Resolving the second of two exceptions must work (not just the first)."""
        store_path = str(tmp_path / "exc_ctl.sqlite")
        store = ProjectStore(store_path)
        store.initialize()
        exc_client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_res2",
        })

        conn = store._get_conn()
        sql = (
            "INSERT INTO exceptions"
            " (exception_id, book_id, exception_type, severity, status,"
            " unit_id, stage, message)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        conn.execute(sql, ("exc_a", "st_res2", "tts_timeout", "high", "open", "ch001", "x", "e1"))
        conn.execute(sql, ("exc_b", "st_res2", "tts_timeout", "high", "open", "ch001", "x", "e2"))
        conn.commit()

        # Resolve the second exception — must succeed
        r = exc_client.post("/api/exceptions/exc_b/resolve")
        assert r.status_code == 200, r.text

        # exc_b no longer in open list
        r2 = exc_client.get("/api/exceptions?book_id=st_res2&status=open")
        open_ids = {e["exception_id"] for e in r2.json()["exceptions"]}
        assert "exc_b" not in open_ids
        store.close()

    def test_resolve_nonexistent_returns_404(self, exc_client):
        r = exc_client.post("/api/exceptions/definitely_not_real_999/resolve")
        assert r.status_code == 404


class TestBufferInvalidFallback:
    @pytest.fixture
    def buf_client(self, tmp_path):
        store_path = str(tmp_path / "st_buf.sqlite")
        data_dir = str(tmp_path / "data_buf")
        app = create_app(data_dir=data_dir, store_path=store_path)
        return TestClient(app)

    def test_invalid_full_no_valid_buffer_returns_404(self, buf_client, tmp_path):
        """Only invalid reader_package, no window_package → /buffer 404."""
        store_path = str(tmp_path / "st_buf.sqlite")
        buf_client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_nobuf",
        })
        buf_client.post("/api/bake", json={
            "book_id": "st_nobuf", "chapter_id": "ch001",
        })
        # Corrupt files
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("st_nobuf", "reader_package", "ch001")
        if pkg and pkg.get("file_path"):
            import shutil
            pdir = Path(pkg["file_path"])
            if pdir.exists():
                shutil.rmtree(str(pdir))
        store.close()

        resp = buf_client.get("/api/projects/st_nobuf/chapters/ch001/buffer")
        assert resp.status_code == 404, resp.text

    def test_invalid_both_returns_404(self, buf_client, tmp_path):
        store_path = str(tmp_path / "st_buf.sqlite")
        buf_client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_both",
        })
        buf_client.post("/api/projects/st_both/chapters/ch001/cold-start")
        buf_client.post("/api/bake", json={
            "book_id": "st_both", "chapter_id": "ch001",
        })
        # Corrupt all packages
        store = ProjectStore(store_path)
        for atype in ("reader_package", "window_package"):
            art = store.get_active_artifact("st_both", atype, "ch001")
            if art and art.get("file_path"):
                import shutil
                pdir = Path(art["file_path"])
                if pdir.exists():
                    shutil.rmtree(str(pdir))
        store.close()

        resp = buf_client.get("/api/projects/st_both/chapters/ch001/buffer")
        assert resp.status_code == 404, resp.text

    def test_invalid_full_valid_buffer_returns_buffer(self, buf_client, tmp_path):
        store_path = str(tmp_path / "st_buf.sqlite")
        buf_client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_ifvb",
        })
        buf_client.post("/api/projects/st_ifvb/chapters/ch001/cold-start")
        buf_client.post("/api/bake", json={
            "book_id": "st_ifvb", "chapter_id": "ch001",
        })
        # Only corrupt full package
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("st_ifvb", "reader_package", "ch001")
        if pkg and pkg.get("file_path"):
            import shutil
            pdir = Path(pkg["file_path"])
            if pdir.exists():
                shutil.rmtree(str(pdir))
        store.close()

        resp = buf_client.get("/api/projects/st_ifvb/chapters/ch001/buffer")
        assert resp.status_code == 200, resp.text
        assert resp.json()["package_kind"] == "buffer"

    def test_valid_full_valid_buffer_returns_full(self, buf_client):
        buf_client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_vfvb",
        })
        buf_client.post("/api/projects/st_vfvb/chapters/ch001/cold-start")
        buf_client.post("/api/bake", json={
            "book_id": "st_vfvb", "chapter_id": "ch001",
        })

        resp = buf_client.get("/api/projects/st_vfvb/chapters/ch001/buffer")
        assert resp.status_code == 200, resp.text
        assert resp.json()["package_kind"] == "full"


class TestPreflightChapterOp:
    """Preflight validation on bake/cold-start/rebuild rejects bad chapters."""

    @pytest.fixture
    def pf_client(self, tmp_path):
        store_path = str(tmp_path / "pf.sqlite")
        data_dir = str(tmp_path / "data_pf")
        from fastapi.testclient import TestClient

        from vn_server.api import create_app
        app = create_app(data_dir=data_dir, store_path=store_path)
        return TestClient(app)

    def _import(self, client):
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "pf_test",
        })

    def test_bake_missing_chapter_returns_409(self, pf_client, tmp_path):
        store_path = str(tmp_path / "pf.sqlite")
        self._import(pf_client)
        r = pf_client.post("/api/bake", json={
            "book_id": "pf_test", "chapter_id": "ch999_nonexistent",
        })
        assert r.status_code == 409, r.text
        # Exception must be written
        from vn_core.store import ProjectStore
        store = ProjectStore(store_path)
        excs = store.list_exceptions(book_id="pf_test", status="open")
        assert any("ch999_nonexistent" in str(e.get("message", "")) for e in excs), \
            f"No exception for missing chapter. Exceptions: {excs}"
        store.close()

    def test_cold_start_missing_chapter_returns_409(self, pf_client, tmp_path):
        store_path = str(tmp_path / "pf.sqlite")
        self._import(pf_client)
        r = pf_client.post("/api/projects/pf_test/chapters/ch999/cold-start")
        assert r.status_code == 409, r.text
        from vn_core.store import ProjectStore
        store = ProjectStore(store_path)
        excs = store.list_exceptions(book_id="pf_test", status="open")
        assert any("ch999" in str(e.get("message", "")) for e in excs), \
            f"No exception for missing chapter. Exceptions: {excs}"
        store.close()

    def test_rebuild_missing_chapter_returns_409(self, pf_client, tmp_path):
        store_path = str(tmp_path / "pf.sqlite")
        self._import(pf_client)
        r = pf_client.post("/api/projects/pf_test/chapters/ch999/rebuild")
        assert r.status_code == 409, r.text
        from vn_core.store import ProjectStore
        store = ProjectStore(store_path)
        excs = store.list_exceptions(book_id="pf_test", status="open")
        assert any("ch999" in str(e.get("message", "")) for e in excs), \
            f"No exception for missing chapter. Exceptions: {excs}"
        store.close()

    def test_bake_missing_book_returns_409(self, pf_client, tmp_path):
        store_path = str(tmp_path / "pf.sqlite")
        r = pf_client.post("/api/bake", json={
            "book_id": "nonexistent_book", "chapter_id": "ch001",
        })
        assert r.status_code == 409, r.text
        from vn_core.store import ProjectStore
        store = ProjectStore(store_path)
        excs = store.list_exceptions(book_id="nonexistent_book", status="open")
        assert any("not found" in str(e.get("message", "")).lower() for e in excs), \
            f"No exception for missing book. Exceptions: {excs}"
        store.close()

    def test_cold_start_missing_book_returns_409(self, pf_client, tmp_path):
        store_path = str(tmp_path / "pf.sqlite")
        r = pf_client.post(
            "/api/projects/nonexistent_book/chapters/ch001/cold-start",
        )
        assert r.status_code == 409, r.text
        from vn_core.store import ProjectStore
        store = ProjectStore(store_path)
        excs = store.list_exceptions(book_id="nonexistent_book", status="open")
        assert any("not found" in str(e.get("message", "")).lower() for e in excs), \
            f"No exception for missing book. Exceptions: {excs}"
        store.close()

    def test_rebuild_missing_book_returns_409(self, pf_client, tmp_path):
        store_path = str(tmp_path / "pf.sqlite")
        r = pf_client.post(
            "/api/projects/nonexistent_book/chapters/ch001/rebuild",
        )
        assert r.status_code == 409, r.text
        from vn_core.store import ProjectStore
        store = ProjectStore(store_path)
        excs = store.list_exceptions(book_id="nonexistent_book", status="open")
        assert any("not found" in str(e.get("message", "")).lower() for e in excs), \
            f"No exception for missing book. Exceptions: {excs}"
        store.close()

    def test_bake_missing_generation_config_returns_409(self, pf_client, tmp_path):
        """Missing generation_config_id must return 409, write exception, no pipeline."""
        store_path = str(tmp_path / "pf.sqlite")
        self._import(pf_client)
        r = pf_client.post("/api/bake", json={
            "book_id": "pf_test", "chapter_id": "ch001",
            "generation_config_id": "missing_cfg",
        })
        assert r.status_code == 409, r.text
        from vn_core.store import ProjectStore
        store = ProjectStore(store_path)
        excs = store.list_exceptions(book_id="pf_test", status="open")
        assert any(
            "missing_cfg" in str(e.get("message", "")) for e in excs
        ), f"No exception for missing config. Exceptions: {excs}"
        # No reader_package should have been created
        pkg = store.get_current_artifact("pf_test", "reader_package", "ch001")
        assert pkg is None or pkg.get("status") != "active", (
            f"No reader_package should exist after preflight rejection. Got: {pkg}"
        )
        store.close()
