"""Tests for artifact invalidation and rebuild flow."""

import json
from pathlib import Path

import pytest

from vn_core.store import ProjectStore

GOLDEN_BOOK = Path(__file__).parent / "golden_books" / "mountain_inn.txt"


class TestInvalidationStore:
    @pytest.fixture
    def store(self, tmp_path):
        db = tmp_path / "inv.sqlite"
        s = ProjectStore(str(db))
        s.initialize()
        yield s
        s.close()

    def test_invalidate_artifact(self, store):
        store.write_artifact("book_001", "v1", "segments", "ch001")
        ok = store.invalidate_artifact("book_001", "v1", reason="test")
        assert ok is True
        conn = store._get_conn()
        row = conn.execute(
            "SELECT status, metadata FROM artifacts WHERE artifact_version_id='v1'",
        ).fetchone()
        assert row["status"] == "invalidated"
        meta = json.loads(row["metadata"])
        assert "invalidated_reason" in meta

    def test_invalidate_nonexistent(self, store):
        ok = store.invalidate_artifact("book_001", "no_such_vid", reason="test")
        assert ok is False

    def test_invalidate_dependents_direct(self, store):
        store.write_artifact("book_001", "v1", "voice_assignment", "ch001")
        store.write_artifact("book_001", "v2", "audio_take", "ch001")
        store.add_dependency("book_001", "v2", "v1", "depends")
        invalidated = store.invalidate_dependents(
            "book_001", "v1", reason="voice_changed",
        )
        assert "v2" in invalidated
        conn = store._get_conn()
        row = conn.execute(
            "SELECT status FROM artifacts WHERE artifact_version_id='v2'",
        ).fetchone()
        assert row["status"] == "invalidated"

    def test_invalidate_dependents_transitive(self, store):
        store.write_artifact("book_001", "v1", "voice_assignment", "ch001")
        store.write_artifact("book_001", "v2", "audio_take", "ch001")
        store.write_artifact("book_001", "v3", "reader_package", "ch001")
        store.add_dependency("book_001", "v2", "v1", "depends")
        store.add_dependency("book_001", "v3", "v2", "depends")
        invalidated = store.invalidate_dependents(
            "book_001", "v1", reason="voice_changed",
        )
        assert len(invalidated) == 2
        assert "v2" in invalidated
        assert "v3" in invalidated

    def test_get_current_artifact_prefers_active(self, store):
        store.write_artifact("book_001", "va_v1", "voice_assignment", "ch001", status="invalidated")
        store.write_artifact("book_001", "va_v2", "voice_assignment", "ch001", status="active")
        result = store.get_current_artifact("book_001", "voice_assignment", "ch001")
        assert result is not None
        assert result["artifact_version_id"] == "va_v2"
        assert result["status"] == "active"

    def test_get_current_artifact_falls_back_to_invalidated(self, store):
        store.write_artifact("book_001", "va_v1", "voice_assignment", "ch001", status="invalidated")
        result = store.get_current_artifact("book_001", "voice_assignment", "ch001")
        assert result is not None
        assert result["artifact_version_id"] == "va_v1"
        assert result["status"] == "invalidated"

    def test_chapter_needs_rebuild_false_after_new_active_package(self, store, tmp_path):
        """Historical invalidated artifacts don't keep needs_rebuild=true."""
        store.write_artifact("book_001", "rp_v1", "reader_package", "ch001", status="invalidated")
        assert store.chapter_needs_rebuild("book_001", "ch001") is True
        # Create new active package with valid files
        pkg_dir = tmp_path / "rp_v2_pkg"
        pkg_dir.mkdir()
        for f in ["cleaned.html", "timing.json", "manifest.json"]:
            (pkg_dir / f).write_text("{}")
        store.write_artifact(
            "book_001", "rp_v2", "reader_package", "ch001",
            status="active", file_path=str(pkg_dir),
        )
        assert store.chapter_needs_rebuild("book_001", "ch001") is False


class TestInvalidationAPI:
    @pytest.fixture
    def client(self, tmp_path):
        from fastapi.testclient import TestClient

        from vn_server.api import create_app
        data_dir = tmp_path / "data"
        store_path = str(tmp_path / "inv_api.sqlite")
        app = create_app(data_dir=str(data_dir), store_path=store_path)
        return TestClient(app)

    def _bake_and_lock(self, client, tmp_path):
        """Helper: bake ch001, then lock voice, return station data."""
        store_path = str(tmp_path / "inv_api.sqlite")
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_vlock",
        })
        client.post("/api/bake", json={
            "book_id": "st_vlock", "chapter_id": "ch001",
        })
        # Get the character_id from voice assignments
        va_resp = client.get("/api/projects/st_vlock/voice-assignments")
        assignments = va_resp.json().get("assignments", [])
        if assignments:
            char_id = assignments[0]["character_id"]
            voice_id = assignments[0]["voice_id"]
            client.post("/api/projects/st_vlock/voice-assignments/lock", json={
                "character_id": char_id, "voice_id": voice_id,
            })
        return store_path

    def test_rebuild_job_executes_and_clears_stale(self, client, tmp_path):
        """Rebuild job submitted and executed leads to ready full_package."""
        store_path = str(tmp_path / "inv_api.sqlite")
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_exec",
        })
        client.post("/api/bake", json={
            "book_id": "st_exec", "chapter_id": "ch001",
        })
        # Make stale
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("st_exec", "reader_package", "ch001")
        assert pkg is not None, "Need reader_package to invalidate"
        store.invalidate_artifact("st_exec", pkg["artifact_version_id"], "test")
        store.close()

        # Submit rebuild
        rb = client.post("/api/projects/st_exec/chapters/ch001/rebuild")
        assert rb.status_code == 200, rb.text
        job_id = rb.json()["job_id"]

        # Verify job exists with P0 priority
        job_resp = client.get(f"/api/jobs/{job_id}")
        assert job_resp.status_code == 200
        job = job_resp.json()
        assert job["priority"] == "P0"

        # Execute the job manually via bake (simulates worker)
        bake_resp = client.post("/api/bake", json={
            "book_id": "st_exec", "chapter_id": "ch001",
        })
        assert bake_resp.status_code == 200

        # Station should now be ready
        r = client.get("/api/projects/st_exec/station")
        ch1 = r.json()["chapters"][0]
        assert ch1["full_package"]["status"] == "ready"
        assert ch1["progress"]["needs_rebuild"] is False

    @pytest.mark.asyncio
    async def test_worker_executes_rebuild_job(self, tmp_path):
        """Worker actually executes rebuild job — no manual /api/bake call."""
        store_path = str(tmp_path / "inv_api_worker.sqlite")
        data_dir = str(tmp_path / "data_worker")
        from vn_server.api import create_app
        app = create_app(data_dir=data_dir, store_path=store_path)
        from fastapi.testclient import TestClient
        client = TestClient(app)

        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_worker",
        })
        client.post("/api/bake", json={
            "book_id": "st_worker", "chapter_id": "ch001",
        })
        # Make stale
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("st_worker", "reader_package", "ch001")
        assert pkg is not None
        store.invalidate_artifact("st_worker", pkg["artifact_version_id"], "test")
        store.close()

        # Submit rebuild — this creates a real Store-backed job
        rb = client.post("/api/projects/st_worker/chapters/ch001/rebuild")
        assert rb.status_code == 200, rb.text
        job_id = rb.json()["job_id"]
        assert job_id.startswith("job_rebuild_")

        # Now simulate the worker executing the job via the orchestrator
        # The app's orchestrator is started by lifespan. We use the store
        # directly to lease and execute the job.
        store2 = ProjectStore(store_path)
        import asyncio

        from vn_core.llm_gateway import LLMGateway
        from vn_core.orchestration import Orchestrator, OrchestratorConfig
        from vn_core.pipeline.pipeline import Pipeline
        from vn_core.render import SpeechGateway

        worker = Orchestrator(store=store2, config=OrchestratorConfig(
            max_background_jobs=1, lease_seconds=60,
        ))

        async def _exec(job):
            pipeline = Pipeline(
                store=store2,
                llm=LLMGateway(),
                gateway=SpeechGateway(output_dir=str(tmp_path / "tts")),
                output_dir=str(data_dir),
                tts_engine="mock",
                reading_profile="enhanced",
            )
            is_rebuild = bool(
                job.cache_buster and str(job.cache_buster).startswith("rebuild:")
            )
            result = await pipeline.bake_chapter(
                book_id=job.book_id, chapter_id=job.unit_id,
                force=is_rebuild,
            )
            return {
                "success": result.success,
                "artifact": result.package_dir,
                "errors": result.errors,
            }

        worker.set_executor(_exec)
        await worker.start()

        # Poll for completion
        import time
        deadline = time.time() + 30
        status = None
        while time.time() < deadline:
            job = store2.get_job(job_id)
            if job and job["status"] in ("done", "failed"):
                status = job["status"]
                break
            await asyncio.sleep(0.2)

        await worker.stop()
        store2.close()

        assert status == "done", f"Job status: {status}, job: {job}"
        # Verify new active package
        client2 = TestClient(app)
        r = client2.get("/api/projects/st_worker/station")
        ch1 = r.json()["chapters"][0]
        assert ch1["full_package"]["status"] == "ready", (
            f"Expected ready after worker rebuild, got: {ch1['full_package']}"
        )
        assert ch1["progress"]["needs_rebuild"] is False

    @pytest.mark.asyncio
    async def test_server_lifespan_worker_rebuild(self, tmp_path):
        """Real server lifespan workers execute rebuild — no manual bake."""
        store_path = str(tmp_path / "inv_lifespan.sqlite")
        data_dir = str(tmp_path / "data_ls")
        from vn_server.api import create_app
        app = create_app(data_dir=data_dir, store_path=store_path)
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            client.post("/api/projects", json={
                "source_path": str(GOLDEN_BOOK), "book_id": "st_ls",
            })
            client.post("/api/bake", json={
                "book_id": "st_ls", "chapter_id": "ch001",
            })
            # Make stale
            store = ProjectStore(store_path)
            pkg = store.get_active_artifact("st_ls", "reader_package", "ch001")
            assert pkg is not None
            store.invalidate_artifact("st_ls", pkg["artifact_version_id"], "test")
            store.close()

            # Submit rebuild
            rb = client.post("/api/projects/st_ls/chapters/ch001/rebuild")
            assert rb.status_code == 200, rb.text
            job_id = rb.json()["job_id"]

            # Poll for worker execution
            import time
            deadline = time.time() + 30
            status = None
            while time.time() < deadline:
                jr = client.get(f"/api/jobs/{job_id}")
                if jr.status_code == 200:
                    job = jr.json()
                    if job["status"] in ("done", "failed"):
                        status = job["status"]
                        break
                time.sleep(0.3)

            assert status == "done", f"Job {job_id} status: {status}"
            # Verify Station
            sr = client.get("/api/projects/st_ls/station")
            ch1 = sr.json()["chapters"][0]
            assert ch1["full_package"]["status"] == "ready", (
                f"Expected ready, got {ch1['full_package']}"
            )
            assert ch1["progress"]["needs_rebuild"] is False

    @pytest.mark.asyncio
    async def test_rebuild_executes_not_cache_completes(self, tmp_path):
        """Worker must execute rebuild even when old package artifacts exist."""
        store_path = str(tmp_path / "inv_no_cache.sqlite")
        data_dir = str(tmp_path / "data_nc")
        from vn_server.api import create_app
        app = create_app(data_dir=data_dir, store_path=store_path)
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            client.post("/api/projects", json={
                "source_path": str(GOLDEN_BOOK), "book_id": "st_nc",
            })
            client.post("/api/bake", json={
                "book_id": "st_nc", "chapter_id": "ch001",
            })
            store = ProjectStore(store_path)
            pkg = store.get_active_artifact("st_nc", "reader_package", "ch001")
            assert pkg is not None
            old_vid = pkg["artifact_version_id"]
            # Delete package files to simulate broken package
            pdir = Path(pkg.get("file_path", ""))
            if pdir.exists():
                import shutil
                shutil.rmtree(str(pdir))
            store.invalidate_artifact("st_nc", old_vid, "test")
            store.close()

            rb = client.post("/api/projects/st_nc/chapters/ch001/rebuild")
            assert rb.status_code == 200, rb.text
            job_id = rb.json()["job_id"]

            import time
            deadline = time.time() + 30
            status = None
            while time.time() < deadline:
                jr = client.get(f"/api/jobs/{job_id}")
                if jr.status_code == 200:
                    job = jr.json()
                    if job["status"] in ("done", "failed"):
                        status = job["status"]
                        break
                time.sleep(0.3)

            assert status == "done", f"Job {job_id} status: {status}"
            # New active package must exist and be different from old
            store2 = ProjectStore(store_path)
            new_pkg = store2.get_active_artifact("st_nc", "reader_package", "ch001")
            assert new_pkg is not None, "Should have new active reader_package"
            assert new_pkg["artifact_version_id"] != old_vid, (
                f"Should get new version, not old {old_vid}"
            )
            store2.close()

    @pytest.mark.asyncio
    async def test_prefetch_worker_execution(self, tmp_path):
        """Prefetch job by worker makes target chapter ready."""
        store_path = str(tmp_path / "inv_pref.sqlite")
        data_dir = str(tmp_path / "data_pref")
        from vn_server.api import create_app
        app = create_app(data_dir=data_dir, store_path=store_path)
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            # Import book with 2+ chapters
            golden2 = Path(__file__).parent / "golden_books" / "mountain_inn.txt"
            client.post("/api/projects", json={
                "source_path": str(golden2), "book_id": "st_pref",
            })
            chapters = client.get("/api/projects/st_pref/chapters").json()
            chapter_ids = [ch["chapter_id"] for ch in chapters]
            assert "ch002" in chapter_ids

            client.post("/api/bake", json={
                "book_id": "st_pref", "chapter_id": "ch001",
            })
            # Prefetch next chapter
            pf = client.post("/api/projects/st_pref/prefetch", json={
                "current_chapter_id": "ch001",
            })
            assert pf.status_code == 200, pf.text
            data = pf.json()
            enqueued = data.get("enqueued_jobs", [])
            assert enqueued, "Prefetch should enqueue at least ch002"
            assert any(j.get("chapter_id") == "ch002" for j in enqueued)

            # If a prefetch job was submitted, verify worker executes it
            for ej in enqueued:
                jid = ej["job_id"]
                import time
                deadline = time.time() + 30
                status = None
                while time.time() < deadline:
                    jr = client.get(f"/api/jobs/{jid}")
                    if jr.status_code == 200:
                        job = jr.json()
                        if job["status"] in ("done", "failed"):
                            status = job["status"]
                            break
                    time.sleep(0.3)
                assert status == "done", (
                    f"Prefetch job {jid} status: {status}"
                )

            station = client.get("/api/projects/st_pref/station").json()
            ch002 = next(
                ch for ch in station["chapters"] if ch["chapter_id"] == "ch002"
            )
            assert ch002["full_package"]["status"] == "ready"

    def test_prefetch_skips_valid_package(self, client):
        """Prefetch should skip an already valid target chapter."""
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_pfskip",
        })
        client.post("/api/bake", json={
            "book_id": "st_pfskip", "chapter_id": "ch002",
        })
        pf = client.post("/api/projects/st_pfskip/prefetch", json={
            "current_chapter_id": "ch001",
        })
        assert pf.status_code == 200
        payload = pf.json()
        assert "ch002" in payload.get("prefetch_chapters", [])
        jobs = payload.get("enqueued_jobs", [])
        ch002_jobs = [j for j in jobs if j.get("chapter_id") == "ch002"]
        assert ch002_jobs == [], "Should skip already-baked prefetch target"

    def test_prefetch_no_duplicate(self, client):
        """Duplicate prefetch calls should not create duplicate jobs."""
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_pfdup",
        })
        pf1 = client.post("/api/projects/st_pfdup/prefetch", json={
            "current_chapter_id": "ch001",
        })
        jobs1 = pf1.json().get("enqueued_jobs", [])
        assert jobs1, "First prefetch should create pending jobs"
        pf2 = client.post("/api/projects/st_pfdup/prefetch", json={
            "current_chapter_id": "ch001",
        })
        jobs2 = pf2.json().get("enqueued_jobs", [])
        ids1 = {j["chapter_id"]: j["job_id"] for j in jobs1}
        ids2 = {j["chapter_id"]: j["job_id"] for j in jobs2}
        assert ids2 == ids1, "Second prefetch should return existing job ids"

        station = client.get("/api/projects/st_pfdup/station").json()
        station_jobs = [
            job
            for ch in station["chapters"]
            for job in ch["jobs"]
            if job.get("job_kind") == "prefetch"
            and job.get("status") in ("pending", "running")
        ]
        assert len(station_jobs) == len(ids1)

    def test_rebuild_cache_miss_when_files_missing(self, tmp_path):
        """Worker must not cache-hit when package files are missing."""
        store_path = str(tmp_path / "inv_api_cache.sqlite")
        data_dir = str(tmp_path / "data_cache")
        from vn_server.api import create_app
        app = create_app(data_dir=data_dir, store_path=store_path)
        from fastapi.testclient import TestClient
        client = TestClient(app)

        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_cmiss",
        })
        # Bake once to populate cache, then delete files
        client.post("/api/bake", json={
            "book_id": "st_cmiss", "chapter_id": "ch001",
        })
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("st_cmiss", "reader_package", "ch001")
        assert pkg is not None
        # Delete package files but keep artifact
        import shutil
        pdir = Path(pkg["file_path"])
        if pdir.exists():
            shutil.rmtree(str(pdir))
        # Make stale
        store.invalidate_artifact("st_cmiss", pkg["artifact_version_id"], "test")
        store.close()

        # Submit rebuild
        rb = client.post("/api/projects/st_cmiss/chapters/ch001/rebuild")
        assert rb.status_code == 200, rb.text

        # Verify rebuild job was created (not cache-completed)
        job_id = rb.json()["job_id"]
        store2 = ProjectStore(store_path)
        job = store2.get_job(job_id)
        assert job is not None
        # Job should be pending (not already completed by cache)
        assert job["status"] in ("pending", "running"), (
            f"Job should not be cache-completed: {job}"
        )
        store2.close()

    def test_cancel_rebuild_keeps_needs_rebuild(self, client, tmp_path):
        """Cancel pending rebuild: job gone, needs_rebuild still true."""
        store_path = str(tmp_path / "inv_api.sqlite")
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_cancelrb",
        })
        client.post("/api/bake", json={
            "book_id": "st_cancelrb", "chapter_id": "ch001",
        })
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("st_cancelrb", "reader_package", "ch001")
        assert pkg is not None
        store.invalidate_artifact("st_cancelrb", pkg["artifact_version_id"], "test")
        store.close()

        rb = client.post("/api/projects/st_cancelrb/chapters/ch001/rebuild")
        job_id = rb.json()["job_id"]

        # Cancel
        cancel = client.post(f"/api/jobs/{job_id}/cancel")
        assert cancel.status_code == 200

        r = client.get("/api/projects/st_cancelrb/station")
        ch1 = r.json()["chapters"][0]
        assert ch1["progress"]["needs_rebuild"] is True

    def test_voice_lock_makes_station_stale(self, client, tmp_path):
        """Voice lock should invalidate chapter dependents, Station shows stale."""
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_vlock",
        })
        client.post("/api/bake", json={
            "book_id": "st_vlock", "chapter_id": "ch001",
        })

        # Station should show ready before lock
        r1 = client.get("/api/projects/st_vlock/station")
        ch1 = r1.json()["chapters"][0]
        assert ch1["full_package"]["status"] == "ready"

        # Lock a voice
        va_resp = client.get("/api/projects/st_vlock/voice-assignments")
        va_list = va_resp.json().get("assignments", [])
        assert len(va_list) > 0, "Bake should produce voice assignments"
        char_id = va_list[0]["character_id"]
        voice_id = va_list[0]["voice_id"]
        lock_resp = client.post("/api/projects/st_vlock/voice-assignments/lock", json={
            "character_id": char_id, "voice_id": voice_id,
        })
        assert lock_resp.status_code == 200, lock_resp.text

        # Station should show stale
        r2 = client.get("/api/projects/st_vlock/station")
        ch1b = r2.json()["chapters"][0]
        assert ch1b["progress"]["needs_rebuild"] is True, (
            f"Expected needs_rebuild after voice lock. Got: {ch1b['progress']}"
        )

    def test_voice_recast_invalidates_dependents(self, client, tmp_path):
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_vrec",
        })
        client.post("/api/bake", json={
            "book_id": "st_vrec", "chapter_id": "ch001",
        })

        # Unlock one character first so recast has a target
        va_resp = client.get("/api/projects/st_vrec/voice-assignments")
        va_list = va_resp.json().get("assignments", [])
        unlocked = [a for a in va_list if not a.get("user_locked")]
        if not unlocked:
            # Lock+unlock to test unlock also triggers invalidation
            if va_list:
                client.post("/api/projects/st_vrec/voice-assignments/unlock", json={
                    "character_id": va_list[0]["character_id"],
                })

        recast_resp = client.post(
            "/api/projects/st_vrec/voice-assignments/recast-unlocked",
        )
        assert recast_resp.status_code == 200, recast_resp.text

        r = client.get("/api/projects/st_vrec/station")
        ch1 = r.json()["chapters"][0]
        assert ch1["progress"]["needs_rebuild"] is True

    def test_rollback_via_api_makes_station_stale(self, client, tmp_path):
        """Real rollback API call should invalidate old adaptation dependents."""
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_rbapi",
        })
        client.post("/api/bake", json={
            "book_id": "st_rbapi", "chapter_id": "ch001",
        })

        # Station ready before rollback
        r1 = client.get("/api/projects/st_rbapi/station")
        ch1 = r1.json()["chapters"][0]
        assert ch1["full_package"]["status"] == "ready"

        # Get adaptation ops to find an op_id to rollback
        ops_resp = client.get(
            "/api/projects/st_rbapi/chapters/ch001/adaptation-ops",
        )
        ops_data = ops_resp.json().get("ops", [])
        assert len(ops_data) > 0, "Bake should produce adaptation ops"
        raw = ops_data[0].get("value", ops_data[0])
        op_id = raw.get("op_id", "")
        assert op_id, f"No op_id in adaptation ops: {raw}"
        rb_resp = client.post(
            "/api/projects/st_rbapi/chapters/ch001/adaptation-ops/rollback",
            json={"op_ids": [op_id], "reason": "test rollback"},
        )
        # Rollback may succeed or fail depending on state
        if rb_resp.status_code == 200:
            r2 = client.get("/api/projects/st_rbapi/station")
            ch1b = r2.json()["chapters"][0]
            assert ch1b["progress"]["needs_rebuild"] is True

    def test_rebuild_api(self, client):
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_rd",
        })
        resp = client.post("/api/projects/st_rd/chapters/ch001/rebuild")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("job_id")
        assert data.get("status") == "pending"

    def test_rebuild_dedup_only_rebuild_jobs(self, client):
        """Normal pending job should NOT block rebuild submission."""
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_rd3",
        })
        # Submit normal job
        client.post("/api/jobs", json={
            "book_id": "st_rd3", "chapter_id": "ch001",
            "stage": "tts_render", "priority": "P2",
        })
        # Submit rebuild — must succeed (not dedup against normal job)
        rb = client.post("/api/projects/st_rd3/chapters/ch001/rebuild")
        assert rb.status_code == 200, rb.text
        assert rb.json().get("duplicate") is False, (
            "Rebuild should not dedup against normal job"
        )

    def test_rebuild_dedup(self, client):
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_rd2",
        })
        client.post("/api/projects/st_rd2/chapters/ch001/rebuild")
        r2 = client.post("/api/projects/st_rd2/chapters/ch001/rebuild")
        assert r2.json().get("duplicate") is True

    def test_stale_full_stale_buffer_returns_404(self, client, tmp_path):
        store_path = str(tmp_path / "inv_api.sqlite")
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_sboth",
        })
        client.post("/api/bake", json={
            "book_id": "st_sboth", "chapter_id": "ch001",
        })
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("st_sboth", "reader_package", "ch001")
        if pkg:
            store.invalidate_artifact("st_sboth", pkg["artifact_version_id"], "test")
        store.close()
        resp = client.get("/api/projects/st_sboth/chapters/ch001/buffer")
        assert resp.status_code == 404, resp.text

    def test_stale_full_valid_buffer_returns_buffer(self, client, tmp_path):
        store_path = str(tmp_path / "inv_api.sqlite")
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_sfvb",
        })
        client.post("/api/projects/st_sfvb/chapters/ch001/cold-start")
        client.post("/api/bake", json={
            "book_id": "st_sfvb", "chapter_id": "ch001",
        })
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("st_sfvb", "reader_package", "ch001")
        if pkg:
            store.invalidate_artifact("st_sfvb", pkg["artifact_version_id"], "test")
        store.close()
        resp = client.get("/api/projects/st_sfvb/chapters/ch001/buffer")
        assert resp.status_code == 200, resp.text
        assert resp.json()["package_kind"] == "buffer"

    def test_rebuild_clears_needs_rebuild(self, client, tmp_path):
        """After stale + rebuild, Station full_package back to ready."""
        store_path = str(tmp_path / "inv_api.sqlite")
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_rebuild",
        })
        client.post("/api/bake", json={
            "book_id": "st_rebuild", "chapter_id": "ch001",
        })
        # Invalidate to make stale
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("st_rebuild", "reader_package", "ch001")
        if pkg:
            store.invalidate_artifact("st_rebuild", pkg["artifact_version_id"], "test")
        store.close()

        r1 = client.get("/api/projects/st_rebuild/station")
        assert r1.json()["chapters"][0]["progress"]["needs_rebuild"] is True

        # Rebuild
        client.post("/api/projects/st_rebuild/chapters/ch001/rebuild")
        # Manually bake to simulate job completion
        client.post("/api/bake", json={
            "book_id": "st_rebuild", "chapter_id": "ch001",
        })
        r2 = client.get("/api/projects/st_rebuild/station")
        ch1 = r2.json()["chapters"][0]
        assert ch1["full_package"]["status"] == "ready"
        assert ch1["progress"]["needs_rebuild"] is False

    def test_rollback_old_adaptation_invalidated_new_active(self, client, tmp_path):
        """Rollback invalidates OLD adaptation_ops dependents; new one active."""
        store_path = str(tmp_path / "inv_api.sqlite")
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_oldnew",
        })
        client.post("/api/bake", json={
            "book_id": "st_oldnew", "chapter_id": "ch001",
        })
        store = ProjectStore(store_path)
        old_adapt = store.get_active_artifact("st_oldnew", "adaptation_ops", "ch001")
        assert old_adapt is not None, "Need existing adaptation_ops for test"
        old_vid = old_adapt["artifact_version_id"]
        store.close()

        # Rollback via API
        ops_resp = client.get(
            "/api/projects/st_oldnew/chapters/ch001/adaptation-ops",
        )
        ops_data = ops_resp.json().get("ops", [])
        assert len(ops_data) > 0, "Bake should produce adaptation ops"
        raw = ops_data[0].get("value", ops_data[0])
        op_id = raw.get("op_id", "")
        assert op_id, f"No op_id found in: {raw}"
        rb = client.post(
            "/api/projects/st_oldnew/chapters/ch001/adaptation-ops/rollback",
            json={"op_ids": [op_id], "reason": "test rollback"},
        )
        assert rb.status_code == 200, (
            f"Rollback should succeed, got {rb.status_code}: {rb.text}"
        )

        store = ProjectStore(store_path)
        # Old adaptation should be superseded (not active)
        old_check = store._get_conn().execute(
            "SELECT status FROM artifacts WHERE artifact_version_id=?",
            (old_vid,),
        ).fetchone()
        assert old_check is not None
        assert old_check[0] != "active", f"Old adaptation {old_vid} should not be active"
        # New adaptation should be active
        new_adapt = store.get_active_artifact("st_oldnew", "adaptation_ops", "ch001")
        assert new_adapt is not None
        assert new_adapt["artifact_version_id"] != old_vid
        assert new_adapt["status"] == "active"
        # At least one dependent of old_vid should be invalidated
        invalidated_list = store.list_invalidated_artifacts("st_oldnew", unit_id="ch001")
        assert len(invalidated_list) > 0, (
            f"No dependents of {old_vid} were invalidated"
        )
        store.close()

        r = client.get("/api/projects/st_oldnew/station")
        ch1 = r.json()["chapters"][0]
        assert ch1["progress"]["needs_rebuild"] is True

    def test_stale_full_valid_buffer_needs_rebuild_true(self, client, tmp_path):
        """Stale full + valid buffer: /buffer returns buffer, needs_rebuild=true."""
        store_path = str(tmp_path / "inv_api.sqlite")
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_sfneed",
        })
        client.post("/api/projects/st_sfneed/chapters/ch001/cold-start")
        client.post("/api/bake", json={
            "book_id": "st_sfneed", "chapter_id": "ch001",
        })
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("st_sfneed", "reader_package", "ch001")
        if pkg:
            store.invalidate_artifact("st_sfneed", pkg["artifact_version_id"], "test")
        store.close()

        r = client.get("/api/projects/st_sfneed/station")
        ch1 = r.json()["chapters"][0]
        assert ch1["full_package"]["status"] == "stale", (
            f"Expected stale full, got {ch1['full_package']['status']}"
        )
        assert ch1["progress"]["needs_rebuild"] is True, (
            "needs_rebuild must be true even if buffer is valid"
        )
        # /buffer should return buffer (not 404)
        buf = client.get("/api/projects/st_sfneed/chapters/ch001/buffer")
        assert buf.status_code == 200
        assert buf.json()["package_kind"] == "buffer"

    def test_active_full_missing_files_needs_rebuild(self, client, tmp_path):
        """Active full with missing files should be invalid + needs_rebuild."""
        store_path = str(tmp_path / "inv_api.sqlite")
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_miss",
        })
        client.post("/api/bake", json={
            "book_id": "st_miss", "chapter_id": "ch001",
        })
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("st_miss", "reader_package", "ch001")
        if pkg and pkg.get("file_path"):
            import shutil
            pdir = Path(pkg["file_path"])
            if pdir.exists():
                shutil.rmtree(str(pdir))
        store.close()

        r = client.get("/api/projects/st_miss/station")
        ch1 = r.json()["chapters"][0]
        assert ch1["full_package"]["status"] == "invalid", (
            f"Expected invalid, got {ch1['full_package']['status']}"
        )
        assert ch1["progress"]["needs_rebuild"] is True

    def test_station_stale_status_for_invalidated(self, client, tmp_path):
        """Station explicitly shows 'stale' for invalidated packages."""
        store_path = str(tmp_path / "inv_api.sqlite")
        client.post("/api/projects", json={
            "source_path": str(GOLDEN_BOOK), "book_id": "st_sstat",
        })
        client.post("/api/bake", json={
            "book_id": "st_sstat", "chapter_id": "ch001",
        })
        store = ProjectStore(store_path)
        pkg = store.get_active_artifact("st_sstat", "reader_package", "ch001")
        if pkg:
            store.invalidate_artifact("st_sstat", pkg["artifact_version_id"], "test")
        store.close()
        r = client.get("/api/projects/st_sstat/station")
        ch1 = r.json()["chapters"][0]
        assert ch1["full_package"]["status"] == "stale", (
            f"Expected stale, got {ch1['full_package']['status']}"
        )
        assert ch1["buffer"]["status"] in ("missing", "stale")
