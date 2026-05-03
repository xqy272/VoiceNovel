"""Orchestrator tests: queue, execution, retry, prefetch, and progress events."""

import asyncio

import pytest

from vn_core.contracts.job_state import JobStage, JobState, JobStatus
from vn_core.orchestration import Orchestrator, OrchestratorConfig


class TestOrchestratorQueue:
    @pytest.fixture
    def orch(self):
        return Orchestrator(config=OrchestratorConfig(max_background_jobs=2))

    def test_enqueue_returns_job_id(self, orch):
        job = JobState(
            job_id="test_job_001", stage=JobStage.tts_render,
            unit_id="ch001", status=JobStatus.pending,
        )
        jid = orch.enqueue(job)
        assert jid == "test_job_001"
        assert orch.pending_count() == 1

    def test_process_next_returns_highest_priority(self, orch):
        p0 = JobState(job_id="p0", stage=JobStage.tts_render, unit_id="u1",
                      status=JobStatus.pending, priority="P0")
        p2 = JobState(job_id="p2", stage=JobStage.tts_render, unit_id="u2",
                      status=JobStatus.pending, priority="P2")
        orch.enqueue(p2)
        orch.enqueue(p0)
        next_job = orch.process_next()
        assert next_job.job_id == "p0"
        assert orch.pending_count() == 1

    def test_process_next_empty_queue(self, orch):
        assert orch.process_next() is None

    def test_pending_count(self, orch):
        job = JobState(job_id="j1", stage=JobStage.tts_render, unit_id="u1",
                       status=JobStatus.pending)
        orch.enqueue(job)
        assert orch.pending_count() == 1

    def test_running_count(self, orch):
        assert orch.running_count() == 0

    def test_mark_done_and_get_status(self, orch):
        job = JobState(job_id="j1", stage=JobStage.tts_render, unit_id="u1",
                       status=JobStatus.pending)
        orch.enqueue(job)
        orch.mark_done("j1", artifact_path="/tmp/test")
        status = orch.get_status("j1")
        assert status is not None
        assert status.status == JobStatus.done
        assert status.artifact == "/tmp/test"

    def test_mark_failed(self, orch):
        job = JobState(job_id="j_fail", stage=JobStage.tts_render, unit_id="u1",
                       status=JobStatus.pending)
        orch.enqueue(job)
        orch.mark_failed("j_fail", error="something broke")
        status = orch.get_status("j_fail")
        assert status.status == JobStatus.failed

    def test_get_stats(self, orch):
        stats = orch.get_stats()
        assert stats["pending"] == 0
        assert stats["running"] == 0
        assert stats["completed"] == 0
        assert stats["failed"] == 0
        assert "max_concurrent" in stats


class TestOrchestratorExecutor:
    @pytest.fixture
    def orch(self):
        return Orchestrator(config=OrchestratorConfig(
            max_background_jobs=2, job_timeout_seconds=5,
            max_retries=0,  # no retries for deterministic testing
        ))

    @pytest.mark.asyncio
    async def test_executor_success(self, orch):
        events = []

        async def track(event_type, data):
            events.append((event_type, data))

        orch.on_progress(track)

        async def good_executor(job):
            return {"success": True, "artifact": "/tmp/ok", "errors": []}

        orch.set_executor(good_executor)

        job = JobState(job_id="j_ok", stage=JobStage.tts_render, unit_id="ch001",
                       status=JobStatus.pending)
        orch.enqueue(job)

        # Run one cycle manually
        next_job = orch.process_next()
        assert next_job is not None
        await orch._execute_job(next_job)

        status = orch.get_status("j_ok")
        assert status.status == JobStatus.done
        assert any(e[0] == "job_completed" for e in events)

    @pytest.mark.asyncio
    async def test_executor_failure(self, orch):
        events = []

        async def track(event_type, data):
            events.append((event_type, data))

        orch.on_progress(track)

        async def bad_executor(job):
            return {"success": False, "artifact": "", "errors": ["test error"]}

        orch.set_executor(bad_executor)

        job = JobState(job_id="j_bad", stage=JobStage.tts_render, unit_id="ch001",
                       status=JobStatus.pending)
        orch.enqueue(job)

        next_job = orch.process_next()
        await orch._execute_job(next_job)

        status = orch.get_status("j_bad")
        assert status.status == JobStatus.failed
        assert any(e[0] == "job_failed" for e in events)

    @pytest.mark.asyncio
    async def test_executor_no_executor(self, orch):
        job = JobState(job_id="j_noexec", stage=JobStage.tts_render, unit_id="ch001",
                       status=JobStatus.pending)
        orch.enqueue(job)
        next_job = orch.process_next()
        await orch._execute_job(next_job)
        status = orch.get_status("j_noexec")
        assert status.status == JobStatus.failed

    @pytest.mark.asyncio
    async def test_executor_timeout(self, orch):
        async def slow_executor(job):
            await asyncio.sleep(10)
            return {"success": True, "artifact": "", "errors": []}

        orch.set_executor(slow_executor)

        job = JobState(job_id="j_slow", stage=JobStage.tts_render, unit_id="ch001",
                       status=JobStatus.pending)
        orch.enqueue(job)
        next_job = orch.process_next()
        await orch._execute_job(next_job)

        status = orch.get_status("j_slow")
        assert status.status == JobStatus.failed

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, orch):
        orch = Orchestrator(config=OrchestratorConfig(
            max_background_jobs=2, max_retries=2, retry_delay_seconds=0.01,
            job_timeout_seconds=5,
        ))
        events = []

        async def track(event_type, data):
            events.append((event_type, data))

        orch.on_progress(track)

        attempt_count = 0

        async def flaky_executor(job):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                return {"success": False, "artifact": "", "errors": ["flaky"]}
            return {"success": True, "artifact": "/tmp/eventually", "errors": []}

        orch.set_executor(flaky_executor)

        job = JobState(job_id="j_flaky", stage=JobStage.tts_render, unit_id="ch001",
                       status=JobStatus.pending)
        orch.enqueue(job)
        next_job = orch.process_next()
        await orch._execute_job(next_job)

        assert attempt_count == 3
        status = orch.get_status("j_flaky")
        assert status.status == JobStatus.done
        assert any(e[0] == "job_retrying" for e in events)


class TestOrchestratorPrefetch:
    @pytest.fixture
    def orch(self):
        return Orchestrator(config=OrchestratorConfig(
            prefetch_chapters_ahead=2,
            keep_hot_chapters_before=1,
            keep_hot_chapters_after=3,
        ))

    def test_compute_prefetch_plan(self, orch):
        all_chapters = ["ch001", "ch002", "ch003", "ch004", "ch005"]
        plan = orch.compute_prefetch_plan("ch002", all_chapters)
        assert plan == ["ch003", "ch004"]

    def test_compute_prefetch_plan_at_end(self, orch):
        all_chapters = ["ch001", "ch002"]
        plan = orch.compute_prefetch_plan("ch002", all_chapters)
        assert plan == []

    def test_compute_prefetch_plan_unknown_chapter(self, orch):
        plan = orch.compute_prefetch_plan("nonexistent", ["ch001"])
        assert plan == []

    def test_get_hot_window(self, orch):
        all_chapters = ["ch001", "ch002", "ch003", "ch004", "ch005"]
        before, after = orch.get_hot_window("ch003", all_chapters)
        assert before == ["ch002"]
        assert "ch004" in after

    def test_get_hot_window_at_start(self, orch):
        all_chapters = ["ch001", "ch002", "ch003"]
        before, after = orch.get_hot_window("ch001", all_chapters)
        assert before == []
        assert "ch002" in after


class TestOrchestratorCacheKey:
    def test_compute_cache_key_deterministic(self):
        k1 = Orchestrator.compute_cache_key(foo="bar", baz=42)
        k2 = Orchestrator.compute_cache_key(foo="bar", baz=42)
        assert k1 == k2

    def test_compute_cache_key_different(self):
        k1 = Orchestrator.compute_cache_key(x="a")
        k2 = Orchestrator.compute_cache_key(x="b")
        assert k1 != k2

    def test_compute_cache_key_skips_none(self):
        k1 = Orchestrator.compute_cache_key(a="x", b=None)
        k2 = Orchestrator.compute_cache_key(a="x")
        assert k1 == k2


class TestOrchestratorLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        orch = Orchestrator(config=OrchestratorConfig(max_background_jobs=1))
        events = []

        async def track(event_type, data):
            events.append(event_type)

        orch.on_progress(track)
        await orch.start()
        assert "worker_started" in events
        await orch.stop()
        assert "worker_stopped" in events


class TestStoreBackedOrchestrator:
    """Tests that exercise the real Store-backed path (with lease, recovery, dedup)."""

    @pytest.fixture
    def store(self, tmp_path):
        from vn_core.store import ProjectStore
        db = tmp_path / "orch_store.sqlite"
        s = ProjectStore(str(db))
        s.initialize()
        yield s
        s.close()

    @pytest.mark.asyncio
    async def test_enqueue_and_lease(self, store):
        orch = Orchestrator(store=store, config=OrchestratorConfig(lease_seconds=10))
        job = JobState(
            job_id="j_lease_001", book_id="book_001",
            stage=JobStage.tts_render, unit_id="ch001",
            status=JobStatus.pending, cache_key="test_ck_001",
        )
        orch.enqueue(job)

        # Lease the job
        leased = store.lease_next_job("test_worker", lease_seconds=10)
        assert leased is not None
        assert leased["job_id"] == "j_lease_001"
        assert leased["status"] == "running"
        assert leased["lease_owner"] == "test_worker"

        # Second worker should NOT get the same job
        leased2 = store.lease_next_job("other_worker", lease_seconds=10)
        assert leased2 is None

    @pytest.mark.asyncio
    async def test_stale_lease_recovery(self, store):
        orch = Orchestrator(store=store, config=OrchestratorConfig(lease_seconds=1))
        job = JobState(
            job_id="j_stale_001", book_id="book_001",
            stage=JobStage.tts_render, unit_id="ch001",
            status=JobStatus.pending, cache_key="stale_ck",
        )
        orch.enqueue(job)

        # Lease with very short TTL
        leased = store.lease_next_job("worker_a", lease_seconds=0)
        assert leased is not None

        # Immediately, another worker should recover the stale lease
        leased2 = store.lease_next_job("worker_b", lease_seconds=60)
        assert leased2 is not None
        assert leased2["job_id"] == "j_stale_001"
        assert leased2["lease_owner"] == "worker_b"

    @pytest.mark.asyncio
    async def test_dedup_pending_job(self, store):
        orch = Orchestrator(store=store, config=OrchestratorConfig())
        job1 = JobState(
            job_id="j_dedup_001", book_id="book_001",
            stage=JobStage.tts_render, unit_id="ch001",
            status=JobStatus.pending, cache_key="dedup_ck",
        )
        job2 = JobState(
            job_id="j_dedup_002", book_id="book_001",
            stage=JobStage.tts_render, unit_id="ch001",
            status=JobStatus.pending, cache_key="dedup_ck",
        )
        jid1 = orch.enqueue(job1)
        jid2 = orch.enqueue(job2)
        assert jid1 == jid2  # second enqueue returns the first job's ID

    @pytest.mark.asyncio
    async def test_complete_and_fail(self, store):
        orch = Orchestrator(store=store, config=OrchestratorConfig())
        job = JobState(
            job_id="j_cf_001", book_id="book_001",
            stage=JobStage.tts_render, unit_id="ch001",
            status=JobStatus.pending,
        )
        orch.enqueue(job)

        # Lease first (sets status=running), then complete
        leased = store.lease_next_job("worker_test", lease_seconds=60)
        assert leased is not None

        store.complete_job("j_cf_001", artifact_path="/tmp/test.wav",
                           lease_owner="worker_test")
        result = store.get_job("j_cf_001")
        assert result["status"] == "done"
        assert result["artifact"] == "/tmp/test.wav"
        assert result["finished_at"] != ""

    @pytest.mark.asyncio
    async def test_requeue_and_fail(self, store):
        orch = Orchestrator(store=store, config=OrchestratorConfig())
        job = JobState(
            job_id="j_rf_001", book_id="book_001",
            stage=JobStage.tts_render, unit_id="ch001",
            status=JobStatus.pending,
        )
        orch.enqueue(job)

        # Lease, then fail
        store.lease_next_job("worker_test", lease_seconds=60)
        store.fail_job("j_rf_001", "test error", lease_owner="worker_test")
        result = store.get_job("j_rf_001")
        assert result["status"] == "failed"
        assert result["last_error"] == "test error"

        # Requeue: back to pending, retry_count preserved
        store.update_job_retry_count("j_rf_001", 2)
        store.requeue_job("j_rf_001")
        result2 = store.get_job("j_rf_001")
        assert result2["status"] == "pending"
        assert result2["retry_count"] == 2  # preserved through requeue
        assert result2["last_error"] == ""  # cleared

    @pytest.mark.asyncio
    async def test_list_and_stats(self, store):
        orch = Orchestrator(store=store, config=OrchestratorConfig())
        for i in range(3):
            orch.enqueue(JobState(
                job_id=f"j_list_{i}", book_id="book_001",
                stage=JobStage.tts_render, unit_id=f"ch00{i}",
                status=JobStatus.pending,
            ))

        jobs = store.list_jobs(book_id="book_001")
        assert len(jobs) >= 3

        stats = orch.get_stats()
        assert stats["pending"] >= 3

    @pytest.mark.asyncio
    async def test_cache_key_artifact_lookup(self, store):
        store.write_artifact("book_001", "cache_v001", "audio_take", "ch001",
                             input_hash="abc123", file_path="/tmp/audio.wav")
        found = store.find_artifact_by_cache_key("book_001", "audio_take", "abc123")
        assert found is not None
        assert found["artifact_version_id"] == "cache_v001"

        not_found = store.find_artifact_by_cache_key("book_001", "audio_take", "no_match")
        assert not_found is None

    @pytest.mark.asyncio
    async def test_cache_hit_respects_artifact_type(self, store):
        """output_artifact_type='audio_take' should find audio_take, not reader_package."""
        store.write_artifact("book_001", "rp_v1", "reader_package", "ch001",
                             input_hash="same_hash", file_path="/tmp/rp")
        store.write_artifact("book_001", "at_v1", "audio_take", "ch001",
                             input_hash="same_hash", file_path="/tmp/at")
        # Searching for 'audio_take' with same_hash should return the audio_take artifact
        found = store.find_artifact_by_cache_key("book_001", "audio_take", "same_hash")
        assert found is not None
        assert found["artifact_type"] == "audio_take"
        assert found["artifact_version_id"] == "at_v1"

    @pytest.mark.asyncio
    async def test_cancel_pending_job_not_leased(self, store):
        """Cancel a pending job — it should become failed and never be leased."""
        job = JobState(
            job_id="j_cancel_pending", book_id="book_001",
            stage=JobStage.tts_render, unit_id="ch001",
            status=JobStatus.pending,
        )
        store.upsert_job(job)
        store.fail_job("j_cancel_pending", "cancelled by user")  # API cancel: no lease_owner
        result = store.get_job("j_cancel_pending")
        assert result["status"] == "failed"
        assert result["last_error"] == "cancelled by user"

        # Should not be leased since it's failed
        leased = store.lease_next_job("worker_x", lease_seconds=10)
        assert leased is None

    @pytest.mark.asyncio
    async def test_cancel_running_job_not_overwritten_by_complete(self, store):
        """Complete should NOT overwrite a job that was already cancelled."""
        job = JobState(
            job_id="j_cancel_race", book_id="book_001",
            stage=JobStage.tts_render, unit_id="ch001",
            status=JobStatus.pending,
        )
        store.upsert_job(job)
        # Worker A leases it
        store.lease_next_job("worker_a", lease_seconds=60)
        # API cancel (no lease_owner = force)
        store.fail_job("j_cancel_race", "cancelled by user")
        # Worker A tries to complete — must be rejected
        store.complete_job("j_cancel_race", "/tmp/done.wav", lease_owner="worker_a")
        result = store.get_job("j_cancel_race")
        assert result["status"] == "failed"  # NOT done
        assert result["last_error"] == "cancelled by user"

    @pytest.mark.asyncio
    async def test_retry_count_semantics(self, store):
        """retry_count should equal actual retries: 2 failures then success = 2."""
        job = JobState(
            job_id="j_retry_sem", book_id="book_001",
            stage=JobStage.tts_render, unit_id="ch001",
            status=JobStatus.pending,
        )
        store.upsert_job(job)
        store.lease_next_job("worker_r", lease_seconds=60)

        # Simulate: attempt 0 fails, retry_count -> 1
        store.update_job_retry_count("j_retry_sem", 1)
        # Simulate: attempt 1 fails, retry_count -> 2
        store.update_job_retry_count("j_retry_sem", 2)
        # Simulate: attempt 2 succeeds
        r = store.get_job("j_retry_sem")
        assert r["retry_count"] == 2
        store.complete_job("j_retry_sem", "/tmp/ok.wav", lease_owner="worker_r")
        final = store.get_job("j_retry_sem")
        assert final["status"] == "done"
        assert final["retry_count"] == 2

    @pytest.mark.asyncio
    async def test_lease_renewal_preserves_owner(self, store):
        """Only current lease_owner can renew; old owner cannot steal."""
        job = JobState(
            job_id="j_renew_001", book_id="book_001",
            stage=JobStage.tts_render, unit_id="ch001",
            status=JobStatus.pending,
        )
        store.upsert_job(job)
        store.lease_next_job("worker_a", lease_seconds=5)

        # worker_a renews — should work
        import datetime
        ts = datetime.datetime.now(
            datetime.timezone.utc,
        ) + datetime.timedelta(seconds=30)
        new_until = ts.isoformat()
        store._get_conn().execute(
            "UPDATE jobs SET lease_until=? WHERE job_id=? AND lease_owner=?",
            (new_until, "j_renew_001", "worker_a"),
        )
        store._get_conn().commit()

        # worker_b tries to renew — should NOT match
        store._get_conn().execute(
            "UPDATE jobs SET lease_until=? WHERE job_id=? AND lease_owner=?",
            (new_until, "j_renew_001", "worker_b"),
        )
        store._get_conn().commit()
        # Job should still be owned by worker_a (lease_until updated only for worker_a's call)
        result = store.get_job("j_renew_001")
        assert result["lease_owner"] == "worker_a"

    @pytest.mark.asyncio
    async def test_cache_miss_on_inactive_dependency(self, store):
        """Cache hit should miss if artifact dependency is not active."""
        # Write segments artifact (inactive)
        store.write_artifact("book_001", "seg_v1", "segments", "ch001",
                             status="superseded")
        # Write reader_package with cache key
        ck = "test_ck_dep_001"
        store.write_artifact("book_001", "rp_v1", "reader_package", "ch001",
                             input_hash=ck, file_path="/tmp/rp")

        # Add dependency from rp_v1 -> seg_v1 (inactive)
        store.add_dependency("book_001", "rp_v1", "seg_v1", "depends_on")

        # Cache lookup finds rp_v1 but deps not all active -> should miss
        cached = store.find_artifact_by_cache_key("book_001", "reader_package", ck)
        assert cached is not None  # artifact exists
        dep_ok = store.check_dependencies_active("book_001", "rp_v1")
        assert dep_ok["all_active"] is False  # dependency is NOT active


class TestRebuildCacheBypass:
    """Orchestrator must bypass cache for rebuild jobs (cache_buster starts with 'rebuild:')."""

    @pytest.fixture
    def store(self, tmp_path):
        from vn_core.store import ProjectStore
        db = tmp_path / "rcb.sqlite"
        s = ProjectStore(str(db))
        s.initialize()
        yield s
        s.close()

    @pytest.mark.asyncio
    async def test_normal_job_hits_cache(self, store):
        """Normal job with active artifact hits cache — executor NOT called."""
        # Write active reader_package with valid files including audio
        pkg_dir = store.db_path.parent / "rcb_pkg"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        for f in ["cleaned.html", "timing.json", "manifest.json"]:
            (pkg_dir / f).write_text("{}")
        (pkg_dir / "audio").mkdir(exist_ok=True)
        (pkg_dir / "audio" / "test.wav").write_text("fake wav")
        ck = "normal_cache_key_001"
        store.write_artifact("book_001", "rp_v1", "reader_package", "ch001",
                             input_hash=ck, file_path=str(pkg_dir))

        orch = Orchestrator(store=store, config=OrchestratorConfig(max_retries=0))
        job = JobState(
            job_id="j_normal", book_id="book_001",
            stage=JobStage.tts_render, unit_id="ch001",
            status=JobStatus.running, cache_key=ck,
            output_artifact_type="reader_package",
        )

        executor_called = []
        async def _exec(j):
            executor_called.append(j.job_id)
            return {"success": True, "artifact": "/tmp/x", "errors": []}
        orch.set_executor(_exec)

        await orch._execute_job(job)
        assert len(executor_called) == 0, "Executor should NOT be called on cache hit"

    @pytest.mark.asyncio
    async def test_rebuild_job_bypasses_cache(self, store):
        """Rebuild job must NOT cache-hit even with valid active artifact."""
        pkg_dir = store.db_path.parent / "rcb_rebuild"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        for f in ["cleaned.html", "timing.json", "manifest.json"]:
            (pkg_dir / f).write_text("{}")
        ck = "rebuild_cache_key_002"
        store.write_artifact("book_001", "rp_v1", "reader_package", "ch001",
                             input_hash=ck, file_path=str(pkg_dir))

        orch = Orchestrator(store=store, config=OrchestratorConfig(max_retries=0))
        job = JobState(
            job_id="j_rebuild", book_id="book_001",
            stage=JobStage.tts_render, unit_id="ch001",
            status=JobStatus.running, cache_key=ck,
            cache_buster="rebuild:abc12345",
            output_artifact_type="reader_package",
        )

        executor_called = []
        async def _exec(j):
            executor_called.append(j.job_id)
            return {"success": True, "artifact": "/tmp/new", "errors": []}
        orch.set_executor(_exec)

        await orch._execute_job(job)
        assert len(executor_called) == 1, (
            f"Rebuild executor MUST be called. Calls: {len(executor_called)}"
        )
        assert executor_called[0] == "j_rebuild"
