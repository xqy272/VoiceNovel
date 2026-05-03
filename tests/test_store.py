"""Tests for Project Store module."""


import sqlite3

import pytest

from vn_core.contracts.generation_config import GenerationConfig
from vn_core.contracts.job_state import JobStage, JobState, JobStatus
from vn_core.store import ProjectStore


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "test_project.sqlite"
    s = ProjectStore(str(db_path))
    s.initialize()
    yield s
    s.close()


class TestProjectStoreInit:
    def test_creates_database(self, store):
        conn = store._get_conn()
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {row[0] for row in tables}
        assert "artifacts" in table_names
        assert "jobs" in table_names
        assert "generation_configs" in table_names
        assert "characters" in table_names
        assert "glossary" in table_names

    def test_v2_migration_rebuilds_dependency_pk_and_paragraph_source_hint(self, tmp_path):
        db_path = tmp_path / "legacy_v1.sqlite"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            PRAGMA user_version=1;

            CREATE TABLE artifacts (
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

            CREATE TABLE artifact_dependencies (
                artifact_version_id TEXT NOT NULL,
                depends_on_artifact_version_id TEXT NOT NULL,
                dependency_role TEXT NOT NULL DEFAULT '',
                book_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (artifact_version_id, depends_on_artifact_version_id)
            );

            CREATE TABLE jobs (
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
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE paragraphs (
                book_id TEXT NOT NULL,
                chapter_id TEXT NOT NULL,
                paragraph_id TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                source_href TEXT NOT NULL DEFAULT '',
                source_order INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (book_id, paragraph_id)
            );
            """
        )
        conn.close()

        migrated = ProjectStore(str(db_path))
        migrated.initialize()
        try:
            version = migrated._get_conn().execute("PRAGMA user_version").fetchone()[0]
            assert version >= 2  # v3 adds lease columns, still >= 2

            dep_cols = migrated._get_conn().execute(
                "PRAGMA table_info(artifact_dependencies)"
            ).fetchall()
            dep_pk = {row[1]: row[5] for row in dep_cols if row[5]}
            assert dep_pk["book_id"] > 0

            paragraph_cols = {
                row[1]
                for row in migrated._get_conn().execute("PRAGMA table_info(paragraphs)")
            }
            assert "source_dom_hint" in paragraph_cols

            migrated.add_dependency("book_a", "pkg_v001", "seg_v001", "segments")
            migrated.add_dependency("book_b", "pkg_v001", "seg_v001", "segments")

            assert len(migrated.get_artifact_dependencies("book_a", "pkg_v001")) == 1
            assert len(migrated.get_artifact_dependencies("book_b", "pkg_v001")) == 1
        finally:
            migrated.close()


class TestArtifactOperations:
    def test_write_and_read_artifact(self, store):
        store.write_artifact(
            book_id="book_001",
            artifact_version_id="segver_001",
            artifact_type="segments",
            unit_id="ch001",
            input_hash="abc123",
        )
        artifact = store.get_active_artifact("book_001", "segments", "ch001")
        assert artifact is not None
        assert artifact["artifact_version_id"] == "segver_001"
        assert artifact["status"] == "active"

    def test_artifact_not_found(self, store):
        artifact = store.get_active_artifact("book_001", "segments", "ch999")
        assert artifact is None

    def test_new_active_artifact_supersedes_previous(self, store):
        store.write_artifact(
            book_id="book_001",
            artifact_version_id="segver_001",
            artifact_type="segments",
            unit_id="ch001",
        )
        store.write_artifact(
            book_id="book_001",
            artifact_version_id="segver_002",
            artifact_type="segments",
            unit_id="ch001",
        )

        active = store.get_active_artifact("book_001", "segments", "ch001")
        assert active["artifact_version_id"] == "segver_002"

        rows = store._get_conn().execute(
            "SELECT artifact_version_id, status FROM artifacts "
            "WHERE book_id=? AND artifact_type=? AND unit_id=?",
            ("book_001", "segments", "ch001"),
        ).fetchall()
        statuses = {row["artifact_version_id"]: row["status"] for row in rows}
        assert statuses["segver_001"] == "superseded"
        assert statuses["segver_002"] == "active"


class TestJobOperations:
    def test_upsert_and_get_job(self, store):
        job = JobState(
            job_id="job_001",
            stage=JobStage.tts_render,
            unit_id="ch001_p023_s002",
            status=JobStatus.pending,
        )
        store.upsert_job(job)
        retrieved = store.get_job("job_001")
        assert retrieved is not None
        assert retrieved["job_id"] == "job_001"


class TestGenerationConfigOperations:
    def test_get_default_generation_config(self, store):
        config = store.get_generation_config("book_001")
        assert config.book_id == "book_001"
        assert config.generation_config_id == "default"
        assert config.reading_profile == "enhanced"

    def test_upsert_generation_config(self, store):
        config = GenerationConfig(
            book_id="book_001",
            reading_profile="faithful",
            execution_mode="economy",
            tts_engine="mock",
            metadata={"note": "test"},
        )
        store.upsert_generation_config(config)

        retrieved = store.get_generation_config("book_001")
        assert retrieved.reading_profile == "faithful"
        assert retrieved.execution_mode == "economy"
        assert retrieved.metadata == {"note": "test"}


class TestBookModelOperations:
    def test_upsert_and_get_character(self, store):
        store.upsert_character(
            book_id="book_001",
            character_id="char_lu_ming",
            names=["陆明"],
            aliases=["少主", "陆公子"],
            traits=["male", "young_adult", "cold"],
            first_seen="ch001",
        )
        chars = store.get_characters("book_001")
        assert len(chars) >= 1
        assert chars[0]["character_id"] == "char_lu_ming"

    def test_scene_snapshot(self, store):
        store.upsert_scene_snapshot(
            book_id="book_001",
            chapter_id="ch001",
            snapshot_data={
                "active_characters": ["char_lu_ming", "char_lin_wan"],
                "last_speaker": "char_lu_ming",
                "location": "客栈房间",
            },
        )
        snapshot = store.get_scene_snapshot("book_001", "ch001")
        assert snapshot is not None
        assert "active_characters" in snapshot["snapshot_data"]


class TestArtifactSwitching:
    @pytest.fixture
    def store(self, tmp_path):
        db_path = tmp_path / "artifact_switch.sqlite"
        s = ProjectStore(str(db_path))
        s.initialize()
        yield s
        s.close()

    def test_list_artifact_versions(self, store):
        store.write_artifact("book_001", "v001", "segments", "ch001")
        store.write_artifact("book_001", "v002", "segments", "ch001")
        versions = store.list_artifact_versions("book_001", "segments", "ch001")
        assert len(versions) >= 2

    def test_list_artifact_versions_filtered(self, store):
        store.write_artifact("book_001", "v001", "segments", "ch001")
        store.write_artifact("book_001", "v002", "timing", "ch001")
        segs = store.list_artifact_versions("book_001", artifact_type="segments")
        assert len(segs) >= 1
        for s in segs:
            assert s["artifact_type"] == "segments"

    def test_activate_artifact(self, store):
        store.write_artifact("book_001", "v001", "segments", "ch001", status="active")
        store.write_artifact("book_001", "v002", "segments", "ch001", status="superseded")
        result = store.activate_artifact("book_001", "v002")
        assert result is not None
        assert result["status"] == "active"
        # v001 should now be superseded
        active = store.get_active_artifact("book_001", "segments", "ch001")
        assert active is not None
        assert active["artifact_version_id"] == "v002"

    def test_activate_nonexistent_artifact(self, store):
        result = store.activate_artifact("book_001", "nonexistent")
        assert result is None

    def test_add_and_get_dependencies(self, store):
        store.add_dependency("book_001", "v002", "v001", "depends_on")
        deps = store.get_artifact_dependencies("book_001", "v002")
        assert len(deps) == 1
        assert deps[0]["depends_on_artifact_version_id"] == "v001"

    def test_check_dependencies_active(self, store):
        store.write_artifact("book_001", "v001", "segments", "ch001", status="active")
        store.write_artifact("book_001", "v002", "timing", "ch001", status="active")
        store.add_dependency("book_001", "v002", "v001", "depends_on")
        result = store.check_dependencies_active("book_001", "v002")
        assert result["all_active"] is True
        assert len(result["inactive"]) == 0

    def test_check_dependencies_inactive(self, store):
        store.write_artifact("book_001", "v001", "segments", "ch001", status="superseded")
        store.write_artifact("book_001", "v002", "timing", "ch001", status="active")
        store.add_dependency("book_001", "v002", "v001", "depends_on")
        result = store.check_dependencies_active("book_001", "v002")
        assert result["all_active"] is False

    def test_count_artifacts_by_type(self, store):
        store.write_artifact("book_001", "v001", "segments", "ch001")
        store.write_artifact("book_001", "v002", "segments", "ch002")
        store.write_artifact("book_001", "v003", "timing", "ch001")
        counts = store.count_artifacts_by_type("book_001")
        assert counts.get("segments", 0) >= 2
        assert counts.get("timing", 0) >= 1
