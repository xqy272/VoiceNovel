"""Orchestrator: Store-backed job scheduling with lease, recovery, and concurrency control.

All job state lives in the Project Store (SQLite). The Orchestrator uses
``BEGIN IMMEDIATE`` leases so that only one worker processes a job at a time.
Stale leases are auto-recovered on each poll cycle.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Coroutine

from vn_core.contracts.job_state import JobState, JobStatus
from vn_core.harness import HarnessGate
from vn_core.store import ProjectStore


class ExecutionMode(str, Enum):
    economy = "economy"
    balanced = "balanced"


@dataclass
class OrchestratorConfig:
    startup_buffer_segments: int = 40
    startup_buffer_minutes: float = 2.0
    prefetch_chapters_ahead: int = 2
    keep_hot_chapters_before: int = 1
    keep_hot_chapters_after: int = 3
    max_background_jobs: int = 2
    execution_mode: ExecutionMode = ExecutionMode.balanced
    max_concurrent_tts: int = 3
    max_concurrent_llm: int = 2
    worker_poll_interval_ms: int = 100
    job_timeout_seconds: int = 600
    max_retries: int = 1
    retry_delay_seconds: float = 1.0
    lease_seconds: int = 300
    worker_id: str = ""


ProgressCallback = Callable[[str, dict], Coroutine[Any, Any, None]]


class Orchestrator:
    """Store-backed job scheduler with lease-based execution and crash recovery.

    All job state is persisted in the Project Store. Workers acquire jobs via
    ``BEGIN IMMEDIATE`` leases. On restart, stale leases (past ``lease_until``)
    are reset to ``pending`` so unfinished work is recovered.
    """

    def __init__(
        self,
        store: ProjectStore | None = None,
        config: OrchestratorConfig | None = None,
        harness_gate: HarnessGate | None = None,
    ):
        self.store = store  # required for Store-backed mode
        self.config = config or OrchestratorConfig()
        self.config.worker_id = self.config.worker_id or f"worker_{uuid.uuid4().hex[:8]}"
        self.harness = harness_gate or HarnessGate()
        self._running: dict[str, asyncio.Task] = {}
        self._progress_callbacks: list[ProgressCallback] = []
        self._semaphore: asyncio.Semaphore | None = None
        self._worker_task: asyncio.Task | None = None
        self._executor: Callable[[JobState], Coroutine[Any, Any, dict]] | None = None
        self._running_flag = False
        # Memory fallback: used only when no Store is configured (tests)
        self._pending: deque[JobState] = deque()
        self._completed: dict[str, JobState] = {}
        self._failed: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Progress events
    # ------------------------------------------------------------------

    def on_progress(self, callback: ProgressCallback):
        self._progress_callbacks.append(callback)

    async def _emit(self, event_type: str, data: dict):
        for cb in self._progress_callbacks:
            try:
                await cb(event_type, data)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Executor
    # ------------------------------------------------------------------

    def set_executor(self, executor: Callable[[JobState], Coroutine[Any, Any, dict]]):
        self._executor = executor

    # ------------------------------------------------------------------
    # Cache key
    # ------------------------------------------------------------------

    @staticmethod
    def compute_cache_key(**fields: Any) -> str:
        content = "|".join(str(v) for v in fields.values() if v is not None)
        return hashlib.sha256(content.encode()).hexdigest()[:40]

    # ------------------------------------------------------------------
    # Store-backed enqueue (with dedup)
    # ------------------------------------------------------------------

    def enqueue(self, job: JobState) -> str:
        """Write job to Store. Falls back to in-memory queue if no Store."""
        if self.store:
            dup = self.store.find_duplicate_job(
                job.book_id, job.stage.value, job.unit_id, job.cache_key,
            )
            if dup:
                return dup["job_id"]
            self.store.upsert_job(job)
        else:
            # Memory fallback for tests
            self._pending.append(job)
            self._completed[job.job_id] = job
        return job.job_id

    # For test compatibility — pops from memory queue when no Store
    def process_next(self) -> JobState | None:
        if not self._pending:
            return None
        self._pending = deque(
            sorted(
                self._pending,
                key=lambda j: {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}.get(j.priority, 2),
            )
        )
        return self._pending.popleft()

    # For test compatibility — marks complete in memory
    def mark_done(self, job_id: str, artifact_path: str = ""):
        if job_id in self._completed:
            self._completed[job_id].status = JobStatus.done
            self._completed[job_id].artifact = artifact_path
        self._running.pop(job_id, None)

    def mark_failed(self, job_id: str, error: str = ""):
        if job_id in self._completed:
            self._completed[job_id].status = JobStatus.failed
        self._failed[job_id] = error
        self._running.pop(job_id, None)

    # ------------------------------------------------------------------
    # Status helpers (delegated to Store)
    # ------------------------------------------------------------------

    def pending_count(self) -> int:
        if not self.store:
            return len(self._pending)
        stats = self.store.get_job_stats()
        return stats.get("pending", 0)

    def running_count(self) -> int:
        return len(self._running)

    def get_status(self, job_id: str):
        if self.store:
            return self.store.get_job(job_id)
        return self._completed.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job by cancelling its asyncio task and writing to Store."""
        task = self._running.get(job_id)
        if task and not task.done():
            task.cancel()
        if self.store:
            self.store.fail_job(job_id, "cancelled by user")
        else:
            self.mark_failed(job_id, "cancelled by user")
        self._running.pop(job_id, None)
        return True

    def get_stats(self) -> dict:
        if not self.store:
            return {
                "pending": len(self._pending),
                "running": len(self._running),
                "completed": sum(1 for j in self._completed.values() if j.status == JobStatus.done),
                "failed": sum(1 for j in self._completed.values() if j.status == JobStatus.failed),
                "max_concurrent": self.config.max_background_jobs,
            }
        s = self.store.get_job_stats()
        return {
            "pending": s.get("pending", 0),
            "running": s.get("running", 0),
            "completed": s.get("done", 0),
            "failed": s.get("failed", 0),
            "max_concurrent": self.config.max_background_jobs,
        }

    # ------------------------------------------------------------------
    # Worker loop (Store-backed, lease-based)
    # ------------------------------------------------------------------

    async def start(self):
        if self._worker_task is not None:
            return
        self._running_flag = True
        self._semaphore = asyncio.Semaphore(self.config.max_background_jobs)
        self._worker_task = asyncio.ensure_future(self._worker_loop())
        await self._emit("worker_started", {
            "worker_id": self.config.worker_id,
            "max_jobs": self.config.max_background_jobs,
        })

    async def stop(self):
        self._running_flag = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        if self._running:
            remaining = list(self._running.values())
            try:
                await asyncio.wait_for(
                    asyncio.gather(*remaining, return_exceptions=True),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                pass
            self._running.clear()
        await self._emit("worker_stopped", {"stats": self.get_stats()})

    async def _worker_loop(self):
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.config.max_background_jobs)

        while self._running_flag:
            if not self.store:
                await asyncio.sleep(self.config.worker_poll_interval_ms / 1000)
                continue

            # Acquire capacity BEFORE leasing — don't claim jobs we can't run
            await self._semaphore.acquire()

            # Lease next job from Store (includes stale-lease recovery)
            job_dict = self.store.lease_next_job(
                self.config.worker_id, self.config.lease_seconds,
            )
            if job_dict is None:
                self._semaphore.release()
                await asyncio.sleep(self.config.worker_poll_interval_ms / 1000)
                continue

            # Reconstruct full JobState from DB row
            import json as _json

            from vn_core.contracts.job_state import JobStage
            input_versions_raw = job_dict.get("input_artifact_versions", "[]")
            if isinstance(input_versions_raw, str):
                try:
                    input_versions = _json.loads(input_versions_raw)
                except (TypeError, _json.JSONDecodeError):
                    input_versions = []
            else:
                input_versions = input_versions_raw if isinstance(input_versions_raw, list) else []
            job = JobState(
                job_id=job_dict["job_id"],
                book_id=job_dict.get("book_id", ""),
                stage=JobStage(job_dict.get("stage", "tts_render")),
                unit_id=job_dict.get("unit_id", ""),
                status=JobStatus.running,
                priority=job_dict.get("priority", "P2"),
                generation_config_id=job_dict.get("generation_config_id", ""),
                execution_mode=job_dict.get("execution_mode", "balanced"),
                cache_key=job_dict.get("cache_key", ""),
                input_hash=job_dict.get("input_hash", ""),
                retry_count=job_dict.get("retry_count", 0),
                output_artifact_type=job_dict.get("output_artifact_type", ""),
                input_artifact_versions=input_versions,
                cache_buster=job_dict.get("cache_buster"),
                artifact=job_dict.get("artifact", ""),
                run_id=job_dict.get("run_id", ""),
                memory_snapshot_id=job_dict.get("memory_snapshot_id"),
            )

            async def _run(j: JobState):
                try:
                    await self._execute_job(j)
                finally:
                    self._semaphore.release()

            task = asyncio.ensure_future(_run(job))
            self._running[job.job_id] = task

    def _record_success(self, job_id: str, artifact: str = ""):
        """Persist job completion. Guards against overwriting a cancelled job."""
        if self.store:
            self.store.complete_job(job_id, artifact, self.config.worker_id)
        else:
            self.mark_done(job_id, artifact)

    def _record_failure(self, job_id: str, error: str = ""):
        """Persist job failure. Guards against overwriting a cancelled job."""
        if self.store:
            self.store.fail_job(job_id, error, self.config.worker_id)
        else:
            self.mark_failed(job_id, error)

    async def _execute_job(self, job: JobState):
        job_id = job.job_id
        started_at = time.time()

        await self._emit("job_started", {
            "job_id": job_id, "stage": job.stage.value, "unit_id": job.unit_id,
            "book_id": job.book_id,
        })

        if self._executor is None:
            err = "No executor registered"
            await self._emit("job_failed", {"job_id": job_id, "error": err})
            self._record_failure(job_id, err)
            self._running.pop(job_id, None)
            return

        # Rebuild jobs (cache_buster starts with "rebuild:") bypass cache entirely
        is_rebuild = bool(
            job.cache_buster and str(job.cache_buster).startswith("rebuild:")
        )

        # Task-level cache: skip execution if artifact with same cache_key exists
        # AND its dependencies are all still active — unless this is a rebuild.
        if not is_rebuild and self.store and job.cache_key:
            out_type = job.output_artifact_type or "reader_package"
            cached = self.store.find_artifact_by_cache_key(
                job.book_id, out_type, job.cache_key,
            )
            if cached:
                cached_vid = cached["artifact_version_id"]
                dep_ok = self.store.check_dependencies_active(job.book_id, cached_vid)
                if dep_ok["all_active"]:
                    # For reader_package, verify required files exist
                    if out_type == "reader_package":
                        pkg_dir = cached.get("file_path", "")
                        if not pkg_dir:
                            pass
                        else:
                            p = __import__("pathlib").Path(pkg_dir)
                            required = ["cleaned.html", "timing.json", "manifest.json"]
                            if not p.exists() or not all(
                                (p / f).exists() for f in required
                            ):
                                pass  # missing files → fall through
                            else:
                                # Also verify audio directory has at least one file
                                adir = p / "audio"
                                if not adir.exists() or not (
                                    any(adir.glob("*.wav"))
                                    or any(adir.glob("*.mp3"))
                                ):
                                    pass  # missing audio → fall through
                                else:
                                    await self._emit("job_completed", {
                                        "job_id": job_id, "stage": job.stage.value,
                                        "unit_id": job.unit_id, "cached": True,
                                        "artifact_version_id": cached_vid,
                                    })
                                    self._record_success(
                                        job_id, cached.get("file_path", ""),
                                    )
                                    self._running.pop(job_id, None)
                                    return
                    else:
                        await self._emit("job_completed", {
                            "job_id": job_id, "stage": job.stage.value,
                            "unit_id": job.unit_id, "cached": True,
                            "artifact_version_id": cached_vid,
                        })
                        self._record_success(job_id, cached.get("file_path", ""))
                        self._running.pop(job_id, None)
                        return

        # Background lease renewal: keep lease_until fresh during long execution
        renew_task: asyncio.Task | None = None

        async def _renew_lease():
            while True:
                await asyncio.sleep(max(self.config.lease_seconds / 2, 10))
                if self.store:
                    import datetime
                    new_until = (
                        datetime.datetime.utcnow()
                        + datetime.timedelta(seconds=self.config.lease_seconds)
                    ).isoformat()
                    self.store._get_conn().execute(
                        """UPDATE jobs SET lease_until=?
                        WHERE job_id=? AND lease_owner=?""",
                        (new_until, job_id, self.config.worker_id),
                    )
                    self.store._get_conn().commit()

        if self.store:
            renew_task = asyncio.ensure_future(_renew_lease())

        last_error = ""
        try:
            for attempt in range(self.config.max_retries + 1):
                try:
                    result = await asyncio.wait_for(
                        self._executor(job),
                        timeout=self.config.job_timeout_seconds,
                    )
                    elapsed_ms = (time.time() - started_at) * 1000

                    if result.get("success"):
                        await self._emit("job_completed", {
                            "job_id": job_id, "stage": job.stage.value,
                            "unit_id": job.unit_id,
                            "artifact": result.get("artifact", ""),
                            "elapsed_ms": elapsed_ms, "attempts": attempt + 1,
                        })
                        self._record_success(job_id, result.get("artifact", ""))
                        self._running.pop(job_id, None)
                        return
                    else:
                        errors = result.get("errors", ["unknown error"])
                        last_error = "; ".join(errors)
                        # retry_count = number of retries already done (not counting first attempt)
                        if attempt < self.config.max_retries:
                            if self.store:
                                self.store.update_job_retry_count(job_id, attempt + 1)
                            await self._emit("job_retrying", {
                                "job_id": job_id, "attempt": attempt + 1,
                                "max_retries": self.config.max_retries,
                                "error": last_error,
                            })
                            await asyncio.sleep(self.config.retry_delay_seconds)
                            continue
                        if self.store:
                            self.store.update_job_retry_count(job_id, attempt)
                        await self._emit("job_failed", {
                            "job_id": job_id, "errors": errors,
                            "elapsed_ms": elapsed_ms, "attempts": attempt + 1,
                        })
                        self._record_failure(job_id, last_error)
                        self._running.pop(job_id, None)
                        return

                except asyncio.TimeoutError:
                    last_error = f"Timeout after {self.config.job_timeout_seconds}s"
                    if attempt < self.config.max_retries:
                        if self.store:
                            self.store.update_job_retry_count(job_id, attempt + 1)
                        await self._emit("job_retrying", {
                            "job_id": job_id, "attempt": attempt + 1,
                            "error": last_error,
                        })
                        await asyncio.sleep(self.config.retry_delay_seconds)
                        continue
                    if self.store:
                        self.store.update_job_retry_count(job_id, attempt)
                    await self._emit("job_failed", {"job_id": job_id, "error": last_error})
                    self._record_failure(job_id, last_error)
                    self._running.pop(job_id, None)
                    return

                except asyncio.CancelledError:
                    await self._emit("job_failed", {"job_id": job_id, "error": "cancelled"})
                    self._record_failure(job_id, "cancelled")
                    self._running.pop(job_id, None)
                    return

                except Exception as exc:
                    last_error = str(exc)
                    if attempt < self.config.max_retries:
                        if self.store:
                            self.store.update_job_retry_count(job_id, attempt + 1)
                        await self._emit("job_retrying", {
                            "job_id": job_id, "attempt": attempt + 1,
                            "error": last_error,
                        })
                        await asyncio.sleep(self.config.retry_delay_seconds)
                        continue
                    if self.store:
                        self.store.update_job_retry_count(job_id, attempt)
                    await self._emit("job_failed", {"job_id": job_id, "error": last_error})
                    self._record_failure(job_id, last_error)
                    self._running.pop(job_id, None)
                    return
        finally:
            if renew_task:
                renew_task.cancel()
                try:
                    await renew_task
                except asyncio.CancelledError:
                    pass

    # ------------------------------------------------------------------
    # Prefetch scheduling
    # ------------------------------------------------------------------

    def compute_prefetch_plan(
        self, current_chapter_id: str, all_chapter_ids: list[str],
    ) -> list[str]:
        try:
            cur_idx = all_chapter_ids.index(current_chapter_id)
        except ValueError:
            return []
        ahead = self.config.prefetch_chapters_ahead
        start = cur_idx + 1
        end = min(start + ahead, len(all_chapter_ids))
        return all_chapter_ids[start:end]

    def get_hot_window(
        self, current_chapter_id: str, all_chapter_ids: list[str],
    ) -> tuple[list[str], list[str]]:
        try:
            cur_idx = all_chapter_ids.index(current_chapter_id)
        except ValueError:
            return [], []
        before_start = max(0, cur_idx - self.config.keep_hot_chapters_before)
        hot_before = all_chapter_ids[before_start:cur_idx]
        after_end = min(
            cur_idx + self.config.keep_hot_chapters_after + 1,
            len(all_chapter_ids),
        )
        hot_after = all_chapter_ids[cur_idx + 1 : after_end]
        return hot_before, hot_after
