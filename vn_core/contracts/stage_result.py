"""StageResult: unified return structure for all pipeline stages.

Services compute, never write Store directly. They return a StageResult,
and the Harness Gate handles validation, commit, and provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StageResult:
    """Result from a pipeline stage — proposed artifacts and side effects.

    A stage MUST NOT write to Store directly. It returns this structure,
    and the Orchestrator/Harness Gate performs the actual writes.
    """

    stage: str = ""
    book_id: str = ""
    unit_id: str = ""

    # Proposed artifacts: list of (artifact_type, data, file_path, input_hash)
    proposed_artifacts: list[dict] = field(default_factory=list)

    # Dependencies: (artifact_version_id, depends_on_version_id, role)
    dependencies: list[tuple[str, str, str]] = field(default_factory=list)

    # Memory patches: Book Model mutations
    memory_patches: list[dict] = field(default_factory=list)

    # Decisions: per-segment pipeline decisions
    decisions: list[dict] = field(default_factory=list)

    # Exceptions: issues that need attention
    exceptions: list[dict] = field(default_factory=list)

    # Provenance: one record per stage
    provenance: dict | None = None

    # Metrics: timing, token usage, etc.
    metrics: dict = field(default_factory=dict)

    # Whether this stage result represents a success
    success: bool = True
    errors: list[str] = field(default_factory=list)
