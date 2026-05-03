"""Tests for Orchestrator module."""

from vn_core.contracts.job_state import JobStage, JobState, JobStatus
from vn_core.orchestration import ExecutionMode, Orchestrator, OrchestratorConfig


class TestOrchestratorConfig:
    def test_default_config(self):
        config = OrchestratorConfig()
        assert config.startup_buffer_segments == 40
        assert config.execution_mode == ExecutionMode.balanced

    def test_economy_mode(self):
        config = OrchestratorConfig(execution_mode=ExecutionMode.economy)
        assert config.execution_mode == ExecutionMode.economy


class TestOrchestrator:
    def test_enqueue_job(self):
        orch = Orchestrator()
        job = JobState(job_id="job_001", stage=JobStage.tts_render, unit_id="ch001")
        job_id = orch.enqueue(job)
        assert job_id == "job_001"

    def test_enqueue_priority_ordering(self):
        orch = Orchestrator()
        job_p2 = JobState(
            job_id="job_p2",
            stage=JobStage.tts_render,
            unit_id="ch001",
            priority="P2",
        )
        job_p0 = JobState(
            job_id="job_p0",
            stage=JobStage.tts_render,
            unit_id="ch002",
            priority="P0",
        )
        orch.enqueue(job_p2)
        orch.enqueue(job_p0)
        next_job = orch.process_next()
        assert next_job.job_id == "job_p0"

    def test_process_next_empty(self):
        orch = Orchestrator()
        assert orch.process_next() is None

    def test_mark_done(self):
        orch = Orchestrator()
        job = JobState(job_id="job_001", stage=JobStage.tts_render, unit_id="ch001")
        orch._completed["job_001"] = job
        orch.mark_done("job_001", artifact_path="/tmp/out.wav")
        assert orch._completed["job_001"].status == JobStatus.done

    def test_compute_cache_key(self):
        orch = Orchestrator()
        key1 = orch.compute_cache_key(text="hello", voice="v1")
        key2 = orch.compute_cache_key(text="hello", voice="v1")
        key3 = orch.compute_cache_key(text="world", voice="v1")
        assert key1 == key2
        assert key1 != key3
