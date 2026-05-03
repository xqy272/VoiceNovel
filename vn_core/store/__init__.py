"""Project Store: SQLite-backed source of truth for book artifacts, job state, and provenance."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from vn_core.contracts.generation_config import GenerationConfig
from vn_core.contracts.job_state import JobState

ARTIFACT_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS artifacts (
    book_id TEXT NOT NULL,
    artifact_version_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '0.1',
    input_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    file_path TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (book_id, artifact_version_id)
);

CREATE TABLE IF NOT EXISTS artifact_dependencies (
    book_id TEXT NOT NULL DEFAULT '',
    artifact_version_id TEXT NOT NULL,
    depends_on_artifact_version_id TEXT NOT NULL,
    dependency_role TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (book_id, artifact_version_id, depends_on_artifact_version_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL DEFAULT '',
    generation_config_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    memory_snapshot_id TEXT,
    execution_mode TEXT NOT NULL DEFAULT 'balanced',
    stage TEXT NOT NULL DEFAULT 'import',
    unit_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT NOT NULL DEFAULT 'P2',
    input_artifact_versions TEXT NOT NULL DEFAULT '[]',
    output_artifact_type TEXT NOT NULL DEFAULT '',
    input_hash TEXT NOT NULL DEFAULT '',
    cache_key TEXT NOT NULL DEFAULT '',
    cache_buster TEXT,
    artifact TEXT NOT NULL DEFAULT '',
    retry_count INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT NOT NULL DEFAULT '',
    lease_until TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS generation_configs (
    book_id TEXT NOT NULL,
    generation_config_id TEXT NOT NULL DEFAULT 'default',
    reading_profile TEXT NOT NULL DEFAULT 'enhanced',
    execution_mode TEXT NOT NULL DEFAULT 'balanced',
    tts_engine TEXT NOT NULL DEFAULT 'mock',
    cache_buster TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (book_id, generation_config_id)
);

CREATE TABLE IF NOT EXISTS provenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    generation_config_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    artifact_version_id TEXT NOT NULL DEFAULT '',
    llm_model TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    input_hash TEXT NOT NULL DEFAULT '',
    output_hash TEXT NOT NULL DEFAULT '',
    cache_key TEXT NOT NULL DEFAULT '',
    cache_buster TEXT,
    reading_profile TEXT NOT NULL DEFAULT 'enhanced',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS exceptions (
    exception_id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL,
    exception_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'open',
    unit_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT '{}',
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT
);
"""

BOOK_STRUCT_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS books (
    book_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    source_file TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chapters (
    book_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    source_file TEXT NOT NULL DEFAULT '',
    chapter_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (book_id, chapter_id)
);

CREATE TABLE IF NOT EXISTS paragraphs (
    book_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    paragraph_id TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    source_href TEXT NOT NULL DEFAULT '',
    source_order INTEGER NOT NULL DEFAULT 0,
    source_dom_hint TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (book_id, paragraph_id)
);
"""

BOOK_MODEL_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS characters (
    book_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    names TEXT NOT NULL DEFAULT '[]',
    aliases TEXT NOT NULL DEFAULT '[]',
    traits TEXT NOT NULL DEFAULT '[]',
    first_seen TEXT NOT NULL DEFAULT '',
    assigned_voice_id TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'inferred',
    evidence TEXT NOT NULL DEFAULT '[]',
    user_locked INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (book_id, character_id)
);

CREATE TABLE IF NOT EXISTS glossary (
    book_id TEXT NOT NULL,
    term TEXT NOT NULL,
    definition TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    pronunciation TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'inferred',
    evidence_segments TEXT NOT NULL DEFAULT '[]',
    created_by TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (book_id, term)
);

CREATE TABLE IF NOT EXISTS pronunciation_overrides (
    book_id TEXT NOT NULL,
    text TEXT NOT NULL,
    reading TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'tts_only',
    confidence REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'inferred',
    created_by TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (book_id, text)
);

CREATE TABLE IF NOT EXISTS decisions (
    book_id TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'inferred',
    user_locked INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '[]',
    created_by TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (book_id, segment_id, decision_type)
);

CREATE TABLE IF NOT EXISTS scene_snapshots (
    book_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    snapshot_data TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (book_id, chapter_id)
);

CREATE TABLE IF NOT EXISTS voice_assignments (
    book_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    voice_id TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    user_locked INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'auto',
    status TEXT NOT NULL DEFAULT 'inferred',
    assigned_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (book_id, character_id)
);
"""


class ProjectStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def initialize(self):
        conn = self._get_conn()
        conn.executescript(ARTIFACT_TABLES_SQL)
        conn.executescript(BOOK_STRUCT_TABLES_SQL)
        conn.executescript(BOOK_MODEL_TABLES_SQL)
        conn.commit()
        self._migrate()

    def _migrate(self):
        """Apply schema migrations incrementally based on user_version."""
        conn = self._get_conn()
        current = conn.execute("PRAGMA user_version").fetchone()[0]

        if current < 1:
            # v1: add book_id to jobs, artifact_dependencies
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN book_id TEXT NOT NULL DEFAULT ''")
            except Exception:
                pass  # column may already exist
            try:
                conn.execute(
                    "ALTER TABLE artifact_dependencies ADD COLUMN book_id TEXT NOT NULL DEFAULT ''",
                )
            except Exception:
                pass
            conn.execute("PRAGMA user_version=1")
            current = 1

        if current < 2:
            # v2: rebuild artifact_dependencies so book_id is part of the primary key,
            # and persist source_dom_hint on paragraphs.
            dep_cols = conn.execute("PRAGMA table_info(artifact_dependencies)").fetchall()
            dep_col_names = [c[1] for c in dep_cols]
            dep_pk = {c[1]: c[5] for c in dep_cols if c[5]}

            if "book_id" not in dep_col_names:
                conn.execute(
                    "ALTER TABLE artifact_dependencies ADD COLUMN book_id TEXT NOT NULL DEFAULT ''",
                )
                dep_col_names.append("book_id")

            if dep_pk.get("book_id", 0) == 0:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS artifact_dependencies_v2 (
                        book_id TEXT NOT NULL DEFAULT '',
                        artifact_version_id TEXT NOT NULL,
                        depends_on_artifact_version_id TEXT NOT NULL,
                        dependency_role TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY (
                            book_id,
                            artifact_version_id,
                            depends_on_artifact_version_id
                        )
                    )""",
                )
                conn.execute(
                    """INSERT OR REPLACE INTO artifact_dependencies_v2
                    (book_id, artifact_version_id, depends_on_artifact_version_id, dependency_role)
                    SELECT book_id, artifact_version_id, depends_on_artifact_version_id,
                           dependency_role
                    FROM artifact_dependencies""",
                )
                conn.execute("DROP TABLE artifact_dependencies")
                conn.execute("ALTER TABLE artifact_dependencies_v2 RENAME TO artifact_dependencies")

            para_cols = conn.execute("PRAGMA table_info(paragraphs)").fetchall()
            para_col_names = [c[1] for c in para_cols]
            if "source_dom_hint" not in para_col_names:
                conn.execute(
                    "ALTER TABLE paragraphs ADD COLUMN source_dom_hint TEXT NOT NULL DEFAULT ''",
                )

            conn.execute("PRAGMA user_version=2")
            current = 2

        if current < 3:
            # v3: add lease/timing columns to jobs for Store-backed Orchestrator
            v3_columns = {
                "lease_owner": "TEXT NOT NULL DEFAULT ''",
                "lease_until": "TEXT NOT NULL DEFAULT ''",
                "started_at": "TEXT NOT NULL DEFAULT ''",
                "finished_at": "TEXT NOT NULL DEFAULT ''",
                "last_error": "TEXT NOT NULL DEFAULT ''",
            }
            existing = {
                c[1] for c in conn.execute("PRAGMA table_info(jobs)").fetchall()
            }
            for col_name, col_def in v3_columns.items():
                if col_name not in existing:
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_def}")
            conn.execute("PRAGMA user_version=3")
            current = 3

        if current < 4:
            # v4: add status column to voice_assignments for lifecycle support
            va_cols = [
                c[1] for c in conn.execute("PRAGMA table_info(voice_assignments)").fetchall()
            ]
            if "status" not in va_cols:
                conn.execute(
                    """ALTER TABLE voice_assignments
                    ADD COLUMN status TEXT NOT NULL DEFAULT 'inferred'""",
                )
            conn.execute("PRAGMA user_version=4")

        conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # --- Artifact operations ---

    def write_artifact(
        self,
        book_id: str,
        artifact_version_id: str,
        artifact_type: str,
        unit_id: str,
        file_path: str = "",
        input_hash: str = "",
        schema_version: str = "0.1",
        metadata: dict | None = None,
        status: str = "active",
    ):
        conn = self._get_conn()
        if status == "active":
            conn.execute(
                """UPDATE artifacts SET status='superseded'
                WHERE book_id=? AND artifact_type=? AND unit_id=? AND status='active'
                AND artifact_version_id != ?""",
                (book_id, artifact_type, unit_id, artifact_version_id),
            )
        conn.execute(
            """INSERT OR REPLACE INTO artifacts
            (book_id, artifact_version_id, artifact_type, unit_id, schema_version,
             input_hash, status, file_path, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (book_id, artifact_version_id, artifact_type, unit_id, schema_version,
             input_hash, status, file_path, json.dumps(metadata or {})),
        )
        conn.commit()

    def add_dependency(
        self,
        book_id: str,
        artifact_version_id: str,
        depends_on_artifact_version_id: str,
        dependency_role: str = "",
    ):
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO artifact_dependencies
            (book_id, artifact_version_id, depends_on_artifact_version_id, dependency_role)
            VALUES (?, ?, ?, ?)""",
            (book_id, artifact_version_id, depends_on_artifact_version_id, dependency_role),
        )
        conn.commit()

    def get_active_artifact(self, book_id: str, artifact_type: str, unit_id: str) -> dict | None:
        conn = self._get_conn()
        row = conn.execute(
            """SELECT * FROM artifacts
            WHERE book_id=? AND artifact_type=? AND unit_id=? AND status='active'
            ORDER BY created_at DESC LIMIT 1""",
            (book_id, artifact_type, unit_id),
        ).fetchone()
        return dict(row) if row else None

    def get_current_artifact(
        self, book_id: str, artifact_type: str, unit_id: str,
    ) -> dict | None:
        """Return the most recent active or invalidated artifact for this type+unit.

        Prefers active over invalidated. Used by Station to detect stale packages
        (packages that exist but are no longer active after user actions).
        """
        conn = self._get_conn()
        # Try active first
        row = conn.execute(
            """SELECT * FROM artifacts
            WHERE book_id=? AND artifact_type=? AND unit_id=? AND status='active'
            ORDER BY created_at DESC LIMIT 1""",
            (book_id, artifact_type, unit_id),
        ).fetchone()
        if row:
            return dict(row)
        # Fall back to most recent invalidated
        row = conn.execute(
            """SELECT * FROM artifacts
            WHERE book_id=? AND artifact_type=? AND unit_id=? AND status='invalidated'
            ORDER BY created_at DESC LIMIT 1""",
            (book_id, artifact_type, unit_id),
        ).fetchone()
        return dict(row) if row else None

    # --- Job operations ---

    def upsert_job(self, job: JobState):
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO jobs
            (job_id, book_id, generation_config_id, run_id, memory_snapshot_id,
             execution_mode, stage, unit_id, status, priority, input_artifact_versions,
             output_artifact_type, input_hash, cache_key, cache_buster, artifact, retry_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job.job_id, job.book_id, job.generation_config_id, job.run_id,
             job.memory_snapshot_id, job.execution_mode, job.stage.value, job.unit_id,
             job.status.value, job.priority, json.dumps(job.input_artifact_versions),
             job.output_artifact_type, job.input_hash, job.cache_key, job.cache_buster,
             job.artifact, job.retry_count),
        )
        conn.commit()

    def get_job(self, job_id: str) -> dict | None:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    # --- Store-backed job queue (lease-based) ---

    def lease_next_job(
        self, worker_id: str, lease_seconds: int = 300,
    ) -> dict | None:
        """Atomically lease the highest-priority pending (or expired) job.

        Uses BEGIN IMMEDIATE to prevent concurrent workers from claiming
        the same job. Returns the job dict or None if queue is empty.
        """
        import datetime as _dt
        conn = self._get_conn()
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()

        conn.execute("BEGIN IMMEDIATE")
        try:
            # Recover stale leases: reset to pending, clear lease fields only
            conn.execute(
                """UPDATE jobs SET status='pending', lease_owner='', lease_until=''
                WHERE status='running' AND lease_until < ? AND lease_until != ''""",
                (now,),
            )
            # Find next pending job by priority, then age
            row = conn.execute(
                """SELECT * FROM jobs
                WHERE status='pending'
                ORDER BY
                    CASE priority
                        WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2
                        WHEN 'P3' THEN 3 WHEN 'P4' THEN 4 ELSE 2
                    END,
                    created_at
                LIMIT 1""",
            ).fetchone()
            if not row:
                conn.execute("ROLLBACK")
                return None

            job = dict(row)
            lease_until = (
                _dt.datetime.now(_dt.timezone.utc)
                + _dt.timedelta(seconds=lease_seconds)
            ).isoformat()
            conn.execute(
                """UPDATE jobs SET status='running', lease_owner=?,
                lease_until=?, started_at=?
                WHERE job_id=?""",
                (worker_id, lease_until, now, job["job_id"]),
            )
            conn.commit()
            job["status"] = "running"
            job["lease_owner"] = worker_id
            job["lease_until"] = lease_until
            job["started_at"] = now
            return job
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def complete_job(self, job_id: str, artifact_path: str = "", lease_owner: str = ""):
        """Mark job as done. Only transitions from 'running'.

        If lease_owner is provided, only completes the job if it's still owned
        by the same worker (prevents cancelled jobs from being overwritten).
        """
        from datetime import datetime as dt
        from datetime import timezone as tz
        conn = self._get_conn()
        if lease_owner:
            conn.execute(
                """UPDATE jobs SET status='done', finished_at=?, artifact=?
                WHERE job_id=? AND status='running' AND lease_owner=?""",
                (dt.now(tz.utc).isoformat(), artifact_path, job_id, lease_owner),
            )
        else:
            conn.execute(
                """UPDATE jobs SET status='done', finished_at=?, artifact=?
                WHERE job_id=? AND status='running'""",
                (dt.now(tz.utc).isoformat(), artifact_path, job_id),
            )
        conn.commit()

    def fail_job(self, job_id: str, error: str = "", lease_owner: str = ""):
        """Mark job as failed. Only transitions from 'running'.

        If lease_owner is provided, only fails the job if it's still owned
        by the same worker. For API-initiated cancel, omit lease_owner to
        force-fail regardless of owner.
        """
        from datetime import datetime as dt
        from datetime import timezone as tz
        conn = self._get_conn()
        if lease_owner:
            conn.execute(
                """UPDATE jobs SET status='failed', finished_at=?, last_error=?
                WHERE job_id=? AND status='running' AND lease_owner=?""",
                (dt.now(tz.utc).isoformat(), error, job_id, lease_owner),
            )
        else:
            # API cancel: force transition from any non-terminal status
            conn.execute(
                """UPDATE jobs SET status='failed', finished_at=?, last_error=?
                WHERE job_id=? AND status IN ('pending', 'running')""",
                (dt.now(tz.utc).isoformat(), error, job_id),
            )
        conn.commit()

    def update_job_retry_count(self, job_id: str, count: int):
        """Set the retry_count to an exact value."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE jobs SET retry_count=? WHERE job_id=?", (count, job_id),
        )
        conn.commit()

    def requeue_job(self, job_id: str):
        """Reset a failed job back to pending for manual retry.

        Clears lease fields and error but preserves retry_count history.
        """
        conn = self._get_conn()
        conn.execute(
            """UPDATE jobs SET status='pending', lease_owner='', lease_until='',
            started_at='', finished_at='', last_error=''
            WHERE job_id=?""",
            (job_id,),
        )
        conn.commit()

    def find_duplicate_job(
        self, book_id: str, stage: str, unit_id: str,
        cache_key: str = "", cache_buster_prefix: str = "",
    ) -> dict | None:
        """Check if a job with the same identity is already pending or running."""
        conn = self._get_conn()
        query = """SELECT * FROM jobs WHERE book_id=? AND stage=? AND unit_id=?
        AND status IN ('pending', 'running')"""
        params: list = [book_id, stage, unit_id]
        if cache_key:
            query += " AND cache_key=?"
            params.append(cache_key)
        if cache_buster_prefix:
            query += " AND cache_buster LIKE ?"
            params.append(f"{cache_buster_prefix}%")
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def list_jobs(
        self, book_id: str = "", status: str = "", unit_id: str = "",
        limit: int = 50,
    ) -> list[dict]:
        """List jobs with optional filters."""
        conn = self._get_conn()
        query = "SELECT * FROM jobs WHERE 1=1"
        params: list = []
        if book_id:
            query += " AND book_id=?"
            params.append(book_id)
        if status:
            query += " AND status=?"
            params.append(status)
        if unit_id:
            query += " AND unit_id=?"
            params.append(unit_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def find_artifact_by_cache_key(
        self, book_id: str, artifact_type: str, cache_key: str,
    ) -> dict | None:
        """Find an active artifact by its cache key for reuse."""
        conn = self._get_conn()
        row = conn.execute(
            """SELECT * FROM artifacts
            WHERE book_id=? AND artifact_type=? AND status='active'
            AND input_hash=? ORDER BY created_at DESC LIMIT 1""",
            (book_id, artifact_type, cache_key),
        ).fetchone()
        return dict(row) if row else None

    def get_job_stats(self, book_id: str = "") -> dict:
        """Get aggregated job counts by status."""
        conn = self._get_conn()
        query = """SELECT status, COUNT(*) as cnt FROM jobs"""
        params: list = []
        if book_id:
            query += " WHERE book_id=?"
            params.append(book_id)
        query += " GROUP BY status"
        rows = conn.execute(query, params).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    # --- Generation config operations ---

    def upsert_generation_config(self, config: GenerationConfig):
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO generation_configs
            (book_id, generation_config_id, reading_profile, execution_mode,
             tts_engine, cache_buster, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(book_id, generation_config_id) DO UPDATE SET
                reading_profile=excluded.reading_profile,
                execution_mode=excluded.execution_mode,
                tts_engine=excluded.tts_engine,
                cache_buster=excluded.cache_buster,
                metadata=excluded.metadata,
                updated_at=datetime('now')""",
            (
                config.book_id,
                config.generation_config_id,
                config.reading_profile,
                config.execution_mode,
                config.tts_engine,
                config.cache_buster,
                json.dumps(config.metadata, ensure_ascii=False),
            ),
        )
        conn.commit()

    def get_generation_config(
        self,
        book_id: str,
        generation_config_id: str = "default",
    ) -> GenerationConfig:
        conn = self._get_conn()
        row = conn.execute(
            """SELECT * FROM generation_configs
            WHERE book_id=? AND generation_config_id=?""",
            (book_id, generation_config_id),
        ).fetchone()
        if not row:
            return GenerationConfig(
                book_id=book_id,
                generation_config_id=generation_config_id,
            )
        data = dict(row)
        data["metadata"] = json.loads(data.get("metadata") or "{}")
        return GenerationConfig(**data)

    def generation_config_exists(
        self, book_id: str, generation_config_id: str = "default",
    ) -> bool:
        """Return True if the generation config row exists, False otherwise."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT 1 FROM generation_configs WHERE book_id=? AND generation_config_id=?",
            (book_id, generation_config_id),
        ).fetchone()
        return row is not None

    # --- Book structure operations ---

    def upsert_book(self, book_id: str, title: str = "", source_file: str = ""):
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO books (book_id, title, source_file) VALUES (?, ?, ?)""",
            (book_id, title, source_file),
        )
        conn.commit()

    def upsert_chapter(self, book_id: str, chapter_id: str, title: str = "",
                       source_file: str = "", chapter_order: int = 0):
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO chapters
            (book_id, chapter_id, title, source_file, chapter_order)
            VALUES (?, ?, ?, ?, ?)""",
            (book_id, chapter_id, title, source_file, chapter_order),
        )
        conn.commit()

    def upsert_paragraph(
        self,
        book_id: str,
        chapter_id: str,
        paragraph_id: str,
        text: str,
        source_href: str = "",
        source_order: int = 0,
        source_dom_hint: str = "",
    ):
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO paragraphs
            (book_id, chapter_id, paragraph_id, text, source_href, source_order, source_dom_hint)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                book_id,
                chapter_id,
                paragraph_id,
                text,
                source_href,
                source_order,
                source_dom_hint,
            ),
        )
        conn.commit()

    def get_chapters(self, book_id: str) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM chapters WHERE book_id=? ORDER BY chapter_order",
            (book_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_paragraphs(self, book_id: str, chapter_id: str) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM paragraphs WHERE book_id=? AND chapter_id=? ORDER BY source_order",
            (book_id, chapter_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_book(self, book_id: str) -> dict | None:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM books WHERE book_id=?", (book_id,)).fetchone()
        return dict(row) if row else None

    # --- Book Model operations ---

    def upsert_character(self, book_id: str, character_id: str, names: list[str],
                         aliases: list[str] | None = None, traits: list[str] | None = None,
                         first_seen: str = "", assigned_voice_id: str = "",
                         confidence: float = 1.0, status: str = "inferred",
                         evidence: list[str] | None = None, created_by: str = "",
                         run_id: str = ""):
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO characters
            (book_id, character_id, names, aliases, traits, first_seen,
             assigned_voice_id, confidence, status, evidence, created_by, run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (book_id, character_id, json.dumps(names), json.dumps(aliases or []),
             json.dumps(traits or []), first_seen, assigned_voice_id, confidence,
             status, json.dumps(evidence or []), created_by, run_id),
        )
        conn.commit()

    def get_characters(self, book_id: str) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM characters WHERE book_id=?", (book_id,)).fetchall()
        return [dict(r) for r in rows]

    def upsert_decision(self, book_id: str, segment_id: str, decision_type: str,
                        value: dict | None = None, confidence: float = 1.0,
                        status: str = "inferred", user_locked: bool = False,
                        source: str = "", evidence: list[str] | None = None,
                        created_by: str = "", run_id: str = ""):
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO decisions
            (book_id, segment_id, decision_type, value, confidence, status,
             user_locked, source, evidence, created_by, run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (book_id, segment_id, decision_type, json.dumps(value or {}),
             confidence, status, int(user_locked), source,
             json.dumps(evidence or []), created_by, run_id),
        )
        conn.commit()

    def get_scene_snapshot(self, book_id: str, chapter_id: str) -> dict | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM scene_snapshots WHERE book_id=? AND chapter_id=?",
            (book_id, chapter_id),
        ).fetchone()
        if row:
            data = dict(row)
            data["snapshot_data"] = json.loads(data.get("snapshot_data", "{}"))
            return data
        return None

    def upsert_scene_snapshot(self, book_id: str, chapter_id: str,
                              snapshot_data: dict, created_by: str = "", run_id: str = ""):
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO scene_snapshots
            (book_id, chapter_id, snapshot_data, created_by, run_id)
            VALUES (?, ?, ?, ?, ?)""",
            (book_id, chapter_id, json.dumps(snapshot_data, ensure_ascii=False),
             created_by, run_id),
        )
        conn.commit()

    def upsert_voice_assignment(self, book_id: str, character_id: str,
                                voice_id: str, confidence: float = 1.0,
                                user_locked: bool = False, source: str = "auto",
                                status: str = "inferred"):
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO voice_assignments
            (book_id, character_id, voice_id, confidence, user_locked, source, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (book_id, character_id, voice_id, confidence, int(user_locked), source, status),
        )
        conn.commit()

    def get_voice_assignment(self, book_id: str, character_id: str) -> dict | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM voice_assignments WHERE book_id=? AND character_id=?",
            (book_id, character_id),
        ).fetchone()
        return dict(row) if row else None

    def list_voice_assignments(self, book_id: str, status: str | None = None) -> list[dict]:
        conn = self._get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM voice_assignments WHERE book_id=? AND status=?",
                (book_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM voice_assignments WHERE book_id=?",
                (book_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def set_voice_assignment_status(
        self, book_id: str, character_id: str, status: str,
    ):
        conn = self._get_conn()
        conn.execute(
            "UPDATE voice_assignments SET status=? WHERE book_id=? AND character_id=?",
            (status, book_id, character_id),
        )
        conn.commit()

    def recast_unlocked_voice_assignments(
        self, book_id: str, cast_fn,
    ) -> list[dict]:
        """Re-cast voice assignments for all unlocked characters.

        ``cast_fn`` is a callable ``(character_id, traits) -> (voice_id, confidence)``.
        Returns list of updated assignment dicts.
        """
        conn = self._get_conn()
        unlocked = conn.execute(
            """SELECT * FROM voice_assignments
            WHERE book_id=? AND user_locked=0""",
            (book_id,),
        ).fetchall()
        results = []
        for row in unlocked:
            char_id = row["character_id"]
            # Get character traits for scoring
            char_row = conn.execute(
                "SELECT traits FROM characters WHERE book_id=? AND character_id=?",
                (book_id, char_id),
            ).fetchone()
            traits_raw = char_row["traits"] if char_row else "[]"
            import json as _json
            traits = _json.loads(traits_raw) if isinstance(traits_raw, str) else traits_raw
            new_voice_id, confidence = cast_fn(char_id, traits)
            conn.execute(
                """UPDATE voice_assignments SET voice_id=?, confidence=?, status=?,
                source='auto' WHERE book_id=? AND character_id=? AND user_locked=0""",
                (new_voice_id, confidence, "inferred", book_id, char_id),
            )
            results.append(dict(conn.execute(
                "SELECT * FROM voice_assignments WHERE book_id=? AND character_id=?",
                (book_id, char_id),
            ).fetchone()))
        conn.commit()
        return results

    # --- Active artifact switching ---

    def invalidate_artifact(
        self, book_id: str, artifact_version_id: str, reason: str = "",
    ) -> bool:
        """Mark an artifact as invalidated (keeps provenance, doesn't delete)."""
        conn = self._get_conn()
        import datetime as _dt
        # Read current metadata, merge invalidation info
        row = conn.execute(
            "SELECT metadata FROM artifacts WHERE book_id=? AND artifact_version_id=?",
            (book_id, artifact_version_id),
        ).fetchone()
        if not row:
            return False
        try:
            meta = json.loads(row[0] or "{}")
        except (TypeError, json.JSONDecodeError):
            meta = {}
        meta["invalidated_reason"] = reason
        meta["invalidated_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
        cursor = conn.execute(
            """UPDATE artifacts SET status='invalidated', metadata=?
            WHERE book_id=? AND artifact_version_id=?
            AND status IN ('active', 'superseded')""",
            (json.dumps(meta), book_id, artifact_version_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def invalidate_dependents(
        self, book_id: str, changed_artifact_version_id: str,
        reason: str = "", recursive: bool = True,
    ) -> list[str]:
        """Invalidate all direct dependents of *changed_artifact_version_id*.

        If *recursive*, transitively follows the dependency chain.
        Returns a list of invalidated artifact_version_ids.
        """
        conn = self._get_conn()
        invalidated: list[str] = []
        queue = [changed_artifact_version_id]
        seen = {changed_artifact_version_id}
        while queue:
            current = queue.pop(0)
            deps = conn.execute(
                """SELECT artifact_version_id FROM artifact_dependencies
                WHERE book_id=? AND depends_on_artifact_version_id=?""",
                (book_id, current),
            ).fetchall()
            for (dep_vid,) in deps:
                if dep_vid in seen:
                    continue
                seen.add(dep_vid)
                if recursive:
                    queue.append(dep_vid)
                if self.invalidate_artifact(book_id, dep_vid, reason):
                    invalidated.append(dep_vid)
        return invalidated

    def chapter_needs_rebuild(self, book_id: str, unit_id: str) -> bool:
        """True when the chapter's reader_package is missing, stale, has broken
        deps, or has missing files — even if a playable buffer exists.

        ``needs_rebuild`` means: a full reader_package should be (re)generated.
        A valid buffer keeps ``playable=True`` but does not suppress rebuild.
        """
        from pathlib import Path as _Path
        cur_pkg = self.get_current_artifact(book_id, "reader_package", unit_id)
        if not cur_pkg:
            return True  # no full package at all
        if cur_pkg.get("status") != "active":
            return True  # stale, invalidated, or superseded
        dep_ok = self.check_dependencies_active(book_id, cur_pkg["artifact_version_id"])
        if not dep_ok["all_active"]:
            return True
        # Check files exist on disk
        pkg_dir = cur_pkg.get("file_path", "")
        if not pkg_dir or not _Path(pkg_dir).exists():
            return True
        required = ["cleaned.html", "timing.json", "manifest.json"]
        if not all((_Path(pkg_dir) / f).exists() for f in required):
            return True
        return False

    def list_invalidated_artifacts(
        self, book_id: str, unit_id: str = "",
    ) -> list[dict]:
        """List invalidated (stale) artifacts, optionally filtered by unit."""
        conn = self._get_conn()
        query = "SELECT * FROM artifacts WHERE book_id=? AND status='invalidated'"
        params: list = [book_id]
        if unit_id:
            query += " AND unit_id=?"
            params.append(unit_id)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def list_artifact_versions(
        self, book_id: str, artifact_type: str | None = None, unit_id: str | None = None,
    ) -> list[dict]:
        """List all artifact versions, optionally filtered by type and unit."""
        conn = self._get_conn()
        query = "SELECT * FROM artifacts WHERE book_id=?"
        params: list = [book_id]
        if artifact_type:
            query += " AND artifact_type=?"
            params.append(artifact_type)
        if unit_id:
            query += " AND unit_id=?"
            params.append(unit_id)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def activate_artifact(
        self, book_id: str, artifact_version_id: str,
    ) -> dict | None:
        """Explicitly set a specific artifact version as active.

        Supersedes the current active artifact of the same type and unit.
        Returns the activated artifact or None if not found.
        """
        conn = self._get_conn()
        artifact = conn.execute(
            "SELECT * FROM artifacts WHERE book_id=? AND artifact_version_id=?",
            (book_id, artifact_version_id),
        ).fetchone()
        if not artifact:
            return None

        art = dict(artifact)
        # Supersede current active of same type + unit
        conn.execute(
            """UPDATE artifacts SET status='superseded'
            WHERE book_id=? AND artifact_type=? AND unit_id=? AND status='active'
            AND artifact_version_id != ?""",
            (book_id, art["artifact_type"], art["unit_id"], artifact_version_id),
        )
        # Activate target
        conn.execute(
            "UPDATE artifacts SET status='active' WHERE book_id=? AND artifact_version_id=?",
            (book_id, artifact_version_id),
        )
        conn.commit()
        return dict(conn.execute(
            "SELECT * FROM artifacts WHERE book_id=? AND artifact_version_id=?",
            (book_id, artifact_version_id),
        ).fetchone())

    def get_artifact_dependencies(
        self, book_id: str, artifact_version_id: str,
    ) -> list[dict]:
        """Get all dependencies for an artifact version, scoped to a book."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM artifact_dependencies
            WHERE book_id=? AND artifact_version_id=?""",
            (book_id, artifact_version_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def check_dependencies_active(
        self, book_id: str, artifact_version_id: str,
    ) -> dict:
        """Check if all dependencies of an artifact are active.

        Returns ``{"all_active": bool, "inactive": list[dict]}``.
        """
        deps = self.get_artifact_dependencies(book_id, artifact_version_id)
        inactive = []
        conn = self._get_conn()
        for dep in deps:
            dep_id = dep["depends_on_artifact_version_id"]
            row = conn.execute(
                """SELECT status FROM artifacts
                WHERE book_id=? AND artifact_version_id=?""",
                (book_id, dep_id),
            ).fetchone()
            if not row or row[0] != "active":
                inactive.append(dep)
        return {"all_active": len(inactive) == 0, "inactive": inactive}

    def write_text_adaptation_ops(
        self,
        book_id: str,
        unit_id: str,
        operations: list,
        created_by: str = "pipeline",
    ):
        """Persist text adaptation operations for a segment or paragraph."""
        conn = self._get_conn()
        import json as _json
        for op in operations:
            data = op.model_dump() if hasattr(op, "model_dump") else op
            conn.execute(
                """INSERT OR REPLACE INTO decisions
                (book_id, segment_id, decision_type, value, confidence, status,
                 user_locked, source, evidence, created_by, run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    book_id,
                    data.get("segment_id", unit_id),
                    f"text_adaptation:{data.get('op_id', unit_id)}",
                    _json.dumps(data, ensure_ascii=False),
                    data.get("confidence", 0.99),
                    "inferred",
                    0,
                    data.get("source", "rule"),
                    _json.dumps(data.get("evidence", [])),
                    created_by,
                    "",
                ),
            )
        conn.commit()

    def get_text_adaptation_ops(
        self, book_id: str, unit_id: str = "", segment_id: str = "",
    ) -> list[dict]:
        """Query text adaptation operations from decisions table.

        Returns ops ordered by segment_id then source_order for stability.
        """
        conn = self._get_conn()
        query = """SELECT * FROM decisions
        WHERE book_id=? AND decision_type LIKE 'text_adaptation%'"""
        params: list = [book_id]
        if unit_id:
            query += " AND segment_id LIKE ?"
            params.append(f"{unit_id}%")
        if segment_id:
            query += " AND segment_id=?"
            params.append(segment_id)
        query += " ORDER BY segment_id, rowid"
        rows = conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["value"] = json.loads(d.get("value", "{}"))
            except (TypeError, json.JSONDecodeError):
                pass
            results.append(d)
        return results

    def count_artifacts_by_type(self, book_id: str) -> dict[str, int]:
        """Count active artifacts by type for a book."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT artifact_type, COUNT(*) as cnt
            FROM artifacts WHERE book_id=? AND status='active'
            GROUP BY artifact_type""",
            (book_id,),
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    # --- Exception queue management ---

    def list_exceptions(
        self,
        book_id: str = "",
        status: str = "",
        exception_type: str = "",
        unit_id: str = "",
        limit: int = 100,
    ) -> list[dict]:
        """Query exceptions, optionally filtered by book, status, type, and unit."""
        conn = self._get_conn()
        query = "SELECT * FROM exceptions WHERE 1=1"
        params: list = []
        if book_id:
            query += " AND book_id=?"
            params.append(book_id)
        if status:
            query += " AND status=?"
            params.append(status)
        if exception_type:
            query += " AND exception_type=?"
            params.append(exception_type)
        if unit_id:
            query += " AND unit_id=?"
            params.append(unit_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_exception(self, exception_id: str) -> dict | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM exceptions WHERE exception_id=?",
            (exception_id,),
        ).fetchone()
        return dict(row) if row else None

    def update_exception_status(
        self, exception_id: str, status: str, resolved_at: str | None = None,
    ):
        """Transition an exception to a new status."""
        conn = self._get_conn()
        import datetime as _dt2
        if resolved_at is None and status in ("auto_resolved", "user_resolved"):
            resolved_at = _dt2.datetime.now(_dt2.timezone.utc).isoformat()
        conn.execute(
            "UPDATE exceptions SET status=?, resolved_at=? WHERE exception_id=?",
            (status, resolved_at, exception_id),
        )
        conn.commit()

    def increment_exception_retry(self, exception_id: str) -> int:
        """Increment retry_count for an exception and return the new count."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE exceptions SET retry_count=retry_count+1 WHERE exception_id=?",
            (exception_id,),
        )
        conn.commit()
        row = conn.execute(
            "SELECT retry_count FROM exceptions WHERE exception_id=?",
            (exception_id,),
        ).fetchone()
        return row[0] if row else 0

    def get_exception_count(self, book_id: str = "", status: str = "open") -> int:
        """Count exceptions matching criteria."""
        conn = self._get_conn()
        query = "SELECT COUNT(*) FROM exceptions WHERE 1=1"
        params: list = []
        if book_id:
            query += " AND book_id=?"
            params.append(book_id)
        if status:
            query += " AND status=?"
            params.append(status)
        row = conn.execute(query, params).fetchone()
        return row[0] if row else 0

    def write_exception(
        self,
        book_id: str,
        exception_type: str,
        message: str,
        *,
        unit_id: str = "",
        stage: str = "",
        severity: str = "medium",
        details: dict | None = None,
    ) -> str:
        """Insert an exception directly and return its exception_id."""
        import uuid as _uuid
        conn = self._get_conn()
        exc_id = f"exc_{_uuid.uuid4().hex[:12]}"
        conn.execute(
            """INSERT INTO exceptions
            (exception_id, book_id, exception_type, severity,
             status, unit_id, stage, message, details)
            VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
            (exc_id, book_id, exception_type, severity,
             unit_id, stage, message,
             json.dumps(details or {})),
        )
        conn.commit()
        return exc_id
