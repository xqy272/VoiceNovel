# Orchestrator — AI Agent Guide

## Purpose
Job scheduling, prefetch policy, cache key computation, concurrency control, and priority queue management. The Orchestrator manages the execution order and resource allocation for pipeline jobs.

## Key Concepts
- **Execution modes**: `economy` (conservative, fewer concurrent ops) and `balanced` (moderate parallelism)
- **Prefetch policy**: Configurable chapters-ahead prefetch with hot-chapter window (keep N before, M after current)
- **Cache keys**: SHA-256 hash of all input fields for deterministic cache deduplication
- **Priority queue**: P0-P4 priority with P0 processed first

## Module: `vn_core/orchestration/`

### `ExecutionMode`
Enum: `economy`, `balanced`

### `OrchestratorConfig`
- `startup_buffer_segments: int = 40` — Minimum segments to render before playback starts
- `startup_buffer_minutes: float = 2.0` — Minimum audio duration before playback
- `prefetch_chapters_ahead: int = 2` — Chapters to prefetch ahead of current
- `keep_hot_chapters_before: int = 1` — Keep hot behind current
- `keep_hot_chapters_after: int = 3` — Keep hot ahead of current
- `max_background_jobs: int = 2` — Max concurrent background jobs
- `execution_mode: ExecutionMode = balanced`
- `max_concurrent_tts: int = 3` — Parallel TTS limit
- `max_concurrent_llm: int = 2` — Parallel LLM limit

### `Orchestrator(config, harness_gate)`

#### `compute_cache_key(**fields) -> str`
SHA-256 of `|`-joined field values, truncated to 40 chars.

#### `enqueue(job: JobState) -> str`
Add job to priority queue (sorted P0→P4). Returns job_id.

#### `process_next() -> JobState | None`
Pop highest-priority pending job.

#### `mark_done(job_id, artifact_path)` / `mark_failed(job_id, error)`
Update job completion state.

#### `get_status(job_id) -> JobState | None`
Get current job state.

## Dependencies
- `vn_core.contracts.job_state` — JobState, JobStatus
- `vn_core.harness` — HarnessGate
